# S8-004 Strategy Gate Evidence

## Scope

- Issue: #38 / S8-004.
- Outcome: production `build_strategy_gate_report` consumes real `StrategyDecision`
  objects and realized utility observations to evaluate skipped-vs-taken utility,
  turnover proxy, cost drag, and reason-code distribution.
- Boundary: local strategy validation only. No model promotion, portfolio allocation,
  risk approval, order routing, simulator/paper/live gateway, leverage, derivatives,
  shorts, margin, or live capital path is introduced.

## Requirement trace

- FR-009: report groups taken and skipped trade/no-trade decisions with reason codes.
- FR-014: strategy behavior is evaluated separately from model metrics using utility,
  turnover, cost-drag, and reason-distribution metrics.

## Deterministic report evidence

- Strategy gate report ID: `STRATEGYGATE:9EC2D4774C46AD7261652360E19FD760`
- Strategy gate report hash: `e6f3ce12fb7db7a923264ab35d8267072b44cb7853c51887d429e56a68fa0e6c`
- Observations: 4 real `StrategyDecision` objects; 2 taken, 2 skipped.
- Taken mean utility: `0.033`.
- Skipped mean opportunity utility: `-0.0035`.
- Skipped-vs-taken mean utility: `-0.0365`.
- Turnover proxy notional: `10000.0`.
- Cost drag notional: `20.0000`.
- Reason distribution: `trade_positive_net_edge=2`, `insufficient_net_edge=1`,
  `cost_threshold=1`.

## Acceptance evidence

- Added `StrategyGateUtilityObservation` and `StrategyGateReport` contracts with
  deterministic ID/hash validation.
- Added production `ta_model.evaluation.strategy_gate.build_strategy_gate_report`.
- Tests build the report from real decisions and assert skipped-vs-taken utility,
  turnover, cost drag, reason distribution, deterministic ID/hash, and absence of
  model-promotion or risk-approval claims.

## Docker/runtime impact

- No new dependency, service, datastore, broker, Docker profile, or Compose change.

## Validation commands

- `uv run pytest tests/test_strategy_decisions.py tests/test_strategy_gate_report.py` — PASS, 22 tests.
- `uv run ruff check .` — PASS.
- `uv run mypy src tests` — PASS, 72 source files.
- `uv run pytest` — PASS, 283 tests.

## Anti-drift checklist

- Report consumes production `StrategyDecision` objects, not mocks or docs-only data.
- Turnover and cost drag are labeled pre-risk proposal proxies, not fills or TCA.
- No S8 report field claims independent risk approval or model promotion.
