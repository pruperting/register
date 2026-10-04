# register

A small self-hosted project register for people who start more projects
than they finish.

It answers one question: **what state is each of my projects in, and how
do I pick it up again?** It does not do search, chat, or retrieval —
those turned out to be better handled by the AI tools themselves.

## How it works

Your Obsidian vault is the entire database. There is no SQL, no vector
store, and no state outside the vault — so there is nothing to re-index,
nothing to corrupt, and nothing extra to back up.

- A **project** is a folder under `projects/`. Nothing else creates one.
- A **file belongs** to a project when its `project:` frontmatter matches
  a folder name exactly. Anything else lands in a "to be filed" queue in
  the UI, where you assign it or promote it into a new project.
- Project names are **TitleCase** (`HomelabRationalisation`). One
  convention avoids case-only duplicates, which break file sync against
  case-insensitive filesystems like Windows.
- **Summaries** are generated from *handoff notes* — the context summary
  you ask an AI to write at the end of a working session — rather than raw
  chat transcripts. That is what makes local CPU summarisation viable:
  seconds instead of tens of minutes.

Each project gets a three-section human summary: **Overview**, **Where it stands**
and **Pick up here**. It also maintains a deterministic `CTX/2`
`<Project>_CONTEXT.md` checkpoint designed to paste into a fresh AI coding chat.
`context_through` is a freshness watermark: when new source material appears,
the checkpoint is rebuilt from all immutable handoffs/debriefs so repeated
lossy recompression cannot accumulate. Optionally a `<Project>_RUNBOOK.md` is
generated too.

## Vault layout

```
vault/
├── projects/
│   └── MyProject/
│       ├── _project.md             # status, description, repo, archived
│       ├── MyProject_summary.md    # generated
│       ├── MyProject_RUNBOOK.md    # generated, optional
│       └── handoffs/               # your end-of-session notes
└── anywhere-else/*.md              # filed by `project:` frontmatter
```

Handoff notes are recognised by `type: handoff` frontmatter, a filename
starting `handoff`/`context`, or living in a `handoffs/` folder. Filing is
by frontmatter, so a note can sit anywhere in the vault.

## Running it

```bash
cp .env.example .env     # set VAULT_HOST_PATH at minimum
docker compose up -d --build
```

Then open `http://<host>:5557`.

Summaries need either Ollama (`SUMMARY_BACKEND=local`, the default) or a
Gemini API key (`SUMMARY_BACKEND=gemini`). A mixture-of-experts model such
as `qwen3:30b-a3b` runs at usable speed on CPU.

A nightly job folds new handoff notes into each project's verified AI context and human summary. It
skips projects with nothing new (costing no model calls at all) and
projects with no handoff notes, and is capped per run.


## Compress arbitrary documents

The web UI has a **compress** page (`GET /compress`) for one-off Markdown or
text files that are not Register projects. Drop one or more `.md`, `.markdown`
or `.txt` files onto the page, choose Safe/Balanced/Dense, and Register produces
a deterministic `CTX/2` document. Compression makes no AI calls; protected facts
and explicit corrections are checked mechanically.

Uploads are transient: Register does not save the source files or compressed
result into the vault. Copy the result or download `compressed-context.ctx`
and give that to ChatGPT, Claude, Gemini, etc.

The total upload limit defaults to 20 MB and can be changed with
`COMPRESS_MAX_MB`.

The deterministic compressor is intentionally model-free, so it is fast on the
low-power host and does not depend on Ollama/Gemini availability. AI remains in
the human-facing summary and RUNBOOK paths. The web poller retries temporary
LAN/browser failures without abandoning the server-side job.

## Tools

**`synthesise.py`** — monthly cross-project review. Sends every project's
summary and handoffs to Gemini in one call and asks what has stalled, what
overlaps, what problems recur, and what to kill. Writes
`projects/_estate/review-YYYY-MM.md`.

```bash
docker exec -e GEMINI_API_KEY=... register \
  python /app/synthesise.py --vault /vault --stdout
```

**`tidy-vault.py`** — vault inventory and cleanup. Read-only by default.
Finds junk files, duplicate and case-colliding project names, folders not
in TitleCase, and files claiming projects that do not exist.

```bash
python3 tidy-vault.py --vault /path/to/vault
python3 tidy-vault.py --vault /path/to/vault --fix-junk --apply-titlecase --apply-claims
```

`--fix-junk` quarantines to a timestamped folder rather than deleting.
Merges and renames move files and are not undoable — back up first.

**Two prompts**, both served as plain text with your own values filled in:

`GET /prompt` — the end-of-session **handoff** prompt, with your current
project slugs embedded so the model can't invent a new one. Records what
changed this session; gets folded into the project summary. Copy button in
the UI header.

`GET /prompt/debrief?project=Name` — a full **debrief** prompt, scoped to
one project and carrying its repo URL. Produces a standalone technical
description of the project as it stands today — architecture, files,
config, conventions, gotchas — with no history in it. Paste the result at
the start of a new AI chat to bring it fully up to speed. Copy button on
each project page.

The distinction matters: a handoff accumulates, a debrief supersedes. Use
handoffs continuously; regenerate a debrief when you are about to start
serious work in a fresh conversation.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/compress` | compress transient Markdown/text uploads into CTX/1 |
| `POST /api/summary/<project>` | generate or update a summary (`{"full": true}` to rebuild) |
| `GET /api/context/<project>` | return compact AI context as text (`?download=1` to download) |
| `POST /api/context/<project>` | update context (`{"full": true}` to rebuild and reverify) |
| `POST /api/runbook/<project>` | generate RUNBOOK.md |
| `POST /api/status/<project>` | `running`, `building`, `paused`, `idea`, `retired` |
| `POST /api/archive/<project>` | `{"archived": true}` |
| `POST /api/rename/<project>` | `{"new": "NewName"}` |
| `POST /api/merge` | `{"sources": [...], "target": "..."}` |
| `POST /api/file` | resolve an unfiled claim |
| `GET /api/jobs/<key>` | poll a background job |
| `GET /api/stats` | counts |
| `GET /prompt` | handoff prompt with current slugs |
| `GET /prompt/debrief?project=` | full project debrief prompt |

Summaries, runbooks, renames and merges run as background jobs and return
`202` immediately — they take minutes on a local model, far longer than
any HTTP timeout.

## Notes

Generated files are named per-project (`MyProject_summary.md`) rather than
`_summary.md`, so citations stay readable when the vault is fed to a RAG
tool.

The container runs as `PUID`/`PGID` rather than root, because it writes
into a synced vault and root-owned files there cause trouble.

Licence: MIT.

Local compressor formatting is parsed tolerantly; cosmetic output drift from smaller models no longer triggers an expensive retry. Final CTX/1 structure is canonicalised locally in Python.


### Deterministic compressor (default)

`/compress` now defaults to **Deterministic · no AI**. It parses Markdown
structure, joins wrapped prose, removes formatting overhead, classifies content
into CTX sections, de-duplicates exact repeats, and protects lines containing
technical literals/status language. It does not paraphrase source facts, so
there is no model latency or hallucination risk. `Safe`, `Balanced`, and
`Dense` control how much ordinary explanatory prose is retained.

**AI refine** is optional. It performs one model pass only after deterministic
compaction, so Ollama sees a much smaller input. It is not required for normal
compression.

Compression jobs now log file size, approximate tokens, parser progress,
protected-fact count, output size, elapsed time, and optional AI timing. The
same progress is exposed by `/api/jobs/<key>` and displayed in the UI.


### Budget-aware deterministic compression

Balanced deterministic compression now targets about 3,000 tokens by default
(configurable in the Compress UI). Source is parsed into semantic units and
ranked by section, status/action language, technical literals and information
density. NEXT, invariants, open items and critical state/bug facts are protected
before the remaining token budget is filled. Fenced command/code blocks are
kept line-for-line. The target is soft: protected facts may push output above it.
No AI call is made unless `AI refine` is explicitly selected.


### Protected 30B refinement

Optional AI refinement now defaults to `qwen3:30b-a3b`. The deterministic
compiler still runs first at ~3,000 tokens. A single refinement call targets
~2,200 tokens by default. Before the call, Register derives a mandatory
retention contract from NEXT, invariants, open items, current state, critical
bugs and important design facts. After the call Python verifies that contract.

If any protected fact is missing, the AI result is **rejected automatically**
and the safe deterministic context is returned instead. The UI reports
refinement coverage. Configure with `REFINE_MODEL`, `REFINE_NUM_CTX`,
`REFINE_TIMEOUT_S`, and `REFINE_TARGET_TOKENS`.


### v6: fast Qwen3 refinement

Local Qwen3 refinement explicitly sends `"think": false` to Ollama. Refinement
also gets exactly one model attempt: the generic `_complete()` corrective retry
is disabled for this stage. If that one call fails validation, times out, or
fails the protected-fact contract, Register immediately returns the safe
deterministic ~3K CTX instead. Other Register model calls retain their existing
retry behaviour.


### Production compressor

`/compress` is now deterministic-only. AI refinement was removed after testing:
the 30B local refinement took ~11 minutes and retained only 59.5% of the
protected contract, while the deterministic compiler completed in well under
a second. The compressor keeps a soft token target, preserves the project goal,
protects continuation-critical facts, performs safe cross-section duplicate
removal, and reports protected retained/missing counts plus AI calls (= 0).


### v8 adaptive compression

The token target now scales with source size instead of filling a fixed 3K
budget. Balanced anchors are approximately 2K→1.3K, 3.5K→1.9K, 8K→3K,
15K→4.3K, 30K→6.2K and 60K→8.5K. Dense and Safe scale that curve down/up.
The UI defaults to Auto; explicit token choices are caps.

Long verbatim evidence blocks, exhaustive status listings and code listings are
ranked below continuation state. Exact operational marker settings in
STATE/DEC/INV receive protection. NEXT, OPEN, invariants, current bug/state and
the first project goal remain protected.


### v9 canonical context engine

Canonical `<Project>_CONTEXT.md` generation now uses the same adaptive
deterministic compiler as `/compress`. `context_through` is only a freshness
watermark: if a new handoff exists, Register rebuilds from all immutable
handoffs rather than recompressing the previous context. This avoids cumulative
loss. Canonical context generation performs zero AI calls and writes CTX/2.

AI remains intentionally available for human-facing summaries and runbooks.
All local Ollama calls through `_complete()` now send `think: false` by default;
a caller can still explicitly override `think` if a future feature needs it.

### v10 deterministic preprocessing for every AI artifact

AI-generated project summaries no longer receive raw handoffs. Register first
refreshes the canonical deterministic CTX/2 and passes that compact context to
the model. RUNBOOK generation uses CTX/2 plus a second safe-profile deterministic
operational-evidence context, preserving useful commands/config/gotchas without
sending the raw handoff corpus.

Monthly `synthesise.py` uses canonical CTX/2 as its primary per-project input.
If a handoff is newer than `context_through`, that unsynchronised delta is
compressed deterministically before Gemini sees it. Raw handoffs are therefore
not sent directly to the synthesis model. Legacy projects with no CTX/2 yet may
still fall back to their existing human summary.

All local Ollama calls continue to default to `think: false` through `_complete()`.


### v11 model-output sanitisation
AI artifacts are structurally extracted before validation/saving. Summaries select the last complete `## Where it stands` / `## Pick up here` document, preventing untagged Qwen reasoning or earlier drafts from leaking into saved files. `<think>...</think>` stripping remains. Runbooks prefer the final H1. Local Ollama remains `think: false`.


### v12 summary schema and automatic AI routing

Project summaries now contain exactly three sections:

- `## Overview` — 2–4 sentence purpose and broad approach.
- `## Where it stands` — concrete current implementation/deployment state.
- `## Pick up here` — immediate next steps/open decisions.

The output sanitizer selects the **last complete three-section summary**, so Qwen
can emit an unwanted draft/reasoning preamble without either leaking it into the
file or losing the Overview.

Human-facing AI generation also has automatic local/Gemini routing. With
`SUMMARY_BACKEND=local`, Register normally uses Ollama, but switches an individual
summary/runbook generation to Gemini when either compacted prompt size exceeds
`LOCAL_AI_MAX_INPUT_TOKENS` (default `8000`) or the underlying handoff count exceeds
`LOCAL_AI_MAX_SOURCE_DOCS` (default `12`). `GEMINI_API_KEY` must be configured for
automatic escalation; without it Register logs a warning and retains the local
fallback. Set either threshold through Docker/Portainer environment variables.

The routing decision is made **after deterministic compilation**, using the actual
AI prompt token estimate plus the original source-document count. Thus many small
handoffs can trigger Gemini even when CTX/2 is compact, while a small project stays
local. Summary API results expose `source_docs` and `ai_backend`; runbook results do
the same.

Monthly/Sunday cross-project `synthesise.py` already deliberately uses Gemini for
the whole-estate synthesis, so no local-model threshold is needed there.


### v13 coverage-preserving large-project summaries and diagnostic logging

v12 had a counting bug: `_material()` obeyed the legacy `CHAR_BUDGET`, so a project could visibly contain 23 handoffs while the router only counted the first handful that fit the character budget. The same cap also meant canonical CTX/2 could be rebuilt from only that prefix.

v13 separates bounded legacy material from **all handoff material**. Canonical context rebuilds now consume every handoff. Summary routing counts every handoff. When a project exceeds `LOCAL_AI_MAX_SOURCE_DOCS` (default 12) or the canonical context exceeds `LOCAL_AI_MAX_INPUT_TOKENS` (default 8000), and `GEMINI_API_KEY` is available, every handoff is assigned chronologically to a deterministic batch (`LARGE_PROJECT_BATCH_DOCS`, default 6). Each batch is compiled independently with a ceiling of `LARGE_PROJECT_BATCH_TOKENS` (default 5000), then all batch contexts are sent together to Gemini. This prevents a single project-wide selection budget from allowing one topic to dominate.

Logs now state project, true source count, approximate raw/canonical/final prompt tokens, thresholds, strategy, backend, batch count, batch document ranges/titles, per-batch selected units/hard facts/timing, and final output size. Context rebuild and runbook preparation/routing also log true source counts and token estimates.


### v14 authoritative correction propagation

Handoff and debrief prompts now contain a mandatory `## Corrections to previous records`
section. When the current conversation establishes that an earlier handoff/debrief fact was
wrong or materially misleading, the prompt requires a structured record:

```text
- CORRECTION | PREVIOUS: <old claim> | CURRENT: <authoritative claim> | AFFECTS: <...> | EVIDENCE: <...>
```

`CORRECTIONS` is a first-class CTX/2 section with the highest selection weight and hard
protection. It is never discarded to meet a compression target. During deterministic
compilation, Register conservatively matches `PREVIOUS` against earlier active units and
removes matched obsolete units from current-state sections. The immutable source handoff is
unchanged, so the audit trail remains available. CTX/2 also carries an explicit precedence
rule: later corrections override conflicting earlier facts and `PREVIOUS` values are
historical only.

Large-project batching builds a global correction override index across the complete handoff
corpus before the per-batch contexts. This prevents a correction in a later batch from being
separated from the earlier fact it supersedes. Summary and RUNBOOK prompts explicitly apply
`CURRENT` correction values and must not emit `PREVIOUS` values as live state or operational
guidance.

Correction propagation is cross-artifact. `refresh_project()` refreshes canonical context and
human project status, and regenerates the RUNBOOK whenever a correction source is newer than
the current RUNBOOK (or no RUNBOOK exists). The nightly refresh uses this path. Manual summary
or context updates also escalate to the full correction-aware refresh whenever a correction is
not yet represented across all derived artifacts.

Compression/API metadata now reports `corrections` and `corrections_reconciled`, and canonical
context frontmatter records both counts for auditability.
