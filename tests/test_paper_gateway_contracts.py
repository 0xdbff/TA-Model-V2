"""S10-001 evidence for shared simulator/paper gateway lifecycle contracts."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from inspect import signature

import pytest
from pydantic import ValidationError

import ta_model.contracts as public_contracts
from risk_test_helpers import (
    START,
    account_state,
    bar,
    default_policy,
    intent,
    load_snapshot,
    risk_request,
)
from ta_model.contracts.execution import (
    ExecutionFillMode,
    ExecutionGatewayKind,
    ExecutionGatewayLifecycleEvent,
    ExecutionGatewayOrderStatus,
    ExecutionGatewayReport,
)
from ta_model.contracts.risk import KillSwitchState, RiskDecisionStatus, RiskReasonCode
from ta_model.contracts.simulation import ReplayFillStatus, make_execution_cost_model
from ta_model.contracts.stream_health import (
    DataHealthReasonCode,
    DataHealthSignal,
    DataHealthStatus,
    StreamHealthCheck,
    StreamHealthMetricName,
    StreamHealthScope,
    StreamHealthStatus,
)
from ta_model.contracts.streaming import StreamChannel
from ta_model.execution import run_paper_gateway_replay, run_simulator_gateway_replay
from ta_model.risk.engine import evaluate_pre_trade_risk


def test_public_exports_include_shared_execution_gateway_contracts() -> None:
    assert public_contracts.ExecutionGatewayReport is ExecutionGatewayReport
    assert public_contracts.ExecutionGatewayLifecycleEvent is ExecutionGatewayLifecycleEvent
    assert public_contracts.ExecutionGatewayKind is ExecutionGatewayKind
    assert public_contracts.ExecutionFillMode is ExecutionFillMode


def test_paper_gateway_requires_risk_events_not_raw_order_intents() -> None:
    parameters = signature(run_paper_gateway_replay).parameters

    assert "risk_events" in parameters
    assert "order_intents" not in parameters


def test_simulator_and_paper_gateways_emit_same_lifecycle_shape_for_approved_risk() -> None:
    approved = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(order_id="ORDER:S10:APPROVED")),
        policy=default_policy(),
    )
    model = make_execution_cost_model(
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
    )

    simulator_report = run_simulator_gateway_replay(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(approved,),
        run_id="GATEWAY:S10:SIMULATOR",
        execution_cost_model=model,
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )
    paper_report = run_paper_gateway_replay(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(approved,),
        run_id="GATEWAY:S10:PAPER",
        execution_cost_model=model,
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )

    _assert_successful_gateway_report(
        simulator_report,
        gateway_kind=ExecutionGatewayKind.SIMULATOR,
        fill_mode=ExecutionFillMode.EVENT_TIME_REPLAY,
        expected_requirements=("FR-010", "FR-012", "NFR-004", "TFR-008"),
    )
    _assert_successful_gateway_report(
        paper_report,
        gateway_kind=ExecutionGatewayKind.PAPER,
        fill_mode=ExecutionFillMode.PAPER_SIMULATED_FILL,
        expected_requirements=("FR-010", "FR-013", "NFR-004", "TFR-008"),
    )
    assert set(simulator_report.model_dump()) == set(paper_report.model_dump())
    assert set(simulator_report.events[0].model_dump()) == set(paper_report.events[0].model_dump())


def test_paper_gateway_records_rejected_kill_and_stale_risk_events_as_blocked() -> None:
    notional_rejected = evaluate_pre_trade_risk(
        request=risk_request(
            order_intent=intent(quantity=Decimal("3"), order_id="ORDER:S10:BLOCK")
        ),
        policy=default_policy(),
    )
    kill_blocked = evaluate_pre_trade_risk(
        request=risk_request(
            order_intent=intent(order_id="ORDER:S10:KILL"),
            kill_state=KillSwitchState.PAUSE_NEW_ORDERS,
        ),
        policy=default_policy(),
    )
    stale_blocked = evaluate_pre_trade_risk(
        request=risk_request(
            order_intent=intent(order_id="ORDER:S10:STALE"),
            data_health_signals=(_stale_data_health_signal(),),
        ),
        policy=default_policy(),
    )

    report = run_paper_gateway_replay(
        bars=(bar(0), bar(1)),
        risk_events=(notional_rejected, kill_blocked, stale_blocked),
        run_id="GATEWAY:S10:PAPER-BLOCKED",
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )

    assert notional_rejected.final_decision is RiskDecisionStatus.REJECTED
    assert kill_blocked.final_decision is RiskDecisionStatus.REJECTED
    assert stale_blocked.final_decision is RiskDecisionStatus.REJECTED
    assert report.gateway_kind is ExecutionGatewayKind.PAPER
    assert report.fill_mode is ExecutionFillMode.PAPER_SIMULATED_FILL
    assert report.approved_risk_check_ids == ()
    assert report.blocked_risk_check_ids == (
        notional_rejected.risk_check_id,
        kill_blocked.risk_check_id,
        stale_blocked.risk_check_id,
    )
    assert report.source_replay_report_id is None
    assert {event.status for event in report.events} == {ExecutionGatewayOrderStatus.BLOCKED}
    assert all(event.gateway_order_id is None for event in report.events)
    assert all(event.replay_order_result_id is None for event in report.events)
    assert all(event.filled_quantity == 0 for event in report.events)
    assert RiskReasonCode.KILL_SWITCH_ACTIVE in report.events[1].risk_reason_codes
    assert RiskReasonCode.DATA_HEALTH_BLOCK in report.events[2].risk_reason_codes


def test_gateway_contracts_reject_inconsistent_blocked_placement_and_bad_ids() -> None:
    rejected = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(quantity=Decimal("3"), order_id="ORDER:S10:BAD")),
        policy=default_policy(),
    )
    blocked_report = run_paper_gateway_replay(
        bars=(bar(0), bar(1)),
        risk_events=(rejected,),
        run_id="GATEWAY:S10:PAPER-BLOCKED-BAD",
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )
    blocked_event = blocked_report.events[0]

    with pytest.raises(ValidationError, match="blocked risk events"):
        ExecutionGatewayLifecycleEvent(
            **blocked_event.model_dump(exclude={"gateway_order_id"}),
            gateway_order_id="GATEWAYORDER:BYPASS",
        )

    approved = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(order_id="ORDER:S10:BAD-ID")),
        policy=default_policy(),
    )
    approved_report = run_paper_gateway_replay(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(approved,),
        run_id="GATEWAY:S10:PAPER-BAD-ID",
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )
    approved_event = approved_report.events[0]

    with pytest.raises(ValidationError, match="gateway_event_id"):
        ExecutionGatewayLifecycleEvent(
            **approved_event.model_dump(exclude={"gateway_event_id"}),
            gateway_event_id="GATEWAYEVENT:BROKEN",
        )
    with pytest.raises(ValidationError, match="gateway_report_hash"):
        ExecutionGatewayReport(
            **approved_report.model_dump(exclude={"gateway_report_hash"}),
            gateway_report_hash="1" * 64,
        )


def _assert_successful_gateway_report(
    report: ExecutionGatewayReport,
    *,
    gateway_kind: ExecutionGatewayKind,
    fill_mode: ExecutionFillMode,
    expected_requirements: tuple[str, ...],
) -> None:
    assert report.gateway_kind is gateway_kind
    assert report.fill_mode is fill_mode
    assert report.requirement_ids == expected_requirements
    assert report.source_risk_gated_replay_result_id.startswith("RISKGATEDREPLAY:")
    assert report.source_replay_report_id is not None
    assert report.source_replay_report_hash is not None
    assert len(report.events) == 1
    event = report.events[0]
    assert event.gateway_kind is report.gateway_kind
    assert event.fill_mode is report.fill_mode
    assert event.requirement_ids == report.requirement_ids
    assert event.risk_decision is RiskDecisionStatus.APPROVED
    assert event.status is ExecutionGatewayOrderStatus.FILLED
    assert event.replay_status is ReplayFillStatus.FILLED
    assert event.gateway_order_id is not None
    assert event.replay_order_result_id is not None
    assert event.fill_event_close_ts == bar(1).close_ts
    assert event.filled_quantity == Decimal("1")
    assert event.remaining_quantity == Decimal("0")


def _stale_data_health_signal() -> DataHealthSignal:
    return DataHealthSignal(
        signal_id="DATAHEALTH:S10:STALE",
        status=DataHealthStatus.BLOCKED,
        reason_codes=(DataHealthReasonCode.CRITICAL_FRESHNESS_STALE,),
        blocks_trading=True,
        blocked_instrument_id="COINBASE_SPOT:BTC-USD",
        source_health_event_id="STREAMHEALTH:S10:STALE",
        source_health_status=StreamHealthStatus.DEGRADED,
        source_scope=StreamHealthScope(
            subscription_id="STREAM:S10:BTCUSD",
            source_id="SOURCE:S10:FIXTURE",
            venue_id="COINBASE_SPOT",
            channel=StreamChannel.TRADES,
            instrument_id="COINBASE_SPOT:BTC-USD",
        ),
        source_checks=(StreamHealthCheck.FRESHNESS,),
        source_metric_names=(StreamHealthMetricName.FRESHNESS_AGE_SECONDS,),
        evaluation_ts=START + timedelta(minutes=1, seconds=1),
    )
