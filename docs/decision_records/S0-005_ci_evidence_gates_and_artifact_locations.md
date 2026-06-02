# S0-005 Decision Record — CI Evidence Gates and Artifact Locations

| Field | Value |
|---|---|
| Status | Pending approval; becomes the approved S0 CI evidence baseline once merged via GitHub Issue #6 / PR review. |
| Sprint / gate | S0 Build readiness / `gate:build` |
| Issue | #6 — S0-005: Define CI evidence gates and artifact locations |
| Decision owners | Infrastructure, QA, security, architecture, product/risk |
| Runtime / Docker impact | Governance and CI planning only; no workflow file, Compose file, image, dependency lock, credential, datastore, broker, model registry, or runtime service is changed by this issue. Future executable gates will first affect the `dev` Compose profile and later the `core`, `research`, `stream`, `paper`, and `observability` profiles as those services are introduced by traceable issues. |
| Primary artifacts | This decision record; future CI gate summary, evidence manifest, test reports, scan outputs, Docker image/build evidence, and smoke logs. |
| Scope boundary | Defines required CI evidence gates, failure semantics, and artifact storage paths. It does not implement GitHub Actions, branch protection, application code, runtime services, live credentials, live capital, leverage, derivatives, or autonomous model promotion. |

---

## 1. Requirement and source trace

### Catalog trace used for implementation/PR hygiene

- `NFR-002` — protect API keys and secrets; CI must detect committed secrets,
  prevent secret leakage in logs/artifacts, audit dependencies/images, and avoid
  exposing live-trading credentials to unsafe contexts.
- `NFR-005` — preserve reproducibility; CI must retain objective evidence that a
  PR was checked against a specific commit, dependency lock, config hash, Docker
  image/build, and validation command set where applicable.

### Supporting future gate trace

The initial issue trace is `NFR-002` and `NFR-005`. The CI plan also defines
future hooks for requirements that become executable in later sprints:

- `NFR-001` — leakage tests must fail the build on known future-derived features
  or labels once feature/dataset code exists.
- `NFR-003` and `NFR-006` — reconnect, data freshness, gap, duplicate, and
  fail-closed checks become required once ingestion and live data-health paths
  exist.
- `NFR-004`, `FR-010`, and `FR-011` — traceability, risk-engine, and kill-switch
  evidence become required before simulator, paper, or future live gateways can be
  treated as ready.

### Binding source documents

- `docs/rules/00_delivery_anti_drift_rules.md` — source-of-truth, Docker,
  secret-handling, validation, integration, and stop-the-line rules.
- `docs/02_requirements_catalog.csv` — primary FR/NFR traceability authority.
- `docs/11_tech_stack_and_docker.md` — approved stack, Compose profiles,
  security checks, and artifact storage baseline.
- `docs/12_sprint_execution_playbook.md` — sprint evidence packets, evidence
  storage convention, and gate review template.
- `docs/decision_records/S0-002_technical_stack_and_docker_profiles.md` — stack
  baseline that hands off secret scan, dependency audit, container scan, Docker
  build/test smoke, and evidence artifact expectations to S0-005.

---

## 2. Decision summary

Approve the following CI evidence baseline for the MVP delivery path:

1. Every implementation PR must either run the applicable CI gates or explicitly
   record why a gate is not yet applicable because the relevant code, dependency
   lock, Docker service, or contract does not exist.
2. CI gates are evidence-producing controls, not just pass/fail badges. Each gate
   must publish machine-readable output where practical and be summarized in a
   PR/gate evidence packet.
3. Secret scanning, dependency auditing, container scanning, leakage checks,
   risk/kill-switch forced-breach checks, and replay evidence are fail-closed
   controls once their corresponding project layer exists.
4. Generated evidence must be retained as CI artifacts initially and mirrored to
   approved object storage once `core` storage exists. Small durable summaries may
   be committed under `docs/reports/` when useful for gate review.
5. CI may not introduce live-capital credentials, exchange secrets, leverage,
   derivatives, margin, shorting, online model self-update, or autonomous model
   promotion into any MVP path.

This record intentionally defines the target gates before the repository has
application code, `pyproject.toml`, Dockerfiles, or Compose services. Later
implementation issues must convert these gates into executable workflows without
weakening the semantics below.

---

## 3. Required CI gate matrix

Gate IDs are stable handles for future workflow job names, branch protection,
evidence manifests, and gate reports. Tool versions and exact commands must be
pinned in the dependency lock or workflow/tool image when implemented.

| Gate ID | Purpose | Applies when | Minimum evidence output | Failure semantics | Primary trace |
|---|---|---|---|---|---|
| `ci.traceability` | Prove issue/PR hygiene: requirement IDs, sprint/stage, Docker impact, validation evidence, and anti-drift checklist. | All implementation PRs. | PR body/checklist plus `gate_summary.md` or equivalent summary artifact. | Missing requirement trace, Docker impact, or anti-drift evidence blocks merge until corrected. | `NFR-005` |
| `ci.docs_integrity` | Catch broken documentation-only changes before runtime exists. | Docs, rules, decision records, issue templates, and Markdown/CSV changes. | Markdown/CSV review notes, link/path checks when tooling exists, and `git diff --check` output. | Whitespace/path/link errors block merge; content conflicts with `docs/rules/` require owner decision. | `NFR-005` |
| `ci.lint` | Enforce deterministic style and common static defects. | Python/YAML/TOML/shell/Markdown sources after corresponding files/tooling exist. | Linter log and machine-readable report, for example Ruff JSON for Python. | Lint errors block merge unless an owner-approved, time-boxed exception is recorded. | `NFR-005` |
| `ci.type` | Catch typed-contract drift before runtime or paper behavior changes. | Python packages, Pydantic schemas, CLI/API contracts, and typed service code. | Type-check report, for example mypy output or an approved equivalent selected in `pyproject.toml`. | Type errors block merge for production/runtime code. Explicitly experimental notebooks remain outside paper credentials and cannot satisfy gate evidence. | `NFR-005` |
| `ci.unit_schema_contract` | Prove deterministic logic and contracts. | Application code, schemas, fixtures, contracts, CLI/API code, and migrations. | Pytest JUnit XML, coverage summary where configured, and schema/contract test output. | Test failure, missing required failure-case fixture, or untested contract change blocks merge. | `NFR-005` plus affected FR/NFR |
| `ci.leakage` | Prevent lookahead and event-time violations. | Feature, dataset, simulation, benchmark, label, replay, and model-training code. | Leakage report and JUnit output for marked leakage/event-time tests. | Any known leakage is a stop-the-line failure; validation claims and promotion remain blocked until fixed and rerun. | `NFR-001` |
| `ci.secret_scan` | Detect committed secrets, credentials, tokens, and banned log fields. | All PRs and scheduled scans. | Detect-secrets JSON/SARIF or approved equivalent; reviewed baseline diff; redaction proof for logs where applicable. | Unreviewed secret finding blocks merge. Confirmed committed/logged secret is a stop-the-line incident requiring rotation/removal evidence. | `NFR-002` |
| `ci.dependency_audit` | Detect vulnerable or unpinned dependency risk. | Dependency manifests, lockfiles, Docker build contexts, and scheduled scans. | Dependency audit JSON/SARIF, lockfile hash, and SBOM where practical. | Unresolved critical/high runtime vulnerability, unpinned production dependency, or missing lockfile evidence blocks runtime expansion unless an approved exception records owner, expiry, mitigation, and rollback. | `NFR-002`, `NFR-005` |
| `ci.docker_build` | Prove the Dockerized local/CI boundary builds reproducibly. | Dockerfile or Compose service changes; required before service-dependent integration tests. | Build log, image tag, image digest where practical, Dockerfile/Compose config hash, and dependency lock hash. | Build failure, floating production base tag after stack lock, root/credential anti-pattern, or missing digest evidence blocks affected runtime work. | `NFR-005` |
| `ci.container_scan` | Detect container/package vulnerabilities before runtime expansion. | Built app images and service images controlled by the repo. | Trivy SARIF/JSON or approved equivalent; image digest scanned. | Unresolved critical/high image vulnerability blocks paper-affecting runtime work unless approved with expiry and mitigation. Secrets embedded in images are a stop-the-line failure. | `NFR-002` |
| `ci.compose_smoke` | Exercise the lowest-risk Docker profile for the changed layer. | Compose profiles/services, integration tests, or runtime-adjacent changes. | Compose config validation, service health output, smoke-test JUnit/logs, and relevant container logs on failure. | Failed build, failed healthcheck, missing required healthcheck for paper-affecting services, or inability to run the profile blocks merge for that runtime path. | `NFR-005` plus affected FR/NFR |
| `ci.evidence_manifest` | Tie all gate outputs to commit, PR, commands, hashes, and artifact locations. | All CI runs once an executable workflow exists; manually summarized before automation. | `evidence_manifest.json` plus human-readable `gate_summary.md`. | Missing manifest, missing artifact reference, or mismatched commit/config/lock hash blocks gate completion. | `NFR-005` |

### 3.1 Initial tool choices for executable CI

The following tool choices are approved for future executable workflow work unless
a later traceable issue selects an equivalent and records the rationale:

| Control | Initial tool path | Notes |
|---|---|---|
| Python environment and lock | `uv` with `pyproject.toml` and lockfile | Matches the approved stack; lock hash must appear in evidence when dependencies exist. |
| Python lint/format | Ruff | Exact version pinned in dependencies or workflow tool image. |
| Python type check | mypy | Exact version pinned in dependencies or workflow tool image; changing type-checker later requires a traceable rationale. |
| Unit/schema/contract tests | pytest, Hypothesis, Pandera, Pydantic schema tests | Test markers should distinguish unit, contract, leakage, integration, and slow tests. |
| Secret scan | detect-secrets | Baseline entries must be reviewed; real secrets cannot be accepted into the baseline. |
| Dependency audit | pip-audit | Audit output must cite the dependency lock/hash used for the run; changing audit tool later requires a traceable rationale. |
| Container scan | Trivy | Scan the image digest that the Docker build gate produced. |
| Docker smoke | Docker Compose profiles from `docs/11_tech_stack_and_docker.md` | Start with `dev`; expand only as services are introduced by traceable issues. |

---

## 4. Gate applicability by project maturity

| Project maturity point | Required CI posture |
|---|---|
| S0 documentation-only baseline | PR evidence may be a decision record plus local `git diff --check` and reviewer checklist. No application runtime exists, so lint/type/test/Docker gates are recorded as planned but not executable. |
| First executable CI workflow | Enable `ci.traceability`, `ci.docs_integrity`, `ci.secret_scan`, and `ci.evidence_manifest` for all PRs, independent of whether Python package code exists. |
| First Python package / `pyproject.toml` | Enable `ci.lint`, `ci.type`, `ci.unit_schema_contract`, and `ci.dependency_audit` for Python and config changes while keeping `ci.secret_scan` active for all PRs. |
| First Dockerfile or `dev` Compose profile | Enable `ci.docker_build`, `ci.container_scan`, and `ci.compose_smoke` for `dev` profile build/test evidence. |
| First data/feature/dataset implementation | Add `ci.leakage`, data contract tests, event-time fixtures, and source/license evidence checks. |
| First stateful service in `core` | Add Compose smoke for PostgreSQL/TimescaleDB and MinIO health, durable volume expectations, migration checks, and artifact mirroring handoff. |
| First stream/paper-affecting service | Add profile-specific smoke, healthchecks, stale-feed fail-closed tests, no-live-credential proof, risk/kill-switch forced-breach tests, and trace/audit evidence. |
| S12 MVP paper validation | Require full gate packet: fixed config, run ID, trace samples, risk approvals, TCA/portfolio reports, dashboards where applicable, and reproducible rerun evidence. |

A non-applicable gate must be marked `not_applicable` with the reason, owner, and
future trigger. A gate cannot be marked `skipped` merely for convenience.

---

## 5. Evidence artifact locations

### 5.1 Initial GitHub CI artifact layout

Until `core` storage exists, CI evidence is retained by the CI system and linked
from the PR. Workflow implementations should publish artifacts under a stable
layout equivalent to:

```text
ci-evidence/
  gate_summary.md
  evidence_manifest.json
  traceability/
    pr_checklist.md
  docs/
    diff_check.log
  lint/
    ruff.json
    ruff.log
  type/
    mypy.log
  tests/
    junit.xml
    coverage.xml
    schema_contract.log
    leakage_report.md
  security/
    detect_secrets.json
    dependency_audit.json
    sbom.json
  docker/
    build.log
    image_digest.txt
    trivy.sarif
    compose_config.json
    compose_smoke.log
```

Only artifacts relevant to the applicable gates need to be present. The evidence
manifest must declare absent gates as `not_applicable` with a reason.

### 5.2 Future object-storage layout

After the approved `core` profile exists, long-lived CI and gate evidence should
be mirrored to MinIO using the `reports` bucket path family from
`docs/11_tech_stack_and_docker.md`:

```text
reports/ci/
  source=github_actions/
  repo=TA-Model-V2/
  pr=<pr_number>/
  run_id=<ci_run_id>/
  commit=<git_sha>/
    evidence_manifest.json
    gate_summary.md
    <gate_id>/<artifact files>
```

Validation and runtime artifacts should continue to use their layer-specific
paths when those layers exist, for example:

| Evidence family | Preferred durable location after services exist |
|---|---|
| CI gate summaries | GitHub PR summary plus MinIO `reports/ci/.../gate_summary.md` |
| Test logs/JUnit/coverage | CI artifact; mirrored to MinIO `reports/ci/.../tests/` for gate reviews |
| Security scan outputs | CI artifact and GitHub security/SARIF integration where available; mirrored sanitized summaries only when useful |
| Data quality reports | MinIO `reports/data_gate/` plus PR/gate summary |
| Leakage reports | MinIO `reports/leakage_gate/` plus JUnit in CI artifacts |
| Simulation/backtest reports | MinIO `reports/simulation/` with run/config/data snapshot identifiers |
| Paper/TCA reports | MinIO `reports/paper/` with paper run ID and trace samples |
| Model metrics/artifacts | MLflow with PostgreSQL backend and MinIO artifacts |
| Dashboard definitions | Committed Grafana JSON once dashboards exist; screenshots or exports as CI/gate artifacts |
| Trace replay samples | PostgreSQL/MinIO records plus markdown summary for audit gate review |

Generated logs, reports, scans, and coverage outputs should not be committed to
the repository unless they are small durable summaries intentionally stored under
`docs/reports/`. Corrections create a new run or artifact version; raw evidence
must not be overwritten to make a failed gate appear to pass.

---

## 6. Evidence manifest contract

Every executable CI run should produce an `evidence_manifest.json` containing at
least the following fields:

| Field | Purpose |
|---|---|
| `schema_version` | Version of the manifest shape, starting at `1`. |
| `repo`, `branch`, `base_branch`, `commit_sha`, `pr_number`, `issue_numbers` | Identifies the code and review context. |
| `sprint_or_stage`, `requirement_ids`, `gate_labels` | Preserves traceability to `docs/02_requirements_catalog.csv` and sprint gates. |
| `started_at`, `finished_at`, `ci_provider`, `ci_run_id` | Identifies the run and supports audit review. |
| `docker_profiles`, `services`, `image_tags`, `image_digests` | Records runtime impact and scanned/built images when applicable. |
| `dependency_lock_hash`, `config_hashes`, `source_data_versions` | Records reproducibility inputs when they exist. |
| `gates[]` | One object per gate with `gate_id`, `status`, `command`, `tool_version`, `artifacts`, `artifact_hashes`, `not_applicable_reason`, and `owner`. |
| `exceptions[]` | Owner-approved exceptions with issue link, expiry, risk, mitigation, rollback, and affected requirement IDs. |
| `anti_drift_checks` | Boolean/status fields for no live capital, no leverage/derivatives, no risk bypass, no secrets, no lookahead, and no replay failure. |

The manifest and published logs must not contain secrets, private credentials,
confidential license text, paid raw market data payloads, or live-account details.

---

## 7. Docker/runtime and security rules for CI

This S0-005 issue has **no runtime impact**. It does not create or modify a
Compose file, image, container, credential, dependency lock, or service.

Future CI implementations must follow these runtime rules:

1. The `dev` profile is the first executable CI target for lint, type, tests,
   fixtures, schemas, and local smoke checks.
2. The `core` profile may be used only after PostgreSQL/TimescaleDB and MinIO are
   introduced by traceable issues with durable state rules and safe local secrets.
3. `research`, `stream`, `paper`, and `observability` profile smoke tests are
   added only when their services exist and must include healthchecks, logs, and
   no-live-credential proof.
4. CI must use dummy/local credentials or scoped CI secrets only. Research and
   notebook-style jobs must never receive live-execution credentials.
5. Paper-affecting services require healthchecks and fail-closed evidence before
   they can be claimed ready.
6. Runtime records should capture code commit, dependency lock hash, config hash,
   container image tag/digest, and evidence artifact path where practical.

---

## 8. Failure, exception, and stop-the-line policy

1. The following have no routine exception path and must stop merge/promotion
   claims until remediated with evidence: known lookahead leakage, committed or
   logged secrets, risk-engine bypass, kill-switch bypass, forced-breach order
   reaching a gateway, duplicate order exposure, required replay failure,
   unapproved data use beyond exploration, or any live-capital path in MVP.
2. Non-stop-the-line exceptions, such as a temporary vulnerability waiver, require
   owner approval, affected requirement IDs, risk assessment, mitigation,
   rollback plan, expiry date, and linked issue/PR evidence.
3. Exceptions cannot weaken validation thresholds after a run begins. If an
   assumption changes, the affected validation run must be invalidated or rerun.
4. A missing tool or workflow is not a permanent exception. The PR must record the
   future trigger that makes the gate executable.

---

## 9. Implementation handoff

| Future work | Handoff from this decision |
|---|---|
| First CI workflow issue | Implement gate IDs from Section 3, at minimum enabling traceability, docs integrity, secret scan, and evidence manifest gates for all PRs; publish `gate_summary.md` and `evidence_manifest.json`; wire branch protection to required gates appropriate for the current maturity point. |
| First Python package issue | Add `pyproject.toml`, lock dependencies with `uv`, pin lint/type/test/security tools, make `ci.lint`, `ci.type`, `ci.unit_schema_contract`, and `ci.dependency_audit` executable, and keep `ci.secret_scan` active for all PRs. |
| First Docker profile issue | Build the `dev` app image, run test smoke in Compose, scan the exact image digest, and publish Docker evidence artifacts. |
| S2/S3 data issues | Add source/license register checks, ingestion contract tests, data quality reports, reconnect/freshness evidence, and fail-closed stale-feed tests. |
| S4 feature/dataset issues | Add leakage/event-time tests and dataset hash evidence; known leakage remains stop-the-line. |
| S6/S9 simulator and risk issues | Add venue/cash/inventory rejection tests, forced-breach risk matrix, kill-switch persistence evidence, and duplicate-idempotency tests. |
| S10–S12 paper/audit issues | Add paper loop smoke, no-live-credential proof, TCA reports, dashboard smoke, trace replay samples, and gate review packet artifacts. |

---

## 10. Anti-drift checkpoints

- MVP remains validated paper trading plus promotion recommendation only; CI does
  not enable live capital or live-execution credential flow.
- MVP remains spot-only and liquid-instrument focused; no leverage, margin,
  derivatives, shorting, market making, or HFT scope is introduced.
- CI gates preserve, rather than bypass, independent risk-engine, kill-switch,
  event-time, trace/replay, and no-trade requirements.
- Secret scan, dependency audit, container scan, and Docker smoke evidence are
  required before runtime expansion into higher-risk profiles.
- Evidence artifacts must be tied to immutable commits, lock/config hashes, image
  digests, run IDs, and artifact checksums where practical.
- CI logs/artifacts must not leak secrets, confidential license terms, paid raw
  data payloads, model tokens, or live-account details.
- Validation assumptions, cost settings, benchmark sets, and risk thresholds
  cannot be moved after a run begins to turn a failing gate into a passing one.

---

## 11. Acceptance evidence checklist

- [x] Decision record exists for Issue #6 / S0-005.
- [x] Catalog trace includes `NFR-002` and `NFR-005` from
  `docs/02_requirements_catalog.csv`.
- [x] Docker/runtime impact is explicitly recorded as governance/CI planning only
  with no runtime service, Compose file, image, dependency lock, or workflow
  changed by this issue.
- [x] CI gate plan covers traceability, docs integrity, lint, type checks, unit /
  schema / contract tests, leakage tests, secret scan, dependency audit, Docker
  build, container scan, Compose smoke, and evidence manifest publication.
- [x] Artifact locations are defined for initial CI artifacts and future MinIO
  `reports/ci/...` storage, with generated artifacts kept out of the repo except
  small approved summaries.
- [x] Evidence manifest fields cover commit, PR, issue, requirement IDs, commands,
  tool versions, Docker profile/service impact, hashes, gate status, exceptions,
  and anti-drift checks.
- [x] Failure semantics and stop-the-line controls preserve no secrets, no
  lookahead leakage, no risk/kill-switch bypass, no duplicate order exposure, no
  replay failure, and no live-capital path in MVP.
