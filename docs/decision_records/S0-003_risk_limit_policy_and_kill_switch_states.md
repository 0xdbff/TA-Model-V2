# S0-003 Decision Record — Risk-Limit Policy and Initial Kill-Switch States

| Field | Value |
|---|---|
| Status | Pending approval; becomes the approved S0 build-readiness risk baseline once merged via GitHub Issue #4 / PR review. |
| Sprint / gate | S0 Build readiness / `gate:risk` |
| Issue | #4 — S0-003: Define risk-limit policy and initial kill-switch states |
| Decision owners | Risk, product, execution, operations, QA |
| Runtime / Docker impact | Governance decision record only; no Compose file, image, container, dependency lock, config file, or runtime service is changed by this issue. Future implementation will affect the `paper` profile (`api`, `worker`, `redpanda`) and the `core` profile (`postgres`) for durable risk/kill-switch state. |
| Contract touched | Risk policy only; future risk-check and kill-switch event-contract handoffs are specified but not implemented here. |
| Scope boundary | Risk policy and approval path only; no connector, paper loop, exchange credential, live-capital path, risk-engine implementation, or executable limit config is introduced. |

---

## 1. Requirement, risk, and source trace

### Catalog trace used for implementation/PR hygiene

- `FR-010` — enforce independent pre-trade controls; forced-breach tests must
  block unsafe orders 100% of the time.
- `FR-011` — provide manual and automated kill switches; kill state must persist
  across restart and block new orders.
- `NFR-004` — log all live decisions and overrides; future order submission
  cannot occur without traceable decision and risk approval.
- `NFR-006` — fail closed on stale critical feeds; affected
  strategy/instrument paths must be blocked when required feeds are stale.

### Supporting risk and user-story trace

- `RISK-001` — market drawdown; controlled through daily loss, drawdown,
  exposure, volatility targeting, de-risking overlays, and stress tests.
- `RISK-002` — liquidity collapse; controlled through spread/depth/volume gates,
  participation caps, no-trade rules, and TCA.
- `US-003` — risk owner can block unsafe orders before venue submission.
- `US-004` — operator can activate a kill switch that blocks new orders,
  optionally cancels opens, persists state, and logs actor/time/reason.

### Binding source documents

- `docs/rules/00_delivery_anti_drift_rules.md` — source-of-truth,
  validation, Docker/runtime, risk, kill-switch, and stop-the-line rules.
- `docs/02_requirements_catalog.csv` — primary FR/NFR traceability authority.
- `docs/04_risk_register.csv` — project risk IDs and control owners.
- `docs/10_implementation_roadmap.md` — Sprint 0 risk-limit decision and
  Sprint 9 risk-engine/kill-switch implementation handoff.
- `docs/11_tech_stack_and_docker.md` — approved durable state and Docker profile
  baseline.
- `docs/12_sprint_execution_playbook.md` — evidence and gate-review rules.

---

## 2. Decision summary

Approve this draft as the initial risk policy baseline for the MVP delivery path.
The system remains **validated paper trading only** through MVP; no live capital,
leverage, margin, derivatives, shorting, market making, HFT, or autonomous model
self-promotion is introduced or implied by this decision.

Risk limits are split into:

1. **Hard limits** — fail-closed controls that block risk-increasing order
   intents before any simulator, paper, or future live gateway can receive them.
2. **Soft limits** — early-warning controls that cap size, require no-trade or
   reduce-only behavior, alert owners, and may escalate to hard limits when
   repeated or severe.

The independent risk engine remains mandatory between strategy/order-intent
generation and every gateway. Strategy or model code may propose an action, but
it cannot approve its own risk, clear a kill switch, widen limits, or bypass the
risk check.

---

## 3. Scope assumptions

1. Limits are expressed as percentages of the configured paper-account net asset
   value (`paper_nav`) unless a future approved executable config supplies a
   lower instrument/account-specific cap.
2. Until a paper account exists, S6/S9/S10 fixtures should use a clearly labelled
   virtual-equity reference amount for tests. Fixture equity does not represent
   live capital and must not be used to enable live trading.
3. Benchmarks such as buy-and-hold may report 100% notional exposure for
   evaluation purposes, but executable strategies must still pass this risk
   policy before sending order intents to a gateway.
4. Missing risk config, missing instrument metadata, missing fee/cost schedule,
   missing venue status, or unavailable durable kill-switch state is a hard
   fail-closed condition.
5. Numeric thresholds below are conservative initial defaults. Widening a hard
   limit, relaxing a kill trigger, or changing a validation threshold after a run
   starts requires the approval path in Section 7 and a new validation run when
   results would be affected.

---

## 4. Limit severity semantics

| Severity | Meaning | Required response | Gateway eligibility |
|---|---|---|---|
| Informational | Observation does not reduce safety margin. | Log metric/event with trace/run context. | Allowed only if all independent risk checks pass. |
| Soft breach | Safety margin is degraded but not yet a stop condition. | Emit alert, record reason, cap size or require no-trade/reduce-only per policy. | Risk-increasing orders are allowed only after size is capped below hard limits. |
| Hard breach | Configured safety boundary is crossed or required state is missing. | Reject risk-increasing order intent with machine-readable reason; escalate kill state where listed. | Blocked before simulator/paper/future live gateway. |
| Stop-the-line | Risk-engine bypass, kill-switch bypass, forced-breach order reaches a gateway, duplicate exposure, secrets exposure, replay failure, or lookahead leakage. | Pause merge/promotion path; create incident/blocker with owner, rollback, and evidence. | No promotion or paper-readiness claim until resolved. |

Soft-breach responses may reduce risk below the proposed size, but they may not
increase exposure above configured limits or override hard limits. Hard breaches
may allow cancellations or risk-reducing orders only when the active kill state
explicitly permits them and the risk engine records the approval.

---

## 5. Initial hard and soft risk-limit policy

The following IDs are the policy handles future executable config, risk-check
events, dashboards, and forced-breach fixtures should use or map to.

| Limit ID | Scope | Soft limit / warning action | Hard limit / blocking action | Primary owner |
|---|---|---|---|---|
| `scope.product_mvp` | Product/runtime | None; any proposal outside MVP scope is immediately invalid. | Block live-capital, leverage, margin, derivative, short, market-making, HFT, or online self-promotion paths. | Product / risk |
| `config.required_state` | Risk engine | None. | Block when risk config, fee/cost schedule, instrument constraints, venue status, trace ID, or durable kill-switch state is missing/unknown. | Risk / architecture |
| `order.max_notional` | Per order | Proposed order > 1.0% `paper_nav`: cap to soft limit unless risk-reducing. | Proposed order > 2.5% `paper_nav` or lower venue/instrument cap: reject. | Risk / execution |
| `order.price_collar` | Per order | Price > 50 bps from event-time reference mid/last: require limit order or no-trade. | Price > 100 bps from reference, missing reference price, or marketable order during collar breach: reject. | Execution / risk |
| `position.instrument_exposure` | Instrument/account | Resulting instrument exposure > 15% `paper_nav`: cap new size and alert. | Resulting instrument exposure > 25% `paper_nav`: reject risk-increasing order. | Risk |
| `position.strategy_exposure` | Strategy/account | Strategy exposure > 20% `paper_nav`: cap new risk. | Strategy exposure > 30% `paper_nav`: reject risk-increasing order. | Risk / strategy owner |
| `position.total_spot_exposure` | Portfolio/account | Total risky spot exposure > 45% `paper_nav`: cap new exposure and prefer no-trade. | Total risky spot exposure > 60% `paper_nav` or minimum cash reserve < 30%: reject risk-increasing order. | Risk / product |
| `position.no_short_or_oversell` | Instrument/account | None. | Sell/reduce order exceeds settled inventory or creates short exposure: reject. | Risk / execution |
| `loss.daily_account` | Portfolio/account | Daily realized + unrealized loss <= -1.0% `paper_nav`: reduce max new size by at least 50% and alert. | Daily loss <= -2.0% `paper_nav`: set scoped/global kill state to `PAUSE_NEW_ORDERS` or stricter. | Risk |
| `loss.daily_strategy` | Strategy/account | Strategy daily loss <= -0.5% `paper_nav`: reduce strategy size by at least 50%. | Strategy daily loss <= -1.0% `paper_nav`: set strategy scope to `PAUSE_NEW_ORDERS` or stricter. | Risk / strategy owner |
| `loss.max_drawdown` | Portfolio/account | Peak-to-trough drawdown <= -5.0%: move to reduce-only sizing and alert. | Peak-to-trough drawdown <= -8.0%: set global or account kill state to `REDUCE_ONLY` or stricter. | Risk / product |
| `liquidity.participation` | Instrument/venue | Proposed order > 0.5% rolling 24h quote volume or > 5% displayed top-of-book depth where available: cap size. | Proposed order > 1.0% rolling 24h quote volume, > 10% displayed top-of-book depth, or required depth metric unavailable for a depth-dependent strategy: reject. | Execution / risk |
| `liquidity.spread` | Instrument/venue | Current spread > 25 bps or above configured strategy percentile: cap/no-trade and alert. | Current spread > 50 bps, spread unavailable, or spread exceeds cost model envelope: reject. | Execution / risk |
| `market.volatility` | Instrument/strategy | Realized/forecast volatility > 2x configured strategy envelope: cap size by at least 50%. | Volatility > 3x envelope, envelope unavailable, or volatility shock scenario active: reject risk-increasing order or set reduce-only. | Risk / quant |
| `data.freshness` | Instrument/venue/feed | Feed age approaching stale threshold: alert and cap new risk for affected path. | Required feed stale beyond configured threshold; default is > 2 bar intervals for bar-driven decisions or > 60 seconds for live quote/trade-driven paper decisions: block affected instrument/strategy. | Data / risk |
| `venue.status` | Venue/instrument | Venue status degraded or maintenance announced: cap/no-trade for affected venue. | Venue halted, maintenance active, API unavailable for required cancel/status/balance path, or venue status unknown: halt affected venue/instrument scope. | Ops / execution |
| `execution.order_throttle` | Strategy/venue/account | > 5 order intents/minute per strategy-instrument or > 15/minute account-wide: alert and throttle. | > 10 order intents/minute per strategy-instrument, > 30/minute account-wide, or venue/API limit risk: reject new intents and consider scoped pause. | Execution / ops |
| `execution.duplicate_idempotency` | Trace/order intent | Duplicate-like retry detected: hold intent until reconciliation. | Same unresolved idempotency key, same trace/order intent already placed, or state mismatch that could duplicate exposure: reject and escalate to `CANCEL_ONLY`/incident as needed. | Execution / risk |
| `execution.reject_burst` | Venue/account | >= 3 rejects in 5 minutes for same strategy/venue: alert and cap/pause strategy. | >= 5 rejects in 5 minutes or any reject reason implying unknown venue/account state: pause affected scope. | Execution / ops |
| `engine.latency` | Decision/risk/order path | p95 decision-to-risk or risk-to-gateway latency > 50% of strategy horizon/staleness budget: cap/no-trade. | Latency exceeds strategy horizon/staleness budget or timestamps cannot prove event-time validity: block affected decisions. | Ops / risk |
| `model.drift_or_calibration` | Model/strategy | Sustained prediction/calibration drift: disable promotion and cap affected strategy. | Severe model anomaly outside training envelope or uncalibrated outputs used for sizing: no-trade affected strategy until reviewed. | ML / risk |
| `tca.cost_slippage` | Execution/strategy | Realized/predicted cost > 2x assumption over review window: alert and cap strategy. | Realized/predicted cost > 3x assumption, fill quality unknown, or TCA unavailable for required path: pause affected strategy/venue. | Execution / risk |

### 5.1 Required risk-check output

Future S9 risk-check events must record at minimum:

- `trace_id`, `decision_ts`, `risk_check_ts`, `strategy_version`,
  `instrument_id`, `venue_id`, and account/paper context.
- Proposed order effect: action, side, quantity, notional, resulting position,
  cash/equity impact, and whether the action is risk-increasing or
  risk-reducing.
- For every evaluated limit: `limit_id`, current value, soft threshold, hard
  threshold, pass/fail, capped value where applicable, reason code, and owner.
- Active kill-switch scope/state and whether cancellation/reduce-only behavior
  is permitted.
- Final approval decision: approved, approved-after-cap, rejected, no-trade, or
  cancel/reduce-only approved.

---

## 6. Initial kill-switch state model

Kill switches are scoped. The most restrictive active state across matching
scopes wins.

| Scope | Examples | Notes |
|---|---|---|
| Global | Entire paper/runtime system. | Used for systemic incidents, unknown durable state, stop-the-line events, or global risk breach. |
| Account | Paper account or future approved account. | Blocks account-specific risk while allowing unrelated fixtures/jobs to continue if safe. |
| Venue | Coinbase-like spot venue, Kraken-like spot venue. | Used for venue outage, status uncertainty, API incident, or venue-specific liquidity collapse. |
| Instrument | Canonical instrument such as `BTC-USD`. | Used for stale data, halt, spread explosion, or instrument-specific anomaly. |
| Strategy | Strategy version or strategy family. | Used for model/strategy drift, loss, reject burst, or bad sizing behavior. |

| State | Meaning | New risk-increasing orders | Risk-reducing orders | Cancels | Activation source |
|---|---|---:|---:|---:|---|
| `UNKNOWN_FAIL_CLOSED` | Durable state/config cannot be read or has not been initialized. | Block | Block unless an operator-approved recovery record exists | Allow only if state can be audited | Automatic startup/default |
| `CLEAR` | No active kill switch for the scope. | Allow only after all risk checks pass | Allow after risk checks | Allow | Manual initialization or approved clear |
| `SOFT_LIMITED` | Soft limit active; risk budget is degraded. | Cap/no-trade per breached limits | Allow after risk checks | Allow | Automatic or manual |
| `PAUSE_NEW_ORDERS` | New risk is paused for the scope. | Block | Allow after risk checks if explicitly risk-reducing | Allow | Automatic or manual |
| `REDUCE_ONLY` | Exposure may only decrease. | Block | Allow only when resulting exposure decreases and price/liquidity controls pass | Allow | Automatic or manual |
| `CANCEL_ONLY` | Only cancellation/reconciliation is allowed. | Block | Block | Allow | Automatic or manual |
| `HALTED` | Full scoped halt pending owner approval. | Block | Block unless an approved incident plan permits reduce-only/flattening | Allow if safer than leaving opens | Manual or severe automatic |

### 6.1 Startup and persistence rules

1. Startup default is `UNKNOWN_FAIL_CLOSED` until the durable state store is
   reachable and the latest applicable kill-switch records are resolved.
2. A fresh paper environment may move to `CLEAR` only through an audited operator
   initialization record.
3. Kill-switch state, clearances, overrides, risk approvals, orders, and audit
   records must not rely on ephemeral container state. The approved future store
   is PostgreSQL/TimescaleDB through the `core` profile.
4. A service restart must preserve the active kill state. If persistence cannot
   be proven, the system remains `UNKNOWN_FAIL_CLOSED`.
5. Manual overrides and state changes must record actor, role, timestamp, scope,
   prior state, new state, reason, cancel-open-orders choice, and linked incident
   or issue where applicable.

### 6.2 Automated kill-trigger mapping

| Trigger | Default scoped state | Notes |
|---|---|---|
| Hard daily account loss | `PAUSE_NEW_ORDERS` escalating to `REDUCE_ONLY` after risk review. | Blocks new risk and forces review before re-enable. |
| Hard portfolio drawdown | `REDUCE_ONLY` or `HALTED` depending on severity and owner runbook. | Prevents model optimism from overriding capital protection. |
| Venue halted/API unavailable/unknown cancel path | `CANCEL_ONLY` or `HALTED` for venue scope. | Cancellation/reconciliation has priority over new risk. |
| Stale critical feed | `PAUSE_NEW_ORDERS` for affected instrument/strategy. | Fulfills fail-closed data rule. |
| Duplicate/idempotency uncertainty | `CANCEL_ONLY` for affected strategy/venue/account until reconciliation. | Prevents duplicate exposure. |
| Reject burst/order state mismatch | `PAUSE_NEW_ORDERS` or `CANCEL_ONLY` for affected scope. | Requires execution/ops triage. |
| Severe latency or timestamp validity failure | `PAUSE_NEW_ORDERS` for affected path. | Preserves event-time correctness. |
| Severe model/feature/calibration drift | `PAUSE_NEW_ORDERS` or strategy no-trade. | Disables promotion; never auto-updates or auto-promotes. |
| Manual operator emergency stop | Operator-selected `PAUSE_NEW_ORDERS`, `CANCEL_ONLY`, `REDUCE_ONLY`, or `HALTED`. | Must include reason and cancel-open-orders choice. |

---

## 7. Owner approval and change-control path

### 7.1 Approval to establish this baseline

This record becomes the initial approved risk baseline only after Issue #4 / PR
review. Expected reviewers are:

1. Risk owner — approves hard/soft limit philosophy and kill-state mapping.
2. Product owner — confirms MVP scope and no-live-capital boundary.
3. Execution/ops owner — confirms venue, order, cancel, and incident semantics.
4. QA/audit owner — confirms evidence, trace, forced-breach, and persistence
   handoffs are testable.

### 7.2 Limit-change approvals

| Change type | Required approval | Evidence required |
|---|---|---|
| Tighten a limit or activate a kill switch immediately for safety. | Risk or ops owner may act immediately; follow-up issue/incident record required. | Actor, timestamp, reason, affected scope, expected rollback/clear conditions. |
| Widen a soft limit before a validation run starts. | Risk owner plus affected strategy/execution owner. | Rationale, affected requirement IDs, new threshold, test/fixture impact. |
| Widen a hard limit, remove a kill trigger, or weaken fail-closed behavior. | Risk owner, product owner, QA/audit owner, and affected execution/ops owner; ADR or owner-approved issue comment required. | Alternatives considered, validation impact, rollback, forced-breach fixture update, affected FR/NFR/RISK IDs. |
| Change limits after a validation or paper run has started. | Not allowed for the active run unless tightening for safety. | If needed, terminate or mark the run invalid and start a new run with pre-registered thresholds. |
| Clear `HALTED`, `CANCEL_ONLY`, `REDUCE_ONLY`, or global/account `PAUSE_NEW_ORDERS`. | At least risk owner plus ops/execution owner; product/QA review for global or repeated incidents. | Root cause, open-order reconciliation, data/venue health, no unresolved stop-the-line trigger, audit record. |

No approval path may authorize live capital, leverage, derivatives, margin,
shorting, online self-promotion, risk-engine bypass, or kill-switch bypass inside
the MVP scope.

---

## 8. Implementation handoff

| Future work | Handoff from this decision |
|---|---|
| S1 instrument master | Include constraints needed by risk checks: tick/lot/min-notional, fees, sessions, venue status, permissions, and any lower instrument-specific caps. |
| S3 stream/data health | Emit feed freshness, gap, duplicate, timestamp-drift, and venue-status signals that can drive `data.freshness` and `venue.status` blocks. |
| S6 simulator/scenario suite | Exercise crash/drawdown, liquidity freeze, spread explosion, stale data, venue outage, duplicate retry, and kill-switch restart scenarios. |
| S8 strategy/no-trade | Strategy decisions must include expected cost, net edge, uncertainty, proposed size, and no-trade/rejection reason so risk can cap or reject deterministically. |
| S9 risk engine | Implement independent risk-check contract using Section 5 limit IDs, hard/soft semantics, forced-breach matrix, durable kill-switch state, and restart persistence test. |
| S10 paper trading | Use the same risk engine between strategy decisions and paper gateway; expose dashboards/alerts for active limits, rejects, kill state, and incident status. |
| S11 audit replay | Include risk-check values, thresholds, kill state, approvals, overrides, and order intent in trace replay. |
| S12 paper validation | Pre-register final numeric risk thresholds, config hash, kill-state defaults, benchmark/cost assumptions, and paper duration/trade-count criteria before the run starts. |

---

## 9. Anti-drift checkpoints

- MVP remains validated paper trading plus promotion recommendation only; no live
  capital path is introduced by this decision.
- MVP remains liquid spot-instrument focused; leverage, margin, derivatives,
  shorting, market making, and HFT remain excluded.
- Risk engine independence remains mandatory before any simulator, paper, or
  future live gateway receives an order intent.
- Kill-switch state and risk approvals must be durable and auditable, not
  ephemeral container memory.
- No-trade/cash preservation remains a first-class decision when risk/cost/edge
  thresholds are not met.
- Missing config, missing metadata, stale feeds, unknown venue status, duplicate
  order uncertainty, or active kill switch fails closed.
- Validation risk limits, benchmark assumptions, and cost assumptions cannot be
  weakened or moved after a validation run starts.
- Any forced-breach order reaching a gateway, kill-switch bypass, duplicate order
  exposure, replay failure, lookahead leakage, secrets exposure, or unapproved
  live-capital path is a stop-the-line blocker.

---

## 10. Acceptance evidence checklist

- [x] Decision record exists for Issue #4 / S0-003.
- [x] Catalog trace includes `FR-010` and `FR-011` from
  `docs/02_requirements_catalog.csv`.
- [x] Supporting risk trace includes `RISK-001` and `RISK-002` from
  `docs/04_risk_register.csv`.
- [x] Hard and soft risk limits are documented with owners, default actions, and
  future policy handles.
- [x] Initial kill-switch scopes and states are documented, including
  fail-closed startup behavior and durable persistence expectations.
- [x] Owner approval path covers baseline approval, limit changes, kill-switch
  activation, and kill-switch clearance.
- [x] Docker/runtime impact is explicitly recorded as governance-only with no
  runtime service or Compose file changed by this issue.
- [x] Future handoffs identify S9 forced-breach, kill-switch persistence,
  stale-feed fail-closed, idempotency, and trace/replay evidence requirements.
- [x] Anti-drift controls preserve no live capital, no leverage/derivatives, no
  risk-engine bypass, no kill-switch bypass, no ephemeral risk state, and no
  validation-threshold weakening.
