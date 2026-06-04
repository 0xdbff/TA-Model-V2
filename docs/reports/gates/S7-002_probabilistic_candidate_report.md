# S7-002 Probabilistic Candidate Output Evidence

## Scope

- Issue: #32 / S7-002.
- Outcome: first deterministic, fixture-safe probabilistic candidate layer over `DatasetSnapshot`.
- Boundary: non-promotable candidate outputs only; no registry transitions, model gate report, risk/strategy route, paper/live gateway, leverage, derivatives, downloaded weights, Hugging Face assets, or live capital.

## Requirement trace

- FR-008: adds forecast/candidate output contracts with probabilities, quantiles, uncertainty, calibration metadata, and training-run lineage.
- FR-014: exposes output fields required for downstream evaluation (#34) without performing promotion or gate decisions.
- FR-007: keeps baseline prerequisite untouched; no baseline contracts or gate behavior changed.
- NFR-005: deterministic forecast IDs, model-version hashes, output hashes, dataset hashes, code commit, and training-run IDs support reproducible reruns.

## Acceptance evidence

1. Added strict/frozen Pydantic forecast contracts in `src/ta_model/contracts/forecasts.py`.
   - Rejects invalid probability sums/ranges, non-monotonic quantiles, non-finite uncertainty, in-sample train forecasts, missing calibration status, empty output artifacts, mismatched nested output lineage, and ID/hash lineage conflicts.
   - Forecast identity binds dataset snapshot/hash, training run ID/hash, model version ID/hash, row ID, probabilities, quantiles, uncertainty, and calibration metadata.
2. Added deterministic candidate trainer/scorer in `src/ta_model/training/probabilistic_candidate.py`.
   - Fits probabilities, quantiles, and uncertainty from train-split labels only, conditioned by point-in-time `one_bar_return` feature sequences.
   - Scores configured out-of-sample splits from feature sequences available at or before each row `feature_ts` and S7-001 `TrainingRunResult` lineage.
3. Added tests in `tests/test_probabilistic_candidate.py` for deterministic outputs, dataset/config/commit/seed identity changes, invalid contract rejection, lineage conflict rejection even with rebuilt IDs/hashes, out-of-sample enforcement, feature-conditional scoring, and train-only/no-lookahead behavior.

## Docker/runtime impact

- No new runtime service, datastore, broker, registry, workflow engine, Docker profile, or Compose change.
- No new dependency was added; PyTorch/HF/checkpoints/tokens/downloaded weights were intentionally avoided.
- Existing local/CI Python runtime remains unchanged.

## Anti-drift checks

- S7-001 deterministic SHA/out-of-sample guards are preserved and covered by existing runner tests.
- Candidate uses validation/test labels only as future downstream evaluator inputs; S7-002 trainer/scorer does not read them for fitted parameters.
- Forecasts are explicitly out-of-sample and non-promotable; registry/model promotion work remains for #33/#34.
- No live/paper route, risk bypass, strategy decision path, or order gateway path was introduced.

## Validation commands

- `uv run ruff check .` — PASS.
- `uv run mypy src tests` — PASS.
- `uv run pytest tests/test_training_runner.py tests/test_probabilistic_candidate.py tests/test_dataset_snapshot_builder.py tests/test_s4_leakage_parity.py` — PASS, 32 tests.
- `uv run pytest` — PASS, 227 tests.

## Assumptions and downstream notes

- The first candidate is a deterministic feature-sequence-conditioned distribution baseline, intentionally small and dependency-free.
- #34 can consume `Forecast` and `ProbabilisticCandidateOutput` for model/evaluation gate reports.
- Calibration status is `sequence_conditioned_train_only`; no claim of promotion readiness or calibrated production model quality is made.
