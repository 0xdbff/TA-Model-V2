"""Event-time historical replay foundation for S6-001.

The engine uses OHLCTV close_ts as market-data availability time and fills market
orders only on the next eligible bar open. It intentionally ignores ingest_ts for
ordering/availability and fails closed on duplicate, overlapping, or non-monotonic
bar streams.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from ta_model.contracts.instrument_master import OrderType
from ta_model.contracts.market_data import OHLCTVBar
from ta_model.contracts.simulation import (
    OrderIntent,
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
    *, bars: Iterable[OHLCTVBar], order_intents: Iterable[OrderIntent], run_id: str
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

    results = tuple(_replay_one(intent=intent, bars=bar_tuple) for intent in intent_tuple)
    market_data_hash = _market_data_hash(bar_tuple)
    report_hash = build_replay_report_hash(
        run_id=run_id,
        market_data_hash=market_data_hash,
        results=results,
        requirement_ids=("FR-012", "NFR-001"),
    )
    return ReplayReport(
        replay_report_id=build_replay_report_id(replay_report_hash=report_hash),
        replay_report_hash=report_hash,
        run_id=run_id,
        market_data_hash=market_data_hash,
        result_ids=tuple(result.replay_order_result_id for result in results),
        results=results,
    )


def _replay_one(*, intent: OrderIntent, bars: tuple[OHLCTVBar, ...]) -> ReplayOrderResult:
    if intent.order_type is not OrderType.MARKET:
        return _unfilled_result(intent=intent, reason=ReplayRejectReason.UNSUPPORTED_ORDER_TYPE)

    for bar in bars:
        if bar.instrument_id != intent.instrument_id or bar.venue_id != intent.venue_id:
            continue
        if bar.open_ts >= intent.submitted_at and bar.close_ts > intent.submitted_at:
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
                filled_quantity=intent.quantity,
                fill_event_open_ts=bar.open_ts,
                fill_event_close_ts=bar.close_ts,
                fill_event_source_ts=bar.source_ts,
                fill_raw_payload_id=bar.raw_payload_id,
            )
            result_id = build_replay_order_result_id(result=result)
            return ReplayOrderResult(
                **result.model_dump(exclude={"replay_order_result_id"}),
                replay_order_result_id=result_id,
            )
    return _unfilled_result(intent=intent, reason=ReplayRejectReason.NO_FUTURE_ELIGIBLE_EVENT)


def _unfilled_result(*, intent: OrderIntent, reason: ReplayRejectReason) -> ReplayOrderResult:
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
