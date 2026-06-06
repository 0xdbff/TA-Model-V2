"""Historical silver data-quality reporting for the S2 data gate.

Traceability:
- FR-001: missing historical OHLCTV intervals are measured and flagged.
- US-005: validation reports identify data blockers before promotion.

Scope:
- S2-004 evaluates in-memory silver normalization batches and fixture data only.
- No source/API/network access, persistence, Docker service, real backfill, feature dataset,
  paper/live behavior, leverage, derivatives, or live-capital path is introduced.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, NonNegativeFloat, PositiveInt, model_validator

from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString
from ta_model.contracts.market_data import MarketDataKind, SourceId, Timeframe
from ta_model.normalization.silver import (
    SilverNormalizationBatch,
    SilverOHLCTVRecord,
    SilverTradeRecord,
)


class GateDecision(StrEnum):
    """Data-gate classification used by historical quality reports."""

    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"


class MetricStatus(StrEnum):
    """Per-metric threshold status."""

    PASS = "pass"
    FAIL = "fail"


class DataQualityThresholds(ContractModel):
    """Configurable S2 data-gate thresholds.

    Defaults are fail-closed for validation fixtures: no missing bars, gaps, or duplicate records
    are tolerated unless a test or future approved run config explicitly relaxes the threshold.
    """

    max_missing_interval_rate: NonNegativeFloat = Field(default=0.0, le=1.0)
    max_gap_count: int = Field(default=0, ge=0)
    max_duplicate_rate: NonNegativeFloat = Field(default=0.0, le=1.0)


class DataQualityReportConfig(ContractModel):
    """Expected event-time scope for a silver quality report."""

    source_id: SourceId
    venue_id: CanonicalId
    instrument_id: CanonicalId
    data_kind: MarketDataKind
    window_start: AwareDatetime
    window_end: AwareDatetime
    thresholds: DataQualityThresholds = Field(default_factory=DataQualityThresholds)
    timeframe: Timeframe | None = None

    @model_validator(mode="after")
    def scope_is_consistent(self) -> Self:
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        if self.data_kind is MarketDataKind.OHLCTV and self.timeframe is None:
            raise ValueError("timeframe is required for OHLCTV quality reports")
        if self.data_kind is MarketDataKind.TRADE and self.timeframe is not None:
            raise ValueError("timeframe must be omitted for trade quality reports")
        return self


class ReportScope(ContractModel):
    """Source/venue/instrument/timeframe scope preserved in quality reports."""

    source_id: SourceId
    venue_id: CanonicalId
    instrument_id: CanonicalId
    data_kind: MarketDataKind
    window_start: AwareDatetime
    window_end: AwareDatetime
    timeframe: Timeframe | None = None


class OHLCTVQualityMetrics(ContractModel):
    """Completeness, gap, and duplicate metrics for OHLCTV bars."""

    expected_interval_count: PositiveInt
    observed_record_count: int = Field(ge=0)
    unique_interval_count: int = Field(ge=0)
    missing_interval_count: int = Field(ge=0)
    missing_interval_rate: NonNegativeFloat = Field(le=1.0)
    gap_count: int = Field(ge=0)
    duplicate_bar_count: int = Field(ge=0)
    duplicate_rate: NonNegativeFloat = Field(le=1.0)
    completeness_status: MetricStatus
    gap_status: MetricStatus
    duplicate_status: MetricStatus
    missing_intervals: tuple[AwareDatetime, ...]
    duplicate_intervals: tuple[AwareDatetime, ...]


class TradeQualityMetrics(ContractModel):
    """Duplicate metrics for historical trades."""

    observed_record_count: int = Field(ge=0)
    duplicate_trade_id_count: int = Field(ge=0)
    duplicate_sequence_count: int = Field(ge=0)
    duplicate_record_count: int = Field(ge=0)
    duplicate_rate: NonNegativeFloat = Field(le=1.0)
    duplicate_status: MetricStatus
    duplicate_trade_ids: tuple[str, ...]
    duplicate_sequences: tuple[int, ...]


class DataQualityBlocker(ContractModel):
    """Explicit fail-closed S2 data-gate blocker."""

    code: CanonicalId
    severity: Literal["P0"] = "P0"
    metric: NonEmptyString
    observed: NonNegativeFloat
    threshold: NonNegativeFloat
    message: NonEmptyString


class HistoricalDataQualityReport(ContractModel):
    """Structured data-quality report over silver normalized records."""

    report_id: CanonicalId
    scope: ReportScope
    decision: GateDecision
    thresholds: DataQualityThresholds
    ohlctv_metrics: OHLCTVQualityMetrics | None = None
    trade_metrics: TradeQualityMetrics | None = None
    blockers: tuple[DataQualityBlocker, ...]
    event_time_fields_used: tuple[Literal["open_ts", "close_ts", "event_ts"], ...]
    ingest_time_used_for_quality_decision: Literal[False] = False


def evaluate_silver_ohlctv_batch(
    batch: SilverNormalizationBatch,
    config: DataQualityReportConfig,
) -> HistoricalDataQualityReport:
    """Evaluate OHLCTV interval completeness and duplicate bars using event time."""

    _validate_batch_scope(batch, config, expected_kind=MarketDataKind.OHLCTV)
    if batch.timeframe is None:
        raise ValueError("OHLCTV batch timeframe is required")
    interval = _timeframe_to_timedelta(batch.timeframe)
    expected_opens = _expected_interval_opens(config.window_start, config.window_end, interval)
    open_counts = Counter(
        record.bar.open_ts
        for record in batch.records
        if isinstance(record, SilverOHLCTVRecord)
        and config.window_start <= record.bar.open_ts < config.window_end
    )
    missing_intervals = tuple(open_ts for open_ts in expected_opens if open_counts[open_ts] == 0)
    duplicate_intervals = tuple(
        open_ts for open_ts, count in sorted(open_counts.items()) if count > 1
    )
    observed_record_count = sum(open_counts.values())
    duplicate_bar_count = sum(count - 1 for count in open_counts.values() if count > 1)
    missing_rate = len(missing_intervals) / len(expected_opens)
    duplicate_rate = _safe_rate(duplicate_bar_count, observed_record_count)
    gap_count = _count_contiguous_gaps(missing_intervals, interval)
    metrics = OHLCTVQualityMetrics(
        expected_interval_count=len(expected_opens),
        observed_record_count=observed_record_count,
        unique_interval_count=len(open_counts),
        missing_interval_count=len(missing_intervals),
        missing_interval_rate=missing_rate,
        gap_count=gap_count,
        duplicate_bar_count=duplicate_bar_count,
        duplicate_rate=duplicate_rate,
        completeness_status=_metric_status(
            missing_rate, config.thresholds.max_missing_interval_rate
        ),
        gap_status=_metric_status(float(gap_count), float(config.thresholds.max_gap_count)),
        duplicate_status=_metric_status(duplicate_rate, config.thresholds.max_duplicate_rate),
        missing_intervals=missing_intervals,
        duplicate_intervals=duplicate_intervals,
    )
    blockers = _ohlctv_blockers(metrics, config.thresholds)
    return HistoricalDataQualityReport(
        report_id=_report_id(config),
        scope=_scope(config),
        decision=_decision(blockers),
        thresholds=config.thresholds,
        ohlctv_metrics=metrics,
        blockers=blockers,
        event_time_fields_used=("open_ts", "close_ts"),
    )


def evaluate_silver_trade_batch(
    batch: SilverNormalizationBatch,
    config: DataQualityReportConfig,
) -> HistoricalDataQualityReport:
    """Evaluate trade duplicate IDs and source sequences using event time."""

    _validate_batch_scope(batch, config, expected_kind=MarketDataKind.TRADE)
    records = tuple(record for record in batch.records if isinstance(record, SilverTradeRecord))
    scoped_records = tuple(
        record
        for record in records
        if config.window_start <= record.trade.event_ts < config.window_end
    )
    trade_id_counts = Counter(record.trade.trade_id for record in scoped_records)
    sequence_counts = Counter(
        record.trade.sequence for record in scoped_records if record.trade.sequence is not None
    )
    duplicate_trade_ids = tuple(
        trade_id for trade_id, count in sorted(trade_id_counts.items()) if count > 1
    )
    duplicate_sequences = tuple(
        sequence for sequence, count in sorted(sequence_counts.items()) if count > 1
    )
    duplicate_trade_id_count = sum(count - 1 for count in trade_id_counts.values() if count > 1)
    duplicate_sequence_count = sum(count - 1 for count in sequence_counts.values() if count > 1)
    duplicate_record_count = sum(
        1
        for record in scoped_records
        if trade_id_counts[record.trade.trade_id] > 1
        or (record.trade.sequence is not None and sequence_counts[record.trade.sequence] > 1)
    )
    duplicate_rate = _safe_rate(duplicate_record_count, len(scoped_records))
    metrics = TradeQualityMetrics(
        observed_record_count=len(scoped_records),
        duplicate_trade_id_count=duplicate_trade_id_count,
        duplicate_sequence_count=duplicate_sequence_count,
        duplicate_record_count=duplicate_record_count,
        duplicate_rate=duplicate_rate,
        duplicate_status=_metric_status(duplicate_rate, config.thresholds.max_duplicate_rate),
        duplicate_trade_ids=duplicate_trade_ids,
        duplicate_sequences=duplicate_sequences,
    )
    blockers = _trade_blockers(metrics, config.thresholds)
    return HistoricalDataQualityReport(
        report_id=_report_id(config),
        scope=_scope(config),
        decision=_decision(blockers),
        thresholds=config.thresholds,
        trade_metrics=metrics,
        blockers=blockers,
        event_time_fields_used=("event_ts",),
    )


def _validate_batch_scope(
    batch: SilverNormalizationBatch,
    config: DataQualityReportConfig,
    *,
    expected_kind: MarketDataKind,
) -> None:
    if config.data_kind is not expected_kind or batch.data_kind is not expected_kind:
        raise ValueError("batch and report config must match expected data_kind")
    if batch.source_id != config.source_id:
        raise ValueError("batch source_id must match report scope")
    if batch.venue_id != config.venue_id:
        raise ValueError("batch venue_id must match report scope")
    if batch.instrument_id != config.instrument_id:
        raise ValueError("batch instrument_id must match report scope")
    if batch.timeframe != config.timeframe:
        raise ValueError("batch timeframe must match report scope")


def _timeframe_to_timedelta(timeframe: str) -> timedelta:
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    raise ValueError("unsupported timeframe unit")


def _expected_interval_opens(
    window_start: datetime,
    window_end: datetime,
    interval: timedelta,
) -> tuple[datetime, ...]:
    opens: list[datetime] = []
    cursor = window_start
    while cursor < window_end:
        opens.append(cursor)
        cursor += interval
    if cursor != window_end:
        raise ValueError("window must align exactly to timeframe intervals")
    if len(opens) == 0:
        raise ValueError("quality window must contain at least one expected interval")
    return tuple(opens)


def _count_contiguous_gaps(missing_intervals: tuple[datetime, ...], interval: timedelta) -> int:
    if len(missing_intervals) == 0:
        return 0
    gap_count = 1
    previous = missing_intervals[0]
    for current in missing_intervals[1:]:
        if current != previous + interval:
            gap_count += 1
        previous = current
    return gap_count


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _metric_status(observed: float, threshold: float) -> MetricStatus:
    return MetricStatus.PASS if observed <= threshold else MetricStatus.FAIL


def _ohlctv_blockers(
    metrics: OHLCTVQualityMetrics,
    thresholds: DataQualityThresholds,
) -> tuple[DataQualityBlocker, ...]:
    blockers: list[DataQualityBlocker] = []
    if metrics.missing_interval_rate > thresholds.max_missing_interval_rate:
        blockers.append(
            DataQualityBlocker(
                code="DQB:S2-004:MISSING_BARS",
                metric="missing_interval_rate",
                observed=metrics.missing_interval_rate,
                threshold=thresholds.max_missing_interval_rate,
                message="Missing OHLCTV intervals breach configured completeness threshold.",
            )
        )
    if metrics.gap_count > thresholds.max_gap_count:
        blockers.append(
            DataQualityBlocker(
                code="DQB:S2-004:GAPS",
                metric="gap_count",
                observed=float(metrics.gap_count),
                threshold=float(thresholds.max_gap_count),
                message="OHLCTV event-time gaps breach configured threshold.",
            )
        )
    if metrics.duplicate_rate > thresholds.max_duplicate_rate:
        blockers.append(
            DataQualityBlocker(
                code="DQB:S2-004:DUPLICATE_BARS",
                metric="duplicate_rate",
                observed=metrics.duplicate_rate,
                threshold=thresholds.max_duplicate_rate,
                message="Duplicate OHLCTV bars breach configured duplicate threshold.",
            )
        )
    return tuple(blockers)


def _trade_blockers(
    metrics: TradeQualityMetrics,
    thresholds: DataQualityThresholds,
) -> tuple[DataQualityBlocker, ...]:
    if metrics.duplicate_rate <= thresholds.max_duplicate_rate:
        return ()
    return (
        DataQualityBlocker(
            code="DQB:S2-004:DUPLICATE_TRADES",
            metric="duplicate_rate",
            observed=metrics.duplicate_rate,
            threshold=thresholds.max_duplicate_rate,
            message="Duplicate trade IDs or sequences breach configured duplicate threshold.",
        ),
    )


def _decision(blockers: tuple[DataQualityBlocker, ...]) -> GateDecision:
    return GateDecision.PASS if len(blockers) == 0 else GateDecision.BLOCKED


def _scope(config: DataQualityReportConfig) -> ReportScope:
    return ReportScope(
        source_id=config.source_id,
        venue_id=config.venue_id,
        instrument_id=config.instrument_id,
        data_kind=config.data_kind,
        timeframe=config.timeframe,
        window_start=config.window_start,
        window_end=config.window_end,
    )


def _report_id(config: DataQualityReportConfig) -> str:
    payload = {
        "data_kind": config.data_kind.value,
        "instrument_id": config.instrument_id,
        "source_id": config.source_id,
        "timeframe": config.timeframe,
        "venue_id": config.venue_id,
        "window_end": config.window_end.isoformat(),
        "window_start": config.window_start.isoformat(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    return f"DQREPORT:S2-004:{digest.upper()}"
