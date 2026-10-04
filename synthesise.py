#!/usr/bin/env python3
"""synthesise.py — monthly cross-project review.

Feeds deterministic canonical project contexts to Gemini in one pass and
asks the question the register cannot answer: not "what is the state of
project X" but "what is stalled, what overlaps, and what should I stop
pretending I'll finish".

Gemini rather than the local model, deliberately: this needs the whole
estate in one context window, which is exactly what CPU prompt processing
is worst at and what a 1M-token context is best at. It runs monthly and
costs pennies.

Output: <vault>/projects/_estate/review-YYYY-MM.md, which the register
picks up as a file under the _estate project.

  ./synthesise.py                      # write the review
  ./synthesise.py --dry-run            # show what would be sent, no API call
  ./synthesise.py --stdout             # print instead of writing

Needs GEMINI_API_KEY in the environment.
Cron:  0 4 1 * *  docker exec register python /app/synthesise.py --vault /vault
"""
import argparse
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

DEFAULT_VAULT = os.environ.get("VAULT_PATH", "/vault")
MODEL = os.environ.get("SYNTHESIS_MODEL", "gemini-2.5-pro")
# Generous, but bounded — a runaway vault shouldn't produce a 2M-token call.
CHAR_BUDGET = int(os.environ.get("SYNTHESIS_CHAR_BUDGET", "700000"))
# One project must not eat the whole budget. Without this, a single fat
# project folder (handoffs plus pasted transcripts) starves every project
# after it alphabetically — which is exactly what happened on first run.
PER_PROJECT_CHARS = int(os.environ.get("SYNTHESIS_PER_PROJECT_CHARS", "45000"))
PER_FILE_CHARS = int(os.environ.get("SYNTHESIS_PER_FILE_CHARS", "10000"))

PROMPT = """You are reviewing the complete project estate of one person:
a hobbyist self-hoster who starts many more projects than he finishes, and
who wants an honest outside view rather than encouragement.

Below are deterministic canonical project contexts. Each
project is delimited. Some are active, some have not been touched in
months.

Write a review with exactly these sections:

## Where your attention actually went
What the evidence says he has really been working on over the period
covered, as opposed to what the project list implies. Name specifics.

## Stalled
Projects with no recent activity that were left mid-flight. For each: how
long since it moved, what state it was left in, and the single smallest
next action that would restart it. Be concrete — "next step is X" not
"needs attention".

## Overlapping or duplicated effort
Projects solving the same problem twice, components that could be shared,
or work repeated across projects. Say plainly where consolidation would
pay off.

## Recurring problems
Technical issues, mistakes, or wasted time that show up across more than
one project. These are the patterns worth fixing once rather than
repeatedly.

## Candidates to kill
Be direct here — this is the section he asked for and the one he will
find least comfortable. Which projects should he explicitly abandon or
archive, and why? Base this on evidence: how long stalled, whether it was
superseded, whether the stated goal is already met by something else. It
is more useful to name three than to hedge.

## Do these three things next
Exactly three concrete actions across the whole estate, in priority
order, with a sentence each on why that one and not something else.

Rules:
- Only use what the documents state. Where something is unclear, say so
  rather than inferring.
- Explicit CORRECTIONS are authoritative. Apply CURRENT values and never treat
  PREVIOUS values as live project state. If a newer deterministic delta corrects
  the canonical checkpoint, the newer correction wins.
- Be specific and unsentimental. Vague encouragement is worthless here.
- Do not summarise each project in turn — that already exists. Only say
  things that require seeing the whole estate at once.

--- PROJECTS ---

"""


_CTX_SECTIONS = ("GOAL", "STACK", "ARCH", "FILES", "STATE", "CORRECTIONS",
                 "DEC", "INV", "BUG", "OPEN", "NEXT", "REJECTED", "FACTS")
# Portfolio synthesis cares most about current truth and current action.  These
# caps are ceilings, not quotas: unused room falls through to lower-priority
# sections.  CORRECTIONS is intentionally uncapped and always wins.
_PORTFOLIO_PRIORITY = (
    ("CORRECTIONS", None),
    ("OPEN", 8000),
    ("NEXT", 8000),
    ("GOAL", 3500),
    ("STATE", 7000),
    ("DEC", 5000),
    ("BUG", 3500),
    ("INV", 3500),
    ("ARCH", 3000),
    ("FACTS", 2500),
    ("STACK", 2000),
    ("FILES", 1500),
    ("REJECTED", 1500),
)


def _ctx_sections(text: str) -> dict[str, str]:
    """Parse plain CTX/2 section headings without re-compressing the text."""
    heading = "|".join(map(re.escape, _CTX_SECTIONS))
    matches = list(re.finditer(rf"(?m)^({heading})\s*$", text or ""))
    out = {name: "" for name in _CTX_SECTIONS}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        if body and body != "-":
            name = match.group(1)
            out[name] = (out[name] + "\n" + body).strip() if out[name] else body
    return out


def _take_complete_lines(text: str, limit: int) -> tuple[str, bool]:
    """Take at most limit chars, preferring complete CTX lines/items."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text, False
    if limit <= 0:
        return "", True
    kept = []
    used = 0
    for line in text.splitlines():
        cost = len(line) + (1 if kept else 0)
        if used + cost > limit:
            break
        kept.append(line)
        used += cost
    # A single pathological line should not make the section disappear.
    if not kept and limit >= 80:
        kept = [text[:max(0, limit - 24)].rstrip()]
    return "\n".join(kept).rstrip(), True


def _portfolio_clip(parts: list[str], limit: int) -> str:
    """Build a section-aware portfolio view from canonical CTX/2 parts.

    This is selection, not semantic recompression.  Canonical context and a
    newer deterministic handoff delta remain separate so delta precedence is
    visible to Gemini.  CORRECTIONS is retained in full even if that means an
    exceptional project slightly exceeds its nominal per-project cap.
    """
    sources = []
    for part in parts:
        if not part.strip():
            continue
        first, _, body = part.partition("\n")
        label = first.rstrip(":").strip()
        sections = _ctx_sections(body if body else part)
        sources.append((label, sections))

    if not sources:
        joined = "\n\n".join(parts)
        clipped, _ = _take_complete_lines(joined, limit)
        return clipped + "\n[...project context clipped...]"

    header = "PORTFOLIO VIEW OF DETERMINISTIC CTX/2 (section-aware clipped)\n"
    selected: dict[tuple[int, str], str] = {}
    clipped_keys: set[tuple[int, str]] = set()

    # First preserve all authoritative corrections, newest source last.
    used = len(header)
    for idx, (_label, sections) in enumerate(sources):
        body = sections.get("CORRECTIONS", "")
        if body:
            selected[(idx, "CORRECTIONS")] = body
            used += len(body) + len("CORRECTIONS\n") + 4

    # If corrections alone exceed the nominal limit, authority wins over cost.
    room = max(0, limit - used - 160)

    # Allocate the remaining budget by portfolio relevance.  The handoff delta
    # gets first claim within each section because it is newer than canonical.
    source_order = list(reversed(range(len(sources))))
    for section, section_cap in _PORTFOLIO_PRIORITY:
        if section == "CORRECTIONS" or room <= 0:
            continue
        for idx in source_order:
            body = sources[idx][1].get(section, "")
            if not body:
                continue
            allowance = room if section_cap is None else min(room, section_cap)
            if allowance <= 0:
                break
            kept, was_clipped = _take_complete_lines(body, allowance)
            if kept:
                selected[(idx, section)] = kept
                cost = len(kept) + len(section) + 4
                room = max(0, room - cost)
            if was_clipped:
                clipped_keys.add((idx, section))
            if room <= 0:
                break

    # Render each source separately in canonical CTX section order.  That keeps
    # NEW-HANDOFF DELTA visibly later than the canonical checkpoint.
    out = [header.rstrip()]
    for idx, (label, _sections) in enumerate(sources):
        chosen = [(sec, selected[(idx, sec)]) for sec in _CTX_SECTIONS
                  if (idx, sec) in selected]
        if not chosen:
            continue
        out.append(f"SOURCE {label}")
        for sec, body in chosen:
            out.append(sec)
            out.append(body)
            if (idx, sec) in clipped_keys:
                out.append(f"[...{sec} clipped for portfolio synthesis...]")
    out.append("[...lower-priority project context omitted for portfolio synthesis...]")
    return "\n".join(out).strip()


_REDACTION_PATTERNS = (
    ("private_key", re.compile(
        r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----",
        re.I | re.S), "[REDACTED PRIVATE KEY]"),
    ("bearer", re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}"), r"\1[REDACTED]"),
    ("basic_auth", re.compile(r"(?i)\b(Basic\s+)[A-Za-z0-9+/=]{12,}"), r"\1[REDACTED]"),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"), "[REDACTED GOOGLE API KEY]"),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), "[REDACTED GITHUB TOKEN]"),
    ("slack_token", re.compile(r"\bxox(?:a|b|p|r|s)-[A-Za-z0-9-]{10,}\b"), "[REDACTED SLACK TOKEN]"),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED AWS ACCESS KEY]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED JWT]"),
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|passphrase|api[_-]?key|apikey|secret|token|"
    r"access[_-]?token|refresh[_-]?token|client[_-]?secret|webhook[_-]?secret)\b"
    r"(\s*[:=]\s*)"
    r"(`[^`\n]+`|\"[^\"\n]+\"|'[^'\n]+'|[^\s,;|]+)"
)
_SECRET_LITERAL = re.compile(
    r"(?i)\b(password|passwd|passphrase|api[_-]?key|apikey|secret|token)\b"
    r"(\s+)(`[^`\n]+`|\"[^\"\n]+\"|'[^'\n]+')"
)
_URL_CREDENTIAL = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^\s/:@]+:)([^@\s/]+)(@)")
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def _redact_for_external_ai(text: str) -> tuple[str, dict[str, int]]:
    """Redact secrets only from the ephemeral payload sent to Gemini."""
    import ipaddress

    counts: dict[str, int] = {}

    def sub_counted(name, pattern, repl, value):
        value, n = pattern.subn(repl, value)
        if n:
            counts[name] = counts.get(name, 0) + n
        return value

    out = text
    for name, pattern, repl in _REDACTION_PATTERNS:
        out = sub_counted(name, pattern, repl, out)

    out = sub_counted(
        "secret_assignment", _SECRET_ASSIGNMENT,
        lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
    out = sub_counted(
        "secret_literal", _SECRET_LITERAL,
        lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
    out = sub_counted(
        "url_password", _URL_CREDENTIAL,
        lambda m: f"{m.group(1)}[REDACTED]{m.group(3)}", out)

    def redact_public_ip(match):
        raw = match.group(0)
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return raw
        if (ip.is_private or ip.is_loopback or ip.is_link_local or
                ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return raw
        counts["public_ip"] = counts.get("public_ip", 0) + 1
        return "[REDACTED PUBLIC IP]"

    out = _IPV4.sub(redact_public_ip, out)
    return out, counts


def collect(vault: Path) -> tuple[str, list[str]]:
    """Collect canonical CTX/2 plus deterministically compressed unsynced deltas.

    The monthly AI never receives raw handoff documents. Existing canonical
    contexts are primary; any handoffs newer than context_through are compacted
    deterministically before inclusion so synthesis remains safe even if the
    daily refresh has not run yet.
    """
    projects_dir = vault / "projects"
    if not projects_dir.exists():
        sys.exit(f"no projects directory under {vault}")

    # Import Register's deterministic compiler from the same application image.
    import register as reg

    blocks, included, trimmed = [], [], []
    used = 0

    def last_touch(d: Path) -> float:
        try:
            return max((f.stat().st_mtime for f in d.rglob("*.md")), default=0)
        except OSError:
            return 0

    entries = [
        d for d in projects_dir.iterdir()
        if d.is_dir()
        and not d.name.startswith(".")
        and d.name != "_estate"
    ]
    entries.sort(key=last_touch, reverse=True)

    for d in entries:
        meta = d / "_project.md"
        if meta.exists() and "archived: true" in meta.read_text(encoding="utf-8", errors="replace").lower():
            continue

        context = d / f"{d.name}_CONTEXT.md"
        summary = d / f"{d.name}_summary.md"
        if not summary.exists():
            summary = d / "_summary.md"

        parts, proj_used = [], 0
        context_hwm = 0.0
        if context.exists():
            ctext = context.read_text(encoding="utf-8", errors="replace").strip()
            parts.append("CANONICAL DETERMINISTIC CONTEXT:\n" + ctext)
            proj_used += len(parts[-1])
            try:
                import frontmatter
                context_hwm = float(frontmatter.load(context).get("context_through", 0) or 0)
            except Exception:
                context_hwm = context.stat().st_mtime
        elif summary.exists():
            # Legacy fallback only for projects that have never had CTX generated.
            st = summary.read_text(encoding="utf-8", errors="replace").strip()
            parts.append("LEGACY STATUS SUMMARY (no CTX/2 yet):\n" + st[:PER_FILE_CHARS])
            proj_used += len(parts[-1])

        newer = sorted(
            (f for f in d.rglob("*.md")
             if not f.name.endswith(("_summary.md", "_RUNBOOK.md", "_CONTEXT.md"))
             and f.name != "_project.md" and f.stat().st_mtime > context_hwm + 0.5),
            key=lambda f: f.stat().st_mtime)
        if newer:
            docs=[]
            for f in newer:
                raw=f.read_text(encoding="utf-8", errors="replace")
                docs.append((f.name, raw))
            delta=reg._deterministic_compress(docs, profile="balanced", target_tokens=4000)
            if delta.get("missing_hard"):
                print(f"protected delta facts missing for {d.name}; omitting unsafe delta", file=sys.stderr)
            else:
                block="DETERMINISTIC NEW-HANDOFF DELTA:\n" + delta["context"]
                parts.append(block)
                proj_used += len(block)

        if not parts:
            continue
        if proj_used > PER_PROJECT_CHARS:
            parts=[_portfolio_clip(parts, PER_PROJECT_CHARS)]
            trimmed.append(d.name)

        newest = last_touch(d)
        age = int((time.time() - newest) / 86400) if newest else -1
        block=(f"\n\n===== PROJECT: {d.name} (last activity {age} days ago) =====\n\n" +
               "\n\n".join(parts))
        if used + len(block) > CHAR_BUDGET:
            print(f"char budget reached — stopping at {d.name}", file=sys.stderr)
            break
        blocks.append(block); included.append(d.name); used += len(block)

    if trimmed:
        print("trimmed: " + ", ".join(trimmed), file=sys.stderr)
    return "".join(blocks), included


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=os.environ.get("VAULT_PATH", DEFAULT_VAULT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()

    vault = Path(args.vault)
    material, included = collect(vault)
    if not material:
        sys.exit("no project material found — nothing to review")

    material, redactions = _redact_for_external_ai(material)
    print(f"{len(included)} projects, {len(material):,} chars",
          file=sys.stderr)
    if redactions:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(redactions.items()))
        print(f"redacted for external AI: {detail}", file=sys.stderr)

    if args.dry_run:
        print(", ".join(included))
        sys.exit(0)

    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        sys.exit("GEMINI_API_KEY not set")

    try:
        from google import genai
    except ImportError:
        sys.exit("google-genai not installed. Either:\n"
                 "  pip install google-genai --break-system-packages\n"
                 "or run it inside the register container, which already "
                 "has it:\n"
                 "  docker exec -e GEMINI_API_KEY=$GEMINI_API_KEY \\\n"
                 "    register python /app/synthesise.py --vault /vault")
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(model=MODEL,
                                          contents=PROMPT + material)
    text = (resp.text or "").strip()
    if not text:
        sys.exit("empty response from model")

    header = (f"---\ntype: review\nproject: _estate\n"
              f"date: {date.today().isoformat()}\n"
              f"title: Cross-project review, {date.today():%B %Y}\n"
              f"generated_by: {MODEL}\n"
              f"projects_reviewed: {len(included)}\n---\n\n")

    if args.stdout:
        print(header + text)
        return

    out = vault / "projects" / "_estate" / f"review-{date.today():%Y-%m}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + text + "\n", encoding="utf-8")
    print(f"written: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
