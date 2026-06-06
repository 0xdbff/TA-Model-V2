"""Evidence for S4-001 point-in-time TA feature engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ta_model.contracts.features import FeatureVector
from ta_model.contracts.market_data import (
    HistoricalBackfillPage,
    HistoricalProvenance,
    MarketDataKind,
    OHLCTVBar,
    QualityFlag,
    RawPayloadReference,
    TradeRecord,
    deterministic_payload_hash,
)
from ta_model.features.ta import (
    TAFeatureEngineError,
    build_ta_feature_snapshot,
    build_ta_feature_vectors,
)
from ta_model.normalization.silver import SilverNormalizationBatch, normalize_historical_page

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
SOURCE_ID = "FIXTURE_FEATURE_SOURCE"
VENUE_ID = "FIXTURE_SPOT"
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"


def _raw_payload(raw_payload_id: str) -> RawPayloadReference:
    return RawPayloadReference(
        raw_payload_id=raw_payload_id,
        source_id=SOURCE_ID,
        content_hash=deterministic_payload_hash(
            {"fixture": "ta-feature-engine", "raw_payload_id": raw_payload_id}
        ),
        uri=f"fixture://features/{raw_payload_id}",
        content_type="application/json",
        fetched_at=NOW,
        byte_count=512,
    )


def _provenance(raw_payload_id: str) -> HistoricalProvenance:
    return HistoricalProvenance(
        source_id=SOURCE_ID,
        connector_name="fixture-feature-connector",
        connector_version="0.0.0-test",
        fetched_at=NOW,
        raw_payload=_raw_payload(raw_payload_id),
    )


def _bar(
    index: int,
    close: Decimal,
    *,
    timeframe: str = "1m",
    minutes: int = 1,
    ingest_offset: int = 0,
) -> OHLCTVBar:
    open_ts = START + timedelta(minutes=index * minutes)
    close_ts = open_ts + timedelta(minutes=minutes)
    return OHLCTVBar(
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        timeframe=timeframe,
        open_ts=open_ts,
        close_ts=close_ts,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        base_volume=Decimal("10"),
        quote_volume=close * Decimal("10"),
        trade_count=10 + index,
        vwap=close,
        source_ts=close_ts,
        ingest_ts=NOW + timedelta(seconds=ingest_offset),
        quality_flags=(QualityFlag.LATE,),
        raw_payload_id=f"RAW:S4-001:TF{timeframe.upper()}:{index}",
    )


def _trade() -> TradeRecord:
    return TradeRecord(
        trade_id="fixture-trade",
        instrument_id=INSTRUMENT_ID,
        event_ts=START,
        price=Decimal("100"),
        quantity=Decimal("1"),
        ingest_ts=NOW,
        raw_payload_id="RAW:S4-001:TRADE",
    )


def _page(
    data_kind: MarketDataKind, records: tuple[OHLCTVBar | TradeRecord, ...], raw_id: str
) -> HistoricalBackfillPage:
    return HistoricalBackfillPage(
        page_id=HistoricalBackfillPage.build_page_id(
            request_id="HISTREQ:S4-001",
            data_kind=data_kind,
            raw_payload_id=raw_id,
            cursor=None,
        ),
        request_id="HISTREQ:S4-001",
        data_kind=data_kind,
        records=records,
        provenance=_provenance(raw_id),
        fetched_at=NOW,
    )


def _batch(
    closes: tuple[str, ...], *, ingest_offset: int = 0, timeframe: str = "1m", minutes: int = 1
) -> SilverNormalizationBatch:
    bars = tuple(
        _bar(
            index,
            Decimal(close),
            timeframe=timeframe,
            minutes=minutes,
            ingest_offset=ingest_offset,
        )
        for index, close in enumerate(closes)
    )
    raw_id = bars[0].raw_payload_id
    normalized_bars = tuple(bar.model_copy(update={"raw_payload_id": raw_id}) for bar in bars)
    return normalize_historical_page(
        _page(MarketDataKind.OHLCTV, normalized_bars, raw_id),
        venue_id=VENUE_ID,
        instrument_id=INSTRUMENT_ID,
    )


def test_contract_validation_and_deterministic_feature_ids() -> None:
    vectors = build_ta_feature_vectors(_batch(("100", "101", "103", "106")))
    rebuilt = FeatureVector.model_validate(vectors[-1].model_dump())

    assert rebuilt.feature_vector_id == vectors[-1].feature_vector_id
    assert rebuilt.feature_ts == START + timedelta(minutes=4)
    assert "one_bar_return" in rebuilt.values
    with pytest.raises(ValidationError, match="feature_vector_id is not deterministic"):
        FeatureVector.model_validate({**rebuilt.model_dump(), "feature_vector_id": "FEATURE:WRONG"})


def test_shifted_feature_leakage_future_mutation_does_not_change_earlier_vectors() -> None:
    baseline = build_ta_feature_vectors(_batch(("100", "101", "103", "106", "110")))
    mutated_future = build_ta_feature_vectors(_batch(("100", "101", "103", "106", "999")))

    assert baseline[0].model_dump() == mutated_future[0].model_dump()
    assert baseline[1].model_dump() == mutated_future[1].model_dump()
    assert baseline[2].model_dump() == mutated_future[2].model_dump()
    assert baseline[3].model_dump() == mutated_future[3].model_dump()
    assert baseline[4].feature_vector_id != mutated_future[4].feature_vector_id


def test_ingest_time_perturbation_cannot_change_feature_ids_or_values() -> None:
    first = build_ta_feature_vectors(_batch(("100", "101", "103", "106"), ingest_offset=0))
    second = build_ta_feature_vectors(_batch(("100", "101", "103", "106"), ingest_offset=3600))

    assert tuple(vector.feature_vector_id for vector in first) == tuple(
        vector.feature_vector_id for vector in second
    )
    assert tuple(vector.values for vector in first) == tuple(vector.values for vector in second)


def test_non_ohlctv_and_duplicate_or_non_monotonic_event_time_fail_closed() -> None:
    trade_batch = normalize_historical_page(
        _page(MarketDataKind.TRADE, (_trade(),), "RAW:S4-001:TRADE"),
        venue_id=VENUE_ID,
        instrument_id=INSTRUMENT_ID,
    )
    with pytest.raises(TAFeatureEngineError, match="OHLCTV"):
        build_ta_feature_vectors(trade_batch)

    valid = _batch(("100", "101"))
    duplicate = valid.model_copy(update={"records": (valid.records[0], valid.records[0])})
    with pytest.raises(TAFeatureEngineError, match="strictly increasing"):
        build_ta_feature_vectors(duplicate)

    reversed_batch = valid.model_copy(update={"records": tuple(reversed(valid.records))})
    with pytest.raises(TAFeatureEngineError, match="strictly increasing"):
        build_ta_feature_vectors(reversed_batch)


def test_higher_timeframe_lag_unavailable_before_close_then_available_at_close() -> None:
    base = _batch(("100", "101", "102", "103", "104", "105"), timeframe="1m", minutes=1)
    higher = _batch(("1000", "1100"), timeframe="5m", minutes=5)

    vectors = build_ta_feature_vectors(base, higher_timeframe_batch=higher)

    assert vectors[0].values["htf_close"] is None
    assert vectors[3].values["htf_close"] is None
    assert vectors[4].feature_ts == START + timedelta(minutes=5)
    assert vectors[4].values["htf_close"] == Decimal("1000")
    assert vectors[5].values["htf_close"] == Decimal("1000")


def test_feature_engine_snapshot_hash_is_deterministic() -> None:
    vectors = build_ta_feature_vectors(_batch(("100", "101", "103", "106")))
    snapshot = build_ta_feature_snapshot(vectors)
    rebuilt = build_ta_feature_snapshot(vectors)

    assert snapshot.feature_snapshot_id == rebuilt.feature_snapshot_id
    assert snapshot.snapshot_hash == rebuilt.snapshot_hash
    assert snapshot.vector_ids == tuple(vector.feature_vector_id for vector in vectors)
