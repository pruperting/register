# Persistent AI context checkpoints

Register maintains `<Project>_CONTEXT.md` alongside the human project summary and optional RUNBOOK.

## Current behaviour

- Canonical context is deterministic `CTX/2`; no LLM decides what facts survive.
- `context_through` is a freshness watermark only. When new material exists, Register rebuilds from every immutable handoff/debrief rather than recompressing the previous checkpoint.
- Hard-protected units cannot be discarded to meet a nominal token target.
- Generated context files are excluded from source material.
- Writes are atomic (`fsync` + `os.replace`).
- Rename/merge operations discard stale generated contexts so they can be rebuilt under the resulting project identity.
- The nightly refresh calls `refresh_project()`, which updates canonical context and human status. A newer explicit correction also forces RUNBOOK regeneration.
- Large projects are compiled in chronological deterministic batches and routed to Gemini when configured; every source handoff remains covered.

## Authoritative corrections

Handoff/debrief documents may contain `## Corrections to previous records` with records in this exact shape:

```text
- CORRECTION | PREVIOUS: <old claim> | CURRENT: <authoritative claim> | AFFECTS: <...> | EVIDENCE: <...>
```

Corrections are first-class hard-protected context units. Later corrections override conflicting earlier material. During whole-project deterministic compilation, Register conservatively removes an earlier active unit when its claim matches `PREVIOUS`; the correction record remains, preserving both audit history and the authoritative `CURRENT` value. A correction that cannot be matched mechanically is still retained verbatim and remains authoritative through the CTX/2 correction-precedence rule.

For large-project summary batching, Register also prepends a global correction override index built from the complete source corpus so a correction and the fact it supersedes cannot become isolated in different batches.

## UI/API

Project pages expose **AI context** generate/update/rebuild/copy/download controls.

- `GET /api/context/<project>` returns the context body as plain text.
- `GET /api/context/<project>?download=1` downloads it.
- `POST /api/context/<project>` refreshes it; if an unpropagated correction exists, Register performs the full correction-aware project refresh.
- `POST /api/context/<project>` with `{"full": true}` forces a full rebuild.

## Deploy

Rebuild the existing image:

```bash
docker compose up -d --build
docker compose logs -f register
```
