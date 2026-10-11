# Obsidian daily-note integration

This feature is **read-only for existing Obsidian notes and checkpoints**. It reads date-named Markdown notes under `DAILY_NOTES_DIR` (default `daily`) in the existing mounted vault. Set `DAILY_NOTES_DIR` in your Register `.env` to the actual folder relative to the vault root. No separate Obsidian plugin is required.

## Daily note

```markdown
# 2026-10-11

## Today
Notes about my day.

## Existing projects
### [[Register]]
- [ ] #high Add a tasks dashboard
- [ ] Review an outstanding issue
- A new correction or decision to reconcile at next checkpoint

### [[Herald]]
- [ ] Verify the morning brief

## New projects / ideas
### [[PotentialIdea]]
- [ ] Explore this idea

## Tomorrow
Other thoughts.
```

Only tasks under project headings in the two designated sections are imported. Existing project headings must be exact registered, non-archived project names; unknown names are visible in the unassigned section. New ideas do not create Register projects.

The Tasks navigation provides a grouped dashboard and `/api/tasks` returns JSON. `/api/obsidian/project-index` generates a Markdown index of exact current project links for use in Obsidian. This endpoint is intentionally read-only; copy the result into your vault's Project Index note if desired.

The `/api/context/<Project>` full and compact copies and the project-specific handoff prompt include a labelled *pending evidence* section ahead of the accepted checkpoint, leaving its stored content and CHECKPOINT_ID untouched. The weekly Gemini review also sees pending note evidence. Obsidian checklist completion is never used to infer completion of existing checkpoint tasks.

## Scope and limitations

- No automatic task editor or reconciliation ledger: the same note task remains pending until a future mechanism explicitly records its acceptance into a new checkpoint.
- The parser does not detect standalone prose outside project sections. For predictable behaviour, write bullets and checkboxes under exact project headings.
- The dashboard deliberately displays checkpoint and note tasks separately; similar phrasing is not automatically merged.
- Project index is generated on demand, not automatically written to the user's vault.
- No migraine fields are included in daily-note parsing.
- Run `python -m pytest -q` from the repository and confirm server behaviour before merging/deploying.
