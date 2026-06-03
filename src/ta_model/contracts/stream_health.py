"""Streaming data-health metric contracts and deterministic evaluator.

Traceability:
- FR-002: stream freshness, sequence gaps, duplicates, and reconnects measured.
- NFR-006: stale critical feed detection contract for later fail-closed behavior.

Scope:
- S3-002 only emits structured health/metric records for synthetic stream events.
- No strategy/risk fail-closed signal, event bus, Prometheus/Grafana, Docker service,
  real connector stream, live capital, leverage, margin, derivatives, or shorting path
  is introduced here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString
from ta_model.contracts.market_data import SourceId
from ta_model.contracts.streaming import (
    HeartbeatEvent,
    LifecycleEvent,
    OrderBookEvent,
    QuoteEvent,
    StreamChannel,
    StreamEvent,
    StreamEventType,
    TradeEvent,
)

NonNegativeDecimal = Annotated[Decimal, Field(ge=Decimal("0"))]
PositiveTimedelta = Annotated[timedelta, Field(gt=timedelta(0))]


class StreamHealthStatus(StrEnum):
    """Overall health class for one evaluated stream event."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"


class StreamHealthCheck(StrEnum):
    """Machine-readable health check families emitted by S3-002."""

    FRESHNESS = "freshness"
    SEQUENCE_GAP = "sequence_gap"
    DUPLICATE = "duplicate"
    TIMESTAMP_DRIFT = "timestamp_drift"


class StreamHealthMetricName(StrEnum):
    """Stable metric names reserved for later observability wiring."""

    FRESHNESS_AGE_SECONDS = "stream.freshness.age_seconds"
    STALE_EVENT = "stream.freshness.stale_event"
    SEQUENCE_GAP_SIZE = "stream.sequence.gap_size"
    DUPLICATE_EVENT = "stream.duplicate.event"
    TIMESTAMP_DRIFT_SECONDS = "stream.timestamp.drift_seconds"


class StreamHealthPolicy(ContractModel):
    """Thresholds for deterministic fixture stream-health evaluation."""

    max_event_age: PositiveTimedelta = timedelta(seconds=5)
    max_timestamp_drift: PositiveTimedelta = timedelta(seconds=1)


class StreamHealthScope(ContractModel):
    """Instrument/source/channel key used for scoped health state."""

    subscription_id: CanonicalId
    source_id: SourceId
    venue_id: CanonicalId
    channel: StreamChannel | StreamEventType
    instrument_id: CanonicalId | None = None

    def key(self) -> tuple[str, str, str, str, str | None]:
        """Return a hashable state key without relying on model internals."""

        return (
            self.subscription_id,
            self.source_id,
            self.venue_id,
            self.channel.value,
            self.instrument_id,
        )


class StreamHealthMetric(ContractModel):
    """Single structured health metric sample."""

    name: StreamHealthMetricName
    value: NonNegativeDecimal
    threshold: NonNegativeDecimal | None = None
    breached: bool = False
    check: StreamHealthCheck
    scope: StreamHealthScope
    evaluation_ts: AwareDatetime


class StreamHealthIssue(ContractModel):
    """Detailed health finding for downstream alerts/fail-closed consumers."""

    check: StreamHealthCheck
    metric_name: StreamHealthMetricName
    observed_value: NonNegativeDecimal
    threshold: NonNegativeDecimal | None = None
    description: NonEmptyString


class StreamHealthRecord(ContractModel):
    """Evaluation output for one stream event."""

    event_type: StreamEventType
    event_id: NonEmptyString
    sequence: int | None
    scope: StreamHealthScope
    evaluation_ts: AwareDatetime
    event_ts: AwareDatetime
    source_ts: AwareDatetime | None = None
    status: StreamHealthStatus
    metrics: tuple[StreamHealthMetric, ...]
    issues: tuple[StreamHealthIssue, ...] = ()

    @model_validator(mode="after")
    def degraded_requires_issue(self) -> StreamHealthRecord:
        if self.status is StreamHealthStatus.DEGRADED and not self.issues:
            raise ValueError("degraded stream health record requires at least one issue")
        return self


class StreamHealthEvaluator:
    """Stateful, explicit-clock stream-health evaluator with no global state."""

    def __init__(self, policy: StreamHealthPolicy | None = None) -> None:
        self.policy = policy or StreamHealthPolicy()
        self._last_sequence_by_scope: dict[tuple[str, str, str, str, str | None], int] = {}
        self._seen_event_ids_by_scope: dict[tuple[str, str, str, str, str | None], set[str]] = {}
        self._seen_sequences_by_scope: dict[tuple[str, str, str, str, str | None], set[int]] = {}

    def evaluate(self, event: StreamEvent, *, evaluation_ts: datetime) -> StreamHealthRecord:
        """Evaluate one event against an explicit event-time clock.

        `evaluation_ts` is required so freshness/drift checks never fall back to
        ingestion time or wall-clock time.
        """

        scope = _scope_for(event)
        scope_key = scope.key()
        event_id = _event_id_for(event)
        sequence = _sequence_for(event)
        metrics: list[StreamHealthMetric] = []
        issues: list[StreamHealthIssue] = []

        age = max(evaluation_ts - event.event_ts, timedelta(0))
        age_value = _seconds(age)
        stale_threshold = _seconds(self.policy.max_event_age)
        stale = age > self.policy.max_event_age
        metrics.append(
            self._metric(
                StreamHealthMetricName.FRESHNESS_AGE_SECONDS,
                age_value,
                stale_threshold,
                stale,
                StreamHealthCheck.FRESHNESS,
                scope,
                evaluation_ts,
            )
        )
        metrics.append(
            self._metric(
                StreamHealthMetricName.STALE_EVENT,
                Decimal(1 if stale else 0),
                Decimal(0),
                stale,
                StreamHealthCheck.FRESHNESS,
                scope,
                evaluation_ts,
            )
        )
        if stale:
            issues.append(
                StreamHealthIssue(
                    check=StreamHealthCheck.FRESHNESS,
                    metric_name=StreamHealthMetricName.STALE_EVENT,
                    observed_value=age_value,
                    threshold=stale_threshold,
                    description="event_ts is older than max_event_age at evaluation_ts",
                )
            )

        drift_reference_ts = event.source_ts or event.event_ts
        drift = abs(evaluation_ts - drift_reference_ts)
        drift_value = _seconds(drift)
        drift_threshold = _seconds(self.policy.max_timestamp_drift)
        drifted = drift > self.policy.max_timestamp_drift
        metrics.append(
            self._metric(
                StreamHealthMetricName.TIMESTAMP_DRIFT_SECONDS,
                drift_value,
                drift_threshold,
                drifted,
                StreamHealthCheck.TIMESTAMP_DRIFT,
                scope,
                evaluation_ts,
            )
        )
        if drifted:
            issues.append(
                StreamHealthIssue(
                    check=StreamHealthCheck.TIMESTAMP_DRIFT,
                    metric_name=StreamHealthMetricName.TIMESTAMP_DRIFT_SECONDS,
                    observed_value=drift_value,
                    threshold=drift_threshold,
                    description=(
                        "source_ts/event_ts is outside max_timestamp_drift at evaluation_ts"
                    ),
                )
            )

        duplicate = event_id in self._seen_event_ids_by_scope.setdefault(scope_key, set())
        if sequence is not None:
            duplicate = duplicate or sequence in self._seen_sequences_by_scope.setdefault(
                scope_key,
                set(),
            )
        metrics.append(
            self._metric(
                StreamHealthMetricName.DUPLICATE_EVENT,
                Decimal(1 if duplicate else 0),
                Decimal(0),
                duplicate,
                StreamHealthCheck.DUPLICATE,
                scope,
                evaluation_ts,
            )
        )
        if duplicate:
            issues.append(
                StreamHealthIssue(
                    check=StreamHealthCheck.DUPLICATE,
                    metric_name=StreamHealthMetricName.DUPLICATE_EVENT,
                    observed_value=Decimal(1),
                    threshold=Decimal(0),
                    description="event_id or sequence was already observed in this stream scope",
                )
            )

        gap_size = 0
        previous_sequence = self._last_sequence_by_scope.get(scope_key)
        if (
            sequence is not None
            and previous_sequence is not None
            and sequence > previous_sequence + 1
        ):
            gap_size = sequence - previous_sequence - 1
        gap_value = Decimal(gap_size)
        gap_detected = gap_size > 0
        metrics.append(
            self._metric(
                StreamHealthMetricName.SEQUENCE_GAP_SIZE,
                gap_value,
                Decimal(0),
                gap_detected,
                StreamHealthCheck.SEQUENCE_GAP,
                scope,
                evaluation_ts,
            )
        )
        if gap_detected:
            issues.append(
                StreamHealthIssue(
                    check=StreamHealthCheck.SEQUENCE_GAP,
                    metric_name=StreamHealthMetricName.SEQUENCE_GAP_SIZE,
                    observed_value=gap_value,
                    threshold=Decimal(0),
                    description="sequence advanced by more than one in this stream scope",
                )
            )

        self._seen_event_ids_by_scope[scope_key].add(event_id)
        if sequence is not None:
            self._seen_sequences_by_scope.setdefault(scope_key, set()).add(sequence)
            if previous_sequence is None or sequence > previous_sequence:
                self._last_sequence_by_scope[scope_key] = sequence

        return StreamHealthRecord(
            event_type=event.event_type,
            event_id=event_id,
            sequence=sequence,
            scope=scope,
            evaluation_ts=evaluation_ts,
            event_ts=event.event_ts,
            source_ts=event.source_ts,
            status=StreamHealthStatus.DEGRADED if issues else StreamHealthStatus.HEALTHY,
            metrics=tuple(metrics),
            issues=tuple(issues),
        )

    def evaluate_many(
        self,
        events: tuple[StreamEvent, ...],
        *,
        evaluation_ts: datetime,
    ) -> tuple[StreamHealthRecord, ...]:
        """Evaluate a deterministic fixture batch with one explicit evaluation timestamp."""

        return tuple(self.evaluate(event, evaluation_ts=evaluation_ts) for event in events)

    @staticmethod
    def _metric(
        name: StreamHealthMetricName,
        value: Decimal,
        threshold: Decimal | None,
        breached: bool,
        check: StreamHealthCheck,
        scope: StreamHealthScope,
        evaluation_ts: datetime,
    ) -> StreamHealthMetric:
        return StreamHealthMetric(
            name=name,
            value=value,
            threshold=threshold,
            breached=breached,
            check=check,
            scope=scope,
            evaluation_ts=evaluation_ts,
        )


def _scope_for(event: StreamEvent) -> StreamHealthScope:
    channel: StreamChannel | StreamEventType
    instrument_id: str | None = None
    if isinstance(event, TradeEvent):
        channel = StreamChannel.TRADES
        instrument_id = event.instrument_id
    elif isinstance(event, QuoteEvent):
        channel = StreamChannel.QUOTES
        instrument_id = event.instrument_id
    elif isinstance(event, OrderBookEvent):
        channel = StreamChannel.ORDER_BOOK
        instrument_id = event.instrument_id
    else:
        channel = event.event_type
    return StreamHealthScope(
        subscription_id=event.subscription_id,
        source_id=event.source_id,
        venue_id=event.venue_id,
        channel=channel,
        instrument_id=instrument_id,
    )


def _event_id_for(event: StreamEvent) -> str:
    if isinstance(event, TradeEvent):
        return event.trade_id
    if isinstance(event, QuoteEvent):
        return event.quote_id
    if isinstance(event, OrderBookEvent):
        return event.book_event_id
    if isinstance(event, HeartbeatEvent):
        return event.raw_payload_id
    if isinstance(event, LifecycleEvent):
        return event.raw_payload_id


def _sequence_for(event: StreamEvent) -> int | None:
    if isinstance(event, TradeEvent | QuoteEvent | OrderBookEvent):
        return event.sequence
    return None


def _seconds(value: timedelta) -> Decimal:
    return Decimal(str(value.total_seconds()))
