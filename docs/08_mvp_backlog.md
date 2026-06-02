# MVP Backlog and Delivery Plan

## MVP north star

Deliver a paper-trading, validation-first system for a constrained universe of liquid spot instruments. The MVP must answer: “Does the complete decision system improve net, risk-adjusted, benchmark-aware portfolio outcomes after costs without violating capital-protection constraints?”

## P0 backlog

| Epic | Story/Task | Acceptance criteria |
|---|---|---|
| Product framing | Define objective function and benchmarks. | Written scorecard includes cash, buy-and-hold, equal-weight/vol-target baseline, and market benchmark. |
| Risk framing | Define hard/soft limits. | Limits stored in config and enforced by risk engine tests. |
| Data sourcing | Approve initial data sources. | Source register includes license, API, retention, and production-use status. |
| Instrument master | Build canonical asset/instrument model. | Selected instruments map across venue symbols with tick/lot/min-notional and fee metadata. |
| Historical ingestion | Backfill OHLCTV and trades. | Completeness and gap report pass configured thresholds. |
| Streaming ingestion | Build live feed with heartbeats. | Stale/gap alerts tested. |
| Feature engine | Implement TA and basic liquidity features. | Features pass point-in-time and batch-vs-stream tests. |
| Dataset builder | Create chronological train/validation/test snapshots. | Dataset hash, split, label, and feature version stored. |
| Baselines | Implement cash, buy-and-hold, TA heuristic, and simple ML. | Baseline report generated for all evaluation windows. |
| Simulator | Build historical replay engine. | Costs, slippage, partial fills, latency, and venue constraints are modeled. |
| Model | Train first sequence/transformer candidate. | Candidate emits calibrated probabilities/quantiles and uncertainty. |
| Strategy layer | Implement trade/no-trade and sizing. | Decision object complete for taken and skipped trades. |
| Risk engine | Implement pre-trade controls and kill switch. | 100% forced-breach tests block orders. |
| Paper trading | Run live-paper gateway. | Paper portfolio, orders, fills, TCA, and drift metrics logged. |
| Observability | Build dashboards and alerts. | Data/model/strategy/portfolio/engine dashboards available. |
| Audit | Build trace replay. | 100 sampled decisions replay end-to-end. |

## Phase gates

| Gate | Exit criteria |
|---|---|
| Build readiness | Objective, universe, data sources, and risk limits approved. |
| Data readiness | Historical and streaming data pass quality gates. |
| Research readiness | Baselines and simulator produce reproducible reports. |
| Model readiness | Candidate model beats or explains failure versus baselines; no leakage. |
| Paper readiness | Strategy/risk/execution pipeline runs on live data with no capital. |
| Live readiness | Paper gate, TCA gate, kill-switch gate, compliance gate, and approval pass. |

## What not to build in MVP

- No leverage, derivatives, margin, shorting, or market-making obligations.
- No unsupervised live model updates.
- No HFT/colocation/latency-arbitrage scope.
- No client-facing investment advice.
- No alternative data until baseline pipeline is validated.
