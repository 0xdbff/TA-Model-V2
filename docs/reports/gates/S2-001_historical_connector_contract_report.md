# S2-001 Historical Connector Contract Report

Gate: S2 Historical ingestion / data gate part 1
Sprint/milestone: S2-001 historical connector interface
Requirement IDs: FR-001; supporting FR-003, NFR-005; spec support TFR-001

## Scope covered

- Contract-first historical backfill interface for OHLCTV bars and trades.
- Pydantic v2 strict/frozen market-data contracts with event-time fields distinct from fetched/ingest timestamps.
- Synthetic fixture contract tests for valid pages, provenance/raw payload reference shape, retry/idempotency, rate-limit state, source-register approval fail-closed behavior, page lineage, OHLC/trade invariants, and unknown-field/status rejection.

## Scope explicitly not covered

- No real exchange/API/network ingestion; source register candidates remain blocked pending review.
- No bronze storage (#12), silver normalization (#13), gap/missing interval report (#14), streaming connectors (#15), datasets/features (#19-#22), runtime service, Docker Compose, paper/live route, leverage, margin, derivatives, or shorting.

## Docker/runtime impact

- No runtime service or Docker profile changed. Local `dev` profile test commands only.

## Evidence artifacts

- `src/ta_model/contracts/market_data.py`
- `src/ta_model/connectors/historical.py`
- `tests/test_historical_connector_contracts.py`

## Tests run

- `uv run ruff check .` → `All checks passed!`
- `uv run mypy src tests` → `Success: no issues found in 9 source files`
- `uv run pytest` → `42 passed in 0.38s`

## Anti-drift checks

- Source approval uses source-register/S0-004-aligned states and fails closed unless license status is `approved` or `approved_with_restrictions`, approved-use status is `backtest_approved` or `paper_approved`, and review evidence, register version, retention/storage/raw-payload, event-time, and rate-limit evidence fields are present.
- `blocked_pending_review`, `expired`, `research_approved`, `exploration_only`, and invented/unknown approval statuses cannot authorize historical ingestion.
- Page lineage enforces one raw payload per page: every record `raw_payload_id` must match page provenance.
- Fixture URIs only; no live or network source pulls and no persistent market dataset.
- Event-time fields (`open_ts`, `close_ts`, `event_ts`, `source_ts`) remain separate from `ingest_ts`/`fetched_at`.
- Unknown fields are forbidden to prevent silent provider schema drift.
- Deterministic request/page IDs support replay/idempotency and do not depend on ingest time.

## Decision

Pass for S2-001 contract scope; downstream storage/normalization/gap-report work remains deferred.
