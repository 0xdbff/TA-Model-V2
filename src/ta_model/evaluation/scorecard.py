"""Build deterministic S5 evaluation scorecards from baseline reports."""

from __future__ import annotations

from decimal import Decimal

from ta_model.contracts.baselines import BaselineReport, BaselineRow
from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.evaluation import (
    BaselineSplitScore,
    BenchmarkConfig,
    EvaluationMetric,
    EvaluationScorecard,
    MetricAssumptions,
    MetricStatus,
    build_scorecard_hash,
    build_scorecard_id,
)


class EvaluationBuildError(ValueError):
    """Raised when baseline reports cannot be safely scorecarded."""


def build_evaluation_scorecard(
    reports: tuple[BaselineReport, ...],
    *,
    benchmark_report: BaselineReport,
    assumptions: MetricAssumptions | None = None,
) -> EvaluationScorecard:
    """Compute net-first S5 metrics by baseline report and split.

    Benchmark-relative net return is only available when rows align exactly by
    split, instrument, venue, and event-time timestamp. This fails closed rather
    than silently comparing different windows.
    """

    if not reports:
        raise EvaluationBuildError("at least one baseline report is required")
    assumptions = assumptions or MetricAssumptions()
    benchmark_config = BenchmarkConfig(
        benchmark_report_id=benchmark_report.baseline_report_id,
        benchmark_report_hash=benchmark_report.baseline_report_hash,
        benchmark_name=benchmark_report.baseline_config.name,
    )
    scores: list[BaselineSplitScore] = []
    for report in reports:
        _validate_same_dataset(report=report, benchmark_report=benchmark_report)
        for split in DatasetSplit:
            split_rows = tuple(row for row in report.rows if row.split is split)
            benchmark_rows = tuple(row for row in benchmark_report.rows if row.split is split)
            scores.append(
                _score_split(
                    report=report,
                    split=split,
                    rows=split_rows,
                    benchmark_rows=benchmark_rows,
                    assumptions=assumptions,
                )
            )

    input_ids = tuple(report.baseline_report_id for report in reports)
    input_hashes = tuple(report.baseline_report_hash for report in reports)
    score_tuple = tuple(scores)
    scorecard_hash = build_scorecard_hash(
        input_baseline_report_ids=input_ids,
        input_baseline_report_hashes=input_hashes,
        benchmark_config=benchmark_config,
        metric_assumptions=assumptions,
        scores=score_tuple,
    )
    return EvaluationScorecard(
        scorecard_id=build_scorecard_id(scorecard_hash=scorecard_hash),
        scorecard_hash=scorecard_hash,
        input_baseline_report_ids=input_ids,
        input_baseline_report_hashes=input_hashes,
        benchmark_config=benchmark_config,
        metric_assumptions=assumptions,
        scores=score_tuple,
    )


def _score_split(
    *,
    report: BaselineReport,
    split: DatasetSplit,
    rows: tuple[BaselineRow, ...],
    benchmark_rows: tuple[BaselineRow, ...],
    assumptions: MetricAssumptions,
) -> BaselineSplitScore:
    returns = tuple(row.net_return for row in rows)
    reason = f"empty split {split.value}"
    benchmark_relative = _benchmark_relative_net_return(
        rows=rows, benchmark_rows=benchmark_rows
    )
    return BaselineSplitScore(
        baseline_report_id=report.baseline_report_id,
        baseline_name=report.baseline_config.name,
        baseline_kind=report.baseline_config.kind,
        split=split,
        observation_count=len(rows),
        net_return=_metric(_compounded_return(returns), reason=reason),
        mean_net_return=_metric(_mean(returns), reason=reason),
        sharpe=_sharpe(returns),
        sortino=_sortino(returns),
        calmar=_calmar(returns),
        max_drawdown=_metric(_max_drawdown(returns), reason=reason),
        cvar=_metric(_cvar(returns, assumptions.cvar_tail_probability), reason=reason),
        turnover_sum=_metric(_sum_tuple(tuple(row.turnover for row in rows)), reason=reason),
        average_exposure=_metric(_mean(tuple(row.exposure for row in rows)), reason=reason),
        cost_return_sum=_metric(_sum_tuple(tuple(row.cost_return for row in rows)), reason=reason),
        benchmark_relative_net_return=benchmark_relative,
    )


def _validate_same_dataset(*, report: BaselineReport, benchmark_report: BaselineReport) -> None:
    if report.dataset_snapshot_id != benchmark_report.dataset_snapshot_id:
        raise EvaluationBuildError("benchmark dataset_snapshot_id mismatch")
    if report.dataset_hash != benchmark_report.dataset_hash:
        raise EvaluationBuildError("benchmark dataset_hash mismatch")


def _benchmark_relative_net_return(
    *, rows: tuple[BaselineRow, ...], benchmark_rows: tuple[BaselineRow, ...]
) -> EvaluationMetric:
    if not rows:
        return EvaluationMetric(
            value=None,
            status=MetricStatus.NOT_APPLICABLE,
            reason="empty split has no benchmark-relative return",
        )
    if len(rows) != len(benchmark_rows):
        raise EvaluationBuildError("benchmark alignment mismatch: row counts differ")
    row_keys = tuple(_alignment_key(row) for row in rows)
    benchmark_keys = tuple(_alignment_key(row) for row in benchmark_rows)
    if row_keys != benchmark_keys:
        raise EvaluationBuildError(
            "benchmark alignment mismatch: split/instrument/venue/feature_ts differ"
        )
    row_return = _compounded_return(tuple(row.net_return for row in rows))
    benchmark_return = _compounded_return(tuple(row.net_return for row in benchmark_rows))
    if row_return is None or benchmark_return is None:
        return EvaluationMetric(
            value=None,
            status=MetricStatus.BLOCKED,
            reason="benchmark-relative return unavailable for empty aligned input",
        )
    return EvaluationMetric(
        value=row_return - benchmark_return,
        status=MetricStatus.AVAILABLE,
    )


def _alignment_key(row: BaselineRow) -> tuple[DatasetSplit, str, str, str]:
    return (row.split, row.instrument_id, row.venue_id, row.feature_ts.isoformat())


def _metric(value: Decimal | None, *, reason: str) -> EvaluationMetric:
    if value is None:
        return EvaluationMetric(value=None, status=MetricStatus.NOT_APPLICABLE, reason=reason)
    return EvaluationMetric(value=value, status=MetricStatus.AVAILABLE)


def _sum_tuple(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0"))


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _compounded_return(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    equity = Decimal("1")
    for value in values:
        equity *= Decimal("1") + value
    return equity - Decimal("1")


def _population_std(values: tuple[Decimal, ...]) -> Decimal | None:
    mean = _mean(values)
    if mean is None:
        return None
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(len(values))
    return variance.sqrt()


def _sharpe(values: tuple[Decimal, ...]) -> EvaluationMetric:
    mean = _mean(values)
    if mean is None:
        return EvaluationMetric(
            value=None, status=MetricStatus.NOT_APPLICABLE, reason="empty split"
        )
    std = _population_std(values)
    if std is None or std == 0:
        return EvaluationMetric(
            value=None,
            status=MetricStatus.NOT_APPLICABLE,
            reason="zero volatility makes Sharpe undefined",
        )
    return EvaluationMetric(value=mean / std, status=MetricStatus.AVAILABLE)


def _sortino(values: tuple[Decimal, ...]) -> EvaluationMetric:
    mean = _mean(values)
    if mean is None:
        return EvaluationMetric(
            value=None, status=MetricStatus.NOT_APPLICABLE, reason="empty split"
        )
    downside = tuple(value for value in values if value < 0)
    if not downside:
        return EvaluationMetric(
            value=None,
            status=MetricStatus.NOT_APPLICABLE,
            reason="no downside returns make Sortino undefined",
        )
    downside_std = _population_std(downside)
    if downside_std is None or downside_std == 0:
        return EvaluationMetric(
            value=None,
            status=MetricStatus.NOT_APPLICABLE,
            reason="zero downside volatility makes Sortino undefined",
        )
    return EvaluationMetric(value=mean / downside_std, status=MetricStatus.AVAILABLE)


def _calmar(values: tuple[Decimal, ...]) -> EvaluationMetric:
    net_return = _compounded_return(values)
    if net_return is None:
        return EvaluationMetric(
            value=None, status=MetricStatus.NOT_APPLICABLE, reason="empty split"
        )
    drawdown = _max_drawdown(values)
    if drawdown is None or drawdown == 0:
        return EvaluationMetric(
            value=None,
            status=MetricStatus.NOT_APPLICABLE,
            reason="no drawdown makes Calmar undefined",
        )
    return EvaluationMetric(value=net_return / abs(drawdown), status=MetricStatus.AVAILABLE)


def _max_drawdown(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    equity = Decimal("1")
    peak = Decimal("1")
    max_drawdown = Decimal("0")
    for value in values:
        equity *= Decimal("1") + value
        if equity > peak:
            peak = equity
        drawdown = (equity / peak) - Decimal("1")
        if drawdown < max_drawdown:
            max_drawdown = drawdown
    return max_drawdown


def _cvar(values: tuple[Decimal, ...], tail_probability: Decimal) -> Decimal | None:
    if not values:
        return None
    tail_count = max(1, _ceil_decimal(Decimal(len(values)) * tail_probability))
    tail = tuple(sorted(values)[:tail_count])
    return sum(tail, Decimal("0")) / Decimal(len(tail))


def _ceil_decimal(value: Decimal) -> int:
    integral = int(value)
    if value == integral:
        return integral
    return integral + 1
