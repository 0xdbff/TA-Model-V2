"""Deterministic fake-asset scenarios for S6 integrated replay QA.

Traceability:
- FR-012: scenarios execute the real event-time replay simulator path.
- RISK-001: crash scenario captures market drawdown stress evidence.
- RISK-002: liquidity and outage scenarios capture fail-closed stress evidence.

All data is synthetic/local.  The suite preserves MVP spot-only constraints and
does not introduce live capital, leverage, derivatives, margin, shorting, market
making, HFT, strategy/model logic, paper gateways, risk engines, or kill switches.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import Random

from ta_model.contracts.instrument_master import InstrumentMasterSnapshot, OrderType
from ta_model.contracts.market_data import OHLCTVBar, QualityFlag
from ta_model.contracts.scenarios import (
    SyntheticScenarioId,
    SyntheticScenarioResult,
    SyntheticScenarioSuiteReport,
    make_synthetic_scenario_suite_report,
)
from ta_model.contracts.simulation import (
    OrderIntent,
    OrderSide,
    ReplayReport,
    SimulatedAccountState,
    SimulatedBalance,
    make_execution_cost_model,
)
from ta_model.simulation.replay import replay_ohlctv_market_orders

START = datetime(2026, 1, 1, tzinfo=UTC)
VENUE_ID = "SYNTH_SPOT"
INSTRUMENT_ID = "SYNTH_SPOT:FAKE-USD"
ACCOUNT_ID = "SIM_SYNTH_SPOT_001"


def run_synthetic_scenario_suite(
    *, seed: int = 6004, run_id: str = "SYNTHETIC:S6-004:SUITE"
) -> SyntheticScenarioSuiteReport:
    """Run all required fake-asset scenarios through integrated S6 replay."""

    rng = Random(seed)
    scenario_results = (
        _run_random_walk(rng=rng),
        _run_trend(),
        _run_crash(),
        _run_spread(),
        _run_liquidity(),
        _run_outage(),
    )
    return make_synthetic_scenario_suite_report(
        run_id=run_id, seed=seed, scenario_results=scenario_results
    )


def _run_random_walk(*, rng: Random) -> SyntheticScenarioResult:
    prices = _random_walk_prices(rng=rng, start=Decimal("100.00"), count=5)
    bars = _bars(SyntheticScenarioId.RANDOM_WALK, prices=prices)
    report = _replay(
        scenario_id=SyntheticScenarioId.RANDOM_WALK,
        bars=bars,
        intents=(
            _intent(
                SyntheticScenarioId.RANDOM_WALK,
                order_index=1,
                submitted_at=bars[0].close_ts,
                quantity=Decimal("1"),
            ),
        ),
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("4"),
        slippage_bps=Decimal("6"),
    )
    return _summary(
        scenario_id=SyntheticScenarioId.RANDOM_WALK,
        name="Deterministic baseline random-walk fills with costs",
        traceability=("FR-012",),
        labels=("fake_data", "baseline_fill_cost"),
        bars=bars,
        report=report,
    )


def _run_trend() -> SyntheticScenarioResult:
    bars = _bars(
        SyntheticScenarioId.TREND,
        prices=(Decimal("100"), Decimal("102"), Decimal("104"), Decimal("106")),
    )
    report = _replay(
        scenario_id=SyntheticScenarioId.TREND,
        bars=bars,
        intents=(
            _intent(SyntheticScenarioId.TREND, order_index=1, submitted_at=bars[0].close_ts),
            _intent(
                SyntheticScenarioId.TREND,
                order_index=2,
                submitted_at=bars[1].close_ts,
                side=OrderSide.SELL,
                quantity=Decimal("0.50"),
            ),
        ),
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("2"),
        slippage_bps=Decimal("3"),
    )
    return _summary(
        scenario_id=SyntheticScenarioId.TREND,
        name="Directional trend with deterministic buy/sell balance accounting",
        traceability=("FR-012",),
        labels=("fake_data", "inventory_accounting"),
        bars=bars,
        report=report,
    )


def _run_crash() -> SyntheticScenarioResult:
    bars = _bars(
        SyntheticScenarioId.CRASH,
        prices=(Decimal("100"), Decimal("92"), Decimal("78"), Decimal("61")),
    )
    report = _replay(
        scenario_id=SyntheticScenarioId.CRASH,
        bars=bars,
        intents=(
            _intent(SyntheticScenarioId.CRASH, order_index=1, submitted_at=bars[0].close_ts),
        ),
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("6"),
        slippage_bps=Decimal("10"),
    )
    return _summary(
        scenario_id=SyntheticScenarioId.CRASH,
        name="Market drawdown stress path; evidence only, not strategy success",
        traceability=("FR-012", "RISK-001"),
        labels=("fake_data", "market_drawdown", "RISK-001"),
        bars=bars,
        report=report,
    )


def _run_spread() -> SyntheticScenarioResult:
    bars = _bars(
        SyntheticScenarioId.SPREAD,
        prices=(Decimal("100"), Decimal("100.5"), Decimal("101")),
    )
    intent = _intent(SyntheticScenarioId.SPREAD, order_index=1, submitted_at=bars[0].close_ts)
    low_cost = _replay(
        scenario_id=SyntheticScenarioId.SPREAD,
        bars=bars,
        intents=(intent,),
        run_suffix="LOWCOST",
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("1"),
        slippage_bps=Decimal("1"),
    )
    high_cost = _replay(
        scenario_id=SyntheticScenarioId.SPREAD,
        bars=bars,
        intents=(intent,),
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("60"),
        slippage_bps=Decimal("90"),
    )
    return _summary(
        scenario_id=SyntheticScenarioId.SPREAD,
        name="High spread/slippage stress with explicit cost comparison",
        traceability=("FR-012", "RISK-002", "RISK-005"),
        labels=("fake_data", "cost_sensitivity", "liquidity_cost_stress"),
        bars=bars,
        report=high_cost,
        comparison_total_cost=sum((result.total_cost for result in low_cost.results), Decimal("0")),
    )


def _run_liquidity() -> SyntheticScenarioResult:
    bars = _bars(
        SyntheticScenarioId.LIQUIDITY,
        prices=(Decimal("100"), Decimal("99"), Decimal("98")),
        volumes=(Decimal("10"), Decimal("2"), Decimal("0")),
        quality_flags=((), (), (QualityFlag.MISSING,)),
    )
    report = _replay(
        scenario_id=SyntheticScenarioId.LIQUIDITY,
        bars=bars,
        intents=(
            _intent(
                SyntheticScenarioId.LIQUIDITY,
                order_index=1,
                submitted_at=bars[0].close_ts,
                quantity=Decimal("5"),
            ),
            _intent(
                SyntheticScenarioId.LIQUIDITY,
                order_index=2,
                submitted_at=bars[1].close_ts,
                quantity=Decimal("1"),
            ),
        ),
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("20"),
        slippage_bps=Decimal("40"),
        max_participation_rate=Decimal("0.25"),
    )
    return _summary(
        scenario_id=SyntheticScenarioId.LIQUIDITY,
        name="Liquidity collapse produces partial and failed fills",
        traceability=("FR-012", "RISK-002"),
        labels=("fake_data", "liquidity_collapse", "RISK-002"),
        bars=bars,
        report=report,
    )


def _run_outage() -> SyntheticScenarioResult:
    bars = _bars(
        SyntheticScenarioId.OUTAGE,
        prices=(Decimal("100"),),
        quality_flags=((QualityFlag.MISSING,),),
    )
    report = _replay(
        scenario_id=SyntheticScenarioId.OUTAGE,
        bars=bars,
        intents=(
            _intent(SyntheticScenarioId.OUTAGE, order_index=1, submitted_at=bars[0].close_ts),
        ),
        venue_status="maintenance",
        taker_fee_rate=Decimal("0.001"),
        spread_bps=Decimal("5"),
        slippage_bps=Decimal("5"),
    )
    return _summary(
        scenario_id=SyntheticScenarioId.OUTAGE,
        name="Venue outage fail-closed rejection with no future eligible event",
        traceability=("FR-012", "RISK-002"),
        labels=("fake_data", "venue_outage", "fail_closed", "RISK-002"),
        bars=bars,
        report=report,
    )


def _random_walk_prices(*, rng: Random, start: Decimal, count: int) -> tuple[Decimal, ...]:
    prices = [start]
    for _ in range(count - 1):
        step_cents = rng.choice((-35, -20, -5, 10, 25, 40))
        prices.append(max(Decimal("1"), prices[-1] + Decimal(step_cents) / Decimal("100")))
    return tuple(prices)


def _bars(
    scenario_id: SyntheticScenarioId,
    *,
    prices: tuple[Decimal, ...],
    volumes: tuple[Decimal, ...] | None = None,
    quality_flags: tuple[tuple[QualityFlag, ...], ...] | None = None,
) -> tuple[OHLCTVBar, ...]:
    result: list[OHLCTVBar] = []
    volume_values = volumes or tuple(Decimal("10") for _ in prices)
    flag_values = quality_flags or tuple(() for _ in prices)
    for index, close_price in enumerate(prices):
        open_ts = START + timedelta(minutes=index)
        close_ts = open_ts + timedelta(minutes=1)
        previous = prices[index - 1] if index else close_price
        high = max(previous, close_price) + Decimal("0.50")
        low = max(Decimal("0"), min(previous, close_price) - Decimal("0.50"))
        volume = volume_values[index]
        result.append(
            OHLCTVBar(
                instrument_id=INSTRUMENT_ID,
                venue_id=VENUE_ID,
                timeframe="1m",
                open_ts=open_ts,
                close_ts=close_ts,
                open=previous,
                high=high,
                low=low,
                close=close_price,
                base_volume=volume,
                quote_volume=previous * volume,
                trade_count=10 if volume > 0 else 0,
                vwap=previous,
                source_ts=close_ts,
                ingest_ts=START + timedelta(hours=1, minutes=index),
                quality_flags=flag_values[index],
                raw_payload_id=f"RAW:S6-004:{scenario_id.value.upper()}:{index}",
            )
        )
    return tuple(result)


def _intent(
    scenario_id: SyntheticScenarioId,
    *,
    order_index: int,
    submitted_at: datetime,
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("1"),
) -> OrderIntent:
    suffix = f"{scenario_id.value.upper()}:{order_index}"
    return OrderIntent(
        client_order_id=f"ORDER:S6-004:{suffix}",
        trace_id=f"TRACE:S6-004:{suffix}",
        source_decision_id=f"DECISION:S6-004:{suffix}",
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        submitted_at=submitted_at,
    )


def _replay(
    *,
    scenario_id: SyntheticScenarioId,
    bars: tuple[OHLCTVBar, ...],
    intents: tuple[OrderIntent, ...],
    taker_fee_rate: Decimal,
    spread_bps: Decimal,
    slippage_bps: Decimal,
    max_participation_rate: Decimal = Decimal("1"),
    venue_status: str = "active",
    run_suffix: str | None = None,
) -> ReplayReport:
    return replay_ohlctv_market_orders(
        bars=bars,
        order_intents=intents,
        run_id=(
            f"REPLAY:S6-004:{scenario_id.value.upper()}"
            + (f":{run_suffix}" if run_suffix else "")
        ),
        execution_cost_model=make_execution_cost_model(
            taker_fee_rate=taker_fee_rate,
            spread_bps=spread_bps,
            slippage_bps=slippage_bps,
            max_participation_rate=max_participation_rate,
        ),
        instrument_master_snapshot=_snapshot(venue_status=venue_status),
        starting_account_state=_account_state(),
    )


def _summary(
    *,
    scenario_id: SyntheticScenarioId,
    name: str,
    traceability: tuple[str, ...],
    labels: tuple[str, ...],
    bars: tuple[OHLCTVBar, ...],
    report: ReplayReport,
    comparison_total_cost: Decimal | None = None,
) -> SyntheticScenarioResult:
    return SyntheticScenarioResult.from_replay_report(
        scenario_id=scenario_id,
        scenario_name=name,
        traceability=traceability,
        stress_labels=labels,
        report=report,
        min_close_price=min(bar.close for bar in bars),
        max_close_price=max(bar.close for bar in bars),
        comparison_total_cost=comparison_total_cost,
    )


def _account_state() -> SimulatedAccountState:
    return SimulatedAccountState(
        account_id=ACCOUNT_ID,
        balances=(
            SimulatedBalance(
                account_id=ACCOUNT_ID, venue_id=VENUE_ID, asset_id="FAKE", available=Decimal("10")
            ),
            SimulatedBalance(
                account_id=ACCOUNT_ID, venue_id=VENUE_ID, asset_id="USD", available=Decimal("10000")
            ),
        ),
    )


def _snapshot(*, venue_status: str) -> InstrumentMasterSnapshot:
    source = "SYNTHETIC_S6_004"
    created_at = "2026-01-01T00:00:00Z"
    return InstrumentMasterSnapshot.model_validate(
        {
            "schema_version": "instrument-master.v1",
            "snapshot_id": f"SYNTHETIC_S6_004_{venue_status.upper()}",
            "created_at": created_at,
            "source_id": source,
            "source_version": "v1",
            "metadata_ts": created_at,
            "assets": [
                _asset("FAKE", "crypto", "digital_asset", source, created_at),
                _asset("USD", "fiat", "cash", source, created_at),
            ],
            "venues": [
                {
                    "schema_version": "venue.v1",
                    "venue_id": VENUE_ID,
                    "name": "Synthetic Spot QA Venue",
                    "venue_type": "simulator",
                    "timezone": "UTC",
                    "api_endpoint_group": {
                        "group_id": "SYNTH_SPOT_PUBLIC",
                        "rest_base_url": "https://synthetic.invalid",
                    },
                    "status": venue_status,
                    "rate_limits": [
                        {
                            "rate_limit_id": "SYNTH_SPOT_METADATA",
                            "scope": "metadata",
                            "limit": 100,
                            "interval_seconds": 1,
                        }
                    ],
                    "supported_order_types": ["market"],
                    "source_id": source,
                    "source_version": "v1",
                    "metadata_ts": created_at,
                }
            ],
            "fee_schedules": [
                {
                    "schema_version": "fee-schedule.v1",
                    "fee_schedule_id": "SYNTH_SPOT_STANDARD_FEES",
                    "venue_id": VENUE_ID,
                    "fee_tier_id": "SYNTH_SPOT_STANDARD_FEES",
                    "maker_fee_rate": "0.001",
                    "taker_fee_rate": "0.001",
                    "fee_asset_id": "USD",
                    "min_fee": "0",
                    "effective_from": created_at,
                    "effective_to": None,
                    "source_id": source,
                    "source_version": "v1",
                    "metadata_ts": created_at,
                }
            ],
            "trading_sessions": [
                {
                    "schema_version": "trading-session.v1",
                    "session_id": "SYNTH_SPOT_24X7",
                    "venue_id": VENUE_ID,
                    "name": "Synthetic 24x7 QA Session",
                    "timezone": "UTC",
                    "days_of_week": [
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    ],
                    "is_24x7": True,
                    "open_time": None,
                    "close_time": None,
                    "status": "active",
                    "effective_from": created_at,
                    "effective_to": None,
                    "source_id": source,
                    "source_version": "v1",
                    "metadata_ts": created_at,
                }
            ],
            "instrument_constraints": [
                {
                    "schema_version": "instrument-constraint.v1",
                    "constraint_id": "SYNTH_SPOT:FAKE-USD:CONSTRAINTS",
                    "instrument_id": INSTRUMENT_ID,
                    "tick_size": "0.01",
                    "lot_size": "0.00000001",
                    "min_notional": "1.00",
                    "min_order_quantity": "0.00000001",
                    "max_order_quantity": None,
                    "max_order_notional": None,
                    "effective_from": created_at,
                    "effective_to": None,
                    "source_id": source,
                    "source_version": "v1",
                    "metadata_ts": created_at,
                }
            ],
            "instruments": [
                {
                    "schema_version": "instrument.v1",
                    "instrument_id": INSTRUMENT_ID,
                    "venue_id": VENUE_ID,
                    "base_asset_id": "FAKE",
                    "quote_asset_id": "USD",
                    "venue_symbol": "FAKE-USD",
                    "canonical_symbol": "FAKE-USD",
                    "instrument_type": "spot",
                    "status": "trading",
                    "tick_size": "0.01",
                    "lot_size": "0.00000001",
                    "min_notional": "1.00",
                    "fee_schedule_id": "SYNTH_SPOT_STANDARD_FEES",
                    "supported_order_types": ["market"],
                    "effective_from": created_at,
                    "effective_to": None,
                    "is_derivative": False,
                    "margin_allowed": False,
                    "short_selling_allowed": False,
                    "leverage_allowed": False,
                    "source_id": source,
                    "source_version": "v1",
                    "metadata_ts": created_at,
                }
            ],
            "accounts": [
                {
                    "schema_version": "account.v1",
                    "account_id": ACCOUNT_ID,
                    "venue_id": VENUE_ID,
                    "account_type": "simulation",
                    "status": "active",
                    "trading_permissions": ["place_orders", "read_market_data", "view_balances"],
                    "fee_tier_id": "SYNTH_SPOT_STANDARD_FEES",
                    "risk_limits": {
                        "max_order_notional_pct": "0.025",
                        "max_instrument_exposure_pct": "0.25",
                        "max_strategy_exposure_pct": "0.30",
                        "max_total_spot_exposure_pct": "0.60",
                        "min_cash_reserve_pct": "0.30",
                        "max_daily_loss_pct": "0.02",
                        "max_drawdown_pct": "0.08",
                    },
                    "key_scope": "trade_no_withdrawal",
                    "live_capital_enabled": False,
                    "withdrawals_enabled": False,
                    "margin_enabled": False,
                    "derivatives_enabled": False,
                    "shorting_enabled": False,
                    "source_id": source,
                    "source_version": "v1",
                    "metadata_ts": created_at,
                }
            ],
        }
    )


def _asset(
    asset_id: str, asset_type: str, category: str, source: str, created_at: str
) -> dict[str, object]:
    return {
        "schema_version": "asset.v1",
        "asset_id": asset_id,
        "symbol": asset_id,
        "name": f"Synthetic {asset_id}",
        "asset_type": asset_type,
        "classifications": [asset_type],
        "issuer": None,
        "category": category,
        "status": "active",
        "source_id": source,
        "source_version": "v1",
        "metadata_ts": created_at,
    }
