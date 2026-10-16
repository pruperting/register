Use the ENTIRE conversation as the evidence to produce a COMPLETE replacement
project checkpoint, not a session delta or transcript. Register will import your
finished document directly; no later AI will repair, summarise or merge it.

PROJECT: <PROJECT>
REPOSITORY: <REPO>
<PROJECT_SELECTION_RULE>

The prior checkpoint below describes the project BEFORE this conversation.
Reconcile it against all work and evidence in this conversation. Carry forward
still-valid facts, technical anchors, deployment commands and constraints.
For every prior OPEN/NEXT item, record whether it is DONE, still OPEN/NEXT,
REJECTED, or SUPERSEDED. Never infer completion from silence, agreement or a
proposal. Keep completed work in DONE and implemented reality in STATE.
Retain relevant older DONE entries, corrections and rejected approaches so the
next AI knows what was tried, completed and remains outstanding.

<prior_project_checkpoint>
CHECKPOINT_ID <BASED_ON>
<CURRENT_CHECKPOINT>
</prior_project_checkpoint>

Produce TWO separate Markdown files: the complete ACTIVE checkpoint and
its RETIRED knowledge sidecar. Never concatenate both into a single .md file.
FILE 1 starts with exactly the YAML frontmatter below. FILE 2 is specified
later in this prompt. No preamble or sign-off belongs in either saved file.
Begin with exactly this YAML frontmatter (quote project and title safely):

---
type: handoff
project: <PROJECT>
date: <today's date, YYYY-MM-DD>
created_at: <CREATED_AT>
title: <short description of the resulting checkpoint>
checkpoint_version: 1
retired_sidecar: true
based_on: <BASED_ON>
project_status: <running/building/paused/idea/retired, or omit if not established>
<RECONCILES>
---

If a reconciles list is supplied, copy it exactly and reconcile ALL the conflicting
versions supplied below into the complete replacement. Never discard a conflict
by selecting only the version you prefer.

Copy based_on exactly; it links this update to its starting checkpoint. Do not
invent a timestamp: use the supplied created_at value. If you used a DIFFERENT
starting checkpoint in this conversation, use its CHECKPOINT_ID instead and
explain the discrepancy to the owner before finalising. Use ROOT only for a
new project with no prior evidence. For existing projects, use the project-
specific prompt so Register can provide the correct starting identity.

Then output exactly these two Markdown H2 headings, in this order:

## Human summary

A brief, readable Markdown summary (roughly 150–300 words, less for a small
project) with two short paragraphs:

1. **Project overview:** explain what the project is, who or what it serves,
   the problem it solves, its main capabilities and its overall current state.
   Make this self-contained for someone who has never seen the project. Retain
   its still-valid purpose and capabilities from the prior checkpoint even when
   this conversation focused on a small fix; do not replace the overview with
   a release note or a list of this session's changes.
2. **Recent progress and next steps:** explain the latest meaningful changes,
   verified completed work, outstanding issues and immediate next actions.
   Distinguish recent progress from the project's overall description.

Use plain language and mention important decisions where they help explain the
project. Preserve uncertainty. Do not claim a local commit was pushed or deployed without evidence.
This is the summary Register displays in its UI; it must agree with CTX/2.

## AI checkpoint

Start with CTX/2, followed by ALL the following plain section headings exactly
once, in this order. No Markdown # prefixes on the CTX headings. Put a single
- beneath any empty section; absence never means "inherit older content".

CTX/2
GOAL
- Stable project purpose and current objectives.
STACK
- Environment, deployment state, hosts, ports, mounts, versions, env variable NAMES; known build/start/schedule commands.
ARCH
- Current architecture, service interactions, authority model and dependencies.
FILES
- Repository URL, relevant paths, symbols, APIs and schemas; ad-hoc code/config not stored in a repo, where necessary.
STATE
- CURRENT implemented reality, latest verified results and deployment status; distinguish built/committed/pushed/deployed.
DONE
- Verified completed tasks and outcomes, including relevant carry-forward completions; retain IDs if available.
CORRECTIONS
- CORRECTION | PREVIOUS: <earlier wrong/superseded claim> | CURRENT: <authoritative value> | AFFECTS: <affected area> | EVIDENCE: <evidence>
DEC
- Decisions and rationale; distinguish chosen-but-pending designs from implementations.
INV
- Invariants, constraints, things that must remain true.
BUG
- Known bugs, exact errors, symptoms, fixes, gotchas, and useful failed attempts.
OPEN
- Unresolved issues, blockers, uncertainties and remaining TODOs; preserve IDs if available.
NEXT
- Ordered outstanding actions with enough detail to resume cold; preserve task IDs if available.
REJECTED
- REJECTED/SUPERSEDED tasks, designs and approaches with brief reasons; don't retry them silently.
FACTS
- Other continuation-critical facts, estate changes, or evidence not covered above.

Preserve every still-useful implementation literal: exact paths, filenames,
function/class names, endpoints, schema/table/column names, versions, ports,
commands, config, important numbers and relevant error text. Code fences are
allowed INSIDE section bodies for commands/config. Never include secret values,
API keys, passwords, private keys or tokens; retain environment variable names
and outstanding remediation tasks instead.

Explicit corrections outrank conflicting earlier facts. PREVIOUS is historical
only: never present it as current config elsewhere. Carry forward useful
correction audit records. Record new corrections in the exact structured shape
above rather than just omitting the old fact. Preserve unknowns as unknown;
never fill gaps from general knowledge.

Produce the compact, authoritative project knowledge during this handoff,
not a verbose transcript that will need downstream compression. Use each
unique fact once in its most relevant CTX/2 section; where a second section
needs the same point, cross-reference it briefly rather than duplicating its
full detail. Combine equivalent statements only when they really express the
same fact. Explicit corrections must retain PREVIOUS, CURRENT and EVIDENCE;
never silently merge conflicting claims or treat a proposal as deployed.
Use concise complete sentences or terse bullets/semicolons, but never remove
negations, uncertainty, time/status distinctions, commands, paths, numbers,
completed work, unresolved tasks or reasoning needed to resume accurately.
Prioritise factual fidelity over artificial brevity and do not pad to a token
target. Register's local /compress page is not a second semantic summariser.
SIZE CONTRACT — enforce this BEFORE returning the final document:
- Target no more than <HANDOFF_TARGET_TOKENS> estimated tokens for the entire
  body, from `## Human summary` through the last CTX/2 line (roughly
  <HANDOFF_TARGET_TOKENS> × 4 characters). The warning threshold is
  <HANDOFF_WARN_TOKENS> estimated tokens.
- The absolute Register rejection limit is <HANDOFF_HARD_MAX_TOKENS>
  estimated tokens for that same body. NEVER output a larger document.
- Before finalising, estimate body tokens as round(character_count / 4),
  including the human summary, all headings, lists and code. Leave headroom
  rather than aiming at the hard limit. If too long, revise and check again.
- Remove repetition, verbose narration and superseded historical detail FIRST.
  Keep every still-valid decision, technical literal, task, correction, bug,
  deployment distinction and essential implementation fact; do not turn a
  substantive section into `-` just to reach the target. Preserve every one
  of the fourteen sections in the prescribed order.
- Complete the document within the cap; never send a truncated, partial,
  delta-only or multi-part checkpoint. Register does not merge old sections.

Save FILE 1 as an ordinary .md handoff file named with this conversation and date,
preferably under projects/<PROJECT>/handoffs/. Do not name the upload
<PROJECT>_CONTEXT.md or <PROJECT>_summary.md: those are Register's derived views.
The exact project frontmatter files the document even if Syncthing puts it elsewhere.



RELEVANCE REVIEW — DO THIS BEFORE WRITING FILE 1:
Review EVERY item in the prior checkpoint, especially FACTS, CORRECTIONS,
DONE, BUG and REJECTED. Assign an internal disposition: CURRENT (retain),
UPDATED (keep authoritative current information in a suitable section), or
RETIRED (historical material no longer needed for safe resumption). Every
previous OPEN/NEXT item must be explicitly reconciled; never retire an
unresolved task just because it is old. Age alone is NOT a retirement reason.

Retire one-off diagnostics, old mistaken assumptions, superseded intermediate
implementations and redundant historical detail only when their removal will
not impair future decisions. Retain corrective lessons that prevent a repeated
mistake and any currently needed command, restriction, known failure mode or
technical fact. A useful current fact from a retired CORRECTION must still
appear in the active checkpoint. Do not silently drop an older claim: if you
classify it RETIRED, reproduce its substantive meaning in FILE 2. If a fact
is only rewritten into a clearer current statement, it is UPDATED, not lost.

OUTPUT TWO SEPARATE .md FILES (NEVER ONE CONCATENATED MARKDOWN FILE):
FILE 1 is the complete active checkpoint specified above. Its frontmatter MUST
contain retired_sidecar: true, linking it to FILE 2. The AI-facing token target
and hard cap apply to FILE 1 (the active checkpoint), not FILE 2. If your AI
interface supports creating two downloadable files, deliver both. Otherwise
produce clearly labelled FILE 1 and FILE 2 separately, each in its own
Markdown code block for manual saving; do not include labels or outer code
fences INSIDE the saved files.

FILE 2 is the retired-knowledge sidecar, saved alongside FILE 1 in the same
projects/<PROJECT>/handoffs/ folder under a DISTINCT filename ending
-retired.md. Use this EXACT YAML shape and the same 14 CTX/2 sections as FILE 1:

---
type: retired-knowledge
archive_version: 1
project: <PROJECT>
retired_from: <BASED_ON>
paired_created_at: <CREATED_AT>
title: "Retired knowledge from this checkpoint update"
---
CTX/2
GOAL
-
STACK
-
ARCH
-
FILES
-
STATE
-
DONE
-
CORRECTIONS
-
DEC
-
INV
-
BUG
-
OPEN
-
NEXT
-
REJECTED
-
FACTS
-

Replace each '-' with material RETIRED from that corresponding section of the
prior checkpoint. All 14 headings must be present once and in order; use '-' in
sections with no retirement. Preserve historical context precisely (including
negations, numbers, reasons and useful literals), but do not put passwords,
API keys or secrets in either output. FILE 2 must contain no Human summary and
no active instructions. Its statements are historical, not authoritative.
Even if nothing was retired, still produce FILE 2 with all fourteen sections
set to '-': Register requires the pair to avoid an unnoticed knowledge-loss gap.
Register retains every original handoff and every retired sidecar unchanged,
then builds a separate cumulative historical file for optional recovery. This
historical file is not consulted by the normal project prompt or active state.

PROJECT SLUGS — copy one exact slug, including capitalisation:
<SLUG_LIST>
