"""Historical market-data contracts for OHLCTV bars and trades.

Traceability:
- FR-001: historical OHLCTV backfill contract validates schema and lineage.
- FR-003: records use canonical instrument and venue identifiers.
- NFR-005: deterministic request/page identifiers and raw payload references support replay.

Scope:
- S2-001 defines connector-facing contracts only.
- No real exchange/API/network ingestion, storage, normalization, gap reporting, streaming,
  paper trading, live capital, leverage, margin, shorting, or derivatives are introduced.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, Field, PositiveInt, StringConstraints, model_validator

from ta_model.contracts.instrument_master import (
    CanonicalId,
    ContractModel,
    NonEmptyString,
    NonNegativeDecimal,
    PositiveDecimal,
)

HashHex = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Cursor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
SourceId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
Timeframe = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=8,
        pattern=r"^[1-9][0-9]*(m|h|d)$",
    ),
]


class MarketDataKind(StrEnum):
    """Historical market-data record families supported by S2-001."""

    OHLCTV = "ohlctv"
    TRADE = "trade"


class TradeSide(StrEnum):
    """Optional aggressor side for trade records where the source provides it."""

    BUYER = "buyer"
    SELLER = "seller"


class QualityFlag(StrEnum):
    """Quality flags from docs/07_data_contracts.md."""

    MISSING = "missing"
    LATE = "late"
    ESTIMATED = "estimated"
    DUPLICATE = "duplicate"
    OUTLIER = "outlier"
    REPAIRED = "repaired"


class LicenseReviewStatus(StrEnum):
    """Source-license review states from docs/source_license_register.csv."""

    NOT_STARTED = "not_started"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    APPROVED_WITH_RESTRICTIONS = "approved_with_restrictions"
    BLOCKED = "blocked"
    EXPIRED = "expired"


class ApprovedUseStatus(StrEnum):
    """Approved-use states from docs/source_license_register.csv."""

    BLOCKED_PENDING_REVIEW = "blocked_pending_review"
    EXPLORATION_ONLY = "exploration_only"
    RESEARCH_APPROVED = "research_approved"
    BACKTEST_APPROVED = "backtest_approved"
    PAPER_APPROVED = "paper_approved"
    BLOCKED = "blocked"


class SourceApproval(ContractModel):
    """Fail-closed source approval snapshot for a backfill request."""

    source_id: SourceId
    license_review_status: LicenseReviewStatus
    approved_use_status: ApprovedUseStatus
    reviewed_at: AwareDatetime | None = None
    evidence_uri: NonEmptyString | None = None
    source_register_version: NonEmptyString | None = Field(
        default=None,
        description="Source-register evidence/version reference from the S0-004 workflow.",
    )
    retention_allowed: bool | None = None
    storage_allowed: bool | None = None
    raw_payload_storage_allowed: bool | None = None
    event_time_fields_documented: bool | None = None
    rate_limit_policy_ref: NonEmptyString | None = None

    def is_historical_ingestion_approved(self) -> bool:
        """Return True only for source-register-approved historical ingestion."""

        return (
            self.license_review_status
            in {
                LicenseReviewStatus.APPROVED,
                LicenseReviewStatus.APPROVED_WITH_RESTRICTIONS,
            }
            and self.approved_use_status
            in {
                ApprovedUseStatus.BACKTEST_APPROVED,
                ApprovedUseStatus.PAPER_APPROVED,
            }
            and self.reviewed_at is not None
            and self.evidence_uri is not None
            and self.source_register_version is not None
            and self.retention_allowed is True
            and self.storage_allowed is True
            and self.raw_payload_storage_allowed is True
            and self.event_time_fields_documented is True
            and self.rate_limit_policy_ref is not None
        )


class RawPayloadReference(ContractModel):
    """Reference to an immutable raw payload stored by a future bronze layer."""

    raw_payload_id: CanonicalId
    source_id: SourceId
    content_hash: HashHex
    uri: NonEmptyString = Field(
        description="Immutable object reference; S2-001 fixtures use non-network fixture:// URIs."
    )
    content_type: NonEmptyString
    fetched_at: AwareDatetime
    byte_count: PositiveInt


class HistoricalProvenance(ContractModel):
    """Connector provenance attached to historical pages and records."""

    source_id: SourceId
    connector_name: NonEmptyString
    connector_version: NonEmptyString
    fetched_at: AwareDatetime
    raw_payload: RawPayloadReference

    @model_validator(mode="after")
    def raw_payload_source_matches(self) -> Self:
        if self.raw_payload.source_id != self.source_id:
            raise ValueError("raw_payload.source_id must match provenance source_id")
        return self


class HistoricalBackfillRequest(ContractModel):
    """Canonical historical backfill request shared by future connectors."""

    request_id: CanonicalId
    source_id: SourceId
    venue_id: CanonicalId
    instrument_id: CanonicalId
    data_kind: MarketDataKind
    start_ts: AwareDatetime
    end_ts: AwareDatetime
    source_approval: SourceApproval
    timeframe: Timeframe | None = None
    page_size: PositiveInt = Field(le=10_000)
    requested_at: AwareDatetime
    cursor: Cursor | None = None

    @model_validator(mode="after")
    def request_is_event_time_valid_and_source_approved(self) -> Self:
        if self.end_ts <= self.start_ts:
            raise ValueError("end_ts must be after start_ts")
        if self.source_approval.source_id != self.source_id:
            raise ValueError("source_approval.source_id must match request source_id")
        if not self.source_approval.is_historical_ingestion_approved():
            raise ValueError("source is not approved for historical ingestion")
        if self.data_kind is MarketDataKind.OHLCTV and self.timeframe is None:
            raise ValueError("timeframe is required for OHLCTV backfill")
        if self.data_kind is MarketDataKind.TRADE and self.timeframe is not None:
            raise ValueError("timeframe must be omitted for trade backfill")
        return self

    @classmethod
    def build_request_id(
        cls,
        *,
        source_id: str,
        instrument_id: str,
        data_kind: MarketDataKind,
        start_ts: datetime,
        end_ts: datetime,
        timeframe: str | None,
    ) -> str:
        """Build a stable request ID from event-time inputs, not ingest time."""

        payload = {
            "data_kind": data_kind.value,
            "end_ts": end_ts.isoformat(),
            "instrument_id": instrument_id,
            "source_id": source_id,
            "start_ts": start_ts.isoformat(),
            "timeframe": timeframe,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:32]
        return f"HISTREQ:{digest.upper()}"


class OHLCTVBar(ContractModel):
    """Canonical OHLCTV bar schema from docs/07_data_contracts.md."""

    instrument_id: CanonicalId
    venue_id: CanonicalId
    timeframe: Timeframe
    open_ts: AwareDatetime
    close_ts: AwareDatetime
    open: NonNegativeDecimal
    high: NonNegativeDecimal
    low: NonNegativeDecimal
    close: NonNegativeDecimal
    base_volume: NonNegativeDecimal
    quote_volume: NonNegativeDecimal | None = None
    trade_count: int | None = Field(default=None, ge=0)
    vwap: NonNegativeDecimal | None = None
    source_ts: AwareDatetime
    ingest_ts: AwareDatetime
    quality_flags: tuple[QualityFlag, ...]
    raw_payload_id: CanonicalId

    @model_validator(mode="after")
    def ohlc_invariants_hold(self) -> Self:
        if self.close_ts <= self.open_ts:
            raise ValueError("close_ts must be after open_ts")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must be >= open, low, and close")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must be <= open, high, and close")
        if self.vwap is not None and not self.low <= self.vwap <= self.high:
            raise ValueError("vwap must be between low and high")
        return self


class TradeRecord(ContractModel):
    """Canonical trade schema from docs/07_data_contracts.md."""

    trade_id: NonEmptyString
    instrument_id: CanonicalId
    event_ts: AwareDatetime
    price: PositiveDecimal
    quantity: PositiveDecimal
    side: TradeSide | None = None
    sequence: int | None = Field(default=None, ge=0)
    source_ts: AwareDatetime | None = None
    ingest_ts: AwareDatetime
    raw_payload_id: CanonicalId


class HistoricalBackfillPage(ContractModel):
    """A connector page of validated historical records plus provenance."""

    page_id: CanonicalId
    request_id: CanonicalId
    data_kind: MarketDataKind
    records: tuple[OHLCTVBar | TradeRecord, ...]
    provenance: HistoricalProvenance
    fetched_at: AwareDatetime
    next_cursor: Cursor | None = None

    @model_validator(mode="after")
    def records_match_data_kind(self) -> Self:
        expected_type: type[OHLCTVBar] | type[TradeRecord]
        expected_type = OHLCTVBar if self.data_kind is MarketDataKind.OHLCTV else TradeRecord
        if not all(isinstance(record, expected_type) for record in self.records):
            raise ValueError("records must match page data_kind")
        raw_payload_id = self.provenance.raw_payload.raw_payload_id
        if not all(record.raw_payload_id == raw_payload_id for record in self.records):
            raise ValueError("record raw_payload_id must match page provenance raw_payload_id")
        return self

    @classmethod
    def build_page_id(
        cls,
        *,
        request_id: str,
        data_kind: MarketDataKind,
        raw_payload_id: str,
        cursor: str | None,
    ) -> str:
        """Build a stable page ID for idempotent retry/replay checks."""

        payload = {
            "cursor": cursor,
            "data_kind": data_kind.value,
            "raw_payload_id": raw_payload_id,
            "request_id": request_id,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:32]
        return f"HISTPAGE:{digest.upper()}"


class RetryState(ContractModel):
    """Retry/backoff state for historical connector calls."""

    request_id: CanonicalId
    attempt: PositiveInt
    max_attempts: PositiveInt
    idempotency_key: CanonicalId
    retry_after_seconds: PositiveInt
    next_retry_at: AwareDatetime
    error_hash: HashHex

    @model_validator(mode="after")
    def attempt_must_not_exceed_max(self) -> Self:
        if self.attempt > self.max_attempts:
            raise ValueError("attempt must be <= max_attempts")
        return self

    @classmethod
    def build_error_hash(cls, error_family: str, message: str) -> str:
        """Build deterministic hash without retaining provider payloads or secrets."""

        payload = {"error_family": error_family, "message": message}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


class RateLimitState(ContractModel):
    """Rate-limit observation contract for future connector schedulers."""

    source_id: SourceId
    limit_id: CanonicalId
    observed_at: AwareDatetime
    remaining: int = Field(ge=0)
    limit: PositiveInt
    reset_at: AwareDatetime
    retry_after_seconds: int = Field(ge=0)
    state: Literal["available", "throttled"]

    @model_validator(mode="after")
    def rate_limit_state_is_consistent(self) -> Self:
        if self.remaining > self.limit:
            raise ValueError("remaining must be <= limit")
        if self.state == "throttled" and self.retry_after_seconds <= 0:
            raise ValueError("throttled state requires positive retry_after_seconds")
        return self


HistoricalRecord = OHLCTVBar | TradeRecord


def deterministic_payload_hash(payload: dict[str, Any]) -> str:
    """Hash fixture/raw payload metadata with a stable JSON representation."""

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
