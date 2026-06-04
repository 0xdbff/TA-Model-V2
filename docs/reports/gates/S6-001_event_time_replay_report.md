# S6-001 Event-Time Historical Replay Report

## Traceability

- Issue: #27 / Sprint S6-001 — Implement event-time historical replay engine.
- Requirement IDs: FR-012 (historical replay with execution realism foundation), NFR-001 (prevent lookahead leakage).
- Backlog evidence expectation: same-bar leakage prevention test.

## Scope delivered

- Added minimal frozen simulation contracts for `OrderIntent`, replay order results, replay reports, statuses, reasons, and deterministic replay IDs/hashes.
- Added OHLCTV replay engine that uses bar `close_ts` as market-data availability and fills market orders only at the next eligible bar `open`.
- Added fail-closed validation for late-source bars, duplicate bars, globally unsorted event-time inputs, per-stream non-monotonic/overlapping bars, mixed-timeframe ambiguity, and duplicate client order IDs; missing future events produce explicit unfilled results.

## Docker/runtime impact

- No Docker profile, runtime service, datastore, broker, dependency, or image changes.
- Local/CI impact is limited to Python package code and tests.

## Acceptance evidence

- Same-bar leakage prevention: `tests/test_event_time_replay.py::test_market_order_fills_next_bar_open_not_signal_bar_close_high_low` proves an order submitted at signal bar close fills on the next bar open and not signal bar high/low/close.
- Event-time availability: `tests/test_event_time_replay.py::test_replay_uses_close_ts_availability_not_ingest_ts_ordering` uses inverted `ingest_ts` ordering and still fills according to event-time bar order.
- Late source leakage prevention: `tests/test_event_time_replay.py::test_late_source_ohlctv_bar_fails_closed_before_fill` fails closed when `source_ts > close_ts`, before the late bar can become fill evidence.
- Global event-time ordering: `tests/test_event_time_replay.py::test_multi_instrument_bars_are_sorted_by_global_event_time` accepts multi-instrument bars sorted by `close_ts/instrument/venue/timeframe`, and `tests/test_event_time_replay.py::test_stream_grouped_but_event_time_out_of_order_bars_fail_closed` rejects stream-grouped but event-time-out-of-order input.
- Fail-closed unsafe inputs: `tests/test_event_time_replay.py::test_duplicate_or_non_monotonic_bars_fail_closed` covers duplicate and unsorted bars; `tests/test_event_time_replay.py::test_mixed_timeframes_for_same_instrument_venue_fail_closed` covers ambiguous mixed timeframes; `tests/test_event_time_replay.py::test_duplicate_client_order_id_fails_closed` covers duplicate order intents.
- Explicit no-fill path: `tests/test_event_time_replay.py::test_missing_future_fill_event_is_explicit_unfilled_result` returns `UNFILLED` with `NO_FUTURE_ELIGIBLE_EVENT`.
- Determinism: `tests/test_event_time_replay.py::test_replay_ids_and_hashes_are_deterministic` verifies stable report/result IDs and hashes across reruns.

## Validation commands

- `uv run ruff check .` — passed.
- `uv run mypy src tests` — passed.
- `uv run pytest` — passed, 168 tests.

## Anti-drift notes

- No same-bar fill path uses the signal bar close/high/low.
- Late-source bars fail closed when `source_ts` is after `close_ts`, matching the feature-engine no-leakage posture.
- Replay input ordering is global event-time availability order, not stream-grouped order.
- Mixed timeframes for the same instrument/venue fail closed because S6-001 has no timeframe selector in `OrderIntent`.
- `ingest_ts` is excluded from replay ordering, availability decisions, and market-data hash inputs.
- Costs/slippage/latency/partial fills, cash/inventory constraints, risk checks, paper/live gateway behavior, and scenario suites remain out of S6-001 scope for S6-002/S6-003/S6-004.
- No leverage, derivatives, margin, shorting, market making, HFT, live capital, or autonomous promotion path was added.

## Known follow-ups

- S6-002 should add fees, spread, slippage, latency, and partial/failed fill realism on top of these replay result contracts.
- S6-003 should add simulator cash/inventory and venue/instrument constraint enforcement before any gateway-like use.
