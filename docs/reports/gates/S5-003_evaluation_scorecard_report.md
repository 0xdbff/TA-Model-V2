# S5-003 Evaluation Scorecard Gate Report

## Requirement trace

- **Issue/Sprint:** #25 / S5-003.
- **Requirements:** FR-014 (separate model/strategy/portfolio evaluation metrics), FR-007 (baseline reports), NFR-001 (event-time/no lookahead consumption), NFR-005 (reproducible IDs/hashes).
- **Validation gate:** S5 baseline gate evidence before complex model work.

## Docker/runtime impact

- Local dev/research Python only (`uv run ...`).
- No new runtime service, datastore, broker, external API, live credentials, orders, paper/live gateway, leverage, derivatives, shorting, margin, or promotion path.

## Metric assumptions

- Net return is primary: `product(1 + row.net_return) - 1` per baseline/split.
- Sharpe/Sortino/Calmar are not annualized; risk-free rate is zero.
- Volatility and downside volatility use population standard deviation.
- Max drawdown is computed from the compounded net-return equity path.
- CVaR uses the lower tail with default tail probability `0.05` and `ceil(n * tail)` observations.
- Cost metrics are S5 proxy `cost_return` values from baseline rows only; this does **not** claim S6 slippage/TCA completeness.
- Undefined metrics are explicit `not_applicable` with reasons, not zero-valued passes.

## Deterministic scorecard evidence

- Scorecard ID: `EVALSCORECARD:EA271BF38D429ADA73A3E05D8D5E9745`
- Scorecard hash: `4ea685336ae6d1f9295297f2a60c3690eb90e36d6f02f055e955af5067c02ecb`
- Benchmark report ID: `BASELINEREPORT:18EF624A3A7D704A5C3145CF03A66B93`
- Benchmark report hash: `5714e86121d6ce8b8d4b13433057465bc57b5c16c85e3209e894260826f9a555`
- Benchmark: cash/no-trade report with exact split/instrument/venue/feature_ts row alignment.

| baseline | split | n | net return | Sharpe | max DD | CVaR | turnover | avg exposure | costs | rel. cash |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cash_no_trade | train | 2 | 0 | N/A zero volatility | 0 | 0 | 0 | 0 | 0 | 0 |
| cash_no_trade | validation | 2 | 0 | N/A zero volatility | 0 | 0 | 0 | 0 | 0 | 0 |
| cash_no_trade | test | 2 | 0 | N/A zero volatility | 0 | 0 | 0 | 0 | 0 | 0 |
| buy_and_hold | train | 2 | 0.018990099009900990099009901 | 20.97802197802197802197801978 | 0 | 0.009 | 1 | 1 | 0.001 | 0.018990099009900990099009901 |
| buy_and_hold | validation | 2 | 0.018598134399390824290881401 | 20.46013044393014937933937559 | 0 | 0.008803921568627450980392157 | 1 | 1 | 0.001 | 0.018598134399390824290881401 |
| buy_and_hold | test | 2 | 0.018221245421245421245421246 | 19.96774193548387096774193442 | 0 | 0.008615384615384615384615385 | 1 | 1 | 0.001 | 0.018221245421245421245421246 |
| equal_weight_basket | train | 2 | 0.018990099009900990099009901 | 20.97802197802197802197801978 | 0 | 0.009 | 1 | 1 | 0.001 | 0.018990099009900990099009901 |
| equal_weight_basket | validation | 2 | 0.018598134399390824290881401 | 20.46013044393014937933937559 | 0 | 0.008803921568627450980392157 | 1 | 1 | 0.001 | 0.018598134399390824290881401 |
| equal_weight_basket | test | 2 | 0.018221245421245421245421246 | 19.96774193548387096774193442 | 0 | 0.008615384615384615384615385 | 1 | 1 | 0.001 | 0.018221245421245421245421246 |
| ta_heuristic | train | 2 | 0.018990099009900990099009901 | 20.97802197802197802197801978 | 0 | 0.009 | 1 | 1 | 0.001 | 0.018990099009900990099009901 |
| ta_heuristic | validation | 2 | 0.008708737864077669902912621 | 1 | 0 | 0 | 1 | 0.5 | 0.001 | 0.008708737864077669902912621 |
| ta_heuristic | test | 2 | 0.008523809523809523809523810 | 1 | 0 | 0 | 1 | 0.5 | 0.001 | 0.008523809523809523809523810 |
| simple_ml | train | 2 | 0.008900990099009900990099010 | 1 | 0 | 0 | 1 | 0.5 | 0.001 | 0.008900990099009900990099010 |
| simple_ml | validation | 2 | 0.008708737864077669902912621 | 1 | 0 | 0 | 1 | 0.5 | 0.001 | 0.008708737864077669902912621 |
| simple_ml | test | 2 | 0.008523809523809523809523810 | 1 | 0 | 0 | 1 | 0.5 | 0.001 | 0.008523809523809523809523810 |

Sortino is `not_applicable` for the fixture rows above because there are no downside returns. Calmar is `not_applicable` where max drawdown is zero. Loss-window tests cover available Sortino/Calmar/drawdown/CVaR behavior.

## Validation commands

- `uv run ruff check .` — passed.
- `uv run mypy src tests` — passed.
- `uv run pytest` — 148 passed.

## Acceptance evidence

- Scorecard contracts and builder consume `BaselineReport`/`BaselineRow` directly.
- Metrics include net return, mean net return, Sharpe, Sortino, Calmar, max drawdown, CVaR, turnover, average exposure, costs, and benchmark-relative net return.
- Tests cover cash/no-trade flat windows, all-positive undefined Sortino, no-drawdown undefined Calmar, loss windows, empty/missing baseline inputs, benchmark alignment mismatch, deterministic IDs/hashes, and propagation of costs/turnover/exposure.

## Anti-drift checklist

- Net-of-cost metrics are primary; gross PnL is not used as success evidence.
- Undefined risk metrics are explicit with reasons.
- Benchmark-relative metrics fail closed on row-alignment mismatch.
- S5 costs are labeled proxy costs only; no S6 TCA/slippage claim.
- No live-capital, order, gateway, leverage, derivative, or autonomous promotion path added.
