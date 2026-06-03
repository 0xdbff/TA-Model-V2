"""Streaming ingestion connector contracts.

Traceability:
- FR-002: ingest real-time trades, quotes, and order-book data where available.
- NFR-003: recover ingestion from disconnects with reconnect/backoff evidence.

Scope:
- S3-001 defines project-owned streaming contracts, lifecycle states, heartbeat
  and retry helpers, and source-approval fail-closed checks.
- No live WebSocket/API/network stream, broker service, persistent market-data
  storage, freshness/gap/duplicate metric implementation, strategy fail-closed
  signal, paper routing, live capital, leverage, margin, derivatives, or shorting
  path is introduced here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import AwareDatetime, Field, PositiveInt, model_validator

from ta_model.contracts.instrument_master import (
    CanonicalId,
    ContractModel,
    NonEmptyString,
    NonNegativeDecimal,
    PositiveDecimal,
)
from ta_model.contracts.market_data import (
    ApprovedUseStatus,
    LicenseReviewStatus,
    SourceId,
    TradeSide,
)

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveTimedelta = Annotated[timedelta, Field(gt=timedelta(0))]


class ProductionUseStatus(StrEnum):
    """Normalized `production_use_status` states from the source register."""

    NOT_APPROVED_FOR_PRODUCTION = "not_approved_for_production"
    PAPER_ONLY = "paper_only"
    APPROVED_WITH_RESTRICTIONS = "approved_with_restrictions"
    PRODUCTION_APPROVED = "production_approved"
    BLOCKED = "blocked"


class StreamChannel(StrEnum):
    """Market-data stream channels covered by the S3-001 contract."""

    TRADES = "trades"
    QUOTES = "quotes"
    ORDER_BOOK = "order_book"


class StreamEventType(StrEnum):
    """Envelope event families emitted by streaming connectors."""

    TRADE = "trade"
    QUOTE = "quote"
    ORDER_BOOK = "order_book"
    HEARTBEAT = "heartbeat"
    LIFECYCLE = "lifecycle"


class ConnectorStatus(StrEnum):
    """Connector lifecycle states for health and downstream fail-closed users."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    SOURCE_BLOCKED = "source_blocked"
    FAILED = "failed"
    CLOSED = "closed"


class HeartbeatStatus(StrEnum):
    """Heartbeat observation states."""

    OBSERVED = "observed"
    MISSED = "missed"


class DisconnectReason(StrEnum):
    """Machine-readable disconnect/reconnect reasons."""

    HEARTBEAT_MISSED = "heartbeat_missed"
    SOURCE_BLOCKED = "source_blocked"
    TRANSPORT_CLOSED = "transport_closed"
    RETRY_EXHAUSTED = "retry_exhausted"
    OPERATOR_REQUEST = "operator_request"
    FIXTURE_COMPLETE = "fixture_complete"


class StreamQualityFlag(StrEnum):
    """Schema-level flags reserved for future quality metric consumers."""

    GAP = "gap"
    STALE = "stale"
    DUPLICATE = "duplicate"
    CROSSED = "crossed"
    REPAIRED = "repaired"
    LATE = "late"
    ESTIMATED = "estimated"


class StreamingSourceApproval(ContractModel):
    """Source-register review snapshot consumed before connector startup.

    Non-synthetic streaming is intentionally stricter than research/backtest use:
    license review must be approved or approved with restrictions, approved use
    must be paper-approved or stricter, and review evidence must be present.
    Fixture/test approval is separate from source-register states and only permits
    `subscription.synthetic_only=True`.
    """

    source_id: SourceId
    license_review_status: LicenseReviewStatus
    approved_use_status: ApprovedUseStatus
    production_use_status: ProductionUseStatus
    fixture_only: bool = False
    evidence_link: NonEmptyString | None = None
    approved_by: NonEmptyString | None = None
    decision_notes: NonEmptyString | None = None
    checked_at: AwareDatetime

    def permits_subscription(self, subscription: StreamSubscription) -> bool:
        """Return whether this source may stream for the requested subscription."""

        if self.source_id != subscription.source_id:
            return False
        if subscription.synthetic_only:
            return self.fixture_only
        return (
            not self.fixture_only
            and self.license_review_status
            in {
                LicenseReviewStatus.APPROVED,
                LicenseReviewStatus.APPROVED_WITH_RESTRICTIONS,
            }
            and self.approved_use_status is ApprovedUseStatus.PAPER_APPROVED
            and self.production_use_status
            in {
                ProductionUseStatus.PAPER_ONLY,
                ProductionUseStatus.APPROVED_WITH_RESTRICTIONS,
                ProductionUseStatus.PRODUCTION_APPROVED,
            }
            and self.evidence_link is not None
            and self.approved_by is not None
        )


class StreamSubscription(ContractModel):
    """Canonical market-data subscription request."""

    subscription_id: CanonicalId
    source_id: SourceId
    venue_id: CanonicalId
    instrument_ids: tuple[CanonicalId, ...]
    channels: tuple[StreamChannel, ...]
    requested_at: AwareDatetime
    synthetic_only: bool = Field(
        default=True,
        description=(
            "True for fixture streams; false requires an approved source and future connector."
        ),
    )

    @model_validator(mode="after")
    def require_non_empty_targets(self) -> StreamSubscription:
        if not self.instrument_ids:
            raise ValueError("at least one instrument_id is required")
        if not self.channels:
            raise ValueError("at least one stream channel is required")
        return self


class StreamEnvelopeBase(ContractModel):
    """Shared source, event-time, and ingestion-time fields for stream events."""

    event_type: StreamEventType
    subscription_id: CanonicalId
    source_id: SourceId
    venue_id: CanonicalId
    event_ts: AwareDatetime = Field(description="Event/source availability time in UTC.")
    source_ts: AwareDatetime | None = Field(
        default=None,
        description="Source-published timestamp when different from event_ts.",
    )
    ingest_ts: AwareDatetime = Field(description="System receive/ingestion timestamp.")
    raw_payload_id: NonEmptyString


class TradeEvent(StreamEnvelopeBase):
    """Trade event schema aligned to docs/07_data_contracts.md."""

    event_type: Literal[StreamEventType.TRADE] = StreamEventType.TRADE
    trade_id: NonEmptyString
    instrument_id: CanonicalId
    price: PositiveDecimal
    quantity: PositiveDecimal
    side: TradeSide | None = None
    sequence: NonNegativeInt | None = None


class QuoteEvent(StreamEnvelopeBase):
    """Best bid/ask quote event schema."""

    event_type: Literal[StreamEventType.QUOTE] = StreamEventType.QUOTE
    quote_id: NonEmptyString
    instrument_id: CanonicalId
    best_bid: NonNegativeDecimal
    best_ask: NonNegativeDecimal
    sequence: NonNegativeInt | None = None
    quality_flags: tuple[StreamQualityFlag, ...] = ()

    @model_validator(mode="after")
    def reject_crossed_quote_without_flag(self) -> QuoteEvent:
        if self.best_bid > self.best_ask and StreamQualityFlag.CROSSED not in self.quality_flags:
            raise ValueError("crossed quote requires crossed quality flag")
        return self


class BookLevel(ContractModel):
    """Single order-book price level."""

    price: PositiveDecimal
    quantity: NonNegativeDecimal


class OrderBookEvent(StreamEnvelopeBase):
    """Order-book snapshot/delta event schema."""

    event_type: Literal[StreamEventType.ORDER_BOOK] = StreamEventType.ORDER_BOOK
    book_event_id: NonEmptyString
    instrument_id: CanonicalId
    sequence: NonNegativeInt | None = None
    is_snapshot: bool
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    best_bid: NonNegativeDecimal | None = None
    best_ask: NonNegativeDecimal | None = None
    quality_flags: tuple[StreamQualityFlag, ...] = ()

    @model_validator(mode="after")
    def validate_best_prices(self) -> OrderBookEvent:
        if self.best_bid is not None and self.best_ask is not None:
            if (
                self.best_bid > self.best_ask
                and StreamQualityFlag.CROSSED not in self.quality_flags
            ):
                raise ValueError("crossed book requires crossed quality flag")
        return self


class HeartbeatEvent(StreamEnvelopeBase):
    """Connector heartbeat event."""

    event_type: Literal[StreamEventType.HEARTBEAT] = StreamEventType.HEARTBEAT
    status: HeartbeatStatus
    last_observed_ts: AwareDatetime | None = None
    timeout: PositiveTimedelta


class LifecycleEvent(StreamEnvelopeBase):
    """Connector lifecycle transition event."""

    event_type: Literal[StreamEventType.LIFECYCLE] = StreamEventType.LIFECYCLE
    status: ConnectorStatus
    reason: DisconnectReason | None = None
    attempt: NonNegativeInt = 0


StreamEvent = TradeEvent | QuoteEvent | OrderBookEvent | HeartbeatEvent | LifecycleEvent


class RetryBackoffPolicy(ContractModel):
    """Deterministic exponential retry/backoff policy."""

    initial_delay: PositiveTimedelta = timedelta(seconds=1)
    max_delay: PositiveTimedelta = timedelta(seconds=30)
    multiplier: Annotated[Decimal, Field(ge=Decimal("1"), le=Decimal("10"))] = Decimal("2")
    max_attempts: PositiveInt = 5

    @model_validator(mode="after")
    def require_ordered_delays(self) -> RetryBackoffPolicy:
        if self.initial_delay > self.max_delay:
            raise ValueError("initial_delay must be <= max_delay")
        return self

    def delay_for_attempt(self, attempt: int) -> timedelta:
        """Return capped delay for a 1-based retry attempt."""

        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        factor = self.multiplier ** Decimal(attempt - 1)
        delay = self.initial_delay.total_seconds() * float(factor)
        capped = min(delay, self.max_delay.total_seconds())
        return timedelta(seconds=capped)


class HeartbeatPolicy(ContractModel):
    """Heartbeat timeout policy used by connectors and health checks."""

    interval: PositiveTimedelta = timedelta(seconds=15)
    timeout: PositiveTimedelta = timedelta(seconds=45)

    @model_validator(mode="after")
    def require_timeout_at_least_interval(self) -> HeartbeatPolicy:
        if self.timeout < self.interval:
            raise ValueError("timeout must be >= interval")
        return self

    def status_at(self, *, now: datetime, last_observed_ts: datetime | None) -> HeartbeatStatus:
        """Classify heartbeat state without mutating connector state."""

        if last_observed_ts is None:
            return HeartbeatStatus.MISSED
        if now - last_observed_ts > self.timeout:
            return HeartbeatStatus.MISSED
        return HeartbeatStatus.OBSERVED


class SourceNotApprovedError(RuntimeError):
    """Raised when source review status requires connector startup to fail closed."""


class StreamingConnector(Protocol):
    """Project-owned connector interface; implementations stay behind this boundary."""

    subscription: StreamSubscription
    status: ConnectorStatus

    async def connect(self) -> LifecycleEvent: ...

    async def disconnect(self, reason: DisconnectReason) -> LifecycleEvent: ...
    async def reconnect(self, reason: DisconnectReason) -> LifecycleEvent: ...
    def events(self) -> AsyncIterator[StreamEvent]: ...
