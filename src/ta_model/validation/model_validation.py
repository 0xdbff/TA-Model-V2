"""Deterministic S7-004 model validation/gate reporting."""

from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

from ta_model.contracts.datasets import DatasetRow, DatasetSnapshot, DatasetSplit
from ta_model.contracts.forecasts import Forecast, ProbabilisticCandidateOutput
from ta_model.contracts.model_registry import ModelRegistryRecord, ModelRegistryState
from ta_model.contracts.model_validation import (
    BaselineEvidenceReference,
    ModelComparison,
    ModelGateRecommendation,
    ModelMetricSet,
    ModelValidationReport,
    QuantileCoverageMetric,
    RegistryMetadataReference,
    UncertaintySummary,
    build_model_validation_report_hash,
    build_model_validation_report_id,
)

_REQUIREMENT_IDS = ("FR-008", "FR-014", "FR-007", "NFR-005")
_EPSILON = 1e-15


class ModelValidationError(ValueError):
    """Raised when S7 validation evidence must fail closed."""


def build_model_validation_report(
    *,
    snapshot: DatasetSnapshot,
    candidate_output: ProbabilisticCandidateOutput,
    baseline_evidence: BaselineEvidenceReference,
    registry_record: ModelRegistryRecord | None = None,
) -> ModelValidationReport:
    """Evaluate out-of-sample candidate forecasts without promotion side effects."""

    _validate_baseline_evidence_paths(baseline_evidence)
    rows_by_id = _validate_forecast_alignment(snapshot=snapshot, candidate_output=candidate_output)
    train_rows = tuple(row for row in snapshot.rows if row.split is DatasetSplit.TRAIN)
    if not train_rows:
        raise ModelValidationError("train split rows are required for train-prior baseline")

    evaluation_pairs = tuple(
        (forecast, rows_by_id[forecast.dataset_row_id]) for forecast in candidate_output.forecasts
    )
    candidate_metrics = _metrics_for_forecasts(evaluation_pairs)
    train_prior_probabilities = _train_prior_probabilities(train_rows)
    train_prior_quantiles = _train_prior_quantiles(train_rows)
    baseline_metrics = _metrics_for_prior(
        rows_by_id.values(), train_prior_probabilities, train_prior_quantiles
    )
    ablation_metrics = _metrics_for_prior(
        rows_by_id.values(), train_prior_probabilities, train_prior_quantiles
    )
    quantile_coverage = _quantile_coverage(evaluation_pairs)
    uncertainty_summary = _uncertainty_summary(candidate_output.forecasts)

    train_prior_comparison = _comparison(
        name="unconditional_train_prior_no_skill",
        description=(
            "Train-split label prior applied to each OOS forecast row; "
            "validation/test labels are evaluation outcomes only."
        ),
        candidate_metrics=candidate_metrics,
        comparator_metrics=baseline_metrics,
    )
    sequence_ablation = _comparison(
        name="ablated_global_prior_no_sequence",
        description=(
            "Feature/sequence ablation using the same train-only global prior "
            "on the exact evaluated rows."
        ),
        candidate_metrics=candidate_metrics,
        comparator_metrics=ablation_metrics,
    )
    registry_metadata = (
        _registry_metadata(registry_record, candidate_output) if registry_record else None
    )
    recommendation, reasons, caveats = _recommendation(
        candidate_metrics=candidate_metrics,
        baseline=train_prior_comparison,
        ablation=sequence_ablation,
        registry_metadata=registry_metadata,
    )

    evaluated_splits = tuple(
        dict.fromkeys(forecast.split for forecast in candidate_output.forecasts)
    )
    report_hash = build_model_validation_report_hash(
        requirement_ids=_REQUIREMENT_IDS,
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        dataset_hash=snapshot.dataset_hash,
        training_run_id=candidate_output.training_run_id,
        training_run_hash=candidate_output.training_run_hash,
        model_version_id=candidate_output.model_version_id,
        model_version_hash=candidate_output.model_version_hash,
        forecast_output_id=candidate_output.output_id,
        forecast_output_hash=candidate_output.output_hash,
        evaluated_splits=evaluated_splits,
        evaluated_forecast_ids=candidate_output.forecast_ids,
        candidate_metrics=candidate_metrics,
        quantile_coverage=quantile_coverage,
        uncertainty_summary=uncertainty_summary,
        train_prior_baseline=train_prior_comparison,
        sequence_ablation=sequence_ablation,
        baseline_evidence=baseline_evidence,
        registry_metadata=registry_metadata,
        recommendation=recommendation,
        reasons=reasons,
        caveats=caveats,
    )
    return ModelValidationReport(
        report_id=build_model_validation_report_id(report_hash=report_hash),
        report_hash=report_hash,
        requirement_ids=_REQUIREMENT_IDS,
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        dataset_hash=snapshot.dataset_hash,
        training_run_id=candidate_output.training_run_id,
        training_run_hash=candidate_output.training_run_hash,
        model_version_id=candidate_output.model_version_id,
        model_version_hash=candidate_output.model_version_hash,
        forecast_output_id=candidate_output.output_id,
        forecast_output_hash=candidate_output.output_hash,
        evaluated_splits=evaluated_splits,
        evaluated_forecast_ids=candidate_output.forecast_ids,
        candidate_metrics=candidate_metrics,
        quantile_coverage=quantile_coverage,
        uncertainty_summary=uncertainty_summary,
        train_prior_baseline=train_prior_comparison,
        sequence_ablation=sequence_ablation,
        baseline_evidence=baseline_evidence,
        registry_metadata=registry_metadata,
        recommendation=recommendation,
        reasons=reasons,
        caveats=caveats,
    )


def _validate_baseline_evidence_paths(evidence: BaselineEvidenceReference) -> None:
    gate_path = Path(evidence.gate_report_path)
    scorecard_path = Path(evidence.scorecard_report_path)
    missing = [path for path in (gate_path, scorecard_path) if not path.exists()]
    if missing:
        raise ModelValidationError(
            f"fixed S5 baseline evidence is missing: {', '.join(str(path) for path in missing)}"
        )
    gate_text = gate_path.read_text(encoding="utf-8")
    scorecard_text = scorecard_path.read_text(encoding="utf-8")
    if "Decision: PASS" not in gate_text:
        raise ModelValidationError("S5 baseline gate evidence must contain a PASS decision")
    for label, text in (("gate", gate_text), ("scorecard", scorecard_text)):
        if evidence.scorecard_id not in text:
            raise ModelValidationError(f"S5 {label} evidence does not contain scorecard ID")
        if evidence.scorecard_hash not in text:
            raise ModelValidationError(f"S5 {label} evidence does not contain scorecard hash")


def _validate_forecast_alignment(
    *, snapshot: DatasetSnapshot, candidate_output: ProbabilisticCandidateOutput
) -> dict[str, DatasetRow]:
    if candidate_output.dataset_snapshot_id != snapshot.dataset_snapshot_id:
        raise ModelValidationError("forecast output dataset_snapshot_id does not match snapshot")
    if candidate_output.dataset_hash != snapshot.dataset_hash:
        raise ModelValidationError("forecast output dataset_hash does not match snapshot")
    rows_by_id = {row.row_id: row for row in snapshot.rows}
    if len(rows_by_id) != len(snapshot.rows):
        raise ModelValidationError("dataset snapshot contains duplicate row IDs")
    forecast_row_ids = tuple(forecast.dataset_row_id for forecast in candidate_output.forecasts)
    if len(set(forecast_row_ids)) != len(forecast_row_ids):
        raise ModelValidationError("duplicate forecast dataset_row_id values are not allowed")
    forecast_splits = {forecast.split for forecast in candidate_output.forecasts}
    expected_row_ids = {row.row_id for row in snapshot.rows if row.split in forecast_splits}
    if set(forecast_row_ids) != expected_row_ids:
        raise ModelValidationError(
            "forecasts must cover exactly the dataset rows for evaluated splits"
        )
    aligned: dict[str, DatasetRow] = {}
    expected_quantile_levels: tuple[Decimal, ...] | None = None
    for forecast in candidate_output.forecasts:
        quantile_levels = tuple(quantile.level for quantile in forecast.quantiles)
        if expected_quantile_levels is None:
            expected_quantile_levels = quantile_levels
        elif quantile_levels != expected_quantile_levels:
            raise ModelValidationError("all forecasts must use identical quantile levels")
        row = rows_by_id.get(forecast.dataset_row_id)
        if row is None:
            raise ModelValidationError("forecast references an unknown dataset row")
        _validate_forecast_row(forecast, row, snapshot)
        aligned[row.row_id] = row
    return aligned


def _validate_forecast_row(forecast: Forecast, row: DatasetRow, snapshot: DatasetSnapshot) -> None:
    checks = {
        "dataset_snapshot_id": forecast.dataset_snapshot_id == snapshot.dataset_snapshot_id,
        "dataset_hash": forecast.dataset_hash == snapshot.dataset_hash,
        "feature_vector_id": forecast.feature_vector_id == row.feature_vector_id,
        "feature_input_snapshot_id": forecast.feature_input_snapshot_id
        == row.feature_input_snapshot_id,
        "feature_version": forecast.feature_version == row.feature_version,
        "source_feature_snapshot_ids": forecast.source_feature_snapshot_ids
        == row.source_feature_snapshot_ids,
        "feature_ts": forecast.feature_ts == row.feature_ts,
        "split": forecast.split == row.split,
        "instrument_id": forecast.instrument_id == row.instrument_id,
        "venue_id": forecast.venue_id == row.venue_id,
        "label_rule_id": forecast.label_rule_id == row.label_rule_id,
    }
    mismatches = tuple(name for name, ok in checks.items() if not ok)
    if mismatches:
        raise ModelValidationError(f"forecast/dataset alignment mismatch: {', '.join(mismatches)}")
    if forecast.split is DatasetSplit.TRAIN:
        raise ModelValidationError("model validation forecasts must be out-of-sample")


def _metrics_for_forecasts(pairs: tuple[tuple[Forecast, DatasetRow], ...]) -> ModelMetricSet:
    return _metric_set(
        labels=tuple(_class_label(row.label_value) for _, row in pairs),
        probabilities=tuple(forecast.probabilities for forecast, _ in pairs),
    )


def _metrics_for_prior(
    rows: Iterable[DatasetRow],
    probabilities: dict[str, Decimal],
    quantiles: tuple[Decimal, ...],
) -> ModelMetricSet:
    del quantiles  # quantile coverage for comparator is intentionally not claimed in this report.
    row_tuple = tuple(rows)
    return _metric_set(
        labels=tuple(_class_label(row.label_value) for row in row_tuple),
        probabilities=tuple(probabilities for _ in row_tuple),
    )


def _metric_set(
    *, labels: tuple[str, ...], probabilities: tuple[dict[str, Decimal], ...]
) -> ModelMetricSet:
    if not labels:
        raise ModelValidationError("at least one evaluation row is required")
    nll = 0.0
    brier = 0.0
    positive_probabilities: list[float] = []
    positive_outcomes: list[int] = []
    for label, row_probabilities in zip(labels, probabilities, strict=True):
        probability = max(float(row_probabilities[label]), _EPSILON)
        nll += -math.log(probability)
        for class_name in ("negative", "non_negative"):
            target = 1.0 if class_name == label else 0.0
            brier += (float(row_probabilities[class_name]) - target) ** 2
        positive_probabilities.append(float(row_probabilities["non_negative"]))
        positive_outcomes.append(1 if label == "non_negative" else 0)
    count = len(labels)
    return ModelMetricSet(
        observation_count=count,
        nll=_decimal(nll / count),
        brier=_decimal(brier / count),
        calibration_error=_decimal(_ece(positive_probabilities, positive_outcomes)),
    )


def _ece(probabilities: list[float], outcomes: list[int], *, bins: int = 10) -> float:
    total = len(probabilities)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        bucket = [
            i
            for i, probability in enumerate(probabilities)
            if lower <= probability < upper or (index == bins - 1 and probability == 1.0)
        ]
        if not bucket:
            continue
        confidence = sum(probabilities[i] for i in bucket) / len(bucket)
        accuracy = sum(outcomes[i] for i in bucket) / len(bucket)
        error += (len(bucket) / total) * abs(confidence - accuracy)
    return error


def _quantile_coverage(
    pairs: tuple[tuple[Forecast, DatasetRow], ...],
) -> tuple[QuantileCoverageMetric, ...]:
    levels = tuple(quantile.level for quantile in pairs[0][0].quantiles)
    metrics = []
    for level in levels:
        covered = sum(
            1
            for forecast, row in pairs
            for quantile in forecast.quantiles
            if quantile.level == level and row.label_value <= quantile.value
        )
        observed = Decimal(covered) / Decimal(len(pairs))
        metrics.append(
            QuantileCoverageMetric(
                level=level,
                observed_coverage=observed,
                coverage_error=abs(observed - level),
            )
        )
    return tuple(metrics)


def _uncertainty_summary(forecasts: tuple[Forecast, ...]) -> UncertaintySummary:
    values = tuple(forecast.uncertainty for forecast in forecasts)
    return UncertaintySummary(
        mean_uncertainty=sum(values, Decimal("0")) / Decimal(len(values)),
        min_uncertainty=min(values),
        max_uncertainty=max(values),
    )


def _train_prior_probabilities(train_rows: tuple[DatasetRow, ...]) -> dict[str, Decimal]:
    count = Decimal(len(train_rows))
    non_negative = Decimal(sum(1 for row in train_rows if row.label_value >= 0)) / count
    return {"negative": Decimal("1") - non_negative, "non_negative": non_negative}


def _train_prior_quantiles(train_rows: tuple[DatasetRow, ...]) -> tuple[Decimal, ...]:
    ordered = tuple(sorted(row.label_value for row in train_rows))
    return tuple(
        ordered[
            int((Decimal(len(ordered) - 1) * level).to_integral_value(rounding="ROUND_HALF_UP"))
        ]
        for level in (Decimal("0.1"), Decimal("0.5"), Decimal("0.9"))
    )


def _comparison(
    *,
    name: str,
    description: str,
    candidate_metrics: ModelMetricSet,
    comparator_metrics: ModelMetricSet,
) -> ModelComparison:
    return ModelComparison(
        comparator_name=name,
        comparator_description=description,
        metrics=comparator_metrics,
        candidate_nll_delta=candidate_metrics.nll - comparator_metrics.nll,
        candidate_brier_delta=candidate_metrics.brier - comparator_metrics.brier,
        candidate_improved_nll=candidate_metrics.nll < comparator_metrics.nll,
        candidate_improved_brier=candidate_metrics.brier < comparator_metrics.brier,
    )


def _registry_metadata(
    registry_record: ModelRegistryRecord, output: ProbabilisticCandidateOutput
) -> RegistryMetadataReference:
    if registry_record.training_run_id != output.training_run_id:
        raise ModelValidationError("registry record training_run_id does not match forecasts")
    if registry_record.training_run_hash != output.training_run_hash:
        raise ModelValidationError("registry record training_run_hash does not match forecasts")
    if registry_record.dataset_snapshot_id != output.dataset_snapshot_id:
        raise ModelValidationError("registry record dataset_snapshot_id does not match forecasts")
    if registry_record.dataset_hash != output.dataset_hash:
        raise ModelValidationError("registry record dataset_hash does not match forecasts")
    if registry_record.current_state is not ModelRegistryState.CANDIDATE:
        raise ModelValidationError("S7-004 validation expects registry record state=candidate")
    if registry_record.source_model_version_id != output.model_version_id:
        raise ModelValidationError("registry source_model_version_id does not match forecasts")
    if registry_record.source_model_version_hash != output.model_version_hash:
        raise ModelValidationError("registry source_model_version_hash does not match forecasts")
    return RegistryMetadataReference(
        registry_record_id=registry_record.registry_record_id,
        registry_record_hash=registry_record.registry_record_hash,
        model_version_id=registry_record.model_version_id,
        source_model_version_id=registry_record.source_model_version_id,
        source_model_version_hash=registry_record.source_model_version_hash,
        current_state=registry_record.current_state.value,
        auto_promotion_enabled=registry_record.auto_promotion_enabled,
    )


def _recommendation(
    *,
    candidate_metrics: ModelMetricSet,
    baseline: ModelComparison,
    ablation: ModelComparison,
    registry_metadata: RegistryMetadataReference | None,
) -> tuple[ModelGateRecommendation, tuple[str, ...], tuple[str, ...]]:
    del candidate_metrics
    reasons = [
        (
            "Forecast-only metrics are insufficient for promotion; strategy, portfolio, "
            "execution, and risk gates remain unevidenced."
        ),
        (
            "No product-approved S7 pass thresholds were available, so the conservative "
            "gate recommendation is continue_research."
        ),
    ]
    if not (baseline.candidate_improved_nll and baseline.candidate_improved_brier):
        reasons.append(
            "Candidate did not improve both NLL and Brier against the unconditional "
            "train-prior baseline."
        )
    if not (ablation.candidate_improved_nll and ablation.candidate_improved_brier):
        reasons.append(
            "Sequence-conditioned candidate did not improve both NLL and Brier against "
            "the no-sequence ablation."
        )
    if registry_metadata is None:
        reasons.append(
            "Registry metadata was not supplied; validation remains report-only with "
            "no registry state transition."
        )
    caveats = (
        (
            "Forecast-only evidence does not claim strategy, portfolio, paper-trading, "
            "or live-capital outperformance."
        ),
        "Report performs no auto-promotion and does not route orders to paper/live gateways.",
    )
    return ModelGateRecommendation.CONTINUE_RESEARCH, tuple(reasons), caveats


def _class_label(label_value: Decimal) -> str:
    return "non_negative" if label_value >= 0 else "negative"


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 12)))
