"""S7 model validation/gate evidence contracts.

Traceability:
- FR-008: evaluates governed model candidate lineage from training/forecast/registry artifacts.
- FR-014: records probabilistic metrics, calibration, uncertainty, and quantile evidence.
- FR-007: keeps fixed S5 baseline-comparator evidence explicit before model gate review.
- NFR-005: deterministic validation report IDs/hashes support reproducible gate evidence.

Scope:
- S7-004 validation/reporting only. No model promotion, registry transitions,
  serving, paper/live routing, leverage, derivatives, online self-update, or live capital.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString


class ModelGateRecommendation(StrEnum):
    """Honest forecast-only model gate recommendation."""

    PASS = "pass"
    FAIL = "fail"
    CONTINUE_RESEARCH = "continue_research"
    BLOCKED = "blocked"


class ModelMetricSet(ContractModel):
    """Core probabilistic metrics over one evaluated forecast set."""

    observation_count: int = Field(gt=0)
    nll: Decimal
    brier: Decimal
    calibration_error: Decimal = Field(ge=Decimal("0"))

    @field_validator("nll", "brier", "calibration_error")
    @classmethod
    def metric_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("model metrics must be finite")
        return value


class QuantileCoverageMetric(ContractModel):
    """Observed coverage for one predicted quantile level."""

    level: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"))
    observed_coverage: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    coverage_error: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))

    @model_validator(mode="after")
    def coverage_error_matches_level(self) -> Self:
        if self.coverage_error != abs(self.observed_coverage - self.level):
            raise ValueError("coverage_error must equal abs(observed_coverage - level)")
        return self


class UncertaintySummary(ContractModel):
    """Summary of candidate uncertainty values across evaluated forecasts."""

    mean_uncertainty: Decimal = Field(ge=Decimal("0"))
    min_uncertainty: Decimal = Field(ge=Decimal("0"))
    max_uncertainty: Decimal = Field(ge=Decimal("0"))

    @model_validator(mode="after")
    def uncertainty_range_is_valid(self) -> Self:
        if (
            self.min_uncertainty > self.mean_uncertainty
            or self.mean_uncertainty > self.max_uncertainty
        ):
            raise ValueError("uncertainty summary must satisfy min <= mean <= max")
        return self


class BaselineEvidenceReference(ContractModel):
    """Fixed S5 baseline evidence required before S7 model gate review."""

    scorecard_id: CanonicalId
    gate_report_path: NonEmptyString
    scorecard_report_path: NonEmptyString
    baseline_gate_status: Literal["PASS"] = "PASS"


class ModelComparison(ContractModel):
    """Candidate-vs-comparator probabilistic metric comparison."""

    comparator_name: NonEmptyString
    comparator_description: NonEmptyString
    metrics: ModelMetricSet
    candidate_nll_delta: Decimal
    candidate_brier_delta: Decimal
    candidate_improved_nll: bool
    candidate_improved_brier: bool


class RegistryMetadataReference(ContractModel):
    """Read-only registry metadata consumed by the validation report."""

    registry_record_id: CanonicalId
    registry_record_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_version_id: CanonicalId
    current_state: NonEmptyString
    auto_promotion_enabled: Literal[False] = False


class ModelValidationReport(ContractModel):
    """Deterministic S7-004 forecast-only validation report."""

    report_id: CanonicalId
    report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    requirement_ids: tuple[NonEmptyString, ...]
    dataset_snapshot_id: CanonicalId
    dataset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_run_id: CanonicalId
    training_run_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_version_id: CanonicalId
    model_version_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    forecast_output_id: CanonicalId
    forecast_output_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluated_splits: tuple[DatasetSplit, ...]
    evaluated_forecast_ids: tuple[CanonicalId, ...]
    candidate_metrics: ModelMetricSet
    quantile_coverage: tuple[QuantileCoverageMetric, ...]
    uncertainty_summary: UncertaintySummary
    train_prior_baseline: ModelComparison
    sequence_ablation: ModelComparison
    baseline_evidence: BaselineEvidenceReference
    registry_metadata: RegistryMetadataReference | None = None
    recommendation: ModelGateRecommendation
    reasons: tuple[NonEmptyString, ...]
    caveats: tuple[NonEmptyString, ...]
    no_auto_promotion: Literal[True] = True

    @model_validator(mode="after")
    def report_identity_is_deterministic(self) -> Self:
        if not self.evaluated_splits:
            raise ValueError("model validation reports require evaluated_splits")
        if not self.evaluated_forecast_ids:
            raise ValueError("model validation reports require forecast IDs")
        if self.recommendation is ModelGateRecommendation.PASS:
            if any("forecast-only" in caveat.lower() for caveat in self.caveats):
                raise ValueError("forecast-only reports cannot be pass recommendations")
        if self.recommendation is not ModelGateRecommendation.PASS and not self.reasons:
            raise ValueError("non-pass recommendations require reasons")
        expected_hash = build_model_validation_report_hash(
            requirement_ids=self.requirement_ids,
            dataset_snapshot_id=self.dataset_snapshot_id,
            dataset_hash=self.dataset_hash,
            training_run_id=self.training_run_id,
            training_run_hash=self.training_run_hash,
            model_version_id=self.model_version_id,
            model_version_hash=self.model_version_hash,
            forecast_output_id=self.forecast_output_id,
            forecast_output_hash=self.forecast_output_hash,
            evaluated_splits=self.evaluated_splits,
            evaluated_forecast_ids=self.evaluated_forecast_ids,
            candidate_metrics=self.candidate_metrics,
            quantile_coverage=self.quantile_coverage,
            uncertainty_summary=self.uncertainty_summary,
            train_prior_baseline=self.train_prior_baseline,
            sequence_ablation=self.sequence_ablation,
            baseline_evidence=self.baseline_evidence,
            registry_metadata=self.registry_metadata,
            recommendation=self.recommendation,
            reasons=self.reasons,
            caveats=self.caveats,
        )
        if self.report_hash != expected_hash:
            raise ValueError("report_hash is not deterministic")
        if self.report_id != build_model_validation_report_id(report_hash=expected_hash):
            raise ValueError("report_id is not deterministic")
        return self


def build_model_validation_report_hash(
    *,
    requirement_ids: tuple[str, ...],
    dataset_snapshot_id: str,
    dataset_hash: str,
    training_run_id: str,
    training_run_hash: str,
    model_version_id: str,
    model_version_hash: str,
    forecast_output_id: str,
    forecast_output_hash: str,
    evaluated_splits: tuple[DatasetSplit, ...],
    evaluated_forecast_ids: tuple[str, ...],
    candidate_metrics: ModelMetricSet,
    quantile_coverage: tuple[QuantileCoverageMetric, ...],
    uncertainty_summary: UncertaintySummary,
    train_prior_baseline: ModelComparison,
    sequence_ablation: ModelComparison,
    baseline_evidence: BaselineEvidenceReference,
    registry_metadata: RegistryMetadataReference | None,
    recommendation: ModelGateRecommendation,
    reasons: tuple[str, ...],
    caveats: tuple[str, ...],
) -> str:
    return _hash(
        {
            "baseline_evidence": _model_json(baseline_evidence),
            "candidate_metrics": _model_json(candidate_metrics),
            "caveats": caveats,
            "dataset_hash": dataset_hash,
            "dataset_snapshot_id": dataset_snapshot_id,
            "evaluated_forecast_ids": evaluated_forecast_ids,
            "evaluated_splits": tuple(split.value for split in evaluated_splits),
            "forecast_output_hash": forecast_output_hash,
            "forecast_output_id": forecast_output_id,
            "model_version_hash": model_version_hash,
            "model_version_id": model_version_id,
            "quantile_coverage": tuple(_model_json(metric) for metric in quantile_coverage),
            "reasons": reasons,
            "recommendation": recommendation.value,
            "registry_metadata": _model_json(registry_metadata) if registry_metadata else None,
            "requirement_ids": requirement_ids,
            "scope": "s7-004-forecast-only-model-validation-report",
            "sequence_ablation": _model_json(sequence_ablation),
            "train_prior_baseline": _model_json(train_prior_baseline),
            "training_run_hash": training_run_hash,
            "training_run_id": training_run_id,
            "uncertainty_summary": _model_json(uncertainty_summary),
        }
    )


def build_model_validation_report_id(*, report_hash: str) -> str:
    return _stable_id("MODELVALIDATION", {"report_hash": report_hash})


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel | None) -> object:
    if model is None:
        return None
    return json.loads(model.model_dump_json())
