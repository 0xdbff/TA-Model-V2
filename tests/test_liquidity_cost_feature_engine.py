"""Evidence for S4-002 FR-005 liquidity/cost feature engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ta_model.contracts.features import (
    FeatureVector,
    QuoteFeatureInput,
    build_quote_feature_input_id,
)
from ta_model.contracts.instrument_master import FeeSchedule
from ta_model.contracts.market_data import (
    HistoricalBackfillPage,
    HistoricalProvenance,
    MarketDataKind,
    OHLCTVBar,
    QualityFlag,
    RawPayloadReference,
    deterministic_payload_hash,
)
from ta_model.features.liquidity_cost import (
    LiquidityCostFeatureEngineError,
    build_liquidity_cost_feature_snapshot,
    build_liquidity_cost_feature_vectors,
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
            {"fixture": "liquidity-cost-feature-engine", "raw_payload_id": raw_payload_id}
        ),
        uri=f"fixture://liquidity-cost/{raw_payload_id}",
        content_type="application/json",
        fetched_at=NOW,
        byte_count=512,
    )


def _provenance(raw_payload_id: str) -> HistoricalProvenance:
    return HistoricalProvenance(
        source_id=SOURCE_ID,
        connector_name="fixture-liquidity-cost-connector",
        connector_version="0.0.0-test",
        fetched_at=NOW,
        raw_payload=_raw_payload(raw_payload_id),
    )


def _bar(
    index: int,
    close: Decimal,
    *,
    ingest_offset: int = 0,
    source_offset: int = 0,
) -> OHLCTVBar:
    open_ts = START + timedelta(minutes=index)
    close_ts = open_ts + timedelta(minutes=1)
    return OHLCTVBar(
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        timeframe="1m",
        open_ts=open_ts,
        close_ts=close_ts,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        base_volume=Decimal("10") + Decimal(index),
        quote_volume=(Decimal("10") + Decimal(index)) * close,
        trade_count=10 + index,
        vwap=close,
        source_ts=close_ts + timedelta(seconds=source_offset),
        ingest_ts=NOW + timedelta(seconds=ingest_offset),
        quality_flags=(QualityFlag.LATE,),
        raw_payload_id=f"RAW:S4-002:BAR:{index}",
    )


def _page(records: tuple[OHLCTVBar, ...], raw_id: str) -> HistoricalBackfillPage:
    return HistoricalBackfillPage(
        page_id=HistoricalBackfillPage.build_page_id(
            request_id="HISTREQ:S4-002",
            data_kind=MarketDataKind.OHLCTV,
            raw_payload_id=raw_id,
            cursor=None,
        ),
        request_id="HISTREQ:S4-002",
        data_kind=MarketDataKind.OHLCTV,
        records=records,
        provenance=_provenance(raw_id),
        fetched_at=NOW,
    )


def _batch(closes: tuple[str, ...], *, ingest_offset: int = 0) -> SilverNormalizationBatch:
    bars = tuple(
        _bar(index, Decimal(close), ingest_offset=ingest_offset)
        for index, close in enumerate(closes)
    )
    raw_id = bars[0].raw_payload_id
    normalized_bars = tuple(bar.model_copy(update={"raw_payload_id": raw_id}) for bar in bars)
    return normalize_historical_page(
        _page(normalized_bars, raw_id),
        venue_id=VENUE_ID,
        instrument_id=INSTRUMENT_ID,
    )


def _batch_with_late_source_bar() -> SilverNormalizationBatch:
    bar = _bar(0, Decimal("100"), source_offset=1)
    raw_id = bar.raw_payload_id
    return normalize_historical_page(
        _page((bar,), raw_id),
        venue_id=VENUE_ID,
        instrument_id=INSTRUMENT_ID,
    )


def _quote(
    index: int,
    bid: str,
    ask: str,
    *,
    ingest_offset: int = 0,
    source_offset: int = 0,
) -> QuoteFeatureInput:
    event_ts = START + timedelta(minutes=index)
    source_ts = event_ts + timedelta(seconds=source_offset)
    best_bid = Decimal(bid)
    best_ask = Decimal(ask)
    bid_size = Decimal("1")
    ask_size = Decimal("2")
    quality_flags: tuple[str, ...] = ()
    raw_payload_id = f"RAW:S4-002:QUOTE:{index}"
    return QuoteFeatureInput(
        quote_feature_input_id=build_quote_feature_input_id(
            instrument_id=INSTRUMENT_ID,
            venue_id=VENUE_ID,
            event_ts=event_ts,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
            source_ts=source_ts,
            quality_flags=quality_flags,
            raw_payload_id=raw_payload_id,
        ),
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        event_ts=event_ts,
        best_bid=best_bid,
        best_ask=best_ask,
        bid_size=bid_size,
        ask_size=ask_size,
        source_ts=source_ts,
        ingest_ts=NOW + timedelta(seconds=ingest_offset),
        quality_flags=quality_flags,
        raw_payload_id=raw_payload_id,
    )


def _fee(
    effective_from: datetime,
    *,
    maker: str = "0.001",
    taker: str = "0.002",
    effective_to: datetime | None = None,
) -> FeeSchedule:
    return FeeSchedule(
        fee_schedule_id=f"FEE:S4-002:{effective_from.strftime('%H%M%S')}",
        venue_id=VENUE_ID,
        fee_tier_id="FEE:TIER:FIXTURE",
        maker_fee_rate=Decimal(maker),
        taker_fee_rate=Decimal(taker),
        min_fee=Decimal("0"),
        effective_from=effective_from,
        effective_to=effective_to,
        source_id=SOURCE_ID,
        source_version="fixture",
        metadata_ts=effective_from,
    )


def test_fr005_contract_validation_and_deterministic_feature_ids() -> None:
    vectors = build_liquidity_cost_feature_vectors(
        _batch(("100", "101", "103", "106")),
        quotes=(_quote(0, "99", "101"),),
        fee_schedules=(_fee(START),),
    )
    rebuilt = FeatureVector.model_validate(vectors[-1].model_dump())

    assert rebuilt.feature_vector_id == vectors[-1].feature_vector_id
    assert rebuilt.values["spread_abs"] == Decimal("2")
    assert rebuilt.values["spread_bps"] == Decimal("200")
    assert rebuilt.values["bid_size"] == Decimal("1")
    assert rebuilt.values["ask_size"] == Decimal("2")
    assert rebuilt.values["top_of_book_base_liquidity"] == Decimal("3")
    assert rebuilt.values["top_of_book_quote_liquidity"] == Decimal("300")
    assert rebuilt.values["round_trip_taker_fee_rate"] == Decimal("0.004")
    assert rebuilt.values["round_trip_taker_cost_bps"] == Decimal("240.000")
    with pytest.raises(ValidationError, match="feature_vector_id is not deterministic"):
        FeatureVector.model_validate({**rebuilt.model_dump(), "feature_vector_id": "FEATURE:WRONG"})


def test_spread_uses_latest_decision_time_quote_and_ignores_future_quote_mutation() -> None:
    batch = _batch(("100", "101", "103"))
    baseline = build_liquidity_cost_feature_vectors(
        batch,
        quotes=(_quote(0, "99", "101"), _quote(2, "100", "104"), _quote(10, "1", "1000")),
        fee_schedules=(_fee(START),),
    )
    mutated_future = build_liquidity_cost_feature_vectors(
        batch,
        quotes=(_quote(0, "99", "101"), _quote(2, "100", "104"), _quote(10, "900", "1000")),
        fee_schedules=(_fee(START),),
    )

    assert baseline[0].values["mid_price"] == Decimal("100")
    assert baseline[1].values["spread_abs"] == Decimal("4")
    assert tuple(vector.model_dump() for vector in baseline) == tuple(
        vector.model_dump() for vector in mutated_future
    )


def test_quote_must_be_available_by_event_and_source_time_at_decision_time() -> None:
    with pytest.raises(LiquidityCostFeatureEngineError, match="no quote is available"):
        build_liquidity_cost_feature_vectors(
            _batch(("100",)),
            quotes=(_quote(2, "99", "101"),),
            fee_schedules=(_fee(START),),
        )

    with pytest.raises(LiquidityCostFeatureEngineError, match="no quote is available"):
        build_liquidity_cost_feature_vectors(
            _batch(("100",)),
            quotes=(_quote(0, "99", "101", source_offset=120),),
            fee_schedules=(_fee(START),),
        )


def test_volume_and_realized_volatility_ignore_future_bar_mutation() -> None:
    baseline = build_liquidity_cost_feature_vectors(
        _batch(("100", "101", "103", "106", "110")),
        quotes=(_quote(0, "99", "101"),),
        fee_schedules=(_fee(START),),
    )
    mutated_future = build_liquidity_cost_feature_vectors(
        _batch(("100", "101", "103", "106", "999")),
        quotes=(_quote(0, "99", "101"),),
        fee_schedules=(_fee(START),),
    )

    assert baseline[3].values["base_volume"] == Decimal("13")
    assert baseline[3].values["realized_volatility_3"] is not None
    assert baseline[3].model_dump() == mutated_future[3].model_dump()
    assert baseline[4].feature_vector_id != mutated_future[4].feature_vector_id


def test_fee_schedule_uses_effective_event_time_and_missing_fee_fails_closed() -> None:
    vectors = build_liquidity_cost_feature_vectors(
        _batch(("100", "101", "103")),
        quotes=(_quote(0, "99", "101"),),
        fee_schedules=(
            _fee(START, taker="0.002", effective_to=START + timedelta(minutes=2)),
            _fee(START + timedelta(minutes=2), taker="0.003"),
        ),
    )

    assert vectors[0].values["taker_fee_rate"] == Decimal("0.002")
    assert vectors[1].values["taker_fee_rate"] == Decimal("0.003")
    with pytest.raises(LiquidityCostFeatureEngineError, match="fee schedule"):
        build_liquidity_cost_feature_vectors(
            _batch(("100",)),
            quotes=(_quote(0, "99", "101"),),
            fee_schedules=(_fee(START + timedelta(minutes=2)),),
        )


def test_ingest_time_perturbation_cannot_change_ids_or_values() -> None:
    first = build_liquidity_cost_feature_vectors(
        _batch(("100", "101", "103"), ingest_offset=0),
        quotes=(_quote(0, "99", "101", ingest_offset=0),),
        fee_schedules=(_fee(START),),
    )
    second = build_liquidity_cost_feature_vectors(
        _batch(("100", "101", "103"), ingest_offset=3600),
        quotes=(_quote(0, "99", "101", ingest_offset=3600),),
        fee_schedules=(_fee(START),),
    )

    assert tuple(vector.feature_vector_id for vector in first) == tuple(
        vector.feature_vector_id for vector in second
    )
    assert tuple(vector.values for vector in first) == tuple(vector.values for vector in second)


def test_crossed_locked_and_duplicate_quote_event_times_fail_closed() -> None:
    with pytest.raises(ValidationError, match="crossed or locked"):
        _quote(0, "100", "100")

    quote = _quote(0, "99", "101")
    with pytest.raises(LiquidityCostFeatureEngineError, match="strictly increasing"):
        build_liquidity_cost_feature_vectors(
            _batch(("100",)),
            quotes=(quote, quote),
            fee_schedules=(_fee(START),),
        )

    with pytest.raises(LiquidityCostFeatureEngineError, match="strictly increasing"):
        build_liquidity_cost_feature_vectors(
            _batch(("100",)),
            quotes=(_quote(1, "99", "101"), _quote(0, "99", "101")),
            fee_schedules=(_fee(START),),
        )


def test_fee_overlap_and_bad_ohlctv_event_time_fail_closed() -> None:
    with pytest.raises(LiquidityCostFeatureEngineError, match="fee schedule"):
        build_liquidity_cost_feature_vectors(
            _batch(("100",)),
            quotes=(_quote(0, "99", "101"),),
            fee_schedules=(
                _fee(START, effective_to=START + timedelta(minutes=2)),
                _fee(START + timedelta(seconds=30)),
            ),
        )

    valid = _batch(("100", "101"))
    reversed_batch = valid.model_copy(update={"records": tuple(reversed(valid.records))})
    with pytest.raises(LiquidityCostFeatureEngineError, match="strictly increasing"):
        build_liquidity_cost_feature_vectors(
            reversed_batch,
            quotes=(_quote(0, "99", "101"),),
            fee_schedules=(_fee(START),),
        )

    empty_batch = valid.model_copy(update={"records": (), "record_count": 0})
    with pytest.raises(LiquidityCostFeatureEngineError, match="at least one OHLCTV"):
        build_liquidity_cost_feature_vectors(
            empty_batch,
            quotes=(_quote(0, "99", "101"),),
            fee_schedules=(_fee(START),),
        )


def test_late_source_bar_fails_closed_before_feature_emission() -> None:
    with pytest.raises(LiquidityCostFeatureEngineError, match="source_ts"):
        build_liquidity_cost_feature_vectors(
            _batch_with_late_source_bar(),
            quotes=(_quote(0, "99", "101"),),
            fee_schedules=(_fee(START),),
        )


def test_liquidity_cost_feature_snapshot_hash_is_deterministic() -> None:
    vectors = build_liquidity_cost_feature_vectors(
        _batch(("100", "101", "103", "106")),
        quotes=(_quote(0, "99", "101"),),
        fee_schedules=(_fee(START),),
    )
    snapshot = build_liquidity_cost_feature_snapshot(vectors)
    rebuilt = build_liquidity_cost_feature_snapshot(vectors)

    assert snapshot.feature_snapshot_id == rebuilt.feature_snapshot_id
    assert snapshot.snapshot_hash == rebuilt.snapshot_hash
    assert snapshot.vector_ids == tuple(vector.feature_vector_id for vector in vectors)
