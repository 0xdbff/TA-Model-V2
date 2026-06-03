# S3-004 Stream Docker Profile Smoke Report

## Traceability

- Primary: NFR-003 scoped to S3-004 stream Docker profile smoke evidence. Full disconnect/reconnect recovery remains covered by separate streaming-ingestion work.
- Supporting: FR-002 (freshness, sequence gap, duplicate measurements), NFR-006 (stale critical feeds fail closed).

## Docker/runtime impact

- Added `docker-compose.yml` with the `stream` profile and a minimal smoke image Dockerfile.
- Services: `redpanda`, `stream-smoke`.
- Broker image: `docker.redpanda.com/redpandadata/redpanda:v24.3.6`.
- Smoke image: local `ta-model-v2-stream-smoke:s3-004`, built from `python:3.12.10-slim-bookworm` plus the Redpanda `rpk` CLI copied from `docker.redpanda.com/redpandadata/redpanda:v24.3.6`; it installs only `pydantic==2.10.6` for the project contract models and does not add Kafka Python clients.
- Pulled digest observed locally: `docker.redpanda.com/redpandadata/redpanda@sha256:04baa40ed34edf86028396f762be802f3b6b0acaab65e9de696a3f15d54c550f`.
- Python base digest observed in Compose build output: `docker.io/library/python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db`.
- Built smoke image tag observed locally after the final smoke run: `ta-model-v2-stream-smoke:s3-004` (`sha256:41efb882b1be02dde365f6f0bf7d1c37f80c2ca1fe840fa9823ffae6afbbec8c`).
- Broker: Redpanda only; already selected in `docs/11_tech_stack_and_docker.md`, so no ADR required.
- Data: fixture-only synthetic JSONL events mounted read-only; Redpanda smoke state uses the `redpanda_stream_data` named volume and must be removed with `docker compose --profile stream down -v` after smoke runs. No Kafka Python client dependency was added; the smoke path uses `rpk` for bus produce/consume and the project Python contracts for validation of consumed payloads.

## Commands

```bash
uv run ruff check .
uv run mypy src tests
uv run pytest
docker compose --profile stream config
docker compose --profile stream up --build --abort-on-container-exit --exit-code-from stream-smoke stream-smoke
docker compose --profile stream down -v
docker image inspect docker.redpanda.com/redpandadata/redpanda:v24.3.6 --format '{{index .RepoDigests 0}}'
docker image inspect ta-model-v2-stream-smoke:s3-004 --format '{{.Id}} {{json .RepoTags}}'
```

## Results

- `uv run ruff check .`: pass.
- `uv run mypy src tests`: pass (`Success: no issues found in 24 source files`).
- `uv run pytest`: pass (`94 passed in 0.59s`).
- Compose config: pass.
- Compose stream smoke: pass; `stream-smoke` produced 4 fixture-only JSONL events to Redpanda, consumed those bus payloads to `/tmp/consumed.jsonl`, then validated the consumed payloads with `TradeEvent`, `StreamHealthEvaluator`, and `DataHealthGate`. Output showed 4 events evaluated, 1 scoped stale-feed block, and `verdict: pass`; container exited `0`.
- Cleanup: `docker compose --profile stream down -v` removed containers, network, and `redpanda_stream_data` volume.

## Anti-drift notes

- Fixture/synthetic events only; no exchange, API, WebSocket, credential, paper, or live-capital path added.
- Freshness/staleness is evaluated from `event_ts`/`source_ts` against explicit `evaluation_ts`; `ingest_ts` is not used as market availability time.
- Stale BTC-USD fixture emits a scoped `blocks_trading=True` data-health signal only; no order routing, risk bypass, or kill-switch bypass is introduced.

## Gate decision

- Pass for S3-004 fixture-only stream Docker profile smoke evidence.
