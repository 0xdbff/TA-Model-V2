"""Deterministic first probabilistic candidate trainer/scorer for S7-002."""

from __future__ import annotations

from dataclasses import dataclass
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

_CANDIDATE_NAME = "s7-002-sequence-conditioned-candidate-v1"
_BANNED_FEATURE_NAMES = frozenset({"label", "label_value", "future_return", "target"})
_SEQUENCE_FEATURE_NAME = "one_bar_return"
_SEQUENCE_LOOKBACK = 2


@dataclass(frozen=True)
class _DistributionStats:
    probabilities: dict[str, Decimal]
    quantiles: tuple[ForecastQuantile, ...]
    uncertainty: Decimal
    row_count: int


@dataclass(frozen=True)
class _FittedSequenceCandidate:
    global_stats: _DistributionStats
    stats_by_bucket: dict[str, _DistributionStats]


class ProbabilisticCandidateError(ValueError):
    """Raised when candidate training/scoring prerequisites fail closed."""


def train_probabilistic_candidate(
    *,
    snapshot: DatasetSnapshot,
    training_run: TrainingRunResult,
    evaluation_splits: tuple[DatasetSplit, ...] | None = None,
) -> ProbabilisticCandidateOutput:
    """Fit a deterministic train-only sequence candidate and score OOS splits.

    This intentionally small candidate conditions train-label distributions on
    point-in-time feature sequences. Validation/test labels are not read by this
    function; downstream evaluators may consume them later.
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
    _validate_sequence_feature(snapshot.rows)

    train_rows = tuple(row for row in snapshot.rows if row.split is DatasetSplit.TRAIN)
    candidate = _fit_sequence_candidate(rows=snapshot.rows, train_rows=train_rows)
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
            candidate=candidate,
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


def _validate_sequence_feature(rows: tuple[DatasetRow, ...]) -> None:
    for row in rows:
        value = row.feature_values.get(_SEQUENCE_FEATURE_NAME)
        if not isinstance(value, Decimal):
            raise ProbabilisticCandidateError(
                f"sequence feature is required and must be Decimal: {_SEQUENCE_FEATURE_NAME}"
            )


def _fit_sequence_candidate(
    *, rows: tuple[DatasetRow, ...], train_rows: tuple[DatasetRow, ...]
) -> _FittedSequenceCandidate:
    if not train_rows:
        raise ProbabilisticCandidateError("at least one train row is required")
    labels_by_bucket: dict[str, list[Decimal]] = {}
    for row in train_rows:
        bucket = _sequence_bucket(row=row, rows=rows)
        labels_by_bucket.setdefault(bucket, []).append(row.label_value)
    return _FittedSequenceCandidate(
        global_stats=_distribution_stats(tuple(row.label_value for row in train_rows)),
        stats_by_bucket={
            bucket: _distribution_stats(tuple(labels))
            for bucket, labels in sorted(labels_by_bucket.items())
        },
    )


def _distribution_stats(labels: tuple[Decimal, ...]) -> _DistributionStats:
    if not labels:
        raise ProbabilisticCandidateError("at least one fitted label is required")
    count = Decimal(len(labels))
    non_negative_probability = Decimal(sum(1 for label in labels if label >= 0)) / count
    negative_probability = Decimal("1") - non_negative_probability
    mean = sum(labels, Decimal("0")) / count
    variance = sum((label - mean) * (label - mean) for label in labels) / count
    quantiles = tuple(
        ForecastQuantile(level=level, value=_nearest_quantile(labels=labels, level=level))
        for level in (Decimal("0.1"), Decimal("0.5"), Decimal("0.9"))
    )
    return _DistributionStats(
        probabilities={
            "negative": negative_probability,
            "non_negative": non_negative_probability,
        },
        quantiles=quantiles,
        uncertainty=Decimal(str(variance.sqrt())),
        row_count=len(labels),
    )


def _score_row(
    *,
    row: DatasetRow,
    snapshot: DatasetSnapshot,
    training_run: TrainingRunResult,
    model_version_id: str,
    model_version_hash: str,
    candidate: _FittedSequenceCandidate,
) -> Forecast:
    bucket = _sequence_bucket(row=row, rows=snapshot.rows)
    stats = candidate.stats_by_bucket.get(bucket, candidate.global_stats)
    sequence_values = _sequence_values(row=row, rows=snapshot.rows)
    calibration_metadata = {
        "candidate_name": _CANDIDATE_NAME,
        "condition_bucket": bucket,
        "fit_split": DatasetSplit.TRAIN.value,
        "fit_source": "sequence_conditioned_train_labels_only",
        "sequence_feature": _SEQUENCE_FEATURE_NAME,
        "sequence_lookback": str(_SEQUENCE_LOOKBACK),
        "sequence_values": ",".join(str(value) for value in sequence_values),
        "train_bucket_row_count": str(stats.row_count),
        "train_global_row_count": str(candidate.global_stats.row_count),
    }
    forecast_id = build_forecast_id(
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        dataset_hash=snapshot.dataset_hash,
        dataset_row_id=row.row_id,
        split=row.split,
        training_run_id=training_run.training_run_id,
        training_run_hash=training_run.training_run_hash,
        model_version_id=model_version_id,
        model_version_hash=model_version_hash,
        probabilities=stats.probabilities,
        quantiles=stats.quantiles,
        uncertainty=stats.uncertainty,
        calibration_status=CalibrationStatus.SEQUENCE_CONDITIONED_TRAIN_ONLY,
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
        probabilities=stats.probabilities,
        quantiles=stats.quantiles,
        uncertainty=stats.uncertainty,
        calibration_status=CalibrationStatus.SEQUENCE_CONDITIONED_TRAIN_ONLY,
        calibration_metadata=calibration_metadata,
    )


def _nearest_quantile(*, labels: tuple[Decimal, ...], level: Decimal) -> Decimal:
    ordered = tuple(sorted(labels))
    index = int((Decimal(len(ordered) - 1) * level).to_integral_value(rounding="ROUND_HALF_UP"))
    return ordered[index]


def _sequence_bucket(*, row: DatasetRow, rows: tuple[DatasetRow, ...]) -> str:
    score = sum(_sequence_values(row=row, rows=rows), Decimal("0"))
    if score >= Decimal("0"):
        return "sequence_non_negative"
    return "sequence_negative"


def _sequence_values(*, row: DatasetRow, rows: tuple[DatasetRow, ...]) -> tuple[Decimal, ...]:
    eligible_rows = tuple(
        candidate
        for candidate in rows
        if candidate.instrument_id == row.instrument_id
        and candidate.venue_id == row.venue_id
        and candidate.feature_ts <= row.feature_ts
    )
    values: list[Decimal] = []
    for candidate in eligible_rows[-_SEQUENCE_LOOKBACK:]:
        value = candidate.feature_values[_SEQUENCE_FEATURE_NAME]
        if not isinstance(value, Decimal):
            raise ProbabilisticCandidateError("sequence feature must be Decimal")
        values.append(value)
    return tuple(values)
