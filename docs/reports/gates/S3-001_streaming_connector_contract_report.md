# S3-001 Streaming Connector Contract Report

Gate: S3 streaming ingestion / data gate  
Sprint/milestone: S3 Streaming ingestion  
Requirement IDs: FR-002, NFR-003  
Status: partial contract slice for #15 / S3-001; not full FR-002/NFR-003 completion.

## Scope covered

- Added project-owned streaming connector contracts for subscriptions and event envelopes.
- Covered trade, quote, order-book, heartbeat, and lifecycle event schemas with strict/frozen Pydantic validation and unknown-field rejection.
- Preserved event-time correctness with distinct `event_ts`, optional `source_ts`, and `ingest_ts` fields.
- Added heartbeat observed/missed policy, disconnect/reconnect lifecycle states, deterministic retry/backoff helper, and source-register-aligned approval checks.
- Source approval now models exact S0-004/source-register states for `license_review_status`, `approved_use_status`, and `production_use_status`, plus evidence/reviewer fields.
- Source IDs support register values such as `coinbase_spot_market_data` and uppercase template IDs such as `TEMPLATE_NEW_SOURCE`.
- Fixture-only/test approval uses separate `fixture_only=True` metadata and is limited to `subscription.synthetic_only=True`; it is not a register enum state and cannot authorize non-synthetic streams.
- Non-synthetic stream authorization requires license review in `{approved, approved_with_restrictions}`, `approved_use_status == paper_approved`, production use in `{paper_only, approved_with_restrictions, production_approved}`, matching source ID, and evidence/reviewer fields.
- Test-local in-memory synthetic fixture connector performs no network I/O and is not exported from production contracts.

## Scope explicitly not covered

- No live WebSocket/API/network stream and no real exchange source ingestion because current market sources are `blocked_pending_review`.
- No freshness/gap/duplicate metric implementation or evidence; deferred to #16.
- No stale-feed strategy/risk fail-closed signal or evidence; deferred to #17.
- No Docker stream profile, Redpanda, dashboard, or service smoke evidence; deferred to #18.
- No historical storage/normalization; deferred to #12/#13.

## Docker/runtime impact

- No new runtime services, Docker profiles, brokers, datastores, or external connector dependencies were introduced.
- Tests run fully offline using synthetic fixtures.

## Evidence artifacts

- Code: `src/ta_model/contracts/streaming.py`
- Exports: `src/ta_model/contracts/__init__.py`
- Tests: `tests/test_streaming_connector_contracts.py`

## Tests run

- `uv run ruff check .` — `All checks passed!`
- `uv run mypy src tests` — `Success: no issues found in 7 source files`
- `uv run pytest` — `43 passed in 0.35s`

## Anti-drift checks

- Source approval fails closed for blocked sources; tests also cover direct `events()` calls before successful connect.
- No direct ccxt/raw exchange objects are exposed in public streaming contracts.
- No live capital, leverage, margin, derivatives, shorting, paper routing, or autonomous promotion path was introduced.
- Synthetic stream tests verify the lowest-risk path without claiming validation from real market data.

Decision: implementation evidence ready for integration review.
