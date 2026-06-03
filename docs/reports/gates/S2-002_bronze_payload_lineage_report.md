# S2-002 Bronze Payload Lineage Report

Gate: S2 Historical ingestion / data gate
Sprint/milestone: S2-002
Requirement IDs: FR-001, NFR-005

## Scope covered

- Added a bronze raw-payload store interface and local filesystem fixture/dev adapter.
- Persists immutable raw bytes with deterministic SHA-256 hash, raw payload ID, URI, byte count, content type, fetched timestamp, and source ID.
- Enforces source/register provenance through `SourceApproval` before raw retention.
- Provides read and checksum verification APIs usable by later S2-003 silver normalization via `RawPayloadReference` and `HistoricalProvenance`.

## Scope explicitly not covered

- No real exchange/API/network data pulls.
- No committed market data payloads.
- No S2-003 silver normalization, S2-004 gap report, streaming health, features/datasets, real MinIO/S3 service, Docker Compose, paper/live routing, leverage, margin, derivatives, or live capital.

## Docker profile/services used

- No runtime service or Docker Compose changes in this issue.
- Production bronze target remains MinIO under the future `core` profile per `docs/11_tech_stack_and_docker.md`; this issue keeps the local filesystem adapter behind `BronzePayloadStore` for fixture/dev use.

## Evidence artifacts

- Tests added: `tests/test_bronze_payload_store.py`.
- Required commands: `uv run ruff check .`; `uv run mypy src tests`; `uv run pytest`.
- QA command evidence:

```text
$ uv run ruff check . && uv run mypy src tests && uv run pytest
All checks passed!
Success: no issues found in 14 source files
...............................................................          [100%]
63 passed in 0.40s
```
- Post-fix local re-run evidence:

```text
$ uv run ruff check . && uv run mypy src tests && uv run pytest
All checks passed!
Success: no issues found in 14 source files
...............................................................          [100%]
63 passed in 0.32s
```

## Anti-drift checks

- Raw data is immutable: existing objects are re-read and must byte-match; tampered/mismatched objects fail closed.
- Source/license state fails closed via `SourceApproval.is_historical_ingestion_approved()`.
- Unknown metadata fields are rejected by frozen Pydantic contract models.
- Fixture tests use synthetic bytes only; no secrets or real market data are introduced.

## Decision

Pass for S2-002 fixture/dev scope.

## Next actions

- S2-003 can link normalized records to `RawPayloadReference.raw_payload_id`.
- Future issue should add a production MinIO/S3 adapter and Docker/core integration evidence.
