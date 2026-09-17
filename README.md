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

Each project gets a summary with two sections: **Where it stands** and
**Pick up here**. Optionally a `RUNBOOK.md` too: build commands, config,
workarounds and gotchas, meant to be copied into that project's own repo.

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

A nightly job folds new handoff notes into each project's summary. It
skips projects with nothing new (costing no model calls at all) and
projects with no handoff notes, and is capped per run.

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

**`GET /prompt`** — serves the end-of-session handoff prompt with your
current project slugs embedded, so the model can't invent a new one. There
is a copy button in the UI header.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/summary/<project>` | generate or update a summary (`{"full": true}` to rebuild) |
| `POST /api/runbook/<project>` | generate RUNBOOK.md |
| `POST /api/status/<project>` | `running`, `building`, `paused`, `idea`, `retired` |
| `POST /api/archive/<project>` | `{"archived": true}` |
| `POST /api/rename/<project>` | `{"new": "NewName"}` |
| `POST /api/merge` | `{"sources": [...], "target": "..."}` |
| `POST /api/file` | resolve an unfiled claim |
| `GET /api/jobs/<key>` | poll a background job |
| `GET /api/stats` | counts |

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
