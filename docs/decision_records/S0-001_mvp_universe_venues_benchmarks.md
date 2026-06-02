# S0-001 Decision Record — MVP Universe, Venue/Source Candidates, and Benchmark Policy

| Field | Value |
|---|---|
| Status | Pending approval; becomes the approved S0 build-readiness baseline once merged via GitHub Issue #2 / PR review. |
| Sprint / gate | S0 Build readiness / `gate:build` |
| Issue | #2 — S0-001: Lock MVP universe, venue/source candidates, and benchmark policy |
| Decision owners | Product, risk, quant, data/legal |
| Runtime / Docker impact | No runtime service is changed; no Docker Compose profile is affected |
| Scope boundary | Governance decision record only; no connector, credential, data pull, paper order path, or runtime service is introduced |

---

## 1. Requirement and risk trace

### Primary issue trace

- `PG-001` — preserve and grow portfolio value on a risk-adjusted basis.
- `PG-002` — treat no-trade as a first-class decision.
- `PG-003` — prevent unsafe automation.
- `PG-004` — support asset-agnostic research and execution.
- `PG-005` — provide reproducible evaluation.
- `RISK-015` — benchmark misselection.

### Catalog trace used for implementation/PR hygiene

- `FR-003` — normalize symbols, assets, venues, tick size, lot size, min notional, and fees.
- `FR-007` — train and report baselines before transformer candidates.
- `FR-009` — support trade/no-trade decisions with expected return, expected cost, net edge, uncertainty, and reason code.
- `FR-014` — evaluate model, strategy, portfolio, and engine separately with benchmark-relative net metrics.
- `FR-015` — reconstruct decisions from trace ID using immutable data, feature, model, config, and code versions.
- `NFR-001` — prevent lookahead leakage in features, labels, and benchmark construction.
- `NFR-004` — preserve auditability of live decisions and overrides when later runtime paths exist.
- `NFR-005` — preserve reproducibility from run ID, config, code, data snapshot, and benchmark assumptions.

---

## 2. Decision summary

For the MVP delivery path, the project will start with a **constrained, liquid,
spot-only crypto universe** and paper-trading validation only. The runtime MVP
will not include leverage, margin, derivatives, shorting, market making, HFT,
live capital, or autonomous online model promotion.

The initial build assumes a single primary spot venue/source candidate and a
single secondary venue/source candidate for redundancy and future adapter
comparison. Data use remains blocked until the source/license register created
by S0-004 marks the source, license, retention, and production/paper-use status
as approved.

Every validation report must compare candidate strategies against a fixed
benchmark set that includes cash/no-trade, per-instrument buy-and-hold,
equal-weight basket, volatility-targeted basket, and a market-beta benchmark.
Later strategy/model baselines must be added when S5 work exists. A candidate
cannot pass by beating only a weak or cherry-picked baseline.

---

## 3. Locked MVP universe assumptions

### 3.1 Primary tradable seed universe

| Canonical asset | MVP instrument assumption | Quote / settlement | Inclusion rationale | MVP status |
|---|---|---|---|---|
| Bitcoin | `BTC-USD` or venue-equivalent spot pair | USD or approved USD stable quote | Highest-liquidity crypto market-beta asset; useful market benchmark anchor. | Primary |
| Ether | `ETH-USD` or venue-equivalent spot pair | USD or approved USD stable quote | Deep liquidity and distinct risk profile from BTC while remaining liquid. | Primary |
| Solana | `SOL-USD` or venue-equivalent spot pair | USD or approved USD stable quote | Liquid large-cap crypto with higher volatility/regime sensitivity for validation. | Primary |

### 3.2 Inclusion criteria

An instrument may enter the MVP paper universe only when all of the following
are true:

1. Spot instrument only; no margin, leverage, perpetuals, futures, options,
   funding, borrow, or short exposure.
2. Sufficient historical OHLCTV/trade data exists for configured walk-forward
   windows or the missing history is flagged as a blocker.
3. Streaming trades and at least top-of-book or quote data are available where
   the selected venue supports them.
4. Venue metadata can provide or derive tick size, lot size, min notional,
   trading status, fee schedule, and supported order types.
5. Liquidity, spread, volatility, and venue-status checks can fail closed for
   the affected instrument.
6. Source/license review permits the intended storage, retention, backtesting,
   paper use, and reporting.

### 3.3 Explicit exclusions for MVP

- Live capital and production order routing.
- Leverage, margin, shorting, derivatives, borrow/funding-aware instruments,
  options, futures, and perpetual swaps.
- Market-making obligations, two-sided quoting, HFT, latency arbitrage, or
  colocation-sensitive strategies.
- Alternative data, news, fundamentals, on-chain analytics, macro calendars, or
  sentiment feeds until the core baseline pipeline is validated and the source
  gate approves them.
- New venues, brokers, databases, model registries, event buses, or language
  runtimes outside the approved stack without ADR approval.

### 3.4 Asset-agnostic guardrail

The initial runtime universe is deliberately narrow, but schemas and contracts
must stay asset-agnostic. Crypto-specific values must not be hard-coded into
core strategy, model, dataset, risk, or gateway abstractions. Later S1/S2 work
may use fixture assets from other classes to verify the common instrument schema,
but the MVP paper path remains liquid spot instruments only until a separate
approved decision expands it.

---

## 4. Venue and source candidates

| Role | Candidate | Intended use | Approval state | Notes |
|---|---|---|---|---|
| Primary venue/source candidate | Coinbase spot market-data APIs / WebSocket, using venue-native identifiers mapped through `FR-003` instrument master | Historical bars/trades, streaming market data, venue metadata, paper-mode reference venue | Candidate only until S0-004 source/license register approves use | Prefer official venue data over scraped or unofficial datasets. No keys or credentials are committed. |
| Secondary venue/source candidate | Kraken spot market-data APIs / WebSocket, using venue-native identifiers mapped through `FR-003` instrument master | Redundancy, cross-venue sanity checks, future adapter comparison | Candidate only until S0-004 source/license register approves use | Secondary candidate must not expand MVP into multi-venue execution unless separately approved. |
| Deferred / blocked | Global derivatives venues, margin/leveraged products, DEX-only sources, unofficial scraped datasets, unapproved aggregators | Not used in MVP runtime | Blocked | May be explored only under source/license and scope controls; not a delivery dependency for S0-001. |

Source candidates are not source approvals. Before ingestion or paper validation,
S0-004 must record license terms, retention rights, rate limits, allowed storage,
production/paper-use status, source owner, and any jurisdiction or API-account
constraints.

---

## 5. Benchmark policy

### 5.1 Required benchmark set

Every simulation, walk-forward, paper, model, strategy, or portfolio report that
claims improvement must include these benchmark families on the same instruments,
dates, fees/cost assumptions, and event-time availability rules:

| Benchmark | Required for | Policy |
|---|---|---|
| Cash / no-trade baseline | All strategy and portfolio evaluations | Represents capital preservation and opportunity cost. Cash return must be declared; if no approved risk-free proxy exists, use zero nominal cash return and state the assumption. |
| Per-instrument buy-and-hold | Per-instrument strategy evaluations | One buy at the evaluation-window start and one liquidation or mark-to-market at the end; report net of entry/exit fees and configured spread/slippage assumptions. |
| Equal-weight MVP basket | Portfolio evaluations | Equal weights across approved MVP instruments; rebalance cadence, fees, spreads, and any residual cash must be declared before the run. |
| Volatility-targeted basket | Portfolio and risk evaluations | Uses only historical/event-time volatility estimates; no leverage; target exposure is capped at 100% with residual in cash. |
| Market-beta benchmark | Portfolio and benchmark-relative preservation metrics | For the crypto MVP, BTC spot buy-and-hold is the default market-beta anchor. If BTC is the traded instrument under test, also report against the equal-weight basket to avoid self-benchmark bias. |
| TA heuristic and simple ML baselines | S5 and later model/strategy gates | Required once baseline implementations exist; candidates cannot be promoted without comparing against them or documenting owner-approved risk-control value. |

### 5.2 Benchmark construction rules

1. Benchmark data must come from approved sources with the same source/version
   controls as strategy data where practical.
2. Benchmark returns must be point-in-time and event-time correct. No benchmark
   feature, volatility estimate, rebalance signal, or label may use future data.
3. Gross PnL is not a success metric. Reports must include net-of-cost and
   benchmark-relative metrics.
4. Benchmark definitions, rebalance cadence, cash proxy, cost assumptions,
   evaluation windows, risk thresholds, and source versions must be
   pre-registered before each validation run starts.
5. A validation run cannot change benchmarks, windows, costs, or thresholds
   after results are known. Any change requires a new decision/issue comment
   with rationale, risk, rollback, owner approval, and affected requirement IDs.
6. If a benchmark cannot be computed because data is missing or source/license
   approval is absent, the affected validation gate is blocked or explicitly
   conditional; it cannot be silently skipped.
7. Reports must include at minimum: net return, Sharpe, Sortino, Calmar, max
   drawdown, CVaR where available, turnover, exposure, cost drag, and
   benchmark-relative preservation.

---

## 6. Validation and integration handoff

| Future work | Handoff from this decision |
|---|---|
| S0-004 source/license register | Must approve Coinbase/Kraken source terms before ingestion or paper use. |
| S1 instrument master | Seed `BTC`, `ETH`, and `SOL` canonical assets and venue mappings only after source/metadata assumptions are approved. |
| S2/S3 ingestion | Use source-approved venue APIs; persist provenance, source timestamps, and immutable raw payload IDs. |
| S5 baseline/evaluation | Implement cash, buy-and-hold, equal-weight/vol-target, market-beta, TA heuristic, and simple ML comparisons according to this policy. |
| S8 strategy/no-trade | Decision objects must include benchmark/cash alternatives and no-trade reason codes. |
| S9 risk | Risk controls remain mandatory between strategy decisions and any simulator/paper gateway. |
| S12 paper validation | Freeze the final benchmark run config and thresholds before the paper-validation window starts. |

---

## 7. Anti-drift checkpoints

- MVP ends at validated paper trading and a promotion recommendation; no live
  capital path is introduced by this decision.
- The universe is spot-only and liquid-instrument focused; derivatives, margin,
  leverage, shorting, market making, and HFT remain excluded.
- No autonomous online model self-update or auto-promotion is allowed.
- No-trade/cash preservation is a first-class benchmark and decision alternative.
- The independent risk engine remains mandatory before any simulator, paper, or
  future live gateway.
- Source candidates are not data-use approvals; unapproved data cannot be used
  beyond controlled exploration.
- Benchmark criteria cannot be weakened or moved after a validation run begins.
- Any change to the locked universe, venue/source candidates, or benchmark set
  must cite affected requirement IDs and include owner approval, rationale, risk,
  rollback, and validation impact.

---

## 8. Acceptance evidence checklist

- [x] Decision record exists for Issue #2 / S0-001.
- [x] Requirement trace includes issue trace (`PG-001`–`PG-005`, `RISK-015`) and
  catalog trace (`FR-003`, `FR-007`, `FR-009`, `FR-014`, `FR-015`, `NFR-001`,
  `NFR-004`, `NFR-005`).
- [x] MVP universe assumptions are locked to liquid spot instruments.
- [x] Venue/source candidates are documented and gated by source/license review.
- [x] Benchmark set and benchmark construction policy are documented.
- [x] Docker/runtime impact is explicitly recorded as no runtime impact.
- [x] Anti-drift controls preserve no live capital, no leverage/derivatives,
  no risk-engine bypass, no benchmark moving, and no unapproved data use.
