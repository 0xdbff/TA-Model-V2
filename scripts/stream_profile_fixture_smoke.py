"""Validate S3-004 fixture-only stream smoke payloads through health contracts.

Traceability:
- FR-002: fixture stream freshness, sequence gap, and duplicate measurements.
- NFR-003: deterministic stream profile smoke evidence for the event bus path.
- NFR-006: stale critical feed emits a scoped fail-closed signal.

This script uses committed synthetic fixtures only. It does not open exchange/API
connections, use credentials, route orders, or interact with paper/live gateways.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ta_model.contracts.stream_health import DataHealthGate, StreamHealthEvaluator
from ta_model.contracts.streaming import TradeEvent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("tests/fixtures/stream/stream_profile_events.jsonl"),
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/stream_profile/smoke.json"))
    args = parser.parse_args()

    summary = run_smoke(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


def run_smoke(input_path: Path) -> dict[str, Any]:
    evaluator = StreamHealthEvaluator()
    gate = DataHealthGate()
    observations: list[dict[str, Any]] = []

    lines = input_path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        fixture = json.loads(line)
        event = TradeEvent.model_validate(fixture["event"])
        record = evaluator.evaluate(event, evaluation_ts=_parse_datetime(fixture["evaluation_ts"]))
        signal = gate.evaluate(record)
        checks = sorted(issue.check.value for issue in record.issues)

        expected_checks = sorted(fixture["expected_checks"])
        if record.status.value != fixture["expected_health_status"]:
            raise AssertionError(
                f"line {line_number}: unexpected health status {record.status.value}"
            )
        if checks != expected_checks:
            raise AssertionError(
                f"line {line_number}: expected checks {expected_checks}, got {checks}"
            )
        if signal.status.value != fixture["expected_signal_status"]:
            raise AssertionError(
                f"line {line_number}: unexpected signal status {signal.status.value}"
            )
        if signal.blocks_trading is not fixture["expected_blocks_trading"]:
            raise AssertionError(f"line {line_number}: unexpected blocks_trading")

        observations.append(
            {
                "blocks_trading": signal.blocks_trading,
                "checks": checks,
                "health_status": record.status.value,
                "message_id": fixture["message_id"],
                "signal_status": signal.status.value,
            }
        )

    return {
        "anti_drift": {
            "event_time_clock": (
                "evaluation_ts compared to event_ts/source_ts; ingest_ts is not used"
            ),
            "fixture_only": True,
            "live_capital_path": False,
        },
        "blocked_signals": sum(1 for observation in observations if observation["blocks_trading"]),
        "events_evaluated": len(observations),
        "observations": observations,
        "requirements": ["FR-002", "NFR-003", "NFR-006"],
        "verdict": "pass",
    }


def _parse_datetime(value: str) -> Any:
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


if __name__ == "__main__":
    main()
