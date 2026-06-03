"""Point-in-time technical-analysis feature engine over silver OHLCTV records.

Traceability:
- FR-004: computes TA features only from bars closed at or before feature_ts.
- NFR-001: fail-closed ordering checks and shifted-feature leakage protections.

Scope:
- S4-001 TA features only. Liquidity/spread/fee features (S4-002), dataset snapshot
  builder (S4-003), model/strategy/order paths, paper/live routing, leverage, and
  derivatives are intentionally out of scope.
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
    build_feature_input_snapshot_id,
    build_feature_snapshot,
    build_feature_vector_id,
)
from ta_model.contracts.market_data import MarketDataKind
from ta_model.normalization.silver import SilverNormalizationBatch, SilverOHLCTVRecord

FEATURE_VERSION = "ta-pit-1.0.0"


class TAFeatureEngineError(ValueError):
    """Raised when feature generation must fail closed."""


def build_ta_feature_vectors(
    batch: SilverNormalizationBatch,
    *,
    sma_window: int = 3,
    volatility_window: int = 3,
    momentum_window: int = 3,
    higher_timeframe_batch: SilverNormalizationBatch | None = None,
) -> tuple[FeatureVector, ...]:
    """Build deterministic point-in-time TA feature vectors from closed OHLCTV bars."""

    records = _validate_ohlctv_batch(batch)
    if sma_window <= 0 or volatility_window <= 0 or momentum_window <= 0:
        raise TAFeatureEngineError("feature windows must be positive")
    higher_records: tuple[SilverOHLCTVRecord, ...] = ()
    if higher_timeframe_batch is not None:
        higher_records = _validate_higher_timeframe_batch(batch, higher_timeframe_batch)

    lookback_window = f"max({max(sma_window, volatility_window + 1, momentum_window + 1)} bars)"
    closes: list[Decimal] = []
    returns: list[Decimal] = []
    vectors: list[FeatureVector] = []
    for index, record in enumerate(records):
        feature_ts = record.bar.close_ts
        close = record.bar.close
        previous_close = closes[-1] if closes else None
        one_bar_return = _return(close, previous_close) if previous_close is not None else None
        if one_bar_return is not None:
            returns.append(one_bar_return)
        closes.append(close)

        values: dict[str, FeatureValue] = {
            "one_bar_return": one_bar_return,
            f"sma_{sma_window}": _mean(closes[-sma_window:]) if len(closes) >= sma_window else None,
            f"volatility_{volatility_window}": _volatility(returns[-volatility_window:])
            if len(returns) >= volatility_window
            else None,
            f"momentum_{momentum_window}": _return(close, closes[index - momentum_window])
            if index >= momentum_window
            else None,
        }
        if higher_records:
            values["htf_close"] = _latest_higher_timeframe_close(higher_records, feature_ts)
        quality_flags = _quality_flags(values)
        input_record_ids = tuple(record.silver_record_id for record in records[: index + 1])
        if higher_records:
            input_record_ids += tuple(
                htf.silver_record_id for htf in higher_records if htf.bar.close_ts <= feature_ts
            )
        input_snapshot_id = build_feature_input_snapshot_id(record_ids=input_record_ids)
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


def build_ta_feature_snapshot(vectors: Sequence[FeatureVector]) -> FeatureSnapshot:
    """Build minimal deterministic snapshot/hash evidence for TA feature vectors."""

    vector_tuple = tuple(vectors)
    return build_feature_snapshot(
        tuple(vector.feature_vector_id for vector in vector_tuple),
        vectors=vector_tuple,
    )


def _validate_ohlctv_batch(batch: SilverNormalizationBatch) -> tuple[SilverOHLCTVRecord, ...]:
    if batch.data_kind is not MarketDataKind.OHLCTV or batch.timeframe is None:
        raise TAFeatureEngineError("TA features require an OHLCTV silver batch")
    if not all(isinstance(record, SilverOHLCTVRecord) for record in batch.records):
        raise TAFeatureEngineError("TA features require only OHLCTV silver records")
    records = tuple(record for record in batch.records if isinstance(record, SilverOHLCTVRecord))
    previous_close_ts = None
    for record in records:
        if record.timeframe != batch.timeframe:
            raise TAFeatureEngineError("record timeframe must match batch timeframe")
        if previous_close_ts is not None and record.bar.close_ts <= previous_close_ts:
            raise TAFeatureEngineError("OHLCTV close_ts must be strictly increasing")
        previous_close_ts = record.bar.close_ts
    return records


def _validate_higher_timeframe_batch(
    base_batch: SilverNormalizationBatch,
    higher_timeframe_batch: SilverNormalizationBatch,
) -> tuple[SilverOHLCTVRecord, ...]:
    if higher_timeframe_batch.instrument_id != base_batch.instrument_id:
        raise TAFeatureEngineError("higher timeframe instrument scope must match")
    if higher_timeframe_batch.venue_id != base_batch.venue_id:
        raise TAFeatureEngineError("higher timeframe venue scope must match")
    records = _validate_ohlctv_batch(higher_timeframe_batch)
    if _timeframe_seconds(higher_timeframe_batch.timeframe or "") <= _timeframe_seconds(
        base_batch.timeframe or ""
    ):
        raise TAFeatureEngineError("higher timeframe must be longer than base timeframe")
    return records


def _latest_higher_timeframe_close(
    higher_records: tuple[SilverOHLCTVRecord, ...], feature_ts: datetime
) -> Decimal | None:
    available = [record.bar.close for record in higher_records if record.bar.close_ts <= feature_ts]
    return available[-1] if available else None


def _quality_flags(values: dict[str, FeatureValue]) -> tuple[FeatureQualityFlag, ...]:
    if any(value is None for value in values.values()):
        return (FeatureQualityFlag.MISSING, FeatureQualityFlag.INSUFFICIENT_HISTORY)
    return ()


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


def _timeframe_seconds(timeframe: str) -> int:
    unit = timeframe[-1]
    amount = int(timeframe[:-1])
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 60 * 60
    if unit == "d":
        return amount * 60 * 60 * 24
    raise TAFeatureEngineError("unsupported timeframe")
