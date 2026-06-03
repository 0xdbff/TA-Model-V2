# S3-003 Data Health Fail-Closed Signal Report

Gate: S3 Streaming ingestion / data gate  
Sprint/milestone: S3  
Requirement IDs: FR-002, NFR-006; risk trace RISK-006

## Scope covered

- Converts S3-002 `StreamHealthRecord` outputs into scoped `DataHealthSignal` contracts.
- Emits `healthy`, `degraded`, or `blocked` status plus stable reason codes.
- Fails closed for critical freshness/stale breaches by setting `blocks_trading=True` and preserving the affected `blocked_instrument_id` when present.
- Preserves source/venue/channel/instrument scope, source health event ID/status, breached checks, metric names, and evaluation timestamp for audit and future risk/strategy wiring.
- Uses deterministic scope-safe signal identity as `data-health:<sha256>` over canonical JSON-serialized scope plus `event_id`, preventing collisions when event IDs repeat across instruments/sources or when valid IDs contain delimiter characters.

## Scope explicitly not covered

- No risk engine implementation, strategy/order blocking, event bus, Docker/Redpanda smoke, Prometheus/Grafana, or real WebSocket/API stream.
- Deferred #18: runtime stream smoke and observability wiring.
- Future wiring: strategy/risk consumers may consume `DataHealthSignal`, but this issue does not bypass or alter the independent risk engine or kill switch.

## Docker profile/services used

No runtime/Docker impact. This work adds Python contracts, deterministic in-memory gate evaluation, tests, and this report only.

## Evidence artifacts

- `src/ta_model/contracts/stream_health.py`
- `tests/test_data_health_fail_closed.py`
- `docs/reports/gates/S3-003_data_health_fail_closed_report.md`

## Acceptance evidence

- Healthy stream health records produce `DataHealthStatus.HEALTHY`, `blocks_trading=False`, and `STREAM_HEALTHY` reason.
- Stale critical freshness records produce `DataHealthStatus.BLOCKED`, `blocks_trading=True`, `CRITICAL_FRESHNESS_STALE`, and only the affected instrument scope is blocked.
- Non-critical degraded records remain `DEGRADED` and do not block by default.
- Policy can mark another health check critical without broadening source/venue/channel/instrument scope.
- Reason-code and metric traceability links back to source health event ID, checks, metric names, and evaluation timestamp.
- Regression coverage verifies the same source health `event_id` across different source/instrument scopes produces distinct `signal_id` values.
- Regression coverage verifies delimiter-collision scopes such as `subscription_id='SUB:A', source_id='B'` and `subscription_id='SUB', source_id='A:B'` produce distinct hash-derived `signal_id` values.

## Tests

Command evidence:

- `uv run ruff check .` — passed.
- `uv run mypy src tests` — passed, no issues found in 17 source files.
- `uv run pytest` — passed, 78 tests.

Exact combined command output:

```text
All checks passed!
Success: no issues found in 17 source files
........................................................................ [ 92%]
......                                                                   [100%]
78 passed in 0.41s
```

## Anti-drift checks

- FR-002/NFR-006/RISK-006 trace retained for streaming health and fail-closed data signal scope.
- Event-time/evaluation-time traceability is preserved from S3-002 records; ingestion time is not substituted by this gate.
- Signal scope remains affected source/venue/channel/instrument only; unrelated instruments are not blocked by fixture tests.
- Signal identity is deterministic and scope-safe through canonical JSON serialization and SHA-256; repeated source event IDs and delimiter-bearing scope components cannot collide through string concatenation ambiguity.
- No order placement, order blocking implementation, risk-engine bypass, kill-switch bypass, live-capital path, leverage, margin, derivatives, or source-register approval change was introduced.

## Decision

Pass for S3-003 contract/fixture scope; #18 runtime smoke and future risk-engine/strategy wiring remain deferred.
