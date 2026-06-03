"""Point-in-time liquidity, spread, volatility, and fee feature engine.

Traceability:
- FR-005: spread, volume, volatility, and fee features are available at decision time.
- FR-003: fee metadata is selected by effective event-time windows.
- NFR-001/NFR-005: inputs use event/close/effective timestamps, never ingest_ts.

Scope:
- S4-002 fixture-only pure-Python feature builder. No quote ingestion, dataset builder,
  routing, model/strategy/risk changes, leverage, derivatives, or live capital.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal, localcontext

from ta_model.contracts.features import (
    FeatureQualityFlag,
    FeatureSnapshot,
    FeatureValue,
    FeatureVector,
    QuoteFeatureInput,
    build_feature_input_snapshot_id,
    build_feature_snapshot,
    build_feature_vector_id,
)
from ta_model.contracts.instrument_master import FeeSchedule
from ta_model.contracts.market_data import MarketDataKind
from ta_model.normalization.silver import SilverNormalizationBatch, SilverOHLCTVRecord

FEATURE_VERSION = "liquidity-cost-pit-1.0.0"


class LiquidityCostFeatureEngineError(ValueError):
    """Raised when liquidity/cost feature generation must fail closed."""


def build_liquidity_cost_feature_vectors(
    batch: SilverNormalizationBatch,
    *,
    quotes: Sequence[QuoteFeatureInput],
    fee_schedules: Sequence[FeeSchedule],
    volatility_window: int = 3,
) -> tuple[FeatureVector, ...]:
    """Build deterministic FR-005 feature vectors from closed bars, quotes, and fees."""

    if volatility_window <= 0:
        raise LiquidityCostFeatureEngineError("volatility_window must be positive")
    records = _validate_ohlctv_batch(batch)
    quote_inputs = _validate_quotes(
        quotes, instrument_id=batch.instrument_id, venue_id=batch.venue_id
    )
    schedules = _validate_fee_schedules(fee_schedules, venue_id=batch.venue_id)

    lookback_window = f"max({volatility_window + 1} bars, latest quote, active fee)"
    closes: list[Decimal] = []
    returns: list[Decimal] = []
    vectors: list[FeatureVector] = []
    for index, record in enumerate(records):
        feature_ts = record.bar.close_ts
        close = record.bar.close
        previous_close = closes[-1] if closes else None
        one_bar_return = _return(close, previous_close)
        if one_bar_return is not None:
            returns.append(one_bar_return)
        closes.append(close)

        quote = _latest_quote(quote_inputs, feature_ts)
        schedule = _active_fee_schedule(schedules, feature_ts)
        spread_abs = quote.best_ask - quote.best_bid
        mid_price = (quote.best_bid + quote.best_ask) / Decimal("2")
        values: dict[str, FeatureValue] = {
            "spread_abs": spread_abs,
            "spread_bps": (spread_abs / mid_price) * Decimal("10000"),
            "half_spread_bps": (spread_abs / mid_price) * Decimal("5000"),
            "mid_price": mid_price,
            "bid_size": quote.bid_size,
            "ask_size": quote.ask_size,
            "top_of_book_base_liquidity": _quote_base_liquidity(quote),
            "top_of_book_quote_liquidity": _quote_quote_liquidity(quote, mid_price),
            "base_volume": record.bar.base_volume,
            "quote_volume": record.bar.quote_volume,
            "trade_count": None
            if record.bar.trade_count is None
            else Decimal(record.bar.trade_count),
            f"realized_volatility_{volatility_window}": _volatility(returns[-volatility_window:])
            if len(returns) >= volatility_window
            else None,
            "maker_fee_rate": schedule.maker_fee_rate,
            "taker_fee_rate": schedule.taker_fee_rate,
            "round_trip_taker_fee_rate": schedule.taker_fee_rate * Decimal("2"),
            "taker_fee_bps": schedule.taker_fee_rate * Decimal("10000"),
            "one_way_taker_cost_bps": ((spread_abs / mid_price) * Decimal("5000"))
            + (schedule.taker_fee_rate * Decimal("10000")),
            "round_trip_taker_cost_bps": ((spread_abs / mid_price) * Decimal("10000"))
            + (schedule.taker_fee_rate * Decimal("20000")),
            "min_fee": schedule.min_fee,
        }
        quality_flags = _quality_flags(values)
        input_snapshot_id = build_feature_input_snapshot_id(
            record_ids=(
                *(bar.silver_record_id for bar in records[: index + 1]),
                quote.quote_feature_input_id,
                schedule.fee_schedule_id,
            )
        )
        feature_vector_id = build_feature_vector_id(
            instrument_id=batch.instrument_id,
            venue_id=batch.venue_id,
            feature_ts=feature_ts,
            feature_version=FEATURE_VERSION,
            lookback_window=lookback_window,
            values=values,
            input_snapshot_id=input_snapshot_id,
            quality_flags=quality_flags,
        )
        vectors.append(
            FeatureVector(
                feature_vector_id=feature_vector_id,
                instrument_id=batch.instrument_id,
                venue_id=batch.venue_id,
                feature_ts=feature_ts,
                feature_version=FEATURE_VERSION,
                lookback_window=lookback_window,
                values=values,
                input_snapshot_id=input_snapshot_id,
                quality_flags=quality_flags,
            )
        )
    return tuple(vectors)


def build_liquidity_cost_feature_snapshot(vectors: Sequence[FeatureVector]) -> FeatureSnapshot:
    vector_tuple = tuple(vectors)
    return build_feature_snapshot(
        tuple(vector.feature_vector_id for vector in vector_tuple),
        vectors=vector_tuple,
    )


def _validate_ohlctv_batch(batch: SilverNormalizationBatch) -> tuple[SilverOHLCTVRecord, ...]:
    if batch.data_kind is not MarketDataKind.OHLCTV or batch.timeframe is None:
        raise LiquidityCostFeatureEngineError("liquidity/cost features require an OHLCTV batch")
    if not all(isinstance(record, SilverOHLCTVRecord) for record in batch.records):
        raise LiquidityCostFeatureEngineError("liquidity/cost features require OHLCTV records")
    records = tuple(record for record in batch.records if isinstance(record, SilverOHLCTVRecord))
    if len(records) == 0:
        raise LiquidityCostFeatureEngineError("at least one OHLCTV record is required")
    previous_close_ts: datetime | None = None
    for record in records:
        if record.timeframe != batch.timeframe:
            raise LiquidityCostFeatureEngineError("record timeframe must match batch timeframe")
        if record.bar.source_ts > record.bar.close_ts:
            raise LiquidityCostFeatureEngineError(
                "OHLCTV source_ts must be available at or before close_ts"
            )
        if previous_close_ts is not None and record.bar.close_ts <= previous_close_ts:
            raise LiquidityCostFeatureEngineError("OHLCTV close_ts must be strictly increasing")
        previous_close_ts = record.bar.close_ts
    return records


def _validate_quotes(
    quotes: Sequence[QuoteFeatureInput], *, instrument_id: str, venue_id: str
) -> tuple[QuoteFeatureInput, ...]:
    quote_inputs = tuple(quotes)
    if len(quote_inputs) == 0:
        raise LiquidityCostFeatureEngineError("at least one quote is required")
    previous_event_ts: datetime | None = None
    for quote in quote_inputs:
        if quote.instrument_id != instrument_id or quote.venue_id != venue_id:
            raise LiquidityCostFeatureEngineError("quote scope must match feature batch")
        if quote.best_ask <= quote.best_bid:
            raise LiquidityCostFeatureEngineError("quote must not be crossed or locked")
        if quote.source_ts is not None and quote.source_ts < quote.event_ts:
            raise LiquidityCostFeatureEngineError("quote source_ts must not precede event_ts")
        if previous_event_ts is not None and quote.event_ts <= previous_event_ts:
            raise LiquidityCostFeatureEngineError("quote event_ts must be strictly increasing")
        previous_event_ts = quote.event_ts
    return quote_inputs


def _validate_fee_schedules(
    fee_schedules: Sequence[FeeSchedule], *, venue_id: str
) -> tuple[FeeSchedule, ...]:
    schedules = tuple(fee_schedules)
    if len(schedules) == 0:
        raise LiquidityCostFeatureEngineError("at least one fee schedule is required")
    for schedule in schedules:
        if schedule.venue_id != venue_id:
            raise LiquidityCostFeatureEngineError("fee schedule venue must match feature batch")
    return schedules


def _latest_quote(quotes: tuple[QuoteFeatureInput, ...], feature_ts: datetime) -> QuoteFeatureInput:
    available = [
        quote
        for quote in quotes
        if quote.event_ts <= feature_ts
        and (quote.source_ts is None or quote.source_ts <= feature_ts)
    ]
    if not available:
        raise LiquidityCostFeatureEngineError("no quote is available at feature_ts")
    return available[-1]


def _active_fee_schedule(schedules: tuple[FeeSchedule, ...], feature_ts: datetime) -> FeeSchedule:
    active = [
        schedule
        for schedule in schedules
        if schedule.effective_from <= feature_ts
        and (schedule.effective_to is None or feature_ts < schedule.effective_to)
    ]
    if len(active) != 1:
        raise LiquidityCostFeatureEngineError(
            "exactly one fee schedule must be active at feature_ts"
        )
    return active[0]


def _quality_flags(values: dict[str, FeatureValue]) -> tuple[FeatureQualityFlag, ...]:
    if any(value is None for value in values.values()):
        return (FeatureQualityFlag.MISSING, FeatureQualityFlag.INSUFFICIENT_HISTORY)
    return ()


def _quote_base_liquidity(quote: QuoteFeatureInput) -> Decimal | None:
    if quote.bid_size is None or quote.ask_size is None:
        return None
    return quote.bid_size + quote.ask_size


def _quote_quote_liquidity(quote: QuoteFeatureInput, mid_price: Decimal) -> Decimal | None:
    base_liquidity = _quote_base_liquidity(quote)
    return None if base_liquidity is None else base_liquidity * mid_price


def _return(close: Decimal, previous_close: Decimal | None) -> Decimal | None:
    if previous_close is None or previous_close == 0:
        return None
    return (close / previous_close) - Decimal("1")


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _volatility(values: Sequence[Decimal]) -> Decimal:
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
    with localcontext() as context:
        context.prec = 28
        return variance.sqrt()
