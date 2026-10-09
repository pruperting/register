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

Return ONE Markdown document, without an outer code fence, preamble or sign-off.
Begin with exactly this YAML frontmatter (quote project and title safely):

---
type: handoff
project: <PROJECT>
date: <today's date, YYYY-MM-DD>
created_at: <CREATED_AT>
title: <short description of the resulting checkpoint>
checkpoint_version: 1
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

Use terse bullets/semicolons where safe. Remove repetition and narrative first,
not tasks, completed work, corrections, decisions, gotchas or technical anchors.
Aim for a compact chat-ready checkpoint appropriate to the project's size;
maximum 15000 estimated tokens (roughly 60000 characters) for the whole document.
The snapshot is complete, so DO NOT rely on Register to union historical sections.

Save as an ordinary .md handoff file named with this conversation and date,
preferably under projects/<PROJECT>/handoffs/. Do not name the upload
<PROJECT>_CONTEXT.md or <PROJECT>_summary.md: those are Register's derived views.
The exact project frontmatter files the document even if Syncthing puts it elsewhere.

PROJECT SLUGS — copy one exact slug, including capitalisation:
<SLUG_LIST>
