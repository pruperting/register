Please analyse our entire conversation from the beginning and produce a
structured handoff document. Its purpose is twofold: for me to resume this
project after months away, and to be folded automatically into a running
project summary. It must be complete and accurate — but it is a summary,
not a transcript.

Begin the output with exactly this YAML frontmatter, filled in:

```
---
type: handoff
project: <PROJECT>
date: <today's date, YYYY-MM-DD>
created_at: <CREATED_AT>
title: <one-line description of this session>
---
```

<PROJECT_SELECTION_RULE>

Before writing the handoff, reconcile the full conversation against the
project checkpoint below.

PROJECT: <PROJECT>
REPOSITORY: <REPO>

The checkpoint describes the project BEFORE this conversation. It is evidence
from previous handoffs, not a description that you should blindly repeat.

<prior_project_checkpoint>
<CURRENT_CHECKPOINT>
</prior_project_checkpoint>

Your most important job is to work out what THIS conversation changed.

For every prior OPEN or NEXT item:
- if it was completed in this conversation, explicitly record that it is now
  completed/current and do not carry it forward as unfinished work;
- if it is still unfinished, carry it forward under Open issues or Next steps;
- if it was abandoned, rejected, replaced, or made irrelevant, say so
  explicitly using REJECTED or SUPERSEDED;
- if its wording changed but the work remains outstanding, preserve the actual
  remaining work rather than creating a second duplicate task.

For prior STATE/current facts:
- preserve them only when this conversation did not replace or disprove them;
- if this conversation changed a value, architecture, deployment state,
  implementation status, path, command, dependency, or decision, record the
  new value and add a strict CORRECTION when the previous record is now wrong;
- never mark something completed merely because it was proposed, discussed,
  planned, approved, or reacted to positively.

Use the ENTIRE conversation as the evidence for this reconciliation. You are
the AI that participated in the work, so perform this reconciliation here
rather than leaving it for a later summariser to infer.

Then use these sections as Markdown H2 headings, in this order:

**Objective** What we set out to do in this session, in two or three
sentences. If the objective changed partway through, say so and explain
why.

**What changed** What is actually different now that wasn't before —
features added, bugs fixed, files created or modified. Be concrete and
specific. Name files and functions rather than describing changes in the
abstract.

**Current state** Reconcile the starting checkpoint with this entire
conversation and state the important CURRENT position at session end. Include
implemented/running facts that the next AI genuinely needs. Do not simply copy
the prior checkpoint. Do not put planned or unresolved work here.

**Corrections to previous records** Review the current conversation for any
evidence that a fact in an earlier handoff, debrief, project status, AI context,
or runbook was wrong, misleading, materially incomplete, or has since been
disproved. If so, call the correction out explicitly here — do not merely state
the new value and leave the old claim ambiguous. Each correction MUST be one
bullet using exactly this shape:

`- CORRECTION | PREVIOUS: <the earlier wrong claim/value> | CURRENT: <the corrected authoritative claim/value> | AFFECTS: <project/status/AI context/runbook as applicable> | EVIDENCE: <what in this conversation established the correction>`

Use one record per corrected fact. `PREVIOUS` is historical/audit information;
`CURRENT` is authoritative from this point onward. If this conversation surfaced
no correction to an earlier record, write exactly `none`. Corrections are
continuation-critical and must never be omitted for brevity.

**Decisions and constraints** Key decisions with the reasoning behind
them, and any constraints we worked within. Distinguish clearly between
what was decided and implemented, what was suggested but not acted on,
and what remains open. Do not present an idea I merely reacted well to as
a settled decision.

**Estate changes** Only what this session changed or newly established
about physical hardware, storage, or network. The full inventory lives in
`projects/_estate/hardware.md`; do not reproduce it. If nothing physical
changed, write "none". If something contradicts that document, say so.

**Environment and deployment** Anything needed to run this: host, ports,
paths, mounts, environment variables, image and container names, exact
build and start commands, pinned dependency versions that matter,
scheduled jobs reproduced verbatim. Carry forward what is known from
earlier sessions and mark it as such; write "not discussed" only where
nothing has ever been established — do not reconstruct plausible commands
from general knowledge, and do not restate a value I corrected during the
session in its uncorrected form.

**Workarounds and gotchas** The non-obvious things: what broke and why,
what the fix was, what looks wrong but is intentional, anything that will
confuse me in three months. This is the highest-value section — be
generous with it. Include the symptom as well as the fix, so I can
recognise the problem if it recurs. Include any conclusion you reached
during the session that later turned out to be wrong, and the reasoning
that misled you.

**Code** Carry-forward section for anything not stored in a repository.
List files created or changed with a one-line description of each.
Reproduce literal code or commands in full where they are (a) not saved
anywhere on disk, (b) a config snippet, cron entry or command whose exact
wording matters, or (c) a fix whose detail would be lost in prose. Any
ad-hoc command or one-liner that took more than one attempt to get right
must be reproduced verbatim. Do not reproduce full contents of files that
live in a repository; name the repo and path instead.

**Dependencies and interactions** How this connects to the rest of the
system — other services it talks to, files that must change together,
anything elsewhere that would break if this changed. Explicitly note
anything that would fail silently rather than erroring.

**Open issues** Unresolved problems, blockers, uncertainties, or previously
open items that remain unresolved at session end. Do not include an old issue
if this conversation solved it. Write `none` if there are no known open issues.

**Next steps** Unfinished work and logical next actions, in priority order.
Reconcile this against the starting checkpoint: remove work completed in this
conversation, retain work that really remains, explicitly account for deferred
items, and add genuinely new next actions. For each item say enough that I
could start it cold without rereading this conversation.

Rules for the whole document:

- Only record what this conversation actually establishes. Where
  something is unknown or wasn't covered, write "not discussed" rather
  than inferring or filling the gap from general knowledge.
- Prefer specifics over summary language: exact filenames, values, error
  messages, version numbers, port numbers.
- Note anything we tried that did not work and was abandoned, so I don't
  repeat it.
- Write for me alone, months from now, with no memory of this session. No
  preamble, no sign-off, no offers of further help — the document is the
  entire output.
- Name the output file with the title of the conversation alongside
  today's date, as a markdown file.

I will save your output into my Obsidian vault. It does not matter which
folder it lands in — the `project:` field above is what files it.

CONTEXT CHECKPOINT RULES — these make the handoff safe to merge into the
project's compact AI checkpoint:

- For implementation-relevant facts, make the state explicit where ambiguity
  is possible: CURRENT, SUPERSEDED, OPEN, or REJECTED.
- Preserve exact filenames and paths, function/class names, API endpoints,
  environment variables, database/schema names, versions, ports, commands,
  important numeric values, and exact error text where it matters.
- When a new fact replaces an older one, explicitly say what is superseded;
  do not merely omit the old value. If the earlier value appeared in a previous
  handoff/debrief, also record it in `## Corrections to previous records` using
  the strict `CORRECTION | PREVIOUS | CURRENT | AFFECTS | EVIDENCE` form above.
- Explicit corrections outrank every conflicting earlier record. Never restate
  a corrected PREVIOUS value as CURRENT elsewhere in this handoff.
- Do not call a proposal CURRENT unless it was actually implemented or the
  conversation explicitly established it as the chosen design.
- Treat the prior checkpoint as the starting position, not as text to repeat.
  The finished handoff must reflect the state AFTER this conversation.
- Never carry a prior NEXT/OPEN item forward merely because it existed before.
  First decide from the full conversation whether it was completed, remains
  open, or was rejected/superseded.
- Conversely, never infer completion from silence. A prior unfinished item
  remains unfinished unless this conversation provides evidence that it was
  completed, rejected, superseded, or no longer applicable.

---

PROJECT SLUGS — copy one of these exactly into the `project:` field:

<SLUG_LIST>
