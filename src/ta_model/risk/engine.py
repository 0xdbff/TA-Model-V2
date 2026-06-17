"""Pure independent pre-trade risk engine for S9.

The engine returns deterministic risk evidence only. It never calls simulator,
paper, or future live gateways; routing is handled by the risk-gated replay seam.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    "position.instrument_exposure": "Risk",
    "position.strategy_exposure": "Risk / strategy owner",
    "position.total_spot_exposure": "Risk / product",
    "position.no_short_or_oversell": "Risk / execution",
    "data.freshness": "Data / risk",
    "venue.status": "Ops / execution",
    "execution.order_throttle": "Execution / ops",
    "execution.duplicate_idempotency": "Execution / risk",
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
        _data_freshness_evaluation(request=request),
        _idempotency_evaluation(request=request),
        *_throttle_evaluations(request=request),
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

    allowed_incremental_notionals = tuple(
        cap
        for cap in (
            _allowed_incremental_notional(request=request, evaluation=evaluation)
            for evaluation in evaluations
        )
        if cap is not None
    )
    if not allowed_incremental_notionals:
        return RiskDecisionStatus.APPROVED, request.order_intent

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
