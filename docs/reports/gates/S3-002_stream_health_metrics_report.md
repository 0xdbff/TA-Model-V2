# S3-002 Stream Health Metrics Report

Gate: S3 Streaming ingestion / data gate  
Sprint/milestone: S3  
Requirement IDs: FR-002, NFR-006

## Scope covered

- Added deterministic stream-health evaluator contracts for S3-001 synthetic stream events.
- Emits structured records/metrics for freshness age, stale event indicator, sequence gap size, duplicate event indicator, and timestamp drift seconds.
- Scopes sequence and duplicate state by subscription, source, venue, channel, and instrument.
- Requires explicit `evaluation_ts`; freshness/timestamp drift do not substitute ingestion time or wall-clock time.

## Scope explicitly not covered

- Deferred #17: no stale-feed strategy/risk fail-closed signal and no order/intent blocking behavior.
- Deferred #18: no Docker/Redpanda smoke, event bus, Prometheus, Grafana, or runtime service changes.
- No real WebSocket/API/network streams, no real market data source enablement, and no source-register status changes.

## Docker profile/services used

No runtime/Docker impact. This work adds Python contracts, deterministic in-memory evaluation, and tests only.

## Evidence artifacts

- `src/ta_model/contracts/stream_health.py`
- `tests/test_stream_health_metrics.py`

## Metrics vs thresholds

- `stream.freshness.age_seconds` compared with `StreamHealthPolicy.max_event_age`.
- `stream.freshness.stale_event` emitted as `0/1` breached when freshness exceeds threshold.
- `stream.sequence.gap_size` emitted as missing sequence count within scoped source/channel/instrument state.
- `stream.duplicate.event` emitted as `0/1` for repeated stable event IDs or repeated sequences in scope.
- `stream.timestamp.drift_seconds` is defined for this contract slice as absolute distance between explicit `evaluation_ts` and source timestamp when present, otherwise event timestamp; it is compared with `StreamHealthPolicy.max_timestamp_drift` and does not use `ingest_ts` as a substitute. #17/#18 should review production thresholds and semantics when wiring fail-closed/runtime behavior.

## Tests

Command evidence:

- `uv run ruff check .` — passed.
- `uv run mypy src tests` — passed, no issues found in 13 source files.
- `uv run pytest` — passed, 65 tests.

Coverage scenarios:

- Healthy stream with structured metric names/values.
- Stale event detection.
- Sequence gap detection.
- Duplicate event detection.
- Timestamp drift detection.
- Future-dated source/event timestamp drift detection without ingest-time substitution.
- Per-instrument/source/channel scoping.
- Deterministic batch record output.

## Anti-drift checks

- FR-002/NFR-006 trace retained; S3-002 stops at metric/health records.
- Event-time correctness preserved via explicit `evaluation_ts`; ingestion time is not used for freshness/drift decisions.
- No fail-closed trading behavior, risk bypass, live-capital path, new data source, runtime service, or observability stack was introduced.
- Source register candidates remain blocked pending review; synthetic fixtures only.

## Decision

Pass for S3-002 contract/fixture scope; #17 fail-closed behavior and #18 runtime smoke remain deferred.
