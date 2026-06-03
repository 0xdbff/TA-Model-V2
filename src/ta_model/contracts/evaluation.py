"""S5 baseline evaluation scorecard contracts.

Traceability:
- FR-014: scorecards expose net strategy, risk, cost, exposure, and benchmark metrics.
- FR-007: inputs are S5 cash, buy-and-hold, TA heuristic, and simple ML baseline reports.
- NFR-001: scorecards consume event-time baseline rows without changing decisions.
- NFR-005: deterministic scorecard IDs/hashes support reproducible reruns.

Scope: local fixture/research evaluation only; no orders, paper/live execution,
leverage, derivatives, shorting, margin, or model promotion path is introduced.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString


class MetricStatus(StrEnum):
    """Explicit metric availability state."""

    AVAILABLE = "available"
    NOT_APPLICABLE = "not_applicable"
    BLOCKED = "blocked"


class BaselineGateStatus(StrEnum):
    """S5 baseline gate acceptance state."""

    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


class EvaluationMetric(ContractModel):
    """One scorecard metric with explicit undefined/blocker handling."""

    value: Decimal | None
    status: MetricStatus
    reason: NonEmptyString | None = None

    @model_validator(mode="after")
    def status_matches_value(self) -> Self:
        if self.status is MetricStatus.AVAILABLE and self.value is None:
            raise ValueError("available metrics require a value")
        if self.status is not MetricStatus.AVAILABLE and self.reason is None:
            raise ValueError("undefined metrics require a reason")
        return self


class BenchmarkConfig(ContractModel):
    """Benchmark selection used for relative net-return metrics."""

    benchmark_report_id: CanonicalId
    benchmark_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    benchmark_name: NonEmptyString
    alignment: NonEmptyString = "split/instrument/venue/feature_ts exact row alignment"


class MetricAssumptions(ContractModel):
    """Deterministic S5 scorecard metric assumptions."""

    net_return_formula: NonEmptyString = "compounded product(1 + per-row net_return) - 1"
    mean_return_formula: NonEmptyString = "arithmetic mean of per-row net_return observations"
    volatility_formula: NonEmptyString = "population standard deviation; not annualized"
    sharpe_formula: NonEmptyString = (
        "mean net return / population stddev; risk-free rate 0; not annualized"
    )
    sortino_formula: NonEmptyString = (
        "mean net return / downside population stddev of negative returns; not annualized"
    )
    calmar_formula: NonEmptyString = "compounded net return / abs(max_drawdown); not annualized"
    max_drawdown_formula: NonEmptyString = "minimum equity/peak - 1 over compounded net-return path"
    cvar_formula: NonEmptyString = (
        "average lower-tail per-row net returns using ceil(n * tail_probability) observations"
    )
    cvar_tail_probability: Decimal = Field(
        default=Decimal("0.05"), gt=Decimal("0"), le=Decimal("1")
    )
    cost_scope: NonEmptyString = (
        "S5 proxy cost_return from baseline rows; no S6 slippage/TCA completeness claim"
    )


class BaselineSplitScore(ContractModel):
    """Metrics for one baseline report and chronological split/window."""

    baseline_report_id: CanonicalId
    baseline_name: NonEmptyString
    split: DatasetSplit
    observation_count: int = Field(ge=0)
    net_return: EvaluationMetric
    mean_net_return: EvaluationMetric
    sharpe: EvaluationMetric
    sortino: EvaluationMetric
    calmar: EvaluationMetric
    max_drawdown: EvaluationMetric
    cvar: EvaluationMetric
    turnover_sum: EvaluationMetric
    average_exposure: EvaluationMetric
    cost_return_sum: EvaluationMetric
    benchmark_relative_net_return: EvaluationMetric


class EvaluationScorecard(ContractModel):
    """Deterministic S5 baseline evaluation artifact."""

    scorecard_id: CanonicalId
    scorecard_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_baseline_report_ids: tuple[CanonicalId, ...]
    input_baseline_report_hashes: tuple[str, ...]
    benchmark_config: BenchmarkConfig
    metric_assumptions: MetricAssumptions
    scores: tuple[BaselineSplitScore, ...]

    @model_validator(mode="after")
    def scorecard_identity_is_deterministic(self) -> Self:
        expected_hash = build_scorecard_hash(
            input_baseline_report_ids=self.input_baseline_report_ids,
            input_baseline_report_hashes=self.input_baseline_report_hashes,
            benchmark_config=self.benchmark_config,
            metric_assumptions=self.metric_assumptions,
            scores=self.scores,
        )
        if self.scorecard_hash != expected_hash:
            raise ValueError("scorecard_hash is not deterministic")
        if self.scorecard_id != build_scorecard_id(scorecard_hash=self.scorecard_hash):
            raise ValueError("scorecard_id is not deterministic")
        return self


class BaselineGateDecision(ContractModel):
    """Aggregated S5 baseline-gate decision for fixed-comparator readiness."""

    status: BaselineGateStatus
    scorecard_id: CanonicalId
    scorecard_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    required_baselines: tuple[NonEmptyString, ...]
    required_metric_families: tuple[NonEmptyString, ...]
    evidence_paths: tuple[NonEmptyString, ...]
    blockers: tuple[NonEmptyString, ...] = ()
    caveats: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def status_matches_blockers(self) -> Self:
        if self.status is BaselineGateStatus.PASS and self.blockers:
            raise ValueError("passing baseline gates cannot include blockers")
        if self.status is not BaselineGateStatus.PASS and not self.blockers:
            raise ValueError("non-passing baseline gates require blockers")
        return self


def build_scorecard_hash(
    *,
    input_baseline_report_ids: tuple[str, ...],
    input_baseline_report_hashes: tuple[str, ...],
    benchmark_config: BenchmarkConfig,
    metric_assumptions: MetricAssumptions,
    scores: tuple[BaselineSplitScore, ...],
) -> str:
    return _hash(
        {
            "benchmark_config": _model_json(benchmark_config),
            "input_baseline_report_hashes": input_baseline_report_hashes,
            "input_baseline_report_ids": input_baseline_report_ids,
            "metric_assumptions": _model_json(metric_assumptions),
            "scores": tuple(_model_json(score) for score in scores),
        }
    )


def build_scorecard_id(*, scorecard_hash: str) -> str:
    return _stable_id("EVALSCORECARD", {"scorecard_hash": scorecard_hash})


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())
