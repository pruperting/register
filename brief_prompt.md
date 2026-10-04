Produce a complete technical briefing for the project named below, as it
stands **today**. The reader is an AI assistant with no prior knowledge of
this project that is about to help me modify, extend or debug it. It needs
to understand how the thing actually works well enough to make a correct
change on its first attempt.

This is a description of the current system, not a history of it. Do not
write a changelog, do not describe how the design evolved, and do not
mention approaches that were tried and abandoned — unless knowing about
them prevents a mistake now (for example, a library deliberately not used,
or a pattern that looks wrong but is intentional).

Begin the output with exactly this YAML frontmatter, filled in:

```
---
type: context
project: <PROJECT>
date: <today's date, YYYY-MM-DD>
title: <PROJECT> — full project brief
---
```

Then use these sections as Markdown H2 headings, in this order:

**What it is** Two or three sentences: what the project does, who or what
it serves, and the problem it solves. Then a short list of what it
explicitly does *not* do, where that would otherwise be assumed.

**How it works** The architecture in prose and, where it helps, a simple
diagram in a code block. Cover the main components and how they
communicate, the request or data flow from entry point to result, and
which parts are synchronous versus background. Be specific about
mechanisms — name the actual libraries, protocols and patterns used.

**Repository and files** The repo URL, then every significant file and
directory with one line on its role and what lives inside it. A reader
should be able to tell from this section alone which file to open for a
given change. Group by area rather than listing alphabetically. Do not
reproduce file contents — the repo has them.

**Data and state** Where state lives and in what format: databases,
files, schemas, frontmatter conventions, caches, volumes. What is
authoritative, what is derived and can be regenerated, and what would be
lost if a container were destroyed. Include naming conventions that the
code depends on.

**Configuration** Every environment variable and config option: name,
what it does, default, and whether it is required. Mark anything that is
a secret. Note which values have defaults that are wrong for production
use.

**Running it** Exact commands to build, start, stop and check health,
including ports and URLs. How to tell it is working. How to run any
scripts or tools that ship alongside it. Any scheduled jobs, reproduced
verbatim.

**Interfaces** Endpoints, CLI arguments, APIs or UI actions, in a table:
what each does, what it expects, what it returns. Include anything
internal that a developer would need.

**Conventions and rules that still apply** The design rules the code
enforces and the reasoning behind them, stated as current constraints
rather than past decisions. These are the rules a change must not break —
naming schemes, validation, what may write where, invariants held by the
data model. This is the section that prevents a well-intentioned change
from breaking something subtle.

**Known gotchas** Live problems and traps: things that fail silently,
behaviours that look like bugs but are deliberate, environment quirks,
and anything that has bitten before and will again. Give the symptom as
well as the cause, so it is recognisable.

**Current state and limitations** What works, what is unfinished or
stubbed, known bugs, and where the design will not scale. Be honest about
rough edges rather than presenting the project as more complete than it
is.

**Where to make changes** For each of the three or four most likely kinds
of modification, name the files to touch and anything to update alongside
them. This is the practical payoff of the whole document.

Rules for the whole document:

- Describe only what is actually established — from this conversation, the
  repository, and the project's own documents. Where something is unknown,
  write "not documented" rather than inferring it or filling the gap from
  general knowledge about similar systems.
- Be specific: real filenames, real variable names, real ports, real
  command syntax. A brief full of generalities is worthless.
- Write in the present tense throughout.
- Do not reproduce source files that exist in the repository. Reproduce
  only config snippets, commands or schema fragments whose exact wording
  matters and that are not in the repo.
- Never include secrets, API keys, passwords, tokens or private
  credentials. Refer to them by variable name only.
- No preamble, no sign-off, no offers of further help — the document is
  the entire output.
- Name the output file `<PROJECT>-brief-<today's date>.md`.

<REPO_LINE>
I will save your output into my Obsidian vault; the `project:` field above
is what files it.

---

PROJECT: <PROJECT>
