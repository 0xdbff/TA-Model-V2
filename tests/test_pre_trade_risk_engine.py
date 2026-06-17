"""Evidence for S9 independent pre-trade risk engine behavior."""

from __future__ import annotations

from decimal import Decimal

from risk_test_helpers import default_policy, intent, risk_request
from ta_model.contracts.risk import (
    KillSwitchState,
    LiquidityRiskTelemetry,
    LossRiskTelemetry,
    MarketRiskTelemetry,
    RiskDecisionStatus,
    RiskLimitStatus,
    RiskReasonCode,
)
from ta_model.contracts.simulation import OrderSide
from ta_model.risk.engine import evaluate_pre_trade_risk


def test_approved_spot_order_records_independent_risk_approval() -> None:
    event = evaluate_pre_trade_risk(request=risk_request(), policy=default_policy())

    assert event.final_decision is RiskDecisionStatus.APPROVED
    assert event.approved_order_intent == event.request.order_intent
    assert all(
        evaluation.status is not RiskLimitStatus.HARD_BREACH
        for evaluation in event.limit_evaluations
    )


def test_hard_order_notional_breach_rejects_before_any_gateway_path() -> None:
    request = risk_request(order_intent=intent(quantity=Decimal("3")))

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    order_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "order.max_notional"
    )
    assert event.final_decision is RiskDecisionStatus.REJECTED
    assert event.approved_order_intent is None
    assert order_limit.status is RiskLimitStatus.HARD_BREACH
    assert order_limit.reason_code is RiskReasonCode.ORDER_MAX_NOTIONAL_HARD
    assert order_limit.current_value == Decimal("300")
    assert order_limit.hard_threshold == Decimal("250.000")


def test_soft_order_notional_breach_caps_buy_intent_before_approval() -> None:
    request = risk_request(order_intent=intent(quantity=Decimal("1.5")))

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    order_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "order.max_notional"
    )
    assert event.final_decision is RiskDecisionStatus.APPROVED_AFTER_CAP
    assert event.approved_order_intent is not None
    assert event.approved_order_intent.quantity == Decimal("1.0")
    assert event.request.order_intent.quantity == Decimal("1.5")
    assert order_limit.status is RiskLimitStatus.SOFT_BREACH
    assert order_limit.reason_code is RiskReasonCode.ORDER_MAX_NOTIONAL_SOFT
    assert order_limit.current_value == Decimal("150.0")
    assert order_limit.capped_value == Decimal("100.00")


def test_soft_exposure_cap_at_existing_limit_becomes_no_trade_without_approved_intent() -> None:
    request = risk_request(
        current_instrument_exposure=Decimal("1500"),
        order_intent=intent(quantity=Decimal("1"), order_id="ORDER:S9:SOFT-NO-TRADE"),
    )

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    exposure_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "position.instrument_exposure"
    )
    assert event.final_decision is RiskDecisionStatus.NO_TRADE
    assert event.approved_order_intent is None
    assert exposure_limit.status is RiskLimitStatus.SOFT_BREACH
    assert exposure_limit.reason_code is RiskReasonCode.POSITION_INSTRUMENT_EXPOSURE_SOFT
    assert exposure_limit.capped_value == Decimal("1500.00")


def test_soft_liquidity_participation_breach_caps_buy_intent_before_approval() -> None:
    request = risk_request(
        liquidity_risk=LiquidityRiskTelemetry(
            rolling_24h_quote_volume_notional=Decimal("15000")
        ),
        order_intent=intent(order_id="ORDER:S9:SOFT-LIQUIDITY-CAP"),
    )

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    liquidity_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "liquidity.participation"
    )
    assert event.final_decision is RiskDecisionStatus.APPROVED_AFTER_CAP
    assert event.approved_order_intent is not None
    assert event.approved_order_intent.quantity == Decimal("0.75000")
    assert liquidity_limit.status is RiskLimitStatus.SOFT_BREACH
    assert liquidity_limit.reason_code is RiskReasonCode.LIQUIDITY_PARTICIPATION_SOFT
    assert liquidity_limit.capped_value == Decimal("75.000")


def test_soft_daily_account_loss_requires_no_trade_without_approved_intent() -> None:
    request = risk_request(
        loss_risk=LossRiskTelemetry(daily_account_pnl=Decimal("-150")),
        order_intent=intent(order_id="ORDER:S9:SOFT-DAILY-LOSS"),
    )

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    loss_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "loss.daily_account"
    )
    assert event.final_decision is RiskDecisionStatus.NO_TRADE
    assert event.approved_order_intent is None
    assert loss_limit.status is RiskLimitStatus.SOFT_BREACH
    assert loss_limit.reason_code is RiskReasonCode.DAILY_ACCOUNT_LOSS_SOFT


def test_soft_drawdown_requires_no_trade_without_approved_intent() -> None:
    request = risk_request(
        loss_risk=LossRiskTelemetry(max_drawdown_pct=Decimal("0.06")),
        order_intent=intent(order_id="ORDER:S9:SOFT-DRAWDOWN"),
    )

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    drawdown_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "loss.max_drawdown"
    )
    assert event.final_decision is RiskDecisionStatus.NO_TRADE
    assert event.approved_order_intent is None
    assert drawdown_limit.status is RiskLimitStatus.SOFT_BREACH
    assert drawdown_limit.reason_code is RiskReasonCode.MAX_DRAWDOWN_SOFT


def test_soft_volatility_requires_no_trade_without_approved_intent() -> None:
    request = risk_request(
        market_risk=MarketRiskTelemetry(volatility_envelope_multiplier=Decimal("2.5")),
        order_intent=intent(order_id="ORDER:S9:SOFT-VOLATILITY"),
    )

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    volatility_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "market.volatility"
    )
    assert event.final_decision is RiskDecisionStatus.NO_TRADE
    assert event.approved_order_intent is None
    assert volatility_limit.status is RiskLimitStatus.SOFT_BREACH
    assert volatility_limit.reason_code is RiskReasonCode.MARKET_VOLATILITY_SOFT


def test_soft_daily_account_loss_allows_risk_decreasing_sell() -> None:
    request = risk_request(
        order_intent=intent(
            side=OrderSide.SELL,
            quantity=Decimal("0.5"),
            order_id="ORDER:S9:SOFT-LOSS-REDUCE",
        ),
        current_position_quantity=Decimal("1"),
        current_instrument_exposure=Decimal("100"),
        current_strategy_exposure=Decimal("100"),
        current_total_spot_exposure=Decimal("100"),
        loss_risk=LossRiskTelemetry(daily_account_pnl=Decimal("-150")),
    )

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    assert event.final_decision is RiskDecisionStatus.APPROVED
    assert event.approved_order_intent == request.order_intent
    assert event.order_effect.risk_increasing is False
    assert RiskReasonCode.DAILY_ACCOUNT_LOSS_SOFT in event.reason_codes


def test_active_pause_new_orders_kill_switch_rejects_risk_increasing_orders() -> None:
    request = risk_request(kill_state=KillSwitchState.PAUSE_NEW_ORDERS)

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    kill_limit = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "kill_switch.active_state"
    )
    assert event.final_decision is RiskDecisionStatus.REJECTED
    assert event.active_kill_state is KillSwitchState.PAUSE_NEW_ORDERS
    assert kill_limit.status is RiskLimitStatus.HARD_BREACH
    assert kill_limit.reason_code is RiskReasonCode.KILL_SWITCH_ACTIVE


def test_oversell_is_blocked_as_no_short_control() -> None:
    sell_intent = intent(side=OrderSide.SELL, quantity=Decimal("2"), order_id="ORDER:S9:SELL")
    request = risk_request(
        order_intent=sell_intent,
        current_position_quantity=Decimal("1"),
        current_instrument_exposure=Decimal("100"),
        current_total_spot_exposure=Decimal("100"),
        current_strategy_exposure=Decimal("100"),
    )

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    no_short = next(
        evaluation
        for evaluation in event.limit_evaluations
        if evaluation.limit_id == "position.no_short_or_oversell"
    )
    assert event.final_decision is RiskDecisionStatus.REJECTED
    assert event.order_effect.resulting_position_quantity == Decimal("-1")
    assert no_short.status is RiskLimitStatus.HARD_BREACH
    assert no_short.reason_code is RiskReasonCode.NO_SHORT_OR_OVERSELL


def test_unknown_kill_switch_state_fails_closed() -> None:
    request = risk_request(kill_state=KillSwitchState.UNKNOWN_FAIL_CLOSED)

    event = evaluate_pre_trade_risk(request=request, policy=default_policy())

    assert event.final_decision is RiskDecisionStatus.REJECTED
    assert RiskReasonCode.UNKNOWN_KILL_STATE in event.reason_codes
    assert RiskReasonCode.REQUIRED_STATE_MISSING in event.reason_codes
