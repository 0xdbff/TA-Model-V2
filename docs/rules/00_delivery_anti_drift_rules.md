# Delivery and Anti-Drift Rules

**Status:** binding delivery rule set for implementation work
**Applies to:** all future implementation, planning, GitHub issues, validation gates, Docker/runtime choices, model promotion, and paper/live readiness work.
**Primary references:** `docs/01_project_spec.md`, `docs/02_requirements_catalog.csv`, `docs/05_metrics_validation_matrix.csv`, `docs/07_data_contracts.md`, `docs/08_mvp_backlog.md`, `docs/10_implementation_roadmap.md`, `docs/11_tech_stack_and_docker.md`, and `docs/12_sprint_execution_playbook.md`.

These rules prevent two forms of drift:

1. **Project drift:** scope, architecture, technology, or issue execution moves away from the validation-first product intent.
2. **System drift:** data, features, predictions, calibration, execution quality, strategy behavior, or portfolio risk degrade after validation.

---

## 1. Source-of-truth hierarchy

When requirements conflict, use this hierarchy:

1. Latest explicit user/product decision.
2. Files in `docs/rules/`.
3. Requirement and validation catalogs in `docs/02_requirements_catalog.csv` and `docs/05_metrics_validation_matrix.csv`.
4. Main specification in `docs/01_project_spec.md`.
5. Roadmap, sprint, issue, and stack docs.
6. Existing implementation patterns after implementation begins.

Any intentional deviation from P0 scope, validation gates, risk rules, or the selected stack requires an ADR or issue comment with owner approval, rationale, risk, rollback, and affected requirement IDs.

---

## 2. MVP scope locks

These rules are hard defaults until explicitly changed by an ADR:

| Rule | Drift prevented |
|---|---|
| MVP ends at validated paper trading and a promotion recommendation. No live capital is part of MVP. | Live-risk creep. |
| Initial implementation is spot-only, liquid-instrument focused. No leverage, margin, derivatives, shorting, market making, or HFT scope. | Asset/execution scope explosion. |
| No autonomous online model self-update or auto-promotion. Candidate models move only through gated registry states. | Unsafe model governance drift. |
| No-trade/cash preservation is a first-class decision and must be logged/evaluated. | Overtrading and predictor-only drift. |
| Risk engine remains independent and mandatory between strategy decisions and any simulator/paper/future-live gateway. | Safety bypass drift. |
| Same strategy code must run through simulation, paper, and future live paths via execution-gateway interfaces. | Divergent research vs execution behavior. |

---

## 3. Requirement traceability rules

Every GitHub issue and implementation PR must include:

1. Requirement IDs from `docs/02_requirements_catalog.csv` or an explicit “enabling infrastructure” rationale.
2. Sprint or stage milestone.
3. Acceptance criteria that can be tested or evidenced.
4. Validation gate affected.
5. Required evidence artifact: test output, report, fixture, dashboard screenshot, run ID, trace ID, or checklist.
6. Anti-drift checkpoint: what the work must not change or bypass.

Work without traceability is not “implementation”; it is exploratory and cannot be merged into the main delivery path unless converted into traceable work.

Use `docs/02_requirements_catalog.csv` as the implementation traceability authority. If a similarly named requirement in `docs/01_project_spec.md` uses different numbering, cite the catalog ID for issue/PR tracking and optionally add the spec section as supporting context.

---

## 4. Technology and Docker drift rules

Use `docs/11_tech_stack_and_docker.md` as the default stack decision.

| Rule | Enforcement |
|---|---|
| All runtime services must be runnable through Docker/Compose in local and CI integration contexts. | Issue/PR must name the affected Docker profile or explain why no runtime service is affected. |
| No new database, broker, model registry, workflow engine, observability stack, or language runtime without ADR approval. | Stack additions require rationale, alternatives, failure mode, operating cost, and rollback. |
| Docker images must avoid floating production tags after Sprint 0 stack lock. | Pin image tags and record container digests in reproducibility artifacts where practical. |
| Secrets must not be baked into images, committed in config, or printed in logs. | Secret scanning and banned-log-field checks are required CI gates. |
| Kill-switch state, risk approvals, orders, and audit data cannot rely on ephemeral container state. | Durable state belongs in PostgreSQL/TimescaleDB or object storage, depending on data type. |
| Research/notebook containers must not have live-trading credentials. | Credential scopes are separated by Docker profile/environment. |

---

## 5. Validation drift rules

Validation criteria cannot be weakened after a run begins.

1. Benchmark set, cost assumptions, risk limits, train/validation/test windows, and promotion thresholds must be pre-registered for each validation run.
2. Gross PnL cannot be the primary success metric. Reports must include net-of-cost and benchmark-relative metrics.
3. A model can improve prediction metrics and still fail if strategy, portfolio, execution, audit, or risk evidence fails.
4. A candidate cannot pass without baseline comparison unless the issue explicitly documents risk-control value and owner approval.
5. Any known lookahead leakage is a stop-the-line failure.
6. Any forced-breach order that reaches a gateway is a stop-the-line failure.
7. Any required sampled decision that cannot be replayed is a stop-the-line failure before promotion.

---

## 6. Data, feature, and model drift rules

| Drift area | Rule | Default automated action | Human action |
|---|---|---|---|
| Data completeness/freshness | Required feeds breaching freshness, gap, duplicate, timestamp, or schema thresholds fail closed for affected instruments/strategies. | Block affected strategy/instrument. | Source incident review and repair plan. |
| Feature distribution | Sustained PSI/KS/z-score shifts outside configured bounds cannot be ignored. | Reduce confidence/position cap or force no-trade if severe. | Drift triage with feature/version evidence. |
| Prediction distribution | Entropy, probability, uncertainty, or output distribution shifts outside training envelope must be surfaced. | Disable promotion and reduce caps where configured. | Model review and possible candidate retraining. |
| Calibration/residuals | Calibration, Brier/NLL, residual, or quantile coverage degradation blocks model promotion. | Candidate/champion warning or disable promotion. | Recalibration/retrain decision. |
| Strategy behavior | Turnover spike, no-trade degradation, edge decay, hidden concentration, or cost drag breach must be investigated. | Disable strategy if severe. | Strategy review and issue creation. |
| Execution/TCA | Slippage, reject, latency, fill, or idempotency breach must not be normalized as “market noise.” | Halt or switch affected path if severe. | Execution model recalibration. |
| Portfolio risk | Drawdown, CVaR, beta, concentration, venue cap, or correlation breach overrides model optimism. | De-risk or halt. | Risk committee review. |

No drift response may auto-promote a model, widen limits, or increase capital exposure.

---

## 7. Integration anti-drift rules

1. Integration is contract-first: connector, instrument, feature, dataset, forecast, decision, risk-check, gateway, TCA, and trace contracts must be explicit and tested.
2. Each sprint must exercise the lowest-risk end-to-end path available, even if fixtures are used.
3. Simulator, paper, and future live gateways must share the same order lifecycle contract.
4. Data and decision timestamps must be event-time correct. Ingestion time cannot be used as a substitute for market availability time.
5. Raw data and validation artifacts are immutable. Corrections create new versions with lineage.
6. Manual overrides, approvals, kill-switch changes, and incidents require actor, timestamp, reason, and audit trail.

---

## 8. GitHub issue hygiene rules

Every implementation issue should use the implementation-work template and include:

- `priority:*`, `area:*`, `type:*`, `gate:*`, and `sprint:*` labels.
- Requirement IDs or enabling rationale.
- Docker/profile impact.
- Acceptance tests and evidence.
- Dependencies and integration handoff.
- Anti-drift checklist.

Validation-review issues should use the validation-gate template and stay open until evidence is attached and reviewed.

---

## 9. Stop-the-line triggers

Pause promotion or merge-to-main delivery if any of these occur:

1. Known lookahead leakage.
2. Unlicensed or unapproved data source used beyond exploration.
3. Secrets committed, logged, or embedded in images.
4. Risk engine bypass, kill-switch bypass, or failed forced-breach test.
5. Duplicate order exposure in simulator/paper tests.
6. Required decision replay failure.
7. Model/strategy gate result changed by moving benchmark, risk, or cost assumptions after the run.
8. P1/P2 work blocks or rewrites incomplete P0 controls without approved exception.
9. Any live-capital path introduced before MVP paper gate and compliance gate are complete.
