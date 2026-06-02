# S1-001 Instrument Master Schema Contracts

| Field | Value |
|---|---|
| Sprint / issue | `S1-001` / GitHub Issue `#7` |
| Requirement trace | `FR-003`, `NFR-004` |
| Contract touched | Canonical asset, venue, instrument, account, and instrument-master snapshot metadata |
| Docker/runtime impact | No runtime service or Docker Compose profile is changed. The future executable test boundary is the approved `dev` / `app-dev` profile once Compose exists. |
| Acceptance evidence | Pydantic schema tests and invalid-record fixtures under `tests/fixtures/instrument_master/` |

## Contract summary

The implementation in `src/ta_model/contracts/instrument_master.py` defines Pydantic v2 contracts for:

- `Asset` — canonical asset identity, symbol, type, classification flags, issuer/category, status, and metadata lineage.
- `Venue` — canonical venue identity, venue type, IANA timezone, API endpoint group, status, rate limits, supported order types, and metadata lineage.
- `Instrument` — venue-specific tradable instrument mapped to canonical base/quote assets, with symbol, status, tick size, lot size, min notional, fee-schedule reference, supported order types, effective dating, and explicit MVP no-derivative/no-margin/no-short/no-leverage flags.
- `Account` — simulation/paper account identity, venue, permissions, fee tier, key scope, hard risk-limit references, and explicit no-live-capital/no-withdrawal/no-margin/no-derivative/no-shorting flags.
- `InstrumentMasterSnapshot` — point-in-time snapshot that enforces uniqueness and referential integrity across assets, venues, instruments, and accounts.

## Validation and anti-drift controls

- Unknown fields are rejected (`extra="forbid"`) so drifted metadata cannot be silently accepted by ingestion, simulator, risk, or gateway consumers.
- Snapshot validation rejects duplicate IDs, missing asset/venue references, and instrument order types not supported by the venue.
- Instrument validation requires positive `tick_size`, `lot_size`, and `min_notional`, effective dates in order, distinct base/quote assets, and explicit `false` values for derivative, margin, short-selling, and leverage flags.
- Account validation requires least-privilege paper/simulation/research account types, explicit `false` live-capital and withdrawal flags, and hard risk-limit caps aligned with the S0 risk policy.
- All metadata records carry `source_id`, optional `source_version`, and `metadata_ts` for audit and future source-register traceability.

## Scope boundaries

This issue does **not** implement source approval, seeded production mappings, fee schedules, sessions, database migrations, connectors, risk-engine execution, gateway behavior, paper trading, live capital, leverage, margin, derivatives, shorting, market making, or autonomous model self-promotion.
