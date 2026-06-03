# S4-004 Leakage and Parity Gate Report

Issue: #22  
Sprint: S4-004  
Requirements: FR-004, FR-006, NFR-001; preserves FR-005, NFR-005

## Scope delivered

- Added an integrated fixture/local leakage and batch-vs-incremental parity suite in `tests/test_s4_leakage_parity.py`.
- Exercised the lowest-risk S4 path: fixture spot OHLCTV/quotes/fees -> TA features -> liquidity/cost features -> merged point-in-time feature vectors -> chronological dataset rows/labels.
- Kept scope to deterministic local QA evidence only. No source/API/network data, Docker/runtime services, new dependencies, storage adapters, strategy, risk/order path, paper/live routing, leverage, derivatives, margin, or live capital.

## Acceptance evidence

- TA batch computation matches stream-style incremental computation at each newly available bar timestamp.
- Liquidity/cost batch computation matches stream-style incremental computation using quotes/fees available by decision time.
- Integrated chronological dataset rows match incremental snapshots for rows whose configured future label horizon is available.
- Future bar mutations do not change prior TA vectors or integrated dataset rows; only the mutated bar row changes.
- Future quote mutations outside decision-time availability do not change prior liquidity/cost vectors or dataset rows.
- Future label mutations change only rows whose configured label horizon uses the mutated observation.
- Higher-timeframe TA close remains unavailable before the higher-timeframe bar close and becomes available only at/after close.
- Split assignment is by `feature_ts`; a train row with `label_ts` on the validation boundary remains train.
- Unsafe fixtures fail closed for label-as-feature leakage, late/unavailable quote source data, late OHLCTV source data in both TA and liquidity/cost features, non-monotonic TA inputs, and missing configured label horizon.

## Validation commands

Executed locally in this PR branch:

1. `uv run ruff check .` — passed (`All checks passed!`)
2. `uv run mypy src tests` — passed (`Success: no issues found in 35 source files`)
3. `uv run pytest` — passed (`128 passed in 0.64s`)

## Docker/runtime impact

No Docker, Compose, runtime service, database, broker, object storage, external API, or dependency changes.

## Anti-drift checks

- Event-time correctness: feature generation uses bar close/event/source/effective timestamps, not `ingest_ts`; dataset split assignment uses `feature_ts`, not `label_ts`.
- Lookahead prevention: future bars, future quotes, and future labels cannot alter prior vectors/rows except rows whose configured label horizon consumes the mutated label observation.
- Higher-timeframe leakage prevention: higher-timeframe values remain unavailable until the higher-timeframe close.
- Fail-closed behavior: intentionally unsafe leakage fixtures raise domain errors instead of producing vectors/rows.
- Reproducibility: deterministic IDs/hashes are preserved across batch and incremental fixture paths.
- MVP scope preserved: fixture spot data only; no leverage, derivatives, margin, shorting, strategy/risk/order/paper/live scope, or live capital.

## Gate decision

Pass for S4-004 local QA evidence: zero known leakage observed across TA features, liquidity/cost features, and chronological dataset snapshots under the committed test fixtures and validation commands above.

## Risks / follow-ups

No known S4-004 acceptance blockers. Future production/storage integrations should keep this suite as the leakage parity regression gate and add connector-specific fixtures without weakening these checks.
