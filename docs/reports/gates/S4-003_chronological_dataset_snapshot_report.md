# S4-003 Chronological Dataset Snapshot Gate Report

Issue: #21  
Sprint: S4-003  
Requirements: FR-006, NFR-005; preserves FR-004, FR-005, NFR-001

## Scope delivered

- Added fixture/local chronological dataset contracts and builder for point-in-time `FeatureVector` inputs.
- Stored deterministic dataset snapshot ID/hash, feature versions, feature/vector lineage, split windows, label rule, row IDs, row counts by split, and source feature snapshot IDs.
- Implemented explicit future label observations/rules with label timestamps strictly after `feature_ts`.
- Assigned train/validation/test splits only from feature availability time (`feature_ts`).

## Acceptance evidence

- Deterministic dataset hash and row IDs are contract-tested.
- Feature versions, source feature snapshot IDs, and split row counts are stored and validated.
- Missing labels, duplicate/non-monotonic feature times, duplicate/non-monotonic label event times, overlapping or misordered split windows, and label-as-feature leakage fail closed.
- Future label mutation changes only rows whose configured horizon uses that observation.
- Future feature mutation does not alter earlier rows.

## Validation commands

Executed locally in this PR branch:

1. `uv run ruff check .` — passed (`All checks passed!`)
2. `uv run mypy src tests` — passed (`Success: no issues found in 34 source files`)
3. `uv run pytest` — passed (`118 passed in 0.55s`)

## Docker/runtime impact

No Docker, Compose, runtime service, database, broker, object storage, or external API changes.

## Anti-drift checks

- Event-time correctness: split assignment uses `feature_ts`; no ingest timestamp participates in IDs or hashes.
- Leakage prevention: labels are explicit row outputs, never feature values; `label_ts > feature_ts` is enforced.
- Reproducibility: row IDs and dataset hash are derived from deterministic feature, split, label, and lineage fields.
- MVP scope preserved: fixture/local spot examples only; no leverage, derivatives, margin, shorting, model training, strategy, risk/order path, paper/live routing, or live capital.

## Risks / follow-ups

No known S4-003 acceptance blockers. Downstream S4-004 can consume the dataset contract for baseline training without adding storage/runtime adapters.
