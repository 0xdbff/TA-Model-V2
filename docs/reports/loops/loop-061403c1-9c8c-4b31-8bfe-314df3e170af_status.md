# Master Loop Status — S5 Baselines and Evaluation

**Loop UUID:** `061403c1-9c8c-4b31-8bfe-314df3e170af`  
**Loop branch:** `agent/loop-061403c1-9c8c-4b31-8bfe-314df3e170af`  
**Loop worktree:** `/Users/db/dev/TA-Model-v2/TA-Model-V2-loop-061403c1-9c8c-4b31-8bfe-314df3e170af`  
**Base:** latest `origin/dev` at `b89ff36`  
**Final PR base:** `dev`  
**Final PR source:** `agent/loop-061403c1-9c8c-4b31-8bfe-314df3e170af`  
**Final PR:** Not opened yet.

## Scope and sprint objective

Sprint IDs in scope: `S5-*`  
GitHub issues in scope: `#23`-`#26`

Sprint objective: implement deterministic baseline strategies and an evaluation
scorecard before complex model work. The integrated S5 increment must compare
cash/no-trade, buy-and-hold, basket allocation, TA heuristic, and simple ML
baselines across configured chronological windows using net-of-cost,
risk-adjusted, and benchmark-relative metrics, then produce a baseline gate
decision with blockers called out explicitly.

## Binding controls

- `docs/rules/00_delivery_anti_drift_rules.md`
- `docs/02_requirements_catalog.csv` (`FR-007`, `FR-014`, `NFR-001`, `NFR-005`)
- `docs/10_implementation_roadmap.md` Sprint 5
- `docs/11_tech_stack_and_docker.md`
- `docs/13_github_issue_backlog.md` S5 entries

Hard guardrails: MVP paper-trading validation only; spot/liquid instruments only;
no live capital, leverage, derivatives, margin, shorting, autonomous promotion,
unapproved runtime/datastore/broker additions, risk/kill-switch bypass, lookahead
leakage, or use of `ingest_ts` as market availability time. Gross PnL alone is
not sufficient evidence; no-trade/cash must be a first-class logged baseline.

## Issue status

| Issue | Sprint | Status at loop start | Evidence / notes |
|---|---|---:|---|
| #23 | S5-001 | PR #85 merged to loop | Cash/no-trade, buy-and-hold, and equal-weight basket baselines added with split-local turnover reset semantics, deterministic lineage, proxy-cost assumptions, and concrete per-window report evidence. |
| #24 | S5-002 | PR #86 merged to loop | TA heuristic and pure-Python simple ML baselines added through shared baseline contracts with no-trade rows, train-only ML fitting, proxy-cost assumptions, and comparator report evidence. |
| #25 | S5-003 | PR #87 merged to loop | Evaluation scorecard added with net return, Sharpe, Sortino, Calmar, max drawdown, CVaR, turnover, exposure, costs, benchmark-relative metrics, explicit undefined states, and benchmark hash lineage. |
| #26 | S5-004 | PR pending | Baseline gate decision added with PASS result, caveats, and blocker tests for missing baseline/evidence/benchmark-relative metrics. |

## Dependencies and sequencing

1. `#23` / `S5-001` establishes deterministic baseline output contracts and
   first baseline reports; it should land before or alongside the first scorecard
   adapter.
2. `#24` / `S5-002` can proceed in parallel after confirming the shared
   dataset/baseline-output interface; ML training must not use validation/test
   rows as training input.
3. `#25` / `S5-003` depends on stable baseline output schema from `#23` and
   `#24`; it must handle missing or not-applicable metrics explicitly.
4. `#26` / `S5-004` is last and must aggregate validated evidence from `#23`,
   `#24`, and `#25` into the baseline gate report.

## Sub-agent assignments

| Issue | Sprint | Branch | Worktree | Agent | PR | Status |
|---|---|---|---|---|---|---|
| #23 | S5-001 | `agent/23-S5-001` | `/Users/db/dev/TA-Model-v2/TA-Model-V2-23-S5-001-061403c1-9c8c-4b31-8bfe-314df3e170af` | backend-impl | [#85](https://github.com/0xdbff/TA-Model-V2/pull/85) merged | Completed after QA-requested split/window reset, chronological fail-closed validation, and concrete report-table evidence fixes. |
| #24 | S5-002 | `agent/24-S5-002` | `/Users/db/dev/TA-Model-v2/TA-Model-V2-24-S5-002-061403c1-9c8c-4b31-8bfe-314df3e170af` | backend-impl | [#86](https://github.com/0xdbff/TA-Model-V2/pull/86) merged | Completed after QA-requested documentation caveats for S5-wide baseline contracts and in-sample train metrics. |
| #25 | S5-003 | `agent/25-S5-003` | `/Users/db/dev/TA-Model-v2/TA-Model-V2-25-S5-003-061403c1-9c8c-4b31-8bfe-314df3e170af` | backend-impl | [#87](https://github.com/0xdbff/TA-Model-V2/pull/87) merged | Completed after QA-requested benchmark report hash lineage fix and evidence count correction. |
| #26 | S5-004 | `agent/26-S5-004` | `/Users/db/dev/TA-Model-v2/TA-Model-V2-26-S5-004-061403c1-9c8c-4b31-8bfe-314df3e170af` | backend-impl | Not opened | Implemented locally; gate report decision is PASS with S5 proxy-cost and simple-ML caveats. |

## Validation plan

Required per implementation PR unless a narrower first pass is explicitly noted:

```text
uv run ruff check .
uv run mypy src tests
uv run pytest
```

Additional focused checks expected:

- #23: baseline strategy contract tests and deterministic fixture report.
- #24: TA heuristic/ML baseline tests, split/leakage tests, deterministic seed tests.
- #25: metric formula tests including flat/no-trade, loss-only, empty/undefined,
  cost, turnover, exposure, and benchmark-relative cases.
- #26: gate-report tests that fail when required S5 evidence is missing or blocker
  conditions are present.
- Integrated loop: full lint/type/test suite; review `docs/reports/gates/S5-*`;
  confirm Docker/profile impact is either `dev`/`research` only or explicitly
  `no runtime service impact`.

## QA findings and integration risks

- #23 initial review found blocking split/window semantics: buy-and-hold and equal-weight
  position state carried across train/validation/test windows, understating entry
  turnover/cost. Fixed before merge by resetting state per `(split, instrument)`,
  adding chronological fail-closed validation, regression tests, and a concrete
  per-window report table.
- #24 review approved TA/ML behavior and requested documentation polish before
  merge: baseline contracts now say S5-wide fixture/local scope and the S5-002
  report explicitly calls out simple-ML train metrics as in-sample while
  validation/test decisions remain out-of-sample with respect to label usage.
- #25 initial review found a blocking reproducibility gap: benchmark-relative
  metrics used `benchmark_report` rows but did not record benchmark report hash
  when the benchmark was not in scored `reports`. Fixed before merge by adding
  `BenchmarkConfig.benchmark_report_hash`, regression coverage, and report evidence.
- Baselines must consume S4 dataset/feature contracts where feasible; fixture/local
  deterministic data is acceptable only at appropriate test/report boundaries.
- S5 cost modeling is pre-S6; conservative/proxy costs must be documented and not
  misrepresented as execution-grade slippage/TCA evidence.
- Volatility-target and ML baselines are leakage-sensitive: volatility estimates,
  training windows, normalization, and thresholds must use only event-time-available
  data.
- Undefined metrics such as Sortino/CVaR on flat or tiny windows must be represented
  with explicit not-applicable/blocker reasons, not silently coerced into success.
- Any gross-only report, omitted cash/no-trade baseline, missing benchmark-relative
  comparison, or future-label usage is a stop-the-line QA blocker.

## Integrated validation log

- Loop worktree created from `origin/dev` at `b89ff36`.
- Initial planning/exploration completed before sub-agent assignments.
- #23 PR #85 pre-merge validation in sub-agent worktree: `uv run ruff check .`
  passed; `uv run mypy src tests` passed; `uv run pytest` passed with 137 tests.
- Loop validation after #23 merge: `uv run ruff check .` passed; `uv run mypy src tests`
  passed; `uv run pytest` passed with 137 tests.
- #24 PR #86 pre-merge validation in sub-agent worktree: `uv run ruff check .`
  passed; `uv run mypy src tests` passed; `uv run pytest` passed with 140 tests.
- Loop validation after #24 merge: `uv run ruff check .` passed; `uv run mypy src tests`
  passed; `uv run pytest` passed with 140 tests.
- #25 PR #87 pre-merge validation in sub-agent worktree: `uv run ruff check .`
  passed; `uv run mypy src tests` passed; `uv run pytest` passed with 148 tests.
- Loop validation after #25 merge: `uv run ruff check .` passed; `uv run mypy src tests`
  passed; `uv run pytest` passed with 148 tests.
- #26 pre-PR validation in sub-agent worktree: `uv run ruff check .` passed;
  `uv run mypy src tests` passed; `uv run pytest` passed with 153 tests.

## Human-sync decisions

None yet.

## Remaining blockers

- Sub-agent work for #26 is implemented but not merged yet.
- Final integration PR is not ready until all S5 evidence is implemented,
  reviewed, merged to the loop branch, and validated as an integrated whole.
