# S5-001 Deterministic Baselines Gate Report

Issue: #23  
Sprint: S5-001  
Requirements: FR-007, FR-014, NFR-001, NFR-005

## Scope delivered

- Added deterministic baseline contracts for reusable config, row output, split summaries, and baseline reports.
- Implemented fixture/local cash/no-trade, buy-and-hold, and equal-weight basket baselines over `DatasetSnapshot.rows`.
- Reset default position/turnover state at each configured split/window boundary for per-window baseline reports.
- Preserved dataset/config lineage via `dataset_snapshot_id`, `dataset_hash`, `baseline_config_id`, `baseline_config_hash`, report hash, and row IDs.
- Exposed per-row target weight, exposure, realized return, turnover, cost rate/return, net return, and no-trade reason for S5-003 scorecard integration.

## Acceptance evidence

- Cash/no-trade baseline emits explicit zero target weight, exposure, turnover, costs, and net return with `cash_no_trade_baseline` reason.
- Buy-and-hold uses deterministic event-time rows and applies entry turnover/cost from point-in-time cost features when present.
- Equal-weight basket allocates deterministically across multiple instruments sharing a split/window timestamp.
- Buy-and-hold and equal-weight basket first rows in validation/test incur independent split entry turnover/cost instead of carrying train positions forward.
- Rows must be chronological by `feature_ts`; non-chronological rows fail closed before turnover is computed.
- Future-value labels are converted to realized returns using the row `close` feature available at `feature_ts`; future-return labels are consumed directly as outcomes.
- Missing cost features default to zero and are documented as proxy assumptions, not S6 slippage/TCA evidence.
- Deterministic config/report/row IDs and hashes are tested.
- Bad inputs fail closed for empty snapshots, non-positive close values, and negative cost features.

## Deterministic baseline example across configured windows

Fixture assumptions used by regression tests: chronological windows are train `[00:00, 00:02)`, validation `[00:02, 00:04)`, and test `[00:04, 00:06)`; `close` values are 100 through 105; future-value labels are `close + 1`; `round_trip_taker_cost_bps=10` (0.001 return-rate entry cost). Buy-and-hold uses one instrument. Equal-weight uses two instruments with identical fixture returns, 0.5 target weight per instrument, and split-local turnover reset.

| Baseline | Split/window | Rows | Gross return sum | Turnover sum | Cost return sum | Net return sum | Avg exposure |
|---|---|---:|---:|---:|---:|---:|---:|
| Cash/no-trade | train | 2 | 0 | 0 | 0 | 0 | 0 |
| Cash/no-trade | validation | 2 | 0 | 0 | 0 | 0 | 0 |
| Cash/no-trade | test | 2 | 0 | 0 | 0 | 0 | 0 |
| Buy-and-hold | train | 2 | 0.019900990099 | 1 | 0.001 | 0.018900990099 | 1 |
| Buy-and-hold | validation | 2 | 0.019512659433 | 1 | 0.001 | 0.018512659433 | 1 |
| Buy-and-hold | test | 2 | 0.019139194139 | 1 | 0.001 | 0.018139194139 | 1 |
| Equal-weight basket | train | 4 | 0.019900990099 | 1.0 | 0.0010 | 0.018900990099 | 0.5 |
| Equal-weight basket | validation | 4 | 0.019512659433 | 1.0 | 0.0010 | 0.018512659433 | 0.5 |
| Equal-weight basket | test | 4 | 0.019139194139 | 1.0 | 0.0010 | 0.018139194139 | 0.5 |

## Validation commands

Executed locally in this PR branch:

1. `uv run ruff check .` — passed (`All checks passed!`)
2. `uv run mypy src tests` — passed (`Success: no issues found in 39 source files`)
3. `uv run pytest` — passed (`137 passed in 0.66s`)

## Docker/runtime impact

No Docker, Compose, runtime service, database, broker, object storage, external API, order path, paper/live gateway, or live-capital changes. Impact is limited to local/dev/research Python contracts and deterministic baseline logic.

## Anti-drift checks

- Event-time correctness: baseline position decisions read only `DatasetRow.feature_values` available at `feature_ts`; labels are used only as realized outcomes.
- No-trade first-class: cash/no-trade emits explicit reasoned rows rather than omitting decisions.
- Reproducibility: output IDs/hashes are deterministic from dataset lineage, config, rows, summaries, and cost assumptions.
- MVP scope preserved: fixture/local spot-style baselines only; no leverage, derivatives, margin, shorting, live capital, orders, risk bypass, model promotion, or autonomous updates.
- Cost scope bounded: S5 proxy cost features are documented and do not claim S6-grade slippage/TCA completeness.

## Risks / follow-ups

- S5-003 must compute full scorecard metrics such as Sharpe, Sortino, Calmar, max drawdown, CVaR, and benchmark-relative metrics; S5-001 only prepares deterministic baseline returns and cost fields.
- S6 remains responsible for simulator-grade slippage, latency, fill, and TCA modeling.
