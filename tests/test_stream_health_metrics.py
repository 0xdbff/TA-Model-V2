"""S3-002 streaming data-health metric evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ta_model.contracts.stream_health import (
    StreamHealthCheck,
    StreamHealthEvaluator,
    StreamHealthMetric,
    StreamHealthMetricName,
    StreamHealthPolicy,
    StreamHealthStatus,
)
from ta_model.contracts.streaming import QuoteEvent, StreamChannel, TradeEvent

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
SUBSCRIPTION_ID = "SUB:S3-002:FIXTURE"
SOURCE_ID = "synthetic_fixture_source"
VENUE_ID = "SIMULATOR"


def _trade(
    *,
    trade_id: str = "trade-1",
    instrument_id: str = "BTC-USD",
    event_ts: datetime = NOW,
    source_ts: datetime | None = NOW,
    sequence: int | None = 1,
) -> TradeEvent:
    return TradeEvent(
        subscription_id=SUBSCRIPTION_ID,
        source_id=SOURCE_ID,
        venue_id=VENUE_ID,
        event_ts=event_ts,
        source_ts=source_ts,
        ingest_ts=event_ts + timedelta(milliseconds=2),
        raw_payload_id=f"raw:{trade_id}",
        trade_id=trade_id,
        instrument_id=instrument_id,
        price=Decimal("50000.00"),
        quantity=Decimal("0.10"),
        sequence=sequence,
    )


def _quote(
    *,
    quote_id: str,
    instrument_id: str,
    sequence: int,
) -> QuoteEvent:
    return QuoteEvent(
        subscription_id=SUBSCRIPTION_ID,
        source_id=SOURCE_ID,
        venue_id=VENUE_ID,
        event_ts=NOW,
        source_ts=NOW,
        ingest_ts=NOW + timedelta(milliseconds=2),
        raw_payload_id=f"raw:{quote_id}",
        quote_id=quote_id,
        instrument_id=instrument_id,
        best_bid=Decimal("50000.00"),
        best_ask=Decimal("50000.10"),
        sequence=sequence,
    )


def _metric_value(
    record_name: StreamHealthMetricName,
    record_metrics: tuple[StreamHealthMetric, ...],
) -> Decimal:
    return next(metric.value for metric in record_metrics if metric.name is record_name)


def test_healthy_stream_emits_structured_metric_names_and_values() -> None:
    evaluator = StreamHealthEvaluator(
        StreamHealthPolicy(
            max_event_age=timedelta(seconds=5),
            max_timestamp_drift=timedelta(seconds=1),
        )
    )

    record = evaluator.evaluate(_trade(), evaluation_ts=NOW + timedelta(milliseconds=500))

    assert record.status is StreamHealthStatus.HEALTHY
    assert record.issues == ()
    assert record.scope.channel is StreamChannel.TRADES
    assert record.scope.instrument_id == "BTC-USD"
    metrics_by_name = {metric.name: metric for metric in record.metrics}
    assert set(metrics_by_name) == {
        StreamHealthMetricName.FRESHNESS_AGE_SECONDS,
        StreamHealthMetricName.STALE_EVENT,
        StreamHealthMetricName.TIMESTAMP_DRIFT_SECONDS,
        StreamHealthMetricName.DUPLICATE_EVENT,
        StreamHealthMetricName.SEQUENCE_GAP_SIZE,
    }
    assert metrics_by_name[StreamHealthMetricName.FRESHNESS_AGE_SECONDS].value == Decimal("0.5")
    assert metrics_by_name[StreamHealthMetricName.STALE_EVENT].value == Decimal(0)
    assert metrics_by_name[StreamHealthMetricName.DUPLICATE_EVENT].breached is False


def test_stale_event_detected_from_explicit_evaluation_timestamp() -> None:
    evaluator = StreamHealthEvaluator(StreamHealthPolicy(max_event_age=timedelta(seconds=5)))

    record = evaluator.evaluate(_trade(event_ts=NOW), evaluation_ts=NOW + timedelta(seconds=6))

    assert record.status is StreamHealthStatus.DEGRADED
    assert any(issue.check is StreamHealthCheck.FRESHNESS for issue in record.issues)
    assert _metric_value(StreamHealthMetricName.STALE_EVENT, record.metrics) == Decimal(1)
    assert _metric_value(StreamHealthMetricName.FRESHNESS_AGE_SECONDS, record.metrics) == Decimal(6)


def test_sequence_gap_detected_within_instrument_source_channel_scope() -> None:
    evaluator = StreamHealthEvaluator()

    first = evaluator.evaluate(_trade(trade_id="trade-1", sequence=1), evaluation_ts=NOW)
    gap = evaluator.evaluate(_trade(trade_id="trade-4", sequence=4), evaluation_ts=NOW)

    assert first.status is StreamHealthStatus.HEALTHY
    assert gap.status is StreamHealthStatus.DEGRADED
    assert _metric_value(StreamHealthMetricName.SEQUENCE_GAP_SIZE, gap.metrics) == Decimal(2)
    assert any(issue.check is StreamHealthCheck.SEQUENCE_GAP for issue in gap.issues)


def test_duplicate_event_detected_by_stable_id_and_sequence() -> None:
    evaluator = StreamHealthEvaluator()
    event = _trade(trade_id="trade-dup", sequence=7)

    first = evaluator.evaluate(event, evaluation_ts=NOW)
    duplicate = evaluator.evaluate(event, evaluation_ts=NOW)

    assert first.status is StreamHealthStatus.HEALTHY
    assert duplicate.status is StreamHealthStatus.DEGRADED
    assert _metric_value(StreamHealthMetricName.DUPLICATE_EVENT, duplicate.metrics) == Decimal(1)
    assert any(issue.check is StreamHealthCheck.DUPLICATE for issue in duplicate.issues)


def test_timestamp_drift_uses_source_or_event_timestamp_not_ingest_time() -> None:
    evaluator = StreamHealthEvaluator(StreamHealthPolicy(max_timestamp_drift=timedelta(seconds=1)))
    event = _trade(
        trade_id="trade-drift",
        event_ts=NOW,
        source_ts=NOW - timedelta(seconds=3),
    )

    record = evaluator.evaluate(event, evaluation_ts=NOW)

    assert record.status is StreamHealthStatus.DEGRADED
    assert _metric_value(StreamHealthMetricName.TIMESTAMP_DRIFT_SECONDS, record.metrics) == Decimal(
        3
    )
    assert any(issue.check is StreamHealthCheck.TIMESTAMP_DRIFT for issue in record.issues)


def test_future_dated_source_timestamp_is_degraded_by_timestamp_drift() -> None:
    evaluator = StreamHealthEvaluator(StreamHealthPolicy(max_timestamp_drift=timedelta(seconds=1)))
    event = _trade(
        trade_id="trade-future-drift",
        event_ts=NOW + timedelta(seconds=3),
        source_ts=NOW + timedelta(seconds=3),
    )

    record = evaluator.evaluate(event, evaluation_ts=NOW)

    assert record.status is StreamHealthStatus.DEGRADED
    assert _metric_value(StreamHealthMetricName.TIMESTAMP_DRIFT_SECONDS, record.metrics) == Decimal(
        3
    )
    assert _metric_value(StreamHealthMetricName.FRESHNESS_AGE_SECONDS, record.metrics) == Decimal(0)
    assert any(issue.check is StreamHealthCheck.TIMESTAMP_DRIFT for issue in record.issues)


def test_sequence_and_duplicate_state_are_scoped_per_instrument_source_channel() -> None:
    evaluator = StreamHealthEvaluator()

    btc_trade = evaluator.evaluate(
        _trade(trade_id="trade-btc-1", instrument_id="BTC-USD", sequence=1),
        evaluation_ts=NOW,
    )
    eth_trade = evaluator.evaluate(
        _trade(trade_id="trade-eth-1", instrument_id="ETH-USD", sequence=1),
        evaluation_ts=NOW,
    )
    btc_quote = evaluator.evaluate(
        _quote(quote_id="quote-btc-1", instrument_id="BTC-USD", sequence=1),
        evaluation_ts=NOW,
    )

    assert btc_trade.status is StreamHealthStatus.HEALTHY
    assert eth_trade.status is StreamHealthStatus.HEALTHY
    assert btc_quote.status is StreamHealthStatus.HEALTHY
    assert eth_trade.scope.instrument_id == "ETH-USD"
    assert btc_quote.scope.channel is StreamChannel.QUOTES


def test_evaluate_many_returns_deterministic_structured_records() -> None:
    evaluator = StreamHealthEvaluator()

    records = evaluator.evaluate_many(
        (
            _trade(trade_id="trade-1", sequence=1),
            _trade(trade_id="trade-2", sequence=2),
        ),
        evaluation_ts=NOW,
    )

    assert tuple(record.event_id for record in records) == ("trade-1", "trade-2")
    assert all(record.status is StreamHealthStatus.HEALTHY for record in records)
