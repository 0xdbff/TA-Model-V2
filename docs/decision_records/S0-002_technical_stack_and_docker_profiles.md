# S0-002 Decision Record — Technical Stack and Docker Compose Profile Plan

| Field | Value |
|---|---|
| Status | Pending approval; becomes the approved S0 build-readiness stack baseline once merged via GitHub Issue #3 / PR review. |
| Sprint / gate | S0 Build readiness / `gate:build` |
| Issue | #3 — S0-002: Approve technical stack and Docker Compose profile plan |
| Decision owners | Product, architecture, infrastructure, security, QA |
| Runtime / Docker impact | Governance decision record only; no Compose file, image, container, dependency lock, or runtime service is changed by this issue. The affected future Docker profile plan is documented below. |
| Scope boundary | Stack/profile approval and implementation guardrails only; no credentials, live capital path, connector, datastore instance, broker instance, model registry instance, or paper runtime is introduced. |

---

## 1. Requirement and source trace

### Catalog trace used for implementation/PR hygiene

- `NFR-002` — protect API keys and secrets with no secrets in logs/code,
  least-privilege access, and withdrawal-disabled keys where possible.
- `NFR-005` — preserve reproducibility so experiments and validation evidence can
  be re-run from stored data, config, code, model, and run identifiers.

### Binding source documents

- `docs/rules/00_delivery_anti_drift_rules.md` — binding source-of-truth,
  stack-change, Docker, secret-handling, validation, and stop-the-line rules.
- `docs/11_tech_stack_and_docker.md` — approved technical stack and Docker
  runtime topology baseline referenced by this decision.
- `docs/12_sprint_execution_playbook.md` — S0 evidence expectations and future
  Dockerized integration discipline.
- `docs/02_requirements_catalog.csv` — primary FR/NFR traceability authority.

---

## 2. Decision summary

Approve `docs/11_tech_stack_and_docker.md` as the default implementation stack
and Docker Compose profile plan for the MVP delivery path.

The approved posture is a **Python-first, Dockerized, event-time,
validation-first stack**. Docker Compose is the local and CI integration boundary,
introduced incrementally by profile as sprint work needs it. This decision locks
the default stack choices so later issues can implement runtime services without
selecting incompatible databases, brokers, registries, workflow engines,
observability stacks, or language runtimes by default.

This approval does **not** create running infrastructure in S0-002. It records the
baseline that future implementation issues must follow or explicitly change
through a new ADR/owner-approved exception.

---

## 3. Approved stack baseline

| Layer | Approved default | Stack-control rule |
|---|---|---|
| Primary language | Python 3.12 | Replacing Python requires a new ADR with affected requirement IDs, alternatives, risk, rollback, and owner approval. |
| Dependency/build | `uv`, `pyproject.toml`, locked dependencies | Dependency changes must be locked and reproducible; production/runtime dependencies must not float. |
| APIs/CLIs | FastAPI, Pydantic v2, Typer | Service and CLI contracts must remain typed and schema-validated. |
| Dataframes/query | Polars, PyArrow, DuckDB | Use local/batch analytics before adding distributed compute. |
| Relational/time-series store | PostgreSQL 16 with TimescaleDB extension | Durable metadata, orders, risk state, audit records, and time-series data belong here unless a later ADR changes storage. |
| Object/artifact store | S3-compatible MinIO locally | Raw payloads, datasets, reports, models, and replay evidence are immutable/versioned artifacts. |
| Experiment/model registry | MLflow with PostgreSQL backend and MinIO artifacts | Candidate/champion state, metrics, artifacts, rollback pointers, and promotion evidence use this path; no auto-promotion. |
| Workflow orchestration | Prefect | Python-native backfill, feature, simulation, training, and paper jobs. |
| Event bus | Redpanda/Kafka-compatible stream | Market, decision, risk, order, fill, TCA, and audit event integration path. |
| ML/modeling | scikit-learn + LightGBM baselines; PyTorch sequence candidates; optional Hugging Face `transformers` only under gated research controls | Baselines and evaluation harness ship before complex candidates; checkpoint revisions, licenses, and artifact hashes must be controlled. |
| Validation/testing | pytest, Hypothesis, Pandera, Pydantic schema tests | Unit, property, dataframe, event-contract, leakage, and fixture tests are the default evidence path. |
| Observability | OpenTelemetry, Prometheus, Grafana, structured JSON logs | Telemetry must support gate evidence, incident review, and paper-readiness monitoring. |
| Security checks | detect-secrets, Trivy, dependency audit in CI | S0-005 must turn these into CI/evidence gates before runtime expansion. |
| Containerization | Docker + Docker Compose profiles | Local and CI integration contexts use Compose profiles; paper/future-live-affecting services require healthchecks. |

---

## 4. Approved Docker Compose profile plan

Compose profiles are approved as names and responsibilities. Services may be
implemented incrementally by later traceable issues, but service additions must
stay inside this plan unless a later ADR approves a change.

| Profile | Minimum approved services | Primary purpose | Durability / security expectation | Earliest expected use |
|---|---|---|---|---|
| `dev` | `app-dev` | Developer/test container for lint, tests, fixtures, schemas, and CLIs. | Ephemeral container with source mounted; no production or live-trading secrets. | S0/S1 build and test work. |
| `core` | `postgres`, `minio` | Durable local/integration metadata and artifact foundation. | Named volumes; secrets supplied by environment/Docker secrets; no baked credentials. | S1/S2 schema, data, audit, and artifact work. |
| `research` | `worker`, `mlflow` plus `core` dependencies | Backfills, feature jobs, simulations, training, MLflow tracking, and report generation. | MLflow uses PostgreSQL backend and MinIO artifacts; research containers must not receive live-execution keys. | S2–S7 research/evaluation path. |
| `stream` | `redpanda` | Market-event and connector-stream integration tests. | Named volume when integration evidence requires replay; topic naming must preserve event-time contracts. | S3 streaming work. |
| `paper` | `api`, `worker`, `redpanda` plus `core` dependencies | Live-data-to-paper loop, risk state, paper gateway, TCA, telemetry, and audit trail. | Durable order/risk/audit state; healthchecks required for paper-affecting services; no live capital in MVP. | S10–S12 paper-readiness work. |
| `observability` | `prometheus`, `grafana` | Metrics, dashboards, alert smoke tests, and validation evidence views. | Dashboard definitions committed where useful; paper-window telemetry uses durable volumes. | S10 observability and later gate reviews. |

`docs/11_tech_stack_and_docker.md` also names an `ops` association for the
future `api` service. `ops` is not approved here as an S0-required Compose
profile; it remains deferred until an operator/API issue defines acceptance
evidence, security controls, and runtime impact.

### Runtime impact for S0-002

- No runtime service is changed by this decision record.
- No Docker Compose file is created or modified by this issue.
- Future issues must identify the affected profile/service in their PR evidence
  or explicitly record `no runtime impact`.
- Runtime records should capture code commit, dependency lock hash, config hash,
  and container image tag/digest where practical once services exist.

---

## 5. Security controls for `NFR-002`

1. Credentials, API keys, exchange secrets, model tokens, and data licenses must
   not be committed, baked into images, printed in logs, or stored in notebooks.
2. `.env.example` may describe local configuration shape only. Real secrets must
   come from Docker secrets, environment injection, or an approved secrets
   manager path.
3. Research and notebook-oriented containers must not receive live-trading
   credentials. Paper and future live credential scopes remain separated by
   profile/environment.
4. Exchange/API keys, when later approved, must be least-privilege and
   withdrawal-disabled where the venue supports it.
5. CI gate planning in S0-005 must include secret scanning, dependency audit, and
   container vulnerability scanning before runtime expansion.
6. Structured logs and telemetry must support banned-field checks so secrets are
   not leaked through observability.

---

## 6. Reproducibility controls for `NFR-005`

1. Python dependencies must be declared and locked so local, CI, research,
   simulation, and paper environments resolve the same dependency set.
2. Docker images must avoid floating production tags after the S0 stack lock; tag
   and digest evidence should be captured where practical.
3. PostgreSQL/TimescaleDB stores durable metadata, order/risk/audit state, and
   run/config references. MinIO stores immutable raw payloads, snapshots, model
   artifacts, validation reports, and replay evidence.
4. MLflow is the approved experiment/model registry path for run IDs, metrics,
   model artifacts, candidate/champion state, rollback pointers, and approval
   metadata.
5. Runtime and validation records must be able to resolve code commit,
   dependency lock hash, config hash, data snapshot/model artifact identifiers,
   and container image tag/digest where applicable.
6. No-trade, risk-check, order, fill, TCA, and audit events must remain traceable
   once those contracts exist; future replay failures are stop-the-line blockers.

---

## 7. Deferred choices and ADR triggers

The following remain deferred or blocked unless a later ADR/approved issue proves
necessity, trade-offs, operating cost, failure modes, rollback, and affected
requirement IDs:

- Replacing Python, Docker/Compose, PostgreSQL/TimescaleDB, MinIO, MLflow,
  Prefect, Redpanda, Prometheus/Grafana, or the locked dependency strategy.
- Adding Kubernetes, Feast, Ray/Dask/Spark, a managed/cloud-only dependency, a
  different datastore, a different broker, a different model registry, or a
  separate workflow platform.
- Introducing live-trading credentials, live-capital routing, margin, leverage,
  derivatives, shorting, market-making, HFT, or online model self-update tooling
  into the MVP path.
- Promoting Hugging Face `transformers` from optional gated research library to a
  runtime service/deployment path.

---

## 8. Implementation handoff

| Future work | Handoff from this decision |
|---|---|
| S0-005 CI evidence gates | Convert secret scan, dependency audit, container scan, Docker build/test smoke, and evidence artifact locations into executable CI expectations. |
| S1 instrument master | Use Python/Pydantic schema contracts and plan for PostgreSQL-backed durable metadata without starting unrelated services. |
| S2/S3 ingestion | Persist raw/normalized lineage through MinIO/PostgreSQL and use `stream` profile only for approved connector-stream tests. |
| S4/S5 features, datasets, baselines | Use Polars/PyArrow/DuckDB, immutable snapshots, chronological splits, and reproducible run metadata. |
| S7 model candidate/registry | Use MLflow with PostgreSQL/MinIO; keep candidate/champion promotion gated and reproducible. |
| S9 risk and kill switch | Store kill-switch state, risk approvals, and audit records durably, not in ephemeral containers. |
| S10–S12 paper readiness | Use `paper` and `observability` profiles with healthchecks, telemetry, traceability, and no live capital. |

---

## 9. Anti-drift checkpoints

- MVP remains validated paper trading plus promotion recommendation only; no live
  capital path is introduced by this decision.
- MVP remains spot-only and liquid-instrument focused; no leverage, margin,
  derivatives, shorting, market making, or HFT scope is introduced.
- The independent risk engine, kill switch, event-time data rules, and trace/replay
  expectations remain mandatory for later runtime work.
- No-trade/cash preservation remains a first-class logged and evaluated decision.
- No new database, broker, registry, workflow engine, observability stack, or
  language runtime may be introduced without ADR approval.
- Secrets must not be committed, logged, embedded in images, or exposed through
  research/notebook containers.
- Validation criteria, cost assumptions, benchmark sets, and run configurations
  cannot be weakened after validation runs begin.

---

## 10. Acceptance evidence checklist

- [x] Decision record exists for Issue #3 / S0-002.
- [x] Decision record references `docs/11_tech_stack_and_docker.md` as the
  approved stack/profile baseline.
- [x] Catalog trace includes `NFR-002` and `NFR-005` from
  `docs/02_requirements_catalog.csv`.
- [x] Docker/runtime impact is explicitly recorded as governance-only with no
  runtime service or Compose file changed by this issue.
- [x] Future Docker Compose profile names, services, purposes, durability, and
  security expectations are documented.
- [x] Security controls cover no committed/logged/baked secrets, least privilege,
  profile separation, and CI scan handoff.
- [x] Reproducibility controls cover dependency locks, immutable artifacts, MLflow
  run/model metadata, commit/config/lock/container evidence, and replay handoff.
- [x] Anti-drift controls preserve no live capital, no leverage/derivatives, no
  risk-engine bypass, no unapproved stack expansion, and no validation weakening.
