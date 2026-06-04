# S6-002 Cost, Slippage, Latency, and Fill Realism Report

## Traceability

- Issue: #28 / Sprint S6-002
- Requirement: FR-012 — historical replay with costs, spread/slippage, latency, partial/failed fills.
- Risk: RISK-005 — fee/slippage underestimation mitigated by explicit deterministic cost attribution.
- Supporting guardrail: NFR-001 — event-time replay must not use same-bar or ingest-time availability.

## Docker/runtime impact

- No new runtime service, datastore, broker, dependency, Docker profile, or live/paper gateway was added.
- Changes are limited to Python contracts, replay core logic, tests, and this evidence report.

## Implemented assumptions

- `ExecutionCostModel` records taker fee rate, spread bps, slippage bps, latency bars, maximum participation rate, and partial-fill policy.
- Cost model IDs/hashes are deterministic from explicit assumptions.
- Market orders still fill no earlier than a future eligible OHLCTV bar; signal/same-bar high/low/close are not used for fills.
- Latency skips configured future eligible bars. If latency pushes beyond available event-time data, replay returns an explicit unfilled result.
- Filled quantity is capped by `base_volume * max_participation_rate`; insufficient liquidity can create deterministic partial fills or unfilled results when partial fills are disabled.
- Replay output attributes arrival/reference price, effective fill price, filled/remaining quantity, reference/effective notional, fee cost, spread cost, slippage cost, total cost, latency evidence, and cost model ID/hash.

## Cost stress evidence

- `tests/test_execution_cost_replay.py::test_higher_stress_costs_worsen_effective_execution_and_total_cost` compares low-cost and high-cost configurations over the same bars/order.
- Higher spread/slippage settings produce higher `total_cost`, a worse buy-side effective fill price, and a distinct deterministic result ID.
- This is simulator evidence only; it does not claim TCA calibration, paper/live fill calibration, or venue completeness.

## Validation evidence

- `uv run ruff check .` — passed.
- `uv run mypy src tests` — passed (`Success: no issues found in 49 source files`).
- `uv run pytest` — passed (`175 passed`).

## Anti-drift checks

- No ingest timestamp availability was introduced.
- Same-bar fill prevention from S6-001 remains covered by existing and new tests.
- No cash/inventory/risk/venue enforcement was implemented; S6-003 remains owner of those constraints.
- No live capital, leverage, derivatives, margin, shorting, market making, HFT, or autonomous promotion path was introduced.

## Follow-ups and limits

- S6-002 uses transparent OHLCTV-based assumptions, not calibrated TCA models.
- Venue-specific constraints and account/cash/inventory enforcement remain out of scope for S6-003.
