"""Pure independent pre-trade risk engine for S9.

The engine returns deterministic risk evidence only. It never calls simulator,
paper, or future live gateways; routing is handled by the risk-gated replay seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from ta_model.contracts.instrument_master import (
    Account,
    AccountStatus,
    AccountType,
    Instrument,
    InstrumentConstraint,
    InstrumentMasterSnapshot,
    InstrumentStatus,
    InstrumentType,
    OrderType,
    TradingPermission,
    Venue,
    VenueStatus,
)
from ta_model.contracts.risk import (
    KillSwitchState,
    OrderEffect,
    OrderIdempotencyState,
    RiskCheckEvent,
    RiskCheckRequest,
    RiskDecisionStatus,
    RiskLimitEvaluation,
    RiskLimitStatus,
    RiskPolicy,
    RiskReasonCode,
    build_order_intent_hash,
    make_risk_check_event,
)
from ta_model.contracts.simulation import OrderIntent, OrderSide

_LIMIT_OWNERS: dict[str, str] = {
    "scope.product_mvp": "Product / risk",
    "config.required_state": "Risk / architecture",
    "kill_switch.active_state": "Risk / ops",
    "order.max_notional": "Risk / execution",
    "order.price_collar": "Execution / risk",
    "position.instrument_exposure": "Risk",
    "position.strategy_exposure": "Risk / strategy owner",
    "position.total_spot_exposure": "Risk / product",
    "position.no_short_or_oversell": "Risk / execution",
    "loss.daily_account": "Risk",
    "loss.daily_strategy": "Risk / strategy owner",
    "loss.max_drawdown": "Risk / product",
    "liquidity.participation": "Execution / risk",
    "liquidity.spread": "Execution / risk",
    "market.volatility": "Risk / quant",
    "data.freshness": "Data / risk",
    "venue.status": "Ops / execution",
    "execution.order_throttle": "Execution / ops",
    "execution.duplicate_idempotency": "Execution / risk",
    "execution.reject_burst": "Execution / ops",
    "engine.latency": "Ops / risk",
    "model.drift_or_calibration": "ML / risk",
    "tca.cost_slippage": "Execution / risk",
}

_KILL_STATE_SEVERITY: dict[KillSwitchState, int] = {
    KillSwitchState.CLEAR: 0,
    KillSwitchState.SOFT_LIMITED: 1,
    KillSwitchState.PAUSE_NEW_ORDERS: 2,
    KillSwitchState.REDUCE_ONLY: 3,
    KillSwitchState.CANCEL_ONLY: 4,
    KillSwitchState.HALTED: 5,
    KillSwitchState.UNKNOWN_FAIL_CLOSED: 6,
}

_UNRESOLVED_IDEMPOTENCY_STATES = {
    OrderIdempotencyState.RECEIVED,
    OrderIdempotencyState.ACCEPTED,
    OrderIdempotencyState.PLACED,
    OrderIdempotencyState.UNKNOWN,
}


@dataclass(frozen=True)
class _MetadataView:
    venue: Venue | None
    instrument: Instrument | None
    account: Account | None
    constraint: InstrumentConstraint | None


def evaluate_pre_trade_risk(*, request: RiskCheckRequest, policy: RiskPolicy) -> RiskCheckEvent:
    """Evaluate one order intent against independent hard/soft risk controls.

    The returned event is the only approval artifact accepted by the S9 replay seam.
    Hard breaches always reject. The engine is deterministic and side-effect free.
    """

    metadata = _metadata_view(request)
    order_effect = _build_order_effect(request)
    evaluations = (
        _required_state_evaluation(request=request, metadata=metadata),
        _product_scope_evaluation(metadata=metadata),
        _kill_switch_evaluation(request=request, order_effect=order_effect),
        _venue_status_evaluation(metadata=metadata),
        _price_collar_evaluation(request=request, policy=policy),
        _order_notional_evaluation(
            request=request,
            policy=policy,
            metadata=metadata,
            order_effect=order_effect,
        ),
        _instrument_exposure_evaluation(
            request=request,
            policy=policy,
            metadata=metadata,
            order_effect=order_effect,
        ),
        _strategy_exposure_evaluation(
            request=request,
            policy=policy,
            metadata=metadata,
            order_effect=order_effect,
        ),
        _total_spot_exposure_evaluation(
            request=request,
            policy=policy,
            metadata=metadata,
            order_effect=order_effect,
        ),
        _no_short_or_oversell_evaluation(request=request),
        _daily_account_loss_evaluation(request=request, policy=policy),
        _daily_strategy_loss_evaluation(request=request, policy=policy),
        _max_drawdown_evaluation(request=request, policy=policy),
        _liquidity_participation_evaluation(
            request=request,
            policy=policy,
            order_effect=order_effect,
        ),
        _liquidity_spread_evaluation(request=request, policy=policy),
        _market_volatility_evaluation(request=request, policy=policy),
        _data_freshness_evaluation(request=request),
        _idempotency_evaluation(request=request),
        *_throttle_evaluations(request=request),
        *_reject_burst_evaluations(request=request),
        _engine_latency_evaluation(request=request),
        _model_drift_or_calibration_evaluation(request=request),
        _tca_cost_slippage_evaluation(request=request, policy=policy),
    )

    has_hard_breach = any(
        evaluation.status is RiskLimitStatus.HARD_BREACH for evaluation in evaluations
    )
    if has_hard_breach:
        final_decision = RiskDecisionStatus.REJECTED
        approved_order_intent = None
    else:
        final_decision, approved_order_intent = _approval_after_soft_caps(
            request=request,
            order_effect=order_effect,
            evaluations=evaluations,
        )
    return make_risk_check_event(
        request=request,
        risk_policy=policy,
        order_effect=order_effect,
        limit_evaluations=evaluations,
        final_decision=final_decision,
        approved_order_intent=approved_order_intent,
    )


def _approval_after_soft_caps(
    *,
    request: RiskCheckRequest,
    order_effect: OrderEffect,
    evaluations: tuple[RiskLimitEvaluation, ...],
) -> tuple[RiskDecisionStatus, OrderIntent | None]:
    if request.order_intent.side is not OrderSide.BUY or not order_effect.risk_increasing:
        return RiskDecisionStatus.APPROVED, request.order_intent

    soft_breaches = tuple(
        evaluation
        for evaluation in evaluations
        if evaluation.status is RiskLimitStatus.SOFT_BREACH
    )
    if not soft_breaches:
        return RiskDecisionStatus.APPROVED, request.order_intent

    allowed_incremental_notionals: list[Decimal] = []
    for evaluation in soft_breaches:
        cap = _allowed_incremental_notional(request=request, evaluation=evaluation)
        if cap is None:
            return RiskDecisionStatus.NO_TRADE, None
        allowed_incremental_notionals.append(cap)

    allowed_notional = min(allowed_incremental_notionals)
    if allowed_notional <= 0:
        return RiskDecisionStatus.NO_TRADE, None
    original_notional = request.order_intent.quantity * request.reference_price
    if allowed_notional >= original_notional:
        return RiskDecisionStatus.APPROVED, request.order_intent

    capped_quantity = allowed_notional / request.reference_price
    if capped_quantity <= 0:
        return RiskDecisionStatus.NO_TRADE, None
    return (
        RiskDecisionStatus.APPROVED_AFTER_CAP,
        OrderIntent(
            **request.order_intent.model_dump(exclude={"quantity"}),
            quantity=capped_quantity,
        ),
    )


def _allowed_incremental_notional(
    *, request: RiskCheckRequest, evaluation: RiskLimitEvaluation
) -> Decimal | None:
    if (
        evaluation.status is not RiskLimitStatus.SOFT_BREACH
        or evaluation.capped_value is None
    ):
        return None
    if evaluation.limit_id == "order.max_notional":
        return evaluation.capped_value
    if evaluation.limit_id == "liquidity.participation":
        return evaluation.capped_value
    if evaluation.limit_id == "position.instrument_exposure":
        return evaluation.capped_value - request.current_instrument_exposure_notional
    if evaluation.limit_id == "position.strategy_exposure":
        return evaluation.capped_value - request.current_strategy_exposure_notional
    if (
        evaluation.limit_id == "position.total_spot_exposure"
        and evaluation.reason_code is RiskReasonCode.POSITION_TOTAL_SPOT_EXPOSURE_SOFT
    ):
        return evaluation.capped_value - request.current_total_spot_exposure_notional
    return None


def _metadata_view(request: RiskCheckRequest) -> _MetadataView:
    snapshot = request.instrument_master_snapshot
    intent = request.order_intent
    venue = next((item for item in snapshot.venues if item.venue_id == intent.venue_id), None)
    instrument = next(
        (
            item
            for item in snapshot.instruments
            if item.instrument_id == intent.instrument_id and item.venue_id == intent.venue_id
        ),
        None,
    )
    account = next(
        (
            item
            for item in snapshot.accounts
            if item.account_id == request.account_id and item.venue_id == intent.venue_id
        ),
        None,
    )
    constraint = _active_constraint(snapshot=snapshot, instrument_id=intent.instrument_id)
    return _MetadataView(venue=venue, instrument=instrument, account=account, constraint=constraint)


def _active_constraint(
    *, snapshot: InstrumentMasterSnapshot, instrument_id: str
) -> InstrumentConstraint | None:
    active = tuple(
        constraint
        for constraint in snapshot.instrument_constraints
        if constraint.instrument_id == instrument_id
        and constraint.effective_from <= snapshot.created_at
        and (constraint.effective_to is None or snapshot.created_at < constraint.effective_to)
    )
    return active[0] if len(active) == 1 else None


def _build_order_effect(request: RiskCheckRequest) -> OrderEffect:
    intent = request.order_intent
    proposed_notional = intent.quantity * request.reference_price
    if intent.side is OrderSide.BUY:
        resulting_position_quantity = request.current_instrument_position_quantity + intent.quantity
        resulting_cash = request.current_cash - proposed_notional
        resulting_instrument_exposure = (
            request.current_instrument_exposure_notional + proposed_notional
        )
        resulting_strategy_exposure = request.current_strategy_exposure_notional + proposed_notional
        resulting_total_spot_exposure = (
            request.current_total_spot_exposure_notional + proposed_notional
        )
        risk_increasing = True
    else:
        resulting_position_quantity = request.current_instrument_position_quantity - intent.quantity
        resulting_cash = request.current_cash + proposed_notional
        resulting_instrument_exposure = max(
            Decimal("0"), request.current_instrument_exposure_notional - proposed_notional
        )
        resulting_strategy_exposure = max(
            Decimal("0"), request.current_strategy_exposure_notional - proposed_notional
        )
        resulting_total_spot_exposure = max(
            Decimal("0"), request.current_total_spot_exposure_notional - proposed_notional
        )
        risk_increasing = resulting_position_quantity < 0

    resulting_position_notional = max(
        Decimal("0"), resulting_position_quantity * request.reference_price
    )
    cash_reserve_pct = resulting_cash / request.account_equity
    return OrderEffect(
        side=intent.side,
        quantity=intent.quantity,
        reference_price=request.reference_price,
        proposed_notional=proposed_notional,
        resulting_position_quantity=resulting_position_quantity,
        resulting_position_notional=resulting_position_notional,
        resulting_cash=resulting_cash,
        resulting_instrument_exposure_notional=resulting_instrument_exposure,
        resulting_strategy_exposure_notional=resulting_strategy_exposure,
        resulting_total_spot_exposure_notional=resulting_total_spot_exposure,
        cash_reserve_pct=cash_reserve_pct,
        risk_increasing=risk_increasing,
    )


def _required_state_evaluation(
    *, request: RiskCheckRequest, metadata: _MetadataView
) -> RiskLimitEvaluation:
    state_items = (metadata.venue, metadata.instrument, metadata.account, metadata.constraint)
    state_is_present = all(item is not None for item in state_items)
    required_metadata_is_orderable = (
        metadata.instrument is not None
        and metadata.instrument.status is InstrumentStatus.TRADING
        and OrderType.MARKET in metadata.instrument.supported_order_types
        and metadata.account is not None
        and metadata.account.status is AccountStatus.ACTIVE
        and TradingPermission.PLACE_ORDERS in metadata.account.trading_permissions
    )
    state_is_known = (
        request.kill_switch_snapshot.active_state is not KillSwitchState.UNKNOWN_FAIL_CLOSED
    )
    if state_is_present and required_metadata_is_orderable and state_is_known:
        return _evaluation("config.required_state", Decimal("1"), Decimal("1"), None)
    return _evaluation(
        "config.required_state",
        Decimal("0"),
        Decimal("1"),
        RiskLimitStatus.HARD_BREACH,
        RiskReasonCode.REQUIRED_STATE_MISSING,
    )


def _product_scope_evaluation(*, metadata: _MetadataView) -> RiskLimitEvaluation:
    instrument = metadata.instrument
    account = metadata.account
    in_scope = (
        instrument is not None
        and account is not None
        and instrument.instrument_type is InstrumentType.SPOT
        and instrument.is_derivative is False
        and instrument.margin_allowed is False
        and instrument.short_selling_allowed is False
        and instrument.leverage_allowed is False
        and account.account_type in {AccountType.SIMULATION, AccountType.PAPER}
        and account.live_capital_enabled is False
        and account.margin_enabled is False
        and account.derivatives_enabled is False
        and account.shorting_enabled is False
    )
    if in_scope:
        return _evaluation("scope.product_mvp", Decimal("1"), Decimal("1"), None)
    return _evaluation(
        "scope.product_mvp",
        Decimal("0"),
        Decimal("1"),
        RiskLimitStatus.HARD_BREACH,
        RiskReasonCode.OUTSIDE_MVP_SCOPE,
    )


def _kill_switch_evaluation(
    *, request: RiskCheckRequest, order_effect: OrderEffect
) -> RiskLimitEvaluation:
    state = request.kill_switch_snapshot.active_state
    current_value = Decimal(_KILL_STATE_SEVERITY[state])
    if state is KillSwitchState.UNKNOWN_FAIL_CLOSED:
        return _evaluation(
            "kill_switch.active_state",
            current_value,
            Decimal("0"),
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.UNKNOWN_KILL_STATE,
        )
    if state is KillSwitchState.CLEAR:
        return _evaluation("kill_switch.active_state", current_value, Decimal("0"), None)
    if state is KillSwitchState.SOFT_LIMITED:
        return _evaluation(
            "kill_switch.active_state",
            current_value,
            Decimal("0"),
            RiskLimitStatus.SOFT_BREACH,
            RiskReasonCode.KILL_SWITCH_ACTIVE,
        )
    if state in {KillSwitchState.PAUSE_NEW_ORDERS, KillSwitchState.REDUCE_ONLY}:
        if not order_effect.risk_increasing:
            return _evaluation("kill_switch.active_state", current_value, Decimal("3"), None)
    return _evaluation(
        "kill_switch.active_state",
        current_value,
        Decimal("0"),
        RiskLimitStatus.HARD_BREACH,
        RiskReasonCode.KILL_SWITCH_ACTIVE,
    )


def _venue_status_evaluation(*, metadata: _MetadataView) -> RiskLimitEvaluation:
    venue = metadata.venue
    if venue is not None and venue.status is VenueStatus.ACTIVE:
        return _evaluation("venue.status", Decimal("1"), Decimal("1"), None)
    if venue is not None and venue.status is VenueStatus.DEGRADED:
        return _evaluation(
            "venue.status",
            Decimal("0.5"),
            Decimal("1"),
            RiskLimitStatus.SOFT_BREACH,
            RiskReasonCode.VENUE_STATUS_SOFT,
        )
    return _evaluation(
        "venue.status",
        Decimal("0"),
        Decimal("1"),
        RiskLimitStatus.HARD_BREACH,
        RiskReasonCode.VENUE_STATUS_HARD,
    )


def _price_collar_evaluation(
    *, request: RiskCheckRequest, policy: RiskPolicy
) -> RiskLimitEvaluation:
    telemetry = request.price_risk
    hard_threshold = policy.price_collar_hard_bps
    soft_threshold = policy.price_collar_soft_bps
    current_value = telemetry.price_deviation_bps

    if not telemetry.reference_price_available:
        return _evaluation(
            "order.price_collar",
            current_value,
            hard_threshold,
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.ORDER_PRICE_COLLAR_HARD,
            soft_threshold=soft_threshold,
        )
    if current_value > hard_threshold or (
        request.order_intent.order_type is OrderType.MARKET and current_value > soft_threshold
    ):
        return _evaluation(
            "order.price_collar",
            current_value,
            hard_threshold,
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.ORDER_PRICE_COLLAR_HARD,
            soft_threshold=soft_threshold,
        )
    if current_value > soft_threshold:
        return _evaluation(
            "order.price_collar",
            current_value,
            hard_threshold,
            RiskLimitStatus.SOFT_BREACH,
            RiskReasonCode.ORDER_PRICE_COLLAR_SOFT,
            soft_threshold=soft_threshold,
        )
    return _evaluation(
        "order.price_collar",
        current_value,
        hard_threshold,
        None,
        soft_threshold=soft_threshold,
    )


def _order_notional_evaluation(
    *,
    request: RiskCheckRequest,
    policy: RiskPolicy,
    metadata: _MetadataView,
    order_effect: OrderEffect,
) -> RiskLimitEvaluation:
    account_limit_pct = (
        metadata.account.risk_limits.max_order_notional_pct
        if metadata.account is not None
        else policy.max_order_notional_hard_pct
    )
    hard_threshold = min(
        policy.paper_nav * policy.max_order_notional_hard_pct,
        policy.paper_nav * account_limit_pct,
    )
    if metadata.constraint is not None and metadata.constraint.max_order_notional is not None:
        hard_threshold = min(hard_threshold, metadata.constraint.max_order_notional)
    soft_threshold = policy.paper_nav * policy.max_order_notional_soft_pct
    if not order_effect.risk_increasing:
        return _evaluation(
            "order.max_notional", order_effect.proposed_notional, hard_threshold, None
        )
    if order_effect.proposed_notional > hard_threshold:
        return _evaluation(
            "order.max_notional",
            order_effect.proposed_notional,
            hard_threshold,
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.ORDER_MAX_NOTIONAL_HARD,
            soft_threshold=soft_threshold,
        )
    if order_effect.proposed_notional > soft_threshold:
        return _evaluation(
            "order.max_notional",
            order_effect.proposed_notional,
            hard_threshold,
            RiskLimitStatus.SOFT_BREACH,
            RiskReasonCode.ORDER_MAX_NOTIONAL_SOFT,
            soft_threshold=soft_threshold,
            capped_value=soft_threshold,
        )
    return _evaluation(
        "order.max_notional",
        order_effect.proposed_notional,
        hard_threshold,
        None,
        soft_threshold=soft_threshold,
    )


def _instrument_exposure_evaluation(
    *,
    request: RiskCheckRequest,
    policy: RiskPolicy,
    metadata: _MetadataView,
    order_effect: OrderEffect,
) -> RiskLimitEvaluation:
    account_limit_pct = (
        metadata.account.risk_limits.max_instrument_exposure_pct
        if metadata.account is not None
        else policy.max_instrument_exposure_hard_pct
    )
    hard_threshold = min(
        policy.paper_nav * policy.max_instrument_exposure_hard_pct,
        policy.paper_nav * account_limit_pct,
    )
    soft_threshold = policy.paper_nav * policy.max_instrument_exposure_soft_pct
    if not order_effect.risk_increasing:
        return _evaluation(
            "position.instrument_exposure",
            order_effect.resulting_instrument_exposure_notional,
            hard_threshold,
            None,
            soft_threshold=soft_threshold,
        )
    return _threshold_evaluation(
        limit_id="position.instrument_exposure",
        current_value=order_effect.resulting_instrument_exposure_notional,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        soft_reason=RiskReasonCode.POSITION_INSTRUMENT_EXPOSURE_SOFT,
        hard_reason=RiskReasonCode.POSITION_INSTRUMENT_EXPOSURE_HARD,
    )


def _strategy_exposure_evaluation(
    *,
    request: RiskCheckRequest,
    policy: RiskPolicy,
    metadata: _MetadataView,
    order_effect: OrderEffect,
) -> RiskLimitEvaluation:
    account_limit_pct = (
        metadata.account.risk_limits.max_strategy_exposure_pct
        if metadata.account is not None
        else policy.max_strategy_exposure_hard_pct
    )
    hard_threshold = min(
        policy.paper_nav * policy.max_strategy_exposure_hard_pct,
        policy.paper_nav * account_limit_pct,
    )
    soft_threshold = policy.paper_nav * policy.max_strategy_exposure_soft_pct
    if not order_effect.risk_increasing:
        return _evaluation(
            "position.strategy_exposure",
            order_effect.resulting_strategy_exposure_notional,
            hard_threshold,
            None,
            soft_threshold=soft_threshold,
        )
    return _threshold_evaluation(
        limit_id="position.strategy_exposure",
        current_value=order_effect.resulting_strategy_exposure_notional,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        soft_reason=RiskReasonCode.POSITION_STRATEGY_EXPOSURE_SOFT,
        hard_reason=RiskReasonCode.POSITION_STRATEGY_EXPOSURE_HARD,
    )


def _total_spot_exposure_evaluation(
    *,
    request: RiskCheckRequest,
    policy: RiskPolicy,
    metadata: _MetadataView,
    order_effect: OrderEffect,
) -> RiskLimitEvaluation:
    account_total_pct = (
        metadata.account.risk_limits.max_total_spot_exposure_pct
        if metadata.account is not None
        else policy.max_total_spot_exposure_hard_pct
    )
    account_cash_pct = (
        metadata.account.risk_limits.min_cash_reserve_pct
        if metadata.account is not None
        else policy.min_cash_reserve_pct
    )
    hard_threshold = min(
        policy.paper_nav * policy.max_total_spot_exposure_hard_pct,
        policy.paper_nav * account_total_pct,
    )
    soft_threshold = policy.paper_nav * policy.max_total_spot_exposure_soft_pct
    cash_threshold = max(
        policy.paper_nav * policy.min_cash_reserve_pct,
        policy.paper_nav * account_cash_pct,
    )
    if order_effect.risk_increasing and order_effect.resulting_cash < cash_threshold:
        return _evaluation(
            "position.total_spot_exposure",
            order_effect.resulting_cash,
            cash_threshold,
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.CASH_RESERVE_HARD,
            soft_threshold=soft_threshold,
        )
    if not order_effect.risk_increasing:
        return _evaluation(
            "position.total_spot_exposure",
            order_effect.resulting_total_spot_exposure_notional,
            hard_threshold,
            None,
            soft_threshold=soft_threshold,
        )
    return _threshold_evaluation(
        limit_id="position.total_spot_exposure",
        current_value=order_effect.resulting_total_spot_exposure_notional,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        soft_reason=RiskReasonCode.POSITION_TOTAL_SPOT_EXPOSURE_SOFT,
        hard_reason=RiskReasonCode.POSITION_TOTAL_SPOT_EXPOSURE_HARD,
    )


def _no_short_or_oversell_evaluation(*, request: RiskCheckRequest) -> RiskLimitEvaluation:
    intent = request.order_intent
    oversell_quantity = Decimal("0")
    if intent.side is OrderSide.SELL:
        oversell_quantity = max(
            Decimal("0"), intent.quantity - request.current_instrument_position_quantity
        )
    if oversell_quantity > 0:
        return _evaluation(
            "position.no_short_or_oversell",
            oversell_quantity,
            Decimal("0"),
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.NO_SHORT_OR_OVERSELL,
        )
    return _evaluation("position.no_short_or_oversell", oversell_quantity, Decimal("0"), None)


def _daily_account_loss_evaluation(
    *, request: RiskCheckRequest, policy: RiskPolicy
) -> RiskLimitEvaluation:
    hard_threshold = -(policy.paper_nav * policy.max_daily_account_loss_hard_pct)
    soft_threshold = -(policy.paper_nav * policy.max_daily_account_loss_soft_pct)
    current_value = request.loss_risk.daily_account_pnl
    return _negative_loss_evaluation(
        limit_id="loss.daily_account",
        current_value=current_value,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        soft_reason=RiskReasonCode.DAILY_ACCOUNT_LOSS_SOFT,
        hard_reason=RiskReasonCode.DAILY_ACCOUNT_LOSS_HARD,
    )


def _daily_strategy_loss_evaluation(
    *, request: RiskCheckRequest, policy: RiskPolicy
) -> RiskLimitEvaluation:
    hard_threshold = -(policy.paper_nav * policy.max_daily_strategy_loss_hard_pct)
    soft_threshold = -(policy.paper_nav * policy.max_daily_strategy_loss_soft_pct)
    current_value = request.loss_risk.daily_strategy_pnl
    return _negative_loss_evaluation(
        limit_id="loss.daily_strategy",
        current_value=current_value,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        soft_reason=RiskReasonCode.DAILY_STRATEGY_LOSS_SOFT,
        hard_reason=RiskReasonCode.DAILY_STRATEGY_LOSS_HARD,
    )


def _max_drawdown_evaluation(
    *, request: RiskCheckRequest, policy: RiskPolicy
) -> RiskLimitEvaluation:
    return _threshold_evaluation(
        limit_id="loss.max_drawdown",
        current_value=request.loss_risk.max_drawdown_pct,
        soft_threshold=policy.max_drawdown_soft_pct,
        hard_threshold=policy.max_drawdown_hard_pct,
        soft_reason=RiskReasonCode.MAX_DRAWDOWN_SOFT,
        hard_reason=RiskReasonCode.MAX_DRAWDOWN_HARD,
    )


def _liquidity_participation_evaluation(
    *, request: RiskCheckRequest, policy: RiskPolicy, order_effect: OrderEffect
) -> RiskLimitEvaluation:
    telemetry = request.liquidity_risk
    if telemetry.depth_metric_required and telemetry.top_of_book_depth_notional is None:
        return _evaluation(
            "liquidity.participation",
            Decimal("1"),
            Decimal("0"),
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.LIQUIDITY_PARTICIPATION_HARD,
        )

    checks: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
    if telemetry.rolling_24h_quote_volume_notional is not None:
        checks.append(
            (
                order_effect.proposed_notional / telemetry.rolling_24h_quote_volume_notional,
                policy.max_participation_24h_quote_volume_soft_pct,
                policy.max_participation_24h_quote_volume_hard_pct,
                telemetry.rolling_24h_quote_volume_notional
                * policy.max_participation_24h_quote_volume_soft_pct,
            )
        )
    if telemetry.top_of_book_depth_notional is not None:
        checks.append(
            (
                order_effect.proposed_notional / telemetry.top_of_book_depth_notional,
                policy.max_participation_top_of_book_depth_soft_pct,
                policy.max_participation_top_of_book_depth_hard_pct,
                telemetry.top_of_book_depth_notional
                * policy.max_participation_top_of_book_depth_soft_pct,
            )
        )

    if not checks:
        return _evaluation(
            "liquidity.participation",
            Decimal("0"),
            policy.max_participation_24h_quote_volume_hard_pct,
            None,
            soft_threshold=policy.max_participation_24h_quote_volume_soft_pct,
        )

    hard_breach = next((check for check in checks if check[0] > check[2]), None)
    if hard_breach is not None:
        current_value, soft_threshold, hard_threshold, _soft_cap_notional = hard_breach
        return _evaluation(
            "liquidity.participation",
            current_value,
            hard_threshold,
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.LIQUIDITY_PARTICIPATION_HARD,
            soft_threshold=soft_threshold,
        )

    soft_breach = next((check for check in checks if check[0] > check[1]), None)
    if soft_breach is not None:
        current_value, soft_threshold, hard_threshold, soft_cap_notional = soft_breach
        return _evaluation(
            "liquidity.participation",
            current_value,
            hard_threshold,
            RiskLimitStatus.SOFT_BREACH,
            RiskReasonCode.LIQUIDITY_PARTICIPATION_SOFT,
            soft_threshold=soft_threshold,
            capped_value=soft_cap_notional,
        )

    current_value, soft_threshold, hard_threshold, _soft_cap_notional = max(
        checks, key=lambda item: item[0]
    )
    return _evaluation(
        "liquidity.participation",
        current_value,
        hard_threshold,
        None,
        soft_threshold=soft_threshold,
    )


def _liquidity_spread_evaluation(
    *, request: RiskCheckRequest, policy: RiskPolicy
) -> RiskLimitEvaluation:
    telemetry = request.liquidity_risk
    hard_threshold = policy.max_spread_hard_bps
    soft_threshold = policy.max_spread_soft_bps
    if telemetry.current_spread_bps is None:
        return _evaluation(
            "liquidity.spread",
            Decimal("0"),
            hard_threshold,
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.LIQUIDITY_SPREAD_HARD,
            soft_threshold=soft_threshold,
        )
    current_value = telemetry.current_spread_bps
    if telemetry.spread_cost_model_envelope_bps is not None:
        hard_threshold = min(hard_threshold, telemetry.spread_cost_model_envelope_bps)
    return _threshold_evaluation(
        limit_id="liquidity.spread",
        current_value=current_value,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        soft_reason=RiskReasonCode.LIQUIDITY_SPREAD_SOFT,
        hard_reason=RiskReasonCode.LIQUIDITY_SPREAD_HARD,
    )


def _market_volatility_evaluation(
    *, request: RiskCheckRequest, policy: RiskPolicy
) -> RiskLimitEvaluation:
    telemetry = request.market_risk
    hard_threshold = policy.max_volatility_envelope_hard_multiplier
    soft_threshold = policy.max_volatility_envelope_soft_multiplier
    current_value = telemetry.volatility_envelope_multiplier or Decimal("0")
    if (
        not telemetry.volatility_envelope_available
        or telemetry.volatility_envelope_multiplier is None
        or telemetry.volatility_shock_active
    ):
        return _evaluation(
            "market.volatility",
            current_value,
            hard_threshold,
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.MARKET_VOLATILITY_HARD,
            soft_threshold=soft_threshold,
        )
    return _threshold_evaluation(
        limit_id="market.volatility",
        current_value=current_value,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        soft_reason=RiskReasonCode.MARKET_VOLATILITY_SOFT,
        hard_reason=RiskReasonCode.MARKET_VOLATILITY_HARD,
    )


def _data_freshness_evaluation(*, request: RiskCheckRequest) -> RiskLimitEvaluation:
    blocking_signals = tuple(
        signal
        for signal in request.data_health_signals
        if signal.blocks_trading
        and (
            signal.blocked_instrument_id is None
            or signal.blocked_instrument_id == request.order_intent.instrument_id
        )
    )
    if blocking_signals:
        return _evaluation(
            "data.freshness",
            Decimal(len(blocking_signals)),
            Decimal("0"),
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.DATA_HEALTH_BLOCK,
        )
    return _evaluation("data.freshness", Decimal("0"), Decimal("0"), None)


def _idempotency_evaluation(*, request: RiskCheckRequest) -> RiskLimitEvaluation:
    order_hash = build_order_intent_hash(order_intent=request.order_intent)
    duplicates = tuple(
        record
        for record in request.idempotency_records
        if record.state in _UNRESOLVED_IDEMPOTENCY_STATES
        and (
            record.idempotency_key == request.idempotency_key
            or record.client_order_id == request.order_intent.client_order_id
            or record.trace_id == request.trace_id
            or record.order_intent_hash == order_hash
        )
    )
    if duplicates:
        return _evaluation(
            "execution.duplicate_idempotency",
            Decimal(len(duplicates)),
            Decimal("0"),
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.DUPLICATE_IDEMPOTENCY,
        )
    return _evaluation("execution.duplicate_idempotency", Decimal("0"), Decimal("0"), None)


def _throttle_evaluations(*, request: RiskCheckRequest) -> tuple[RiskLimitEvaluation, ...]:
    if not request.throttle_windows:
        return (
            _evaluation(
                "execution.order_throttle",
                Decimal("0"),
                Decimal("0"),
                None,
                soft_threshold=Decimal("0"),
            ),
        )
    evaluations: list[RiskLimitEvaluation] = []
    for window in request.throttle_windows:
        projected_count = Decimal(window.observed_intent_count + 1)
        hard_threshold = Decimal(window.hard_limit)
        soft_threshold = Decimal(window.soft_limit)
        if projected_count > hard_threshold:
            evaluations.append(
                _evaluation(
                    "execution.order_throttle",
                    projected_count,
                    hard_threshold,
                    RiskLimitStatus.HARD_BREACH,
                    RiskReasonCode.ORDER_THROTTLE_HARD,
                    soft_threshold=soft_threshold,
                )
            )
        elif projected_count > soft_threshold:
            evaluations.append(
                _evaluation(
                    "execution.order_throttle",
                    projected_count,
                    hard_threshold,
                    RiskLimitStatus.SOFT_BREACH,
                    RiskReasonCode.ORDER_THROTTLE_SOFT,
                    soft_threshold=soft_threshold,
                )
            )
        else:
            evaluations.append(
                _evaluation(
                    "execution.order_throttle",
                    projected_count,
                    hard_threshold,
                    None,
                    soft_threshold=soft_threshold,
                )
            )
    return tuple(evaluations)


def _reject_burst_evaluations(*, request: RiskCheckRequest) -> tuple[RiskLimitEvaluation, ...]:
    if not request.reject_burst_windows:
        return (_evaluation("execution.reject_burst", Decimal("0"), Decimal("0"), None),)

    evaluations: list[RiskLimitEvaluation] = []
    for window in request.reject_burst_windows:
        current_value = Decimal(window.observed_reject_count)
        hard_threshold = Decimal(window.hard_limit)
        soft_threshold = Decimal(window.soft_limit)
        if window.unknown_state_reject_observed or current_value >= hard_threshold:
            evaluations.append(
                _evaluation(
                    "execution.reject_burst",
                    current_value,
                    hard_threshold,
                    RiskLimitStatus.HARD_BREACH,
                    RiskReasonCode.REJECT_BURST_HARD,
                    soft_threshold=soft_threshold,
                )
            )
        elif current_value >= soft_threshold:
            evaluations.append(
                _evaluation(
                    "execution.reject_burst",
                    current_value,
                    hard_threshold,
                    RiskLimitStatus.SOFT_BREACH,
                    RiskReasonCode.REJECT_BURST_SOFT,
                    soft_threshold=soft_threshold,
                )
            )
        else:
            evaluations.append(
                _evaluation(
                    "execution.reject_burst",
                    current_value,
                    hard_threshold,
                    None,
                    soft_threshold=soft_threshold,
                )
            )
    return tuple(evaluations)


def _engine_latency_evaluation(*, request: RiskCheckRequest) -> RiskLimitEvaluation:
    decision_to_risk_ms = _timedelta_ms(request.risk_check_ts - request.decision_ts)
    current_value = max(decision_to_risk_ms, request.engine_latency.risk_to_gateway_latency_ms)
    hard_threshold = request.engine_latency.latency_budget_ms
    soft_threshold = hard_threshold * Decimal("0.5")
    if not request.engine_latency.event_time_validity_proven or current_value > hard_threshold:
        return _evaluation(
            "engine.latency",
            current_value,
            hard_threshold,
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.ENGINE_LATENCY_HARD,
            soft_threshold=soft_threshold,
        )
    if current_value > soft_threshold:
        return _evaluation(
            "engine.latency",
            current_value,
            hard_threshold,
            RiskLimitStatus.SOFT_BREACH,
            RiskReasonCode.ENGINE_LATENCY_SOFT,
            soft_threshold=soft_threshold,
        )
    return _evaluation(
        "engine.latency",
        current_value,
        hard_threshold,
        None,
        soft_threshold=soft_threshold,
    )


def _model_drift_or_calibration_evaluation(
    *, request: RiskCheckRequest
) -> RiskLimitEvaluation:
    telemetry = request.model_risk
    if telemetry.severe_anomaly_detected or not telemetry.calibrated_outputs:
        return _evaluation(
            "model.drift_or_calibration",
            Decimal("1"),
            Decimal("0"),
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.MODEL_DRIFT_OR_CALIBRATION_HARD,
            soft_threshold=Decimal("0"),
        )
    if telemetry.sustained_drift_detected:
        return _evaluation(
            "model.drift_or_calibration",
            Decimal("1"),
            Decimal("0"),
            RiskLimitStatus.SOFT_BREACH,
            RiskReasonCode.MODEL_DRIFT_OR_CALIBRATION_SOFT,
            soft_threshold=Decimal("0"),
        )
    return _evaluation(
        "model.drift_or_calibration",
        Decimal("0"),
        Decimal("0"),
        None,
        soft_threshold=Decimal("0"),
    )


def _tca_cost_slippage_evaluation(
    *, request: RiskCheckRequest, policy: RiskPolicy
) -> RiskLimitEvaluation:
    telemetry = request.tca_risk
    hard_threshold = policy.tca_cost_slippage_hard_multiplier
    soft_threshold = policy.tca_cost_slippage_soft_multiplier
    current_value = telemetry.cost_slippage_multiplier or Decimal("0")
    if (
        not telemetry.tca_available
        or not telemetry.fill_quality_known
        or telemetry.cost_slippage_multiplier is None
    ):
        return _evaluation(
            "tca.cost_slippage",
            current_value,
            hard_threshold,
            RiskLimitStatus.HARD_BREACH,
            RiskReasonCode.TCA_COST_SLIPPAGE_HARD,
            soft_threshold=soft_threshold,
        )
    return _threshold_evaluation(
        limit_id="tca.cost_slippage",
        current_value=current_value,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        soft_reason=RiskReasonCode.TCA_COST_SLIPPAGE_SOFT,
        hard_reason=RiskReasonCode.TCA_COST_SLIPPAGE_HARD,
    )


def _threshold_evaluation(
    *,
    limit_id: str,
    current_value: Decimal,
    soft_threshold: Decimal,
    hard_threshold: Decimal,
    soft_reason: RiskReasonCode,
    hard_reason: RiskReasonCode,
) -> RiskLimitEvaluation:
    if current_value > hard_threshold:
        return _evaluation(
            limit_id,
            current_value,
            hard_threshold,
            RiskLimitStatus.HARD_BREACH,
            hard_reason,
            soft_threshold=soft_threshold,
        )
    if current_value > soft_threshold:
        return _evaluation(
            limit_id,
            current_value,
            hard_threshold,
            RiskLimitStatus.SOFT_BREACH,
            soft_reason,
            soft_threshold=soft_threshold,
            capped_value=soft_threshold,
        )
    return _evaluation(
        limit_id,
        current_value,
        hard_threshold,
        None,
        soft_threshold=soft_threshold,
    )


def _negative_loss_evaluation(
    *,
    limit_id: str,
    current_value: Decimal,
    soft_threshold: Decimal,
    hard_threshold: Decimal,
    soft_reason: RiskReasonCode,
    hard_reason: RiskReasonCode,
) -> RiskLimitEvaluation:
    if current_value <= hard_threshold:
        return _evaluation(
            limit_id,
            current_value,
            hard_threshold,
            RiskLimitStatus.HARD_BREACH,
            hard_reason,
            soft_threshold=soft_threshold,
        )
    if current_value <= soft_threshold:
        return _evaluation(
            limit_id,
            current_value,
            hard_threshold,
            RiskLimitStatus.SOFT_BREACH,
            soft_reason,
            soft_threshold=soft_threshold,
        )
    return _evaluation(
        limit_id,
        current_value,
        hard_threshold,
        None,
        soft_threshold=soft_threshold,
    )


def _timedelta_ms(delta: timedelta) -> Decimal:
    return Decimal(str(delta.total_seconds())) * Decimal("1000")


def _evaluation(
    limit_id: str,
    current_value: Decimal,
    hard_threshold: Decimal | None,
    status: RiskLimitStatus | None,
    reason_code: RiskReasonCode = RiskReasonCode.PASSED,
    *,
    soft_threshold: Decimal | None = None,
    capped_value: Decimal | None = None,
) -> RiskLimitEvaluation:
    final_status = status or RiskLimitStatus.PASS
    return RiskLimitEvaluation(
        limit_id=limit_id,
        owner=_LIMIT_OWNERS[limit_id],
        status=final_status,
        passed=final_status is RiskLimitStatus.PASS,
        current_value=current_value,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        capped_value=capped_value,
        reason_code=reason_code,
    )
