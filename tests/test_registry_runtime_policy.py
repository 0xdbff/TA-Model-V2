"""Policy evidence for S7-003 registry runtime hardening."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
MLFLOW_DOCKERFILE = ROOT / "docker" / "mlflow" / "Dockerfile"


def test_registry_compose_has_no_committed_secret_defaults() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")

    forbidden_tokens = (
        "password_change_me",
        "secret_key_change_me",
        "mlflow_local_password",
        "mlflow_local_secret",
        "mlflow_local_access_key",
    )
    assert not any(token in compose for token in forbidden_tokens)
    assert "MLFLOW_POSTGRES_PASSWORD:?" in compose
    assert "MLFLOW_MINIO_ROOT_PASSWORD:?" in compose


def test_registry_host_ports_are_localhost_bound() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")

    assert '"127.0.0.1:5000:5000"' in compose
    assert '"127.0.0.1:9000:9000"' in compose
    assert '"127.0.0.1:9001:9001"' in compose
    assert '"5000:5000"' not in compose
    assert '"9000:9000"' not in compose
    assert '"9001:9001"' not in compose


def test_mlflow_dockerfile_declares_non_root_user() -> None:
    dockerfile = MLFLOW_DOCKERFILE.read_text(encoding="utf-8")

    match = re.search(r"^USER\s+(?P<user>\S+)", dockerfile, flags=re.MULTILINE)
    assert match is not None
    assert match.group("user") not in {"0", "0:0", "root"}


def test_mlflow_service_has_healthcheck() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    mlflow_section = compose.split("  mlflow:", maxsplit=1)[1].split("  redpanda:", maxsplit=1)[0]

    assert "healthcheck:" in mlflow_section
    assert "http://127.0.0.1:5000/health" in mlflow_section
