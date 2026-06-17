"""Evidence for S9-003 durable kill-switch persistence and fail-closed reads."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from risk_test_helpers import START, global_scope
from ta_model.contracts.risk import KillSwitchState, KillSwitchTransitionSource
from ta_model.risk.kill_switch import FileKillSwitchStateStore


def test_uninitialized_kill_switch_store_fails_closed(tmp_path: Path) -> None:
    store = FileKillSwitchStateStore(tmp_path / "kill-switch.json")

    snapshot = store.load_snapshot(
        evaluated_at=START,
        evaluated_scopes=(global_scope(),),
    )

    assert snapshot.active_state is KillSwitchState.UNKNOWN_FAIL_CLOSED
    assert snapshot.store_available is True
    assert snapshot.active_records == ()
    assert "uninitialized" in snapshot.reason


def test_kill_switch_state_persists_across_new_store_instance(tmp_path: Path) -> None:
    path = tmp_path / "kill-switch.json"
    first_store = FileKillSwitchStateStore(path)
    clear_record = first_store.transition(
        scope=global_scope(),
        new_state=KillSwitchState.CLEAR,
        actor="alice",
        actor_role="ops_owner",
        transitioned_at=START,
        reason="initialize fixture paper environment",
        cancel_open_orders=False,
    )

    restarted_store = FileKillSwitchStateStore(path)
    snapshot = restarted_store.load_snapshot(
        evaluated_at=START + timedelta(seconds=1),
        evaluated_scopes=(global_scope(),),
    )

    assert clear_record.prior_state is KillSwitchState.UNKNOWN_FAIL_CLOSED
    assert clear_record.new_state is KillSwitchState.CLEAR
    assert snapshot.active_state is KillSwitchState.CLEAR
    assert snapshot.active_records == (clear_record,)
    assert snapshot.store_available is True


def test_kill_switch_transition_audit_fields_are_persisted(tmp_path: Path) -> None:
    path = tmp_path / "kill-switch.json"
    store = FileKillSwitchStateStore(path)
    store.transition(
        scope=global_scope(),
        new_state=KillSwitchState.CLEAR,
        actor="alice",
        actor_role="ops_owner",
        transitioned_at=START,
        reason="initialize fixture paper environment",
        cancel_open_orders=False,
    )
    pause_record = store.transition(
        scope=global_scope(),
        new_state=KillSwitchState.PAUSE_NEW_ORDERS,
        actor="risk-bot",
        actor_role="automated_risk_monitor",
        transitioned_at=START + timedelta(minutes=1),
        reason="hard daily loss trigger fixture",
        cancel_open_orders=True,
    )

    restarted_store = FileKillSwitchStateStore(path)
    snapshot = restarted_store.load_snapshot(
        evaluated_at=START + timedelta(minutes=2),
        evaluated_scopes=(global_scope(),),
    )

    assert pause_record.actor == "risk-bot"
    assert pause_record.actor_role == "automated_risk_monitor"
    assert pause_record.transitioned_at == START + timedelta(minutes=1)
    assert pause_record.scope == global_scope()
    assert pause_record.prior_state is KillSwitchState.CLEAR
    assert pause_record.new_state is KillSwitchState.PAUSE_NEW_ORDERS
    assert pause_record.reason == "hard daily loss trigger fixture"
    assert pause_record.cancel_open_orders is True
    assert snapshot.active_state is KillSwitchState.PAUSE_NEW_ORDERS
    assert snapshot.active_records == (pause_record,)


def test_automated_kill_switch_transition_source_persists_across_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "kill-switch.json"
    store = FileKillSwitchStateStore(path)
    store.transition(
        scope=global_scope(),
        new_state=KillSwitchState.CLEAR,
        actor="alice",
        actor_role="ops_owner",
        transitioned_at=START,
        reason="initialize fixture paper environment",
        cancel_open_orders=False,
    )
    automated_record = store.transition(
        scope=global_scope(),
        new_state=KillSwitchState.PAUSE_NEW_ORDERS,
        actor="risk-bot",
        actor_role="automated_risk_monitor",
        transitioned_at=START + timedelta(minutes=1),
        reason="hard daily loss trigger fixture",
        cancel_open_orders=True,
        source=KillSwitchTransitionSource.AUTOMATED,
    )

    restarted_store = FileKillSwitchStateStore(path)
    snapshot = restarted_store.load_snapshot(
        evaluated_at=START + timedelta(minutes=2),
        evaluated_scopes=(global_scope(),),
    )

    assert automated_record.source is KillSwitchTransitionSource.AUTOMATED
    assert automated_record.cancel_open_orders is True
    assert snapshot.active_state is KillSwitchState.PAUSE_NEW_ORDERS
    assert snapshot.active_records == (automated_record,)
    assert snapshot.active_records[0].source is KillSwitchTransitionSource.AUTOMATED
    assert snapshot.active_records[0].cancel_open_orders is True


def test_unavailable_kill_switch_store_fails_closed(tmp_path: Path) -> None:
    store = FileKillSwitchStateStore(tmp_path)

    snapshot = store.load_snapshot(evaluated_at=START, evaluated_scopes=(global_scope(),))

    assert snapshot.active_state is KillSwitchState.UNKNOWN_FAIL_CLOSED
    assert snapshot.store_available is False
    assert "unavailable" in snapshot.reason
