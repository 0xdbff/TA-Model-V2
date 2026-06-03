# S5-002 TA Heuristic and Simple ML Baselines Gate Report

Issue: #24  
Sprint: S5-002  
Requirements: FR-007, FR-014, NFR-001, NFR-005

## Scope delivered

- Extended reusable S5 `BaselineReport`/`BaselineRow` contracts with `ta_heuristic` and `simple_ml` baseline kinds plus optional deterministic config parameters.
- Implemented a long-only TA heuristic that trades only when point-in-time TA signal features are positive and emits explicit no-trade rows when signal features are missing or non-positive.
- Implemented a pure-Python simple ML threshold baseline that fits only on train-split rows, records learned threshold lineage in the report, and applies unchanged parameters to validation/test rows.
- Preserved S5 proxy cost fields (`cost_rate`, `cost_return`, net return) and split-local turnover reset semantics from S5-001.

## Deterministic comparator table

Fixture assumptions: chronological windows are train `[00:00, 00:02)`, validation `[00:02, 00:04)`, and test `[00:04, 00:06)`; `close` values are 100 through 105; future-value labels are `close + 1`; `round_trip_taker_cost_bps=10` when cost handling is exercised. These are S5 proxy costs only and do not claim S6-grade slippage/TCA.

| Baseline | Split/window | Rows | Gross return sum | Turnover sum | Cost return sum | Net return sum | Avg exposure |
|---|---|---:|---:|---:|---:|---:|---:|
| TA heuristic | train | 2 | 0 | 0 | 0 | 0 | 0 |
| TA heuristic | validation | 2 | 0.019512659433 | 1 | 0.001 | 0.018512659433 | 1 |
| TA heuristic | test | 2 | 0.009523809524 | 1 | 0.001 | 0.008523809524 | 0.5 |
| Simple ML | train | 2 | 0.009900990099 | 1 | 0.001 | 0.008900990099 | 0.5 |
| Simple ML | validation | 2 | 0.009803921569 | 2 | 0.002 | 0.007803921569 | 0.5 |
| Simple ML | test | 2 | 0.009615384615 | 2 | 0.002 | 0.007615384615 | 0.5 |

## Acceptance evidence

- TA and ML outputs use the common `BaselineReport`/`BaselineRow` result contract and include gross/net return, exposure, turnover, cost rate/return, and no-trade reasons.
- TA decision tests cover missing-feature no-trade, non-positive-signal no-trade, positive-signal long-only entries, split-local state, and point-in-time cost handling.
- ML tests prove train-only fitting: changing validation/test labels changes realized outcomes but not learned thresholds, target weights, or no-trade reasons.
- ML fail-closed tests cover missing train features and train-label-only learned behavior; validation/test labels do not influence model parameters, thresholds, or feature selection.
- Deterministic IDs/hashes continue to be covered by the S5-001 baseline regression tests against the shared contracts.

## Validation commands

Executed locally in this PR branch:

1. `uv run ruff check .` — passed (`All checks passed!`)
2. `uv run mypy src tests` — passed (`Success: no issues found in 39 source files`)
3. `uv run pytest` — passed (`140 passed in 0.76s`)

## Docker/runtime impact

No Docker, Compose, runtime service, database, broker, object storage, external API, order path, paper/live gateway, or live-capital changes. Impact is limited to local/dev Python baseline contracts, deterministic baseline logic, tests, and this evidence report.

## Anti-drift checks

- Event-time correctness: baseline position decisions read only `DatasetRow.feature_values` available at `feature_ts`; labels are outcomes only, except train-split labels used for the simple ML fit.
- Leakage prevention: validation/test labels do not influence ML parameters, thresholds, normalization, or feature selection.
- No-trade first-class: declined TA/ML rows are emitted with reason codes rather than omitted.
- MVP scope preserved: fixture/local spot-style baselines only; no leverage, derivatives, margin, shorting, live capital, orders, gateways, risk bypass, model promotion, or autonomous updates.
- Reproducibility: dataset/config/report/row IDs and hashes remain deterministic through common S5 contracts.

## Risks / follow-ups

- The simple ML baseline is intentionally lightweight pure Python for comparator coverage; it is not a promoted model candidate.
- S5-003 owns full scorecard metrics and benchmark-relative aggregation across S5-001 and S5-002 reports.
- S6 remains responsible for simulator-grade slippage, latency, fills, and TCA modeling.
