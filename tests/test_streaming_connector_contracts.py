"""Contract evidence for S3-001 streaming ingestion connector interface."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from pydantic import ValidationError

from ta_model.contracts.streaming import (
    ApprovedUseStatus,
    BookLevel,
    ConnectorStatus,
    DisconnectReason,
    HeartbeatEvent,
    HeartbeatPolicy,
    HeartbeatStatus,
    LicenseReviewStatus,
    LifecycleEvent,
    OrderBookEvent,
    ProductionUseStatus,
    QuoteEvent,
    RetryBackoffPolicy,
    SourceApproval,
    SourceNotApprovedError,
    StreamChannel,
    StreamEvent,
    StreamQualityFlag,
    StreamSubscription,
    TradeEvent,
    TradeSide,
)

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


class SyntheticStreamingConnector:
    """Test-local in-memory fixture connector; performs no network I/O."""

    def __init__(
        self,
        *,
        subscription: StreamSubscription,
        source_approval: SourceApproval,
        events: Sequence[StreamEvent],
        heartbeat_policy: HeartbeatPolicy | None = None,
        retry_policy: RetryBackoffPolicy | None = None,
    ) -> None:
        self.subscription = subscription
        self.source_approval = source_approval
        self._events = tuple(events)
        self.heartbeat_policy = heartbeat_policy or HeartbeatPolicy()
        self.retry_policy = retry_policy or RetryBackoffPolicy()
        self.status = ConnectorStatus.DISCONNECTED
        self.reconnect_attempts = 0
        self.last_observed_heartbeat_ts: datetime | None = None

    async def connect(self) -> LifecycleEvent:
        self.status = ConnectorStatus.CONNECTING
        if not self.source_approval.permits_subscription(self.subscription):
            self.status = ConnectorStatus.SOURCE_BLOCKED
            event = self._lifecycle_event(
                ConnectorStatus.SOURCE_BLOCKED,
                DisconnectReason.SOURCE_BLOCKED,
            )
            raise SourceNotApprovedError(event.model_dump_json())
        self.status = ConnectorStatus.CONNECTED
        return self._lifecycle_event(ConnectorStatus.CONNECTED, None)

    async def disconnect(self, reason: DisconnectReason) -> LifecycleEvent:
        self.status = ConnectorStatus.DISCONNECTED
        return self._lifecycle_event(ConnectorStatus.DISCONNECTED, reason)

    async def reconnect(self, reason: DisconnectReason) -> LifecycleEvent:
        self.reconnect_attempts += 1
        self.status = ConnectorStatus.RECONNECTING
        if self.reconnect_attempts > self.retry_policy.max_attempts:
            self.status = ConnectorStatus.FAILED
            return self._lifecycle_event(ConnectorStatus.FAILED, DisconnectReason.RETRY_EXHAUSTED)
        self.status = ConnectorStatus.CONNECTED
        return self._lifecycle_event(ConnectorStatus.CONNECTED, reason)

    async def _event_iterator(self) -> AsyncIterator[StreamEvent]:
        if self.status != ConnectorStatus.CONNECTED:
            self.status = ConnectorStatus.SOURCE_BLOCKED
            raise SourceNotApprovedError("connector must connect before events are emitted")
        for event in self._events:
            if isinstance(event, HeartbeatEvent) and event.status is HeartbeatStatus.OBSERVED:
                self.last_observed_heartbeat_ts = event.event_ts
            yield event
        self.status = ConnectorStatus.CLOSED

    def events(self) -> AsyncIterator[StreamEvent]:
        return self._event_iterator()

    def heartbeat_status_at(self, now: datetime) -> HeartbeatStatus:
        return self.heartbeat_policy.status_at(
            now=now,
            last_observed_ts=self.last_observed_heartbeat_ts,
        )

    def _lifecycle_event(
        self,
        status: ConnectorStatus,
        reason: DisconnectReason | None,
    ) -> LifecycleEvent:
        now = self.subscription.requested_at
        return LifecycleEvent(
            subscription_id=self.subscription.subscription_id,
            source_id=self.subscription.source_id,
            venue_id=self.subscription.venue_id,
            event_ts=now,
            ingest_ts=now,
            raw_payload_id=f"fixture:{self.subscription.subscription_id}:{status.value}",
            status=status,
            reason=reason,
            attempt=self.reconnect_attempts,
        )


def _subscription() -> StreamSubscription:
    return StreamSubscription(
        subscription_id="SUB:S3-001:FIXTURE",
        source_id="synthetic_fixture_source",
        venue_id="SIMULATOR",
        instrument_ids=("BTC-USD",),
        channels=(StreamChannel.TRADES, StreamChannel.QUOTES, StreamChannel.ORDER_BOOK),
        requested_at=NOW,
    )


def _subscription_for(source_id: str, *, synthetic_only: bool) -> StreamSubscription:
    return StreamSubscription(
        subscription_id="SUB:S3-001:SOURCE",
        source_id=source_id,
        venue_id="COINBASE",
        instrument_ids=("BTC-USD",),
        channels=(StreamChannel.TRADES,),
        requested_at=NOW,
        synthetic_only=synthetic_only,
    )


def _approval(
    approved_use_status: ApprovedUseStatus = ApprovedUseStatus.BLOCKED_PENDING_REVIEW,
    *,
    source_id: str = "synthetic_fixture_source",
    license_review_status: LicenseReviewStatus = LicenseReviewStatus.NOT_STARTED,
    production_use_status: ProductionUseStatus = ProductionUseStatus.NOT_APPROVED_FOR_PRODUCTION,
    fixture_only: bool = True,
    evidence_link: str | None = None,
    approved_by: str | None = None,
) -> SourceApproval:
    return SourceApproval(
        source_id=source_id,
        license_review_status=license_review_status,
        approved_use_status=approved_use_status,
        production_use_status=production_use_status,
        fixture_only=fixture_only,
        evidence_link=evidence_link,
        approved_by=approved_by,
        decision_notes="fixture stream only; no external source",
        checked_at=NOW,
    )


def test_stream_event_contracts_reject_unknown_fields_and_crossed_quotes() -> None:
    trade = TradeEvent(
        subscription_id="SUB:S3-001:FIXTURE",
        source_id="synthetic_fixture_source",
        venue_id="SIMULATOR",
        event_ts=NOW,
        source_ts=NOW - timedelta(milliseconds=1),
        ingest_ts=NOW + timedelta(milliseconds=2),
        raw_payload_id="raw:trade:1",
        trade_id="trade-1",
        instrument_id="BTC-USD",
        price=Decimal("50000.01"),
        quantity=Decimal("0.10"),
        side=TradeSide.BUYER,
        sequence=1,
    )

    assert trade.event_ts != cast("datetime", trade.source_ts)
    assert trade.ingest_ts > trade.event_ts

    with pytest.raises(ValidationError):
        TradeEvent.model_validate({**trade.model_dump(), "exchange_object": {"raw": "blocked"}})

    with pytest.raises(ValidationError, match="crossed quote requires crossed quality flag"):
        QuoteEvent(
            subscription_id="SUB:S3-001:FIXTURE",
            source_id="synthetic_fixture_source",
            venue_id="SIMULATOR",
            event_ts=NOW,
            ingest_ts=NOW,
            raw_payload_id="raw:quote:crossed",
            quote_id="quote-crossed",
            instrument_id="BTC-USD",
            best_bid=Decimal("101"),
            best_ask=Decimal("100"),
        )


def test_heartbeat_policy_reports_observed_and_missed_states() -> None:
    policy = HeartbeatPolicy(interval=timedelta(seconds=10), timeout=timedelta(seconds=30))

    assert policy.status_at(now=NOW, last_observed_ts=NOW - timedelta(seconds=29)) == (
        HeartbeatStatus.OBSERVED
    )
    assert policy.status_at(now=NOW, last_observed_ts=NOW - timedelta(seconds=31)) == (
        HeartbeatStatus.MISSED
    )
    assert policy.status_at(now=NOW, last_observed_ts=None) == HeartbeatStatus.MISSED


def test_retry_backoff_policy_is_capped_and_attempt_limited() -> None:
    policy = RetryBackoffPolicy(
        initial_delay=timedelta(seconds=1),
        max_delay=timedelta(seconds=5),
        multiplier=Decimal("2"),
        max_attempts=2,
    )

    assert policy.delay_for_attempt(1) == timedelta(seconds=1)
    assert policy.delay_for_attempt(3) == timedelta(seconds=4)
    assert policy.delay_for_attempt(9) == timedelta(seconds=5)

    with pytest.raises(ValueError, match="attempt must be >= 1"):
        policy.delay_for_attempt(0)


def test_source_approval_fail_closed_blocks_unapproved_streams() -> None:
    async def scenario() -> None:
        connector = SyntheticStreamingConnector(
            subscription=_subscription_for("coinbase_spot_market_data", synthetic_only=False),
            source_approval=_approval(
                ApprovedUseStatus.BLOCKED_PENDING_REVIEW,
                source_id="coinbase_spot_market_data",
                license_review_status=LicenseReviewStatus.NOT_STARTED,
            ),
            events=(),
        )

        with pytest.raises(SourceNotApprovedError) as error:
            await connector.connect()

        assert connector.status == ConnectorStatus.SOURCE_BLOCKED
        assert "source_blocked" in str(error.value)

    asyncio.run(scenario())


def test_source_register_ids_allow_lowercase_real_source_ids() -> None:
    approval = _approval(
        ApprovedUseStatus.PAPER_APPROVED,
        source_id="coinbase_spot_market_data",
        license_review_status=LicenseReviewStatus.APPROVED_WITH_RESTRICTIONS,
        production_use_status=ProductionUseStatus.PAPER_ONLY,
        fixture_only=False,
        evidence_link="Issue #5 legal review",
        approved_by="legal-owner",
    )
    subscription = _subscription_for("coinbase_spot_market_data", synthetic_only=False)

    assert approval.permits_subscription(subscription)

    template_subscription = _subscription_for("TEMPLATE_NEW_SOURCE", synthetic_only=False)
    assert template_subscription.source_id == "TEMPLATE_NEW_SOURCE"


def test_backtest_or_research_approval_is_not_enough_for_non_synthetic_stream() -> None:
    subscription = _subscription_for("coinbase_spot_market_data", synthetic_only=False)
    backtest_approval = _approval(
        ApprovedUseStatus.BACKTEST_APPROVED,
        source_id="coinbase_spot_market_data",
        license_review_status=LicenseReviewStatus.APPROVED,
        production_use_status=ProductionUseStatus.PAPER_ONLY,
        fixture_only=False,
        evidence_link="Issue #5 legal review",
        approved_by="legal-owner",
    )
    missing_evidence_approval = _approval(
        ApprovedUseStatus.PAPER_APPROVED,
        source_id="coinbase_spot_market_data",
        license_review_status=LicenseReviewStatus.APPROVED,
        production_use_status=ProductionUseStatus.PAPER_ONLY,
        fixture_only=False,
    )

    assert not backtest_approval.permits_subscription(subscription)
    assert not missing_evidence_approval.permits_subscription(subscription)

    research_approval = _approval(
        ApprovedUseStatus.RESEARCH_APPROVED,
        source_id="coinbase_spot_market_data",
        license_review_status=LicenseReviewStatus.APPROVED,
        production_use_status=ProductionUseStatus.PAPER_ONLY,
        fixture_only=False,
        evidence_link="Issue #5 legal review",
        approved_by="legal-owner",
    )
    blocked_approval = _approval(
        ApprovedUseStatus.PAPER_APPROVED,
        source_id="coinbase_spot_market_data",
        license_review_status=LicenseReviewStatus.BLOCKED,
        production_use_status=ProductionUseStatus.PAPER_ONLY,
        fixture_only=False,
        evidence_link="Issue #5 legal review",
        approved_by="legal-owner",
    )
    expired_approval = _approval(
        ApprovedUseStatus.PAPER_APPROVED,
        source_id="coinbase_spot_market_data",
        license_review_status=LicenseReviewStatus.EXPIRED,
        production_use_status=ProductionUseStatus.PAPER_ONLY,
        fixture_only=False,
        evidence_link="Issue #5 legal review",
        approved_by="legal-owner",
    )

    assert not research_approval.permits_subscription(subscription)
    assert not blocked_approval.permits_subscription(subscription)
    assert not expired_approval.permits_subscription(subscription)


def test_invented_fixture_status_fails_validation() -> None:
    payload = _approval().model_dump(mode="json")
    payload["approved_use_status"] = "fixture_only_test"

    with pytest.raises(ValidationError):
        SourceApproval.model_validate(payload)


def test_source_id_mismatch_fails_real_stream_approval() -> None:
    approval = _approval(
        ApprovedUseStatus.PAPER_APPROVED,
        source_id="coinbase_spot_market_data",
        license_review_status=LicenseReviewStatus.APPROVED,
        production_use_status=ProductionUseStatus.PAPER_ONLY,
        fixture_only=False,
        evidence_link="Issue #5 legal review",
        approved_by="legal-owner",
    )
    subscription = _subscription_for("kraken_spot_market_data", synthetic_only=False)

    assert not approval.permits_subscription(subscription)


def test_fixture_only_approval_allows_synthetic_subscription() -> None:
    approval = _approval()

    assert approval.permits_subscription(_subscription())


def test_fixture_only_approval_rejects_non_synthetic_subscription() -> None:
    async def scenario() -> None:
        connector = SyntheticStreamingConnector(
            subscription=_subscription_for("synthetic_fixture_source", synthetic_only=False),
            source_approval=_approval(),
            events=(),
        )

        with pytest.raises(SourceNotApprovedError):
            await connector.connect()

        assert connector.status == ConnectorStatus.SOURCE_BLOCKED

    asyncio.run(scenario())


def test_events_directly_on_unconnected_connector_fails_closed() -> None:
    async def scenario() -> None:
        connector = SyntheticStreamingConnector(
            subscription=_subscription(),
            source_approval=_approval(),
            events=(),
        )

        with pytest.raises(SourceNotApprovedError):
            _ = [event async for event in connector.events()]

        assert connector.status == ConnectorStatus.SOURCE_BLOCKED

    asyncio.run(scenario())


def test_events_directly_on_blocked_connector_fails_closed() -> None:
    async def scenario() -> None:
        connector = SyntheticStreamingConnector(
            subscription=_subscription_for("coinbase_spot_market_data", synthetic_only=False),
            source_approval=_approval(
                ApprovedUseStatus.BLOCKED_PENDING_REVIEW,
                source_id="coinbase_spot_market_data",
            ),
            events=(),
        )

        with pytest.raises(SourceNotApprovedError):
            _ = [event async for event in connector.events()]

        assert connector.status == ConnectorStatus.SOURCE_BLOCKED

    asyncio.run(scenario())


def test_synthetic_stream_iteration_and_lifecycle_without_network() -> None:
    heartbeat = HeartbeatEvent(
        subscription_id="SUB:S3-001:FIXTURE",
        source_id="synthetic_fixture_source",
        venue_id="SIMULATOR",
        event_ts=NOW,
        ingest_ts=NOW,
        raw_payload_id="raw:heartbeat:1",
        status=HeartbeatStatus.OBSERVED,
        last_observed_ts=NOW,
        timeout=timedelta(seconds=30),
    )
    quote = QuoteEvent(
        subscription_id="SUB:S3-001:FIXTURE",
        source_id="synthetic_fixture_source",
        venue_id="SIMULATOR",
        event_ts=NOW + timedelta(milliseconds=1),
        ingest_ts=NOW + timedelta(milliseconds=2),
        raw_payload_id="raw:quote:1",
        quote_id="quote-1",
        instrument_id="BTC-USD",
        best_bid=Decimal("50000.00"),
        best_ask=Decimal("50000.10"),
        sequence=2,
    )
    book = OrderBookEvent(
        subscription_id="SUB:S3-001:FIXTURE",
        source_id="synthetic_fixture_source",
        venue_id="SIMULATOR",
        event_ts=NOW + timedelta(milliseconds=3),
        ingest_ts=NOW + timedelta(milliseconds=4),
        raw_payload_id="raw:book:1",
        book_event_id="book-1",
        instrument_id="BTC-USD",
        sequence=3,
        is_snapshot=True,
        bids=(BookLevel(price=Decimal("50000.00"), quantity=Decimal("1.0")),),
        asks=(BookLevel(price=Decimal("50000.10"), quantity=Decimal("1.1")),),
        best_bid=Decimal("50000.00"),
        best_ask=Decimal("50000.10"),
        quality_flags=(),
    )

    async def scenario() -> list[StreamEvent]:
        connector = SyntheticStreamingConnector(
            subscription=_subscription(),
            source_approval=_approval(),
            heartbeat_policy=HeartbeatPolicy(
                interval=timedelta(seconds=5),
                timeout=timedelta(seconds=30),
            ),
            events=(heartbeat, quote, book),
        )

        connected = await connector.connect()
        assert connected.status == ConnectorStatus.CONNECTED
        assert connector.status == ConnectorStatus.CONNECTED

        observed = [event async for event in connector.events()]
        assert cast("ConnectorStatus", connector.status) == ConnectorStatus.CLOSED
        assert connector.heartbeat_status_at(
            NOW + timedelta(seconds=29)
        ) == HeartbeatStatus.OBSERVED
        assert connector.heartbeat_status_at(
            NOW + timedelta(seconds=31)
        ) == HeartbeatStatus.MISSED
        return observed

    observed_events = asyncio.run(scenario())

    assert observed_events == [heartbeat, quote, book]


def test_disconnect_reconnect_lifecycle_and_retry_exhaustion() -> None:
    async def scenario() -> None:
        connector = SyntheticStreamingConnector(
            subscription=_subscription(),
            source_approval=_approval(),
            retry_policy=RetryBackoffPolicy(max_attempts=1),
            events=(),
        )

        await connector.connect()
        disconnected = await connector.disconnect(DisconnectReason.HEARTBEAT_MISSED)
        assert disconnected.status == ConnectorStatus.DISCONNECTED
        assert disconnected.reason == DisconnectReason.HEARTBEAT_MISSED

        reconnected = await connector.reconnect(DisconnectReason.HEARTBEAT_MISSED)
        assert reconnected.status == ConnectorStatus.CONNECTED
        assert reconnected.attempt == 1

        exhausted = await connector.reconnect(DisconnectReason.TRANSPORT_CLOSED)
        assert exhausted.status == ConnectorStatus.FAILED
        assert exhausted.reason == DisconnectReason.RETRY_EXHAUSTED

    asyncio.run(scenario())


def test_crossed_quote_can_be_quarantined_with_machine_readable_flag() -> None:
    quote = QuoteEvent(
        subscription_id="SUB:S3-001:FIXTURE",
        source_id="synthetic_fixture_source",
        venue_id="SIMULATOR",
        event_ts=NOW,
        ingest_ts=NOW,
        raw_payload_id="raw:quote:crossed-flagged",
        quote_id="quote-crossed-flagged",
        instrument_id="BTC-USD",
        best_bid=Decimal("101"),
        best_ask=Decimal("100"),
        quality_flags=(StreamQualityFlag.CROSSED,),
    )

    assert quote.quality_flags == (StreamQualityFlag.CROSSED,)
