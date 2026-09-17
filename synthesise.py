#!/usr/bin/env python3
"""synthesise.py — monthly cross-project review.

Feeds every project's summary and handoff notes to Gemini in one pass and
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

Below are his project status summaries and session handoff notes. Each
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
- Be specific and unsentimental. Vague encouragement is worthless here.
- Do not summarise each project in turn — that already exists. Only say
  things that require seeing the whole estate at once.

--- PROJECTS ---

"""


def collect(vault: Path) -> tuple[str, list[str]]:
    projects_dir = vault / "projects"
    if not projects_dir.exists():
        sys.exit(f"no projects directory under {vault}")

    blocks, included, trimmed = [], [], []
    used = 0

    # Most recently active first: if the budget does run out, it should
    # drop the projects you haven't touched in months, not the live ones.
    def last_touch(d: Path) -> float:
        try:
            return max((f.stat().st_mtime for f in d.rglob("*.md")), default=0)
        except OSError:
            return 0

    entries = [d for d in projects_dir.iterdir()
               if d.is_dir() and not d.name.startswith(".")]
    entries.sort(key=last_touch, reverse=True)

    for d in entries:
        if not d.is_dir() or d.name.startswith("."):
            continue
        meta = d / "_project.md"
        if meta.exists() and "archived: true" in meta.read_text(
                encoding="utf-8", errors="replace").lower():
            continue

        def clip(text: str) -> str:
            text = text.strip()
            if len(text) <= PER_FILE_CHARS:
                return text
            return text[:PER_FILE_CHARS] + "\n[...truncated...]"

        parts, proj_used, dropped = [], 0, 0

        # The summary is the most valuable item, so it goes in first and
        # is never dropped for budget.
        summary = d / f"{d.name}_summary.md"
        if not summary.exists():
            summary = d / "_summary.md"
        if summary.exists():
            block = "STATUS SUMMARY:\n" + clip(
                summary.read_text(encoding="utf-8", errors="replace"))
            parts.append(block)
            proj_used += len(block)

        handoffs = sorted(
            (f for f in d.rglob("*.md")
             if not f.name.endswith(("_summary.md", "_RUNBOOK.md"))
             and f.name != "_project.md"),
            key=lambda f: f.stat().st_mtime, reverse=True)

        for f in handoffs:
            if proj_used >= PER_PROJECT_CHARS:
                dropped += 1
                continue
            age = int((time.time() - f.stat().st_mtime) / 86400)
            block = (f"HANDOFF ({age}d ago) {f.name}:\n"
                     + clip(f.read_text(encoding="utf-8", errors="replace")))
            parts.append(block)
            proj_used += len(block)

        if dropped:
            parts.append(f"[{dropped} older file(s) omitted for length]")
            trimmed.append(f"{d.name} ({dropped} omitted)")

        if not parts:
            continue

        newest = max((f.stat().st_mtime for f in d.rglob("*.md")), default=0)
        age = int((time.time() - newest) / 86400) if newest else -1
        block = (f"\n\n===== PROJECT: {d.name} "
                 f"(last activity {age} days ago) =====\n\n"
                 + "\n\n".join(parts))
        if used + len(block) > CHAR_BUDGET:
            print(f"char budget reached — stopping at {d.name}", file=sys.stderr)
            break
        blocks.append(block)
        included.append(d.name)
        used += len(block)

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

    print(f"{len(included)} projects, {len(material):,} chars",
          file=sys.stderr)

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
