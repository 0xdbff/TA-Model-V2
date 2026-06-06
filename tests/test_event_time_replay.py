"""Evidence for S6-001 event-time historical replay foundation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ta_model.contracts.instrument_master import OrderType
from ta_model.contracts.market_data import OHLCTVBar
from ta_model.contracts.simulation import (
    OrderIntent,
    OrderSide,
    ReplayFillStatus,
    ReplayRejectReason,
)
from ta_model.simulation.replay import ReplayBuildError, replay_ohlctv_market_orders

START = datetime(2026, 1, 1, tzinfo=UTC)
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"
VENUE_ID = "FIXTURE_SPOT"


def _bar(
    index: int,
    *,
    ingest_offset_minutes: int = 30,
    instrument_id: str = INSTRUMENT_ID,
    timeframe: str = "1m",
    source_ts: datetime | None = None,
) -> OHLCTVBar:
    open_ts = START + timedelta(minutes=index)
    close_ts = open_ts + timedelta(minutes=1)
    open_price = Decimal("100") + Decimal(index)
    return OHLCTVBar(
        instrument_id=instrument_id,
        venue_id=VENUE_ID,
        timeframe=timeframe,
        open_ts=open_ts,
        close_ts=close_ts,
        open=open_price,
        high=open_price + Decimal("10"),
        low=open_price - Decimal("1"),
        close=open_price + Decimal("5"),
        base_volume=Decimal("1"),
        quote_volume=Decimal("100"),
        trade_count=10,
        vwap=open_price + Decimal("1"),
        source_ts=source_ts or close_ts,
        ingest_ts=START + timedelta(minutes=ingest_offset_minutes - index),
        quality_flags=(),
        raw_payload_id=f"RAW:S6-001:{instrument_id}:{timeframe.upper()}:{index}",
    )


def _intent(
    *,
    submitted_at: datetime = START + timedelta(minutes=1),
    client_order_id: str = "ORDER:S6-001:1",
) -> OrderIntent:
    return OrderIntent(
        client_order_id=client_order_id,
        trace_id="TRACE:S6-001:1",
        source_decision_id="DECISION:S6-001:BAR0",
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.25"),
        submitted_at=submitted_at,
    )


def _other_instrument_intent(
    *, submitted_at: datetime = START + timedelta(minutes=1)
) -> OrderIntent:
    return OrderIntent(
        client_order_id="ORDER:S6-001:2",
        trace_id="TRACE:S6-001:2",
        source_decision_id="DECISION:S6-001:ETH-BAR0",
        instrument_id="FIXTURE_SPOT:ETH-USD",
        venue_id=VENUE_ID,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        submitted_at=submitted_at,
    )


def test_market_order_fills_next_bar_open_not_signal_bar_close_high_low() -> None:
    bars = (_bar(0), _bar(1), _bar(2))
    report = replay_ohlctv_market_orders(
        bars=bars, order_intents=(_intent(submitted_at=bars[0].close_ts),), run_id="REPLAY:S6-001"
    )

    result = report.results[0]
    assert result.status is ReplayFillStatus.FILLED
    assert result.fill_price == bars[1].open
    assert result.fill_price != bars[0].close
    assert result.fill_price != bars[0].high
    assert result.fill_price != bars[0].low
    assert result.fill_event_open_ts == bars[1].open_ts
    assert result.fill_event_close_ts == bars[1].close_ts
    assert result.submitted_at == bars[0].close_ts


def test_replay_uses_close_ts_availability_not_ingest_ts_ordering() -> None:
    bars = (_bar(0, ingest_offset_minutes=100), _bar(1, ingest_offset_minutes=10))
    report = replay_ohlctv_market_orders(
        bars=bars, order_intents=(_intent(submitted_at=bars[0].close_ts),), run_id="REPLAY:S6-001"
    )

    assert report.results[0].fill_event_close_ts == bars[1].close_ts
    assert report.results[0].fill_price == bars[1].open


def test_duplicate_or_non_monotonic_bars_fail_closed() -> None:
    with pytest.raises(ReplayBuildError, match="duplicate OHLCTV"):
        replay_ohlctv_market_orders(
            bars=(_bar(0), _bar(0)), order_intents=(_intent(),), run_id="REPLAY:S6-001"
        )

    with pytest.raises(ReplayBuildError, match="sorted"):
        replay_ohlctv_market_orders(
            bars=(_bar(1), _bar(0)), order_intents=(_intent(),), run_id="REPLAY:S6-001"
        )


def test_late_source_ohlctv_bar_fails_closed_before_fill() -> None:
    late_bar = _bar(1, source_ts=START + timedelta(minutes=3))

    with pytest.raises(ReplayBuildError, match="source_ts must not be after close_ts"):
        replay_ohlctv_market_orders(
            bars=(_bar(0), late_bar),
            order_intents=(_intent(submitted_at=START + timedelta(minutes=1)),),
            run_id="REPLAY:S6-001",
        )


def test_multi_instrument_bars_are_sorted_by_global_event_time() -> None:
    eth_id = "FIXTURE_SPOT:ETH-USD"
    bars = (
        _bar(0),
        _bar(0, instrument_id=eth_id),
        _bar(1),
        _bar(1, instrument_id=eth_id),
    )

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(
            _intent(submitted_at=bars[0].close_ts),
            _other_instrument_intent(submitted_at=bars[1].close_ts),
        ),
        run_id="REPLAY:S6-001",
    )

    assert tuple(result.status for result in report.results) == (
        ReplayFillStatus.FILLED,
        ReplayFillStatus.FILLED,
    )
    assert report.results[0].fill_event_close_ts == bars[2].close_ts
    assert report.results[1].fill_event_close_ts == bars[3].close_ts


def test_stream_grouped_but_event_time_out_of_order_bars_fail_closed() -> None:
    with pytest.raises(ReplayBuildError, match="sorted by close_ts"):
        replay_ohlctv_market_orders(
            bars=(
                _bar(0),
                _bar(1),
                _bar(0, instrument_id="FIXTURE_SPOT:ETH-USD"),
            ),
            order_intents=(_intent(),),
            run_id="REPLAY:S6-001",
        )


def test_mixed_timeframes_for_same_instrument_venue_fail_closed() -> None:
    with pytest.raises(ReplayBuildError, match="mixed OHLCTV timeframes"):
        replay_ohlctv_market_orders(
            bars=(_bar(0), _bar(1, timeframe="5m")),
            order_intents=(_intent(),),
            run_id="REPLAY:S6-001",
        )


def test_duplicate_client_order_id_fails_closed() -> None:
    duplicate = OrderIntent(
        **_intent().model_dump(exclude={"source_decision_id", "trace_id"}),
        source_decision_id="DECISION:S6-001:DUPLICATE",
        trace_id="TRACE:S6-001:DUPLICATE",
    )

    with pytest.raises(ReplayBuildError, match="duplicate client_order_id"):
        replay_ohlctv_market_orders(
            bars=(_bar(0), _bar(1)),
            order_intents=(_intent(), duplicate),
            run_id="REPLAY:S6-001",
        )


def test_non_monotonic_order_intent_submitted_at_fails_closed_before_replay() -> None:
    bars = (_bar(0), _bar(1), _bar(2))

    with pytest.raises(ReplayBuildError, match="submitted_at/client_order_id"):
        replay_ohlctv_market_orders(
            bars=bars,
            order_intents=(
                _intent(
                    submitted_at=bars[1].close_ts,
                    client_order_id="ORDER:S6-001:2",
                ),
                _intent(
                    submitted_at=bars[0].close_ts,
                    client_order_id="ORDER:S6-001:3",
                ),
            ),
            run_id="REPLAY:S6-001",
        )


def test_equal_timestamp_order_intents_are_sorted_by_client_order_id() -> None:
    bars = (_bar(0), _bar(1), _bar(2))

    with pytest.raises(ReplayBuildError, match="submitted_at/client_order_id"):
        replay_ohlctv_market_orders(
            bars=bars,
            order_intents=(
                _intent(
                    submitted_at=bars[0].close_ts,
                    client_order_id="ORDER:S6-001:B",
                ),
                _intent(
                    submitted_at=bars[0].close_ts,
                    client_order_id="ORDER:S6-001:A",
                ),
            ),
            run_id="REPLAY:S6-001",
        )


def test_missing_future_fill_event_is_explicit_unfilled_result() -> None:
    bars = (_bar(0),)
    report = replay_ohlctv_market_orders(
        bars=bars, order_intents=(_intent(submitted_at=bars[0].close_ts),), run_id="REPLAY:S6-001"
    )

    result = report.results[0]
    assert result.status is ReplayFillStatus.UNFILLED
    assert result.reason is ReplayRejectReason.NO_FUTURE_ELIGIBLE_EVENT
    assert result.fill_price is None
    assert result.filled_quantity == 0


def test_replay_ids_and_hashes_are_deterministic() -> None:
    bars = (_bar(0), _bar(1), _bar(2))
    intent = _intent(submitted_at=bars[0].close_ts)

    first = replay_ohlctv_market_orders(
        bars=bars, order_intents=(intent,), run_id="REPLAY:S6-001"
    )
    second = replay_ohlctv_market_orders(
        bars=bars, order_intents=(intent,), run_id="REPLAY:S6-001"
    )

    assert first.replay_report_id == second.replay_report_id
    assert first.replay_report_hash == second.replay_report_hash
    assert first.market_data_hash == second.market_data_hash
    assert first.result_ids == second.result_ids
