"""Evidence for S4-003 chronological dataset snapshot builder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ta_model.contracts.datasets import (
    ChronologicalSplitWindow,
    DatasetSplit,
    LabelMethod,
    LabelObservation,
    LabelRule,
    build_label_observation,
    build_label_rule,
)
from ta_model.contracts.features import FeatureValue, FeatureVector, build_feature_vector_id
from ta_model.datasets.snapshots import (
    DatasetSnapshotBuilderError,
    build_chronological_dataset_snapshot,
)

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"
VENUE_ID = "FIXTURE_SPOT"
FEATURE_VERSION = "fixture-pit-1.0.0"
SOURCE_FEATURE_SNAPSHOT_ID = "FEATURESNAPSHOT:S4-003"


def _feature(index: int, close: str) -> FeatureVector:
    feature_ts = START + timedelta(minutes=index)
    values: dict[str, FeatureValue] = {"close": Decimal(close), "one_bar_return": Decimal("0.01")}
    input_snapshot_id = f"FEATUREINPUT:S4-003:{index}"
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


def _features() -> tuple[FeatureVector, ...]:
    closes = ("100", "101", "102", "103", "104", "105")
    return tuple(_feature(index, close) for index, close in enumerate(closes))


def _observations(
    values: tuple[str, ...] = ("100", "101", "102", "103", "104", "105", "106"),
) -> tuple[LabelObservation, ...]:
    return tuple(
        build_label_observation(
            instrument_id=INSTRUMENT_ID,
            venue_id=VENUE_ID,
            event_ts=START + timedelta(minutes=index),
            value=Decimal(value),
            source_lineage_id=f"LABELSOURCE:S4-003:{index}",
        )
        for index, value in enumerate(values)
    )


def _split_windows() -> tuple[ChronologicalSplitWindow, ...]:
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


def _label_rule(method: LabelMethod = LabelMethod.FUTURE_VALUE) -> LabelRule:
    return build_label_rule(name="future_1m", horizon_seconds=60, method=method)


def test_snapshot_hash_row_ids_versions_and_split_counts_are_deterministic() -> None:
    first = build_chronological_dataset_snapshot(
        feature_vectors=_features(),
        label_observations=_observations(),
        split_windows=_split_windows(),
        label_rule=_label_rule(),
        source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
    )
    second = build_chronological_dataset_snapshot(
        feature_vectors=_features(),
        label_observations=_observations(),
        split_windows=_split_windows(),
        label_rule=_label_rule(),
        source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
    )

    assert first.dataset_snapshot_id == second.dataset_snapshot_id
    assert first.dataset_hash == second.dataset_hash
    assert first.row_ids == second.row_ids
    assert first.feature_versions == (FEATURE_VERSION,)
    assert first.source_feature_snapshot_ids == (SOURCE_FEATURE_SNAPSHOT_ID,)
    assert first.row_counts_by_split == {
        DatasetSplit.TRAIN: 3,
        DatasetSplit.VALIDATION: 2,
        DatasetSplit.TEST: 1,
    }


def test_labels_are_strictly_after_feature_ts_and_split_uses_feature_ts() -> None:
    snapshot = build_chronological_dataset_snapshot(
        feature_vectors=_features(),
        label_observations=_observations(),
        split_windows=_split_windows(),
        label_rule=_label_rule(),
    )

    assert all(row.label_ts > row.feature_ts for row in snapshot.rows)
    assert snapshot.rows[2].feature_ts == START + timedelta(minutes=2)
    assert snapshot.rows[2].label_ts == START + timedelta(minutes=3)
    assert snapshot.rows[2].split is DatasetSplit.TRAIN
    assert snapshot.rows[3].split is DatasetSplit.VALIDATION
    assert snapshot.rows[5].split is DatasetSplit.TEST


def test_missing_or_ambiguous_labels_fail_closed() -> None:
    with pytest.raises(DatasetSnapshotBuilderError, match="missing label"):
        build_chronological_dataset_snapshot(
            feature_vectors=_features(),
            label_observations=_observations()[:-1],
            split_windows=_split_windows(),
            label_rule=_label_rule(),
        )

    duplicate = _observations()[:2] + (_observations()[1],) + _observations()[2:]
    with pytest.raises(DatasetSnapshotBuilderError, match="duplicate label event_ts"):
        build_chronological_dataset_snapshot(
            feature_vectors=_features(),
            label_observations=duplicate,
            split_windows=_split_windows(),
            label_rule=_label_rule(),
        )


def test_duplicate_or_non_monotonic_feature_and_label_event_times_fail_closed() -> None:
    features = _features()
    with pytest.raises(DatasetSnapshotBuilderError, match="duplicate feature_vector_id"):
        build_chronological_dataset_snapshot(
            feature_vectors=(features[0], features[0]),
            label_observations=_observations(),
            split_windows=_split_windows(),
            label_rule=_label_rule(),
        )

    with pytest.raises(DatasetSnapshotBuilderError, match="feature_ts must be strictly increasing"):
        build_chronological_dataset_snapshot(
            feature_vectors=tuple(reversed(features)),
            label_observations=_observations(),
            split_windows=_split_windows(),
            label_rule=_label_rule(),
        )

    with pytest.raises(
        DatasetSnapshotBuilderError, match="label event_ts must be strictly increasing"
    ):
        build_chronological_dataset_snapshot(
            feature_vectors=features,
            label_observations=tuple(reversed(_observations())),
            split_windows=_split_windows(),
            label_rule=_label_rule(),
        )


def test_future_label_mutation_only_changes_rows_using_that_horizon_observation() -> None:
    baseline = build_chronological_dataset_snapshot(
        feature_vectors=_features(),
        label_observations=_observations(),
        split_windows=_split_windows(),
        label_rule=_label_rule(),
    )
    mutated = build_chronological_dataset_snapshot(
        feature_vectors=_features(),
        label_observations=_observations(("100", "101", "102", "999", "104", "105", "106")),
        split_windows=_split_windows(),
        label_rule=_label_rule(),
    )

    assert baseline.rows[0].model_dump() == mutated.rows[0].model_dump()
    assert baseline.rows[1].model_dump() == mutated.rows[1].model_dump()
    assert baseline.rows[2].row_id != mutated.rows[2].row_id
    assert baseline.rows[3].model_dump() == mutated.rows[3].model_dump()
    assert baseline.rows[4].model_dump() == mutated.rows[4].model_dump()
    assert baseline.rows[5].model_dump() == mutated.rows[5].model_dump()


def test_future_feature_mutation_does_not_alter_earlier_rows_or_label_values() -> None:
    baseline = build_chronological_dataset_snapshot(
        feature_vectors=_features(),
        label_observations=_observations(),
        split_windows=_split_windows(),
        label_rule=_label_rule(),
    )
    mutated_features = _features()[:-1] + (_feature(5, "999"),)
    mutated = build_chronological_dataset_snapshot(
        feature_vectors=mutated_features,
        label_observations=_observations(),
        split_windows=_split_windows(),
        label_rule=_label_rule(),
    )

    assert baseline.rows[0].model_dump() == mutated.rows[0].model_dump()
    assert baseline.rows[1].model_dump() == mutated.rows[1].model_dump()
    assert baseline.rows[2].model_dump() == mutated.rows[2].model_dump()
    assert baseline.rows[3].model_dump() == mutated.rows[3].model_dump()
    assert baseline.rows[4].model_dump() == mutated.rows[4].model_dump()
    assert baseline.rows[5].row_id != mutated.rows[5].row_id
    assert baseline.rows[5].label_value == mutated.rows[5].label_value


def test_no_hidden_label_as_feature_leakage_and_explicit_return_label() -> None:
    leaked = _feature(0, "100").model_copy(update={"values": {"label": Decimal("1")}})
    with pytest.raises(DatasetSnapshotBuilderError, match="label fields"):
        build_chronological_dataset_snapshot(
            feature_vectors=(leaked,),
            label_observations=_observations(),
            split_windows=_split_windows(),
            label_rule=_label_rule(),
        )

    snapshot = build_chronological_dataset_snapshot(
        feature_vectors=_features(),
        label_observations=_observations(),
        split_windows=_split_windows(),
        label_rule=_label_rule(LabelMethod.FUTURE_RETURN),
    )
    assert snapshot.rows[0].label_value == Decimal("0.01")
    assert "label_value" not in snapshot.rows[0].feature_values
    assert "future_1m" not in snapshot.rows[0].feature_values


def test_split_windows_must_be_ordered_and_non_overlapping() -> None:
    windows = _split_windows()
    overlapping = (
        windows[0],
        ChronologicalSplitWindow(
            split=DatasetSplit.VALIDATION,
            start_ts=START + timedelta(minutes=2),
            end_ts=START + timedelta(minutes=5),
        ),
        windows[2],
    )
    with pytest.raises(DatasetSnapshotBuilderError, match="must not overlap"):
        build_chronological_dataset_snapshot(
            feature_vectors=_features(),
            label_observations=_observations(),
            split_windows=overlapping,
            label_rule=_label_rule(),
        )

    with pytest.raises(DatasetSnapshotBuilderError, match="ordered train/validation/test"):
        build_chronological_dataset_snapshot(
            feature_vectors=_features(),
            label_observations=_observations(),
            split_windows=tuple(reversed(windows)),
            label_rule=_label_rule(),
        )
