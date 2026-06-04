# Master Loop Status — S6 Simulator and Costs

**Loop UUID:** `ae237f94-fbcf-4914-8b77-1a36d323f7cd`  
**Loop branch:** `agent/loop-ae237f94-fbcf-4914-8b77-1a36d323f7cd`  
**Loop worktree:** `/Users/db/dev/TA-Model-v2/TA-Model-V2-loop-ae237f94-fbcf-4914-8b77-1a36d323f7cd`  
**Base:** latest `origin/dev` at `f6c3497`  
**Final PR base:** `dev`  
**Final PR source:** `agent/loop-ae237f94-fbcf-4914-8b77-1a36d323f7cd`  
**Final PR:** pending

## Scope and sprint objective

Sprint IDs in scope: `S6-*`  
GitHub issues in scope: `#27`-`#30`

Sprint objective: build a historical simulator increment that replays market data in event time, prevents same-bar/lookahead fills, applies realistic execution costs and fill outcomes, enforces instrument/venue/cash/inventory constraints, and produces deterministic scenario evidence for the simulation gate.

## Binding controls

- `docs/rules/00_delivery_anti_drift_rules.md`
- `docs/02_requirements_catalog.csv` (`FR-003`, `FR-010`, `FR-012`, `NFR-001`)
- `docs/04_risk_register.csv` (`RISK-001`, `RISK-002`, `RISK-005` where applicable)
- `docs/07_data_contracts.md` event-time market data and fee-schedule rules
- `docs/10_implementation_roadmap.md` Sprint 6
- `docs/11_tech_stack_and_docker.md`
- `docs/12_sprint_execution_playbook.md` simulation gate evidence packet
- `docs/13_github_issue_backlog.md` S6 entries

Hard guardrails: MVP paper-trading validation only; spot/liquid instruments only; no live capital, leverage, derivatives, margin, shorting, market making, HFT, autonomous model promotion, unapproved runtime/datastore/broker additions, risk/kill-switch bypass, lookahead leakage, or use of `ingest_ts` as market availability time. Same gateway/order lifecycle contract must be reusable for simulation and future paper paths. No-trade/cash preservation remains first-class evidence.

## Issue status

| Issue | Sprint | Status at loop start | Evidence / notes |
|---|---|---:|---|
| #27 | S6-001 | Open, planned first | Must establish event-time replay/gateway foundation and same-bar leakage prevention evidence. |
| #28 | S6-002 | Open, blocked on #27 contracts | Must add fees, spread, slippage, latency, partial/failed fills, cost attribution, and stress-cost report. |
| #29 | S6-003 | Open, blocked on #27 contracts | Must enforce venue constraints plus cash/inventory accounting with rejection evidence. |
| #30 | S6-004 | Open, depends on #27 and integrates #28/#29 evidence | Must add deterministic synthetic scenarios covering random-walk, trend, crash, spread, liquidity, and outage cases. |

## Dependencies and sequencing

1. `#27` / `S6-001` is foundational: define/update simulator contracts and event-time replay behavior before broad cost/constraint/scenario work.
2. `#28` / `S6-002` and `#29` / `S6-003` should branch from the loop after #27 lands to avoid divergent order lifecycle or fill models.
3. `#30` / `S6-004` can start with scenario planning but implementation should validate against the integrated simulator after #28/#29 behavior is available.
4. Final loop validation must exercise the lowest-risk end-to-end path: historical replay fixture -> simulator gateway -> cost/slippage/rejection report.

## Sub-agent assignments

| Issue | Sprint | Branch | Worktree | Agent | PR | Status |
|---|---|---|---|---|---|---|
| #27 | S6-001 | `agent/27-S6-001` | `/Users/db/dev/TA-Model-v2/TA-Model-V2-27-S6-001-ae237f94-fbcf-4914-8b77-1a36d323f7cd` | backend-impl | pending | Planned first; worktree pending. |
| #28 | S6-002 | `agent/28-S6-002` | `/Users/db/dev/TA-Model-v2/TA-Model-V2-28-S6-002-ae237f94-fbcf-4914-8b77-1a36d323f7cd` | backend-impl | pending | Pending #27 merge. |
| #29 | S6-003 | `agent/29-S6-003` | `/Users/db/dev/TA-Model-v2/TA-Model-V2-29-S6-003-ae237f94-fbcf-4914-8b77-1a36d323f7cd` | backend-impl | pending | Pending #27 merge. |
| #30 | S6-004 | `agent/30-S6-004` | `/Users/db/dev/TA-Model-v2/TA-Model-V2-30-S6-004-ae237f94-fbcf-4914-8b77-1a36d323f7cd` | backend-impl / QA | pending | Pending simulator behavior; scenario contract planning allowed. |

## Validation plan

Required per implementation PR unless a narrower first pass is explicitly justified:

```text
uv run ruff check .
uv run mypy src tests
uv run pytest
```

Additional focused checks expected:

- #27: event-time ordering, deterministic replay, same-bar leakage prevention, missing/unsorted timestamp fail-closed tests, report artifact for replay fixture.
- #28: fee/spread/slippage/latency/partial-fill/failed-fill tests; net-vs-gross cost attribution; stress-cost report evidence.
- #29: tick/lot/min-notional/fee schedule/venue status tests; cash and spot inventory no-shorting enforcement; rejection accounting evidence.
- #30: deterministic scenario suite for random-walk, trend, crash, spread widening, liquidity reduction, and outage/stale/missing data; seeded reproducibility tests and scenario report.
- Integrated loop: full lint/type/test suite; review `docs/reports/gates/S6-*`; confirm Docker/profile impact is either documented as no runtime service impact or matches approved profiles.

## QA findings and integration risks

- Event-time replay is a stop-the-line area: any use of future bar close/current bar high-low for same-bar fills, or `ingest_ts` as availability time, blocks merge.
- Simulator must not become a paper-only or research-only divergent path. Contracts must preserve the future shared gateway/order lifecycle direction.
- Mocks are acceptable for deterministic fixtures only; they cannot replace production-path service wiring or hide missing simulator integration.
- S6 is pre-risk-engine implementation, but work must not bypass or weaken future independent risk controls. Forced breach orders reaching a gateway remain stop-the-line by rule.
- Unknown venue status, missing fee schedule, impossible cash/inventory, stale/outage data, or invalid instrument constraints should fail closed with explicit rejection/blocker evidence.
- Gross-only PnL or cost-free success evidence is insufficient for FR-012.

## Integrated validation log

- Loop worktree created from `origin/dev` at `f6c3497`.
- Initial S6 issue inventory reviewed: open issues #27-#30 under milestone `S6 Simulator and costs`.

## Human-sync decisions

None yet.

## Remaining blockers

- #27 implementation not yet assigned.
- #28, #29, and #30 should not implement divergent simulator contracts before #27 lands.
- Final integration PR is not ready.
