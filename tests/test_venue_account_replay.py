"""Evidence for S6-003 simulator venue/account feasibility enforcement."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from ta_model.contracts.instrument_master import InstrumentMasterSnapshot, OrderType
from ta_model.contracts.market_data import OHLCTVBar
from ta_model.contracts.simulation import (
    OrderIntent,
    OrderSide,
    ReplayFillStatus,
    ReplayRejectionCount,
    ReplayRejectReason,
    ReplayReport,
    SimulatedAccountState,
    SimulatedBalance,
    build_replay_report_hash,
    build_replay_report_id,
    make_execution_cost_model,
)
from ta_model.simulation.replay import replay_ohlctv_market_orders

START = datetime(2026, 1, 1, tzinfo=UTC)
FIXTURE = Path("tests/fixtures/instrument_master/valid/mvp_spot_snapshot.json")
VENUE_ID = "COINBASE_SPOT"
INSTRUMENT_ID = "COINBASE_SPOT:BTC-USD"
ACCOUNT_ID = "PAPER_COINBASE_SPOT_001"


def _snapshot(
    *,
    venue_status: str = "active",
    instrument_status: str = "trading",
    account_status: str = "active",
    min_notional: str = "1.00",
    market_supported: bool = True,
) -> InstrumentMasterSnapshot:
    payload = json.loads(FIXTURE.read_text())
    payload["venues"][0]["status"] = venue_status
    payload["instruments"][0]["status"] = instrument_status
    payload["accounts"][0]["status"] = account_status
    payload["instrument_constraints"][0]["min_notional"] = min_notional
    payload["instruments"][0]["min_notional"] = min_notional
    if not market_supported:
        payload["venues"][0]["supported_order_types"] = ["limit"]
        for instrument in payload["instruments"]:
            instrument["supported_order_types"] = ["limit"]
    return InstrumentMasterSnapshot.model_validate(payload)


def _snapshot_without_place_orders() -> InstrumentMasterSnapshot:
    payload = json.loads(FIXTURE.read_text())
    payload["accounts"][0]["trading_permissions"] = ["read_market_data", "view_balances"]
    return InstrumentMasterSnapshot.model_validate(payload)


def _snapshot_with_constraint_rollover() -> InstrumentMasterSnapshot:
    payload = json.loads(FIXTURE.read_text())
    old_constraint = payload["instrument_constraints"][0]
    old_constraint["effective_to"] = "2026-01-01T00:02:00Z"
    new_constraint = dict(old_constraint)
    new_constraint["constraint_id"] = "COINBASE_SPOT:BTC-USD:CONSTRAINTS:STRICT:2026Q1"
    new_constraint["min_notional"] = "1000.00"
    new_constraint["effective_from"] = "2026-01-01T00:02:00Z"
    new_constraint["effective_to"] = None
    payload["instrument_constraints"].append(new_constraint)
    return InstrumentMasterSnapshot.model_validate(payload)


def _account_state(
    *, usd: Decimal = Decimal("1000"), btc: Decimal = Decimal("1")
) -> SimulatedAccountState:
    return SimulatedAccountState(
        account_id=ACCOUNT_ID,
        balances=(
            SimulatedBalance(
                account_id=ACCOUNT_ID, venue_id=VENUE_ID, asset_id="USD", available=usd
            ),
            SimulatedBalance(
                account_id=ACCOUNT_ID, venue_id=VENUE_ID, asset_id="BTC", available=btc
            ),
        ),
    )


def _bar(index: int, *, open_price: Decimal = Decimal("100")) -> OHLCTVBar:
    open_ts = START + timedelta(minutes=index)
    close_ts = open_ts + timedelta(minutes=1)
    return OHLCTVBar(
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        timeframe="1m",
        open_ts=open_ts,
        close_ts=close_ts,
        open=open_price,
        high=open_price + Decimal("1"),
        low=open_price - Decimal("1"),
        close=open_price,
        base_volume=Decimal("10"),
        quote_volume=open_price * Decimal("10"),
        trade_count=10,
        vwap=open_price,
        source_ts=close_ts,
        ingest_ts=START + timedelta(minutes=100 - index),
        quality_flags=(),
        raw_payload_id=f"RAW:S6-003:{index}",
    )


def _intent(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("1"),
    submitted_at: datetime,
    order_id: str = "ORDER:S6-003:1",
) -> OrderIntent:
    return OrderIntent(
        client_order_id=order_id,
        trace_id=f"TRACE:{order_id}",
        source_decision_id=f"DECISION:{order_id}",
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        submitted_at=submitted_at,
    )


def _balance(report_asset_state: SimulatedAccountState, asset_id: str) -> Decimal:
    return next(
        balance.available for balance in report_asset_state.balances if balance.asset_id == asset_id
    )


def test_successful_buy_and_sell_update_balances_with_costs() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")), _bar(2, open_price=Decimal("110")))
    model = make_execution_cost_model(
        taker_fee_rate=Decimal("0.001"), spread_bps=Decimal("0"), slippage_bps=Decimal("0")
    )

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(
            _intent(
                quantity=Decimal("1"),
                submitted_at=bars[0].close_ts,
                order_id="ORDER:S6-003:B",
            ),
            _intent(
                side=OrderSide.SELL,
                quantity=Decimal("0.5"),
                submitted_at=bars[1].close_ts,
                order_id="ORDER:S6-003:S",
            ),
        ),
        run_id="REPLAY:S6-003:BALANCES",
        execution_cost_model=model,
        instrument_master_snapshot=_snapshot(),
        starting_account_state=_account_state(usd=Decimal("1000"), btc=Decimal("1")),
    )

    assert tuple(result.status for result in report.results) == (
        ReplayFillStatus.FILLED,
        ReplayFillStatus.FILLED,
    )
    assert report.final_account_state is not None
    assert _balance(report.final_account_state, "BTC") == Decimal("1.5")
    assert _balance(report.final_account_state, "USD") == Decimal("954.8450")
    assert report.rejection_counts == ()
    assert report.requirement_ids == ("FR-012", "NFR-001", "RISK-005", "FR-003", "FR-010")


def test_insufficient_cash_rejects_before_state_mutation() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:CASH",
        instrument_master_snapshot=_snapshot(),
        starting_account_state=_account_state(usd=Decimal("99"), btc=Decimal("1")),
    )

    assert report.results[0].status is ReplayFillStatus.REJECTED
    assert report.results[0].reason is ReplayRejectReason.INSUFFICIENT_CASH
    assert report.final_account_state is not None
    assert _balance(report.final_account_state, "USD") == Decimal("99")
    assert _balance(report.final_account_state, "BTC") == Decimal("1")


def test_insufficient_inventory_rejects_no_shorting_before_state_mutation() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(
            _intent(
                side=OrderSide.SELL,
                quantity=Decimal("2"),
                submitted_at=bars[0].close_ts,
            ),
        ),
        run_id="REPLAY:S6-003:INVENTORY",
        instrument_master_snapshot=_snapshot(),
        starting_account_state=_account_state(usd=Decimal("1000"), btc=Decimal("1")),
    )

    assert report.results[0].status is ReplayFillStatus.REJECTED
    assert report.results[0].reason is ReplayRejectReason.INSUFFICIENT_INVENTORY
    assert report.final_account_state is not None
    assert _balance(report.final_account_state, "BTC") == Decimal("1")


def test_inactive_venue_fails_closed_with_rejection_accounting() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:VENUE",
        instrument_master_snapshot=_snapshot(venue_status="maintenance"),
        starting_account_state=_account_state(),
    )

    assert report.results[0].status is ReplayFillStatus.REJECTED
    assert report.results[0].reason is ReplayRejectReason.VENUE_NOT_TRADABLE
    assert [(item.reason, item.count) for item in report.rejection_counts] == [
        (ReplayRejectReason.VENUE_NOT_TRADABLE, 1)
    ]


def test_inactive_instrument_fails_closed_before_balance_mutation() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:INSTRUMENT",
        instrument_master_snapshot=_snapshot(instrument_status="paused"),
        starting_account_state=_account_state(),
    )

    assert report.results[0].status is ReplayFillStatus.REJECTED
    assert report.results[0].reason is ReplayRejectReason.INSTRUMENT_NOT_TRADABLE
    assert report.final_account_state is not None
    assert _balance(report.final_account_state, "USD") == Decimal("1000")
    assert _balance(report.final_account_state, "BTC") == Decimal("1")


def test_disabled_account_fails_closed_before_balance_mutation() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:ACCOUNT-DISABLED",
        instrument_master_snapshot=_snapshot(account_status="disabled"),
        starting_account_state=_account_state(),
    )

    assert report.results[0].status is ReplayFillStatus.REJECTED
    assert report.results[0].reason is ReplayRejectReason.ACCOUNT_NOT_TRADABLE
    assert report.final_account_state is not None
    assert _balance(report.final_account_state, "USD") == Decimal("1000")


def test_missing_place_order_permission_fails_closed() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:ACCOUNT-PERMISSION",
        instrument_master_snapshot=_snapshot_without_place_orders(),
        starting_account_state=_account_state(),
    )

    assert report.results[0].status is ReplayFillStatus.REJECTED
    assert report.results[0].reason is ReplayRejectReason.ACCOUNT_NOT_TRADABLE


def test_unsupported_order_type_from_metadata_fails_closed() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:ORDER-TYPE",
        instrument_master_snapshot=_snapshot(market_supported=False),
        starting_account_state=_account_state(),
    )

    assert report.results[0].status is ReplayFillStatus.REJECTED
    assert report.results[0].reason is ReplayRejectReason.UNSUPPORTED_ORDER_TYPE


def test_constraint_violation_rejects_and_is_counted() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("0.001"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:CONSTRAINT",
        instrument_master_snapshot=_snapshot(min_notional="1.00"),
        starting_account_state=_account_state(),
    )

    assert report.results[0].status is ReplayFillStatus.REJECTED
    assert report.results[0].reason is ReplayRejectReason.CONSTRAINT_VIOLATION
    assert [(item.reason, item.count) for item in report.rejection_counts] == [
        (ReplayRejectReason.CONSTRAINT_VIOLATION, 1)
    ]


def test_tick_size_constraint_violation_rejects() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100.001")))

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:TICK",
        instrument_master_snapshot=_snapshot(),
        starting_account_state=_account_state(),
    )

    assert report.results[0].status is ReplayFillStatus.REJECTED
    assert report.results[0].reason is ReplayRejectReason.CONSTRAINT_VIOLATION


def test_lot_size_constraint_violation_rejects() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(
            _intent(quantity=Decimal("1.000000001"), submitted_at=bars[0].close_ts),
        ),
        run_id="REPLAY:S6-003:LOT",
        instrument_master_snapshot=_snapshot(),
        starting_account_state=_account_state(),
    )

    assert report.results[0].status is ReplayFillStatus.REJECTED
    assert report.results[0].reason is ReplayRejectReason.CONSTRAINT_VIOLATION


def test_latency_constraint_rollover_uses_fill_attempt_event_time() -> None:
    bars = (
        _bar(0, open_price=Decimal("100")),
        _bar(1, open_price=Decimal("100")),
        _bar(2, open_price=Decimal("100")),
    )
    model = make_execution_cost_model(
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        latency_bars=1,
    )

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:ROLLOVER",
        execution_cost_model=model,
        instrument_master_snapshot=_snapshot_with_constraint_rollover(),
        starting_account_state=_account_state(),
    )

    result = report.results[0]
    assert result.status is ReplayFillStatus.REJECTED
    assert result.reason is ReplayRejectReason.CONSTRAINT_VIOLATION
    assert result.fill_attempt_event_index == 2


def test_latency_past_available_events_returns_no_future_before_constraints() -> None:
    bars = (_bar(0, open_price=Decimal("100")), _bar(1, open_price=Decimal("100")))
    model = make_execution_cost_model(
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        latency_bars=1,
    )

    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:LATENCY-MISSING",
        execution_cost_model=model,
        instrument_master_snapshot=_snapshot(min_notional="1000.00"),
        starting_account_state=_account_state(),
    )

    assert report.results[0].status is ReplayFillStatus.UNFILLED
    assert report.results[0].reason is ReplayRejectReason.NO_FUTURE_ELIGIBLE_EVENT


def test_replay_report_rejects_mismatched_rejection_counts_even_with_rebuilt_hash() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))
    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:MISMATCHED-COUNTS",
        instrument_master_snapshot=_snapshot(),
        starting_account_state=_account_state(usd=Decimal("99"), btc=Decimal("1")),
    )
    mismatched_counts = (
        ReplayRejectionCount(reason=ReplayRejectReason.VENUE_NOT_TRADABLE, count=1),
    )
    report_hash = build_replay_report_hash(
        run_id=report.run_id,
        market_data_hash=report.market_data_hash,
        results=report.results,
        requirement_ids=report.requirement_ids,
        rejection_counts=mismatched_counts,
        final_account_state=report.final_account_state,
    )

    with pytest.raises(ValidationError, match="rejection_counts"):
        ReplayReport(
            **report.model_dump(
                exclude={"replay_report_id", "replay_report_hash", "rejection_counts"}
            ),
            rejection_counts=mismatched_counts,
            replay_report_hash=report_hash,
            replay_report_id=build_replay_report_id(replay_report_hash=report_hash),
        )


def test_replay_report_rejects_empty_counts_for_rejected_result_with_rebuilt_hash() -> None:
    bars = (_bar(0), _bar(1, open_price=Decimal("100")))
    report = replay_ohlctv_market_orders(
        bars=bars,
        order_intents=(_intent(quantity=Decimal("1"), submitted_at=bars[0].close_ts),),
        run_id="REPLAY:S6-003:EMPTY-COUNTS",
        instrument_master_snapshot=_snapshot(),
        starting_account_state=_account_state(usd=Decimal("99"), btc=Decimal("1")),
    )
    report_hash = build_replay_report_hash(
        run_id=report.run_id,
        market_data_hash=report.market_data_hash,
        results=report.results,
        requirement_ids=report.requirement_ids,
        rejection_counts=(),
        final_account_state=report.final_account_state,
    )

    with pytest.raises(ValidationError, match="rejection_counts"):
        ReplayReport(
            **report.model_dump(
                exclude={"replay_report_id", "replay_report_hash", "rejection_counts"}
            ),
            rejection_counts=(),
            replay_report_hash=report_hash,
            replay_report_id=build_replay_report_id(replay_report_hash=report_hash),
        )


def test_zero_count_rejection_accounting_is_invalid() -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        ReplayRejectionCount(reason=ReplayRejectReason.INSUFFICIENT_CASH, count=0)
