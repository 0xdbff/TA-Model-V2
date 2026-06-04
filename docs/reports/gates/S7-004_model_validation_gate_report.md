# S7-004 Model Validation/Gate Evidence Report

## Scope and traceability

- Issue/Sprint: #34 / S7-004.
- Requirements: FR-008, FR-014, FR-007 baseline prerequisite, NFR-005.
- Scope: deterministic forecast-only validation/reporting for the integrated S7 training runner and probabilistic candidate.
- Exclusions: no model promotion, no registry state transition, no model serving, no paper/live routing, no leverage, no derivatives, no live capital.

## Evidence artifact

- Report ID: `MODELVALIDATION:55EEADCEE761E631B0DF7493C60F47E2`
- Report hash: `e3b82fbe3cd2cb12f1498f4cc3099272e019699a9846b1edf7599fbd448cf4ec`
- Dataset snapshot: `DATASETSNAPSHOT:ED688079451AFB707A0AB34B7C97E27D`
- Training run: `TRAINRUN:2FF599CEF0DF21B0FAA8BF54BAAD4C14`
- Forecast output: `PROBOUTPUT:F14FAF6DF726943ACA61730649955F06`
- Model version: `MODELVERSION:CB70455E107F3BA03FB66A20F49BA85C`

The validator consumes validation/test labels only after forecasts exist and validates row alignment by dataset row ID, dataset snapshot/hash, feature timestamp, split, instrument, venue, label rule, feature vector/input IDs, feature version, and source feature snapshot IDs.

## Metrics

| Metric family | Candidate | Train-prior baseline / no-sequence ablation |
| --- | ---: | ---: |
| Observation count | 4 | 4 |
| NLL | 0.0 | 0.69314718056 |
| Brier | 0.0 | 0.5 |
| Calibration error | 0.0 | 0.5 |
| Mean uncertainty | 0.2 | n/a |

Quantile coverage:

| Quantile level | Observed coverage | Coverage error |
| ---: | ---: | ---: |
| 0.1 | 1 | 0.9 |
| 0.5 | 1 | 0.5 |
| 0.9 | 1 | 0.1 |

## Baseline and ablation evidence

- Fixed S5 baseline gate evidence: `docs/reports/gates/S5-004_baseline_gate_report.md` (PASS).
- Fixed S5 scorecard evidence: `docs/reports/gates/S5-003_evaluation_scorecard_report.md`.
- Scorecard ID referenced: `EVALSCORECARD:BC0F9618311E62E8739A80410D68483D`.
- Probabilistic no-skill baseline: unconditional train-split label prior applied to the exact OOS evaluation rows.
- Feature/sequence ablation: ablated global train-prior/no-sequence comparator on the same evaluation rows.
- Caveat: these are forecast-only comparisons; they do not claim strategy, portfolio, execution, risk, paper, or live outperformance.

## Gate recommendation

Recommendation: `continue_research`.

Reasons:

1. Forecast-only metrics are insufficient for promotion; strategy, portfolio, execution, and risk gates remain unevidenced.
2. No product-approved S7 pass thresholds were available, so the conservative gate recommendation is `continue_research`.
3. Registry metadata consumption is supported by contract/runtime, but this fixture report did not perform or require registry state transitions.

No auto-promotion flag: `true`.

## Docker/runtime impact

- No Docker, Compose, runtime service, datastore, broker, or registry service changes.
- Compose validation not required because no Docker/Compose files were touched.

## Validation commands

Implementation validation:

```text
uv run ruff check .
Result: All checks passed!

uv run mypy src tests
Result: Success: no issues found in 66 source files

uv run pytest tests/test_training_runner.py tests/test_probabilistic_candidate.py tests/test_model_registry.py tests/test_model_validation_report.py
Result: 34 passed

uv run pytest tests/test_model_validation_report.py
Result: 5 passed

uv run pytest
Result: 253 passed
```

## Anti-drift checks

- Baseline evidence is explicit and missing evidence fails closed.
- Forecast/dataset missing, duplicate, or misaligned rows fail closed.
- Validation/test labels are used only as evaluation outcomes after forecasts are produced.
- Report contracts are strict/frozen and deterministic by hash/ID.
- No promotion, no registry transition, no paper/live route, no live-capital path.

## Known follow-ups

- Forecast-only metrics do not establish economic edge or risk-adjusted strategy performance.
- Product-approved S7 pass/fail thresholds are still needed before any pass recommendation can be made.
- Downstream loop validation should attach registry metadata evidence when available, while preserving no-transition semantics.
