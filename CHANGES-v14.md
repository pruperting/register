# v14 — authoritative correction propagation

## Added

- Mandatory `## Corrections to previous records` instructions in both handoff and debrief prompts.
- Strict correction record format: `CORRECTION | PREVIOUS | CURRENT | AFFECTS | EVIDENCE`.
- First-class `CORRECTIONS` CTX/2 section with highest selection weight and hard protection.
- Deterministic reconciliation that removes conservatively matched earlier active facts while retaining immutable source history.
- Explicit CTX/2 correction precedence: later corrections override conflicting earlier facts; PREVIOUS values are historical only.
- Correction-chain protection: correction records are never near-duplicate-deduplicated.
- Global correction override index for coverage-preserving large-project Gemini batches.
- Correction-aware summary and RUNBOOK prompts.
- `refresh_project()` to propagate corrections across canonical context, human project status and RUNBOOK.
- Manual summary/context updates escalate to the full refresh when a correction is not yet propagated.
- Nightly refresh now uses `refresh_project()`.
- Whole-estate synthesis preserves correction overrides even when an oversized project is clipped.
- Correction/reconciliation counts in compressor results and canonical-context frontmatter.

## Verification

Regression tests cover:

- deterministic context rebuild/freshness;
- earlier active fact removal by a later explicit correction;
- correction retention under a tight compression budget;
- multi-step correction chains (A→B→C) surviving deduplication;
- global correction overrides across separate large-project batches;
- `none` correction sections not triggering propagation;
- correction-driven RUNBOOK regeneration.
