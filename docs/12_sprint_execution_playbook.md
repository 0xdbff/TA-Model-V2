# Sprint Execution, Validation, QA, and Integration Playbook

**Document status:** execution playbook
**Purpose:** turn the roadmap into sprint operating mechanics, validation evidence, and integration discipline.
**Non-duplication note:** `docs/10_implementation_roadmap.md` defines the sprint sequence and requirement coverage. This playbook defines how each sprint is run, reviewed, evidenced, and protected from drift.

---

## 1. Sprint operating model

Use two-week sprints by default. Each sprint must produce a **working increment plus evidence**, not just code or research notes.

| Sprint phase | Required activity | Output |
|---|---|---|
| Intake | Select issues from the current milestone only, unless an exception is approved. | Sprint board with requirement IDs, gate labels, dependencies, and owners. |
| Design | Confirm contracts, Docker profile impact, validation method, and anti-drift constraint. | Issue comments or ADRs for decisions that affect architecture/scope. |
| Build | Implement the smallest slice that can be tested through the lowest-risk integration path. | Code/config/tests/reports. |
| Mid-sprint QA | Run unit, schema, contract, and fixture integration tests before broadening scope. | Early failure list and updated blockers. |
| Gate evidence | Produce the sprint evidence packet. | Test logs, reports, run IDs, traces, dashboards, or checklist records. |
| Exit review | Review acceptance criteria, evidence, drift risks, and handoffs. | Pass/fail/conditional decision and next-sprint blockers. |

---

## 2. Work package requirements

Every implementation work package should include:

| Field | Required content |
|---|---|
| Outcome | User/system value in one sentence. |
| Requirement trace | Catalog FR/NFR IDs plus US/RISK IDs where useful, or enabling-infrastructure rationale. |
| Scope boundary | What this issue explicitly will not do. |
| Contract touched | Data, feature, dataset, forecast, decision, risk, gateway, TCA, trace, or none. |
| Docker impact | Profile/service affected or “no runtime impact.” |
| Validation | Tests/reports/scenarios required before done. |
| Integration path | Lowest-risk path to exercise the work. |
| Evidence | Artifact type and storage location. |
| Anti-drift rule | Specific rule from `docs/rules/00_delivery_anti_drift_rules.md`. |

---

## 3. Sprint-by-sprint evidence packets

This table is intentionally compact. Detailed sprint scope remains in `docs/10_implementation_roadmap.md`.

| Sprint | Gate focus | Required evidence packet |
|---|---|---|
| S0 — Build readiness | Objective, stack, Docker, governance, source/risk readiness | ADRs or decision records for stack/universe/benchmarks/risk limits; Docker profile plan; source-license workflow; CI gate plan. |
| S1 — Instrument master | Canonical metadata | Schema tests; instrument mapping report; fee/tick/lot/min-notional tests; invalid metadata quarantine fixture. |
| S2 — Historical ingestion | Data gate part 1 | Backfill run ID; bronze/silver lineage report; schema/OHLC/duplicate/gap tests; source license status. |
| S3 — Streaming ingestion | Data gate part 2 | Disconnect/reconnect test; freshness/gap/duplicate metrics; stale-feed block evidence; stream health dashboard smoke. |
| S4 — Features/datasets | Leakage gate | Feature version/hash; shifted leakage tests; higher-timeframe lag tests; dataset hash reproducibility report. |
| S5 — Baselines/evaluation | Baseline gate | Cash, buy-and-hold, TA heuristic, simple ML reports; benchmark-relative net metrics; scorecard fixture. |
| S6 — Simulator/costs | Simulation gate | Event-time replay report; cost/slippage stress; partial/failed fills; deterministic seed rerun; same-bar leakage prevention. |
| S7 — Model/registry | Model gate | MLflow run/model entry; calibration/NLL/Brier/quantile reports; baseline comparison; model card draft. |
| S8 — Strategy/no-trade | Strategy gate | Decision object schema tests; no-trade reason distribution; cost/uncertainty threshold tests; skipped-vs-taken report. |
| S9 — Risk/kill switch | Risk gate | Forced-breach matrix; durable kill-switch restart test; stale-feed fail-closed test; idempotency/order throttle tests. |
| S10 — Paper/TCA/alerts | Paper readiness | Paper loop smoke; TCA report; portfolio accounting test; dashboard/alert routing evidence; live-data block test. |
| S11 — Audit replay | Audit gate | Trace replay sample; audit field completeness; run-ID reproducibility smoke; override/incident log fixture. |
| S12 — Paper validation | MVP recommendation | Fixed-config paper window report; daily evidence rollups; gate summary; recommendation to reject/iterate/extend/prepare P1. |

---

## 4. QA strategy by implementation layer

| Layer | QA focus | Minimum checks |
|---|---|---|
| Data connectors | Fidelity, resilience, provenance | Schema, retries, rate-limit handling, heartbeat, duplicate/gap detection, raw payload hash. |
| Instrument master | Cross-component consistency | Canonical-to-venue mapping, effective dates, fees, tick/lot/min-notional, session status. |
| Features/datasets | Point-in-time correctness | Leakage tests, shifted features, lagged higher timeframe features, dataset hash rerun. |
| Baselines/models | Justified complexity | Baseline comparison, calibration, uncertainty utility, ablation, deterministic rerun tolerance. |
| Simulator | Execution realism | Next-event fills, costs, latency, partial fills, venue constraints, cash/inventory, rejected orders. |
| Strategy | Decision quality | Decision object completeness, expected net edge, no-trade reason codes, turnover/cost drag. |
| Risk engine | Fail-closed safety | Forced-breach matrix, kill-switch persistence, stale-feed block, drawdown/CVaR thresholds. |
| Paper gateway | Operational parity | Same execution contract as simulator, account state, fills/rejections, TCA, reconciliation. |
| Observability | Detectability | Metrics emitted, dashboards populated, alerts routed with owner/severity/runbook. |
| Audit/replay | Reproducibility | Trace ID reconstructs data, features, model, strategy, risk, order/fill, config versions. |

---

## 5. Integration rules per sprint

1. **Contract before broad integration:** define or update the relevant contract before wiring components together.
2. **Lowest-risk path first:** use fixtures before historical replay, historical replay before shadow live, shadow live before paper, paper before any future live review.
3. **Dockerized integration:** integration tests that require services should run in the relevant Compose profile.
4. **Same gateway contract:** simulator and paper gateway must implement identical lifecycle methods and event shapes.
5. **Trace continuity:** once `trace_id` exists, every new integration path must preserve it.
6. **Fail closed:** missing config, missing fee schedule, stale required feed, unknown venue status, or active kill switch must block orders/intents as specified.
7. **Evidence over assertion:** “works locally” is not exit evidence unless accompanied by reproducible command, run ID, or artifact.

---

## 6. Gate review packet template

Use this structure for each formal sprint/gate review:

```text
Gate:
Sprint/milestone:
Requirement IDs:
Scope covered:
Scope explicitly not covered:
Docker profile/services used:
Evidence artifacts:
Metrics vs thresholds:
Failed tests or unresolved defects:
Drift risks observed:
Security/secrets review result:
Decision: pass | conditional pass | fail | hold
Owner approval:
Next actions:
```

---

## 7. Sprint exit checklist

A sprint cannot be marked complete until:

- [ ] All completed issues include requirement IDs or enabling rationale.
- [ ] Acceptance criteria have objective evidence.
- [ ] Relevant contracts are documented and tested.
- [ ] Docker/runtime impact is documented.
- [ ] Tests include expected failure cases, not only happy paths.
- [ ] Gate evidence is stored or linked.
- [ ] New risks, decisions, and blockers are recorded.
- [ ] No anti-drift stop-the-line trigger is unresolved.
- [ ] P1/P2 work has not displaced incomplete P0 safety and validation work.

---

## 8. Evidence storage convention

Small, durable summaries may be committed under `docs/` when useful. Large or generated artifacts should go to object storage/MLflow after implementation starts.

| Evidence type | Preferred location |
|---|---|
| ADR/decision record | `docs/adr/` |
| Gate review summary | `docs/reports/gates/` |
| Test logs | CI artifact |
| Model metrics/artifacts | MLflow + MinIO |
| Data quality reports | MinIO `reports/data_gate/` plus summary in docs if needed |
| Backtest/paper reports | MinIO `reports/simulation/` or `reports/paper/` |
| Dashboard definitions | committed Grafana JSON once dashboards exist |
| Trace replay samples | PostgreSQL/MinIO records; markdown summary for gate review |
