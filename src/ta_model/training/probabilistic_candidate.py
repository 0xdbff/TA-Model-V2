"""Deterministic first probabilistic candidate trainer/scorer for S7-002."""

from __future__ import annotations

from decimal import Decimal

from ta_model.contracts.datasets import DatasetRow, DatasetSnapshot, DatasetSplit
from ta_model.contracts.forecasts import (
    CalibrationStatus,
    Forecast,
    ForecastQuantile,
    ProbabilisticCandidateOutput,
    build_forecast_id,
    build_model_version_hash,
    build_model_version_id,
    build_probabilistic_output_hash,
    build_probabilistic_output_id,
)
from ta_model.contracts.training import TrainingRunResult
from ta_model.training.runner import TrainingRunnerError, _validate_prerequisites

_CANDIDATE_NAME = "s7-002-train-prior-sequence-candidate-v1"
_BANNED_FEATURE_NAMES = frozenset({"label", "label_value", "future_return", "target"})


class ProbabilisticCandidateError(ValueError):
    """Raised when candidate training/scoring prerequisites fail closed."""


def train_probabilistic_candidate(
    *,
    snapshot: DatasetSnapshot,
    training_run: TrainingRunResult,
    evaluation_splits: tuple[DatasetSplit, ...] | None = None,
) -> ProbabilisticCandidateOutput:
    """Fit a deterministic train-only prior and score configured OOS splits.

    This intentionally small candidate uses only train-split labels for fitted
    distribution parameters. Validation/test labels are not read by this function;
    downstream S7-004/S7-005 style evaluators may consume them later.
    """

    try:
        _validate_prerequisites(
            snapshot=snapshot,
            config=training_run.training_config,
            code_commit=training_run.code_commit,
        )
    except TrainingRunnerError as exc:
        raise ProbabilisticCandidateError(str(exc)) from exc
    _validate_training_run_lineage(snapshot=snapshot, training_run=training_run)
    splits = evaluation_splits or training_run.training_config.evaluation_splits
    if not splits:
        raise ProbabilisticCandidateError("at least one evaluation split is required")
    if DatasetSplit.TRAIN in splits:
        raise ProbabilisticCandidateError("probabilistic forecasts must be out-of-sample")
    if len(set(splits)) != len(splits):
        raise ProbabilisticCandidateError("evaluation_splits must be unique")
    _reject_label_like_features(snapshot.rows)

    train_rows = tuple(row for row in snapshot.rows if row.split is DatasetSplit.TRAIN)
    parameters = _fit_train_prior(train_rows)
    model_version_hash = build_model_version_hash(
        training_run_id=training_run.training_run_id,
        training_run_hash=training_run.training_run_hash,
        candidate_name=_CANDIDATE_NAME,
    )
    model_version_id = build_model_version_id(model_version_hash=model_version_hash)
    forecasts = tuple(
        _score_row(
            row=row,
            snapshot=snapshot,
            training_run=training_run,
            model_version_id=model_version_id,
            model_version_hash=model_version_hash,
            parameters=parameters,
        )
        for row in snapshot.rows
        if row.split in splits
    )
    if not forecasts:
        raise ProbabilisticCandidateError("evaluation split has no rows")
    output_hash = build_probabilistic_output_hash(
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        dataset_hash=snapshot.dataset_hash,
        training_run_id=training_run.training_run_id,
        training_run_hash=training_run.training_run_hash,
        model_version_id=model_version_id,
        model_version_hash=model_version_hash,
        forecasts=forecasts,
    )
    return ProbabilisticCandidateOutput(
        output_id=build_probabilistic_output_id(output_hash=output_hash),
        output_hash=output_hash,
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        dataset_hash=snapshot.dataset_hash,
        training_run_id=training_run.training_run_id,
        training_run_hash=training_run.training_run_hash,
        model_version_id=model_version_id,
        model_version_hash=model_version_hash,
        forecast_ids=tuple(forecast.forecast_id for forecast in forecasts),
        forecasts=forecasts,
    )


def _validate_training_run_lineage(
    *, snapshot: DatasetSnapshot, training_run: TrainingRunResult
) -> None:
    if training_run.dataset_snapshot_id != snapshot.dataset_snapshot_id:
        raise ProbabilisticCandidateError("training_run dataset_snapshot_id must match snapshot")
    if training_run.dataset_hash != snapshot.dataset_hash:
        raise ProbabilisticCandidateError("training_run dataset_hash must match snapshot")


def _reject_label_like_features(rows: tuple[DatasetRow, ...]) -> None:
    for row in rows:
        names = {name.strip().lower() for name in row.feature_values}
        if names & _BANNED_FEATURE_NAMES:
            raise ProbabilisticCandidateError("label-like feature names are not allowed")


def _fit_train_prior(
    rows: tuple[DatasetRow, ...],
) -> dict[str, Decimal | tuple[ForecastQuantile, ...]]:
    labels = tuple(row.label_value for row in rows)
    if not labels:
        raise ProbabilisticCandidateError("at least one train row is required")
    count = Decimal(len(labels))
    non_negative_probability = Decimal(sum(1 for label in labels if label >= 0)) / count
    negative_probability = Decimal("1") - non_negative_probability
    mean = sum(labels, Decimal("0")) / count
    variance = sum((label - mean) * (label - mean) for label in labels) / count
    quantiles = tuple(
        ForecastQuantile(level=level, value=_nearest_quantile(labels=labels, level=level))
        for level in (Decimal("0.1"), Decimal("0.5"), Decimal("0.9"))
    )
    return {
        "negative_probability": negative_probability,
        "non_negative_probability": non_negative_probability,
        "quantiles": quantiles,
        "uncertainty": Decimal(str(variance.sqrt())),
        "train_row_count": count,
    }


def _score_row(
    *,
    row: DatasetRow,
    snapshot: DatasetSnapshot,
    training_run: TrainingRunResult,
    model_version_id: str,
    model_version_hash: str,
    parameters: dict[str, Decimal | tuple[ForecastQuantile, ...]],
) -> Forecast:
    probabilities = {
        "negative": _as_decimal(parameters["negative_probability"]),
        "non_negative": _as_decimal(parameters["non_negative_probability"]),
    }
    quantiles = _as_quantiles(parameters["quantiles"])
    uncertainty = _as_decimal(parameters["uncertainty"])
    calibration_metadata = {
        "candidate_name": _CANDIDATE_NAME,
        "fit_split": DatasetSplit.TRAIN.value,
        "fit_source": "train_labels_only",
        "train_row_count": str(_as_decimal(parameters["train_row_count"])),
    }
    forecast_id = build_forecast_id(
        dataset_row_id=row.row_id,
        split=row.split,
        training_run_id=training_run.training_run_id,
        model_version_id=model_version_id,
        probabilities=probabilities,
        quantiles=quantiles,
        uncertainty=uncertainty,
        calibration_status=CalibrationStatus.TRAIN_PRIOR_ONLY,
        calibration_metadata=calibration_metadata,
    )
    return Forecast(
        forecast_id=forecast_id,
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        dataset_hash=snapshot.dataset_hash,
        dataset_row_id=row.row_id,
        feature_vector_id=row.feature_vector_id,
        feature_input_snapshot_id=row.feature_input_snapshot_id,
        feature_version=row.feature_version,
        source_feature_snapshot_ids=row.source_feature_snapshot_ids,
        instrument_id=row.instrument_id,
        venue_id=row.venue_id,
        feature_ts=row.feature_ts,
        label_rule_id=row.label_rule_id,
        split=row.split,
        training_run_id=training_run.training_run_id,
        training_run_hash=training_run.training_run_hash,
        model_version_id=model_version_id,
        model_version_hash=model_version_hash,
        probabilities=probabilities,
        quantiles=quantiles,
        uncertainty=uncertainty,
        calibration_status=CalibrationStatus.TRAIN_PRIOR_ONLY,
        calibration_metadata=calibration_metadata,
    )


def _nearest_quantile(*, labels: tuple[Decimal, ...], level: Decimal) -> Decimal:
    ordered = tuple(sorted(labels))
    index = int((Decimal(len(ordered) - 1) * level).to_integral_value(rounding="ROUND_HALF_UP"))
    return ordered[index]


def _as_decimal(value: Decimal | tuple[ForecastQuantile, ...]) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("expected Decimal fitted parameter")
    return value


def _as_quantiles(value: Decimal | tuple[ForecastQuantile, ...]) -> tuple[ForecastQuantile, ...]:
    if isinstance(value, Decimal):
        raise TypeError("expected quantile fitted parameter")
    return value
