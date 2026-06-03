# S2-003 Silver Normalization Report

Gate: S2 Historical ingestion / data gate
Sprint/milestone: S2-003
Requirement IDs: FR-001, FR-003

## Scope covered

- Added in-memory silver normalization contracts for validated historical OHLCTV bars and trades.
- Added deterministic silver record and batch IDs with source, venue, instrument, timeframe, page, and raw payload lineage.
- Reused `OHLCTVBar`, `TradeRecord`, `HistoricalBackfillPage`, and `RawPayloadReference` validators rather than adding provider-specific schemas.
- Enforced trade venue scope using the S1/S2 fixture canonical instrument convention `VENUE_ID:SYMBOL`, because `TradeRecord` does not carry its own `venue_id`.
- Fail-closed checks reject data-kind mismatch, raw-payload lineage mismatch, scope mismatch, unknown fields, and schema/invariant violations.

## Scope explicitly not covered

- No real exchange/API/network ingestion or provider payload parsers.
- No S2-004 completeness/gap/quality report, S4 feature/dataset build, Postgres/Timescale persistence, MinIO/Docker service wiring, paper/live route, leverage, derivatives, or live capital.

## Docker profile/services used

- No runtime service or Docker Compose changes.

## Evidence artifacts

- Code: `src/ta_model/normalization/silver.py`.
- Tests: `tests/test_silver_normalization.py`.
- Required commands: `uv run ruff check . && uv run mypy src tests && uv run pytest`.
- QA command evidence:

```text
$ uv run ruff check . && uv run mypy src tests && uv run pytest
All checks passed!
Success: no issues found in 19 source files
........................................................................ [ 90%]
........                                                                 [100%]
80 passed in 0.40s
```

## Anti-drift checks

- Event-time fields are preserved from validated source records (`open_ts`, `close_ts`, `event_ts`, `source_ts`); ingest time is not substituted for market availability time or used in deterministic IDs.
- Raw lineage remains explicit through `raw_payload_id`, `page_id`, and `request_id`.
- Trade records fail closed when caller-supplied `venue_id` does not match the canonical `instrument_id` venue prefix.
- Unknown silver/provider fields are rejected via the frozen contract base model.
- Fixture-only tests introduce no secrets, real market data, live capital, leverage, margin, or derivatives.

## Deferred work

- #14 / S2-004 remains responsible for completeness, gap, duplicate, quality reporting, and data-gate summaries over silver outputs.
- Future persistence work remains responsible for actual Postgres/Timescale or object-store storage.

## Decision

Pass for S2-003 fixture/dev normalization scope.
