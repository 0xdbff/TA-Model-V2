FROM docker.redpanda.com/redpandadata/redpanda:v24.3.6 AS redpanda

FROM python:3.12.10-slim-bookworm

COPY --from=redpanda /usr/bin/rpk /usr/bin/rpk
COPY --from=redpanda /opt/redpanda/libexec/rpk /opt/redpanda/libexec/rpk

WORKDIR /app
ENV PYTHONPATH=/app/src

COPY src ./src
COPY scripts/stream_profile_fixture_smoke.py ./scripts/stream_profile_fixture_smoke.py

RUN pip install --no-cache-dir pydantic==2.10.6
