# S8-003 Deterministic Sizing Evidence

## Scope

- Issue: #37 / S8-003.
- Outcome: `StrategyDecision` objects can carry deterministic pre-risk sizing proposals
  from explicit risk-budget, reference-price, cost, uncertainty, and drawdown inputs.
- Boundary: sizing remains a strategy proposal only. It does not approve independent
  risk, route orders, submit to simulator/paper/live gateways, add leverage, derivatives,
  shorts, margin, or live capital.

## Requirement trace

- FR-009: trade/no-trade decisions retain expected return, expected cost, net edge,
  uncertainty, action, and reason code while adding auditable proposed size fields.
- FR-010: risk-budget placeholders expose pre-risk proposed notional/quantity and
  keep `risk_approval_status=not_evaluated`, approved fields unset, and no approval ID.

## Acceptance evidence

- Added `StrategySizingInputs`, sizing reason codes, and explicit pre-risk sizing statuses.
- Added production `propose_pre_risk_size` and wired it through `decide_expected_net_edge`.
- Fixture examples from production decisions:
  - Base risk budget 10000 at reference price 100 proposes notional `10000`, quantity `100`, multiplier `1`.
  - Uncertainty `0.020` against max `0.040` reduces proposal to notional `5000.0`, multiplier `0.5`.
  - Cost `0.002` against max `0.004` reduces proposal to notional `5000.0`, multiplier `0.5`.
  - Cost exactly at max and uncertainty exactly at max produce first-class no-trade
    threshold blocks, not zero-size buy decisions.
  - Zero max cost with zero expected cost, and zero max uncertainty with zero
    uncertainty, remain within threshold and allow qualifying positive-size trades.
  - Drawdown `0.10` against max `0.20` reduces proposal to notional `5000.0`, multiplier `0.5`.
  - Drawdown at max blocks to `no_trade/drawdown_threshold` with proposed notional `0`.
- Tests cover positive size, uncertainty reduction/block, cost reduction/block, drawdown
  reduction/block, zero size on no-trade/blocked decisions, and validator rejection of
  any approved risk fields.

## Docker/runtime impact

- No new dependency, service, datastore, broker, Docker profile, or Compose change.

## Validation commands

- `uv run pytest tests/test_strategy_decisions.py tests/test_strategy_gate_report.py` — PASS, 22 tests.
- `uv run ruff check .` — PASS.
- `uv run mypy src tests` — PASS, 72 source files.
- `uv run pytest` — PASS, 283 tests.

## Anti-drift checklist

- S8 does not claim S9 independent risk approval or bypass a future risk engine.
- No-trade and blocked decisions keep proposed size at zero and remain logged decisions.
- Sizing proposals are deterministic and included in decision hash/ID inputs.
