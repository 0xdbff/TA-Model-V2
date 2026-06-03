# S2-004 Historical Data Quality Report

Gate: S2 Historical ingestion / data gate
Sprint/milestone: S2-004
Requirement IDs: FR-001, US-005

## Scope covered

- Added fixture-only historical data-quality reporting over `SilverNormalizationBatch` outputs.
- OHLCTV reports measure expected event-time intervals, missing bars, contiguous gaps, duplicate bars, and blocker codes.
- Trade reports measure duplicate source trade IDs and duplicate source sequences where available.
- Reports preserve source, venue, instrument, timeframe, and event-time window scope.

## Scope explicitly not covered

- No real source/API/network data, source approval changes, persistence, Docker services, S4 feature/dataset work, real backfills, paper/live behavior, leverage, derivatives, or live capital.

## Docker profile/services used

- No runtime service or Docker Compose changes.

## Evidence artifacts

- Code: `src/ta_model/validation/data_quality.py`.
- Tests: `tests/test_historical_data_quality_report.py`.
- Required commands: `uv run ruff check . && uv run mypy src tests && uv run pytest`.

```text
$ uv run ruff check . && uv run mypy src tests && uv run pytest
All checks passed!
Success: no issues found in 23 source files
........................................................................ [ 77%]
.....................                                                    [100%]
93 passed in 0.49s
```

## Metrics vs thresholds

Fixture scenarios use fail-closed default thresholds unless explicitly relaxed in a test:

| Scenario | Metric | Observed | Threshold | Decision |
|---|---:|---:|---:|---|
| Complete 3-bar OHLCTV window | missing interval rate | 0.0 | 0.0 | pass |
| Missing 1 of 3 OHLCTV bars | missing interval rate | 0.333333 | 0.0 | blocked |
| Missing 1 contiguous OHLCTV gap | gap count | 1 | 0 | blocked |
| Duplicate 1 of 4 OHLCTV records | duplicate rate | 0.25 | 0.0 | blocked |
| Duplicate OHLCTV with relaxed config | duplicate rate | 0.25 | 0.25 | pass |
| Duplicate trades by ID/sequence | duplicate rate | 1.0 | 0.0 | blocked |

## Blockers surfaced by fixtures

- `DQB:S2-004:MISSING_BARS`: missing OHLCTV intervals breach completeness threshold.
- `DQB:S2-004:GAPS`: event-time gaps breach configured threshold.
- `DQB:S2-004:DUPLICATE_BARS`: duplicate bars breach duplicate threshold.
- `DQB:S2-004:DUPLICATE_TRADES`: duplicate trade IDs or sequences breach duplicate threshold.

These are expected fixture blockers used to prove the reporter fails closed. They do not represent approved real data because source-register candidates remain `blocked_pending_review`.

## Anti-drift checks

- Completeness/gap decisions use `open_ts`/`close_ts`; trade duplicate windows use `event_ts`.
- `ingest_ts` is explicitly not used for data-quality decisions, and a late-ingest fixture still passes when event-time intervals are complete.
- Known missing bars, gaps, and duplicates are reported as blockers when thresholds are breached; they are not normalized as pass.
- Source, venue, instrument, timeframe, and data-kind scope are validated before metrics are emitted.
- Fixture-only tests introduce no secrets, unapproved data, live capital, leverage, margin, derivatives, or risk-engine bypass.

## S2 data-gate decision

Decision: hold / blocked for real-data promotion readiness.

Rationale: the S2-004 reporter and fixture validation pass, but no real historical source is approved or backfilled in this issue. Future gate review must attach approved-source backfill evidence before promotion.
