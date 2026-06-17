"""S9-002 forced-breach matrix using the real independent risk engine.

Traceability:
- FR-010: forced-breach tests block unsafe orders 100% of the time.
- NFR-004: rejected risk events do not produce a replay/gateway intent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from risk_test_helpers import (
    INSTRUMENT_ID,
    START,
    VENUE_ID,
    account_state,
    bar,
    default_policy,
    intent,
    load_snapshot,
    risk_request,
)
from ta_model.contracts.instrument_master import (
    AccountStatus,
    InstrumentMasterSnapshot,
    InstrumentType,
    VenueStatus,
)
from ta_model.contracts.risk import (
    EngineLatencyTelemetry,
    ExecutionRejectBurstWindow,
    KillSwitchState,
    LiquidityRiskTelemetry,
    LossRiskTelemetry,
    MarketRiskTelemetry,
    ModelRiskTelemetry,
    OrderIdempotencyState,
    OrderThrottleScopeType,
    OrderThrottleWindow,
    PriceRiskTelemetry,
    RiskCheckRequest,
    RiskDecisionStatus,
    RiskLimitStatus,
    RiskReasonCode,
    TcaRiskTelemetry,
    build_order_intent_hash,
    make_order_idempotency_record,
)
from ta_model.contracts.simulation import OrderSide
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
from ta_model.risk.engine import evaluate_pre_trade_risk
from ta_model.risk.replay import replay_risk_approved_market_orders


@dataclass(frozen=True)
class ForcedBreachCase:
    case_id: str
    limit_id: str
    reason_code: RiskReasonCode
    request_factory: Callable[[], RiskCheckRequest]


def _forced_breach_cases() -> tuple[ForcedBreachCase, ...]:
    return (
        ForcedBreachCase(
            "product-scope-outside-mvp",
            "scope.product_mvp",
            RiskReasonCode.OUTSIDE_MVP_SCOPE,
            lambda: risk_request(
                instrument_master_snapshot=_snapshot_with_instrument_type(
                    InstrumentType.CASH_EQUITY
                )
            ),
        ),
        ForcedBreachCase(
            "required-state-account-read-only",
            "config.required_state",
            RiskReasonCode.REQUIRED_STATE_MISSING,
            lambda: risk_request(
                instrument_master_snapshot=_snapshot_with_account_status(AccountStatus.READ_ONLY)
            ),
        ),
        ForcedBreachCase(
            "kill-switch-pause-new-orders",
            "kill_switch.active_state",
            RiskReasonCode.KILL_SWITCH_ACTIVE,
            lambda: risk_request(kill_state=KillSwitchState.PAUSE_NEW_ORDERS),
        ),
        ForcedBreachCase(
            "order-notional-hard",
            "order.max_notional",
            RiskReasonCode.ORDER_MAX_NOTIONAL_HARD,
            lambda: risk_request(
                order_intent=intent(quantity=Decimal("3"), order_id="ORDER:S9:MATRIX-NOTIONAL")
            ),
        ),
        ForcedBreachCase(
            "price-collar-marketable-soft-breach",
            "order.price_collar",
            RiskReasonCode.ORDER_PRICE_COLLAR_HARD,
            lambda: risk_request(price_risk=PriceRiskTelemetry(price_deviation_bps=Decimal("60"))),
        ),
        ForcedBreachCase(
            "price-collar-missing-reference",
            "order.price_collar",
            RiskReasonCode.ORDER_PRICE_COLLAR_HARD,
            lambda: risk_request(
                price_risk=PriceRiskTelemetry(reference_price_available=False)
            ),
        ),
        ForcedBreachCase(
            "instrument-exposure-hard",
            "position.instrument_exposure",
            RiskReasonCode.POSITION_INSTRUMENT_EXPOSURE_HARD,
            lambda: risk_request(
                current_instrument_exposure=Decimal("2490"),
                current_total_spot_exposure=Decimal("2490"),
            ),
        ),
        ForcedBreachCase(
            "strategy-exposure-hard",
            "position.strategy_exposure",
            RiskReasonCode.POSITION_STRATEGY_EXPOSURE_HARD,
            lambda: risk_request(
                current_strategy_exposure=Decimal("2990"),
                current_total_spot_exposure=Decimal("2990"),
            ),
        ),
        ForcedBreachCase(
            "total-spot-exposure-hard",
            "position.total_spot_exposure",
            RiskReasonCode.POSITION_TOTAL_SPOT_EXPOSURE_HARD,
            lambda: risk_request(current_total_spot_exposure=Decimal("5990")),
        ),
        ForcedBreachCase(
            "cash-reserve-hard",
            "position.total_spot_exposure",
            RiskReasonCode.CASH_RESERVE_HARD,
            lambda: risk_request(
                current_cash=Decimal("3100"),
                order_intent=intent(
                    quantity=Decimal("1.5"),
                    order_id="ORDER:S9:MATRIX-CASH-RESERVE",
                ),
            ),
        ),
        ForcedBreachCase(
            "no-short-oversell",
            "position.no_short_or_oversell",
            RiskReasonCode.NO_SHORT_OR_OVERSELL,
            lambda: risk_request(
                order_intent=intent(
                    side=OrderSide.SELL,
                    quantity=Decimal("2"),
                    order_id="ORDER:S9:MATRIX-OVERSELL",
                ),
                current_position_quantity=Decimal("1"),
                current_instrument_exposure=Decimal("100"),
                current_strategy_exposure=Decimal("100"),
                current_total_spot_exposure=Decimal("100"),
            ),
        ),
        ForcedBreachCase(
            "daily-account-loss-hard",
            "loss.daily_account",
            RiskReasonCode.DAILY_ACCOUNT_LOSS_HARD,
            lambda: risk_request(
                loss_risk=LossRiskTelemetry(daily_account_pnl=Decimal("-201"))
            ),
        ),
        ForcedBreachCase(
            "daily-strategy-loss-hard",
            "loss.daily_strategy",
            RiskReasonCode.DAILY_STRATEGY_LOSS_HARD,
            lambda: risk_request(
                loss_risk=LossRiskTelemetry(daily_strategy_pnl=Decimal("-101"))
            ),
        ),
        ForcedBreachCase(
            "max-drawdown-hard",
            "loss.max_drawdown",
            RiskReasonCode.MAX_DRAWDOWN_HARD,
            lambda: risk_request(
                loss_risk=LossRiskTelemetry(max_drawdown_pct=Decimal("0.081"))
            ),
        ),
        ForcedBreachCase(
            "participation-hard-volume",
            "liquidity.participation",
            RiskReasonCode.LIQUIDITY_PARTICIPATION_HARD,
            lambda: risk_request(
                liquidity_risk=LiquidityRiskTelemetry(
                    rolling_24h_quote_volume_notional=Decimal("9000")
                )
            ),
        ),
        ForcedBreachCase(
            "participation-hard-depth-unavailable",
            "liquidity.participation",
            RiskReasonCode.LIQUIDITY_PARTICIPATION_HARD,
            lambda: risk_request(
                liquidity_risk=LiquidityRiskTelemetry(depth_metric_required=True)
            ),
        ),
        ForcedBreachCase(
            "spread-hard-threshold",
            "liquidity.spread",
            RiskReasonCode.LIQUIDITY_SPREAD_HARD,
            lambda: risk_request(
                liquidity_risk=LiquidityRiskTelemetry(current_spread_bps=Decimal("51"))
            ),
        ),
        ForcedBreachCase(
            "spread-hard-missing",
            "liquidity.spread",
            RiskReasonCode.LIQUIDITY_SPREAD_HARD,
            lambda: risk_request(
                liquidity_risk=LiquidityRiskTelemetry(current_spread_bps=None)
            ),
        ),
        ForcedBreachCase(
            "volatility-hard-threshold",
            "market.volatility",
            RiskReasonCode.MARKET_VOLATILITY_HARD,
            lambda: risk_request(
                market_risk=MarketRiskTelemetry(volatility_envelope_multiplier=Decimal("3.1"))
            ),
        ),
        ForcedBreachCase(
            "data-health-block",
            "data.freshness",
            RiskReasonCode.DATA_HEALTH_BLOCK,
            lambda: risk_request(data_health_signals=(_blocking_data_health_signal(),)),
        ),
        ForcedBreachCase(
            "venue-halted",
            "venue.status",
            RiskReasonCode.VENUE_STATUS_HARD,
            lambda: risk_request(
                instrument_master_snapshot=_snapshot_with_venue_status(VenueStatus.HALTED)
            ),
        ),
        ForcedBreachCase(
            "order-throttle-hard",
            "execution.order_throttle",
            RiskReasonCode.ORDER_THROTTLE_HARD,
            lambda: risk_request(throttle_windows=(_hard_throttle_window(),)),
        ),
        ForcedBreachCase(
            "duplicate-idempotency-unresolved",
            "execution.duplicate_idempotency",
            RiskReasonCode.DUPLICATE_IDEMPOTENCY,
            lambda: _duplicate_idempotency_request(),
        ),
        ForcedBreachCase(
            "reject-burst-hard",
            "execution.reject_burst",
            RiskReasonCode.REJECT_BURST_HARD,
            lambda: risk_request(reject_burst_windows=(_hard_reject_burst_window(),)),
        ),
        ForcedBreachCase(
            "engine-latency-budget-exceeded",
            "engine.latency",
            RiskReasonCode.ENGINE_LATENCY_HARD,
            lambda: risk_request(risk_check_ts=START + timedelta(minutes=3)),
        ),
        ForcedBreachCase(
            "engine-latency-event-time-invalid",
            "engine.latency",
            RiskReasonCode.ENGINE_LATENCY_HARD,
            lambda: risk_request(
                engine_latency=EngineLatencyTelemetry(event_time_validity_proven=False)
            ),
        ),
        ForcedBreachCase(
            "model-calibration-hard",
            "model.drift_or_calibration",
            RiskReasonCode.MODEL_DRIFT_OR_CALIBRATION_HARD,
            lambda: risk_request(model_risk=ModelRiskTelemetry(calibrated_outputs=False)),
        ),
        ForcedBreachCase(
            "tca-hard-threshold",
            "tca.cost_slippage",
            RiskReasonCode.TCA_COST_SLIPPAGE_HARD,
            lambda: risk_request(
                tca_risk=TcaRiskTelemetry(cost_slippage_multiplier=Decimal("3.1"))
            ),
        ),
        ForcedBreachCase(
            "tca-unavailable",
            "tca.cost_slippage",
            RiskReasonCode.TCA_COST_SLIPPAGE_HARD,
            lambda: risk_request(tca_risk=TcaRiskTelemetry(tca_available=False)),
        ),
    )


def test_forced_breach_matrix_covers_required_s0_003_hard_limits() -> None:
    actual = tuple(
        (case.case_id, case.limit_id, case.reason_code) for case in _forced_breach_cases()
    )
    expected = (
        ("product-scope-outside-mvp", "scope.product_mvp", RiskReasonCode.OUTSIDE_MVP_SCOPE),
        (
            "required-state-account-read-only",
            "config.required_state",
            RiskReasonCode.REQUIRED_STATE_MISSING,
        ),
        (
            "kill-switch-pause-new-orders",
            "kill_switch.active_state",
            RiskReasonCode.KILL_SWITCH_ACTIVE,
        ),
        ("order-notional-hard", "order.max_notional", RiskReasonCode.ORDER_MAX_NOTIONAL_HARD),
        (
            "price-collar-marketable-soft-breach",
            "order.price_collar",
            RiskReasonCode.ORDER_PRICE_COLLAR_HARD,
        ),
        (
            "price-collar-missing-reference",
            "order.price_collar",
            RiskReasonCode.ORDER_PRICE_COLLAR_HARD,
        ),
        (
            "instrument-exposure-hard",
            "position.instrument_exposure",
            RiskReasonCode.POSITION_INSTRUMENT_EXPOSURE_HARD,
        ),
        (
            "strategy-exposure-hard",
            "position.strategy_exposure",
            RiskReasonCode.POSITION_STRATEGY_EXPOSURE_HARD,
        ),
        (
            "total-spot-exposure-hard",
            "position.total_spot_exposure",
            RiskReasonCode.POSITION_TOTAL_SPOT_EXPOSURE_HARD,
        ),
        ("cash-reserve-hard", "position.total_spot_exposure", RiskReasonCode.CASH_RESERVE_HARD),
        (
            "no-short-oversell",
            "position.no_short_or_oversell",
            RiskReasonCode.NO_SHORT_OR_OVERSELL,
        ),
        ("daily-account-loss-hard", "loss.daily_account", RiskReasonCode.DAILY_ACCOUNT_LOSS_HARD),
        (
            "daily-strategy-loss-hard",
            "loss.daily_strategy",
            RiskReasonCode.DAILY_STRATEGY_LOSS_HARD,
        ),
        ("max-drawdown-hard", "loss.max_drawdown", RiskReasonCode.MAX_DRAWDOWN_HARD),
        (
            "participation-hard-volume",
            "liquidity.participation",
            RiskReasonCode.LIQUIDITY_PARTICIPATION_HARD,
        ),
        (
            "participation-hard-depth-unavailable",
            "liquidity.participation",
            RiskReasonCode.LIQUIDITY_PARTICIPATION_HARD,
        ),
        ("spread-hard-threshold", "liquidity.spread", RiskReasonCode.LIQUIDITY_SPREAD_HARD),
        ("spread-hard-missing", "liquidity.spread", RiskReasonCode.LIQUIDITY_SPREAD_HARD),
        (
            "volatility-hard-threshold",
            "market.volatility",
            RiskReasonCode.MARKET_VOLATILITY_HARD,
        ),
        ("data-health-block", "data.freshness", RiskReasonCode.DATA_HEALTH_BLOCK),
        ("venue-halted", "venue.status", RiskReasonCode.VENUE_STATUS_HARD),
        ("order-throttle-hard", "execution.order_throttle", RiskReasonCode.ORDER_THROTTLE_HARD),
        (
            "duplicate-idempotency-unresolved",
            "execution.duplicate_idempotency",
            RiskReasonCode.DUPLICATE_IDEMPOTENCY,
        ),
        ("reject-burst-hard", "execution.reject_burst", RiskReasonCode.REJECT_BURST_HARD),
        ("engine-latency-budget-exceeded", "engine.latency", RiskReasonCode.ENGINE_LATENCY_HARD),
        (
            "engine-latency-event-time-invalid",
            "engine.latency",
            RiskReasonCode.ENGINE_LATENCY_HARD,
        ),
        (
            "model-calibration-hard",
            "model.drift_or_calibration",
            RiskReasonCode.MODEL_DRIFT_OR_CALIBRATION_HARD,
        ),
        ("tca-hard-threshold", "tca.cost_slippage", RiskReasonCode.TCA_COST_SLIPPAGE_HARD),
        ("tca-unavailable", "tca.cost_slippage", RiskReasonCode.TCA_COST_SLIPPAGE_HARD),
    )
    assert actual == expected


@pytest.mark.parametrize(
    "case",
    _forced_breach_cases(),
    ids=lambda case: case.case_id,
)
def test_each_forced_breach_rejects_without_approved_intent(case: ForcedBreachCase) -> None:
    event = evaluate_pre_trade_risk(request=case.request_factory(), policy=default_policy())

    limit = next(
        evaluation for evaluation in event.limit_evaluations if evaluation.limit_id == case.limit_id
    )
    assert event.final_decision is RiskDecisionStatus.REJECTED
    assert event.approved_order_intent is None
    assert limit.status is RiskLimitStatus.HARD_BREACH
    assert limit.reason_code is case.reason_code
    assert case.reason_code in event.reason_codes


def test_forced_breach_matrix_is_not_forwarded_through_risk_gated_replay() -> None:
    events = tuple(
        evaluate_pre_trade_risk(request=case.request_factory(), policy=default_policy())
        for case in _forced_breach_cases()
    )

    result = replay_risk_approved_market_orders(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=events,
        run_id="REPLAY:S9:FORCED-BREACH-MATRIX",
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
    )

    assert all(event.approved_order_intent is None for event in events)
    assert result.risk_check_ids == tuple(event.risk_check_id for event in events)
    assert result.approved_risk_check_ids == ()
    assert result.blocked_risk_check_ids == tuple(event.risk_check_id for event in events)
    assert result.replay_report is None


def _snapshot_with_instrument_type(instrument_type: InstrumentType) -> InstrumentMasterSnapshot:
    payload = _snapshot_payload()
    instruments = cast("list[dict[str, Any]]", payload["instruments"])
    instruments[0]["instrument_type"] = instrument_type.value
    return InstrumentMasterSnapshot.model_validate(payload)


def _snapshot_with_account_status(account_status: AccountStatus) -> InstrumentMasterSnapshot:
    payload = _snapshot_payload()
    accounts = cast("list[dict[str, Any]]", payload["accounts"])
    accounts[0]["status"] = account_status.value
    return InstrumentMasterSnapshot.model_validate(payload)


def _snapshot_with_venue_status(venue_status: VenueStatus) -> InstrumentMasterSnapshot:
    payload = _snapshot_payload()
    venues = cast("list[dict[str, Any]]", payload["venues"])
    venues[0]["status"] = venue_status.value
    return InstrumentMasterSnapshot.model_validate(payload)


def _snapshot_payload() -> dict[str, Any]:
    return load_snapshot().model_dump(mode="json")


def _blocking_data_health_signal() -> DataHealthSignal:
    return DataHealthSignal(
        signal_id="DATAHEALTH:S9:FORCED-FRESHNESS",
        status=DataHealthStatus.BLOCKED,
        reason_codes=(DataHealthReasonCode.CRITICAL_FRESHNESS_STALE,),
        blocks_trading=True,
        blocked_instrument_id=INSTRUMENT_ID,
        source_health_event_id="STREAMHEALTH:S9:STALE",
        source_health_status=StreamHealthStatus.DEGRADED,
        source_scope=StreamHealthScope(
            subscription_id="SUB:S9:FORCED",
            source_id="SOURCE:S9",
            venue_id=VENUE_ID,
            channel=StreamChannel.TRADES,
            instrument_id=INSTRUMENT_ID,
        ),
        source_checks=(StreamHealthCheck.FRESHNESS,),
        source_metric_names=(StreamHealthMetricName.FRESHNESS_AGE_SECONDS,),
        evaluation_ts=START + timedelta(minutes=1),
    )


def _hard_throttle_window() -> OrderThrottleWindow:
    return OrderThrottleWindow(
        scope_type=OrderThrottleScopeType.STRATEGY_INSTRUMENT,
        scope_id="STRATEGY:S9:BTC-USD",
        observed_intent_count=10,
        soft_limit=5,
        hard_limit=10,
        window_started_at=START,
        window_seconds=60,
    )


def _duplicate_idempotency_request() -> RiskCheckRequest:
    duplicate_intent = intent(order_id="ORDER:S9:MATRIX-DUPLICATE")
    duplicate_record = make_order_idempotency_record(
        idempotency_key=duplicate_intent.client_order_id,
        client_order_id=duplicate_intent.client_order_id,
        trace_id=duplicate_intent.trace_id,
        order_intent_hash=build_order_intent_hash(order_intent=duplicate_intent),
        state=OrderIdempotencyState.PLACED,
        first_seen_at=START,
        updated_at=START,
    )
    return risk_request(order_intent=duplicate_intent, idempotency_records=(duplicate_record,))


def _hard_reject_burst_window() -> ExecutionRejectBurstWindow:
    return ExecutionRejectBurstWindow(
        scope_id="STRATEGY:S9:COINBASE",
        observed_reject_count=5,
        window_started_at=START,
        window_seconds=300,
    )
