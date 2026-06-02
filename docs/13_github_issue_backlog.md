# GitHub Issue Backlog and Milestone Pack

**Document status:** issue creation guide and ready backlog
**Purpose:** convert the requirement catalog and roadmap into issue-sized work with validation and anti-drift controls.
**Non-duplication note:** this document does not restate the full specification. It provides GitHub-ready milestones, labels, templates, and issue titles/evidence requirements.

---

## 1. Milestones

Create milestones in this order:

1. `S0 Build readiness`
2. `S1 Instrument master`
3. `S2 Historical ingestion`
4. `S3 Streaming ingestion`
5. `S4 Features and datasets`
6. `S5 Baselines and evaluation`
7. `S6 Simulator and costs`
8. `S7 Model candidate and registry`
9. `S8 Strategy and no-trade`
10. `S9 Risk engine and kill switch`
11. `S10 Paper trading and observability`
12. `S11 Audit replay`
13. `S12 MVP paper validation`
14. `P1 Multi-venue and limited-live readiness`
15. `P2 Expansion research`

---

## 2. Label taxonomy

Use consistent labels so issues can be filtered by priority, area, type, and gate.

| Label family | Examples |
|---|---|
| Priority | `priority:P0`, `priority:P1`, `priority:P2` |
| Type | `type:implementation`, `type:validation`, `type:contract`, `type:adr`, `type:qa`, `type:ops`, `type:security` |
| Area | `area:data`, `area:features`, `area:model`, `area:simulation`, `area:strategy`, `area:risk`, `area:execution`, `area:observability`, `area:audit`, `area:infra`, `area:governance` |
| Gate | `gate:build`, `gate:data`, `gate:leakage`, `gate:baseline`, `gate:model`, `gate:simulation`, `gate:strategy`, `gate:risk`, `gate:paper`, `gate:audit`, `gate:compliance` |
| Sprint | `sprint:S0` through `sprint:S12`, plus `stage:P1`, `stage:P2` |
| Control | `anti-drift`, `docker`, `needs-adr`, `blocks-promotion`, `evidence-required` |

---

## 3. Issue creation rules

1. Prefer one requirement-facing outcome per issue.
2. Keep implementation and validation issues separate when validation requires independent review.
3. Put gate reviews in `type:validation` issues and keep them open until evidence is attached.
4. Use the templates in `.github/ISSUE_TEMPLATE/`.
5. Add a dependency note when an issue cannot start until a prior contract, schema, Docker profile, or gate exists.
6. Do not create P1/P2 implementation issues as active work until P0 gate blockers are resolved; they may exist as backlog issues.
7. Use `docs/02_requirements_catalog.csv` as the implementation traceability authority. If `docs/01_project_spec.md` contains a differently numbered but similar requirement, cite the catalog ID and add the spec section only as context.
8. Each created issue must include labels from every required family: `priority:*`, `type:*`, `area:*`, `gate:*`, and `sprint:*` or approved inactive `stage:*`. The label column below lists primary labels and is not a complete substitute for issue-template hygiene.

---

## 4. Ready-to-create implementation issues

Each issue should include the fields from the implementation-work template.

### S0 — Build readiness

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S0-001 | Lock MVP universe, venue/source candidates, and benchmark policy | PG-001–PG-005, RISK-015 | `priority:P0`, `area:governance`, `gate:build`, `sprint:S0` | Decision record with approved universe assumptions and benchmark set. |
| S0-002 | Approve technical stack and Docker Compose profile plan | NFR-002, NFR-005 | `priority:P0`, `area:infra`, `type:adr`, `docker`, `sprint:S0` | ADR referencing `docs/11_tech_stack_and_docker.md`. |
| S0-003 | Define risk-limit policy and initial kill-switch states | FR-010, FR-011, RISK-001, RISK-002 | `priority:P0`, `area:risk`, `gate:risk`, `sprint:S0` | Risk policy draft with hard/soft limits and owner approval path. |
| S0-004 | Create source/license register workflow | FR-001, FR-002, RISK-013 | `priority:P0`, `area:data`, `gate:data`, `sprint:S0` | Source register template with license, retention, rate limits, production-use status. |
| S0-005 | Define CI evidence gates and artifact locations | NFR-002, NFR-005 | `priority:P0`, `area:infra`, `type:qa`, `sprint:S0` | CI gate plan for lint/type/tests/secret scan/Docker smoke/evidence artifacts. |

### S1 — Instrument master

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S1-001 | Implement canonical asset, venue, instrument, and account schemas | FR-003, NFR-004 | `priority:P0`, `area:data`, `type:contract`, `sprint:S1` | Schema tests and invalid-record fixtures. |
| S1-002 | Implement effective-dated fees, sessions, tick/lot/min-notional constraints | FR-003, FR-010 | `priority:P0`, `area:data`, `area:risk`, `sprint:S1` | Constraint validation report for MVP instruments. |
| S1-003 | Seed MVP instrument mapping from canonical IDs to venue symbols | FR-003 | `priority:P0`, `area:data`, `sprint:S1` | Mapping report showing canonical-to-venue identifiers and metadata. |
| S1-004 | Add instrument-master contract tests for downstream consumers | FR-003, NFR-005 | `priority:P0`, `type:contract`, `area:simulation`, `area:execution`, `sprint:S1` | Contract test suite consumed by ingestion/simulator/risk/gateway. |

### S2 — Historical ingestion

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S2-001 | Implement historical connector interface for OHLCTV and trades | FR-001, TFR-001 | `priority:P0`, `area:data`, `type:contract`, `sprint:S2` | Connector contract tests for backfill, retry, provenance, rate-limit handling. |
| S2-002 | Persist bronze raw payloads with hashes and provenance | FR-001, NFR-005 | `priority:P0`, `area:data`, `gate:data`, `sprint:S2` | Raw payload lineage sample and checksum verification. |
| S2-003 | Normalize historical bars/trades into silver records | FR-001, FR-003 | `priority:P0`, `area:data`, `sprint:S2` | Schema/OHLC/trade invariant test results. |
| S2-004 | Produce historical completeness, duplicate, and gap report | FR-001, US-005 | `priority:P0`, `area:data`, `type:validation`, `gate:data`, `sprint:S2` | Data gate report with blockers flagged. |

### S3 — Streaming ingestion

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S3-001 | Implement streaming connector interface with heartbeat and reconnect | FR-002, NFR-003 | `priority:P0`, `area:data`, `type:contract`, `sprint:S3` | Disconnect/reconnect integration test. |
| S3-002 | Detect live freshness, sequence gaps, duplicates, and timestamp drift | FR-002, NFR-006 | `priority:P0`, `area:data`, `gate:data`, `sprint:S3` | Metrics emitted and stale/gap fixture evidence. |
| S3-003 | Add fail-closed data health signal for affected instruments | FR-002, NFR-006, RISK-006 | `priority:P0`, `area:risk`, `area:data`, `sprint:S3` | Stale critical feed blocks affected strategy/instrument in fixture. |
| S3-004 | Add stream Docker profile smoke test | NFR-003 | `priority:P0`, `area:infra`, `docker`, `sprint:S3` | Compose `stream` smoke evidence. |

### S4 — Features and datasets

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S4-001 | Implement point-in-time TA feature engine | FR-004, NFR-001 | `priority:P0`, `area:features`, `gate:leakage`, `sprint:S4` | Shifted-feature leakage tests pass. |
| S4-002 | Implement liquidity, spread, volatility, and fee features | FR-005 | `priority:P0`, `area:features`, `sprint:S4` | Feature contract tests with decision-time availability. |
| S4-003 | Build chronological dataset snapshot generator | FR-006, NFR-005 | `priority:P0`, `area:features`, `area:model`, `sprint:S4` | Dataset hash, split rules, labels, feature version. |
| S4-004 | Create leakage and batch-vs-stream parity test suite | FR-004, FR-006, NFR-001 | `priority:P0`, `type:qa`, `gate:leakage`, `sprint:S4` | Leakage gate report with zero known leakage. |

### S5 — Baselines and evaluation

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S5-001 | Implement cash, buy-and-hold, equal-weight/vol-target baselines | FR-007, US-002 | `priority:P0`, `area:simulation`, `gate:baseline`, `sprint:S5` | Baseline report across configured windows. |
| S5-002 | Implement simple TA heuristic and simple ML baselines | FR-007 | `priority:P0`, `area:model`, `gate:baseline`, `sprint:S5` | Baseline comparator metrics. |
| S5-003 | Implement evaluation scorecard with net and benchmark-relative metrics | FR-014, US-001 | `priority:P0`, `area:simulation`, `type:validation`, `sprint:S5` | Scorecard includes net return, Sharpe, Sortino, Calmar, drawdown, CVaR, costs. |
| S5-004 | Create baseline gate validation issue | FR-007, FR-014 | `priority:P0`, `type:validation`, `gate:baseline`, `sprint:S5` | Gate decision with pass/fail/blockers. |

### S6 — Simulator and costs

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S6-001 | Implement event-time historical replay engine | FR-012, NFR-001 | `priority:P0`, `area:simulation`, `gate:simulation`, `sprint:S6` | Same-bar leakage prevention test. |
| S6-002 | Implement fees, spread, slippage, latency, partial and failed fills | FR-012, RISK-005 | `priority:P0`, `area:execution`, `area:simulation`, `sprint:S6` | Cost attribution and stress-cost report. |
| S6-003 | Enforce venue constraints and cash/inventory in simulator | FR-003, FR-010, FR-012 | `priority:P0`, `area:simulation`, `area:risk`, `sprint:S6` | Rejection accounting and venue-rule tests. |
| S6-004 | Create synthetic/fake asset scenario suite | FR-012, RISK-001, RISK-002 | `priority:P0`, `type:qa`, `gate:simulation`, `sprint:S6` | Random-walk, trend, crash, spread, liquidity, outage scenario results. |

### S7 — Model candidate and registry

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S7-001 | Implement reproducible training runner | FR-008, NFR-005 | `priority:P0`, `area:model`, `sprint:S7` | Run ID resolves data snapshot, config, commit, seed, metrics. |
| S7-002 | Train first probabilistic sequence/transformer candidate | FR-008, US-002 | `priority:P0`, `area:model`, `gate:model`, `sprint:S7` | Forecast object with probabilities/quantiles/uncertainty. |
| S7-003 | Configure MLflow model registry states and rollback metadata | FR-008, FR-019 | `priority:P0`, `area:model`, `docker`, `sprint:S7` | Candidate/champion metadata and rollback pointer. |
| S7-004 | Produce calibration, uncertainty, and ablation report | FR-008, FR-014 | `priority:P0`, `type:validation`, `gate:model`, `sprint:S7` | NLL/Brier, quantile coverage, calibration, baseline comparison. |

### S8 — Strategy and no-trade

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S8-001 | Implement decision object contract | FR-009, FR-015, US-006 | `priority:P0`, `area:strategy`, `type:contract`, `sprint:S8` | Contract tests for trade and no-trade decisions. |
| S8-002 | Implement expected net edge and no-trade reason policy | FR-009, PG-002 | `priority:P0`, `area:strategy`, `gate:strategy`, `sprint:S8` | Reason-code distribution and edge/cost/uncertainty tests. |
| S8-003 | Implement deterministic sizing with risk-budget placeholders | FR-009, FR-010 | `priority:P0`, `area:strategy`, `area:risk`, `sprint:S8` | Uncertainty/drawdown/cost thresholds reduce or block size. |
| S8-004 | Create strategy gate validation issue | FR-009, FR-014 | `priority:P0`, `type:validation`, `gate:strategy`, `sprint:S8` | Skipped-vs-taken trade utility and turnover/cost-drag report. |

### S9 — Risk engine and kill switch

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S9-001 | Implement independent pre-trade risk-check contract | FR-010, US-003 | `priority:P0`, `area:risk`, `type:contract`, `sprint:S9` | Risk-check event includes values, thresholds, pass/fail, reason. |
| S9-002 | Implement forced-breach matrix for all P0 risk controls | FR-010, RISK-001, RISK-002 | `priority:P0`, `area:risk`, `type:qa`, `gate:risk`, `sprint:S9` | 100% unsafe order block evidence. |
| S9-003 | Implement durable manual and automated kill switch | FR-011, US-004 | `priority:P0`, `area:risk`, `gate:risk`, `sprint:S9` | Restart persistence and cancel-open-orders fixture. |
| S9-004 | Implement idempotency, duplicate retry, and order throttle checks | FR-010, RISK-007, RISK-009 | `priority:P0`, `area:execution`, `area:risk`, `sprint:S9` | Duplicate retry does not create duplicate exposure. |

### S10 — Paper trading and observability

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S10-001 | Implement paper gateway using simulator/live gateway contract | FR-013, TFR-008 | `priority:P0`, `area:execution`, `type:contract`, `sprint:S10` | Same lifecycle contract tests pass for simulator and paper. |
| S10-002 | Implement paper portfolio accounting and order/fill/rejection logs | FR-013, FR-015 | `priority:P0`, `area:execution`, `area:audit`, `sprint:S10` | Paper account fixture and order lifecycle report. |
| S10-003 | Implement TCA report for paper fills | FR-013, FR-014, US-011 | `priority:P0`, `area:execution`, `type:validation`, `gate:paper`, `sprint:S10` | Arrival mid, quote, predicted slippage, fill, fees, error report. |
| S10-004 | Add data/model/strategy/portfolio/execution/risk dashboards and alerts | FR-014, RISK-014 | `priority:P0`, `area:observability`, `gate:paper`, `sprint:S10` | Dashboard smoke and alert routing evidence. |

### S11 — Audit replay

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S11-001 | Implement trace ID propagation across full decision path | FR-015, NFR-004 | `priority:P0`, `area:audit`, `type:contract`, `sprint:S11` | Trace contract spans data, feature, model, strategy, risk, order, fill. |
| S11-002 | Implement decision replay harness by trace ID | FR-015, US-007 | `priority:P0`, `area:audit`, `gate:audit`, `sprint:S11` | Sample trace replay reconstructs original inputs/outputs/checks. |
| S11-003 | Add run-ID reproducibility smoke test | NFR-005 | `priority:P0`, `area:audit`, `type:qa`, `sprint:S11` | Rerun returns metrics within tolerance. |
| S11-004 | Create audit gate validation issue | FR-015, NFR-004, NFR-005 | `priority:P0`, `type:validation`, `gate:audit`, `sprint:S11` | Required sample passes 100% or blockers listed. |

### S12 — MVP paper validation

| Key | Title | Req/risk trace | Labels | Evidence |
|---|---|---|---|---|
| S12-001 | Freeze paper validation config, thresholds, and benchmark assumptions | All P0 | `priority:P0`, `area:governance`, `gate:paper`, `sprint:S12` | Pre-registered paper run config and thresholds. |
| S12-002 | Run fixed MVP paper-validation window | All P0 | `priority:P0`, `area:execution`, `type:validation`, `sprint:S12` | Daily paper reports with run IDs, incidents, TCA, drift, risk events. |
| S12-003 | Produce MVP validation report and recommendation | All P0 | `priority:P0`, `area:governance`, `type:validation`, `sprint:S12` | Recommendation: reject, iterate, extend paper, or prepare P1 limited-live readiness. |

---

## 5. P1/P2 backlog issues

Create these as backlog issues only until P0 paper evidence is complete.

| Key | Title | Req/risk trace | Labels | Entry condition |
|---|---|---|---|---|
| P1-001 | Add second venue/broker adapter with shared capability tests | FR-016, NFR-007 | `priority:P1`, `area:execution`, `stage:P1` | Stable P0 paper system and adapter contract. |
| P1-002 | Implement portfolio allocator under cash/exposure/vol/correlation constraints | FR-017 | `priority:P1`, `area:strategy`, `area:risk`, `stage:P1` | Multiple validated instruments/strategies. |
| P1-003 | Implement champion/challenger shadow scoring workflow | FR-019, US-009 | `priority:P1`, `area:model`, `stage:P1` | Model registry and paper telemetry stable. |
| P1-004 | Calibrate slippage/fill model from paper observations | FR-020, US-011 | `priority:P1`, `area:execution`, `stage:P1` | Paper TCA data available. |
| P1-005 | Draft limited-live readiness checklist and capital-ramp policy | US-008, RISK-009 | `priority:P1`, `area:governance`, `gate:compliance`, `stage:P1` | P0 paper, audit, risk, TCA, and compliance gates pass. |
| P1-006 | Research offline contextual bandit/RL sizing with deterministic fallback | FR-018, RISK-012 | `priority:P1`, `area:model`, `area:strategy`, `stage:P1` | Simulator realism and deterministic baseline stable. |
| P2-001 | Define alternative-data onboarding gate | FR-021, US-012 | `priority:P2`, `area:data`, `stage:P2` | Core pipeline validated and source owner approved. |
| P2-002 | Define derivatives/funding/borrow/margin control requirements | FR-022 | `priority:P2`, `area:risk`, `stage:P2` | Explicit product/risk/legal approval. |

---

## 6. Requirement coverage check

| Requirement group | Covered by issues |
|---|---|
| FR-001 to FR-003 data/instrument foundation | S1-001 through S3-004 |
| FR-004 to FR-006 features/datasets | S4-001 through S4-004 |
| FR-007 to FR-008 baselines/modeling | S5-001 through S7-004 |
| FR-009 strategy/no-trade | S8-001 through S8-004 |
| FR-010 to FR-011 risk/kill switch | S9-001 through S9-004 |
| FR-012 simulation | S6-001 through S6-004 |
| FR-013 paper trading | S10-001 through S10-004 and S12 issues |
| FR-014 evaluation | S5, S7, S8, S10, S12 validation issues |
| FR-015 audit/replay | S11-001 through S11-004 |
| FR-016 to FR-020 P1 expansion | P1-001 through P1-006. Sprint 10 captures P0 TCA measurement/reporting; FR-020 remains P1 calibration from paper/live observations. |
| FR-021 to FR-022 P2 expansion | P2-001 through P2-002 |
| NFR-001 to NFR-006 P0 controls | S0 through S12 gate/evidence issues |
| NFR-007 to NFR-008 P1 controls | P1-001 through P1-005 |
