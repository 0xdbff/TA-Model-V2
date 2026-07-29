# S8-001 Decision Contract Evidence

## Scope

- Issue: #35 / S8-001.
- Outcome: strict `StrategyDecision` trade/no-trade contract with deterministic IDs,
  hashes, trace ID, forecast lineage, economics, reason code, and pre-risk sizing placeholders.
- Boundary: no order routing, simulation submission, paper/live gateway, risk approval,
  leverage, derivatives, shorts, margin, or live capital.

## Requirement trace

- FR-009: decision includes expected return, expected cost, uncertainty buffer, net edge,
  uncertainty, action, and reason code.
- FR-015/NFR-004: decision carries forecast/run/model/feature lineage plus deterministic
  trace/decision identity for later replay and audit.
- US-006: no-trade remains a complete `StrategyDecision`, not an omitted order.

## Acceptance evidence

- Added `src/ta_model/contracts/decisions.py` with frozen Pydantic contracts for
  `StrategyDecision`, policy identity, reason-code counts, and risk-unapproved sizing placeholders.
- Exported public decision contract symbols from `ta_model.contracts`.
- Added `tests/test_strategy_decisions.py` contract tests for valid trade/no-trade decisions,
  missing/invalid/inconsistent reasons, deterministic identity changes, and train-split rejection.

## Docker/runtime impact

- No new dependency, service, datastore, broker, Docker profile, or Compose change.

## Validation commands

- `uv run pytest tests/test_strategy_decisions.py` — PASS, 10 tests.
- `uv run pytest tests/test_strategy_decisions.py tests/test_probabilistic_candidate.py tests/test_execution_cost_replay.py` — PASS, 31 tests.
- `uv run ruff check .` — PASS.
- `uv run mypy src tests` — PASS.
- `uv run pytest` — PASS, 271 tests (final run after docs report additions: `271 passed in 0.96s`).
