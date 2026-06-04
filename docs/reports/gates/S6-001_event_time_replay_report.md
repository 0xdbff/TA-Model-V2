# S6-001 Event-Time Historical Replay Report

## Traceability

- Issue: #27 / Sprint S6-001 — Implement event-time historical replay engine.
- Requirement IDs: FR-012 (historical replay with execution realism foundation), NFR-001 (prevent lookahead leakage).
- Backlog evidence expectation: same-bar leakage prevention test.

## Scope delivered

- Added minimal frozen simulation contracts for `OrderIntent`, replay order results, replay reports, statuses, reasons, and deterministic replay IDs/hashes.
- Added OHLCTV replay engine that uses bar `close_ts` as market-data availability and fills market orders only at the next eligible bar `open`.
- Added fail-closed validation for duplicate, globally unsorted, per-stream non-monotonic, and overlapping bars; missing future events produce explicit unfilled results.

## Docker/runtime impact

- No Docker profile, runtime service, datastore, broker, dependency, or image changes.
- Local/CI impact is limited to Python package code and tests.

## Acceptance evidence

- Same-bar leakage prevention: `tests/test_event_time_replay.py::test_market_order_fills_next_bar_open_not_signal_bar_close_high_low` proves an order submitted at signal bar close fills on the next bar open and not signal bar high/low/close.
- Event-time availability: `tests/test_event_time_replay.py::test_replay_uses_close_ts_availability_not_ingest_ts_ordering` uses inverted `ingest_ts` ordering and still fills according to event-time bar order.
- Fail-closed unsafe inputs: `tests/test_event_time_replay.py::test_duplicate_or_non_monotonic_bars_fail_closed` covers duplicate and unsorted bars.
- Explicit no-fill path: `tests/test_event_time_replay.py::test_missing_future_fill_event_is_explicit_unfilled_result` returns `UNFILLED` with `NO_FUTURE_ELIGIBLE_EVENT`.
- Determinism: `tests/test_event_time_replay.py::test_replay_ids_and_hashes_are_deterministic` verifies stable report/result IDs and hashes across reruns.

## Validation commands

- `uv run ruff check .` — passed.
- `uv run mypy src tests` — passed.
- `uv run pytest` — passed, 163 tests.

## Anti-drift notes

- No same-bar fill path uses the signal bar close/high/low.
- `ingest_ts` is excluded from replay ordering, availability decisions, and market-data hash inputs.
- Costs/slippage/latency/partial fills, cash/inventory constraints, risk checks, paper/live gateway behavior, and scenario suites remain out of S6-001 scope for S6-002/S6-003/S6-004.
- No leverage, derivatives, margin, shorting, market making, HFT, live capital, or autonomous promotion path was added.

## Known follow-ups

- S6-002 should add fees, spread, slippage, latency, and partial/failed fill realism on top of these replay result contracts.
- S6-003 should add simulator cash/inventory and venue/instrument constraint enforcement before any gateway-like use.
