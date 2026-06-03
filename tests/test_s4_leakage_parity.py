"""S4-004 integrated leakage and batch-vs-incremental parity gate evidence.

Traceability:
- FR-004: TA features are point-in-time and higher-timeframe lagged until close.
- FR-005: liquidity/cost features use only quotes/fees available by decision time.
- FR-006: chronological dataset rows/splits are reproducible from feature_ts.
- NFR-001/NFR-005: leakage checks fail closed and replay is deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from ta_model.contracts.datasets import (
    ChronologicalSplitWindow,
    DatasetSnapshot,
    DatasetSplit,
    LabelMethod,
    LabelObservation,
    LabelRule,
    build_label_observation,
    build_label_rule,
)
from ta_model.contracts.features import (
    FeatureQualityFlag,
    FeatureValue,
    FeatureVector,
    QuoteFeatureInput,
    build_feature_input_snapshot_id,
    build_feature_vector_id,
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
from ta_model.datasets.snapshots import (
    DatasetSnapshotBuilderError,
    build_chronological_dataset_snapshot,
)
from ta_model.features.liquidity_cost import (
    LiquidityCostFeatureEngineError,
    build_liquidity_cost_feature_vectors,
)
from ta_model.features.ta import TAFeatureEngineError, build_ta_feature_vectors
from ta_model.normalization.silver import (
    SilverNormalizationBatch,
    SilverOHLCTVRecord,
    normalize_historical_page,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
SOURCE_ID = "FIXTURE_S4_004_SOURCE"
VENUE_ID = "FIXTURE_SPOT"
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"
MERGED_FEATURE_VERSION = "s4-004-ta-liquidity-pit-1.0.0"
SOURCE_FEATURE_SNAPSHOT_ID = "FEATURESNAPSHOT:S4-004:PARITY"


def _raw_payload(raw_payload_id: str) -> RawPayloadReference:
    return RawPayloadReference(
        raw_payload_id=raw_payload_id,
        source_id=SOURCE_ID,
        content_hash=deterministic_payload_hash(
            {"fixture": "s4-004-leakage-parity", "raw_payload_id": raw_payload_id}
        ),
        uri=f"fixture://s4-004/{raw_payload_id}",
        content_type="application/json",
        fetched_at=NOW,
        byte_count=1024,
    )


def _provenance(raw_payload_id: str) -> HistoricalProvenance:
    return HistoricalProvenance(
        source_id=SOURCE_ID,
        connector_name="fixture-s4-004-connector",
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
    source_offset: int = 0,
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
        base_volume=Decimal("10") + Decimal(index),
        quote_volume=(Decimal("10") + Decimal(index)) * close,
        trade_count=100 + index,
        vwap=close,
        source_ts=close_ts + timedelta(seconds=source_offset),
        ingest_ts=NOW + timedelta(hours=index),
        quality_flags=(QualityFlag.LATE,),
        raw_payload_id=f"RAW:S4-004:{timeframe.upper()}:{index}",
    )


def _page(records: tuple[OHLCTVBar, ...], raw_id: str) -> HistoricalBackfillPage:
    return HistoricalBackfillPage(
        page_id=HistoricalBackfillPage.build_page_id(
            request_id="HISTREQ:S4-004",
            data_kind=MarketDataKind.OHLCTV,
            raw_payload_id=raw_id,
            cursor=None,
        ),
        request_id="HISTREQ:S4-004",
        data_kind=MarketDataKind.OHLCTV,
        records=records,
        provenance=_provenance(raw_id),
        fetched_at=NOW,
    )


def _batch(
    closes: tuple[str, ...], *, timeframe: str = "1m", minutes: int = 1, source_offset: int = 0
) -> SilverNormalizationBatch:
    bars = tuple(
        _bar(
            index,
            Decimal(close),
            timeframe=timeframe,
            minutes=minutes,
            source_offset=source_offset,
        )
        for index, close in enumerate(closes)
    )
    raw_id = bars[0].raw_payload_id
    normalized = tuple(bar.model_copy(update={"raw_payload_id": raw_id}) for bar in bars)
    return normalize_historical_page(
        _page(normalized, raw_id), venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID
    )


def _quote(index: int, bid: str, ask: str, *, source_offset: int = 0) -> QuoteFeatureInput:
    event_ts = START + timedelta(minutes=index)
    source_ts = event_ts + timedelta(seconds=source_offset)
    best_bid = Decimal(bid)
    best_ask = Decimal(ask)
    raw_payload_id = f"RAW:S4-004:QUOTE:{index}"
    quality_flags: tuple[str, ...] = ()
    return QuoteFeatureInput(
        quote_feature_input_id=build_quote_feature_input_id(
            instrument_id=INSTRUMENT_ID,
            venue_id=VENUE_ID,
            event_ts=event_ts,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=Decimal("1"),
            ask_size=Decimal("2"),
            source_ts=source_ts,
            quality_flags=quality_flags,
            raw_payload_id=raw_payload_id,
        ),
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        event_ts=event_ts,
        best_bid=best_bid,
        best_ask=best_ask,
        bid_size=Decimal("1"),
        ask_size=Decimal("2"),
        source_ts=source_ts,
        ingest_ts=NOW + timedelta(hours=index),
        quality_flags=quality_flags,
        raw_payload_id=raw_payload_id,
    )


def _fee(effective_from: datetime = START) -> FeeSchedule:
    return FeeSchedule(
        fee_schedule_id=f"FEE:S4-004:{effective_from.strftime('%H%M%S')}",
        venue_id=VENUE_ID,
        fee_tier_id="FEE:TIER:FIXTURE",
        maker_fee_rate=Decimal("0.001"),
        taker_fee_rate=Decimal("0.002"),
        min_fee=Decimal("0"),
        effective_from=effective_from,
        effective_to=None,
        source_id=SOURCE_ID,
        source_version="fixture",
        metadata_ts=effective_from,
    )


def _label_rule() -> LabelRule:
    return build_label_rule(name="future_1m", horizon_seconds=60, method=LabelMethod.FUTURE_VALUE)


def _observations(values: tuple[str, ...]) -> tuple[LabelObservation, ...]:
    return tuple(
        build_label_observation(
            instrument_id=INSTRUMENT_ID,
            venue_id=VENUE_ID,
            event_ts=START + timedelta(minutes=index + 2),
            value=Decimal(value),
            source_lineage_id=f"LABELSOURCE:S4-004:{index + 2}",
        )
        for index, value in enumerate(values)
    )


def _split_windows() -> tuple[ChronologicalSplitWindow, ...]:
    return (
        ChronologicalSplitWindow(
            split=DatasetSplit.TRAIN,
            start_ts=START,
            end_ts=START + timedelta(minutes=5),
        ),
        ChronologicalSplitWindow(
            split=DatasetSplit.VALIDATION,
            start_ts=START + timedelta(minutes=5),
            end_ts=START + timedelta(minutes=7),
        ),
        ChronologicalSplitWindow(
            split=DatasetSplit.TEST,
            start_ts=START + timedelta(minutes=7),
            end_ts=START + timedelta(minutes=9),
        ),
    )


def _merged_vectors(
    batch: SilverNormalizationBatch,
    *,
    quotes: tuple[QuoteFeatureInput, ...],
    higher_timeframe_batch: SilverNormalizationBatch | None = None,
) -> tuple[FeatureVector, ...]:
    ta_vectors = build_ta_feature_vectors(batch, higher_timeframe_batch=higher_timeframe_batch)
    liquidity_vectors = build_liquidity_cost_feature_vectors(
        batch, quotes=quotes, fee_schedules=(_fee(),)
    )
    merged: list[FeatureVector] = []
    for record, ta_vector, liquidity_vector in zip(
        batch.records, ta_vectors, liquidity_vectors, strict=True
    ):
        bar_record = cast(SilverOHLCTVRecord, record)
        values: dict[str, FeatureValue] = {
            "close": bar_record.bar.close,
            **{f"ta_{name}": value for name, value in ta_vector.values.items()},
            **{f"liquidity_{name}": value for name, value in liquidity_vector.values.items()},
        }
        quality_flags = tuple(
            sorted(
                {*ta_vector.quality_flags, *liquidity_vector.quality_flags},
                key=lambda flag: flag.value,
            )
        )
        input_snapshot_id = build_feature_input_snapshot_id(
            record_ids=(ta_vector.input_snapshot_id, liquidity_vector.input_snapshot_id)
        )
        feature_vector_id = build_feature_vector_id(
            instrument_id=ta_vector.instrument_id,
            venue_id=ta_vector.venue_id,
            feature_ts=ta_vector.feature_ts,
            feature_version=MERGED_FEATURE_VERSION,
            lookback_window="s4-004 merged TA/liquidity PIT inputs",
            values=values,
            input_snapshot_id=input_snapshot_id,
            quality_flags=quality_flags,
        )
        merged.append(
            FeatureVector(
                feature_vector_id=feature_vector_id,
                instrument_id=ta_vector.instrument_id,
                venue_id=ta_vector.venue_id,
                feature_ts=ta_vector.feature_ts,
                feature_version=MERGED_FEATURE_VERSION,
                lookback_window="s4-004 merged TA/liquidity PIT inputs",
                values=values,
                input_snapshot_id=input_snapshot_id,
                quality_flags=quality_flags,
            )
        )
    return tuple(merged)


def _dataset(
    vectors: tuple[FeatureVector, ...], observations: tuple[LabelObservation, ...]
) -> DatasetSnapshot:
    return build_chronological_dataset_snapshot(
        feature_vectors=vectors,
        label_observations=observations,
        split_windows=_split_windows(),
        label_rule=_label_rule(),
        source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
    )


def _row_dumps(
    vectors: tuple[FeatureVector, ...], observations: tuple[LabelObservation, ...]
) -> tuple[dict[str, Any], ...]:
    return tuple(row.model_dump() for row in _dataset(vectors, observations).rows)


def test_ta_batch_vs_incremental_stream_parity_and_future_bar_invariance() -> None:
    closes = ("100", "101", "103", "106", "110", "111", "113", "117")
    batch_vectors = build_ta_feature_vectors(_batch(closes))

    incremental = tuple(
        build_ta_feature_vectors(_batch(closes[: index + 1]))[-1]
        for index in range(len(closes))
    )

    assert tuple(vector.model_dump() for vector in incremental) == tuple(
        vector.model_dump() for vector in batch_vectors
    )

    mutated_future = build_ta_feature_vectors(_batch((*closes[:-1], "999")))
    assert tuple(vector.model_dump() for vector in batch_vectors[:-1]) == tuple(
        vector.model_dump() for vector in mutated_future[:-1]
    )
    assert batch_vectors[-1].feature_vector_id != mutated_future[-1].feature_vector_id


def test_liquidity_cost_batch_vs_incremental_stream_parity_and_future_quote_invariance() -> None:
    closes = ("100", "101", "103", "106", "110", "111")
    quotes = (_quote(0, "99", "101"), _quote(3, "104", "108"), _quote(10, "1", "1000"))
    batch_vectors = build_liquidity_cost_feature_vectors(
        _batch(closes), quotes=quotes, fee_schedules=(_fee(),)
    )

    incremental = tuple(
        build_liquidity_cost_feature_vectors(
            _batch(closes[: index + 1]),
            quotes=tuple(
                quote
                for quote in quotes
                if quote.event_ts <= START + timedelta(minutes=index + 1)
            ),
            fee_schedules=(_fee(),),
        )[-1]
        for index in range(len(closes))
    )

    assert tuple(vector.model_dump() for vector in incremental) == tuple(
        vector.model_dump() for vector in batch_vectors
    )

    mutated_future_quote = build_liquidity_cost_feature_vectors(
        _batch(closes),
        quotes=(_quote(0, "99", "101"), _quote(3, "104", "108"), _quote(10, "900", "1000")),
        fee_schedules=(_fee(),),
    )
    assert tuple(vector.model_dump() for vector in batch_vectors) == tuple(
        vector.model_dump() for vector in mutated_future_quote
    )


def test_integrated_dataset_batch_vs_incremental_parity_for_available_label_horizon() -> None:
    closes = ("100", "101", "103", "106", "110", "111", "113", "117")
    vectors = _merged_vectors(
        _batch(closes), quotes=(_quote(0, "99", "101"), _quote(4, "108", "112"))
    )
    observations = _observations(("101", "103", "106", "110", "111", "113", "117", "120"))
    full_rows = _row_dumps(vectors, observations)

    for prefix_len in range(1, len(vectors) + 1):
        assert _row_dumps(vectors[:prefix_len], observations[:prefix_len]) == full_rows[:prefix_len]


def test_future_bar_quote_and_label_mutations_only_change_dependent_dataset_rows() -> None:
    closes = ("100", "101", "103", "106", "110", "111", "113", "117")
    quotes = (_quote(0, "99", "101"), _quote(4, "108", "112"), _quote(20, "1", "1000"))
    baseline_vectors = _merged_vectors(_batch(closes), quotes=quotes)
    baseline = _dataset(
        baseline_vectors,
        _observations(("101", "103", "106", "110", "111", "113", "117", "120")),
    )

    mutated_future_bar = _dataset(
        _merged_vectors(_batch((*closes[:-1], "999")), quotes=quotes),
        _observations(("101", "103", "106", "110", "111", "113", "117", "120")),
    )
    assert tuple(row.model_dump() for row in baseline.rows[:-1]) == tuple(
        row.model_dump() for row in mutated_future_bar.rows[:-1]
    )
    assert baseline.rows[-1].row_id != mutated_future_bar.rows[-1].row_id

    mutated_future_quote = _dataset(
        _merged_vectors(
            _batch(closes),
            quotes=(_quote(0, "99", "101"), _quote(4, "108", "112"), _quote(20, "900", "1000")),
        ),
        _observations(("101", "103", "106", "110", "111", "113", "117", "120")),
    )
    assert tuple(row.model_dump() for row in baseline.rows) == tuple(
        row.model_dump() for row in mutated_future_quote.rows
    )

    mutated_label = _dataset(
        baseline_vectors,
        _observations(("101", "103", "999", "110", "111", "113", "117", "120")),
    )
    assert tuple(row.model_dump() for row in baseline.rows[:2]) == tuple(
        row.model_dump() for row in mutated_label.rows[:2]
    )
    assert baseline.rows[2].row_id != mutated_label.rows[2].row_id
    assert tuple(row.model_dump() for row in baseline.rows[3:]) == tuple(
        row.model_dump() for row in mutated_label.rows[3:]
    )


def test_higher_timeframe_lag_remains_enforced_in_integrated_vectors() -> None:
    base = _batch(("100", "101", "102", "103", "104", "105"))
    higher = _batch(("1000", "1100"), timeframe="5m", minutes=5)
    vectors = _merged_vectors(base, quotes=(_quote(0, "99", "101"),), higher_timeframe_batch=higher)

    assert vectors[0].values["ta_htf_close"] is None
    assert vectors[3].values["ta_htf_close"] is None
    assert vectors[4].feature_ts == START + timedelta(minutes=5)
    assert vectors[4].values["ta_htf_close"] == Decimal("1000")
    assert vectors[5].values["ta_htf_close"] == Decimal("1000")


def test_split_assignment_uses_feature_ts_even_when_label_ts_crosses_split_boundary() -> None:
    vectors = _merged_vectors(
        _batch(("100", "101", "103", "106", "110", "111", "113", "117")),
        quotes=(_quote(0, "99", "101"), _quote(4, "108", "112")),
    )
    snapshot = _dataset(
        vectors, _observations(("101", "103", "106", "110", "111", "113", "117", "120"))
    )

    boundary_row = snapshot.rows[3]
    assert boundary_row.feature_ts == START + timedelta(minutes=4)
    assert boundary_row.label_ts == START + timedelta(minutes=5)
    assert boundary_row.split is DatasetSplit.TRAIN
    assert snapshot.rows[4].split is DatasetSplit.VALIDATION


def test_intentionally_unsafe_leakage_fixtures_fail_closed() -> None:
    vector = _merged_vectors(_batch(("100",)), quotes=(_quote(0, "99", "101"),))[0]
    label_as_feature = vector.model_copy(
        update={"values": {**vector.values, "future_1m": Decimal("999")}}
    )
    with pytest.raises(DatasetSnapshotBuilderError, match="label fields"):
        _dataset((label_as_feature,), _observations(("101",)))

    with pytest.raises(LiquidityCostFeatureEngineError, match="no quote is available"):
        build_liquidity_cost_feature_vectors(
            _batch(("100",)),
            quotes=(_quote(0, "99", "101", source_offset=120),),
            fee_schedules=(_fee(),),
        )

    with pytest.raises(LiquidityCostFeatureEngineError, match="source_ts"):
        build_liquidity_cost_feature_vectors(
            _batch(("100",), source_offset=1),
            quotes=(_quote(0, "99", "101"),),
            fee_schedules=(_fee(),),
        )

    with pytest.raises(TAFeatureEngineError, match="strictly increasing"):
        valid = _batch(("100", "101"))
        build_ta_feature_vectors(
            valid.model_copy(update={"records": (valid.records[0], valid.records[0])})
        )

    wrong_horizon_observation = build_label_observation(
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        event_ts=START + timedelta(minutes=3),
        value=Decimal("103"),
        source_lineage_id="LABELSOURCE:S4-004:WRONG-HORIZON",
    )
    with pytest.raises(DatasetSnapshotBuilderError, match="missing label observation"):
        _dataset((vector,), (wrong_horizon_observation,))

    assert FeatureQualityFlag.MISSING in vector.quality_flags
