"""Contract evidence for S2-001 historical connector interface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ta_model.connectors.historical import HistoricalConnector
from ta_model.contracts.market_data import (
    ApprovedUseStatus,
    HistoricalBackfillPage,
    HistoricalBackfillRequest,
    HistoricalProvenance,
    LicenseReviewStatus,
    MarketDataKind,
    OHLCTVBar,
    QualityFlag,
    RateLimitState,
    RawPayloadReference,
    RetryState,
    SourceApproval,
    TradeRecord,
    TradeSide,
    deterministic_payload_hash,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
END = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
SOURCE_ID = "FIXTURE_HISTORICAL_SOURCE"
VENUE_ID = "FIXTURE_SPOT"
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"


def _approved_source() -> SourceApproval:
    return SourceApproval(
        source_id=SOURCE_ID,
        license_review_status=LicenseReviewStatus.APPROVED,
        approved_use_status=ApprovedUseStatus.BACKTEST_APPROVED,
        reviewed_at=NOW,
        evidence_uri="fixture://source-license-review/S2-001",
        source_register_version="S0-004-fixture-register-v1",
        retention_allowed=True,
        storage_allowed=True,
        raw_payload_storage_allowed=True,
        event_time_fields_documented=True,
        rate_limit_policy_ref="fixture://source-license-review/S2-001/rate-limits",
    )


def _blocked_source() -> SourceApproval:
    return SourceApproval(
        source_id="coinbase_spot_market_data",
        license_review_status=LicenseReviewStatus.NOT_STARTED,
        approved_use_status=ApprovedUseStatus.BLOCKED_PENDING_REVIEW,
        reviewed_at=None,
        evidence_uri=None,
        source_register_version=None,
        retention_allowed=None,
        storage_allowed=None,
        raw_payload_storage_allowed=None,
        event_time_fields_documented=None,
        rate_limit_policy_ref=None,
    )


def _source_approval(
    *,
    license_review_status: LicenseReviewStatus = LicenseReviewStatus.APPROVED,
    approved_use_status: ApprovedUseStatus = ApprovedUseStatus.BACKTEST_APPROVED,
    reviewed_at: datetime | None = NOW,
    evidence_uri: str | None = "fixture://source-license-review/S2-001",
    source_register_version: str | None = "S0-004-fixture-register-v1",
    retention_allowed: bool | None = True,
    storage_allowed: bool | None = True,
    raw_payload_storage_allowed: bool | None = True,
    event_time_fields_documented: bool | None = True,
    rate_limit_policy_ref: str | None = "fixture://source-license-review/S2-001/rate-limits",
) -> SourceApproval:
    return SourceApproval(
        source_id=SOURCE_ID,
        license_review_status=license_review_status,
        approved_use_status=approved_use_status,
        reviewed_at=reviewed_at,
        evidence_uri=evidence_uri,
        source_register_version=source_register_version,
        retention_allowed=retention_allowed,
        storage_allowed=storage_allowed,
        raw_payload_storage_allowed=raw_payload_storage_allowed,
        event_time_fields_documented=event_time_fields_documented,
        rate_limit_policy_ref=rate_limit_policy_ref,
    )


def _request_with_source_approval(source_approval: SourceApproval) -> HistoricalBackfillRequest:
    return HistoricalBackfillRequest(
        request_id="HISTREQ:SOURCE-APPROVAL-TEST",
        source_id=source_approval.source_id,
        venue_id=VENUE_ID,
        instrument_id=INSTRUMENT_ID,
        data_kind=MarketDataKind.OHLCTV,
        start_ts=START,
        end_ts=END,
        source_approval=source_approval,
        timeframe="1m",
        page_size=100,
        requested_at=NOW,
    )


def _request(data_kind: MarketDataKind = MarketDataKind.OHLCTV) -> HistoricalBackfillRequest:
    return HistoricalBackfillRequest(
        request_id=HistoricalBackfillRequest.build_request_id(
            source_id=SOURCE_ID,
            instrument_id=INSTRUMENT_ID,
            data_kind=data_kind,
            start_ts=START,
            end_ts=END,
            timeframe="1m" if data_kind is MarketDataKind.OHLCTV else None,
        ),
        source_id=SOURCE_ID,
        venue_id=VENUE_ID,
        instrument_id=INSTRUMENT_ID,
        data_kind=data_kind,
        start_ts=START,
        end_ts=END,
        source_approval=_approved_source(),
        timeframe="1m" if data_kind is MarketDataKind.OHLCTV else None,
        page_size=100,
        requested_at=NOW,
    )


def _raw_payload(raw_payload_id: str = "RAW:S2-001:PAGE-1") -> RawPayloadReference:
    return RawPayloadReference(
        raw_payload_id=raw_payload_id,
        source_id=SOURCE_ID,
        content_hash=deterministic_payload_hash(
            {"fixture": "historical", "raw_payload_id": raw_payload_id}
        ),
        uri=f"fixture://historical/{raw_payload_id}",
        content_type="application/json",
        fetched_at=NOW,
        byte_count=256,
    )


def _provenance(raw_payload_id: str = "RAW:S2-001:PAGE-1") -> HistoricalProvenance:
    return HistoricalProvenance(
        source_id=SOURCE_ID,
        connector_name="fixture-historical-connector",
        connector_version="0.0.0-test",
        fetched_at=NOW,
        raw_payload=_raw_payload(raw_payload_id),
    )


def _bar(raw_payload_id: str = "RAW:S2-001:PAGE-1") -> OHLCTVBar:
    return OHLCTVBar(
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
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
        ingest_ts=NOW,
        quality_flags=(),
        raw_payload_id=raw_payload_id,
    )


def _trade(raw_payload_id: str = "RAW:S2-001:TRADES-1") -> TradeRecord:
    return TradeRecord(
        trade_id="fixture-trade-1",
        instrument_id=INSTRUMENT_ID,
        event_ts=START + timedelta(seconds=10),
        price=Decimal("101.00"),
        quantity=Decimal("0.25"),
        side=TradeSide.BUYER,
        sequence=1,
        source_ts=START + timedelta(seconds=10),
        ingest_ts=NOW,
        raw_payload_id=raw_payload_id,
    )


class FixtureHistoricalConnector:
    """Synthetic connector used only to exercise the S2-001 protocol."""

    @property
    def source_id(self) -> str:
        return SOURCE_ID

    def backfill_ohlctv(
        self, request: HistoricalBackfillRequest
    ) -> tuple[HistoricalBackfillPage, ...]:
        raw_payload_id = "RAW:S2-001:PAGE-1"
        page = HistoricalBackfillPage(
            page_id=HistoricalBackfillPage.build_page_id(
                request_id=request.request_id,
                data_kind=MarketDataKind.OHLCTV,
                raw_payload_id=raw_payload_id,
                cursor=request.cursor,
            ),
            request_id=request.request_id,
            data_kind=MarketDataKind.OHLCTV,
            records=(_bar(raw_payload_id),),
            provenance=_provenance(raw_payload_id),
            fetched_at=NOW,
            next_cursor=None,
        )
        return (page,)

    def backfill_trades(
        self, request: HistoricalBackfillRequest
    ) -> tuple[HistoricalBackfillPage, ...]:
        raw_payload_id = "RAW:S2-001:TRADES-1"
        page = HistoricalBackfillPage(
            page_id=HistoricalBackfillPage.build_page_id(
                request_id=request.request_id,
                data_kind=MarketDataKind.TRADE,
                raw_payload_id=raw_payload_id,
                cursor=request.cursor,
            ),
            request_id=request.request_id,
            data_kind=MarketDataKind.TRADE,
            records=(_trade(raw_payload_id),),
            provenance=_provenance(raw_payload_id),
            fetched_at=NOW,
            next_cursor=None,
        )
        return (page,)


@pytest.mark.contract
@pytest.mark.schema
def test_fixture_connector_satisfies_protocol_for_ohlctv_and_trades() -> None:
    connector: HistoricalConnector = FixtureHistoricalConnector()

    bar_pages = connector.backfill_ohlctv(_request(MarketDataKind.OHLCTV))
    trade_pages = connector.backfill_trades(_request(MarketDataKind.TRADE))

    assert bar_pages[0].records[0].raw_payload_id == "RAW:S2-001:PAGE-1"
    assert trade_pages[0].records[0].raw_payload_id == "RAW:S2-001:TRADES-1"
    assert bar_pages[0].provenance.raw_payload.uri.startswith("fixture://")
    assert trade_pages[0].provenance.raw_payload.content_hash == deterministic_payload_hash(
        {"fixture": "historical", "raw_payload_id": "RAW:S2-001:TRADES-1"}
    )


@pytest.mark.contract
@pytest.mark.schema
def test_request_and_page_ids_are_stable_for_retry_idempotency() -> None:
    first_request_id = _request().request_id
    second_request_id = _request().request_id
    first_page_id = HistoricalBackfillPage.build_page_id(
        request_id=first_request_id,
        data_kind=MarketDataKind.OHLCTV,
        raw_payload_id="RAW:S2-001:PAGE-1",
        cursor=None,
    )
    second_page_id = HistoricalBackfillPage.build_page_id(
        request_id=second_request_id,
        data_kind=MarketDataKind.OHLCTV,
        raw_payload_id="RAW:S2-001:PAGE-1",
        cursor=None,
    )

    assert first_request_id == second_request_id
    assert first_page_id == second_page_id


@pytest.mark.contract
@pytest.mark.schema
def test_retry_state_backoff_and_error_hash_are_validated() -> None:
    request = _request()
    error_hash = RetryState.build_error_hash("http_503", "synthetic fixture unavailable")

    retry = RetryState(
        request_id=request.request_id,
        attempt=2,
        max_attempts=3,
        idempotency_key=request.request_id,
        retry_after_seconds=30,
        next_retry_at=NOW + timedelta(seconds=30),
        error_hash=error_hash,
    )

    assert retry.error_hash == error_hash
    with pytest.raises(ValidationError, match="attempt must be <= max_attempts"):
        RetryState(
            request_id=request.request_id,
            attempt=4,
            max_attempts=3,
            idempotency_key=request.request_id,
            retry_after_seconds=30,
            next_retry_at=NOW + timedelta(seconds=30),
            error_hash=error_hash,
        )


@pytest.mark.contract
@pytest.mark.schema
def test_rate_limit_state_requires_consistent_throttle_shape() -> None:
    throttled = RateLimitState(
        source_id=SOURCE_ID,
        limit_id="FIXTURE_REST_MARKET_DATA",
        observed_at=NOW,
        remaining=0,
        limit=100,
        reset_at=NOW + timedelta(minutes=1),
        retry_after_seconds=60,
        state="throttled",
    )

    assert throttled.state == "throttled"
    with pytest.raises(ValidationError, match="throttled state requires"):
        RateLimitState(
            source_id=SOURCE_ID,
            limit_id="FIXTURE_REST_MARKET_DATA",
            observed_at=NOW,
            remaining=0,
            limit=100,
            reset_at=NOW + timedelta(minutes=1),
            retry_after_seconds=0,
            state="throttled",
        )


@pytest.mark.contract
@pytest.mark.schema
def test_blocked_source_approval_fails_closed_for_backfill_request() -> None:
    with pytest.raises(ValidationError, match="source is not approved"):
        HistoricalBackfillRequest(
            request_id="HISTREQ:BLOCKED",
            source_id="coinbase_spot_market_data",
            venue_id="COINBASE_SPOT",
            instrument_id="COINBASE_SPOT:BTC-USD",
            data_kind=MarketDataKind.OHLCTV,
            start_ts=START,
            end_ts=END,
            source_approval=_blocked_source(),
            timeframe="1m",
            page_size=100,
            requested_at=NOW,
        )


@pytest.mark.contract
@pytest.mark.schema
@pytest.mark.parametrize(
    ("license_review_status", "approved_use_status"),
    [
        (LicenseReviewStatus.EXPIRED, ApprovedUseStatus.BACKTEST_APPROVED),
        (LicenseReviewStatus.APPROVED, ApprovedUseStatus.RESEARCH_APPROVED),
        (LicenseReviewStatus.APPROVED, ApprovedUseStatus.EXPLORATION_ONLY),
    ],
)
def test_non_historical_source_register_states_fail_closed(
    license_review_status: LicenseReviewStatus,
    approved_use_status: ApprovedUseStatus,
) -> None:
    with pytest.raises(ValidationError, match="source is not approved"):
        _request_with_source_approval(
            _source_approval(
                license_review_status=license_review_status,
                approved_use_status=approved_use_status,
            )
        )


@pytest.mark.contract
@pytest.mark.schema
def test_backtest_approved_source_register_state_passes() -> None:
    request = _request_with_source_approval(
        _source_approval(
            license_review_status=LicenseReviewStatus.APPROVED_WITH_RESTRICTIONS,
            approved_use_status=ApprovedUseStatus.BACKTEST_APPROVED,
        )
    )

    assert request.source_approval.is_historical_ingestion_approved()


@pytest.mark.contract
@pytest.mark.schema
def test_unknown_source_register_status_fails_validation() -> None:
    payload = _approved_source().model_dump(mode="json")
    payload["approved_use_status"] = "approved_for_ingestion"

    with pytest.raises(ValidationError, match="approved_for_ingestion"):
        SourceApproval.model_validate(payload)


@pytest.mark.contract
@pytest.mark.schema
def test_approved_source_missing_evidence_or_storage_permission_fails_closed() -> None:
    with pytest.raises(ValidationError, match="source is not approved"):
        _request_with_source_approval(_source_approval(evidence_uri=None))

    with pytest.raises(ValidationError, match="source is not approved"):
        _request_with_source_approval(_source_approval(retention_allowed=False))

    with pytest.raises(ValidationError, match="source is not approved"):
        _request_with_source_approval(_source_approval(storage_allowed=False))


@pytest.mark.contract
@pytest.mark.schema
def test_page_lineage_requires_record_raw_payload_to_match_provenance() -> None:
    request = _request()

    with pytest.raises(ValidationError, match="record raw_payload_id must match"):
        HistoricalBackfillPage(
            page_id="HISTPAGE:BAD-LINEAGE",
            request_id=request.request_id,
            data_kind=MarketDataKind.OHLCTV,
            records=(_bar("RAW:S2-001:DIFFERENT"),),
            provenance=_provenance("RAW:S2-001:PAGE-1"),
            fetched_at=NOW,
            next_cursor=None,
        )


@pytest.mark.contract
@pytest.mark.schema
def test_ohlctv_and_trade_invariants_reject_invalid_records() -> None:
    with pytest.raises(ValidationError, match="high must be"):
        OHLCTVBar(
            instrument_id=INSTRUMENT_ID,
            venue_id=VENUE_ID,
            timeframe="1m",
            open_ts=START,
            close_ts=END,
            open=Decimal("100.00"),
            high=Decimal("99.00"),
            low=Decimal("95.00"),
            close=Decimal("105.00"),
            base_volume=Decimal("2.50"),
            quote_volume=None,
            trade_count=10,
            vwap=None,
            source_ts=END,
            ingest_ts=NOW,
            quality_flags=(QualityFlag.OUTLIER,),
            raw_payload_id="RAW:S2-001:BAD-BAR",
        )

    with pytest.raises(ValidationError):
        TradeRecord(
            trade_id="fixture-trade-bad",
            instrument_id=INSTRUMENT_ID,
            event_ts=START,
            price=Decimal("0"),
            quantity=Decimal("0.25"),
            side=None,
            sequence=None,
            source_ts=None,
            ingest_ts=NOW,
            raw_payload_id="RAW:S2-001:BAD-TRADE",
        )


@pytest.mark.contract
@pytest.mark.schema
def test_unknown_fields_fail_validation() -> None:
    payload = _bar().model_dump(mode="json")
    payload["unexpected_provider_field"] = "must fail closed"

    with pytest.raises(ValidationError, match="unexpected_provider_field"):
        OHLCTVBar.model_validate(payload)
