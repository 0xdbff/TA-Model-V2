"""Evidence that S9 risk-gated replay forwards only approved intents to S6 replay."""

from __future__ import annotations

from decimal import Decimal

from risk_test_helpers import (
    START,
    account_state,
    bar,
    default_policy,
    intent,
    load_snapshot,
    risk_request,
)
from ta_model.contracts.risk import (
    OrderIdempotencyState,
    RiskDecisionStatus,
    build_order_intent_hash,
    make_order_idempotency_record,
)
from ta_model.contracts.simulation import ReplayFillStatus, make_execution_cost_model
from ta_model.risk.engine import evaluate_pre_trade_risk
from ta_model.risk.replay import replay_risk_approved_market_orders


def test_rejected_risk_event_does_not_create_replay_report_or_gateway_result() -> None:
    rejected = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(quantity=Decimal("3"), order_id="ORDER:S9:BLOCK")),
        policy=default_policy(),
    )

    result = replay_risk_approved_market_orders(
        bars=(bar(0), bar(1)),
        risk_events=(rejected,),
        run_id="REPLAY:S9:REJECTED-ONLY",
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )

    assert rejected.final_decision is RiskDecisionStatus.REJECTED
    assert result.approved_risk_check_ids == ()
    assert result.blocked_risk_check_ids == (rejected.risk_check_id,)
    assert result.replay_report is None


def test_approved_risk_event_uses_real_s6_replay_path() -> None:
    approved = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(order_id="ORDER:S9:APPROVED")),
        policy=default_policy(),
    )
    model = make_execution_cost_model(
        taker_fee_rate=Decimal("0.001"), spread_bps=Decimal("0"), slippage_bps=Decimal("0")
    )

    result = replay_risk_approved_market_orders(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(approved,),
        run_id="REPLAY:S9:APPROVED",
        execution_cost_model=model,
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )

    assert approved.final_decision is RiskDecisionStatus.APPROVED
    assert result.approved_risk_check_ids == (approved.risk_check_id,)
    assert result.replay_report is not None
    replay_result = result.replay_report.results[0]
    assert replay_result.client_order_id == "ORDER:S9:APPROVED"
    assert replay_result.status is ReplayFillStatus.FILLED
    assert replay_result.fill_event_close_ts == bar(1).close_ts


def test_soft_capped_risk_event_replays_reduced_quantity() -> None:
    capped = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(quantity=Decimal("1.5"), order_id="ORDER:S9:CAP")),
        policy=default_policy(),
    )

    result = replay_risk_approved_market_orders(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(capped,),
        run_id="REPLAY:S9:CAPPED",
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )

    assert capped.final_decision is RiskDecisionStatus.APPROVED_AFTER_CAP
    assert capped.approved_order_intent is not None
    assert capped.approved_order_intent.quantity == Decimal("1.0")
    assert result.replay_report is not None
    replay_result = result.replay_report.results[0]
    assert replay_result.client_order_id == "ORDER:S9:CAP"
    assert replay_result.quantity == Decimal("1.0")
    assert replay_result.filled_quantity == Decimal("1.0")
    assert replay_result.status is ReplayFillStatus.FILLED


def test_mixed_risk_events_forward_only_approved_intents() -> None:
    rejected = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(quantity=Decimal("3"), order_id="ORDER:S9:BLOCK")),
        policy=default_policy(),
    )
    approved = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(order_id="ORDER:S9:APPROVED")),
        policy=default_policy(),
    )

    result = replay_risk_approved_market_orders(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(rejected, approved),
        run_id="REPLAY:S9:MIXED",
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )

    assert result.approved_risk_check_ids == (approved.risk_check_id,)
    assert result.blocked_risk_check_ids == (rejected.risk_check_id,)
    assert result.replay_report is not None
    assert tuple(item.client_order_id for item in result.replay_report.results) == (
        "ORDER:S9:APPROVED",
    )


def test_duplicate_idempotency_rejection_is_not_forwarded_to_replay() -> None:
    duplicate_intent = intent(order_id="ORDER:S9:DUP-REPLAY")
    duplicate_record = make_order_idempotency_record(
        idempotency_key=duplicate_intent.client_order_id,
        client_order_id=duplicate_intent.client_order_id,
        trace_id=duplicate_intent.trace_id,
        order_intent_hash=build_order_intent_hash(order_intent=duplicate_intent),
        state=OrderIdempotencyState.PLACED,
        first_seen_at=START,
        updated_at=START,
    )
    duplicate_rejected = evaluate_pre_trade_risk(
        request=risk_request(
            order_intent=duplicate_intent,
            idempotency_records=(duplicate_record,),
        ),
        policy=default_policy(),
    )

    result = replay_risk_approved_market_orders(
        bars=(bar(0), bar(1)),
        risk_events=(duplicate_rejected,),
        run_id="REPLAY:S9:DUPLICATE-BLOCKED",
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )

    assert duplicate_rejected.final_decision is RiskDecisionStatus.REJECTED
    assert result.approved_risk_check_ids == ()
    assert result.blocked_risk_check_ids == (duplicate_rejected.risk_check_id,)
    assert result.replay_report is None
