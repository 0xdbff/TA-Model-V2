"""S3-004 stream profile fixture smoke evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_stream_profile_fixture_smoke_script_validates_expected_fail_closed_path(
    tmp_path: Path,
) -> None:
    output = tmp_path / "smoke.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/stream_profile_fixture_smoke.py",
            "--input",
            "tests/fixtures/stream/stream_profile_events.jsonl",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(output.read_text(encoding="utf-8"))
    assert summary["verdict"] == "pass"
    assert summary["events_evaluated"] == 4
    assert summary["blocked_signals"] == 1
    assert summary["anti_drift"]["fixture_only"] is True
    assert "NFR-003" in summary["requirements"]
    assert "fixture-trade-stale" in result.stdout
