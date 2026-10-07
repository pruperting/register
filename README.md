# Register

A small self-hosted register: where each project stands, what is DONE, what
remains OPEN/NEXT, and enough technical context to resume an AI conversation.
Your Syncthing/Obsidian vault is the only datastore. Projects are folders under
`projects/`; `project:` frontmatter must match the folder slug exactly.

## Conversation checkpoint workflow

1. **Seed once.** Open the project page and choose **bootstrap checkpoint with
   Gemini**. Existing handoffs are deterministically compressed in chronological
   batches, with task/correction/technical anchors protected and credentials
   redacted. Gemini reconciles them into one complete checkpoint. Projects with
   reference files only use the explicit reference bootstrap. There is no
   automatic AI call on page load or routine refresh.
2. **Start a conversation.** Download the full context or compact chat copy.
   Both include `CHECKPOINT_ID` and CTX/2. The compact copy uses the deterministic
   Markdown parser, preserves every checkpoint item and command/code block, and
   leaves the original snapshot untouched. It may not be smaller when the
   source is already compact; it never drops facts just to meet a token target.
3. **Finish the conversation.** Use the project's **handoff prompt**. It embeds
   the full prior checkpoint and asks the conversation AI to reconcile all
   changes and prior tasks, then emit a complete replacement CTX/2 and a brief
   human summary. The prompt retains exact technical literals, corrections,
   decisions, completed work, rejected approaches and remaining tasks.
4. **Save/sync the handoff.** Save an ordinary `.md` file under
   `projects/<Project>/handoffs/`, or elsewhere with the exact project slug.
   Do not use `<Project>_CONTEXT.md` or `<Project>_summary.md` for the upload:
   those names are reserved for the derived views. Syncthing brings it in.
5. **Register publishes it.** A page visit, rescan, import button or nightly
   scan validates and publishes the snapshot and its human summary. No Gemini
   or Ollama generation occurs. Repeating the import returns `fresh`.

CTX/2 sections: **GOAL, STACK, ARCH, FILES, STATE, DONE, CORRECTIONS, DEC, INV,
BUG, OPEN, NEXT, REJECTED, FACTS**. STATE is implemented current reality; DONE
records verified completions; OPEN/NEXT retain unresolved/future work. A
proposal is never automatically marked complete. An empty section contains `-`.
Human summary and AI context come from the same immutable handoff; Register
checks structure and ancestry, not semantic factual correctness.

## Checkpoint format and conflicts

The project-specific prompt produces:

```markdown
---
type: handoff
project: MyProject
checkpoint_version: 1
based_on: <copy the supplied CHECKPOINT_ID>
created_at: <copy the supplied timezone-aware timestamp>
date: YYYY-MM-DD
title: Current project checkpoint
project_status: building
---

## Human summary
Brief readable project status and next actions.

## AI checkpoint
CTX/2
GOAL
- ...
STACK
- ...
```

The actual document must include ALL fourteen CTX sections, once and in order,
not just the example above. `project_status` is optional; valid values are
`running`, `building`, `paused`, `idea`, `retired`. An established status is
published to project metadata without creating a separate task manager.

`based_on` identifies the preceding snapshot. For a completely new project
with no handoffs, it is `ROOT`; for a first snapshot replacing legacy evidence,
it is a `legacy:<digest>` provided by Register. Never invent it. Timestamp and
filesystem mtime do not decide which snapshot supersedes which.

Malformed files, missing ancestors, changed legacy evidence or sibling updates
are flagged; the last published views are retained. Two valid conflicting
conversation updates can be resolved using **handoff prompt**: it supplies both
versions and a `reconciles` list. The AI must reconcile every version into a
complete new checkpoint based on their common ancestor. Old snapshots remain
immutable. Invalid uploads must be corrected or missing ancestors restored;
there is no silent last-writer-wins merge. Wrong project slugs go to the
existing unfiled queue. Structural validation is deliberately conservative:
missing sections cannot inherit historical state accidentally.

The full source checkpoint has a hard maximum of approximately 15000 tokens.
Conversation AI should remove repetition and narration before sacrificing
continuation-critical facts. Historical handoffs remain unchanged. After
migration, later incremental legacy handoffs are not silently folded in; use
the complete-checkpoint prompt for subsequent updates.

## Upload compressor retained

The **compress** page accepts `.md`, `.markdown` and `.txt` files (20 MB default)
and produces deterministic chat-facing CTX/2 with Safe/Balanced/Dense profiles.
It makes zero model calls, retains protected corrections and task sections,
and understands plain CTX/2 markers, including DONE. Uploads/results are
transient and do not alter the vault; copy or download the `.ctx` result.
This general-purpose compressor selects facts under a soft budget. For a
complete project's lossless chat copy, use its dedicated compact download.

## Weekly Gemini estate review and Herald

The estate review remains separate from per-project updating. It runs **Sunday
04:00 Europe/London** by default, once per week, through `synthesise.py`. It reads
accepted current checkpoints only, excludes archived projects and `_estate`,
and never blends raw handoff mtime deltas into current truth. Oversized review
inputs use section-aware selection that prioritises corrections, OPEN/NEXT,
current state and completed work. It redacts the external payload and output.
Reviews are saved to `projects/_estate/review-YYYY-MM-DD.md`, preserving separate
weeks. An explicit rerun on the same date replaces that date's review.

Projects without an accepted complete checkpoint are reported as excluded:
bootstrap them once or save a conversation checkpoint before expecting them in
the review. The review suggests priorities; it does not modify project truth.
Review collection refreshes the derived views locally, including in dry-run.

Daily 03:00 scans import checkpoints without AI calls. Herald's daily 06:15
export remains, using content/ancestry-aware pending status rather than mtime
watermarks. Existing first-run/daily-delta semantics remain intact.

```bash
docker compose exec -T register python /app/synthesise.py --vault /vault --dry-run
docker compose exec -T register python /app/synthesise.py --vault /vault
```

Check for older host crontab entries that invoke synthesis monthly; disable
those duplicate entries if present. The in-app scheduler now runs weekly.

## Running and migrating an existing deployment

```bash
cp .env.example .env  # new deployments: configure vault path and Gemini key
docker compose up -d --build
```

For existing deployments, **keep your current `.env`**. Set these if you want to
change the weekly defaults:

```dotenv
WEEKLY_SYNTHESIS=true
WEEKLY_SYNTHESIS_DAY=sun
WEEKLY_SYNTHESIS_HOUR=4
```

Compose passes them into the container. Optional `SYNTHESIS_MODEL` selects the
estate-review model; `GEMINI_MODEL` selects bootstrap. Ordinary operation does
not need Ollama. Old Ollama environment settings are harmless compatibility
settings and can be removed later. RUNBOOK generation/UI are retired; existing
RUNBOOK files are left on disk as history, with deployment instructions carried
in STACK/FILES/BUG instead. `/api/runbook/<name>` returns HTTP 410.

Open `http://<host>:5557`. Bootstrap **Register** first and inspect the result,
then migrate other projects as needed. Projects with old generated contexts or
baselines are explicitly marked as needing a complete checkpoint; their old
views remain visible for migration. A prior `context_baseline: true` does not
prevent the one-time complete-checkpoint bootstrap.

If Gemini bootstrap output fails validation, the UI and logs report the specific
failed rule and Gemini's finish reason. A redacted copy of the rejected output,
token counts and budget is saved as `checkpoint-bootstrap-rejected-*.json` in
the project directory. These diagnostic files are never imported as handoffs;
the published checkpoint remains unchanged. Bootstrap does not automatically
retry or make another AI call after rejection.

Test before deployment, from the repository directory:

```bash
git diff --check
python3 -m py_compile app.py register.py checkpoints.py synthesise.py herald_status.py
docker compose run --rm --user root -v "$PWD:/src" -w /src register \
  sh -lc 'python -m pip install -q pytest && pytest -q'
docker compose up -d --build
docker compose logs --tail 80 register
```

Confirm a checkpoint import and repeat it: the second import should be fresh.
Inspect human summary, full/compact downloads, DONE, corrections and OPEN/NEXT.
Verify `/compress` still works and the log schedules the weekly review.
A dry-run review checks project coverage without calling Gemini. New-bootstrap
and estate-review tests stub Gemini; live model output still needs inspection.

## Existing lifecycle and tools

Archiving moves a project to `projects/archive/<Project>` and excludes it from
live dashboards/reviews; unarchive restores it. Default handoffs directories
are created. Unmatched frontmatter is resolved through the unfiled queue.
Rename/merge and repo links remain available. A merge of independent snapshot
histories may flag incompatible ancestry rather than inventing a merged state;
reconcile those histories deliberately before relying on the merged checkpoint.

`tidy-vault.py` inventories/cleans the vault (read-only by default);
`secret-scan.py` and `secretscan.py` remain available. Credential values belong
only in `.env`, never in versioned files, handoffs or review output.
