"""Evidence for S9-004 duplicate/idempotency and order-throttle risk checks."""

from __future__ import annotations

from decimal import Decimal

from risk_test_helpers import START, default_policy, intent, risk_request
from ta_model.contracts.risk import (
    OrderIdempotencyState,
    OrderThrottleScopeType,
    OrderThrottleWindow,
    RiskDecisionStatus,
    RiskLimitStatus,
    RiskReasonCode,
    build_order_intent_hash,
    make_order_idempotency_record,
)
from ta_model.risk.engine import evaluate_pre_trade_risk


def test_unresolved_duplicate_idempotency_key_blocks_duplicate_exposure() -> None:
    order_intent = intent(order_id="ORDER:S9:DUP")
    duplicate = make_order_idempotency_record(
        idempotency_key=order_intent.client_order_id,
        client_order_id=order_intent.client_order_id,
        trace_id=order_intent.trace_id,
        order_intent_hash=build_order_intent_hash(order_intent=order_intent),
        state=OrderIdempotencyState.PLACED,
        first_seen_at=START,
        updated_at=START,
    )
    request = risk_request(order_intent=order_intent, idempotency_records=(duplicate,))

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    duplicate_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "execution.duplicate_idempotency"
    )
    assert event.final_decision is RiskDecisionStatus.REJECTED
    assert event.approved_order_intent is None
    assert duplicate_limit.status is RiskLimitStatus.HARD_BREACH
    assert duplicate_limit.reason_code is RiskReasonCode.DUPLICATE_IDEMPOTENCY


def test_reconciled_idempotency_record_does_not_block_new_check() -> None:
    order_intent = intent(order_id="ORDER:S9:RECONCILED")
    reconciled = make_order_idempotency_record(
        idempotency_key=order_intent.client_order_id,
        client_order_id=order_intent.client_order_id,
        trace_id=order_intent.trace_id,
        order_intent_hash=build_order_intent_hash(order_intent=order_intent),
        state=OrderIdempotencyState.RECONCILED,
        first_seen_at=START,
        updated_at=START,
    )
    request = risk_request(order_intent=order_intent, idempotency_records=(reconciled,))

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    duplicate_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "execution.duplicate_idempotency"
    )
    assert event.final_decision is RiskDecisionStatus.APPROVED
    assert duplicate_limit.status is RiskLimitStatus.PASS


def test_hard_order_throttle_breach_rejects_new_intent() -> None:
    throttle = OrderThrottleWindow(
        scope_type=OrderThrottleScopeType.STRATEGY_INSTRUMENT,
        scope_id="STRATEGY:S9:BTC-USD",
        observed_intent_count=10,
        soft_limit=5,
        hard_limit=10,
        window_started_at=START,
        window_seconds=60,
    )
    request = risk_request(throttle_windows=(throttle,))

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    throttle_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "execution.order_throttle"
    )
    assert event.final_decision is RiskDecisionStatus.REJECTED
    assert throttle_limit.status is RiskLimitStatus.HARD_BREACH
    assert throttle_limit.reason_code is RiskReasonCode.ORDER_THROTTLE_HARD
    assert throttle_limit.current_value == Decimal("11")
    assert throttle_limit.hard_threshold == Decimal("10")


def test_soft_order_throttle_breach_no_trades_without_safe_cap() -> None:
    throttle = OrderThrottleWindow(
        scope_type=OrderThrottleScopeType.STRATEGY_INSTRUMENT,
        scope_id="STRATEGY:S9:BTC-USD",
        observed_intent_count=5,
        soft_limit=5,
        hard_limit=10,
        window_started_at=START,
        window_seconds=60,
    )
    request = risk_request(throttle_windows=(throttle,))

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    throttle_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "execution.order_throttle"
    )
    assert event.final_decision is RiskDecisionStatus.NO_TRADE
    assert event.approved_order_intent is None
    assert throttle_limit.status is RiskLimitStatus.SOFT_BREACH
    assert throttle_limit.reason_code is RiskReasonCode.ORDER_THROTTLE_SOFT
