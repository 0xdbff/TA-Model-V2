# S1 Instrument Master Schema Contracts

| Field | Value |
|---|---|
| Sprint / issues | `S1-001` / GitHub Issue `#7`; `S1-002` / GitHub Issue `#8`; `S1-003` / GitHub Issue `#9`; `S1-004` / GitHub Issue `#10` |
| Requirement trace | `FR-003`, `FR-010`, `NFR-004`, `NFR-005` |
| Contract touched | Canonical asset, venue, fee schedule, trading session, instrument constraint, instrument, account, and instrument-master snapshot metadata |
| Docker/runtime impact | No runtime service or Docker Compose profile is changed. The future executable test boundary is the approved `dev` / `app-dev` profile once Compose exists. |
| Acceptance evidence | Pydantic schema tests, invalid-record fixtures under `tests/fixtures/instrument_master/`, `configs/instrument_master/mvp_spot_seed.json`, and the S1-002/S1-003/S1-004 reports under `docs/reports/gates/` |

## Contract summary

The implementation in `src/ta_model/contracts/instrument_master.py` defines Pydantic v2 contracts for:

- `Asset` — canonical asset identity, symbol, type, classification flags, issuer/category, status, and metadata lineage.
- `Venue` — canonical venue identity, venue type, IANA timezone, API endpoint group, status, rate limits, supported order types, and metadata lineage.
- `FeeSchedule` — effective-dated maker/taker fee rates by venue and fee tier, with non-negative cost assumptions and metadata lineage.
- `TradingSession` — effective-dated venue trading windows, including explicit 24x7 sessions for spot crypto fixtures.
- `InstrumentConstraint` — effective-dated tick size, lot size, min notional, optional min/max quantity/notional limits, and deterministic order-constraint evaluation.
- `Instrument` — venue-specific tradable instrument mapped to canonical base/quote assets, with symbol, status, tick size, lot size, min notional, fee-schedule reference, supported order types, effective dating, and explicit MVP no-derivative/no-margin/no-short/no-leverage flags.
- `Account` — simulation/paper account identity, venue, permissions, fee tier, key scope, hard risk-limit references, and explicit no-live-capital/no-withdrawal/no-margin/no-derivative/no-shorting flags.
- `InstrumentMasterSnapshot` — point-in-time snapshot that enforces uniqueness, referential integrity, active fee/session/constraint windows, and consistency across assets, venues, effective-dated metadata, instruments, and accounts.

## Validation and anti-drift controls

- Unknown fields are rejected (`extra="forbid"`) so drifted metadata cannot be silently accepted by ingestion, simulator, risk, or gateway consumers.
- Snapshot validation rejects duplicate IDs, missing asset/venue references, and instrument order types not supported by the venue.
- Snapshot validation rejects missing or inactive effective-dated fee schedules, trading sessions, or instrument constraints at snapshot time.
- Fee and constraint effective windows are checked for non-overlap by venue/tier and instrument, respectively.
- Current instrument `tick_size`, `lot_size`, `min_notional`, and `fee_schedule_id` fields must agree with exactly one active effective-dated constraint and fee schedule.
- Fee schedules must reference known fee assets, and accounts must reference a venue fee tier with an active effective-dated fee schedule at snapshot time.
- Instrument constraints expose `evaluate_order(...)` so downstream risk, simulator, and gateway code can reject off-tick, off-lot, below-min-notional, or max-limit-breaching order intents without duplicating validation logic.
- The S1-004 tests derive stable ingestion, simulator, risk, and gateway consumer views from the validated seed and pin a SHA-256 digest so unreviewed downstream contract drift is visible.
- The S1-004 fail-closed mutations prove consumers cannot proceed when active fee schedules, sessions, constraints, or venue-supported order types are missing or inconsistent.
- Instrument validation requires positive `tick_size`, `lot_size`, and `min_notional`, effective dates in order, distinct base/quote assets, and explicit `false` values for derivative, margin, short-selling, and leverage flags.
- Account validation requires least-privilege paper/simulation/research account types, explicit `false` live-capital and withdrawal flags, and hard risk-limit caps aligned with the S0 risk policy.
- All metadata records carry `source_id`, optional `source_version`, and `metadata_ts` for audit and future source-register traceability.

## S1-003 MVP mapping seed

`configs/instrument_master/mvp_spot_seed.json` is the current S1 seed snapshot for
the locked MVP spot universe. It maps the canonical instruments
`COINBASE_SPOT:BTC-USD`, `COINBASE_SPOT:ETH-USD`, and `COINBASE_SPOT:SOL-USD` to
their venue-specific Coinbase spot symbols with base/quote assets, active fee
schedule references, 24x7 session metadata, tick sizes, lot sizes, min notionals,
and explicit no-derivative/no-margin/no-short/no-leverage flags.

The seed is contract/configuration evidence only. Because the source/license
register still marks the Coinbase source candidate as blocked pending review, the
mapping does not authorize ingestion, retained venue data, paper trading, or
validation claims. The corresponding acceptance report is
`docs/reports/gates/S1-003_mvp_instrument_mapping_report.md`.

## S1-004 downstream consumer contract suite

`tests/test_instrument_master_contracts.py` now includes explicit S1-004 tests that
load `configs/instrument_master/mvp_spot_seed.json`, validate it with
`InstrumentMasterSnapshot`, and derive deterministic consumer-facing views for:

- ingestion — canonical instrument IDs, venue symbols, active sessions, venue
  status/timezone, source stamp, and market-data rate-limit identifiers;
- simulator — active fees, tick size, lot size, min notional, status, and supported
  order types;
- risk — active constraint identifiers, tick/lot/min-notional/min-quantity
  metadata, account risk caps, and `InstrumentConstraint.evaluate_order(...)`
  pass/fail reason codes;
- gateway — paper account ID, trading permissions, key scope, supported order
  types, and explicit no-live-capital/no-derivative/no-margin/no-short/no-leverage
  flags.

The deterministic view digest is
`f5d0694b5ed521e28158b91851a1aac2534b7129b1e09bfe3545c7c687b35b68`. Any intentional
change to the S1 seed or consumer view shape should update the digest in the same
traceable PR with requirement IDs, acceptance evidence, Docker/runtime impact, and
anti-drift notes.

The S1-004 suite remains contract-test evidence only. It does not implement the
future ingestion, simulator, risk engine, or gateway runtimes and does not approve
Coinbase or any other source for ingestion or paper trading.

## Scope boundaries

This contract work does **not** implement source approval, database migrations, connectors, risk-engine execution, gateway behavior, paper trading, live capital, leverage, margin, derivatives, shorting, market making, or autonomous model self-promotion. The S1-002 fixture, S1-003 seed values, and S1-004 consumer views are contract/configuration evidence only; source-approved production metadata remains separate delivery evidence before ingestion or paper use.
