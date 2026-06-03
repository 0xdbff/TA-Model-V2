"""Evidence for S2-003 historical silver normalization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

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
from ta_model.normalization.silver import (
    SilverNormalizationError,
    SilverOHLCTVRecord,
    SilverTradeRecord,
    normalize_historical_page,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
END = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
SOURCE_ID = "FIXTURE_HISTORICAL_SOURCE"
VENUE_ID = "FIXTURE_SPOT"
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"


def _raw_payload(raw_payload_id: str) -> RawPayloadReference:
    return RawPayloadReference(
        raw_payload_id=raw_payload_id,
        source_id=SOURCE_ID,
        content_hash=deterministic_payload_hash(
            {"fixture": "silver-normalization", "raw_payload_id": raw_payload_id}
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


def _bar(
    raw_payload_id: str = "RAW:S2-003:BAR-1",
    *,
    instrument_id: str = INSTRUMENT_ID,
    venue_id: str = VENUE_ID,
    ingest_ts: datetime = NOW,
) -> OHLCTVBar:
    return OHLCTVBar(
        instrument_id=instrument_id,
        venue_id=venue_id,
        timeframe="1m",
        open_ts=START,
        close_ts=END,
        open=Decimal("100.00"),
        high=Decimal("110.00"),
        low=Decimal("95.00"),
        close=Decimal("105.00"),
        base_volume=Decimal("2.50"),
        quote_volume=Decimal("262.50"),
        trade_count=10,
        vwap=Decimal("102.50"),
        source_ts=END,
        ingest_ts=ingest_ts,
        quality_flags=(QualityFlag.LATE,),
        raw_payload_id=raw_payload_id,
    )


def _trade(
    raw_payload_id: str = "RAW:S2-003:TRADE-1",
    *,
    instrument_id: str = INSTRUMENT_ID,
    ingest_ts: datetime = NOW,
) -> TradeRecord:
    return TradeRecord(
        trade_id="fixture-trade-1",
        instrument_id=instrument_id,
        event_ts=START + timedelta(seconds=10),
        price=Decimal("101.00"),
        quantity=Decimal("0.25"),
        side=TradeSide.BUYER,
        sequence=1,
        source_ts=START + timedelta(seconds=10),
        ingest_ts=ingest_ts,
        raw_payload_id=raw_payload_id,
    )


def _page(
    data_kind: MarketDataKind,
    records: tuple[OHLCTVBar | TradeRecord, ...],
    raw_payload_id: str,
) -> HistoricalBackfillPage:
    return HistoricalBackfillPage(
        page_id=HistoricalBackfillPage.build_page_id(
            request_id="HISTREQ:S2-003",
            data_kind=data_kind,
            raw_payload_id=raw_payload_id,
            cursor=None,
        ),
        request_id="HISTREQ:S2-003",
        data_kind=data_kind,
        records=records,
        provenance=_provenance(raw_payload_id),
        fetched_at=NOW,
    )


def test_valid_ohlctv_page_normalizes_to_silver_with_lineage() -> None:
    page = _page(MarketDataKind.OHLCTV, (_bar(),), "RAW:S2-003:BAR-1")

    batch = normalize_historical_page(page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)

    assert batch.data_kind is MarketDataKind.OHLCTV
    assert batch.source_id == SOURCE_ID
    assert batch.venue_id == VENUE_ID
    assert batch.instrument_id == INSTRUMENT_ID
    assert batch.timeframe == "1m"
    assert batch.raw_payload_ids == ("RAW:S2-003:BAR-1",)
    record = batch.records[0]
    assert isinstance(record, SilverOHLCTVRecord)
    assert record.bar.open_ts == START
    assert record.bar.close_ts == END
    assert record.bar.source_ts == END
    assert record.bar.ingest_ts == NOW
    assert record.raw_payload_id == page.provenance.raw_payload.raw_payload_id


def test_valid_trade_page_normalizes_to_silver_with_venue_scope() -> None:
    page = _page(MarketDataKind.TRADE, (_trade(),), "RAW:S2-003:TRADE-1")

    batch = normalize_historical_page(page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)

    assert batch.data_kind is MarketDataKind.TRADE
    assert batch.timeframe is None
    assert batch.records[0].venue_id == VENUE_ID
    assert batch.records[0].instrument_id == INSTRUMENT_ID
    assert batch.records[0].raw_payload_id == "RAW:S2-003:TRADE-1"


def test_trade_normalization_rejects_wrong_venue_scope() -> None:
    page = _page(MarketDataKind.TRADE, (_trade(),), "RAW:S2-003:TRADE-1")

    with pytest.raises(SilverNormalizationError, match="outside requested venue scope"):
        normalize_historical_page(
            page,
            venue_id="WRONG_VENUE",
            instrument_id=INSTRUMENT_ID,
        )


def test_ohlc_and_trade_invariants_reject_before_normalization() -> None:
    with pytest.raises(ValidationError, match="high must be >="):
        OHLCTVBar.model_validate({**_bar().model_dump(), "high": Decimal("99.00")})

    with pytest.raises(ValidationError, match="greater than 0"):
        TradeRecord.model_validate({**_trade().model_dump(), "quantity": Decimal("0")})


def test_data_kind_mismatch_fails_closed() -> None:
    bar = _bar()

    with pytest.raises(ValidationError, match="records must match page data_kind"):
        _page(MarketDataKind.TRADE, (bar,), "RAW:S2-003:BAR-1")

    bypassed = HistoricalBackfillPage.model_construct(
        page_id="HISTPAGE:BYPASSED-DATA-KIND",
        request_id="HISTREQ:S2-003",
        data_kind=MarketDataKind.TRADE,
        records=(bar,),
        provenance=_provenance("RAW:S2-003:BAR-1"),
        fetched_at=NOW,
        next_cursor=None,
    )
    with pytest.raises(SilverNormalizationError, match="OHLCTV record found"):
        normalize_historical_page(bypassed, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)


def test_raw_payload_lineage_mismatch_fails_closed() -> None:
    with pytest.raises(ValidationError, match="record raw_payload_id must match"):
        _page(MarketDataKind.OHLCTV, (_bar("RAW:S2-003:OTHER"),), "RAW:S2-003:BAR-1")

    bypassed = HistoricalBackfillPage.model_construct(
        page_id="HISTPAGE:BYPASSED-LINEAGE",
        request_id="HISTREQ:S2-003",
        data_kind=MarketDataKind.TRADE,
        records=(_trade("RAW:S2-003:OTHER"),),
        provenance=_provenance("RAW:S2-003:TRADE-1"),
        fetched_at=NOW,
        next_cursor=None,
    )
    with pytest.raises(SilverNormalizationError, match="raw_payload_id must match"):
        normalize_historical_page(bypassed, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)


def test_source_venue_instrument_scoping_fails_closed() -> None:
    wrong_instrument_page = _page(
        MarketDataKind.OHLCTV,
        (_bar(instrument_id="FIXTURE_SPOT:ETH-USD"),),
        "RAW:S2-003:BAR-1",
    )
    with pytest.raises(SilverNormalizationError, match="outside requested venue/instrument"):
        normalize_historical_page(
            wrong_instrument_page,
            venue_id=VENUE_ID,
            instrument_id=INSTRUMENT_ID,
        )

    wrong_source_page = HistoricalBackfillPage.model_construct(
        page_id="HISTPAGE:BYPASSED-SOURCE",
        request_id="HISTREQ:S2-003",
        data_kind=MarketDataKind.OHLCTV,
        records=(_bar(),),
        provenance=HistoricalProvenance.model_construct(
            source_id="FIXTURE_OTHER_SOURCE",
            connector_name="fixture-historical-connector",
            connector_version="0.0.0-test",
            fetched_at=NOW,
            raw_payload=_raw_payload("RAW:S2-003:BAR-1"),
        ),
        fetched_at=NOW,
        next_cursor=None,
    )
    with pytest.raises(SilverNormalizationError, match="raw payload source_id must match"):
        normalize_historical_page(
            wrong_source_page,
            venue_id=VENUE_ID,
            instrument_id=INSTRUMENT_ID,
        )


def test_deterministic_ids_do_not_use_ingest_time() -> None:
    first_page = _page(MarketDataKind.TRADE, (_trade(ingest_ts=NOW),), "RAW:S2-003:TRADE-1")
    second_page = _page(
        MarketDataKind.TRADE,
        (_trade(ingest_ts=NOW + timedelta(hours=1)),),
        "RAW:S2-003:TRADE-1",
    )

    first = normalize_historical_page(first_page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)
    second = normalize_historical_page(second_page, venue_id=VENUE_ID, instrument_id=INSTRUMENT_ID)

    assert first.records[0].silver_record_id == second.records[0].silver_record_id
    assert first.batch_id == second.batch_id
    assert isinstance(first.records[0], SilverTradeRecord)
    assert isinstance(second.records[0], SilverTradeRecord)
    assert first.records[0].trade.event_ts == START + timedelta(seconds=10)
    assert second.records[0].trade.event_ts == START + timedelta(seconds=10)


def test_unknown_silver_fields_are_rejected() -> None:
    page = _page(MarketDataKind.OHLCTV, (_bar(),), "RAW:S2-003:BAR-1")
    record = normalize_historical_page(
        page,
        venue_id=VENUE_ID,
        instrument_id=INSTRUMENT_ID,
    ).records[0]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SilverOHLCTVRecord.model_validate({**record.model_dump(), "provider_surprise": "drift"})
