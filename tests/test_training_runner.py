"""Evidence for S7-001 reproducible training runner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ta_model.contracts.datasets import (
    ChronologicalSplitWindow,
    DatasetSnapshot,
    DatasetSplit,
    LabelMethod,
    build_dataset_snapshot_id,
    build_label_observation,
    build_label_rule,
)
from ta_model.contracts.features import FeatureValue, FeatureVector, build_feature_vector_id
from ta_model.contracts.training import (
    TrainingArtifactReference,
    TrainingMetric,
    TrainingRunResult,
    build_training_config,
)
from ta_model.datasets.snapshots import build_chronological_dataset_snapshot
from ta_model.training.runner import TrainingRunnerError, run_training

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"
VENUE_ID = "FIXTURE_SPOT"
FEATURE_VERSION = "fixture-pit-1.0.0"
CODE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _feature(index: int, close: str) -> FeatureVector:
    feature_ts = START + timedelta(minutes=index)
    values: dict[str, FeatureValue] = {
        "close": Decimal(close),
        "one_bar_return": Decimal("0.01"),
    }
    input_snapshot_id = f"FEATUREINPUT:S7-001:{index}"
    feature_vector_id = build_feature_vector_id(
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        feature_ts=feature_ts,
        feature_version=FEATURE_VERSION,
        lookback_window="fixture-3-bars",
        values=values,
        input_snapshot_id=input_snapshot_id,
        quality_flags=(),
    )
    return FeatureVector(
        feature_vector_id=feature_vector_id,
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        feature_ts=feature_ts,
        feature_version=FEATURE_VERSION,
        lookback_window="fixture-3-bars",
        values=values,
        input_snapshot_id=input_snapshot_id,
        quality_flags=(),
    )


def _snapshot(
    *, no_train_rows: bool = False, no_test_rows: bool = False, last_close: str = "105"
) -> DatasetSnapshot:
    closes = ("100", "101", "102", "103", "104", last_close)
    features = tuple(_feature(index, close) for index, close in enumerate(closes))
    observations = tuple(
        build_label_observation(
            instrument_id=INSTRUMENT_ID,
            venue_id=VENUE_ID,
            event_ts=START + timedelta(minutes=index),
            value=Decimal(str(100 + index)),
            source_lineage_id=f"LABELSOURCE:S7-001:{index}",
        )
        for index in range(7)
    )
    return build_chronological_dataset_snapshot(
        feature_vectors=features,
        label_observations=observations,
        split_windows=_split_windows(no_train_rows=no_train_rows, no_test_rows=no_test_rows),
        label_rule=build_label_rule(
            name="future_1m", horizon_seconds=60, method=LabelMethod.FUTURE_RETURN
        ),
        source_feature_snapshot_ids=("FEATURESNAPSHOT:S7-001",),
    )


def _split_windows(
    *, no_train_rows: bool = False, no_test_rows: bool = False
) -> tuple[ChronologicalSplitWindow, ...]:
    if no_train_rows:
        return (
            ChronologicalSplitWindow(
                split=DatasetSplit.TRAIN,
                start_ts=START - timedelta(minutes=2),
                end_ts=START - timedelta(minutes=1),
            ),
            ChronologicalSplitWindow(
                split=DatasetSplit.VALIDATION,
                start_ts=START,
                end_ts=START + timedelta(minutes=5),
            ),
            ChronologicalSplitWindow(
                split=DatasetSplit.TEST,
                start_ts=START + timedelta(minutes=5),
                end_ts=START + timedelta(minutes=6),
            ),
        )
    if no_test_rows:
        return (
            ChronologicalSplitWindow(
                split=DatasetSplit.TRAIN,
                start_ts=START,
                end_ts=START + timedelta(minutes=3),
            ),
            ChronologicalSplitWindow(
                split=DatasetSplit.VALIDATION,
                start_ts=START + timedelta(minutes=3),
                end_ts=START + timedelta(minutes=6),
            ),
            ChronologicalSplitWindow(
                split=DatasetSplit.TEST,
                start_ts=START + timedelta(minutes=6),
                end_ts=START + timedelta(minutes=7),
            ),
        )
    return (
        ChronologicalSplitWindow(
            split=DatasetSplit.TRAIN,
            start_ts=START,
            end_ts=START + timedelta(minutes=3),
        ),
        ChronologicalSplitWindow(
            split=DatasetSplit.VALIDATION,
            start_ts=START + timedelta(minutes=3),
            end_ts=START + timedelta(minutes=5),
        ),
        ChronologicalSplitWindow(
            split=DatasetSplit.TEST,
            start_ts=START + timedelta(minutes=5),
            end_ts=START + timedelta(minutes=6),
        ),
    )


def test_training_config_and_run_result_identity_are_deterministic() -> None:
    snapshot = _snapshot()
    config = build_training_config(name="s7-001-reference", seed=7)

    first = run_training(snapshot=snapshot, config=config, code_commit=CODE_COMMIT)
    second = run_training(snapshot=snapshot, config=config, code_commit=CODE_COMMIT)

    assert first.training_run_id == second.training_run_id
    assert first.training_run_hash == second.training_run_hash
    assert first.metrics == second.metrics
    assert first.artifacts == second.artifacts
    assert first.dataset_snapshot_id == snapshot.dataset_snapshot_id
    assert first.dataset_hash == snapshot.dataset_hash
    assert first.seed == config.seed
    assert first.status == "runner_evidence_only"


def test_run_identity_changes_when_seed_config_dataset_or_commit_changes() -> None:
    snapshot = _snapshot()
    config = build_training_config(name="s7-001-reference", seed=7)
    baseline = run_training(snapshot=snapshot, config=config, code_commit=CODE_COMMIT)

    changed_seed = run_training(
        snapshot=snapshot,
        config=build_training_config(name="s7-001-reference", seed=8),
        code_commit=CODE_COMMIT,
    )
    changed_config = run_training(
        snapshot=snapshot,
        config=build_training_config(name="s7-001-reference-v2", seed=7),
        code_commit=CODE_COMMIT,
    )
    changed_dataset = run_training(
        snapshot=_snapshot(last_close="999"), config=config, code_commit=CODE_COMMIT
    )
    changed_commit = run_training(snapshot=snapshot, config=config, code_commit="fedcba9876543210")

    assert baseline.training_run_id != changed_seed.training_run_id
    assert baseline.training_run_id != changed_config.training_run_id
    assert baseline.training_run_id != changed_dataset.training_run_id
    assert baseline.training_run_id != changed_commit.training_run_id


def test_run_result_resolves_required_lineage_and_artifacts() -> None:
    snapshot = _snapshot()
    config = build_training_config(name="s7-001-reference", seed=7)
    result = run_training(snapshot=snapshot, config=config, code_commit=CODE_COMMIT)

    metric_names = {(metric.split, metric.name) for metric in result.metrics}
    assert (DatasetSplit.TRAIN, "train_label_mean") in metric_names
    assert (DatasetSplit.TRAIN, "train_row_count") in metric_names
    assert (DatasetSplit.VALIDATION, "mean_absolute_error_against_train_mean") in metric_names
    assert (DatasetSplit.TEST, "mean_absolute_error_against_train_mean") in metric_names
    assert result.artifacts[0].name == "reference_model"
    assert snapshot.dataset_snapshot_id in result.artifacts[0].uri
    assert config.training_config_id in result.artifacts[0].uri
    assert result.training_config.training_config_hash == config.training_config_hash


def test_runner_fails_closed_for_invalid_prerequisites() -> None:
    config = build_training_config(name="s7-001-reference", seed=7)

    with pytest.raises(TrainingRunnerError, match="at least one train row"):
        run_training(snapshot=_snapshot(no_train_rows=True), config=config, code_commit=CODE_COMMIT)

    with pytest.raises(TrainingRunnerError, match="evaluation split has no rows"):
        run_training(snapshot=_snapshot(no_test_rows=True), config=config, code_commit=CODE_COMMIT)

    with pytest.raises(TrainingRunnerError, match="code_commit is required"):
        run_training(snapshot=_snapshot(), config=config, code_commit=" ")

    with pytest.raises(TrainingRunnerError, match="git SHA-like hex string"):
        run_training(snapshot=_snapshot(), config=config, code_commit="not-a-sha")

    with pytest.raises(TrainingRunnerError, match="git SHA-like hex string"):
        run_training(snapshot=_snapshot(), config=config, code_commit="abcdef")


def test_training_config_rejects_in_sample_evaluation_split() -> None:
    with pytest.raises(ValidationError, match="evaluation_splits must not include train_split"):
        build_training_config(
            name="s7-001-reference",
            seed=7,
            evaluation_splits=(DatasetSplit.TRAIN, DatasetSplit.VALIDATION),
        )


def test_reconstructed_dataset_hash_mismatch_fails_closed() -> None:
    snapshot = _snapshot()
    corrupted_hash = "0" * 64
    corrupted = snapshot.model_copy(
        update={
            "dataset_hash": corrupted_hash,
            "dataset_snapshot_id": build_dataset_snapshot_id(dataset_hash=corrupted_hash),
        }
    )

    with pytest.raises(TrainingRunnerError, match="dataset_hash does not match snapshot contents"):
        run_training(
            snapshot=corrupted,
            config=build_training_config(name="s7-001-reference", seed=7),
            code_commit=CODE_COMMIT,
        )


def test_contracts_reject_invalid_metrics_artifacts_and_run_identity() -> None:
    snapshot = _snapshot()
    config = build_training_config(name="s7-001-reference", seed=7)
    result = run_training(snapshot=snapshot, config=config, code_commit=CODE_COMMIT)

    with pytest.raises(ValidationError, match="finite"):
        TrainingMetric(name="bad", split=DatasetSplit.TRAIN, value=Decimal("NaN"))

    with pytest.raises(ValidationError):
        TrainingArtifactReference(name="bad", uri="artifact://bad", content_hash="not-a-hash")

    with pytest.raises(ValidationError, match="training_run_hash is not deterministic"):
        TrainingRunResult(**(result.model_dump() | {"training_run_hash": "0" * 64}))

    with pytest.raises(ValidationError, match="git SHA-like hex string"):
        TrainingRunResult(**(result.model_dump() | {"code_commit": "12345g7"}))
