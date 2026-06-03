"""Aggregate S5 baseline evidence into a fixed-comparator gate decision.

Traceability:
- FR-007: requires the complete S5 baseline set before complex candidates.
- FR-014: requires net, risk, cost, exposure, and benchmark-relative metrics.
- NFR-001/NFR-005: consumes deterministic event-time scorecards without rerouting orders.

Scope: local validation only; no live/paper services, orders, capital, or promotion path.
"""

from __future__ import annotations

from ta_model.contracts.baselines import BaselineKind
from ta_model.contracts.evaluation import (
    BaselineGateDecision,
    BaselineGateStatus,
    BaselineSplitScore,
    EvaluationMetric,
    EvaluationScorecard,
    MetricStatus,
)

REQUIRED_BASELINES: tuple[BaselineKind, ...] = (
    BaselineKind.CASH,
    BaselineKind.BUY_AND_HOLD,
    BaselineKind.EQUAL_WEIGHT_BASKET,
    BaselineKind.TA_HEURISTIC,
    BaselineKind.SIMPLE_ML,
)

REQUIRED_METRIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("net return", "net_return"),
    ("Sharpe", "sharpe"),
    ("Sortino", "sortino"),
    ("Calmar", "calmar"),
    ("max drawdown", "max_drawdown"),
    ("CVaR", "cvar"),
    ("turnover", "turnover_sum"),
    ("exposure", "average_exposure"),
    ("costs", "cost_return_sum"),
    ("benchmark-relative net return", "benchmark_relative_net_return"),
)

REQUIRED_EVIDENCE_MARKERS: tuple[str, ...] = ("S5-001", "S5-002", "S5-003")
_ACCEPTABLE_UNDEFINED_FIELDS = {"sharpe", "sortino", "calmar"}


def validate_s5_baseline_gate(
    scorecard: EvaluationScorecard,
    *,
    evidence_paths: tuple[str, ...],
    caveats: tuple[str, ...] = (
        "S5 costs are proxy baseline-row costs only, not S6 slippage/TCA completeness.",
        "Simple ML train-split metrics are in-sample; validation/test use fixed train parameters.",
    ),
) -> BaselineGateDecision:
    """Validate complete S5 baseline evidence for future fixed-comparator use."""

    blockers: list[str] = []
    _check_required_evidence(evidence_paths=evidence_paths, blockers=blockers)
    scores_by_name = _scores_by_name(scorecard.scores)
    _check_required_baselines(scores_by_name=scores_by_name, blockers=blockers)
    _check_required_metrics(scores=scorecard.scores, blockers=blockers)
    status = BaselineGateStatus.PASS if not blockers else BaselineGateStatus.BLOCKED
    return BaselineGateDecision(
        status=status,
        scorecard_id=scorecard.scorecard_id,
        scorecard_hash=scorecard.scorecard_hash,
        required_baselines=tuple(kind.value for kind in REQUIRED_BASELINES),
        required_metric_families=tuple(name for name, _field in REQUIRED_METRIC_FIELDS),
        evidence_paths=evidence_paths,
        blockers=tuple(blockers),
        caveats=caveats,
    )


def _check_required_evidence(*, evidence_paths: tuple[str, ...], blockers: list[str]) -> None:
    for marker in REQUIRED_EVIDENCE_MARKERS:
        if not any(marker in path for path in evidence_paths):
            blockers.append(f"missing required evidence report {marker}")


def _scores_by_name(
    scores: tuple[BaselineSplitScore, ...],
) -> dict[str, tuple[BaselineSplitScore, ...]]:
    grouped: dict[str, list[BaselineSplitScore]] = {}
    for score in scores:
        grouped.setdefault(score.baseline_name, []).append(score)
    return {name: tuple(items) for name, items in grouped.items()}


def _check_required_baselines(
    *, scores_by_name: dict[str, tuple[BaselineSplitScore, ...]], blockers: list[str]
) -> None:
    for kind in REQUIRED_BASELINES:
        if kind.value not in scores_by_name:
            blockers.append(f"missing required baseline {kind.value}")


def _check_required_metrics(
    *, scores: tuple[BaselineSplitScore, ...], blockers: list[str]
) -> None:
    for score in scores:
        if score.observation_count == 0:
            blockers.append(f"{score.baseline_name}/{score.split.value} has no observations")
        for family, field_name in REQUIRED_METRIC_FIELDS:
            metric = getattr(score, field_name)
            _check_metric(
                score=score,
                family=family,
                field_name=field_name,
                metric=metric,
                blockers=blockers,
            )


def _check_metric(
    *,
    score: BaselineSplitScore,
    family: str,
    field_name: str,
    metric: EvaluationMetric,
    blockers: list[str],
) -> None:
    label = f"{score.baseline_name}/{score.split.value} {family}"
    if metric.status is MetricStatus.BLOCKED:
        blockers.append(f"{label} is blocked: {metric.reason}")
    elif metric.status is MetricStatus.NOT_APPLICABLE:
        if field_name not in _ACCEPTABLE_UNDEFINED_FIELDS:
            blockers.append(f"{label} is missing: {metric.reason}")
        elif metric.reason is None:
            blockers.append(f"{label} is undefined without an explicit reason")
    elif metric.value is None:
        blockers.append(f"{label} is available without a value")
