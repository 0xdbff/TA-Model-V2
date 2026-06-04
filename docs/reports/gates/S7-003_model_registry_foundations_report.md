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
- Compose does not commit password/access-key defaults. Operators must export
  `MLFLOW_POSTGRES_DB`, `MLFLOW_POSTGRES_USER`, `MLFLOW_POSTGRES_PASSWORD`,
  `MLFLOW_MINIO_ROOT_USER`, and `MLFLOW_MINIO_ROOT_PASSWORD` or provide them from an
  ignored `.env` file shaped from `.env.example` before profile config/startup.
- MLflow and MinIO host-published ports are bound to `127.0.0.1` only for local use.
- The app-owned MLflow image declares a non-root `USER`, and the MLflow service has a
  healthcheck against `/health`.
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
- Registry records also validate lineage relationships independently of rebuilt record
  hashes/IDs: training run ID/hash, training config ID/hash, dataset snapshot ID/hash,
  non-empty metrics/artifacts, and MLflow model name/version consistency.
- Champion/shadow governance requires distinct reviewer/approver actors and approval
  timestamps that do not precede review timestamps.
- Tests cover valid candidate and champion metadata, rollback requirements, invalid
  transition rejection, deterministic identity, lineage mismatch tamper regression,
  runtime policy checks, and no-auto-promotion enforcement.

## Validation

- `uv run ruff check .` — passed.
- `uv run mypy src tests` — passed (`Success: no issues found in 60 source files`).
- `uv run pytest tests/test_training_runner.py tests/test_model_registry.py
  tests/test_registry_runtime_policy.py` — passed (`25 passed`).
- `uv run pytest` — passed (`240 passed`).
- `docker compose config` — run with ephemeral local environment variables; passed and no
  default-profile services are started implicitly.
- `docker compose --profile core --profile research config` — run with ephemeral local
  environment variables; passed without committed secret defaults.

## Anti-drift checks

- No direct downstream dependency on third-party MLflow Python objects was introduced.
- No new registry/datastore/broker beyond approved MLflow/PostgreSQL/MinIO stack was
  introduced.
- No autonomous promotion, widened model limits, serving route, live credential, paper/live
  gateway, or risk-engine bypass was introduced.
- No real secrets or committed secret defaults were added; `.env`/`.env.*` are ignored and
  `.env.example` is shape-only with empty values.

## Runtime startup follow-up

- A MinIO bucket-init service was not added in this pass to avoid brittle startup wiring
  around runtime-provided secrets and bucket policies without an accompanying service
  smoke test. Follow-up hardening should add a pinned `mc` init service plus an integration
  startup check that creates/verifies `ta-model-v2-mlflow-artifacts` using only runtime
  env/secrets.
- Image digest pinning is a future provenance hardening step; tags/packages remain pinned
  for this scoped issue.

## Follow-up notes for #34

- Validation reporting can consume `ModelRegistryRecord` and `ModelRegistryTransition`
  for registry state evidence, approval/review status, rollback target lineage, and
  deterministic audit IDs.
