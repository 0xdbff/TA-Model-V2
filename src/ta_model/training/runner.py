"""Deterministic S7-001 training-run foundation."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from ta_model.contracts.datasets import (
    DatasetRow,
    DatasetSnapshot,
    build_dataset_hash,
    build_dataset_snapshot_id,
)
from ta_model.contracts.training import (
    TrainerKind,
    TrainingArtifactReference,
    TrainingConfig,
    TrainingMetric,
    TrainingRunResult,
    TrainingRunStatus,
    build_training_artifact_reference,
    build_training_run_hash,
    build_training_run_id,
)


class TrainingRunnerError(ValueError):
    """Raised when training prerequisites fail closed."""


def run_training(
    *, snapshot: DatasetSnapshot, config: TrainingConfig, code_commit: str
) -> TrainingRunResult:
    """Run deterministic runner evidence over an existing DatasetSnapshot.

    The S7-001 reference trainer intentionally uses only train-split labels to produce
    a reproducibility artifact. It is not the S7-002 probabilistic candidate and is
    explicitly marked as non-promotable runner evidence.
    """

    _validate_prerequisites(snapshot=snapshot, config=config, code_commit=code_commit)
    if config.trainer_kind is not TrainerKind.REFERENCE_MEAN_LABEL:
        raise TrainingRunnerError(f"unsupported trainer_kind: {config.trainer_kind}")

    train_rows = tuple(row for row in snapshot.rows if row.split is config.train_split)
    label_mean = _mean(row.label_value for row in train_rows)
    metrics = _build_metrics(snapshot=snapshot, config=config, train_label_mean=label_mean)
    artifacts = _build_artifacts(snapshot=snapshot, config=config, label_mean=label_mean)
    run_hash = build_training_run_hash(
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        dataset_hash=snapshot.dataset_hash,
        training_config=config,
        code_commit=code_commit,
        seed=config.seed,
        status=TrainingRunStatus.RUNNER_EVIDENCE_ONLY,
        metrics=metrics,
        artifacts=artifacts,
    )
    return TrainingRunResult(
        training_run_id=build_training_run_id(training_run_hash=run_hash),
        training_run_hash=run_hash,
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        dataset_hash=snapshot.dataset_hash,
        training_config=config,
        code_commit=code_commit,
        seed=config.seed,
        status=TrainingRunStatus.RUNNER_EVIDENCE_ONLY,
        metrics=metrics,
        artifacts=artifacts,
    )


def _validate_prerequisites(
    *, snapshot: DatasetSnapshot, config: TrainingConfig, code_commit: str
) -> None:
    if not code_commit.strip():
        raise TrainingRunnerError("code_commit is required")
    expected_snapshot_id = build_dataset_snapshot_id(dataset_hash=snapshot.dataset_hash)
    if snapshot.dataset_snapshot_id != expected_snapshot_id:
        raise TrainingRunnerError("dataset_snapshot_id does not match dataset_hash")
    expected_hash = build_dataset_hash(
        rows=snapshot.rows,
        split_windows=snapshot.split_windows,
        label_rule=snapshot.label_rule,
        source_feature_snapshot_ids=snapshot.source_feature_snapshot_ids,
    )
    if snapshot.dataset_hash != expected_hash:
        raise TrainingRunnerError("dataset_hash does not match snapshot contents")
    if not snapshot.rows:
        raise TrainingRunnerError("at least one dataset row is required")
    if not any(row.split is config.train_split for row in snapshot.rows):
        raise TrainingRunnerError("at least one train row is required")
    _validate_row_order(snapshot.rows)


def _validate_row_order(rows: tuple[DatasetRow, ...]) -> None:
    previous_ts = None
    seen_ids: set[str] = set()
    for row in rows:
        if row.row_id in seen_ids:
            raise TrainingRunnerError("duplicate dataset row_id")
        seen_ids.add(row.row_id)
        if previous_ts is not None and row.feature_ts < previous_ts:
            raise TrainingRunnerError("dataset rows must be chronological by feature_ts")
        if row.label_ts <= row.feature_ts:
            raise TrainingRunnerError("label_ts must be after feature_ts")
        previous_ts = row.feature_ts


def _build_metrics(
    *, snapshot: DatasetSnapshot, config: TrainingConfig, train_label_mean: Decimal
) -> tuple[TrainingMetric, ...]:
    metrics = [
        TrainingMetric(
            name="train_label_mean",
            split=config.train_split,
            value=train_label_mean,
        ),
        TrainingMetric(
            name="train_row_count",
            split=config.train_split,
            value=Decimal(snapshot.row_counts_by_split[config.train_split]),
        ),
    ]
    for split in config.evaluation_splits:
        split_rows = tuple(row for row in snapshot.rows if row.split is split)
        if not split_rows:
            raise TrainingRunnerError(f"evaluation split has no rows: {split.value}")
        metrics.append(
            TrainingMetric(
                name="mean_absolute_error_against_train_mean",
                split=split,
                value=_mean(abs(row.label_value - train_label_mean) for row in split_rows),
            )
        )
        metrics.append(
            TrainingMetric(
                name="evaluation_row_count",
                split=split,
                value=Decimal(len(split_rows)),
            )
        )
    return tuple(metrics)


def _build_artifacts(
    *, snapshot: DatasetSnapshot, config: TrainingConfig, label_mean: Decimal
) -> tuple[TrainingArtifactReference, ...]:
    payload = {
        "dataset_hash": snapshot.dataset_hash,
        "dataset_snapshot_id": snapshot.dataset_snapshot_id,
        "runner_scope": "S7-001 reproducibility evidence only; not a probabilistic candidate",
        "seed": config.seed,
        "train_label_mean": str(label_mean),
        "trainer_kind": config.trainer_kind.value,
        "training_config_id": config.training_config_id,
    }
    uri = "/".join(
        (
            "artifact://s7-001-training-runner",
            snapshot.dataset_snapshot_id,
            config.training_config_id,
            str(config.seed),
            "reference_model.json",
        )
    )
    return (build_training_artifact_reference(name="reference_model", uri=uri, payload=payload),)


def _mean(values: Iterable[Decimal]) -> Decimal:
    decimal_values = tuple(values)
    if not decimal_values:
        raise TrainingRunnerError("cannot compute mean of empty values")
    return sum(decimal_values, Decimal("0")) / Decimal(len(decimal_values))
