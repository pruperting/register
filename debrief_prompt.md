Please produce a complete technical debrief of this project as it stands
**today**. Its purpose is to be pasted at the start of a new AI
conversation so that assistant can immediately continue building on the
current deployment, with no other context.

This is NOT a session summary and NOT a history. Do not narrate how the
project evolved, what was tried and abandoned, or what changed recently,
unless that information is still needed to work on it safely. An
architectural decision matters; the three sessions it took to reach it do
not. Write it as though describing a system you are seeing for the first
time and must hand to a competent engineer.

Begin the output with exactly this YAML frontmatter, filled in:

```
---
type: debrief
project: <PROJECT>
date: <today's date, YYYY-MM-DD>
title: <project name> — full technical debrief
repo: <REPO>
---
```

Then use these sections as Markdown H2 headings, in this order:

**What this is** Two or three sentences: what the project does, who uses
it, and what problem it solves. Then a short paragraph on the core design
idea — the one thing someone must understand before the rest makes sense.

**Corrections to previous records** This is the one deliberate exception to the
"not a history" rule. Review the current conversation for any evidence that a
fact in an earlier handoff or debrief was wrong, misleading, materially
incomplete, or has since been disproved. If so, explicitly preserve the
correction so downstream Register documents cannot resurrect the bad value. Each
correction MUST be one bullet using exactly this shape:

`- CORRECTION | PREVIOUS: <the earlier wrong claim/value> | CURRENT: <the corrected authoritative claim/value> | AFFECTS: <project/status/AI context/runbook as applicable> | EVIDENCE: <what established the correction>`

Use one record per corrected fact. `PREVIOUS` is historical/audit information;
`CURRENT` is authoritative from this point onward. If there are no corrections,
write exactly `none`. Do not hide a correction by simply describing only the
new state elsewhere in the debrief.

**How it works** The architecture in prose and, where it helps, a small
diagram or flow in a code block. Cover the request or data path end to
end, what stores state and where, what runs on a schedule, and what talks
to what. Be concrete about mechanisms, not intentions.

**Components and files** Every meaningful file or module with a one-line
description of its responsibility. Group by directory. Name the important
functions and classes within each, and say what each is responsible for.
Do not paste file contents — the code is in the repository named above.
Flag anything whose purpose is not obvious from its name.

**Data and storage** What data exists, in what format, where it lives, and
what owns it. Schemas, file layouts, frontmatter fields, database tables,
directory conventions — whatever applies. Include naming conventions and
say which are load-bearing rather than cosmetic.

**Configuration** Every environment variable and config value: name,
purpose, default, and whether it is required. Note which contain secrets
and where the real values live. Use a table.

**Running and deploying it** Exact commands to build, start, verify and
update, in order. Ports, hosts, mounts, container names, dependencies on
other services. Include how to tell that a deploy actually worked, not
just that a command exited cleanly.

**Key approaches and conventions** The design decisions that are still
live constraints: why state is held the way it is, what the naming rules
are, which invariants must not be broken, and what a change would break if
someone ignored them. These are the things a new contributor would
otherwise violate without noticing.

**Gotchas that still apply** Non-obvious behaviour, known traps, things
that look wrong but are intentional, and failure modes that are silent
rather than loud. Only include what is still true of the current code —
drop anything that was fixed. For each, give the symptom as well as the
cause, so it can be recognised.

**Current state and limitations** What works, what is unfinished, what is
known to be weak, and what has deliberately been left out of scope. Be
honest about rough edges; an assistant that believes the system is more
complete than it is will make bad suggestions.

**Extending it** What a new assistant most likely needs to do next, and
where in the codebase that work would start. Describe the shape of the
obvious next changes without prescribing an implementation.

Rules for the whole document:

- Describe the system as it is **now**. If code was replaced, describe only
  the replacement, except that `## Corrections to previous records` must retain
  explicit PREVIOUS → CURRENT correction records when this conversation exposed
  an error in earlier handoff/debrief material.
- Explicit corrections outrank every conflicting earlier record. Never present
  a PREVIOUS value from a correction as live state, configuration, or guidance.
- Only state what this conversation and the repository actually establish.
  Where something is genuinely unknown, write "not established" rather
  than inferring a plausible answer — a confident wrong detail about
  deployment is worse than an admitted gap.
- Be specific and technical: real file names, function names, ports,
  environment variable names, exact commands. Assume the reader is a
  competent engineer who has never seen this project.
- Never include API keys, passwords, tokens, private IP addresses,
  personal file paths, or any other credential or personal data. Refer to
  them by variable name only.
- No preamble, no sign-off, no offers of further help — the document is
  the entire output.
- Name the output file `<project>-debrief-<today's date>.md`.

The project's code is at the repository named in the frontmatter above.
Assume whoever reads this document can also read that repository, so
describe structure and responsibility rather than reproducing source.

---

PROJECT: <PROJECT>
REPOSITORY: <REPO>
