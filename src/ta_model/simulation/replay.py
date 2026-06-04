"""Event-time historical replay foundation with optional S6-002 costs.

The engine uses OHLCTV close_ts as market-data availability time and fills market
orders only on the next eligible bar open. It intentionally ignores ingest_ts for
ordering/availability and fails closed on duplicate, overlapping, or non-monotonic
bar streams.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from ta_model.contracts.instrument_master import (
    AccountStatus,
    AccountType,
    InstrumentMasterSnapshot,
    InstrumentStatus,
    InstrumentType,
    OrderType,
    TradingPermission,
    VenueStatus,
)
from ta_model.contracts.market_data import OHLCTVBar
from ta_model.contracts.simulation import (
    ExecutionCostModel,
    OrderIntent,
    OrderSide,
    ReplayFillStatus,
    ReplayOrderResult,
    ReplayRejectReason,
    ReplayReport,
    SimulatedAccountState,
    SimulatedBalance,
    build_rejection_counts,
    build_replay_order_result_id,
    build_replay_report_hash,
    build_replay_report_id,
)


class ReplayBuildError(ValueError):
    """Raised when S6 replay inputs are unsafe or ambiguous."""


def replay_ohlctv_market_orders(
    *,
    bars: Iterable[OHLCTVBar],
    order_intents: Iterable[OrderIntent],
    run_id: str,
    execution_cost_model: ExecutionCostModel | None = None,
    instrument_master_snapshot: InstrumentMasterSnapshot | None = None,
    starting_account_state: SimulatedAccountState | None = None,
) -> ReplayReport:
    """Replay market order intents against validated event-time OHLCTV bars.

    Bars must already be deterministically ordered by event-time availability:
    close_ts, instrument, venue, and timeframe. For an order submitted when bar N
    becomes available, bar N is not eligible for filling; the earliest fill is the
    next bar whose open_ts is at or after submitted_at and whose close_ts is after
    submitted_at.
    """

    bar_tuple = tuple(bars)
    intent_tuple = tuple(order_intents)
    _validate_bars_are_safe(bar_tuple)
    _validate_order_intents(intent_tuple)
    if (instrument_master_snapshot is None) != (starting_account_state is None):
        raise ReplayBuildError(
            "instrument master snapshot and simulated account state must be supplied together"
        )

    balances = _balance_dict(starting_account_state)
    result_list: list[ReplayOrderResult] = []
    for intent in intent_tuple:
        result = _replay_one(
            intent=intent,
            bars=bar_tuple,
            execution_cost_model=execution_cost_model,
            instrument_master_snapshot=instrument_master_snapshot,
            account_state=starting_account_state,
            balances=balances,
        )
        result_list.append(result)
    results = tuple(result_list)
    final_account_state = (
        _build_account_state(starting_account_state, balances)
        if starting_account_state is not None
        else None
    )
    rejection_counts = build_rejection_counts(results=results)
    market_data_hash = _market_data_hash(bar_tuple)
    requirement_ids = _requirement_ids(
        execution_cost_model=execution_cost_model,
        instrument_master_snapshot=instrument_master_snapshot,
    )
    report_hash = build_replay_report_hash(
        run_id=run_id,
        market_data_hash=market_data_hash,
        results=results,
        requirement_ids=requirement_ids,
        rejection_counts=rejection_counts,
        final_account_state=final_account_state,
    )
    return ReplayReport(
        replay_report_id=build_replay_report_id(replay_report_hash=report_hash),
        replay_report_hash=report_hash,
        run_id=run_id,
        market_data_hash=market_data_hash,
        result_ids=tuple(result.replay_order_result_id for result in results),
        results=results,
        requirement_ids=requirement_ids,
        rejection_counts=rejection_counts,
        final_account_state=final_account_state,
    )


def _replay_one(
    *,
    intent: OrderIntent,
    bars: tuple[OHLCTVBar, ...],
    execution_cost_model: ExecutionCostModel | None,
    instrument_master_snapshot: InstrumentMasterSnapshot | None,
    account_state: SimulatedAccountState | None,
    balances: dict[tuple[str, str], Decimal] | None,
) -> ReplayOrderResult:
    if instrument_master_snapshot is not None and account_state is not None:
        reject_reason = _metadata_reject_reason(
            intent=intent,
            snapshot=instrument_master_snapshot,
            account_state=account_state,
        )
        if reject_reason is not None:
            return _unfilled_result(intent=intent, reason=reject_reason)

    if intent.order_type is not OrderType.MARKET:
        return _unfilled_result(intent=intent, reason=ReplayRejectReason.UNSUPPORTED_ORDER_TYPE)

    eligible = tuple(
        (index, bar)
        for index, bar in enumerate(bars)
        if bar.instrument_id == intent.instrument_id
        and bar.venue_id == intent.venue_id
        and bar.open_ts >= intent.submitted_at
        and bar.close_ts > intent.submitted_at
    )
    if not eligible:
        return _unfilled_result(intent=intent, reason=ReplayRejectReason.NO_FUTURE_ELIGIBLE_EVENT)

    if execution_cost_model is None:
        _, bar = eligible[0]
        if instrument_master_snapshot is not None:
            constraint_reason = _constraint_reject_reason(
                intent=intent,
                snapshot=instrument_master_snapshot,
                reference_price=bar.open,
                effective_at=bar.open_ts,
            )
            if constraint_reason is not None:
                return _unfilled_result(intent=intent, reason=constraint_reason)
        filled_quantity = intent.quantity
        reference_notional = bar.open * filled_quantity
        result = ReplayOrderResult.model_construct(
            replay_order_result_id="REPLAYORDER:PLACEHOLDER",
            client_order_id=intent.client_order_id,
            trace_id=intent.trace_id,
            source_decision_id=intent.source_decision_id,
            instrument_id=intent.instrument_id,
            venue_id=intent.venue_id,
            side=intent.side,
            order_type=intent.order_type,
            quantity=intent.quantity,
            submitted_at=intent.submitted_at,
            status=ReplayFillStatus.FILLED,
            fill_price=bar.open,
            filled_quantity=filled_quantity,
            remaining_quantity=Decimal("0"),
            fill_event_open_ts=bar.open_ts,
            fill_event_close_ts=bar.close_ts,
            fill_event_source_ts=bar.source_ts,
            fill_raw_payload_id=bar.raw_payload_id,
            arrival_reference_price=bar.open,
            effective_fill_price=bar.open,
            reference_notional=reference_notional,
            effective_notional=reference_notional,
        )
        result_id = build_replay_order_result_id(result=result)
        filled_result = ReplayOrderResult(
            **result.model_dump(exclude={"replay_order_result_id"}),
            replay_order_result_id=result_id,
        )
        if instrument_master_snapshot is None or balances is None:
            return filled_result
        return _apply_balance_or_reject(
            intent=intent,
            result=filled_result,
            snapshot=instrument_master_snapshot,
            balances=balances,
        )

    if execution_cost_model.latency_bars >= len(eligible):
        return _unfilled_result(
            intent=intent,
            reason=ReplayRejectReason.NO_FUTURE_ELIGIBLE_EVENT,
            execution_cost_model=execution_cost_model,
            eligible_event_index=eligible[0][0],
        )

    eligible_event_index = eligible[0][0]
    fill_attempt_event_index, bar = eligible[execution_cost_model.latency_bars]
    if instrument_master_snapshot is not None:
        constraint_reason = _constraint_reject_reason(
            intent=intent,
            snapshot=instrument_master_snapshot,
            reference_price=bar.open,
            effective_at=bar.open_ts,
        )
        if constraint_reason is not None:
            return _unfilled_result(
                intent=intent,
                reason=constraint_reason,
                execution_cost_model=execution_cost_model,
                eligible_event_index=eligible_event_index,
                fill_attempt_event_index=fill_attempt_event_index,
            )
    max_fill_quantity = bar.base_volume * execution_cost_model.max_participation_rate
    if max_fill_quantity <= 0:
        return _unfilled_result(
            intent=intent,
            reason=ReplayRejectReason.INSUFFICIENT_LIQUIDITY,
            execution_cost_model=execution_cost_model,
            eligible_event_index=eligible_event_index,
            fill_attempt_event_index=fill_attempt_event_index,
        )

    filled_quantity = min(intent.quantity, max_fill_quantity)
    if filled_quantity < intent.quantity and not execution_cost_model.allow_partial_fills:
        return _unfilled_result(
            intent=intent,
            reason=ReplayRejectReason.INSUFFICIENT_LIQUIDITY,
            execution_cost_model=execution_cost_model,
            eligible_event_index=eligible_event_index,
            fill_attempt_event_index=fill_attempt_event_index,
        )

    status = (
        ReplayFillStatus.FILLED
        if filled_quantity == intent.quantity
        else ReplayFillStatus.PARTIALLY_FILLED
    )
    adverse_bps = execution_cost_model.spread_bps + execution_cost_model.slippage_bps
    adjustment = adverse_bps / Decimal("10000")
    arrival_reference_price = bar.open
    effective_fill_price = (
        arrival_reference_price * (Decimal("1") + adjustment)
        if intent.side is OrderSide.BUY
        else arrival_reference_price * (Decimal("1") - adjustment)
    )
    reference_notional = arrival_reference_price * filled_quantity
    effective_notional = effective_fill_price * filled_quantity
    fee_cost = effective_notional.copy_abs() * execution_cost_model.taker_fee_rate
    spread_cost = reference_notional.copy_abs() * execution_cost_model.spread_bps / Decimal("10000")
    slippage_cost = (
        reference_notional.copy_abs() * execution_cost_model.slippage_bps / Decimal("10000")
    )
    total_cost = fee_cost + spread_cost + slippage_cost

    result = ReplayOrderResult.model_construct(
        replay_order_result_id="REPLAYORDER:PLACEHOLDER",
        client_order_id=intent.client_order_id,
        trace_id=intent.trace_id,
        source_decision_id=intent.source_decision_id,
        instrument_id=intent.instrument_id,
        venue_id=intent.venue_id,
        side=intent.side,
        order_type=intent.order_type,
        quantity=intent.quantity,
        submitted_at=intent.submitted_at,
        status=status,
        fill_price=effective_fill_price,
        filled_quantity=filled_quantity,
        remaining_quantity=intent.quantity - filled_quantity,
        fill_event_open_ts=bar.open_ts,
        fill_event_close_ts=bar.close_ts,
        fill_event_source_ts=bar.source_ts,
        fill_raw_payload_id=bar.raw_payload_id,
        cost_model_id=execution_cost_model.cost_model_id,
        cost_model_hash=execution_cost_model.cost_model_hash,
        latency_bars=execution_cost_model.latency_bars,
        eligible_event_index=eligible_event_index,
        fill_attempt_event_index=fill_attempt_event_index,
        arrival_reference_price=arrival_reference_price,
        effective_fill_price=effective_fill_price,
        reference_notional=reference_notional,
        effective_notional=effective_notional,
        fee_cost=fee_cost,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        total_cost=total_cost,
    )
    result_id = build_replay_order_result_id(result=result)
    filled_result = ReplayOrderResult(
        **result.model_dump(exclude={"replay_order_result_id"}),
        replay_order_result_id=result_id,
    )
    if instrument_master_snapshot is None or balances is None:
        return filled_result
    return _apply_balance_or_reject(
        intent=intent,
        result=filled_result,
        snapshot=instrument_master_snapshot,
        balances=balances,
    )


def _unfilled_result(
    *,
    intent: OrderIntent,
    reason: ReplayRejectReason,
    execution_cost_model: ExecutionCostModel | None = None,
    eligible_event_index: int | None = None,
    fill_attempt_event_index: int | None = None,
) -> ReplayOrderResult:
    status = (
        ReplayFillStatus.UNFILLED
        if reason
        in {ReplayRejectReason.NO_FUTURE_ELIGIBLE_EVENT, ReplayRejectReason.INSUFFICIENT_LIQUIDITY}
        else ReplayFillStatus.REJECTED
    )
    result = ReplayOrderResult.model_construct(
        replay_order_result_id="REPLAYORDER:PLACEHOLDER",
        client_order_id=intent.client_order_id,
        trace_id=intent.trace_id,
        source_decision_id=intent.source_decision_id,
        instrument_id=intent.instrument_id,
        venue_id=intent.venue_id,
        side=intent.side,
        order_type=intent.order_type,
        quantity=intent.quantity,
        submitted_at=intent.submitted_at,
        status=status,
        reason=reason,
        remaining_quantity=intent.quantity,
        cost_model_id=(
            execution_cost_model.cost_model_id if execution_cost_model is not None else None
        ),
        cost_model_hash=(
            execution_cost_model.cost_model_hash if execution_cost_model is not None else None
        ),
        latency_bars=execution_cost_model.latency_bars if execution_cost_model is not None else 0,
        eligible_event_index=eligible_event_index,
        fill_attempt_event_index=fill_attempt_event_index,
    )
    result_id = build_replay_order_result_id(result=result)
    return ReplayOrderResult(
        **result.model_dump(exclude={"replay_order_result_id"}),
        replay_order_result_id=result_id,
    )


def _metadata_reject_reason(
    *,
    intent: OrderIntent,
    snapshot: InstrumentMasterSnapshot,
    account_state: SimulatedAccountState,
) -> ReplayRejectReason | None:
    venue = next((item for item in snapshot.venues if item.venue_id == intent.venue_id), None)
    if venue is None or venue.status is not VenueStatus.ACTIVE:
        return ReplayRejectReason.VENUE_NOT_TRADABLE
    if intent.order_type not in venue.supported_order_types:
        return ReplayRejectReason.UNSUPPORTED_ORDER_TYPE

    instrument = next(
        (item for item in snapshot.instruments if item.instrument_id == intent.instrument_id), None
    )
    if (
        instrument is None
        or instrument.venue_id != intent.venue_id
        or instrument.instrument_type is not InstrumentType.SPOT
        or instrument.status is not InstrumentStatus.TRADING
        or instrument.is_derivative
        or instrument.margin_allowed
        or instrument.short_selling_allowed
        or instrument.leverage_allowed
    ):
        return ReplayRejectReason.INSTRUMENT_NOT_TRADABLE
    if intent.order_type not in instrument.supported_order_types:
        return ReplayRejectReason.UNSUPPORTED_ORDER_TYPE

    account = next(
        (item for item in snapshot.accounts if item.account_id == account_state.account_id), None
    )
    if (
        account is None
        or account.venue_id != intent.venue_id
        or account.status is not AccountStatus.ACTIVE
        or account.account_type not in {AccountType.SIMULATION, AccountType.PAPER}
        or TradingPermission.PLACE_ORDERS not in account.trading_permissions
        or account.live_capital_enabled
        or account.margin_enabled
        or account.derivatives_enabled
        or account.shorting_enabled
    ):
        return ReplayRejectReason.ACCOUNT_NOT_TRADABLE
    return None


def _constraint_reject_reason(
    *,
    intent: OrderIntent,
    snapshot: InstrumentMasterSnapshot,
    reference_price: Decimal,
    effective_at: datetime,
) -> ReplayRejectReason | None:
    active_constraints = [
        constraint
        for constraint in snapshot.instrument_constraints
        if constraint.instrument_id == intent.instrument_id
        and constraint.effective_from <= effective_at
        and (constraint.effective_to is None or effective_at < constraint.effective_to)
    ]
    if len(active_constraints) != 1:
        return ReplayRejectReason.CONSTRAINT_VIOLATION
    constraint_result = active_constraints[0].evaluate_order(
        price=reference_price,
        quantity=intent.quantity,
    )
    if not constraint_result.passed:
        return ReplayRejectReason.CONSTRAINT_VIOLATION
    return None


def _apply_balance_or_reject(
    *,
    intent: OrderIntent,
    result: ReplayOrderResult,
    snapshot: InstrumentMasterSnapshot,
    balances: dict[tuple[str, str], Decimal],
) -> ReplayOrderResult:
    instrument = next(
        item for item in snapshot.instruments if item.instrument_id == intent.instrument_id
    )
    base_key = (intent.venue_id, instrument.base_asset_id)
    quote_key = (intent.venue_id, instrument.quote_asset_id)
    base_balance = balances.get(base_key, Decimal("0"))
    quote_balance = balances.get(quote_key, Decimal("0"))

    if intent.side is OrderSide.BUY:
        debit = result.effective_notional + result.fee_cost
        if quote_balance < debit:
            return _unfilled_result(intent=intent, reason=ReplayRejectReason.INSUFFICIENT_CASH)
        balances[quote_key] = quote_balance - debit
        balances[base_key] = base_balance + result.filled_quantity
        return result

    if base_balance < result.filled_quantity:
        return _unfilled_result(intent=intent, reason=ReplayRejectReason.INSUFFICIENT_INVENTORY)
    balances[base_key] = base_balance - result.filled_quantity
    balances[quote_key] = quote_balance + result.effective_notional - result.fee_cost
    return result


def _balance_dict(
    account_state: SimulatedAccountState | None,
) -> dict[tuple[str, str], Decimal] | None:
    if account_state is None:
        return None
    return {
        (balance.venue_id, balance.asset_id): balance.available
        for balance in account_state.balances
    }


def _build_account_state(
    account_state: SimulatedAccountState | None,
    balances: dict[tuple[str, str], Decimal] | None,
) -> SimulatedAccountState | None:
    if account_state is None or balances is None:
        return None
    final_balances = tuple(
        SimulatedBalance(
            account_id=account_state.account_id,
            venue_id=venue_id,
            asset_id=asset_id,
            available=available,
        )
        for (venue_id, asset_id), available in sorted(balances.items())
    )
    return SimulatedAccountState(account_id=account_state.account_id, balances=final_balances)


def _requirement_ids(
    *,
    execution_cost_model: ExecutionCostModel | None,
    instrument_master_snapshot: InstrumentMasterSnapshot | None,
) -> tuple[str, ...]:
    ids = ["FR-012", "NFR-001"]
    if execution_cost_model is not None:
        ids.append("RISK-005")
    if instrument_master_snapshot is not None:
        ids.extend(("FR-003", "FR-010"))
    return tuple(ids)


def _validate_bars_are_safe(bars: tuple[OHLCTVBar, ...]) -> None:
    seen_close_keys: set[tuple[str, str, str, str]] = set()
    last_by_stream: dict[tuple[str, str, str], OHLCTVBar] = {}
    timeframes_by_market: dict[tuple[str, str], set[str]] = {}
    previous_global_key: tuple[str, str, str, str] | None = None
    for bar in bars:
        if bar.source_ts > bar.close_ts:
            raise ReplayBuildError("OHLCTV source_ts must not be after close_ts for replay")

        stream_key = (bar.instrument_id, bar.venue_id, bar.timeframe)
        market_key = (bar.instrument_id, bar.venue_id)
        timeframes_by_market.setdefault(market_key, set()).add(bar.timeframe)
        if len(timeframes_by_market[market_key]) > 1:
            raise ReplayBuildError(
                "mixed OHLCTV timeframes for one instrument/venue are ambiguous for replay"
            )

        close_key = (*stream_key, bar.close_ts.isoformat())
        if close_key in seen_close_keys:
            raise ReplayBuildError("duplicate OHLCTV bars per instrument/venue/timeframe/close_ts")
        seen_close_keys.add(close_key)

        global_key = (bar.close_ts.isoformat(), *stream_key)
        if previous_global_key is not None and global_key < previous_global_key:
            raise ReplayBuildError(
                "OHLCTV bars must be sorted by close_ts/instrument/venue/timeframe"
            )
        previous_global_key = global_key

        last = last_by_stream.get(stream_key)
        if last is not None:
            if bar.close_ts <= last.close_ts:
                raise ReplayBuildError("non-monotonic OHLCTV close_ts in stream")
            if bar.open_ts < last.close_ts:
                raise ReplayBuildError("overlapping OHLCTV bars are ambiguous for replay")
        last_by_stream[stream_key] = bar


def _validate_order_intents(order_intents: tuple[OrderIntent, ...]) -> None:
    seen_client_order_ids: set[str] = set()
    previous_order_key: tuple[datetime, str] | None = None
    for intent in order_intents:
        if intent.client_order_id in seen_client_order_ids:
            raise ReplayBuildError("duplicate client_order_id in replay order intents")
        seen_client_order_ids.add(intent.client_order_id)

        order_key = (intent.submitted_at, intent.client_order_id)
        if previous_order_key is not None and order_key < previous_order_key:
            raise ReplayBuildError(
                "order intents must be sorted by submitted_at/client_order_id for causal replay"
            )
        previous_order_key = order_key


def _market_data_hash(bars: tuple[OHLCTVBar, ...]) -> str:
    payload = tuple(
        {
            "base_volume": str(bar.base_volume),
            "close": str(bar.close),
            "close_ts": bar.close_ts.isoformat(),
            "high": str(bar.high),
            "instrument_id": bar.instrument_id,
            "low": str(bar.low),
            "open": str(bar.open),
            "open_ts": bar.open_ts.isoformat(),
            "quality_flags": tuple(flag.value for flag in bar.quality_flags),
            "quote_volume": str(bar.quote_volume) if bar.quote_volume is not None else None,
            "raw_payload_id": bar.raw_payload_id,
            "source_ts": bar.source_ts.isoformat(),
            "timeframe": bar.timeframe,
            "trade_count": bar.trade_count,
            "venue_id": bar.venue_id,
            "vwap": str(bar.vwap) if bar.vwap is not None else None,
        }
        for bar in bars
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
