"""Durable local JSON kill-switch state store for S9 tests and local runs.

This adapter is intentionally file-backed to avoid adding an unapproved runtime
service in S9. It is not the final PostgreSQL paper-runtime adapter described in
the stack plan, but it provides durable restart semantics and fail-closed reads.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from ta_model.contracts.risk import (
    KillSwitchRecord,
    KillSwitchScope,
    KillSwitchScopeType,
    KillSwitchSnapshot,
    KillSwitchState,
    KillSwitchTransitionSource,
    make_kill_switch_record,
    make_kill_switch_snapshot,
    make_unknown_kill_switch_snapshot,
)


class FileKillSwitchStateStore:
    """Durable JSON-backed kill-switch transition log.

    Reads fail closed to ``UNKNOWN_FAIL_CLOSED`` when the file is absent,
    unreadable, invalid, or contains no initialized records.
    """

    _SCHEMA_VERSION = "kill-switch-store.v1"

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load_snapshot(
        self,
        *,
        evaluated_at: datetime,
        evaluated_scopes: tuple[KillSwitchScope, ...],
    ) -> KillSwitchSnapshot:
        """Load the most restrictive active state for the requested scopes."""

        records = self._read_records()
        if records is None:
            return make_unknown_kill_switch_snapshot(
                evaluated_at=evaluated_at,
                evaluated_scopes=evaluated_scopes,
                store_available=False,
                reason="durable kill-switch state unavailable or invalid",
            )
        if not records:
            return make_unknown_kill_switch_snapshot(
                evaluated_at=evaluated_at,
                evaluated_scopes=evaluated_scopes,
                store_available=True,
                reason="durable kill-switch state uninitialized",
            )

        latest_by_scope = _latest_records_by_scope(records)
        matching_records = _matching_records(
            latest_by_scope=latest_by_scope,
            evaluated_scopes=evaluated_scopes,
        )
        if not matching_records:
            return make_unknown_kill_switch_snapshot(
                evaluated_at=evaluated_at,
                evaluated_scopes=evaluated_scopes,
                store_available=True,
                reason="no applicable kill-switch record for requested scopes",
            )
        active_state = max(
            matching_records,
            key=lambda record: _state_severity(record.new_state),
        ).new_state
        return make_kill_switch_snapshot(
            evaluated_at=evaluated_at,
            evaluated_scopes=evaluated_scopes,
            active_state=active_state,
            active_records=tuple(sorted(matching_records, key=lambda record: record.record_id)),
            store_available=True,
            reason="durable kill-switch state loaded",
        )

    def transition(
        self,
        *,
        scope: KillSwitchScope,
        new_state: KillSwitchState,
        actor: str,
        actor_role: str,
        transitioned_at: datetime,
        reason: str,
        cancel_open_orders: bool,
        source: KillSwitchTransitionSource = KillSwitchTransitionSource.MANUAL,
        linked_incident_id: str | None = None,
    ) -> KillSwitchRecord:
        """Append a durable audited kill-switch transition."""

        records = self._read_records() or ()
        latest = _latest_records_by_scope(records).get(scope.key())
        prior_state = (
            latest.new_state if latest is not None else KillSwitchState.UNKNOWN_FAIL_CLOSED
        )
        record = make_kill_switch_record(
            scope=scope,
            prior_state=prior_state,
            new_state=new_state,
            actor=actor,
            actor_role=actor_role,
            transitioned_at=transitioned_at,
            reason=reason,
            cancel_open_orders=cancel_open_orders,
            source=source,
            linked_incident_id=linked_incident_id,
        )
        self._write_records((*records, record))
        return record

    def _read_records(self) -> tuple[KillSwitchRecord, ...] | None:
        if not self.path.exists():
            return ()
        try:
            payload = cast("dict[str, Any]", json.loads(self.path.read_text(encoding="utf-8")))
            if payload.get("schema_version") != self._SCHEMA_VERSION:
                return None
            raw_records = payload.get("records")
            if not isinstance(raw_records, list):
                return None
            return tuple(KillSwitchRecord.model_validate(item) for item in raw_records)
        except (OSError, json.JSONDecodeError, TypeError, ValidationError):
            return None

    def _write_records(self, records: tuple[KillSwitchRecord, ...]) -> None:
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self._SCHEMA_VERSION,
            "records": [record.model_dump(mode="json") for record in records],
        }
        temp_path = self.path.with_name(f".{self.path.name}.tmp")
        temp_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temp_path, self.path)


def _latest_records_by_scope(
    records: tuple[KillSwitchRecord, ...]
) -> dict[tuple[KillSwitchScopeType, str | None], KillSwitchRecord]:
    latest: dict[tuple[KillSwitchScopeType, str | None], KillSwitchRecord] = {}
    for record in sorted(records, key=lambda item: (item.transitioned_at, item.record_id)):
        latest[record.scope.key()] = record
    return latest


def _matching_records(
    *,
    latest_by_scope: dict[tuple[KillSwitchScopeType, str | None], KillSwitchRecord],
    evaluated_scopes: tuple[KillSwitchScope, ...],
) -> tuple[KillSwitchRecord, ...]:
    scope_keys = {scope.key() for scope in evaluated_scopes}
    global_key = (KillSwitchScopeType.GLOBAL, None)
    keys = scope_keys | {global_key}
    return tuple(record for key, record in latest_by_scope.items() if key in keys)


def _state_severity(state: KillSwitchState) -> int:
    return {
        KillSwitchState.CLEAR: 0,
        KillSwitchState.SOFT_LIMITED: 1,
        KillSwitchState.PAUSE_NEW_ORDERS: 2,
        KillSwitchState.REDUCE_ONLY: 3,
        KillSwitchState.CANCEL_ONLY: 4,
        KillSwitchState.HALTED: 5,
        KillSwitchState.UNKNOWN_FAIL_CLOSED: 6,
    }[state]
