# S0-004 Decision Record — Source/License Register Workflow

| Field | Value |
|---|---|
| Status | Pending approval; becomes the approved S0 source/license workflow baseline once merged via GitHub Issue #5 / PR review. |
| Sprint / gate | S0 Build readiness / `gate:data` |
| Issue | #5 — S0-004: Create source/license register workflow |
| Decision owners | Data owner, legal/data owner, security, product/risk, QA |
| Runtime / Docker impact | Governance and documentation only; no Compose file, image, container, dependency lock, config file, credential, data pull, or runtime service is changed by this issue. Future approved connectors will affect `research`, `stream`, `paper`, and `core` profiles according to their own issues. |
| Primary artifact | `docs/source_license_register.csv` |
| Scope boundary | Source review workflow and register template only; no source is approved by default, no connector is implemented, no market data is ingested, no credentials are requested or stored, and no live-capital path is introduced. |

---

## 1. Requirement, risk, and source trace

### Catalog trace used for implementation/PR hygiene

- `FR-001` — historical OHLCTV ingestion may start only after the source can be
  legally used, retained, versioned, and traced.
- `FR-002` — real-time trades, quotes, and order-book ingestion may start only
  after stream terms, freshness expectations, reconnect behavior, and rate limits
  are documented.
- `FR-003` — venue metadata used by the instrument master must come from an
  approved source with documented constraints.
- `NFR-002` — credentials, API keys, and license materials must not be committed,
  logged, baked into images, or exposed to unauthorized Docker profiles.
- `NFR-005` — experiments and validation reports must remain reproducible from
  source versions, retention rules, artifact hashes, and register evidence.

### Supporting risk trace

- `RISK-013` — data license violation; controlled by source register, retention
  rules, and legal/data approval before non-exploratory use.
- `RISK-009` — compliance breach; controlled by venue/account restrictions,
  rate-limit adherence, and market-rule review.
- `RISK-008` — secrets compromise; controlled by no committed credentials and
  least-privilege account scopes when credentials are later approved.

### Binding source documents

- `docs/rules/00_delivery_anti_drift_rules.md` — source-of-truth, Docker/runtime,
  data-license, secret-handling, validation, and stop-the-line rules.
- `docs/02_requirements_catalog.csv` — primary FR/NFR traceability authority.
- `docs/04_risk_register.csv` — risk IDs and controls.
- `docs/07_data_contracts.md` — lineage, source timestamps, quality gates, and
  license-dependent retention expectations.
- `docs/10_implementation_roadmap.md` — S0 data-source readiness and later
  ingestion/paper handoffs.
- `docs/11_tech_stack_and_docker.md` — approved storage/runtime baseline for
  future raw payloads, normalized data, reports, and credentials separation.

---

## 2. Decision summary

Approve `docs/source_license_register.csv` as the initial source/license register
template and require every market, benchmark, alternative-data, metadata, and
model-checkpoint source to pass this workflow before it is used beyond controlled
exploration.

Being listed in the register is **not** approval. A source is usable only for the
purposes explicitly allowed by its `approved_use_status` and
`production_use_status` fields. Unknown license terms, retention rights,
redistribution rights, rate limits, event-time fields, account restrictions, or
credential requirements are fail-closed blockers for ingestion, dataset creation,
paper trading, and promotion evidence.

The S0-001 Coinbase and Kraken venue/source candidates are seeded in the register
as `blocked_pending_review` and `not_approved_for_production`. They remain
candidate sources only until legal/data, security, and product/risk owners update
the register with evidence and approval. This decision therefore creates the
workflow and evidence template, but it does not approve an ingestion or paper-use
source by itself.

---

## 3. Register schema and required fields

The committed register starts as a CSV artifact because there is not yet an
application schema or metadata database. Future S1/S2 work may migrate the same
fields into PostgreSQL/TimescaleDB or a typed contract, but the field semantics
below remain binding unless changed through a traceable issue/ADR.

| Field | Required | Purpose |
|---|---:|---|
| `source_id` | Yes | Stable machine-readable source key used by connectors, dataset snapshots, validation reports, and trace/replay metadata. |
| `source_name` | Yes | Human-readable source or vendor name. |
| `venue_id` | Conditional | Canonical venue key when the source is venue-specific. |
| `source_type` | Yes | Source family such as official venue market data, vendor data, alternative data, model checkpoint, or benchmark reference. |
| `priority_scope` | Yes | P0/P1/P2 scope guardrail. P1/P2 sources must not become active P0 dependencies without approval. |
| `requirement_trace` | Yes | FR/NFR/RISK IDs that justify the source. |
| `intended_use` | Yes | Explicit use cases such as historical backfill, streaming, benchmark, simulation, research, or paper. |
| `data_classes` | Yes | Data classes requested, for example OHLCTV, trades, quotes, order book, or venue metadata. |
| `access_method` | Yes | REST, WebSocket, S3, manual upload, model registry, or another approved method. |
| `terms_url` | Yes | Link or reference to terms/license evidence. Confidential terms must be referenced, not committed. |
| `license_name` | Yes | License or contract identifier, or `TBD` until reviewed. |
| `license_review_status` | Yes | Review state: `not_started`, `in_review`, `approved`, `approved_with_restrictions`, `blocked`, or `expired`. |
| `approved_use_status` | Yes | Current allowed use state; see Section 4. |
| `production_use_status` | Yes | Whether production/live-like use is `not_approved_for_production`, `paper_only`, `approved_with_restrictions`, `production_approved`, or `blocked`. MVP remains paper-only even if data rights are later production-approved. |
| `retention_allowed` | Yes | Whether raw and normalized retention is allowed. Unknown retention blocks persistent storage. |
| `retention_period` | Yes | Approved retention period or deletion/archive trigger by source, jurisdiction, and audit need. |
| `redistribution_allowed` | Yes | Whether reports, datasets, dashboards, screenshots, or artifacts can expose the source data outside approved users. |
| `storage_allowed` | Yes | Approved storage locations and constraints, for example MinIO `bronze`, PostgreSQL, committed fixtures, or no persistent storage. |
| `raw_payload_storage` | Yes | Whether immutable raw payload storage is allowed and where raw payload hashes/IDs must be recorded. |
| `derived_data_allowed` | Yes | Whether normalized records, features, labels, benchmarks, or model artifacts may be derived and retained. |
| `rate_limit_policy` | Yes | Documented request/stream limits, reconnect/backoff rules, burst limits, and throttle owner. Unknown limits block connector implementation. |
| `account_constraints` | Yes | API-account restrictions, market-data entitlements, venue-rule restrictions, or jurisdiction limits. |
| `credential_requirements` | Yes | Credential shape and security controls. Secrets or license text must not be committed. |
| `jurisdiction_notes` | Yes | Legal/geographic restrictions or review notes. |
| `privacy_pii_status` | Yes | Whether the source includes PII or other restricted data; PII is not expected for MVP market data. |
| `event_time_fields` | Yes | Source fields used to prove market availability time and prevent ingestion-time substitution. |
| `lineage_required` | Yes | Whether downstream records must carry `source_id`, source version, raw payload ID/hash, and register version. Defaults to `yes`. |
| `source_owner`, `legal_owner`, `security_owner` | Yes | Accountable owners for source fitness, license review, and credential/security review. |
| `review_due_date` | Yes | Next review or expiration date. Expired sources fail closed for new ingestion/paper use. |
| `evidence_link` | Yes | Issue, PR, legal ticket, vendor document, or artifact path proving the current status. |
| `last_reviewed_at`, `approved_by` | Conditional | Required before any status beyond blocked/exploration is granted. |
| `decision_notes` | Yes | Scope caveats, restrictions, exceptions, and handoff notes. |

---

## 4. Approval states and allowed use

### 4.1 License review status

| Status | Meaning | Default action |
|---|---|---|
| `not_started` | No license or data-owner review has happened. | Block all ingestion and persistent storage except minimal exploration described in Section 5. |
| `in_review` | Evidence is being gathered or owner review is pending. | Block ingestion, model training, paper use, and validation claims. |
| `approved` | Terms permit the requested use with no additional restrictions beyond the register. | Allow only the explicitly approved uses. |
| `approved_with_restrictions` | Terms permit use only under listed limits. | Enforce restrictions; missing enforcement blocks use. |
| `blocked` | Terms prohibit or owners reject the source. | Do not use; remove dependent work or replace source through a new review. |
| `expired` | Review date or terms version is stale. | Fail closed for new data pulls and paper use until re-reviewed. |

### 4.2 Approved use status

| Status | Allowed use | Prohibited use |
|---|---|---|
| `blocked_pending_review` | Read public docs and collect non-persistent notes for the review ticket. | No persistent market dataset, no committed raw payloads, no connector fixtures beyond approved samples, no model training, no paper use. |
| `exploration_only` | Minimal, non-production investigation with documented owner approval and no validation claims. | Ingestion pipelines, retained bronze/silver/gold datasets, benchmark evidence, and paper runs. |
| `research_approved` | Offline research/backtest use within retention and redistribution limits. | Streaming paper runs or production/live-like use unless separately approved. |
| `backtest_approved` | Historical ingestion, immutable raw payload storage, normalized datasets, and validation reports under stated restrictions. | Live stream/paper use unless separately approved. |
| `paper_approved` | Historical and streaming use for MVP paper trading with no live capital and with risk/data fail-closed controls. | Live-capital execution or broader production use. |
| `blocked` | None. | All use beyond deletion/reconciliation of prior approved artifacts. |

### 4.3 Production-use status

`production_use_status` records data-rights readiness, not trading readiness.
`production_approved` for data does **not** authorize live capital in the MVP.
Live-capital paths remain blocked by the anti-drift rules, risk gates, paper gate,
audit gate, compliance gate, and future owner approval.

---

## 5. Source onboarding workflow

1. **Propose source row.** Add or update a register row with `source_id`, intended
   use, data classes, requirement trace, owners, and initial status
   `blocked_pending_review` or `exploration_only`.
2. **Collect evidence without secrets.** Link public terms, contract references,
   API documentation, model cards, or legal tickets. Do not commit confidential
   contract text, API keys, license keys, private tokens, or paid data payloads.
3. **Review license and retention.** Legal/data owner records allowed use,
   retention period, redistribution limits, storage locations, derived-data rights,
   review date, and evidence link.
4. **Review security and credentials.** Security owner records credential type,
   account scope, secret-handling path, least-privilege expectations, and any
   Docker profile restrictions. Research/notebook containers must not receive
   live-execution credentials.
5. **Review rate limits and venue/account rules.** Data/ops owner records request
   limits, streaming reconnect/backoff policy, throttle owner, and venue/account
   restrictions. Connectors must not circumvent exchange rules or rate limits.
6. **Review event-time and lineage.** Data/QA owner records event-time fields,
   source versioning, raw payload hash/ID expectations, and lineage handoff to
   datasets, decisions, reports, and replay.
7. **Approve or block.** Owners set `license_review_status`,
   `approved_use_status`, `production_use_status`, `last_reviewed_at`,
   `approved_by`, and `review_due_date`. Unknown required fields keep the source
   blocked.
8. **Attach PR/issue evidence.** Every status change beyond exploration requires
   an issue or PR note with requirement IDs, evidence link, affected Docker
   profile/service if any, and anti-drift checklist.
9. **Re-review on change.** Terms changes, API-policy changes, new data classes,
   new venues, new jurisdictions, retention changes, credential-scope changes,
   alternative-data additions, or production/live-like use requests must re-enter
   the workflow before use.

---

## 6. Runtime, Docker, and storage handoff

This S0-004 issue has **no runtime impact**. It does not create a Compose file,
container, dependency, connector, storage bucket, API credential, or data pull.

Future implementation issues must use the register as a gate:

| Future work | Handoff from this workflow |
|---|---|
| S1 instrument master | Venue metadata and fee/rate-limit assumptions must reference an approved `source_id`; unknown source legality blocks production of canonical mappings for paper use. |
| S2 historical ingestion | Backfill connectors must require `backtest_approved` or stricter status, obey `rate_limit_policy`, store raw payload IDs/hashes only where `raw_payload_storage` allows, and include source/register version in lineage. |
| S3 streaming ingestion | Stream connectors must require `paper_approved` for paper paths, enforce reconnect/backoff and rate limits, and fail closed on expired/blocked source status. |
| S4 datasets/features | Dataset snapshots must record source IDs, source versions, register evidence, retention restrictions, and event-time fields used for point-in-time correctness. |
| S5/S12 validation reports | Reports must cite source/register versions and disclose if benchmark/source approval blocks evaluation. |
| S10 paper trading | Paper runtime may only use sources with `paper_approved` status and must not receive live-capital credentials. |
| P2 alternative data | Alternative sources must pass license, latency, quality, leakage, and incremental-value gates before model use. |

When future runtime services exist, register-derived data belongs in the approved
storage path from `docs/11_tech_stack_and_docker.md`: immutable raw payloads in
MinIO `bronze`, normalized metadata/time-series in PostgreSQL/TimescaleDB and/or
versioned Parquet, reports in MinIO/committed summaries, and credentials through
approved secret paths only.

---

## 7. Anti-drift checkpoints

- MVP remains validated paper trading plus promotion recommendation only; no live
  capital path is introduced by this workflow.
- MVP source use remains liquid spot-instrument focused unless a later approved
  issue expands scope; leverage, margin, derivatives, shorting, market making,
  HFT, and unapproved alternative data remain excluded.
- No unlicensed or unapproved data source may be used beyond controlled
  exploration, and any known violation is a stop-the-line blocker.
- Unknown license, retention, redistribution, storage, rate-limit, event-time, or
  credential terms fail closed for ingestion, paper use, and validation evidence.
- Source approvals cannot bypass the independent risk engine, kill switch,
  event-time correctness, trace/replay requirements, or no-trade controls.
- Data-source changes cannot move validation assumptions after a run begins;
  affected runs must be blocked, invalidated, or restarted with pre-registered
  source versions.
- Secrets, API keys, private model tokens, confidential license text, and paid raw
  data payloads must not be committed, logged, or baked into images.

---

## 8. Acceptance evidence checklist

- [x] Decision record exists for Issue #5 / S0-004.
- [x] Source register template exists at `docs/source_license_register.csv`.
- [x] Template includes license, retention, redistribution, storage, rate-limit,
  production-use, owner, evidence, review-date, event-time, and lineage fields.
- [x] Catalog trace includes `FR-001` and `FR-002` from
  `docs/02_requirements_catalog.csv` and supporting `RISK-013` from
  `docs/04_risk_register.csv`.
- [x] Coinbase and Kraken S0-001 source candidates are present as blocked pending
  review, not approved by default.
- [x] Docker/runtime impact is explicitly recorded as governance-only with no
  runtime service or Compose file changed by this issue.
- [x] Future S1/S2/S3/S4/S10/S12 handoffs explain how the register gates
  instrument metadata, historical ingestion, streaming, datasets, paper use, and
  validation reports.
- [x] Anti-drift controls preserve no live capital, no unapproved data use, no
  secret exposure, no rate-limit circumvention, no event-time bypass, and no
  validation-assumption movement after a run starts.
