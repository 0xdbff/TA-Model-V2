# S1-004 Instrument Master Consumer Contract Report

| Field | Value |
|---|---|
| Gate | Data gate / S1 instrument-master downstream contract evidence |
| Sprint / issue | `S1-004` / GitHub Issue `#10` |
| Requirement IDs | `FR-003`, `NFR-005` |
| Scope covered | Contract tests that derive ingestion, simulator, risk, and gateway consumer views from the validated MVP spot instrument-master seed. |
| Scope explicitly not covered | Source-approved production metadata, ingestion runtime, simulator runtime, independent risk-engine execution, gateway behavior, paper trading, live capital, leverage, margin, derivatives, shorting, or autonomous model promotion. |
| Docker profile/services used | No runtime service or Docker Compose profile changed. Validation uses local Python contract tests; future containerized execution remains the approved `dev` / `app-dev` boundary once Compose exists. |
| Evidence artifacts | `tests/test_instrument_master_contracts.py`; `configs/instrument_master/mvp_spot_seed.json`; `docs/contracts/instrument_master_schemas.md`. |
| Anti-drift checkpoint | Downstream consumers must keep using the shared instrument-master contract; missing active fees/sessions/constraints or venue-supported order-type drift fail closed before ingestion, simulator, risk, or gateway code can treat metadata as usable. |

## Consumer views covered

The S1-004 tests validate `configs/instrument_master/mvp_spot_seed.json` with
`InstrumentMasterSnapshot` and derive deterministic views for future consumer test
fixtures:

| Consumer | Contract fields exercised |
|---|---|
| Ingestion | `instrument_id`, `canonical_symbol`, `venue_id`, `venue_symbol`, base/quote asset IDs, active session IDs, venue status/timezone, market-data rate-limit IDs, source stamp. |
| Simulator | Fee schedule ID, maker/taker fee rates, fee asset, tick size, lot size, min notional, min order quantity, instrument status, supported order types. |
| Risk | Active constraint ID, tick/lot/min-notional/min-quantity metadata, account risk caps, and `InstrumentConstraint.evaluate_order(...)` pass/fail reason codes. |
| Gateway | Paper account ID, trading permissions, key scope, supported order types, and explicit `false` live-capital/derivative/margin/short/leverage flags. |

The reproducibility digest for the deterministic consumer view is:

```text
f5d0694b5ed521e28158b91851a1aac2534b7129b1e09bfe3545c7c687b35b68
```

This digest is a contract drift sentinel. If metadata or consumer view shape changes
intentionally, update the digest in the same traceable PR with requirement IDs,
acceptance evidence, Docker/runtime impact, and anti-drift notes.

## Fail-closed checks added

`test_s1_004_downstream_consumers_fail_closed_on_missing_required_metadata` mutates
the seed and verifies validation fails for downstream-breaking states:

- expired active fee schedule;
- suspended active trading session;
- expired active instrument constraint;
- venue-supported order types that no longer cover instrument order types.

## Local acceptance evidence

Captured locally on 2026-06-03 from branch `agent/10-S1-004`:

```text
uv run pytest tests/test_instrument_master_contracts.py -k s1_004
6 passed, 20 deselected in 0.09s

uv run ruff check . && uv run mypy src tests && uv run pytest
All checks passed!
Success: no issues found in 5 source files
28 passed in 0.39s
```

## Drift risks observed

- No runtime service, datastore, broker, Docker image, credential, connector, data
  pull, raw payload, independent risk-engine bypass, gateway path, or live-capital
  path was introduced.
- The consumer views remain contract-test fixtures and do not authorize ingestion,
  retained venue data, paper trading, or validation claims while source/license
  approval remains separate.
- Spot-only scope is preserved: all live-capital, derivative, margin, shorting, and
  leverage fields remain explicitly disabled in the tested gateway view.
