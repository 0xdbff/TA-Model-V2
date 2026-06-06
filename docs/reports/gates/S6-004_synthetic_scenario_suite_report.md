# S6-004 Synthetic Scenario Suite Report

Issue: #30 / Sprint S6-004
Requirement trace: FR-012
Risk trace: RISK-001 market drawdown, RISK-002 liquidity collapse, RISK-005 cost sensitivity
Docker/runtime impact: none; stdlib-only fake/local scenario module, no new service, datastore, broker, dependency, or Docker profile.

## Evidence artifact

- Suite ID: `SYNTHSUITE:3868297592E10807461155B2A4A83F47`
- Suite hash: `7d75deb9542de866131e4c97dfcab6bf4a60288695d686abd6c1cea766e1a5ca`
- Seed: `6004`
- Run ID: `SYNTHETIC:S6-004:SUITE`
- Generator: `ta_model.simulation.scenarios.run_synthetic_scenario_suite`
- Simulator path: every scenario calls `replay_ohlctv_market_orders`; no mocked pass/fail summaries.
- Contract gate: `scenario_results` must contain each required scenario exactly once in deterministic order, suite requirement/risk IDs are validated, and required FR/risk/label traceability is validated at result and suite levels.

## Scenario matrix

| Scenario | Replay report | Status/rejection evidence | Cost evidence | Balance evidence | Trace |
|---|---|---:|---:|---|---|
| `random_walk` | `REPLAYREPORT:D9D6DF22735D7B82B9B9F8B7C2B5503E` | filled: 1 | `0.20010000` | FAKE `11`, USD `9899.79990000` | FR-012 |
| `trend` | `REPLAYREPORT:9672B0B6A1ACC2DBF6194C6127CFABA6` | filled: 2 | `0.226524500` | FAKE `10.50`, USD `9950.773475500` | FR-012 |
| `crash` | `REPLAYREPORT:DBE2CE3DD4B936DCBCFE284500324061` | filled: 1 | `0.2601600` | FAKE `11`, USD `9899.7398400` | FR-012, RISK-001 |
| `spread` | `REPLAYREPORT:FD6461B75C262BCCE4C40BE37247B2DA` | filled: 1 | high cost `1.601500` vs low-cost baseline `0.1200200` | FAKE `11`, USD `9898.398500` | FR-012, RISK-002, RISK-005 |
| `liquidity` | `REPLAYREPORT:FF6EE5CC827215787297D96CE0AFFF53` | partially_filled: 1; unfilled: 1; `insufficient_liquidity`: 1 | `0.35030000` | FAKE `10.50`, USD `9949.64970000` | FR-012, RISK-002 |
| `outage` | `REPLAYREPORT:DFA8743B59C4C2112CCD5043FAE1ED91` | rejected: 1; `venue_not_tradable`: 1 | `0` | FAKE `10`, USD `10000` | FR-012, RISK-002 |

## Validation commands

- `uv run pytest tests/test_synthetic_scenarios.py` — 16 passed.
- `uv run ruff check .` — passed.
- `uv run mypy src tests` — passed.
- `uv run pytest` — 213 passed.

## Anti-drift notes

- Synthetic bars are fake/local and event-time ordered; `source_ts <= close_ts`.
- Replay availability remains close-ts/event-time based; no ingest-time availability dependency and no same-bar fill implementation.
- Spot-only simulated account/instrument metadata; no leverage, derivatives, margin, shorting, market making, HFT, live capital, paper gateway, strategy/model logic, risk engine, or kill-switch implementation.
- Outage and liquidity scenarios fail closed through existing replay rejection accounting.

## Known limits

- The suite is QA evidence for integrated simulator behavior, not a model/strategy performance claim.
- Risk engine and kill-switch behavior are outside S6-004 scope and are not bypassed or simulated here.
