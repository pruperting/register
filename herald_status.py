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

# v2: OPEN is diffed on the full list (via open_ids), items are reduced to short
# headlines, sub-heading bullets are dropped, and a per-project `summary` is
# published for display. A v1 file is not a valid baseline, so the first v2 run
# is a baseline run (no "new OPEN" flood from the old 12-item cap).
SCHEMA_VERSION = 2
ESTATE_DIR = register.VAULT_PATH / register.PROJECTS_DIR / "_estate"
DEFAULT_OUTPUT = ESTATE_DIR / "herald-status.json"
MAX_SECTION_ITEMS = 12          # items shown per section (display only)
MAX_SCAN_ITEMS = 500            # items read per section for diffing
SHORT_ITEM_CHARS = 50  # items this short are shown whole
MAX_SUMMARY_PROJECTS = 8
HEADLINE_CHARS = 80

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


def _is_subheading(text: str) -> bool:
    """A bullet that only labels the bullets after it, e.g. 'Open:'."""
    return text.endswith(":") and len(text) <= 60 and "`" not in text


def _headline(text: str, limit: int = HEADLINE_CHARS) -> str:
    """Reduce a CTX item to a short, readable headline.

    'Verify Garden Beacon: Confirm `/api/garden` is ce08. Repoint ...'
        -> 'Verify Garden Beacon'
    Otherwise the first sentence, with Markdown backticks removed, capped.
    """
    s = re.sub(r"\s+", " ", (text or "").replace("`", "")).strip()
    first = re.split(r"(?<=[^.\d][.;])\s", s, maxsplit=1)[0]
    m = re.match(r"^(.{3,60}?):\s+\S", s)
    if m and (
        len(first) <= SHORT_ITEM_CHARS  # short enough to keep whole
        # "On the Pi: run X" - the bit before the colon is a place, not the task.
        or re.match(r"(?i)(on|in|at|from|for|with|after|before|via|when|if|then)\b", m.group(1))
        # "TODO T-4: inspect logs" - a tag or ticket id, not a summary.
        or re.search(r"(?i)^(todo|fixme|note|bug)\b|\b[A-Z]+-\d+\b", m.group(1))
    ):
        m = None
    s = m.group(1) if m else first
    s = s.rstrip(" .;:")
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


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
            # "- Suggested but not acted on:" / "- Open:" are sub-headings
            # inside a section, not items.
            if cleaned and cleaned != "-" and not _is_subheading(cleaned):
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
    all_opens = _section_items(context, "OPEN", limit=MAX_SCAN_ITEMS)
    opens = all_opens[:MAX_SECTION_ITEMS]
    nexts = _section_items(context, "NEXT")

    return {
        "name": p["name"],
        "checkpoint_id": (p.get("context_source_digest") or None)
                         if p.get("context_source_mode") == "conversation-checkpoint" else None,
        "open_ids": sorted({_item_id(p["name"], x) for x in all_opens}),
        "open_total": len(all_opens),
        "_open_full": all_opens,  # build-time only; stripped before writing
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
        "summary_updated_at", "open_ids", "next", "derived_state_pending",
    )
    return any(cur.get(k) != prev.get(k) for k in fields)


def _summary(projects: list[dict[str, Any]], changed: list[str],
             new_open: list[dict[str, str]]) -> list[dict[str, Any]]:
    """One short line per changed project, always naming the project.

    e.g. 'Herald: 2 new open items · next: Verify Garden Beacon'
    """
    by_name = {p["name"]: p for p in projects}
    new_by_project: dict[str, int] = {}
    for n in new_open:
        new_by_project[n["project"]] = new_by_project.get(n["project"], 0) + 1

    # Projects with new OPEN items first, then most recently active.
    order = sorted(changed, key=lambda n: by_name[n].get("last_activity_at") or "",
                   reverse=True)
    order.sort(key=lambda n: -new_by_project.get(n, 0))  # stable

    out: list[dict[str, Any]] = []
    for name in order[:MAX_SUMMARY_PROJECTS]:
        p = by_name[name]
        bits: list[str] = []
        k = new_by_project.get(name, 0)
        if k:
            bits.append(f"{k} new open item{'s' if k != 1 else ''}")
        else:
            bits.append("updated")
        if p.get("next"):
            bits.append(f"next: {_headline(p['next'][0])}")
        out.append({
            "project": name,
            "status": p.get("status"),
            "new_open": k,
            "open_total": p.get("open_total", 0),
            "next": _headline(p["next"][0]) if p.get("next") else None,
            "line": f"{name}: " + " · ".join(bits),
        })
    hidden = len(changed) - len(out)
    if hidden > 0:
        out.append({"project": None, "line": f"+{hidden} more project{'s' if hidden != 1 else ''} updated"})
    return out


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

            old_ids = set((prev or {}).get("open_ids") or [])
            for item in cur["_open_full"]:
                iid = _item_id(cur["name"], item)
                if iid not in old_ids:
                    new_open.append({
                        "project": cur["name"],
                        "id": iid,
                        "item": item,
                    })

        prev_review = previous.get("portfolio_review")
        review_updated = bool(review) and (
            not isinstance(prev_review, dict)
            or review.get("file") != prev_review.get("file")
            or review.get("updated_at") != prev_review.get("updated_at")
        )

    summary = _summary(projects, changed_projects, new_open)
    for p in projects:
        p.pop("_open_full", None)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "baseline": baseline,
        # Display-ready: one entry per changed project, name first. Herald
        # should render this rather than the raw lists below.
        "summary": summary,
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
