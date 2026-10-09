#!/usr/bin/env python3
"""Publish a small deterministic Register snapshot for Herald.

This is deliberately not an AI step. Register already owns project state; this
module exposes only the small amount Herald needs for the 07:00 attention layer:

* which projects changed since the previous daily snapshot;
* which OPEN items are new since that snapshot;
* the first current NEXT item for changed projects;
* whether derived Register state is still behind a handoff; and
* the newest whole-estate Gemini review.

The previous JSON file is the comparison baseline. On the first run it creates a
baseline without declaring every existing OPEN item to be new.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import register
import checkpoints

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
ESTATE_DIR = register.VAULT_PATH / register.PROJECTS_DIR / "_estate"
DEFAULT_OUTPUT = ESTATE_DIR / "herald-status.json"
MAX_SECTION_ITEMS = 12

# CTX/2 top-level section markers. Keep this list in sync with Register's
# deterministic context format; unknown future sections safely end the current
# section when they are all-caps tokens.
CTX_SECTIONS = {
    "GOAL", "STACK", "ARCH", "FILES", "STATE", "DONE", "CORRECTIONS", "DEC",
    "INV", "BUG", "OPEN", "NEXT", "REJECTED", "FACTS",
}


def _iso(ts: float | int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(timespec="seconds")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def _item_id(project: str, text: str) -> str:
    raw = f"{project}\0{_norm(text)}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _section_lines(context: str, wanted: str) -> list[str]:
    """Return lines inside one CTX/2 top-level section."""
    out: list[str] = []
    inside = False
    fence = None
    for raw in (context or "").splitlines():
        token = raw.strip()
        if token.startswith(('```', '~~~')):
            marker = token[:3]
            fence = None if fence == marker else marker if fence is None else fence
            if inside:
                out.append(raw)
            continue
        if fence is None and token == wanted:
            inside = True
            continue
        if inside and fence is None and (token in CTX_SECTIONS or re.fullmatch(r"[A-Z][A-Z0-9_-]{2,}", token or "")):
            break
        if inside:
            out.append(raw)
    return out


def _section_items(context: str, wanted: str, limit: int = MAX_SECTION_ITEMS) -> list[str]:
    """Extract top-level bullet/numbered items from a CTX/2 section.

    OPEN/NEXT are deliberately represented as concise list items in Register's
    canonical context. Continuation lines are appended to the current item, while
    headings, lone '-' placeholders and fenced code are ignored.
    """
    items: list[str] = []
    current: str | None = None
    fence = None

    def flush() -> None:
        nonlocal current
        if current:
            cleaned = re.sub(r"\s+", " ", current).strip()
            if cleaned and cleaned != "-":
                items.append(cleaned)
        current = None

    for raw in _section_lines(context, wanted):
        s = raw.strip()
        if s.startswith(('```', '~~~')):
            marker = s[:3]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence or not s or s == "-" or s.startswith("@"):
            continue

        m = re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)(.+)$", s)
        if m:
            flush()
            current = m.group(1).strip()
            if len(items) >= limit:
                break
            continue

        # Keep short wrapped prose attached to the current list item. Ignore
        # Markdown headings/table rows and raw CTX labels.
        if current and not s.startswith(("#", "|")):
            current += " " + s

    if len(items) < limit:
        flush()
    return items[:limit]


def _context_mtime(name: str) -> float:
    path = register.project_dir(name) / register.context_name(name)
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _summary_mtime(name: str) -> float:
    path = register.project_dir(name) / register.summary_name(name)
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _project_payload(p: dict[str, Any]) -> dict[str, Any]:
    handoffs = p.get("handoffs") or []
    latest_handoff = float(handoffs[0].get("mtime", 0.0)) if handoffs else 0.0
    context_through = float(p.get("context_through", 0.0) or 0.0)
    summary_through = float(p.get("summarised_through", 0.0) or 0.0)
    context = str(p.get("context") or "")
    opens = _section_items(context, "OPEN")
    nexts = _section_items(context, "NEXT")

    return {
        "name": p["name"],
        "checkpoint_id": (p.get("context_source_digest") or None)
                         if p.get("context_source_mode") == "conversation-checkpoint" else None,
        "status": p.get("status") or "unset",
        "last_activity_at": _iso(float(p.get("mtime", 0.0) or 0.0)),
        "last_handoff_at": _iso(latest_handoff),
        "context_updated_at": _iso(_context_mtime(p["name"])),
        "summary_updated_at": _iso(_summary_mtime(p["name"])),
        "handoff_count": int(p.get("handoff_count", 0) or 0),
        "file_count": int(p.get("file_count", 0) or 0),
        "open": opens,
        "next": nexts,
        "derived_state_pending": checkpoints.pending(p),
    }


def _latest_review(now: datetime) -> dict[str, Any] | None:
    reviews = []
    if ESTATE_DIR.exists():
        reviews = [p for p in ESTATE_DIR.glob("review-*.md") if p.is_file()]
    if not reviews:
        return None
    path = max(reviews, key=lambda p: p.stat().st_mtime)
    mtime = path.stat().st_mtime
    age_days = max(0.0, (now.timestamp() - mtime) / 86400.0)
    return {
        "file": path.name,
        "updated_at": _iso(mtime),
        "age_days": round(age_days, 1),
    }


def _load_previous(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None
    return data


def _project_changed(cur: dict[str, Any], prev: dict[str, Any]) -> bool:
    fields = (
        "checkpoint_id", "status", "last_activity_at", "last_handoff_at", "context_updated_at",
        "summary_updated_at", "open", "next", "derived_state_pending",
    )
    return any(cur.get(k) != prev.get(k) for k in fields)


def build_payload(previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the JSON object without writing it."""
    register.invalidate()
    now = datetime.now(timezone.utc)

    projects = [
        _project_payload(p)
        for p in register.project_list()
        if not p.get("archived") and not str(p.get("name", "")).startswith("_")
    ]
    projects.sort(key=lambda p: p["name"].casefold())

    review = _latest_review(now)
    baseline = not previous
    changed_projects: list[str] = []
    new_open: list[dict[str, str]] = []
    review_updated = False

    if previous:
        prev_projects = {
            p.get("name"): p
            for p in (previous.get("projects") or [])
            if isinstance(p, dict) and p.get("name")
        }
        for cur in projects:
            prev = prev_projects.get(cur["name"])
            if prev is None or _project_changed(cur, prev):
                changed_projects.append(cur["name"])

            old_open = {_norm(x) for x in ((prev or {}).get("open") or [])}
            for item in cur.get("open") or []:
                if _norm(item) not in old_open:
                    new_open.append({
                        "project": cur["name"],
                        "id": _item_id(cur["name"], item),
                        "item": item,
                    })

        prev_review = previous.get("portfolio_review")
        review_updated = bool(review) and (
            not isinstance(prev_review, dict)
            or review.get("file") != prev_review.get("file")
            or review.get("updated_at") != prev_review.get("updated_at")
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "baseline": baseline,
        "counts": {
            "projects": len(projects),
            "changed_projects": len(changed_projects),
            "new_open": len(new_open),
            "pending_derived_state": sum(1 for p in projects if p["derived_state_pending"]),
        },
        "changes": {
            "projects": changed_projects,
            "new_open": new_open,
            "portfolio_review_updated": review_updated,
        },
        "portfolio_review": review,
        "projects": projects,
    }


def export_status(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    """Build and atomically publish the status snapshot."""
    previous = _load_previous(output)
    payload = build_payload(previous)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    tmp.replace(output)
    log.info(
        "Herald status exported: %d projects, %d changed, %d new OPEN, review=%s",
        payload["counts"]["projects"],
        payload["counts"]["changed_projects"],
        payload["counts"]["new_open"],
        (payload.get("portfolio_review") or {}).get("file", "none"),
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Publish Register state for Herald")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    ap.add_argument("--stdout", action="store_true",
                    help="print the would-be payload without updating the baseline")
    args = ap.parse_args(argv)

    output = Path(args.output)
    if args.stdout:
        payload = build_payload(_load_previous(output))
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    payload = export_status(output)
    print(
        f"written {output}: {payload['counts']['projects']} projects, "
        f"{payload['counts']['changed_projects']} changed, "
        f"{payload['counts']['new_open']} new OPEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
