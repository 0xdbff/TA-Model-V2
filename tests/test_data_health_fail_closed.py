"""S3-003 fail-closed data-health signal evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ta_model.contracts.stream_health import (
    DataHealthGate,
    DataHealthGatePolicy,
    DataHealthReasonCode,
    DataHealthStatus,
    StreamHealthCheck,
    StreamHealthEvaluator,
    StreamHealthMetricName,
    StreamHealthPolicy,
)
from ta_model.contracts.streaming import QuoteEvent, TradeEvent

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
SUBSCRIPTION_ID = "SUB:S3-003:FIXTURE"
SOURCE_ID = "synthetic_fixture_source"
VENUE_ID = "SIMULATOR"


def _trade(
    *,
    trade_id: str = "trade-1",
    subscription_id: str = SUBSCRIPTION_ID,
    instrument_id: str = "BTC-USD",
    source_id: str = SOURCE_ID,
    event_ts: datetime = NOW,
    source_ts: datetime | None = NOW,
    sequence: int | None = 1,
) -> TradeEvent:
    return TradeEvent(
        subscription_id=subscription_id,
        source_id=source_id,
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
    instrument_id: str = "BTC-USD",
    sequence: int = 1,
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


def test_healthy_stream_health_record_emits_allow_signal() -> None:
    record = StreamHealthEvaluator().evaluate(_trade(), evaluation_ts=NOW)

    signal = DataHealthGate().evaluate(record)

    assert signal.status is DataHealthStatus.HEALTHY
    assert signal.blocks_trading is False
    assert signal.blocked_instrument_id is None
    assert signal.reason_codes == (DataHealthReasonCode.STREAM_HEALTHY,)
    assert signal.source_health_event_id == "trade-1"
    assert signal.source_scope.instrument_id == "BTC-USD"


def test_stale_critical_feed_blocks_only_affected_instrument_scope() -> None:
    evaluator = StreamHealthEvaluator(StreamHealthPolicy(max_event_age=timedelta(seconds=5)))
    stale_record = evaluator.evaluate(
        _trade(trade_id="stale-btc", instrument_id="BTC-USD", event_ts=NOW),
        evaluation_ts=NOW + timedelta(seconds=6),
    )
    healthy_record = evaluator.evaluate(
        _trade(trade_id="fresh-eth", instrument_id="ETH-USD", event_ts=NOW),
        evaluation_ts=NOW,
    )

    stale_signal, healthy_signal = DataHealthGate().evaluate_many((stale_record, healthy_record))

    assert stale_signal.status is DataHealthStatus.BLOCKED
    assert stale_signal.blocks_trading is True
    assert stale_signal.blocked_instrument_id == "BTC-USD"
    assert stale_signal.reason_codes == (DataHealthReasonCode.CRITICAL_FRESHNESS_STALE,)
    assert StreamHealthCheck.FRESHNESS in stale_signal.source_checks
    assert StreamHealthMetricName.STALE_EVENT in stale_signal.source_metric_names
    assert healthy_signal.status is DataHealthStatus.HEALTHY
    assert healthy_signal.blocks_trading is False
    assert healthy_signal.source_scope.instrument_id == "ETH-USD"


def test_non_critical_degraded_record_does_not_block_by_default() -> None:
    evaluator = StreamHealthEvaluator()
    evaluator.evaluate(_quote(quote_id="quote-1", sequence=1), evaluation_ts=NOW)
    gap_record = evaluator.evaluate(_quote(quote_id="quote-4", sequence=4), evaluation_ts=NOW)

    signal = DataHealthGate().evaluate(gap_record)

    assert signal.status is DataHealthStatus.DEGRADED
    assert signal.blocks_trading is False
    assert signal.blocked_instrument_id is None
    assert signal.reason_codes == (DataHealthReasonCode.NON_CRITICAL_STREAM_DEGRADED,)
    assert signal.source_checks == (StreamHealthCheck.SEQUENCE_GAP,)
    assert signal.source_metric_names == (StreamHealthMetricName.SEQUENCE_GAP_SIZE,)


def test_policy_can_treat_degraded_check_as_critical_with_same_scope() -> None:
    evaluator = StreamHealthEvaluator(StreamHealthPolicy(max_timestamp_drift=timedelta(seconds=1)))
    drift_record = evaluator.evaluate(
        _trade(trade_id="drift-eth", instrument_id="ETH-USD", source_ts=NOW - timedelta(seconds=3)),
        evaluation_ts=NOW,
    )

    signal = DataHealthGate(
        DataHealthGatePolicy(critical_checks=(StreamHealthCheck.TIMESTAMP_DRIFT,))
    ).evaluate(drift_record)

    assert signal.status is DataHealthStatus.BLOCKED
    assert signal.blocks_trading is True
    assert signal.blocked_instrument_id == "ETH-USD"
    assert signal.source_scope.source_id == SOURCE_ID
    assert signal.source_scope.venue_id == VENUE_ID
    assert signal.source_checks == (StreamHealthCheck.TIMESTAMP_DRIFT,)


def test_reason_code_and_metric_traceability_preserves_source_health_link() -> None:
    record = StreamHealthEvaluator(StreamHealthPolicy(max_event_age=timedelta(seconds=5))).evaluate(
        _trade(trade_id="trace-stale", event_ts=NOW),
        evaluation_ts=NOW + timedelta(seconds=7),
    )

    signal = DataHealthGate().evaluate(record)

    assert signal.signal_id.startswith("data-health:")
    assert len(signal.signal_id) == len("data-health:") + 64
    assert signal.source_health_event_id == record.event_id
    assert signal.source_health_status == record.status
    assert signal.evaluation_ts == record.evaluation_ts
    assert signal.reason_codes == (DataHealthReasonCode.CRITICAL_FRESHNESS_STALE,)
    assert StreamHealthMetricName.FRESHNESS_AGE_SECONDS in signal.source_metric_names
    assert StreamHealthMetricName.STALE_EVENT in signal.source_metric_names


def test_signal_id_is_distinct_for_same_event_id_across_different_scopes() -> None:
    evaluator = StreamHealthEvaluator()
    btc_record = evaluator.evaluate(
        _trade(trade_id="shared-event-id", instrument_id="BTC-USD", source_id=SOURCE_ID),
        evaluation_ts=NOW,
    )
    eth_record = evaluator.evaluate(
        _trade(
            trade_id="shared-event-id",
            instrument_id="ETH-USD",
            source_id="alternate_fixture_source",
        ),
        evaluation_ts=NOW,
    )

    btc_signal, eth_signal = DataHealthGate().evaluate_many((btc_record, eth_record))

    assert btc_signal.source_health_event_id == eth_signal.source_health_event_id
    assert btc_signal.source_scope.instrument_id == "BTC-USD"
    assert eth_signal.source_scope.instrument_id == "ETH-USD"
    assert btc_signal.source_scope.source_id == SOURCE_ID
    assert eth_signal.source_scope.source_id == "alternate_fixture_source"
    assert btc_signal.signal_id != eth_signal.signal_id


def test_signal_id_hash_avoids_delimiter_collision_between_valid_scopes() -> None:
    evaluator = StreamHealthEvaluator()
    first_record = evaluator.evaluate(
        _trade(
            trade_id="same-event-id",
            subscription_id="SUB:A",
            source_id="B",
            instrument_id="BTC-USD",
        ),
        evaluation_ts=NOW,
    )
    second_record = evaluator.evaluate(
        _trade(
            trade_id="same-event-id",
            subscription_id="SUB",
            source_id="A:B",
            instrument_id="BTC-USD",
        ),
        evaluation_ts=NOW,
    )

    first_signal, second_signal = DataHealthGate().evaluate_many((first_record, second_record))

    assert first_signal.source_scope.subscription_id == "SUB:A"
    assert first_signal.source_scope.source_id == "B"
    assert second_signal.source_scope.subscription_id == "SUB"
    assert second_signal.source_scope.source_id == "A:B"
    assert first_signal.signal_id.startswith("data-health:")
    assert second_signal.signal_id.startswith("data-health:")
    assert first_signal.signal_id != second_signal.signal_id
