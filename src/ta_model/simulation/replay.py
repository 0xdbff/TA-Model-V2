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
from decimal import Decimal

from ta_model.contracts.instrument_master import OrderType
from ta_model.contracts.market_data import OHLCTVBar
from ta_model.contracts.simulation import (
    ExecutionCostModel,
    OrderIntent,
    OrderSide,
    ReplayFillStatus,
    ReplayOrderResult,
    ReplayRejectReason,
    ReplayReport,
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

    results = tuple(
        _replay_one(intent=intent, bars=bar_tuple, execution_cost_model=execution_cost_model)
        for intent in intent_tuple
    )
    market_data_hash = _market_data_hash(bar_tuple)
    requirement_ids = (
        ("FR-012", "NFR-001")
        if execution_cost_model is None
        else ("FR-012", "NFR-001", "RISK-005")
    )
    report_hash = build_replay_report_hash(
        run_id=run_id,
        market_data_hash=market_data_hash,
        results=results,
        requirement_ids=requirement_ids,
    )
    return ReplayReport(
        replay_report_id=build_replay_report_id(replay_report_hash=report_hash),
        replay_report_hash=report_hash,
        run_id=run_id,
        market_data_hash=market_data_hash,
        result_ids=tuple(result.replay_order_result_id for result in results),
        results=results,
        requirement_ids=requirement_ids,
    )


def _replay_one(
    *,
    intent: OrderIntent,
    bars: tuple[OHLCTVBar, ...],
    execution_cost_model: ExecutionCostModel | None,
) -> ReplayOrderResult:
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
        return ReplayOrderResult(
            **result.model_dump(exclude={"replay_order_result_id"}),
            replay_order_result_id=result_id,
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
    return ReplayOrderResult(
        **result.model_dump(exclude={"replay_order_result_id"}),
        replay_order_result_id=result_id,
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
        ReplayFillStatus.REJECTED
        if reason is ReplayRejectReason.UNSUPPORTED_ORDER_TYPE
        else ReplayFillStatus.UNFILLED
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
    for intent in order_intents:
        if intent.client_order_id in seen_client_order_ids:
            raise ReplayBuildError("duplicate client_order_id in replay order intents")
        seen_client_order_ids.add(intent.client_order_id)


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
