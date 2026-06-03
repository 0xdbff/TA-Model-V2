"""Chronological dataset snapshot builder.

Traceability:
- FR-006: builds reproducible train/validation/test snapshots from point-in-time
  feature vectors with explicit split and label rules.
- NFR-001: split assignment uses feature_ts and labels must occur strictly after it.
- NFR-005: row IDs and dataset hashes exclude ingest-time/nondeterministic inputs.

Scope:
- Fixture/local deterministic builder only; no source/API/network data, storage,
  training, strategy, risk, order, paper/live, leverage, derivatives, or live capital.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

from ta_model.contracts.datasets import (
    ChronologicalSplitWindow,
    DatasetSnapshot,
    DatasetSplit,
    LabelMethod,
    LabelObservation,
    LabelRule,
    build_dataset_hash,
    build_dataset_snapshot_id,
    row_from_feature_vector,
)
from ta_model.contracts.features import FeatureVector


class DatasetSnapshotBuilderError(ValueError):
    """Raised when dataset snapshot construction must fail closed."""


def build_chronological_dataset_snapshot(
    *,
    feature_vectors: Sequence[FeatureVector],
    label_observations: Sequence[LabelObservation],
    split_windows: Sequence[ChronologicalSplitWindow],
    label_rule: LabelRule,
    source_feature_snapshot_ids: Sequence[str] = (),
) -> DatasetSnapshot:
    """Build a deterministic chronological dataset snapshot.

    Feature vectors and label observations must be strictly increasing by event time.
    Splits are assigned solely by feature_ts; label_ts is only the supervised output.
    """

    vectors = tuple(feature_vectors)
    observations = tuple(label_observations)
    windows = tuple(split_windows)
    source_snapshot_ids = tuple(source_feature_snapshot_ids)
    _validate_vectors(vectors)
    _validate_observations(observations)
    _validate_split_windows(windows)
    _validate_no_label_as_feature_leakage(vectors, label_rule)

    observation_by_key = {
        (observation.instrument_id, observation.venue_id, observation.event_ts): observation
        for observation in observations
    }
    rows = []
    for vector in vectors:
        split = _split_for_feature_ts(vector, windows)
        label_ts = vector.feature_ts + timedelta(seconds=label_rule.horizon_seconds)
        observation = observation_by_key.get((vector.instrument_id, vector.venue_id, label_ts))
        if observation is None:
            raise DatasetSnapshotBuilderError("missing label observation for configured horizon")
        if observation.event_ts <= vector.feature_ts:
            raise DatasetSnapshotBuilderError("label observation must be after feature_ts")
        label_value = _compute_label_value(
            vector=vector, observation=observation, label_rule=label_rule
        )
        rows.append(
            row_from_feature_vector(
                feature_vector=vector,
                split=split,
                label_rule=label_rule,
                label_value=label_value,
                label_ts=observation.event_ts,
                label_observation_id=observation.observation_id,
                source_feature_snapshot_ids=source_snapshot_ids,
            )
        )

    row_tuple = tuple(rows)
    dataset_hash = build_dataset_hash(
        rows=row_tuple,
        split_windows=windows,
        label_rule=label_rule,
        source_feature_snapshot_ids=source_snapshot_ids,
    )
    counts = {split: 0 for split in DatasetSplit}
    for row in row_tuple:
        counts[row.split] += 1
    return DatasetSnapshot(
        dataset_snapshot_id=build_dataset_snapshot_id(dataset_hash=dataset_hash),
        dataset_hash=dataset_hash,
        feature_versions=tuple(sorted({row.feature_version for row in row_tuple})),
        feature_vector_ids=tuple(row.feature_vector_id for row in row_tuple),
        source_feature_snapshot_ids=source_snapshot_ids,
        split_windows=windows,
        label_rule=label_rule,
        row_ids=tuple(row.row_id for row in row_tuple),
        row_counts_by_split=counts,
        rows=row_tuple,
    )


def _validate_vectors(vectors: tuple[FeatureVector, ...]) -> None:
    if not vectors:
        raise DatasetSnapshotBuilderError("at least one feature vector is required")
    previous_ts = None
    seen_ids: set[str] = set()
    for vector in vectors:
        if vector.feature_vector_id in seen_ids:
            raise DatasetSnapshotBuilderError("duplicate feature_vector_id")
        seen_ids.add(vector.feature_vector_id)
        if previous_ts is not None and vector.feature_ts <= previous_ts:
            raise DatasetSnapshotBuilderError("feature_ts must be strictly increasing")
        previous_ts = vector.feature_ts


def _validate_observations(observations: tuple[LabelObservation, ...]) -> None:
    if not observations:
        raise DatasetSnapshotBuilderError("at least one label observation is required")
    previous_ts = None
    seen_keys: set[tuple[str, str, object]] = set()
    for observation in observations:
        key = (observation.instrument_id, observation.venue_id, observation.event_ts)
        if key in seen_keys:
            raise DatasetSnapshotBuilderError("ambiguous duplicate label event_ts")
        seen_keys.add(key)
        if previous_ts is not None and observation.event_ts <= previous_ts:
            raise DatasetSnapshotBuilderError("label event_ts must be strictly increasing")
        previous_ts = observation.event_ts


def _validate_split_windows(windows: tuple[ChronologicalSplitWindow, ...]) -> None:
    if tuple(window.split for window in windows) != (
        DatasetSplit.TRAIN,
        DatasetSplit.VALIDATION,
        DatasetSplit.TEST,
    ):
        raise DatasetSnapshotBuilderError("split windows must be ordered train/validation/test")
    previous_end = None
    for window in windows:
        if previous_end is not None and window.start_ts < previous_end:
            raise DatasetSnapshotBuilderError("split windows must not overlap")
        previous_end = window.end_ts


def _validate_no_label_as_feature_leakage(
    vectors: tuple[FeatureVector, ...], label_rule: LabelRule
) -> None:
    forbidden_names = {"label", label_rule.name, f"label_{label_rule.name}"}
    for vector in vectors:
        lower_names = {name.lower() for name in vector.values}
        if lower_names & forbidden_names:
            raise DatasetSnapshotBuilderError("label fields must not appear in feature values")


def _split_for_feature_ts(
    vector: FeatureVector, windows: tuple[ChronologicalSplitWindow, ...]
) -> DatasetSplit:
    for window in windows:
        if window.start_ts <= vector.feature_ts < window.end_ts:
            return window.split
    raise DatasetSnapshotBuilderError("feature_ts is outside configured split windows")


def _compute_label_value(
    *, vector: FeatureVector, observation: LabelObservation, label_rule: LabelRule
) -> Decimal:
    if label_rule.method is LabelMethod.FUTURE_VALUE:
        return observation.value
    if label_rule.method is LabelMethod.FUTURE_RETURN:
        base_value = vector.values.get("close")
        if not isinstance(base_value, Decimal) or base_value == Decimal("0"):
            raise DatasetSnapshotBuilderError("future_return labels require non-zero close feature")
        return (observation.value - base_value) / base_value
    raise DatasetSnapshotBuilderError("unsupported label method")
