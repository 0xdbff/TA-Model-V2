# S7-003 Model Registry Foundations Evidence Report

## Requirement trace

- Issue: #33 / Sprint S7-003.
- Requirements: FR-008, FR-019, NFR-005.
- Scope: MLflow model-registry state/rollback metadata foundations only. No candidate
  forecasting (#32), validation reporting (#34), serving, online updates, live capital,
  derivatives, leverage, or autonomous promotion path was added.

## Docker/profile impact

- `docker-compose.yml` now includes approved-stack registry services under `core` and
  `research` profiles: MLflow registry, PostgreSQL backend store, and MinIO artifacts.
- Images/packages are pinned (`postgres:16.4`,
  `minio/minio:RELEASE.2024-12-18T13-15-44Z`, `python:3.12.8-slim`,
  `mlflow==2.17.2`, `psycopg2-binary==2.9.10`, `boto3==1.35.99`).
- Local environment defaults are explicitly non-secret placeholders. Operators must
  override them outside version control before any non-local use.
- Durable registry metadata/artifact state uses named PostgreSQL/MinIO volumes; no
  registry audit state is intentionally stored in ephemeral-only containers.

## Acceptance evidence

- Added project-owned Pydantic contracts for model registry records, MLflow references,
  review metadata, approval metadata, rollback pointers, and state transitions.
- Registry records map `TrainingRunResult` lineage into deterministic model/version IDs,
  record hashes, dataset/config/code commit lineage, metrics, artifacts, MLflow URIs,
  actor/timestamp/reason fields, and current state.
- Fail-closed validators reject champion/shadow states without rollback pointer plus
  approved review/approval metadata, reject invalid transition combinations, and keep
  `auto_promotion_enabled` as literal `False`.
- Tests cover valid candidate and champion metadata, rollback requirements, invalid
  transition rejection, deterministic identity, and no-auto-promotion enforcement.

## Validation

- `uv run ruff check .` — passed.
- `uv run mypy src tests` — passed (`Success: no issues found in 59 source files`).
- `uv run pytest tests/test_training_runner.py tests/test_model_registry.py` — passed
  (`12 passed`).
- `uv run pytest` — passed (`227 passed`).
- `docker compose config` — passed; no default-profile services are started implicitly.
- `docker compose --profile core --profile research config` — passed; registry services
  render with local placeholder credentials only.

## Anti-drift checks

- No direct downstream dependency on third-party MLflow Python objects was introduced.
- No new registry/datastore/broker beyond approved MLflow/PostgreSQL/MinIO stack was
  introduced.
- No autonomous promotion, widened model limits, serving route, live credential, paper/live
  gateway, or risk-engine bypass was introduced.
- No real secrets were committed; Compose defaults are local placeholders only.

## Follow-up notes for #34

- Validation reporting can consume `ModelRegistryRecord` and `ModelRegistryTransition`
  for registry state evidence, approval/review status, rollback target lineage, and
  deterministic audit IDs.
