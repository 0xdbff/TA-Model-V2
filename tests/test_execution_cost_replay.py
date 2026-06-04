"""Evidence for S6-002 execution-cost and fill realism replay layer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ta_model.contracts.instrument_master import OrderType
from ta_model.contracts.market_data import OHLCTVBar
from ta_model.contracts.simulation import (
    ExecutionCostModel,
    OrderIntent,
    OrderSide,
    ReplayFillStatus,
    ReplayOrderResult,
    ReplayRejectReason,
    build_replay_order_result_id,
    make_execution_cost_model,
)
from ta_model.simulation.replay import replay_ohlctv_market_orders

START = datetime(2026, 1, 1, tzinfo=UTC)
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"
VENUE_ID = "FIXTURE_SPOT"


def _bar(index: int, *, base_volume: Decimal = Decimal("10")) -> OHLCTVBar:
    open_ts = START + timedelta(minutes=index)
    close_ts = open_ts + timedelta(minutes=1)
    open_price = Decimal("100") + Decimal(index)
    return OHLCTVBar(
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        timeframe="1m",
        open_ts=open_ts,
        close_ts=close_ts,
        open=open_price,
        high=open_price + Decimal("10"),
        low=open_price - Decimal("1"),
        close=open_price + Decimal("5"),
        base_volume=base_volume,
        quote_volume=open_price * base_volume,
        trade_count=10,
        vwap=open_price + Decimal("1"),
        source_ts=close_ts,
        ingest_ts=START + timedelta(minutes=100 - index),
        quality_flags=(),
        raw_payload_id=f"RAW:S6-002:{index}",
    )


def _intent(
    *,
    quantity: Decimal = Decimal("1"),
    submitted_at: datetime,
    side: OrderSide = OrderSide.BUY,
) -> OrderIntent:
    return OrderIntent(
        client_order_id="ORDER:S6-002:1",
        trace_id="TRACE:S6-002:1",
        source_decision_id="DECISION:S6-002:BAR0",
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        submitted_at=submitted_at,
    )


def _cost_model(
    *,
    fee: Decimal = Decimal("0.001"),
    spread_bps: Decimal = Decimal("5"),
    slippage_bps: Decimal = Decimal("10"),
    latency_bars: int = 0,
    participation: Decimal = Decimal("1"),
) -> ExecutionCostModel:
    return make_execution_cost_model(
        taker_fee_rate=fee,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        latency_bars=latency_bars,
        max_participation_rate=participation,
    )


def test_cost_replay_full_fill_has_explicit_deterministic_attribution() -> None:
    bars = (_bar(0), _bar(1), _bar(2))
    model = _cost_model()

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-002",
        execution_cost_model=model,
    )

    result = report.results[0]
    assert report.requirement_ids == ("FR-012", "NFR-001", "RISK-005")
    assert result.status is ReplayFillStatus.FILLED
    assert result.arrival_reference_price == bars[1].open
    assert result.fill_price == Decimal("101") * Decimal("1.0015")
    assert result.effective_fill_price == result.fill_price
    assert result.remaining_quantity == 0
    assert result.fee_cost > 0
    assert result.spread_cost > 0
    assert result.slippage_cost > 0
    assert result.total_cost == result.fee_cost + result.spread_cost + result.slippage_cost
    assert result.cost_model_id == model.cost_model_id
    assert result.cost_model_hash == model.cost_model_hash


def _rebuild_malformed_result(candidate: ReplayOrderResult) -> None:
    result_id = build_replay_order_result_id(result=candidate)
    ReplayOrderResult(
        **candidate.model_dump(exclude={"replay_order_result_id"}),
        replay_order_result_id=result_id,
    )


def test_malformed_total_cost_is_rejected_even_with_rebuilt_id() -> None:
    bars = (_bar(0), _bar(1))
    good = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-002-MALFORMED",
        execution_cost_model=_cost_model(),
    ).results[0]
    malformed = ReplayOrderResult.model_construct(
        **good.model_dump(exclude={"replay_order_result_id", "total_cost"}),
        replay_order_result_id="REPLAYORDER:MALFORMED",
        total_cost=good.total_cost + Decimal("1"),
    )

    with pytest.raises(ValidationError, match="total_cost"):
        _rebuild_malformed_result(malformed)


def test_malformed_reference_notional_is_rejected_even_with_rebuilt_id() -> None:
    bars = (_bar(0), _bar(1))
    good = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-002-MALFORMED",
        execution_cost_model=_cost_model(),
    ).results[0]
    malformed = ReplayOrderResult.model_construct(
        **good.model_dump(exclude={"replay_order_result_id", "reference_notional"}),
        replay_order_result_id="REPLAYORDER:MALFORMED",
        reference_notional=good.reference_notional + Decimal("1"),
    )

    with pytest.raises(ValidationError, match="reference_notional"):
        _rebuild_malformed_result(malformed)


def test_cost_model_identity_hash_pairing_is_required() -> None:
    bars = (_bar(0), _bar(1))
    good = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-002-MALFORMED",
        execution_cost_model=_cost_model(),
    ).results[0]
    malformed = ReplayOrderResult.model_construct(
        **good.model_dump(exclude={"replay_order_result_id", "cost_model_hash"}),
        replay_order_result_id="REPLAYORDER:MALFORMED",
        cost_model_hash=None,
    )

    with pytest.raises(ValidationError, match="cost_model_id and cost_model_hash"):
        _rebuild_malformed_result(malformed)


def test_partial_fill_caps_quantity_by_bar_participation() -> None:
    bars = (_bar(0), _bar(1, base_volume=Decimal("2")))
    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("5"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-002",
        execution_cost_model=_cost_model(participation=Decimal("0.25")),
    )

    result = report.results[0]
    assert result.status is ReplayFillStatus.PARTIALLY_FILLED
    assert result.filled_quantity == Decimal("0.50")
    assert result.remaining_quantity == Decimal("4.50")
    assert result.total_cost > 0


def test_failed_fill_when_partial_disallowed_and_liquidity_insufficient() -> None:
    bars = (_bar(0), _bar(1, base_volume=Decimal("1")))
    model = make_execution_cost_model(
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("5"),
        slippage_bps=Decimal("10"),
        max_participation_rate=Decimal("0.25"),
        allow_partial_fills=False,
    )
    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("5"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-002",
        execution_cost_model=model,
    )

    result = report.results[0]
    assert result.status is ReplayFillStatus.UNFILLED
    assert result.reason is ReplayRejectReason.INSUFFICIENT_LIQUIDITY
    assert result.filled_quantity == 0
    assert result.remaining_quantity == Decimal("5")


def test_latency_skips_future_eligible_bar_and_preserves_no_same_bar_rule() -> None:
    bars = (_bar(0), _bar(1), _bar(2), _bar(3))
    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-002",
        execution_cost_model=_cost_model(latency_bars=1),
    )

    result = report.results[0]
    assert result.fill_event_open_ts == bars[2].open_ts
    assert result.eligible_event_index == 1
    assert result.fill_attempt_event_index == 2
    assert result.fill_price != bars[0].close
    assert result.fill_price != bars[0].high
    assert result.fill_price != bars[0].low


def test_latency_past_available_data_is_explicit_unfilled() -> None:
    bars = (_bar(0), _bar(1))
    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-002",
        execution_cost_model=_cost_model(latency_bars=2),
    )

    result = report.results[0]
    assert result.status is ReplayFillStatus.UNFILLED
    assert result.reason is ReplayRejectReason.NO_FUTURE_ELIGIBLE_EVENT
    assert result.cost_model_id is not None


def test_higher_stress_costs_worsen_effective_execution_and_total_cost() -> None:
    bars = (_bar(0), _bar(1))
    intent = _intent(submitted_at=bars[0].close_ts)
    low = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(intent,),
        run_id="REPLAY:S6-002-STRESS",
        execution_cost_model=_cost_model(spread_bps=Decimal("1"), slippage_bps=Decimal("1")),
    ).results[0]
    high = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(intent,),
        run_id="REPLAY:S6-002-STRESS",
        execution_cost_model=_cost_model(spread_bps=Decimal("20"), slippage_bps=Decimal("30")),
    ).results[0]

    assert high.total_cost > low.total_cost
    assert high.fill_price is not None
    assert low.fill_price is not None
    assert high.fill_price > low.fill_price
    assert high.replay_order_result_id != low.replay_order_result_id


def test_sell_side_higher_stress_costs_lower_effective_price_and_raise_cost() -> None:
    bars = (_bar(0), _bar(1))
    intent = _intent(submitted_at=bars[0].close_ts, side=OrderSide.SELL)
    low = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(intent,),
        run_id="REPLAY:S6-002-SELL-STRESS",
        execution_cost_model=_cost_model(spread_bps=Decimal("1"), slippage_bps=Decimal("1")),
    ).results[0]
    high = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(intent,),
        run_id="REPLAY:S6-002-SELL-STRESS",
        execution_cost_model=_cost_model(spread_bps=Decimal("20"), slippage_bps=Decimal("30")),
    ).results[0]

    assert high.total_cost > low.total_cost
    assert high.fill_price is not None
    assert low.fill_price is not None
    assert high.fill_price < low.fill_price


def test_cost_model_ids_and_replay_hashes_are_deterministic() -> None:
    bars = (_bar(0), _bar(1))
    intent = _intent(submitted_at=bars[0].close_ts)
    first_model = _cost_model(latency_bars=0)
    second_model = _cost_model(latency_bars=0)

    first = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(intent,),
        run_id="REPLAY:S6-002-DETERMINISTIC",
        execution_cost_model=first_model,
    )
    second = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(intent,),
        run_id="REPLAY:S6-002-DETERMINISTIC",
        execution_cost_model=second_model,
    )

    assert first_model.cost_model_id == second_model.cost_model_id
    assert first.result_ids == second.result_ids
    assert first.replay_report_hash == second.replay_report_hash
