"""Evidence for S2-004 historical silver data-quality reporting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ta_model.contracts.market_data import (
    HistoricalBackfillPage,
    HistoricalProvenance,
    MarketDataKind,
    OHLCTVBar,
    QualityFlag,
    RawPayloadReference,
    TradeRecord,
    TradeSide,
    deterministic_payload_hash,
)
from ta_model.normalization.silver import normalize_historical_page
from ta_model.validation.data_quality import (
    DataQualityReportConfig,
    DataQualityThresholds,
    GateDecision,
    MetricStatus,
    evaluate_silver_ohlctv_batch,
    evaluate_silver_trade_batch,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
SOURCE_ID = "FIXTURE_HISTORICAL_SOURCE"
VENUE_ID = "FIXTURE_SPOT"
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"


def _raw_payload(raw_payload_id: str) -> RawPayloadReference:
    return RawPayloadReference(
        raw_payload_id=raw_payload_id,
        source_id=SOURCE_ID,
        content_hash=deterministic_payload_hash(
            {"fixture": "s2-004-data-quality", "raw_payload_id": raw_payload_id}
        ),
        uri=f"fixture://historical/{raw_payload_id}",
        content_type="application/json",
        fetched_at=NOW,
        byte_count=512,
    )


def _provenance(raw_payload_id: str) -> HistoricalProvenance:
    return HistoricalProvenance(
        source_id=SOURCE_ID,
        connector_name="fixture-historical-connector",
        connector_version="0.0.0-test",
        fetched_at=NOW,
        raw_payload=_raw_payload(raw_payload_id),
    )


def _bar(offset_minutes: int, raw_payload_id: str = "RAW:S2-004:BAR") -> OHLCTVBar:
    open_ts = START + timedelta(minutes=offset_minutes)
    close_ts = open_ts + timedelta(minutes=1)
    return OHLCTVBar(
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        timeframe="1m",
        open_ts=open_ts,
        close_ts=close_ts,
        open=Decimal("100.00"),
        high=Decimal("110.00"),
        low=Decimal("95.00"),
        close=Decimal("105.00"),
        base_volume=Decimal("2.50"),
        quote_volume=Decimal("262.50"),
        trade_count=10,
        vwap=Decimal("102.50"),
        source_ts=close_ts,
        ingest_ts=NOW + timedelta(days=offset_minutes + 1),
        quality_flags=(QualityFlag.LATE,),
        raw_payload_id=raw_payload_id,
    )


def _trade(
    trade_id: str,
    sequence: int | None,
    offset_seconds: int,
    raw_payload_id: str = "RAW:S2-004:TRADE",
) -> TradeRecord:
    event_ts = START + timedelta(seconds=offset_seconds)
    return TradeRecord(
        trade_id=trade_id,
        instrument_id=INSTRUMENT_ID,
        event_ts=event_ts,
        price=Decimal("101.00"),
        quantity=Decimal("0.25"),
        side=TradeSide.BUYER,
        sequence=sequence,
        source_ts=event_ts,
        ingest_ts=NOW + timedelta(days=1, seconds=offset_seconds),
        raw_payload_id=raw_payload_id,
    )


def _page(
    data_kind: MarketDataKind,
    records: tuple[OHLCTVBar | TradeRecord, ...],
    raw_payload_id: str,
) -> HistoricalBackfillPage:
    return HistoricalBackfillPage(
        page_id=HistoricalBackfillPage.build_page_id(
            request_id="HISTREQ:S2-004",
            data_kind=data_kind,
            raw_payload_id=raw_payload_id,
            cursor=None,
        ),
        request_id="HISTREQ:S2-004",
        data_kind=data_kind,
        records=records,
        provenance=_provenance(raw_payload_id),
        fetched_at=NOW,
    )


def _ohlctv_config(
    *, thresholds: DataQualityThresholds | None = None
) -> DataQualityReportConfig:
    return DataQualityReportConfig(
        source_id=SOURCE_ID,
        venue_id=VENUE_ID,
        instrument_id=INSTRUMENT_ID,
        data_kind=MarketDataKind.OHLCTV,
        timeframe="1m",
        window_start=START,
        window_end=START + timedelta(minutes=3),
        thresholds=thresholds or DataQualityThresholds(),
    )


def _trade_config(*, thresholds: DataQualityThresholds | None = None) -> DataQualityReportConfig:
    return DataQualityReportConfig(
        source_id=SOURCE_ID,
        venue_id=VENUE_ID,
        instrument_id=INSTRUMENT_ID,
        data_kind=MarketDataKind.TRADE,
        window_start=START,
        window_end=START + timedelta(minutes=1),
        thresholds=thresholds or DataQualityThresholds(),
    )


def test_complete_ohlctv_window_passes_and_preserves_scope() -> None:
    page = _page(MarketDataKind.OHLCTV, (_bar(0), _bar(1), _bar(2)), "RAW:S2-004:BAR")
    batch = normalize_historical_page(page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)

    report = evaluate_silver_ohlctv_batch(batch, _ohlctv_config())

    assert report.decision is GateDecision.PASS
    assert report.blockers == ()
    assert report.scope.source_id == SOURCE_ID
    assert report.scope.venue_id == VENUE_ID
    assert report.scope.instrument_id == INSTRUMENT_ID
    assert report.scope.timeframe == "1m"
    assert report.event_time_fields_used == ("open_ts", "close_ts")
    assert report.ingest_time_used_for_quality_decision is False
    assert report.ohlctv_metrics is not None
    assert report.ohlctv_metrics.expected_interval_count == 3
    assert report.ohlctv_metrics.missing_interval_count == 0


def test_missing_ohlctv_interval_blocks_data_gate() -> None:
    page = _page(MarketDataKind.OHLCTV, (_bar(0), _bar(2)), "RAW:S2-004:BAR")
    batch = normalize_historical_page(page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)

    report = evaluate_silver_ohlctv_batch(batch, _ohlctv_config())

    assert report.decision is GateDecision.BLOCKED
    assert report.ohlctv_metrics is not None
    assert report.ohlctv_metrics.completeness_status is MetricStatus.FAIL
    assert report.ohlctv_metrics.gap_status is MetricStatus.FAIL
    assert report.ohlctv_metrics.missing_intervals == (START + timedelta(minutes=1),)
    assert {blocker.code for blocker in report.blockers} == {
        "DQB:S2-004:MISSING_BARS",
        "DQB:S2-004:GAPS",
    }


def test_duplicate_ohlctv_bars_are_detected() -> None:
    page = _page(
        MarketDataKind.OHLCTV,
        (_bar(0), _bar(1), _bar(1), _bar(2)),
        "RAW:S2-004:BAR",
    )
    batch = normalize_historical_page(page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)

    report = evaluate_silver_ohlctv_batch(batch, _ohlctv_config())

    assert report.decision is GateDecision.BLOCKED
    assert report.ohlctv_metrics is not None
    assert report.ohlctv_metrics.duplicate_status is MetricStatus.FAIL
    assert report.ohlctv_metrics.duplicate_bar_count == 1
    assert report.ohlctv_metrics.duplicate_intervals == (START + timedelta(minutes=1),)
    assert report.blockers[0].code == "DQB:S2-004:DUPLICATE_BARS"


def test_trade_duplicate_ids_and_sequences_are_detected() -> None:
    page = _page(
        MarketDataKind.TRADE,
        (
            _trade("fixture-trade-1", 10, 1),
            _trade("fixture-trade-1", 11, 2),
            _trade("fixture-trade-3", 10, 3),
        ),
        "RAW:S2-004:TRADE",
    )
    batch = normalize_historical_page(page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)

    report = evaluate_silver_trade_batch(batch, _trade_config())

    assert report.decision is GateDecision.BLOCKED
    assert report.trade_metrics is not None
    assert report.trade_metrics.duplicate_status is MetricStatus.FAIL
    assert report.trade_metrics.duplicate_trade_ids == ("fixture-trade-1",)
    assert report.trade_metrics.duplicate_sequences == (10,)
    assert report.trade_metrics.duplicate_record_count == 3
    assert report.event_time_fields_used == ("event_ts",)
    assert report.blockers[0].code == "DQB:S2-004:DUPLICATE_TRADES"


def test_event_time_not_ingest_time_drives_ohlctv_completeness() -> None:
    late_ingest_complete_page = _page(
        MarketDataKind.OHLCTV,
        (_bar(0), _bar(1), _bar(2)),
        "RAW:S2-004:BAR",
    )
    missing_event_page = _page(
        MarketDataKind.OHLCTV,
        (_bar(0), _bar(2)),
        "RAW:S2-004:BAR",
    )

    complete_batch = normalize_historical_page(
        late_ingest_complete_page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID
    )
    missing_batch = normalize_historical_page(
        missing_event_page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID
    )

    assert (
        evaluate_silver_ohlctv_batch(complete_batch, _ohlctv_config()).decision
        is GateDecision.PASS
    )
    assert (
        evaluate_silver_ohlctv_batch(missing_batch, _ohlctv_config()).decision
        is GateDecision.BLOCKED
    )


def test_configurable_thresholds_can_allow_known_fixture_duplicate_rate() -> None:
    page = _page(
        MarketDataKind.OHLCTV,
        (_bar(0), _bar(1), _bar(1), _bar(2)),
        "RAW:S2-004:BAR",
    )
    batch = normalize_historical_page(page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)
    relaxed = DataQualityThresholds(max_duplicate_rate=0.25)

    report = evaluate_silver_ohlctv_batch(batch, _ohlctv_config(thresholds=relaxed))

    assert report.decision is GateDecision.PASS
    assert report.ohlctv_metrics is not None
    assert report.ohlctv_metrics.duplicate_rate == 0.25
    assert report.ohlctv_metrics.duplicate_status is MetricStatus.PASS
