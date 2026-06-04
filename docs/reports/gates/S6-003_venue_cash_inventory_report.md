# S6-003 Venue, Cash, and Inventory Replay Evidence

Issue: #29 / Sprint S6-003  
Scope: S6 replay simulator enforcement only; no paper/live gateway, no independent S9 risk engine claim.

## Requirement trace

- FR-003: simulator consumes instrument-master venue/instrument/account metadata and active instrument constraints.
- FR-010: fail-closed simulator feasibility checks prevent venue/account/order infeasibility from mutating simulated state. This is not full S9 risk-engine completion.
- FR-012: existing event-time replay and execution-cost/fill realism remain intact.
- Supporting risk context: RISK-007 duplicate exposure and RISK-009 venue-rule compliance context only.

## Docker/runtime impact

- No new runtime service, datastore, broker, dependency, Docker profile, or live-capital path.
- Pure Python contract/replay/test changes.

## Acceptance evidence

- Added `SimulatedBalance`, `SimulatedAccountState`, and `ReplayRejectionCount` contracts.
- `replay_ohlctv_market_orders(...)` now optionally accepts `instrument_master_snapshot` and `starting_account_state` while preserving legacy calls.
- Enforced when optional metadata/state are supplied:
  - active venue only;
  - spot, non-derivative, trading instrument only;
  - simulation/paper active account with place-order permission and no live/margin/derivative/shorting flags;
  - order type support at venue and instrument;
  - active event-time instrument constraint via `InstrumentConstraint.evaluate_order` using the selected fill-attempt bar open as the market-order reference price and `open_ts` as the effective-dated constraint selection time;
  - non-negative quote cash for buys after effective notional plus fees;
  - non-negative base inventory for sells/no shorting.
- Balance mutation happens only after a filled or partially-filled result passes cash/inventory checks.
- Rejected/unfilled results leave final balances unchanged.

## Rejection accounting

New explicit replay reasons include:

- `venue_not_tradable`
- `instrument_not_tradable`
- `account_not_tradable`
- `constraint_violation`
- `insufficient_cash`
- `insufficient_inventory`

`ReplayReport.rejection_counts` is deterministic, must exactly match result reasons, cannot carry zero-count rows, and is included in `replay_report_hash` with `final_account_state`.

## Validation commands

- `uv run pytest tests/test_venue_account_replay.py tests/test_event_time_replay.py tests/test_execution_cost_replay.py` — 39 passed.
- `uv run ruff check .` — all checks passed.
- `uv run mypy src tests` — success, no issues in 50 source files.
- `uv run pytest` — 197 passed.

## Anti-drift notes

- Event-time semantics are unchanged: no ingest-time availability, no same-bar fills, late-source bars fail closed, and mixed timeframe ambiguity remains guarded.
- S6-002 execution-cost attribution remains intact; enforced account debits/credits use effective notional and fee cost.
- No leverage, derivatives, margin, shorting, live capital, market making, HFT, strategy layer, scenario suite, or autonomous promotion added.
- This simulator guard does not replace or bypass the future independent risk engine or kill switch.
