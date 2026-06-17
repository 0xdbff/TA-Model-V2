"""Shared S9 risk test fixtures using real project contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from ta_model.contracts.instrument_master import InstrumentMasterSnapshot, OrderType
from ta_model.contracts.market_data import OHLCTVBar
from ta_model.contracts.risk import (
    EngineLatencyTelemetry,
    ExecutionRejectBurstWindow,
    KillSwitchRecord,
    KillSwitchScope,
    KillSwitchScopeType,
    KillSwitchSnapshot,
    KillSwitchState,
    LiquidityRiskTelemetry,
    LossRiskTelemetry,
    MarketRiskTelemetry,
    ModelRiskTelemetry,
    OrderIdempotencyRecord,
    OrderThrottleWindow,
    PriceRiskTelemetry,
    RiskCheckRequest,
    RiskPolicy,
    TcaRiskTelemetry,
    make_default_risk_policy,
    make_kill_switch_record,
    make_kill_switch_snapshot,
    make_risk_check_request,
    make_unknown_kill_switch_snapshot,
)
from ta_model.contracts.simulation import (
    OrderIntent,
    OrderSide,
    SimulatedAccountState,
    SimulatedBalance,
)
from ta_model.contracts.stream_health import DataHealthSignal

START = datetime(2026, 1, 1, tzinfo=UTC)
FIXTURE = Path("tests/fixtures/instrument_master/valid/mvp_spot_snapshot.json")
VENUE_ID = "COINBASE_SPOT"
INSTRUMENT_ID = "COINBASE_SPOT:BTC-USD"
ACCOUNT_ID = "PAPER_COINBASE_SPOT_001"


def load_snapshot() -> InstrumentMasterSnapshot:
    payload = cast("dict[str, Any]", json.loads(FIXTURE.read_text(encoding="utf-8")))
    return InstrumentMasterSnapshot.model_validate(payload)


def default_policy() -> RiskPolicy:
    return make_default_risk_policy(paper_nav=Decimal("10000"))


def global_scope() -> KillSwitchScope:
    return KillSwitchScope(scope_type=KillSwitchScopeType.GLOBAL)


def kill_record(
    *,
    new_state: KillSwitchState = KillSwitchState.CLEAR,
    prior_state: KillSwitchState = KillSwitchState.UNKNOWN_FAIL_CLOSED,
    cancel_open_orders: bool = False,
) -> KillSwitchRecord:
    return make_kill_switch_record(
        scope=global_scope(),
        prior_state=prior_state,
        new_state=new_state,
        actor="s9-risk-test-operator",
        actor_role="risk_owner",
        transitioned_at=START,
        reason="test fixture state transition",
        cancel_open_orders=cancel_open_orders,
    )


def kill_snapshot(*, state: KillSwitchState = KillSwitchState.CLEAR) -> KillSwitchSnapshot:
    if state is KillSwitchState.UNKNOWN_FAIL_CLOSED:
        return make_unknown_kill_switch_snapshot(
            evaluated_at=START + timedelta(minutes=1),
            evaluated_scopes=(global_scope(),),
            store_available=False,
            reason="test unknown kill state",
        )
    record = kill_record(new_state=state)
    return make_kill_switch_snapshot(
        evaluated_at=START + timedelta(minutes=1),
        evaluated_scopes=(global_scope(),),
        active_state=state,
        active_records=(record,),
        store_available=True,
        reason="test kill state loaded",
    )


def account_state(
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


def bar(index: int, *, open_price: Decimal = Decimal("100")) -> OHLCTVBar:
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
        base_volume=Decimal("100"),
        quote_volume=open_price * Decimal("100"),
        trade_count=10,
        vwap=open_price,
        source_ts=close_ts,
        ingest_ts=START + timedelta(minutes=100 - index),
        quality_flags=(),
        raw_payload_id=f"RAW:S9:{index}",
    )


def intent(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("1"),
    submitted_at: datetime = START + timedelta(minutes=1),
    order_id: str = "ORDER:S9:1",
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


def risk_request(
    *,
    order_intent: OrderIntent | None = None,
    decision_ts: datetime = START + timedelta(minutes=1),
    risk_check_ts: datetime = START + timedelta(minutes=1, seconds=1),
    reference_price: Decimal = Decimal("100"),
    current_cash: Decimal = Decimal("10000"),
    account_equity: Decimal = Decimal("10000"),
    current_position_quantity: Decimal = Decimal("0"),
    current_instrument_exposure: Decimal = Decimal("0"),
    current_strategy_exposure: Decimal = Decimal("0"),
    current_total_spot_exposure: Decimal = Decimal("0"),
    instrument_master_snapshot: InstrumentMasterSnapshot | None = None,
    kill_state: KillSwitchState = KillSwitchState.CLEAR,
    price_risk: PriceRiskTelemetry | None = None,
    loss_risk: LossRiskTelemetry | None = None,
    liquidity_risk: LiquidityRiskTelemetry | None = None,
    market_risk: MarketRiskTelemetry | None = None,
    engine_latency: EngineLatencyTelemetry | None = None,
    model_risk: ModelRiskTelemetry | None = None,
    tca_risk: TcaRiskTelemetry | None = None,
    idempotency_records: tuple[OrderIdempotencyRecord, ...] = (),
    throttle_windows: tuple[OrderThrottleWindow, ...] = (),
    reject_burst_windows: tuple[ExecutionRejectBurstWindow, ...] = (),
    data_health_signals: tuple[DataHealthSignal, ...] = (),
) -> RiskCheckRequest:
    actual_intent = order_intent or intent()
    return make_risk_check_request(
        run_id="RUN:S9:RISK-TEST",
        decision_ts=decision_ts,
        risk_check_ts=risk_check_ts,
        strategy_version="strategy:s9-risk-fixture:1.0.0",
        account_id=ACCOUNT_ID,
        order_intent=actual_intent,
        reference_price=reference_price,
        account_equity=account_equity,
        current_cash=current_cash,
        current_instrument_position_quantity=current_position_quantity,
        current_instrument_exposure_notional=current_instrument_exposure,
        current_strategy_exposure_notional=current_strategy_exposure,
        current_total_spot_exposure_notional=current_total_spot_exposure,
        instrument_master_snapshot=instrument_master_snapshot or load_snapshot(),
        kill_switch_snapshot=kill_snapshot(state=kill_state),
        price_risk=price_risk,
        loss_risk=loss_risk,
        liquidity_risk=liquidity_risk,
        market_risk=market_risk,
        engine_latency=engine_latency,
        model_risk=model_risk,
        tca_risk=tca_risk,
        data_health_signals=data_health_signals,
        idempotency_records=idempotency_records,
        throttle_windows=throttle_windows,
        reject_burst_windows=reject_burst_windows,
    )
