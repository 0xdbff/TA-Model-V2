# S4-002 Liquidity/Cost Feature Gate Report

Date: 2026-06-03

## Traceability

- Primary: FR-005 — spread, volume, volatility, and fee features available at decision time.
- Supporting: FR-003 fee metadata, FR-004 existing feature-vector contract, NFR-001 leakage prevention, NFR-005 deterministic reproducibility.

## Implementation evidence

- Added fixture-only `QuoteFeatureInput` with deterministic ID derived from event-time quote fields, excluding `ingest_ts`.
- Added pure-Python `liquidity_cost` feature builder producing `FeatureVector`s with spread, half-spread, mid-price, bid/ask size, top-of-book base/quote liquidity, volume, trade count, realized volatility, maker/taker fee, taker-fee bps, one-way/round-trip taker cost bps, and minimum-fee features.
- Feature builder uses close-time bars only when `source_ts <= close_ts`, latest quote with `event_ts <= feature_ts` and `source_ts <= feature_ts` when present, and fee schedule active under `effective_from <= feature_ts < effective_to`.
- Missing quote/fee coverage, crossed/locked quotes, duplicate/non-monotonic quote event times, source-time unavailable quotes, late-source bars, and duplicate/non-monotonic bar close times fail closed.

## Validation command

```text
uv run ruff check . && uv run mypy src tests && uv run pytest
```

Result:

```text
All checks passed!
Success: no issues found in 30 source files
110 passed in 0.56s
```

## Runtime / Docker impact

- No runtime service, Docker profile, datastore, broker, dependency, or network/API market-data change.
- Fixture/synthetic test inputs only.

## Anti-drift notes

- Preserves event-time correctness; `ingest_ts` perturbation tests confirm IDs/values do not change.
- No quote/order-book ingestion, S4-003 dataset builder, model/strategy/risk/kill-switch, paper/live route, leverage, margin, derivative, or live-capital scope added.

## Gate decision

- Pass for S4-002 acceptance evidence: FR-005 feature contract tests with decision-time availability passed.
