# CCXT and Binance Dependency Guardrail Report

| Field | Value |
|---|---|
| Gate | Build/data enabling-infrastructure checkpoint |
| Trigger | Explicit user request to add `ccxt` as a project dependency and keep Binance support important |
| Requirement IDs | `FR-001`, `FR-002`, `FR-003`, `NFR-002`, `NFR-003`, `NFR-005` |
| Scope covered | Pin `ccxt` as a project dependency, verify offline Binance exchange factory availability, and seed Binance spot as a blocked source/license candidate. |
| Scope explicitly not covered | Connector implementation, market-data ingestion, WebSocket streaming, paper trading, live capital, private account access, credentials, order routing, derivatives, leverage, margin, shorting, or source/legal approval. |
| Docker profile/services used | No runtime service or Docker Compose profile changed. Future connector work will affect `dev`, `research`, `stream`, and/or `paper` profiles in separate traceable issues. |
| Evidence artifacts | `pyproject.toml`, `uv.lock`, `docs/source_license_register.csv`, `docs/11_tech_stack_and_docker.md`, `tests/test_exchange_dependency_contracts.py`. |
| Anti-drift checkpoint | `ccxt` remains a library behind project-owned connector/gateway contracts; Binance remains blocked pending source/license review before ingestion or paper use. |

## Dependency decision

`ccxt==4.5.56` is pinned in `pyproject.toml` and locked in `uv.lock` so future
exchange connector work can delegate REST API normalization and exchange metadata
handling to a mature library instead of duplicating vendor-specific plumbing.

The dependency does **not** approve any exchange for use. It also does not create a
runtime service, persistent store, event broker, workflow engine, credential path,
order gateway, or paper/live execution route.

## Binance posture

Binance spot is added to `docs/source_license_register.csv` as
`binance_spot_market_data` because product direction says Binance support is
important. The row starts with:

- `license_review_status=not_started`
- `approved_use_status=blocked_pending_review`
- `production_use_status=not_approved_for_production`

This means future work may inspect public documentation and plan connector
contracts, but it may not ingest, retain, stream, train on, backtest with, paper
trade on, or make validation claims from Binance data until source/license,
retention, rate-limit, event-time, jurisdiction, and credential requirements are
approved.

## CCXT guardrails

- Use `ccxt` behind project-owned connector and gateway interfaces only.
- Standard `ccxt` is REST-oriented; WebSocket streaming remains TBD and requires a
  separate approved implementation path.
- Do not expose private exchange objects to strategy/model/risk code.
- Do not commit API keys, credentials, private account metadata, private payloads,
  paid market data, or confidential terms.
- Do not use SDK-supported derivatives, margin, leverage, shorting, futures,
  perpetuals, or funding endpoints during MVP.
- Do not bypass instrument-master constraints, source/license review, event-time
  data rules, independent pre-trade risk, kill switches, idempotency, audit traces,
  or paper/live promotion gates.

## Local acceptance evidence

Captured locally on branch `agent/add-ccxt-binance`:

```text
uv run ruff check . && uv run mypy src tests && uv run pytest
All checks passed!
Success: no issues found in 5 source files
21 passed in 0.29s
```
