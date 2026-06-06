# S1-002 Instrument Constraint Validation Report

| Field | Value |
|---|---|
| Gate | Data gate / S1 instrument-master evidence |
| Sprint / issue | `S1-002` / GitHub Issue `#8` |
| Requirement IDs | `FR-003`, `FR-010` |
| Scope covered | Effective-dated fee schedule, venue trading session, and tick/lot/min-notional instrument constraints for the S1 MVP spot fixture. |
| Scope explicitly not covered | Source-approved production metadata, ingestion, simulator execution, risk-engine execution, gateway behavior, paper trading, live capital, leverage, margin, derivatives, shorting, or S1-003 production mapping report. |
| Docker profile/services used | No runtime service or Docker Compose profile changed. Validation uses the future approved `dev` / `app-dev` boundary but runs as local Python contract tests until Compose exists. |
| Evidence artifacts | `tests/test_instrument_master_contracts.py`; `tests/fixtures/instrument_master/valid/mvp_spot_snapshot.json`; invalid fixtures in `tests/fixtures/instrument_master/invalid/`. |
| Anti-drift checkpoint | Missing fee schedules, sessions, or instrument constraints fail closed at schema/snapshot validation; live-capital, margin, derivative, shorting, and leverage flags remain explicitly blocked. |

## Fixture coverage

The committed S1-002 fixture is `S1_002_MVP_SPOT_CONSTRAINT_FIXTURE` with fixture-only Coinbase spot metadata for the current MVP spot candidates from the S0 universe decision record:

| Instrument | Fee schedule | Trading session | Tick size | Lot size | Min notional | Status |
|---|---|---|---:|---:|---:|---|
| `COINBASE_SPOT:BTC-USD` | `COINBASE_SPOT_STANDARD_FEES_2026Q1` | `COINBASE_SPOT_24X7_2026Q1` | `0.01` | `0.00000001` | `1.00` | Pass |
| `COINBASE_SPOT:ETH-USD` | `COINBASE_SPOT_STANDARD_FEES_2026Q1` | `COINBASE_SPOT_24X7_2026Q1` | `0.01` | `0.00000001` | `1.00` | Pass |
| `COINBASE_SPOT:SOL-USD` | `COINBASE_SPOT_STANDARD_FEES_2026Q1` | `COINBASE_SPOT_24X7_2026Q1` | `0.01` | `0.000001` | `1.00` | Pass |

These values are contract fixtures, not source-approved production metadata. Before ingestion or paper use, the source/license workflow and future mapping evidence must approve and version venue-derived metadata.

## Validation checks added

- `FeeSchedule` rejects negative maker/taker fee rates and invalid effective windows.
- `TradingSession` validates IANA timezones, explicit 24x7 day coverage, and effective windows.
- `InstrumentConstraint` validates positive tick/lot/min-notional values, optional min/max bounds, and effective windows.
- `InstrumentConstraint.evaluate_order(...)` returns machine-readable reason codes for off-tick prices, off-lot quantities, below-min-notional orders, non-positive inputs, and optional max-limit breaches.
- `InstrumentMasterSnapshot` rejects duplicate metadata IDs, unknown fee/session/constraint references, fee schedules with unknown fee assets, overlapping effective windows, missing active trading sessions, missing active fee schedules for instruments/accounts, and drift between current instrument fields and active effective-dated constraints.

## Local acceptance evidence

Captured locally on 2026-06-02 from branch `agent/8-S1-002`:

```text
uv run ruff check . && uv run mypy src tests && uv run pytest
All checks passed!
Success: no issues found in 4 source files
19 passed in 0.09s
```

## Drift risks observed

- No runtime service, datastore, broker, Docker image, credential, source data pull, risk-engine bypass, gateway path, or live-capital path was introduced.
- The S1-002 fixture deliberately remains marked with `source_id=FIXTURE_S1_002` to avoid treating fixture metadata as source-approved venue metadata.
