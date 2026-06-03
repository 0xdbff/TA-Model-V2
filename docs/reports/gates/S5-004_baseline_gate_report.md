# S5-004 Baseline Gate Validation Report

Issue: #26  
Sprint: S5-004  
Requirements: FR-007, FR-014, NFR-001, NFR-005  
Validation gate: S5 fixed baseline readiness before complex model work

## Final gate decision

**Decision: PASS**

The S5 baseline gate passes because the aggregated evidence includes the required fixed comparator set and the scorecard includes net-first strategy, risk, exposure, cost, and benchmark-relative metric families with explicit undefined reasons where applicable. Future candidates can be compared against these fixed S5 baselines before complex model work proceeds.

## Evidence checked

- S5-001 deterministic baselines: `docs/reports/gates/S5-001_deterministic_baselines_report.md`
  - Cash/no-trade, buy-and-hold, and equal-weight basket baselines.
  - Event-time rows include gross/net return, turnover, exposure, proxy cost fields, and no-trade reasons.
- S5-002 TA/ML baselines: `docs/reports/gates/S5-002_ta_ml_baselines_report.md`
  - TA heuristic and simple ML baselines.
  - Simple ML fit is train-only; validation/test labels are used as outcomes only.
- S5-003 scorecard: `docs/reports/gates/S5-003_evaluation_scorecard_report.md`
  - Scorecard ID: `EVALSCORECARD:9F641495BBD6C5403B7346B0037DAA4B`
  - Scorecard hash: `7f524de6f8dfd99a3695d835f5d0724efa8742c35972aea43545007a7a23031a`
  - Benchmark: cash/no-trade with exact split/instrument/venue/feature_ts row alignment.

## Baseline set checked

Required and present:

- `cash_no_trade`
- `buy_and_hold`
- `equal_weight_basket`
- `ta_heuristic`
- `simple_ml`

## Metric families checked

Required and present in S5-003 scorecard evidence:

- Net return
- Sharpe
- Sortino
- Calmar
- Max drawdown
- CVaR
- Turnover
- Exposure
- Costs
- Benchmark-relative net return

Undefined Sharpe/Sortino/Calmar cases are explicitly marked `not_applicable` with reasons such as zero volatility, no downside returns, or no drawdown. Missing required baselines, missing baseline split/window evidence across train/validation/test, duplicate baseline split evidence, missing evidence files, blocked benchmark-relative metrics, empty scored splits, or non-risk metric `not_applicable` statuses are treated as gate blockers by `validate_s5_baseline_gate`.

## Validation commands

Executed locally in this PR branch:

1. `uv run pytest tests/test_evaluation_scorecard.py` — passed (`17 passed in 0.19s`).
2. `uv run ruff check .` — passed (`All checks passed!`).
3. `uv run mypy src tests` — passed (`Success: no issues found in 44 source files`).
4. `uv run pytest` — passed (`157 passed in 0.73s`).

## Docker/runtime impact

No Docker, Compose, runtime service, datastore, broker, object storage, external API, live credentials, order path, paper/live gateway, leverage, derivatives, margin, shorting, autonomous promotion, or live-capital change. Work is local deterministic validation logic, tests, and this gate report only.

## Anti-drift checklist

- Net-of-cost scorecard evidence is required; gross-only evidence is not sufficient.
- No-trade/cash is a required first-class comparator and benchmark.
- Benchmark-relative net return is required and fails closed on blocked/misaligned evidence.
- Required baselines are validated by stable `BaselineKind`, not mutable display names.
- Each required baseline kind must include train, validation, and test split/window evidence.
- Evidence paths must exist, and S5-003 evidence must match the actual scorecard ID/hash.
- S5 proxy costs remain labeled pre-S6 and are not represented as simulator-grade slippage/TCA completeness.
- Simple ML caveat is preserved: train metrics are in-sample; validation/test apply fixed train parameters.
- No live/paper execution path, orders, risk bypass, leverage, derivatives, margin, shorting, or model promotion is introduced.

## Blockers / caveats

Blockers: none.

Caveats:

- S5 costs are proxy baseline-row costs only; S6 remains responsible for simulator-grade slippage, latency, fills, and TCA evidence.
- Simple ML remains a lightweight comparator, not a promoted model candidate.
