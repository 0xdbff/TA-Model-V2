# Implementation Roadmap — Validation-First Spot Trading Intelligence System

**Document status:** implementation planning artifact
**Planning basis:** `01_project_spec.md`, `02_requirements_catalog.csv`, `03_user_stories.csv`, `04_risk_register.csv`, `05_metrics_validation_matrix.csv`, `07_data_contracts.md`, and `08_mvp_backlog.md`
**Execution rule:** no model, strategy, execution path, or venue path may advance to a higher-risk environment without the required validation evidence and gate approval.

> Binding delivery and anti-drift rules live in `docs/rules/00_delivery_anti_drift_rules.md` and supersede this roadmap where they are more specific.

---

## 1. Delivery posture

The project is a **validation-first, asset-agnostic trading intelligence system**. The MVP is not a live trading product. It is a controlled research-to-paper-trading platform that proves whether the complete decision system can improve net, risk-adjusted, benchmark-aware outcomes after costs while preserving capital and auditability.

### 1.1 MVP scope boundaries

| Boundary | Decision |
|---|---|
| Capital exposure | **No live capital in MVP.** MVP ends at validated paper trading and a promotion recommendation. |
| Asset scope | Start with constrained, liquid **spot** instruments. No margin, leverage, shorting, derivatives, or market-making obligation. |
| Model updates | Offline batch training and scheduled/shadow candidates are allowed. Autonomous live self-training and auto-promotion are prohibited. |
| Strategy stance | No-trade/cash preservation is first-class and must be measured, not treated as a missing signal. |
| Architecture stance | The same strategy code should run through simulation, paper, and future live modes through dependency-injected execution gateways. |
| Safety stance | Risk engine is independent and fail-closed. Model/strategy code cannot bypass pre-trade checks or kill-switch state. |

### 1.2 Delivery cadence

- Use **two-week implementation sprints** unless project capacity dictates otherwise.
- Every sprint has: scope, requirement IDs, deliverables, QA evidence, integration evidence, and exit criteria.
- P0 requirements ship before P1/P2 expansion.
- Sprints may overlap only when interfaces are stable and validation ownership is explicit.

### 1.3 Definition of done for implementation work

A work item is done only when all applicable items are complete:

1. Requirement IDs and acceptance criteria are linked.
2. Interfaces/contracts are documented or schema-tested.
3. Unit tests pass for deterministic logic.
4. Contract tests pass for cross-component interfaces.
5. Integration path is exercised in the lowest-risk environment available.
6. Validation metrics or reports are produced where applicable.
7. Audit/lineage fields are present for decisions, datasets, models, configs, and orders.
8. Failure cases are tested, especially stale data, rejected orders, duplicate retries, limit breaches, and kill-switch state.
9. No secrets are committed, logged, or required in unsafe contexts.
10. Evidence is retained as CI artifact, experiment artifact, report, dashboard snapshot, or checklist entry.

---

## 2. Project stages and gates

The roadmap follows the staged model in `01_project_spec.md` and `08_mvp_backlog.md`.

| Stage | Priority | Goal | Primary deliverables | Blocking exit gate |
|---|---:|---|---|---|
| Stage 0 — Product/risk framing | P0 | Lock objective, MVP scope, benchmarks, universe, risk limits, and data/legal readiness. | Scorecard, source register, risk policy, benchmark policy, implementation backlog. | Build readiness gate |
| Stage 1 — Data foundation | P0 | Build canonical data ingestion and storage foundation. | Instrument master, connectors, bronze/silver stores, historical/live data QA. | Data gate |
| Stage 2 — Research/evaluation core | P0 | Build leakage-safe features, datasets, baselines, and backtest/evaluation core. | Feature engine, dataset builder, baselines, replay simulator, metrics reports. | Leakage + baseline gates |
| Stage 3 — Model/strategy MVP | P0 | Add probabilistic model candidate, decision layer, sizing, and risk controls. | Model registry, inference outputs, decision object, no-trade policy, risk engine, kill switch. | Model + simulation + risk gates |
| Stage 4 — Paper trading | P0 | Validate live data loop without capital. | Paper gateway, portfolio accounting, TCA, dashboards, alerts, trace replay. | Paper + audit gates |
| Stage 5 — Limited live readiness | P1 | Prepare controlled capital exposure after MVP evidence. | Live checklist, compliance review, capital cap, rollback plan, human approvals. | Limited-live gate |
| Stage 6 — Multi-venue/portfolio beta | P1 | Increase robustness and breadth without uncontrolled risk. | Second adapter, adapter contracts, portfolio allocator, shadow champion/challenger. | Multi-venue paper/live evidence |
| Stage 7 — Advanced expansion | P2 | Add exogenous data, derivatives research, and meta-policy only after value is proven. | Alternative data gate, derivative risk model, meta-strategy research. | Incremental-value and risk gates |

---

## 3. Implementation workstreams

| Workstream | Responsibilities | Primary requirements |
|---|---|---|
| Product, governance, and risk policy | Objective function, benchmark policy, scope guardrails, approvals, model/risk cards, promotion workflow. | PG-001–PG-007, FR-010, FR-011, FR-014, NFR-004, NFR-005 |
| Data acquisition and contracts | Data source/license register, connectors, instrument master, bronze/silver/gold layering, lineage, quality gates. | FR-001, FR-002, FR-003, NFR-003, NFR-006 |
| Feature engineering and datasets | Point-in-time TA/liquidity features, feature versioning, chronological splits, leakage prevention. | FR-004, FR-005, FR-006, NFR-001, NFR-005 |
| Modeling and registry | Baselines, probabilistic sequence model, calibration, uncertainty, registry, champion/challenger after MVP. | FR-007, FR-008, FR-019 |
| Simulation and evaluation | Walk-forward replay, synthetic stress, cost/slippage measurement, strategy/portfolio/engine metrics, promotion reports. | FR-012, FR-014, RISK-005 |
| Strategy and risk | Trade/no-trade, expected net edge, sizing, order intent, independent pre-trade checks, kill switch. | FR-009, FR-010, FR-011 |
| Execution and paper trading | Execution gateway abstraction, simulator/paper parity, order lifecycle, paper account, TCA measurement; P1 calibration follows FR-020. | FR-012, FR-013, FR-014 |
| Observability, audit, and operations | Dashboards, alerts, trace IDs, replay harness, incident logging, reproducibility. | FR-014, FR-015, NFR-004, NFR-005 |
| Security and compliance | Secret handling, least privilege, data rights, exchange ToS, recordkeeping, market abuse controls. | NFR-002, RISK-008, RISK-009, RISK-013 |
| Post-MVP expansion | Multi-venue adapters, allocator, offline RL/bandits, alternative data, derivatives readiness. | FR-016, FR-017, FR-018, FR-021, FR-022, NFR-007, NFR-008 |

---

## 4. Sprint plan

### Sprint 0 — Build readiness and control baseline

| Item | Plan |
|---|---|
| Goal | Freeze MVP boundaries, success criteria, initial universe assumptions, risk limits, benchmark set, and validation ownership. |
| Requirements | PG-001–PG-005, FR-010, FR-014, NFR-002, NFR-004, NFR-005 |
| Implementation work | Create benchmark scorecard; draft risk-limit config; create source/license register; define initial instrument universe decision record; define model/strategy promotion states; define CI evidence expectations. |
| QA/validation | Acceptance checklist for build readiness; review P0 open questions from `01_project_spec.md` section 20; confirm no live capital, leverage, derivatives, or online self-promotion in MVP. |
| Integration | Establish repository structure for configs, contracts, test artifacts, and reports. |
| Exit evidence | Approved objective/benchmark policy, risk policy, data-source review path, and initial backlog traceability. |

### Sprint 1 — Instrument master and data contracts

| Item | Plan |
|---|---|
| Goal | Establish canonical asset, venue, instrument, account, and metadata model. |
| Requirements | FR-003, NFR-004, NFR-005, `07_data_contracts.md` |
| Implementation work | Define canonical IDs; implement schemas for assets, venues, instruments, fees, sessions, tick/lot/min-notional; add effective-dated metadata; create seed config for selected spot instruments. |
| QA/validation | Schema tests; mapping tests from canonical instrument to venue symbol; fee/tick/lot/min-notional validation; invalid metadata quarantine tests. |
| Integration | Instrument master feeds ingestion, simulator, strategy, risk, and execution gateway constraints. |
| Exit evidence | Canonical mapping report for MVP instruments and passing instrument contract tests. |

### Sprint 2 — Historical ingestion and data layers

| Item | Plan |
|---|---|
| Goal | Backfill historical bars/trades with immutable raw storage and normalized quality-scored records. |
| Requirements | FR-001, FR-003, NFR-003, NFR-005, RISK-013 |
| Implementation work | Build historical connector interface; implement OHLCTV/trade backfill; persist bronze raw payloads and silver normalized records; store raw payload IDs, checksums, source timestamps, and ingest timestamps. |
| QA/validation | Schema validation; OHLC invariant tests; duplicate detection; missing interval reports; lineage checks from silver to bronze. |
| Integration | Historical data supports feature engine, dataset builder, baselines, and simulator. |
| Exit evidence | Data completeness/gap report below configured threshold or clearly flagged as blocking. |

### Sprint 3 — Streaming ingestion and live data quality

| Item | Plan |
|---|---|
| Goal | Add live trades/quotes/order-book stream where venue supports it, with heartbeat and fail-closed health checks. |
| Requirements | FR-002, FR-005, NFR-003, NFR-006 |
| Implementation work | Implement stream connector interface; freshness, sequence, duplicate, reconnect, and gap-repair logic; emit data-health metrics; block affected streams when stale/degraded. |
| QA/validation | Simulated disconnect/reconnect tests; duplicate prevention; sequence-gap detection; stale-feed alert and block tests. |
| Integration | Streaming data feeds paper trading, streaming features, drift, and execution health dashboards. |
| Exit evidence | Stream health report and reconnect/gap-fill test evidence. |

### Sprint 4 — Feature engine and dataset builder

| Item | Plan |
|---|---|
| Goal | Build point-in-time TA/liquidity features and chronological training/evaluation snapshots. |
| Requirements | FR-004, FR-005, FR-006, NFR-001, NFR-005 |
| Implementation work | Implement TA indicators, returns, volatility, spread/liquidity/cost features; feature version/hash; event-time joins; chronological train/validation/test split builder; dataset snapshot metadata. |
| QA/validation | Leakage tests; shifted-feature tests; higher-timeframe lag tests; batch-vs-stream parity tests; dataset hash reproducibility. |
| Integration | Feature vectors flow into baselines, model training, inference, strategy state assembly, and trace replay. |
| Exit evidence | Leakage gate pass and reproducible dataset snapshot report. |

### Sprint 5 — Baselines and evaluation scorecard

| Item | Plan |
|---|---|
| Goal | Implement baseline strategies and evaluation reports before adding complex models. |
| Requirements | FR-007, FR-014, US-001, US-002 |
| Implementation work | Implement cash/no-trade, buy-and-hold, equal-weight or volatility-targeted basket, simple TA heuristic, and simple ML baseline; produce per-window metrics. |
| QA/validation | Baseline report includes net return, Sharpe, Sortino, Calmar, max drawdown, CVaR, turnover, exposure, costs, and benchmark-relative results. |
| Integration | Baseline outputs become promotion comparators for model, strategy, and portfolio gates. |
| Exit evidence | Baseline gate pass: every candidate can be compared against the fixed benchmark set. |

### Sprint 6 — Simulator and cost/slippage model

| Item | Plan |
|---|---|
| Goal | Build historical replay with realistic execution constraints and net-of-cost accounting. |
| Requirements | FR-012, FR-014, RISK-005 |
| Implementation work | Implement replay engine; cost model for fees/spread/slippage; partial/failed fills; latency; venue constraints; order lifecycle; point-in-time benchmark returns. |
| QA/validation | Same-bar leakage prevention; cash/inventory constraints; venue rule enforcement; stress-cost sensitivity; deterministic seed reproducibility. |
| Integration | Simulator implements the same execution gateway interface as paper/future live mode. |
| Exit evidence | Walk-forward replay report with cost attribution and failed/rejected order accounting. |

### Sprint 7 — Probabilistic model candidate and registry

| Item | Plan |
|---|---|
| Goal | Train and register the first sequence/transformer candidate with calibrated uncertainty. |
| Requirements | FR-008, FR-014, NFR-005 |
| Implementation work | Implement training runner; candidate model; output probabilities/quantiles/uncertainty; calibration layer/report; model registry entry with data snapshot, config, code commit, metrics, and rollback pointer. |
| QA/validation | NLL/Brier; calibration error; quantile coverage; baseline comparison; feature ablation; deterministic rerun tolerance where feasible. |
| Integration | Registry feeds inference service and strategy layer while preserving candidate/champion status. |
| Exit evidence | Model gate recommendation: pass, fail, or continue research with documented reasons. |

### Sprint 8 — Strategy, no-trade, and deterministic sizing

| Item | Plan |
|---|---|
| Goal | Convert forecasts into auditable trade/no-trade decisions and risk-aware target sizes. |
| Requirements | FR-009, FR-014, US-006 |
| Implementation work | Implement decision object; expected gross return, expected cost, uncertainty buffer, expected net edge, benchmark/cash alternative, no-trade reason code, proposed size, approved size placeholder. |
| QA/validation | Decision completeness tests; no-trade quality report; cost threshold tests; uncertainty reduces/blocks size; skipped vs taken trade utility analysis. |
| Integration | Decision object becomes the traceable handoff from model/strategy to risk and order planning. |
| Exit evidence | Strategy gate evidence showing decisions are complete for both trades and abstentions. |

### Sprint 9 — Independent risk engine and kill switch

| Item | Plan |
|---|---|
| Goal | Add fail-closed controls before any paper execution loop can place simulated orders. |
| Requirements | FR-010, FR-011, NFR-006, US-003, US-004 |
| Implementation work | Implement pre-trade checks for notional, position, daily loss, drawdown, liquidity, spread, volatility, venue status, data freshness, duplicate/idempotency, order throttle, and kill-switch state; implement manual and automated kill switches. |
| QA/validation | Forced-breach tests block unsafe orders 100% of the time; kill-switch state survives restart; cancel-open-orders path tested; stale critical feed blocks affected strategy/instrument. |
| Integration | Risk engine is the mandatory gate between strategy/order intent and simulator/paper/future live gateway. |
| Exit evidence | Risk gate pass with breach matrix and kill-switch audit record. |

### Sprint 10 — Paper trading, TCA, dashboards, and alerts

| Item | Plan |
|---|---|
| Goal | Run the full live-data-to-paper-order loop with simulated account state, TCA, and monitoring. |
| Requirements | FR-013, FR-014, NFR-004, NFR-006, US-011 |
| Implementation work | Implement paper gateway; simulated fills; portfolio accounting; order/fill/rejection logs; TCA; live dashboards for data/model/strategy/portfolio/execution/risk; alerts with owner/severity/runbook link. |
| QA/validation | End-to-end integration tests; live-data freshness block; TCA report comparing arrival mid, quote, predicted slippage, realized simulated fill, fees; alert routing smoke tests. |
| Integration | Paper mode uses the same strategy, risk, and gateway contracts as historical replay and future live mode. |
| Exit evidence | Paper readiness gate pass and dashboard/alert evidence. |

### Sprint 11 — Audit replay and MVP validation harness

| Item | Plan |
|---|---|
| Goal | Prove decision traceability and prepare fixed paper-validation window. |
| Requirements | FR-015, FR-014, NFR-004, NFR-005, US-007 |
| Implementation work | Implement trace replay by trace ID; store data snapshot ID, feature version, model version, strategy version, config version, risk checks, order intent, fill/TCA, portfolio snapshot. |
| QA/validation | Random decision replay sample; reproducibility from run ID; audit field completeness; incident/override log test. |
| Integration | Trace IDs span ingestion → feature → model → strategy → risk → order → fill → evaluation. |
| Exit evidence | Audit gate pass: required sampled decisions replay with 100% success before any promotion review. |

### Sprint 12 — MVP paper-validation window and promotion recommendation

| Item | Plan |
|---|---|
| Goal | Run the MVP in paper mode long enough to decide whether to reject, iterate, extend paper validation, or prepare P1 limited-live readiness. |
| Requirements | All P0 FRs and NFRs |
| Implementation work | Freeze paper config; run paper window; collect daily reports; triage incidents; compare against baselines; produce model, strategy, portfolio, execution, data, risk, and audit evidence. |
| QA/validation | Paper metrics: duration/trade count, net risk-adjusted performance, drawdown, CVaR, no-trade quality, TCA error, reject rate, latency, drift, kill-switch health, reproducibility. |
| Integration | Validate that operational runbooks, dashboards, alerts, and replay harness work together during sustained paper operation. |
| Exit evidence | MVP validation report with recommendation: continue research, fix blockers, extend paper, or start P1 limited-live readiness. |

---

## 5. Post-MVP sprint themes

These are intentionally blocked until P0 evidence is complete.

| Theme | Priority | Requirements | Work | Entry condition | Exit evidence |
|---|---:|---|---|---|---|
| P1-A — Multi-venue adapters | P1 | FR-016, NFR-007 | Add second venue/broker adapter; shared capability tests; normalized order lifecycle; venue status/rate-limit handling. | Stable P0 paper system. | Two adapters pass identical contract and lifecycle tests. |
| P1-B — Portfolio allocator and shadow lifecycle | P1 | FR-017, FR-019 | Capital allocation across assets/strategies; champion/challenger; shadow scoring; drift-triggered candidate review. | Multiple validated strategies/assets. | Allocator respects cash, exposure, volatility, correlation, venue, and concentration constraints. |
| P1-C — TCA calibration and limited-live readiness | P1 | FR-020, US-008, US-011 | Calibrate simulated slippage/fill models from paper/live observations; define capital ramp; rollback and daily review. | Paper gate and compliance gate pass. | Slippage/fill error within tolerance and signed live-readiness checklist. |
| P1-D — Offline RL/bandit research | P1 | FR-018 | Offline contextual bandit/RL for sizing, allocation, or strategy selection only; deterministic fallback. | Simulator realism and baseline policies stable. | Policy beats deterministic heuristics without worse drawdown/CVaR and passes reward-hacking checks. |
| P2-A — Alternative data | P2 | FR-021 | Add news/macro/on-chain/fundamental sources through gated feature families. | Core pipeline validated; license owner approved. | License, schema, latency, quality, leakage, and incremental-value gates pass. |
| P2-B — Derivatives/funding/borrow | P2 | FR-022 | Research funding, borrow, margin, liquidation, expiry, multiplier, and derivative-specific risk controls. | Explicit product/risk/legal approval. | Derivative strategies remain blocked until every derivative-specific control exists and is tested. |

---

## 6. Requirements coverage matrix

This matrix uses `02_requirements_catalog.csv` as the execution tracker. Expanded interpretations are in `01_project_spec.md`.

### 6.1 Functional requirements

| Requirement | Priority | Covered by | Required evidence |
|---|---:|---|---|
| FR-001 Historical OHLCTV ingestion | P0 | Sprint 2 | Backfill, schema validation, missing-interval flags, lineage. |
| FR-002 Real-time trades/quotes/order-book ingestion | P0 | Sprint 3, Sprint 10 | Freshness, sequence gaps, duplicates, reconnects measured and alerted. |
| FR-003 Instrument master normalization | P0 | Sprint 1, Sprint 2 | Canonical instrument maps to venue identifiers, constraints, fees. |
| FR-004 Point-in-time TA features | P0 | Sprint 4 | Leakage tests and higher-timeframe lag tests pass. |
| FR-005 Liquidity/cost features | P0 | Sprint 3, Sprint 4, Sprint 6 | Spread, volume, volatility, fees available at decision time. |
| FR-006 Chronological dataset snapshots | P0 | Sprint 4 | Snapshot hash, split rules, labels, feature versions stored. |
| FR-007 Baselines before transformer | P0 | Sprint 5 | Cash, buy-and-hold, TA heuristic, simple ML baseline report. |
| FR-008 Probabilistic outputs and uncertainty | P0 | Sprint 7 | Forecast object with probabilities/quantiles, calibration status, uncertainty. |
| FR-009 Trade/no-trade decisions | P0 | Sprint 8 | Decision object with expected return, expected cost, net edge, uncertainty, reason code. |
| FR-010 Independent pre-trade controls | P0 | Sprint 9 | Forced-breach tests block unsafe orders 100% of the time. |
| FR-011 Manual and automated kill switches | P0 | Sprint 9 | Kill state persists across restart and blocks new orders. |
| FR-012 Historical replay with costs/slippage | P0 | Sprint 6 | Fees, spread, slippage, latency, partial/failed fills represented. |
| FR-013 Paper strategy on live data | P0 | Sprint 10, Sprint 12 | Paper account logs signals, orders, fills, portfolio, TCA, rejections. |
| FR-014 Separate model/strategy/portfolio/engine evaluation | P0 | Sprints 5–12 | Reports include calibration, net strategy metrics, portfolio risk, TCA. |
| FR-015 Decision reconstruction by trace ID | P0 | Sprint 11 | Sampled decisions replay data, features, model output, checks, order intent. |
| FR-016 Multiple adapters | P1 | P1-A | Two adapters pass shared capability and lifecycle tests. |
| FR-017 Portfolio allocation under constraints | P1 | P1-B | Allocator respects exposure, volatility, correlation, venue, cash constraints. |
| FR-018 Offline RL/bandits | P1 | P1-D | Policy beats deterministic heuristic without worse drawdown/CVaR. |
| FR-019 Champion/challenger and shadow mode | P1 | P1-B | Candidate scores live data without influencing orders until approved. |
| FR-020 Slippage/fill model calibration | P1 | Sprint 10 measurement, P1-C calibration | P0 paper mode measures TCA; P1 calibration compares arrival mid, realized fill, predicted slippage, benchmark prices. |
| FR-021 Exogenous feature families | P2 | P2-A | New source passes license, leakage, quality, incremental-value gates. |
| FR-022 Derivatives/funding/borrow/margin | P2 | P2-B | Derivative strategies blocked until derivative-specific data and controls exist. |

### 6.2 Non-functional requirements

| Requirement | Priority | Covered by | Required evidence |
|---|---:|---|---|
| NFR-001 Prevent lookahead leakage | P0 | Sprint 4, Sprint 6 | Automated leakage tests fail build on future-derived features/labels. |
| NFR-002 Protect API keys and secrets | P0 | Sprint 0 onward | Secrets manager plan, no secrets in code/logs, least-privilege/withdrawal-disabled keys where possible. |
| NFR-003 Recover ingestion from disconnects | P0 | Sprint 3 | Reconnect and gap-fill test passes without duplicate data. |
| NFR-004 Log all live decisions and overrides | P0 | Sprints 8–11 | Orders cannot be submitted without traceable decision and risk approval. |
| NFR-005 Re-run experiments from run ID | P0 | Sprints 4, 7, 11 | Metrics reproduce within tolerance from stored data/config/code/model. |
| NFR-006 Fail closed on stale critical feeds | P0 | Sprints 3, 9, 10 | Risk engine blocks affected strategy/instrument when required feed is stale. |
| NFR-007 Onboard new venues without core changes | P1 | P1-A | Adapter contract tests pass; core strategy/model code unchanged. |
| NFR-008 Track infrastructure and data costs | P1 | P1-B/P1-C | Cost report available per experiment and production day. |

---

## 7. Validation strategy

Validation is layered. Passing a lower-level metric is necessary but never sufficient for capital exposure.

| Gate | Applies to | Required evidence | Blocking failures |
|---|---|---|---|
| Data gate | Sprints 1–3 | Source/license register, schema tests, completeness, freshness, duplicates, timestamp drift, lineage. | Unlicensed source, missing required metadata, severe gaps, stale critical feed, lineage break. |
| Leakage gate | Sprint 4 onward | Event-time joins, shifted-feature tests, higher-timeframe lag tests, label leakage tests. | Any known lookahead leakage. |
| Baseline gate | Sprint 5 onward | Cash/no-trade, buy-and-hold, TA heuristic, simple ML results across windows. | Candidate lacks baseline comparison. |
| Model gate | Sprint 7 onward | Calibration, NLL/Brier, quantile coverage, uncertainty utility, ablation, model registry record. | Worse than baseline without documented risk-control value; uncalibrated outputs used for sizing. |
| Simulation gate | Sprint 6 onward | Walk-forward replay, cost/slippage stress, partial/failed fills, latency, venue constraints, stress scenarios. | Same-bar leakage, unrealistic fills, gross-only PnL reporting, cost sensitivity failure. |
| Strategy gate | Sprint 8 onward | Decision completeness, no-trade quality, turnover, cost drag, benchmark-relative performance. | Missing no-trade reasons, hidden churn, skipped trades materially outperform taken trades. |
| Risk gate | Sprint 9 onward | Forced-breach matrix, kill-switch persistence, stale-feed fail-closed, drawdown/CVaR checks. | Any unsafe order reaches gateway in forced-breach tests. |
| Paper gate | Sprints 10–12 | Paper duration/trade count, TCA error, reject rate, drift, latency, drawdown, dashboard/alert health. | Severe risk event, unresolved data outage, replay failure, TCA materially worse than assumptions. |
| Audit gate | Sprint 11 onward | Trace replay sample, decision/order/fill lineage, config/model/data versions. | Required sampled decisions cannot be reconstructed. |
| Compliance gate | Stage 5 onward | Exchange ToS, data rights, jurisdiction, recordkeeping, market abuse controls, key permissions. | Unresolved P0 legal/compliance blocker. |

### 7.1 Minimum validation scenarios

The simulator and paper systems must explicitly test these scenarios before promotion review:

| Scenario | Expected behavior |
|---|---|
| Random walk with costs | System should mostly no-trade; active trading must not appear profitable from gross noise. |
| Trending low-cost market | Trend strategy may participate, capped by volatility and drawdown controls. |
| Mean-reverting range | Trend strategy reduces/no-trades; mean reversion remains P1 unless validated. |
| Crash or drawdown | De-risking overlay reduces exposure; hard drawdown disables strategy. |
| Flash crash/recovery | No same-bar recovery leakage; price collars and risk checks prevent catastrophic fills. |
| Liquidity freeze | Orders blocked or resized; open orders managed according to policy. |
| Spread explosion | Cost threshold triggers no-trade. |
| Venue/API outage | Affected venue halted; reconciliation/runbook triggered. |
| Stale critical feed | Risk engine blocks affected strategy/instrument. |
| Duplicate retry | Idempotency prevents duplicate exposure. |
| Kill-switch restart | Persisted kill state blocks new orders after restart. |
| Drift breach | Alerts fire; model promotion disabled or position caps reduced; no auto-update. |

---

## 8. QA strategy

### 8.1 Test layers

| Layer | Scope | Examples |
|---|---|---|
| Unit tests | Deterministic functions and local invariants. | Indicators, feature timestamps, cost model, sizing, risk predicates, kill state, order math. |
| Schema tests | Data contracts and event shapes. | OHLCTV, trades, quotes/books, features, decision object, risk checks, order lifecycle, fills/TCA. |
| Contract tests | Interfaces between modules. | Connector, execution gateway, simulator gateway, paper gateway, adapter capability, model registry. |
| Integration tests | End-to-end component paths. | Data → feature → dataset → baseline; model → strategy → risk → simulator; live stream → paper → TCA → dashboard. |
| Scenario/stress tests | Failure-mode and market-regime behavior. | Outage, stale data, spread blowout, partial fills, duplicate order, drawdown breach, kill switch. |
| Reproducibility tests | Experiment and decision replay. | Run ID rerun tolerance, trace ID reconstruction, deterministic seeds. |
| Model validation | Statistical/model quality. | Calibration, NLL/Brier, quantile coverage, uncertainty utility, ablation, drift. |
| Paper validation | Operational and portfolio behavior without capital. | Paper duration/trade count, TCA, rejects, latency, risk events, audit replay. |
| Security/compliance QA | Secrets and rule adherence. | Secret scan, key-scope review, data-license checklist, recordkeeping, market-abuse rule checks. |

### 8.2 CI and release checks

Minimum CI/release checks should include:

1. Static validation: lint, type checks where applicable, formatting, dependency health.
2. Secret scanning and banned-log-field checks.
3. Unit and schema tests.
4. Contract tests for data, model, risk, and gateway interfaces.
5. Leakage test suite for features and labels.
6. Simulator smoke run with deterministic seed.
7. Reproducibility smoke test for one run ID or fixture trace ID.
8. Forced-breach risk tests.
9. Kill-switch persistence test.
10. Evidence artifact generation for validation reports.

### 8.3 QA ownership

| Quality area | Primary owner | Review partner |
|---|---|---|
| Data quality and lineage | Data engineering | ML / audit |
| Leakage prevention | ML engineering | Quant / QA |
| Model validation | ML lead | Risk / product |
| Strategy and backtest realism | Quant research | Execution / risk |
| Risk controls and kill switch | Risk owner | Execution / QA |
| Paper trading operations | Ops | Product / risk |
| Auditability and reproducibility | QA / audit | Data / ML / execution |
| Security and compliance | Security / legal | Ops / product |

---

## 9. Integration strategy

### 9.1 Canonical integration path

Every release should preserve this flow:

```text
Market source
  → connector
  → bronze raw event store
  → normalizer + instrument master
  → silver clean market store
  → feature engine / gold feature snapshot
  → dataset builder and/or inference state
  → model registry / inference output
  → strategy decision object
  → independent risk engine
  → simulator or paper execution gateway
  → order/fill/TCA/portfolio events
  → evaluation, monitoring, audit replay
```

### 9.2 Integration contracts

| Contract | Purpose | Must include |
|---|---|---|
| Data connector contract | Normalize backfill/stream behavior across sources. | Backfill, stream, heartbeat, retry, rate-limit handling, provenance metadata. |
| Instrument master contract | Keep venue constraints consistent across data, simulation, risk, and execution. | Tick size, lot size, min notional, fees, sessions, status, effective dates. |
| Feature contract | Ensure point-in-time, versioned features. | Feature timestamp, feature version, input snapshot ID, quality flags. |
| Dataset contract | Ensure reproducible training/evaluation. | Dataset hash, split rules, labels, feature versions, source versions. |
| Forecast contract | Prevent ambiguous model outputs. | Model version, probabilities/quantiles, uncertainty, calibration status, latency. |
| Decision contract | Preserve no-trade and auditability. | Trace ID, action, expected return/cost/net edge, uncertainty, proposed size, rejection/no-trade reason. |
| Risk-check contract | Make safety independent and reviewable. | Pre/post values, thresholds, pass/fail, reason, kill-switch state. |
| Execution gateway contract | Reuse strategy code across simulator, paper, and future live. | Place/amend/cancel/status, idempotency key, balances, venue metadata, order lifecycle. |
| TCA contract | Align simulation and paper/live execution. | Arrival mid, quote, fill price/size, fees, predicted/realized slippage, benchmark prices. |
| Trace contract | Reconstruct any decision. | Data snapshot, feature vector, model output, config, strategy, risk checks, order/fill/portfolio events. |

### 9.3 Environment integration sequence

| Environment | Integration purpose | Promotion requirement |
|---|---|---|
| Local/dev fixtures | Fast deterministic component and contract checks. | Unit, schema, contract, leakage, risk forced-breach tests pass. |
| Research batch | Historical datasets, model training, baseline comparisons. | Dataset reproducibility and baseline gate pass. |
| Historical simulation | End-to-end decision and execution realism on past data. | Walk-forward and stress reports pass. |
| Synthetic/fake asset simulation | Known-regime and failure-mode tests. | Scenario behavior matches expected controls. |
| Shadow live | Live data and candidate scoring without decisions. | Drift, latency, and prediction monitoring stable. |
| Paper trading | Live data with simulated orders/accounting. | Paper gate and audit gate pass. |
| Limited live readiness | P1 only; controlled capital review. | Paper, TCA, kill-switch, compliance, and human approval gates pass. |

---

## 10. Risk-driven controls

| Risk | Priority | Implementation control | Validation evidence |
|---|---:|---|---|
| Market drawdown | P0 | Max drawdown, daily loss, volatility targeting, de-risking overlay. | Stress tests, forced-breach tests, paper drawdown report. |
| Liquidity collapse | P0 | Spread/depth/volume gates, participation caps, no-trade rules. | Spread explosion and liquidity freeze scenarios. |
| Model overfit | P0 | Baselines, walk-forward, ablation, paper gate, drift monitoring. | Baseline/model reports and paper validation. |
| Lookahead leakage | P0 | Event-time joins, shifted tests, higher-timeframe lagging. | Leakage gate with zero known leakage. |
| Fee/slippage underestimation | P0 | Conservative cost model, cost stress, TCA calibration. | Cost sensitivity and TCA reports. |
| API/venue outage | P0 | Venue status monitor, halt affected venue, reconciliation. | Outage scenario and runbook test. |
| Order duplication | P0 | Idempotency keys, order state machine, reconciliation. | Duplicate retry scenario. |
| Secrets compromise | P0 | Secrets manager, least privilege, no withdrawal keys where possible. | Secret scan and key-scope review. |
| Compliance breach | P0 | Legal/data/venue review, market abuse controls, recordkeeping. | Compliance gate before any live review. |
| Data license violation | P0 | Source license register and retention policy. | Data gate and legal review. |
| Benchmark misselection | P0 | Benchmark governance and multiple baselines. | Scorecard and benchmark-relative reports. |

---

## 11. Open decisions before execution

These decisions should be resolved in Sprint 0 or explicitly tracked as blockers:

| Decision | Priority | Owner |
|---|---:|---|
| Select initial asset universe and venue/source set. | P0 | Product / risk / legal |
| Define benchmark set for each asset class. | P0 | Product / quant |
| Configure hard risk limits: daily loss, max drawdown, order notional, position, venue exposure, turnover. | P0 | Risk owner |
| Approve data sources, license terms, retention, and production-use rights. | P0 | Legal / data owner |
| Define minimum paper-trading duration and trade count before any P1 live review. | P0 | Product / risk |
| Choose MVP order types and execution constraints for simulation/paper. | P0 | Execution / risk |
| Decide storage stack and point-in-time feature-store approach. | P0 | Architecture / data |
| Define model governance owners, approvers, rollback criteria, retraining cadence, and drift thresholds. | P0 | ML / risk / product |
| Decide whether order book depth is P0 for the chosen venue or partially deferred to P1. | P0/P1 | Product / execution |
| Decide when, if ever, RL may influence live sizing or strategy selection. | P1 | ML / risk / product |

---

## 12. Operating rule for future live readiness

Limited live trading is **not part of MVP**. It becomes eligible for review only after:

1. All P0 functional and non-functional requirements are implemented and evidenced.
2. Paper gate passes for the configured minimum duration and trade count.
3. TCA confirms paper/live assumptions are conservative enough.
4. Manual and automated kill switches pass simulation and paper tests.
5. Required sampled decisions replay successfully.
6. Compliance/data/venue/security reviews have no unresolved P0 blockers.
7. Human approvers sign a capital cap, rollback plan, incident process, and daily review cadence.

If any of these fail, the system remains in research or paper mode.
