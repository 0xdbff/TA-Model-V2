# S1-003 MVP Instrument Mapping Report

| Field | Value |
|---|---|
| Gate | Data gate / S1 instrument-master evidence |
| Sprint / issue | `S1-003` / GitHub Issue `#9` |
| Requirement IDs | `FR-003` |
| Scope covered | Seed canonical MVP spot assets and instruments with venue-specific Coinbase spot identifiers, quote/base mapping, active status, fee schedule reference, 24x7 session reference, tick size, lot size, and min notional metadata. |
| Scope explicitly not covered | Source-approved production metadata, ingestion, simulator execution, risk-engine execution, gateway behavior, paper trading, live capital, leverage, margin, derivatives, shorting, multi-venue execution, or autonomous model promotion. |
| Docker profile/services used | No runtime service or Docker Compose profile changed. Validation uses the future approved `dev` / `app-dev` boundary but runs as local Python contract tests until Compose exists. |
| Evidence artifacts | `configs/instrument_master/mvp_spot_seed.json`; `tests/test_instrument_master_contracts.py`; existing invalid fixtures in `tests/fixtures/instrument_master/invalid/`. |
| Anti-drift checkpoint | Seed remains spot-only and candidate-only; all live-capital, derivative, margin, shorting, and leverage flags are explicitly false; source/license approval is still blocked before ingestion or paper use. |

## Mapping seed

The committed seed snapshot is `S1_003_MVP_SPOT_MAPPING_SEED` at
`configs/instrument_master/mvp_spot_seed.json`. It extends the S1 instrument-master
contract evidence into an explicit configuration artifact for downstream ingestion,
simulator, risk, and gateway consumers to reference in future contract work.

| Canonical instrument ID | Canonical symbol | Venue ID | Venue symbol | Base asset ID | Quote asset ID | Type | Status | Tick size | Lot size | Min notional | Fee schedule | Session |
|---|---|---|---|---|---|---|---|---:|---:|---:|---|---|
| `COINBASE_SPOT:BTC-USD` | `BTC-USD` | `COINBASE_SPOT` | `BTC-USD` | `BTC` | `USD` | `spot` | `trading` | `0.01` | `0.00000001` | `1.00` | `COINBASE_SPOT_STANDARD_FEES_2026Q2` | `COINBASE_SPOT_24X7_2026Q2` |
| `COINBASE_SPOT:ETH-USD` | `ETH-USD` | `COINBASE_SPOT` | `ETH-USD` | `ETH` | `USD` | `spot` | `trading` | `0.01` | `0.00000001` | `1.00` | `COINBASE_SPOT_STANDARD_FEES_2026Q2` | `COINBASE_SPOT_24X7_2026Q2` |
| `COINBASE_SPOT:SOL-USD` | `SOL-USD` | `COINBASE_SPOT` | `SOL-USD` | `SOL` | `USD` | `spot` | `trading` | `0.01` | `0.000001` | `1.00` | `COINBASE_SPOT_STANDARD_FEES_2026Q2` | `COINBASE_SPOT_24X7_2026Q2` |

## Metadata and source posture

- Seed source stamp: `source_id=S1_003_MAPPING_SEED`, `source_version=mvp_seed_v1`,
  `metadata_ts=2026-06-02T00:00:00Z`.
- The source/license register still marks `coinbase_spot_market_data` as
  `blocked_pending_review` and `not_approved_for_production`.
- This seed is therefore a contract/configuration fixture for S1/S2 handoff, not
  approval to ingest, retain venue data, run paper trading, or claim validation
  performance.
- No API credentials, secrets, raw market payloads, paid data, or confidential
  license text are committed.

## Validation checks added

- `test_s1_003_mvp_seed_maps_canonical_instruments_to_venue_symbols` validates the
  seed snapshot with the `InstrumentMasterSnapshot` Pydantic contract.
- The test asserts exact canonical instrument IDs, venue IDs, venue symbols,
  base/quote asset IDs, tick sizes, lot sizes, and min notionals.
- The test asserts all seed instruments remain spot/trading instruments and that
  derivative, margin, short-selling, and leverage flags remain false.
- Existing snapshot validation continues to enforce referential integrity, active
  effective-dated fee schedules, active trading sessions, active constraints, and
  unknown-field rejection.

## Local acceptance evidence

Captured locally on 2026-06-02 from branch `agent/9-S1-003`:

```text
uv run ruff check . && uv run mypy src tests && uv run pytest
All checks passed!
Success: no issues found in 4 source files
20 passed in 0.09s
```

## Drift risks observed

- No runtime service, datastore, broker, Docker image, credential, connector, data
  pull, raw payload, risk-engine bypass, gateway path, or live-capital path was
  introduced.
- The seed deliberately uses `S1_003_MAPPING_SEED` rather than an approved venue
  source ID to avoid treating blocked source metadata as approved for ingestion or
  paper use.
- Secondary venue/source candidate mappings are not guessed here. Kraken or other
  venue mappings require source/license review and metadata evidence before they
  can become delivery artifacts.
