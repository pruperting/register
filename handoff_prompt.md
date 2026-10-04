Please analyse our entire conversation from the beginning and produce a
structured handoff document. Its purpose is twofold: for me to resume this
project after months away, and to be folded automatically into a running
project summary. It must be complete and accurate — but it is a summary,
not a transcript.

Begin the output with exactly this YAML frontmatter, filled in:

```
---
type: handoff
project: <SLUG>
date: <today's date, YYYY-MM-DD>
title: <one-line description of this session>
---
```

The `project` value MUST be copied exactly from the list at the end of
this prompt, including its capitalisation. Do not invent a new slug,
abbreviate one, or coin a variant — an invented slug creates a duplicate
project, and a different capitalisation breaks file syncing. If none of
the listed slugs fits, use the literal value `NEW` and say so in one line
at the very end of your output, after the document.

Then use these sections as Markdown H2 headings, in this order:

**Objective** What we set out to do in this session, in two or three
sentences. If the objective changed partway through, say so and explain
why.

**What changed** What is actually different now that wasn't before —
features added, bugs fixed, files created or modified. Be concrete and
specific. Name files and functions rather than describing changes in the
abstract.

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

**Next steps** Unfinished work, known bugs, and logical next actions, in
priority order. For each, say enough that I could start it cold without
rereading this conversation. Include anything I said I would do but
haven't yet, and anything I explicitly deferred.

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

---

PROJECT SLUGS — copy one of these exactly into the `project:` field:

<SLUG_LIST>
