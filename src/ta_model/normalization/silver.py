"""Silver normalization for validated historical market-data pages.

Traceability:
- FR-001: validated historical OHLCTV/trade records carry raw-payload lineage.
- FR-003: records preserve canonical source, venue, instrument, and timeframe scope.

Scope:
- S2-003 normalizes already-validated historical pages into in-memory silver contracts.
- No real source parsers, completeness/gap reports, database persistence, Docker services,
  paper/live routes, leverage, derivatives, or live capital are introduced.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Self

from pydantic import Field, PositiveInt, model_validator

from ta_model.contracts.instrument_master import CanonicalId, ContractModel
from ta_model.contracts.market_data import (
    HistoricalBackfillPage,
    MarketDataKind,
    OHLCTVBar,
    SourceId,
    Timeframe,
    TradeRecord,
)


class SilverNormalizationError(ValueError):
    """Raised when a historical page cannot fail-closed into silver records."""


class SilverOHLCTVRecord(ContractModel):
    """Silver OHLCTV record with deterministic ID and bronze lineage."""

    silver_record_id: CanonicalId
    source_id: SourceId
    venue_id: CanonicalId
    instrument_id: CanonicalId
    timeframe: Timeframe
    raw_payload_id: CanonicalId
    page_id: CanonicalId
    request_id: CanonicalId
    bar: OHLCTVBar

    @model_validator(mode="after")
    def lineage_matches_bar(self) -> Self:
        if self.bar.venue_id != self.venue_id:
            raise ValueError("bar venue_id must match silver venue_id")
        if self.bar.instrument_id != self.instrument_id:
            raise ValueError("bar instrument_id must match silver instrument_id")
        if self.bar.timeframe != self.timeframe:
            raise ValueError("bar timeframe must match silver timeframe")
        if self.bar.raw_payload_id != self.raw_payload_id:
            raise ValueError("bar raw_payload_id must match silver raw_payload_id")
        if self.silver_record_id != build_silver_ohlctv_record_id(
            source_id=self.source_id,
            venue_id=self.venue_id,
            instrument_id=self.instrument_id,
            timeframe=self.timeframe,
            raw_payload_id=self.raw_payload_id,
            bar=self.bar,
        ):
            raise ValueError("silver_record_id is not deterministic for OHLCTV record")
        return self


class SilverTradeRecord(ContractModel):
    """Silver trade record with deterministic ID and bronze lineage."""

    silver_record_id: CanonicalId
    source_id: SourceId
    venue_id: CanonicalId
    instrument_id: CanonicalId
    raw_payload_id: CanonicalId
    page_id: CanonicalId
    request_id: CanonicalId
    trade: TradeRecord

    @model_validator(mode="after")
    def lineage_matches_trade(self) -> Self:
        if self.trade.instrument_id != self.instrument_id:
            raise ValueError("trade instrument_id must match silver instrument_id")
        if not _instrument_id_matches_venue(self.instrument_id, self.venue_id):
            raise ValueError("trade instrument_id must match silver venue_id scope")
        if self.trade.raw_payload_id != self.raw_payload_id:
            raise ValueError("trade raw_payload_id must match silver raw_payload_id")
        if self.silver_record_id != build_silver_trade_record_id(
            source_id=self.source_id,
            venue_id=self.venue_id,
            instrument_id=self.instrument_id,
            raw_payload_id=self.raw_payload_id,
            trade=self.trade,
        ):
            raise ValueError("silver_record_id is not deterministic for trade record")
        return self


SilverRecord = SilverOHLCTVRecord | SilverTradeRecord


class SilverNormalizationBatch(ContractModel):
    """Deterministic batch of silver records produced from historical page(s)."""

    batch_id: CanonicalId
    request_id: CanonicalId
    data_kind: MarketDataKind
    source_id: SourceId
    venue_id: CanonicalId
    instrument_id: CanonicalId
    timeframe: Timeframe | None = None
    page_ids: tuple[CanonicalId, ...]
    raw_payload_ids: tuple[CanonicalId, ...]
    records: tuple[SilverRecord, ...]
    record_count: PositiveInt = Field(description="Number of silver records in the batch.")

    @model_validator(mode="after")
    def batch_scope_matches_records(self) -> Self:
        if self.record_count != len(self.records):
            raise ValueError("record_count must match records length")
        if len(self.page_ids) == 0:
            raise ValueError("page_ids must not be empty")
        if len(self.raw_payload_ids) == 0:
            raise ValueError("raw_payload_ids must not be empty")

        expected_type: type[SilverOHLCTVRecord] | type[SilverTradeRecord]
        expected_type = (
            SilverOHLCTVRecord if self.data_kind is MarketDataKind.OHLCTV else SilverTradeRecord
        )
        if not all(isinstance(record, expected_type) for record in self.records):
            raise ValueError("records must match batch data_kind")
        if self.data_kind is MarketDataKind.OHLCTV and self.timeframe is None:
            raise ValueError("timeframe is required for OHLCTV silver batches")
        if self.data_kind is MarketDataKind.TRADE and self.timeframe is not None:
            raise ValueError("timeframe must be omitted for trade silver batches")
        for record in self.records:
            if record.source_id != self.source_id:
                raise ValueError("record source_id must match batch source_id")
            if record.venue_id != self.venue_id:
                raise ValueError("record venue_id must match batch venue_id")
            if record.instrument_id != self.instrument_id:
                raise ValueError("record instrument_id must match batch instrument_id")
            if record.raw_payload_id not in self.raw_payload_ids:
                raise ValueError("record raw_payload_id must be present in batch raw_payload_ids")
            if record.page_id not in self.page_ids:
                raise ValueError("record page_id must be present in batch page_ids")
        if self.batch_id != build_silver_batch_id(
            request_id=self.request_id,
            data_kind=self.data_kind,
            source_id=self.source_id,
            venue_id=self.venue_id,
            instrument_id=self.instrument_id,
            timeframe=self.timeframe,
            page_ids=self.page_ids,
            raw_payload_ids=self.raw_payload_ids,
            record_ids=tuple(record.silver_record_id for record in self.records),
        ):
            raise ValueError("batch_id is not deterministic for silver batch")
        return self


def normalize_historical_pages(
    pages: Sequence[HistoricalBackfillPage],
    *,
    venue_id: str,
    instrument_id: str,
) -> SilverNormalizationBatch:
    """Normalize validated historical pages into one deterministic silver batch."""

    if len(pages) == 0:
        raise SilverNormalizationError("at least one historical page is required")

    first = pages[0]
    request_id = first.request_id
    data_kind = first.data_kind
    source_id = first.provenance.source_id
    silver_records: list[SilverRecord] = []
    page_ids: list[str] = []
    raw_payload_ids: list[str] = []
    timeframe: str | None = None

    for page in pages:
        _validate_page_scope(
            page,
            request_id=request_id,
            data_kind=data_kind,
            source_id=source_id,
        )
        page_ids.append(page.page_id)
        raw_payload_id = page.provenance.raw_payload.raw_payload_id
        raw_payload_ids.append(raw_payload_id)
        for record in page.records:
            if isinstance(record, OHLCTVBar):
                if data_kind is not MarketDataKind.OHLCTV:
                    raise SilverNormalizationError("OHLCTV record found in non-OHLCTV page")
                if record.venue_id != venue_id or record.instrument_id != instrument_id:
                    raise SilverNormalizationError(
                        "OHLCTV record is outside requested venue/instrument scope"
                    )
                if timeframe is None:
                    timeframe = record.timeframe
                elif record.timeframe != timeframe:
                    raise SilverNormalizationError("OHLCTV records have mixed timeframes")
                silver_records.append(_normalize_bar(page, record))
            elif isinstance(record, TradeRecord):
                if data_kind is not MarketDataKind.TRADE:
                    raise SilverNormalizationError("trade record found in non-trade page")
                if record.instrument_id != instrument_id:
                    raise SilverNormalizationError(
                        "trade record is outside requested instrument scope"
                    )
                if not _instrument_id_matches_venue(record.instrument_id, venue_id):
                    raise SilverNormalizationError(
                        "trade record instrument_id is outside requested venue scope"
                    )
                silver_records.append(_normalize_trade(page, record, venue_id=venue_id))
            else:
                raise SilverNormalizationError("unsupported historical record type")

    if len(silver_records) == 0:
        raise SilverNormalizationError("silver batch must contain at least one record")
    if data_kind is MarketDataKind.TRADE:
        timeframe = None

    deduped_page_ids = tuple(dict.fromkeys(page_ids))
    deduped_raw_payload_ids = tuple(dict.fromkeys(raw_payload_ids))
    return SilverNormalizationBatch(
        batch_id=build_silver_batch_id(
            request_id=request_id,
            data_kind=data_kind,
            source_id=source_id,
            venue_id=venue_id,
            instrument_id=instrument_id,
            timeframe=timeframe,
            page_ids=deduped_page_ids,
            raw_payload_ids=deduped_raw_payload_ids,
            record_ids=tuple(record.silver_record_id for record in silver_records),
        ),
        request_id=request_id,
        data_kind=data_kind,
        source_id=source_id,
        venue_id=venue_id,
        instrument_id=instrument_id,
        timeframe=timeframe,
        page_ids=deduped_page_ids,
        raw_payload_ids=deduped_raw_payload_ids,
        records=tuple(silver_records),
        record_count=len(silver_records),
    )


def normalize_historical_page(
    page: HistoricalBackfillPage,
    *,
    venue_id: str,
    instrument_id: str,
) -> SilverNormalizationBatch:
    """Normalize one validated historical page into a deterministic silver batch."""

    return normalize_historical_pages((page,), venue_id=venue_id, instrument_id=instrument_id)


def build_silver_ohlctv_record_id(
    *,
    source_id: str,
    venue_id: str,
    instrument_id: str,
    timeframe: str,
    raw_payload_id: str,
    bar: OHLCTVBar,
) -> str:
    """Build a stable bar ID from event-time fields and immutable raw lineage."""

    return _stable_id(
        "SILVERBAR",
        {
            "base_volume": str(bar.base_volume),
            "close": str(bar.close),
            "close_ts": bar.close_ts.isoformat(),
            "high": str(bar.high),
            "instrument_id": instrument_id,
            "low": str(bar.low),
            "open": str(bar.open),
            "open_ts": bar.open_ts.isoformat(),
            "quality_flags": tuple(flag.value for flag in bar.quality_flags),
            "quote_volume": str(bar.quote_volume) if bar.quote_volume is not None else None,
            "raw_payload_id": raw_payload_id,
            "source_id": source_id,
            "source_ts": bar.source_ts.isoformat(),
            "timeframe": timeframe,
            "trade_count": bar.trade_count,
            "venue_id": venue_id,
            "vwap": str(bar.vwap) if bar.vwap is not None else None,
        },
    )


def build_silver_trade_record_id(
    *,
    source_id: str,
    venue_id: str,
    instrument_id: str,
    raw_payload_id: str,
    trade: TradeRecord,
) -> str:
    """Build a stable trade ID from event-time fields and immutable raw lineage."""

    return _stable_id(
        "SILVERTRADE",
        {
            "event_ts": trade.event_ts.isoformat(),
            "instrument_id": instrument_id,
            "price": str(trade.price),
            "quantity": str(trade.quantity),
            "raw_payload_id": raw_payload_id,
            "sequence": trade.sequence,
            "side": trade.side.value if trade.side is not None else None,
            "source_id": source_id,
            "source_trade_id": trade.trade_id,
            "source_ts": trade.source_ts.isoformat() if trade.source_ts is not None else None,
            "venue_id": venue_id,
        },
    )


def build_silver_batch_id(
    *,
    request_id: str,
    data_kind: MarketDataKind,
    source_id: str,
    venue_id: str,
    instrument_id: str,
    timeframe: str | None,
    page_ids: tuple[str, ...],
    raw_payload_ids: tuple[str, ...],
    record_ids: tuple[str, ...],
) -> str:
    """Build a stable silver batch ID without wall-clock or ingest-time inputs."""

    return _stable_id(
        "SILVERBATCH",
        {
            "data_kind": data_kind.value,
            "instrument_id": instrument_id,
            "page_ids": page_ids,
            "raw_payload_ids": raw_payload_ids,
            "record_ids": record_ids,
            "request_id": request_id,
            "source_id": source_id,
            "timeframe": timeframe,
            "venue_id": venue_id,
        },
    )


def _normalize_bar(page: HistoricalBackfillPage, bar: OHLCTVBar) -> SilverOHLCTVRecord:
    raw_payload_id = page.provenance.raw_payload.raw_payload_id
    if bar.raw_payload_id != raw_payload_id:
        raise SilverNormalizationError("bar raw_payload_id must match page provenance")
    return SilverOHLCTVRecord(
        silver_record_id=build_silver_ohlctv_record_id(
            source_id=page.provenance.source_id,
            venue_id=bar.venue_id,
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            raw_payload_id=raw_payload_id,
            bar=bar,
        ),
        source_id=page.provenance.source_id,
        venue_id=bar.venue_id,
        instrument_id=bar.instrument_id,
        timeframe=bar.timeframe,
        raw_payload_id=raw_payload_id,
        page_id=page.page_id,
        request_id=page.request_id,
        bar=bar,
    )


def _normalize_trade(
    page: HistoricalBackfillPage,
    trade: TradeRecord,
    *,
    venue_id: str,
) -> SilverTradeRecord:
    raw_payload_id = page.provenance.raw_payload.raw_payload_id
    if trade.raw_payload_id != raw_payload_id:
        raise SilverNormalizationError("trade raw_payload_id must match page provenance")
    return SilverTradeRecord(
        silver_record_id=build_silver_trade_record_id(
            source_id=page.provenance.source_id,
            venue_id=venue_id,
            instrument_id=trade.instrument_id,
            raw_payload_id=raw_payload_id,
            trade=trade,
        ),
        source_id=page.provenance.source_id,
        venue_id=venue_id,
        instrument_id=trade.instrument_id,
        raw_payload_id=raw_payload_id,
        page_id=page.page_id,
        request_id=page.request_id,
        trade=trade,
    )


def _validate_page_scope(
    page: HistoricalBackfillPage,
    *,
    request_id: str,
    data_kind: MarketDataKind,
    source_id: str,
) -> None:
    if page.request_id != request_id:
        raise SilverNormalizationError("all pages must share request_id")
    if page.data_kind is not data_kind:
        raise SilverNormalizationError("all pages must share data_kind")
    if page.provenance.source_id != source_id:
        raise SilverNormalizationError("all pages must share provenance source_id")
    if page.provenance.raw_payload.source_id != page.provenance.source_id:
        raise SilverNormalizationError("raw payload source_id must match page provenance source_id")
    raw_payload_id = page.provenance.raw_payload.raw_payload_id
    for record in page.records:
        if record.raw_payload_id != raw_payload_id:
            raise SilverNormalizationError("record raw_payload_id must match page provenance")


def _stable_id(prefix: str, payload: object) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    return f"{prefix}:{digest.upper()}"


def _instrument_id_matches_venue(instrument_id: str, venue_id: str) -> bool:
    """Validate fixture canonical instrument IDs that are scoped as VENUE_ID:SYMBOL."""

    return instrument_id.startswith(f"{venue_id}:")
