# Technical Stack and Docker Plan

**Document status:** early stack decision for implementation planning
**Purpose:** choose a practical stack before implementation starts, so sprint work and GitHub issues do not drift into incompatible tools.
**Non-duplication note:** this document does not restate product requirements. It turns the current spec into default technology, runtime, and Docker decisions.

---

## 1. Stack decision summary

Use a **Python-first, Dockerized, event-time, validation-first stack**.

| Layer | Selected default | Why |
|---|---|---|
| Primary language | Python 3.12 | Strong data/ML ecosystem; fastest path to ingestion, features, modeling, simulation, and paper trading. |
| Dependency/build | `uv`, `pyproject.toml`, locked dependencies | Fast reproducible Python environments; works well in Docker and CI. |
| APIs/CLIs | FastAPI, Pydantic v2, Typer | Typed contracts for services and CLI workflows; clean validation for event schemas. |
| Exchange connector SDK | `ccxt` | Pinned Python dependency for future REST-based spot exchange adapters and metadata discovery. It must remain behind project connector/gateway contracts and does not approve any venue source, live credentials, paper routing, or risk bypass by itself. |
| Dataframes/query | Polars, PyArrow, DuckDB | Efficient local/batch analytics, Parquet snapshots, leakage-safe dataset generation. |
| Relational/time-series store | PostgreSQL 16 with TimescaleDB extension | Durable metadata, orders, risk state, audit records, and time-series querying in one Dockerized service. |
| Object/artifact store | S3-compatible storage via MinIO locally | Immutable bronze payloads, dataset snapshots, model artifacts, reports, and replay evidence. |
| Experiment/model registry | MLflow with PostgreSQL backend and object-store artifacts | Reproducible experiments, model registry states, metrics, artifacts, and rollback pointers. |
| Workflow orchestration | Prefect | Python-native scheduled/backfill/training/paper workflows without adopting heavyweight infra early. |
| Event bus | Redpanda/Kafka-compatible event stream | Local Docker-compatible stream for market events, paper trading, and integration tests. |
| ML/modeling | scikit-learn + LightGBM for baselines; PyTorch for sequence/transformer candidates; optional Hugging Face `transformers` for gated research candidates | Baselines first; deep model only after baseline/evaluation harness exists. Hugging Face usage must stay within existing Python/PyTorch + MLflow workflows and must not introduce a new runtime service, datastore, registry, or deployment path. |
| Validation/testing | pytest, Hypothesis, Pandera, Pydantic schema tests | Unit, property, dataframe, event-contract, and leakage checks. |
| Observability | OpenTelemetry, Prometheus, Grafana, structured JSON logs | Metrics, traces, latency, dashboards, and alert-ready telemetry. |
| Security checks | detect-secrets, Trivy, dependency audit in CI | Secret and supply-chain checks before runtime expansion. |
| Containerization | Docker + Docker Compose profiles | Reproducible local, CI, research, simulation, and paper environments. |

---

## 2. Deliberately deferred stack choices

These are blocked unless an issue/ADR proves they are needed:

| Deferred tool/scope | Default decision |
|---|---|
| Kubernetes | Defer until P1/P2 deployment scale requires it. Compose is enough for MVP local/CI/paper. |
| Feast or heavy managed feature store | Defer. Use versioned feature definitions, Parquet snapshots, DuckDB/Polars, and registry metadata first. |
| Ray/Dask/Spark | Defer until backtest/training throughput evidence exceeds Polars/DuckDB/single-node limits. |
| Full web UI | Defer. Use reports, dashboards, and APIs first; add UI only when operator workflow demands it. |
| Online learning framework | Prohibited for live impact in MVP. Shadow candidates only. |
| Derivatives/margin-specific systems | Defer to P2 and only after derivative-specific controls exist. |

### 2.1 Hugging Face and 1B-class model guidance

Hugging Face `transformers` is an **optional research/modeling library**, not a
runtime dependency or promotion shortcut. It may be used for sequence and
time-series transformer candidates only when package versions, model checkpoint
revisions, model licenses, artifact hashes, and offline/reproducible download
paths are controlled through the existing dependency lock, source/license review,
and MLflow artifact/registry workflow. Any dependency or checkpoint introduction
must be handled by a traceable issue/PR with requirement IDs, Docker/profile
impact, validation evidence, and anti-drift checks.

For a future 1B-class candidate, using the 2026 option set as the planning
baseline, the preferred architecture is a **patched decoder-only time-series
Transformer** inspired by time-series transformer and foundation-model families
such as PatchTST, TimesFM, and Chronos, with market-specific numeric patch
embeddings and probabilistic forecast heads. This is preferred over a general
text LLM because it aligns with event-time causal forecasting, supports long
market contexts more efficiently than per-timestep attention, avoids fragile
text-token numeric modeling, and can emit calibrated return/volatility/quantile
distributions needed by the strategy layer.

Architecture guardrails:

1. Treat 1B-class models as S7+ research candidates only; they must not block
   baseline, simulator, risk, audit, or paper-readiness work.
2. Start with smaller PatchTST/Chronos/TimesFM-style pilots before scaling; scale
   toward ~0.7B–1B parameters only after smaller candidates show reproducible,
   net-of-cost, benchmark-relative, calibrated improvement.
3. Use causal/event-time inputs only. No feature, target, patch, benchmark, or
   normalization statistic may use future data.
4. Produce probabilistic outputs: return distribution, quantiles, uncertainty,
   and calibration metadata. Point forecasts alone are insufficient.
5. Compare against cash/no-trade, buy-and-hold, basket benchmarks, LightGBM,
   simple PyTorch sequence baselines, and S5 baseline reports before promotion.
6. Keep model promotion gated through MLflow states and owner review; no online
   self-update, auto-promotion, or direct paper/live routing is allowed.
7. Do not commit Hugging Face tokens, private model credentials, downloaded
   weights, or unapproved pretrained checkpoints. Pin checkpoint revision hashes
   where practical and record model-card/license evidence.

### 2.2 CCXT exchange connector guidance

`ccxt` is an approved project dependency for reducing exchange-specific REST API
plumbing in future connector work. It is a library dependency, not a new runtime
service, datastore, broker, registry, gateway, source approval, or execution
permission.

Guardrails:

1. Use `ccxt` only behind project-owned connector and execution-gateway
   interfaces so downstream ingestion, simulator, risk, paper, and future live
   paths do not depend directly on third-party exchange objects.
2. Treat every exchange exposed by `ccxt` as blocked until its row in
   `docs/source_license_register.csv` is reviewed and approved for the intended
   use. Binance spot is important for future support, but its source row starts
   `blocked_pending_review`.
3. Standard `ccxt` covers REST exchange integration. WebSocket streaming, if
   needed for S3/S10 paper paths, must be implemented through an approved native
   connector or separately approved dependency and source review.
4. Do not commit exchange API keys, secrets, account IDs, private payloads, paid
   data, or confidential terms. Any future credential use must be least-privilege,
   withdrawal-disabled, and isolated by Docker profile/environment.
5. `ccxt` cannot bypass instrument-master constraints, event-time data rules,
   source/license gates, independent pre-trade risk, kill switches, idempotency,
   audit traces, or paper/live promotion gates.
6. Derivatives, margin, leverage, shorting, futures, perpetuals, and funding
   endpoints remain out of MVP scope even if an exchange SDK exposes them.

---

## 3. Docker runtime topology

Docker is the default runtime boundary from Sprint 0 onward. Compose profiles should be introduced incrementally; not every service must exist on day one.

| Compose service | Profile | Purpose | Data durability |
|---|---|---|---|
| `app-dev` | `dev` | Developer/test container with repo mounted; runs lint, tests, fixtures, CLIs. | Ephemeral; source mounted. |
| `api` | `paper`, `ops` | FastAPI service for health, config, risk state, kill switch, registry lookup, and operator APIs. | PostgreSQL-backed. |
| `worker` | `research`, `paper` | Prefect worker for backfills, feature jobs, simulations, training, paper loops. | PostgreSQL/MinIO-backed. |
| `postgres` | `core` | Metadata, instrument master, configs, orders, risk state, audit, Timescale hypertables. | Named volume; backups required before real paper evidence. |
| `minio` | `core` | Raw payloads, Parquet snapshots, MLflow artifacts, validation reports. | Named volume; immutable-object policy where practical. |
| `mlflow` | `research` | Experiment tracker and model registry. | PostgreSQL backend + MinIO artifacts. |
| `redpanda` | `stream`, `paper` | Market event and paper-event bus. | Named volume for integration/paper runs. |
| `prometheus` | `observability` | Metrics scrape and alert-ready telemetry. | Named volume for paper windows. |
| `grafana` | `observability` | Data/model/strategy/portfolio/execution dashboards. | Named volume; dashboard JSON committed. |

### Required Docker profiles

| Profile | Minimum use |
|---|---|
| `dev` | Run local tests, schema checks, and fixture simulations without host-specific setup. |
| `core` | Start PostgreSQL/TimescaleDB and MinIO for durable local/integration state. |
| `research` | Run backfills, feature builds, baselines, training, MLflow, and report generation. |
| `stream` | Run event bus and connector stream integration tests. |
| `paper` | Run live-data-to-paper loop with risk, paper gateway, TCA, telemetry, and audit trail. |
| `observability` | Run Prometheus/Grafana dashboards and alert smoke tests. |

---

## 4. Containerization rules

1. Use multi-stage Dockerfiles for app images once application code exists.
2. Run containers as non-root wherever possible.
3. Do not bake credentials, API keys, exchange secrets, or data licenses into images.
4. Use `.env.example` for local shape only; real secrets must come from Docker secrets, environment injection, or an approved secrets manager.
5. Every service that can affect paper/live behavior must have a healthcheck.
6. CI should build the app image and run tests inside Docker before paper-readiness work begins.
7. Paper-mode Compose must not mount developer notebooks with trading credentials.
8. Research containers must not have live-execution keys.
9. Runtime records must capture code commit, dependency lock hash, config hash, and container image tag/digest where practical.

---

## 5. Data and artifact layout

Use storage paths that support immutable snapshots and replay.

| Artifact | Default storage | Naming rule |
|---|---|---|
| Raw source payloads | MinIO bucket `bronze` | `source=<source>/venue=<venue>/date=<yyyy-mm-dd>/<payload_hash>.json` |
| Normalized market data | PostgreSQL/TimescaleDB + Parquet snapshots | Partition by `venue_id`, `instrument_id`, `timeframe`, event date. |
| Feature snapshots | MinIO bucket `gold` / Parquet | Include `feature_version`, `snapshot_id`, and source data version. |
| Dataset snapshots | MinIO bucket `datasets` | Include dataset hash, split rules, label rules, feature version. |
| Experiment artifacts | MLflow/MinIO | Include run ID, code commit, config hash, container tag/digest. |
| Validation reports | MinIO bucket `reports` or committed small markdown summaries | Include gate name, run ID, thresholds, pass/fail, owner. |
| Decision traces | PostgreSQL + optional trace artifacts in MinIO | Use `trace_id` spanning data → feature → model → strategy → risk → order/fill. |

---

## 6. Early implementation implications

Sprint 0 must create or approve:

1. `pyproject.toml` and dependency strategy.
2. Docker base image strategy and Compose profile names.
3. PostgreSQL/TimescaleDB schema migration tool choice.
4. MinIO bucket layout and local credentials policy.
5. MLflow backend/artifact configuration.
6. Hugging Face `transformers` dependency policy for optional research use,
   including model revision pinning, license review, and offline artifact
   capture when transformer candidates are introduced.
7. Redpanda topic naming convention for market, decision, risk, order, fill, TCA, and audit events.
8. CI gates for Docker build, unit/schema tests, leakage tests, secret scan, and minimal integration smoke.

---

## 7. ADR triggers

Create an ADR before any of these changes:

- Replacing Python as the primary implementation language.
- Replacing PostgreSQL/TimescaleDB, MinIO, MLflow, Prefect, or Redpanda.
- Adding a new persistent datastore, event broker, cloud-managed dependency, or workflow platform.
- Introducing Kubernetes, live trading credentials, derivatives-specific runtime, or online model update tooling.
- Removing Docker from local/CI integration expectations.
