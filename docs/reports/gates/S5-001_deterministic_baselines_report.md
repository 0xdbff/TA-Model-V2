# S5-001 Deterministic Baselines Gate Report

Issue: #23  
Sprint: S5-001  
Requirements: FR-007, FR-014, NFR-001, NFR-005

## Scope delivered

- Added deterministic baseline contracts for reusable config, row output, split summaries, and baseline reports.
- Implemented fixture/local cash/no-trade, buy-and-hold, and equal-weight basket baselines over `DatasetSnapshot.rows`.
- Preserved dataset/config lineage via `dataset_snapshot_id`, `dataset_hash`, `baseline_config_id`, `baseline_config_hash`, report hash, and row IDs.
- Exposed per-row target weight, exposure, realized return, turnover, cost rate/return, net return, and no-trade reason for S5-003 scorecard integration.

## Acceptance evidence

- Cash/no-trade baseline emits explicit zero target weight, exposure, turnover, costs, and net return with `cash_no_trade_baseline` reason.
- Buy-and-hold uses deterministic event-time rows and applies entry turnover/cost from point-in-time cost features when present.
- Equal-weight basket allocates deterministically across multiple instruments sharing a split/window timestamp.
- Future-value labels are converted to realized returns using the row `close` feature available at `feature_ts`; future-return labels are consumed directly as outcomes.
- Missing cost features default to zero and are documented as proxy assumptions, not S6 slippage/TCA evidence.
- Deterministic config/report/row IDs and hashes are tested.
- Bad inputs fail closed for empty snapshots, non-positive close values, and negative cost features.

## Validation commands

Executed locally in this PR branch:

1. `uv run ruff check .` — passed (`All checks passed!`)
2. `uv run mypy src tests` — passed (`Success: no issues found in 39 source files`)
3. `uv run pytest` — passed (`135 passed in 0.62s`)

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
