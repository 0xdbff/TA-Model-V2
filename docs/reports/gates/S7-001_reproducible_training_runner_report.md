# S7-001 Reproducible Training Runner Evidence

Date: 2026-06-04
Issue: #31 / S7-001

## Requirement trace

- FR-008: adds the reusable training-run foundation for later probabilistic candidate work.
- NFR-005: run IDs resolve dataset snapshot, config, code commit, seed, metrics, and artifacts.
- FR-007 prerequisite: consumes existing S4/S5 dataset/baseline-era contracts without replacing baseline gates.

## Scope and anti-drift checks

- Implemented runner scaffolding only; no S7-002 candidate architecture, MLflow registry state, calibration/ablation report, paper/live routing, leverage, derivatives, live capital, online self-update, or auto-promotion.
- Reference trainer is explicitly marked `runner_evidence_only` and is not a promotable model candidate.
- Dataset labels remain outputs. The runner trains only from train-split labels and evaluates configured non-train splits after DatasetSnapshot point-in-time validation.
- Fails closed for empty train split, empty evaluation split, missing code commit, duplicated/non-chronological rows, label timestamp violations, and reconstructed dataset hash/snapshot mismatches.

## Implementation evidence

- Contracts: `src/ta_model/contracts/training.py`
  - `TrainingConfig` with deterministic `training_config_hash` / `training_config_id`.
  - `TrainingRunResult` with deterministic `training_run_hash` / `training_run_id`.
  - `TrainingMetric` and `TrainingArtifactReference` reject invalid/non-finite metric and artifact states.
- Runner: `src/ta_model/training/runner.py`
  - Consumes an existing `DatasetSnapshot` and `TrainingConfig` plus explicit `code_commit`.
  - Produces run lineage over `dataset_snapshot_id`, `dataset_hash`, config, code commit, seed, metrics, and deterministic artifact references.
- Tests: `tests/test_training_runner.py`
  - Deterministic rerun stability.
  - Identity changes for seed/config/dataset/commit.
  - Required lineage/artifact fields.
  - Fail-closed invalid prerequisites and reconstructed dataset hash mismatch.

## Docker/runtime impact

- No runtime service impact.
- No Docker/Compose profile changes.
- No new dependencies, model weights, private tokens, or external downloads.

## Validation commands

- `uv run ruff check .` — passed (`All checks passed!`).
- `uv run mypy src tests` — passed (`Success: no issues found in 57 source files`).
- `uv run pytest tests/test_training_runner.py tests/test_dataset_snapshot_builder.py tests/test_deterministic_baselines.py tests/test_evaluation_scorecard.py` — passed (`47 passed in 0.31s`).
- `uv run pytest` — passed (`221 passed in 2.42s`).

## Downstream notes

- #32 can replace or extend `TrainerKind` with a real probabilistic candidate while preserving run-result lineage.
- #33 can map `TrainingRunResult` fields into MLflow metadata without this issue introducing registry states.
- #34 can consume metrics/artifacts for validation reporting; calibration/ablation details remain out of scope here.
