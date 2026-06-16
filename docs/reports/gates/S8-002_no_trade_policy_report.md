# S8-002 Expected Net-Edge / No-Trade Policy Evidence

## Scope

- Issue: #36 / S8-002.
- Outcome: production `decide_expected_net_edge` policy converts S7 `Forecast` objects into
  auditable trade/no-trade `StrategyDecision` objects.
- Boundary: produces decisions only; it does not size beyond placeholders, approve risk,
  submit/simulate orders, route to gateways, or introduce live-capital behavior.

## Requirement trace

- FR-009: policy computes `expected_return - expected_cost - uncertainty_buffer` as explicit
  `net_edge`, then assigns trade/no-trade action and reason code.
- PG-002/US-006: no-trade decisions are represented and reason-coded for logging/evaluation.
- FR-015: policy preserves forecast lineage and deterministic trace IDs.

## Acceptance evidence

- Added `src/ta_model/strategy/decisions.py` and `src/ta_model/strategy/__init__.py`.
- Policy uses the forecast median quantile as expected return, explicit policy cost assumptions,
  and an uncertainty buffer multiplier.
- Tests cover positive net-edge trade, no-trade for cost threshold, uncertainty threshold,
  non-positive expected return, insufficient edge, unsupported forecast quantile, and a
  reason-code distribution summary from real `StrategyDecision` objects.
- Fixture reason-code summary asserted from real decisions:
  `cost_threshold=1`, `insufficient_net_edge=1`, `non_positive_expected_return=1`,
  `trade_positive_net_edge=1`.

## Docker/runtime impact

- No new dependency, service, datastore, broker, Docker profile, or Compose change.

## Validation commands

- `uv run pytest tests/test_strategy_decisions.py` — PASS, 10 tests.
- `uv run pytest tests/test_strategy_decisions.py tests/test_probabilistic_candidate.py tests/test_execution_cost_replay.py` — PASS, 31 tests.
- `uv run ruff check .` — PASS.
- `uv run mypy src tests` — PASS.
- `uv run pytest` — PASS, 271 tests (final run after docs report additions: `271 passed in 0.96s`).
