"""Chronological dataset snapshot contracts.

Traceability:
- FR-006: dataset snapshots store split rules, labels, feature versions, row counts,
  source feature snapshot IDs, and deterministic hashes.
- NFR-001: labels are explicit outputs after feature_ts and never feature inputs.
- NFR-005: deterministic row IDs and dataset hashes enable reproducible reruns.

Scope:
- S4-003 fixture/local dataset snapshots only. No storage adapter, training,
  strategy, risk, order, paper/live routing, leverage, derivatives, or live capital.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.features import FeatureValue, FeatureVector
from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString


class DatasetSplit(StrEnum):
    """Chronological dataset split names."""

    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class LabelMethod(StrEnum):
    """Supported fixture label computation methods."""

    FUTURE_VALUE = "future_value"
    FUTURE_RETURN = "future_return"


class LabelObservation(ContractModel):
    """Event-time label source observation.

    ingest_ts is intentionally absent: label identity is event-time/lineage based.
    """

    observation_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    event_ts: AwareDatetime
    value: Decimal
    source_lineage_id: CanonicalId

    @model_validator(mode="after")
    def observation_id_is_deterministic(self) -> Self:
        if self.observation_id != build_label_observation_id(
            instrument_id=self.instrument_id,
            venue_id=self.venue_id,
            event_ts=self.event_ts,
            value=self.value,
            source_lineage_id=self.source_lineage_id,
        ):
            raise ValueError("observation_id is not deterministic")
        return self


class LabelRule(ContractModel):
    """Explicit supervised label rule stored with every dataset snapshot."""

    label_rule_id: CanonicalId
    name: NonEmptyString
    horizon_seconds: int = Field(gt=0)
    method: LabelMethod

    @model_validator(mode="after")
    def label_rule_id_is_deterministic(self) -> Self:
        if self.label_rule_id != build_label_rule_id(
            name=self.name,
            horizon_seconds=self.horizon_seconds,
            method=self.method,
        ):
            raise ValueError("label_rule_id is not deterministic")
        return self


class ChronologicalSplitWindow(ContractModel):
    """Half-open feature_ts split window [start_ts, end_ts)."""

    split: DatasetSplit
    start_ts: AwareDatetime
    end_ts: AwareDatetime

    @model_validator(mode="after")
    def window_is_forward(self) -> Self:
        if self.end_ts <= self.start_ts:
            raise ValueError("split end_ts must be after start_ts")
        return self


class DatasetRow(ContractModel):
    """One reproducible training/evaluation row with explicit label output."""

    row_id: CanonicalId
    feature_vector_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    feature_ts: AwareDatetime
    feature_version: NonEmptyString
    feature_values: dict[str, FeatureValue] = Field(min_length=1)
    feature_input_snapshot_id: CanonicalId
    split: DatasetSplit
    label_rule_id: CanonicalId
    label_value: Decimal
    label_ts: AwareDatetime
    label_observation_id: CanonicalId
    source_feature_snapshot_ids: tuple[CanonicalId, ...] = ()

    @model_validator(mode="after")
    def row_is_deterministic_and_pit_safe(self) -> Self:
        if self.label_ts <= self.feature_ts:
            raise ValueError("label_ts must be after feature_ts")
        if self.row_id != build_dataset_row_id(
            feature_vector_id=self.feature_vector_id,
            instrument_id=self.instrument_id,
            venue_id=self.venue_id,
            feature_ts=self.feature_ts,
            feature_version=self.feature_version,
            feature_values=self.feature_values,
            feature_input_snapshot_id=self.feature_input_snapshot_id,
            split=self.split,
            label_rule_id=self.label_rule_id,
            label_value=self.label_value,
            label_ts=self.label_ts,
            label_observation_id=self.label_observation_id,
            source_feature_snapshot_ids=self.source_feature_snapshot_ids,
        ):
            raise ValueError("row_id is not deterministic")
        return self


class DatasetSnapshot(ContractModel):
    """Deterministic chronological dataset snapshot metadata and rows."""

    dataset_snapshot_id: CanonicalId
    dataset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    feature_versions: tuple[NonEmptyString, ...]
    feature_vector_ids: tuple[CanonicalId, ...]
    source_feature_snapshot_ids: tuple[CanonicalId, ...] = ()
    split_windows: tuple[ChronologicalSplitWindow, ...]
    label_rule: LabelRule
    row_ids: tuple[CanonicalId, ...]
    row_counts_by_split: dict[DatasetSplit, int]
    rows: tuple[DatasetRow, ...]

    @model_validator(mode="after")
    def snapshot_is_deterministic(self) -> Self:
        if self.row_ids != tuple(row.row_id for row in self.rows):
            raise ValueError("row_ids must match rows")
        if self.feature_vector_ids != tuple(row.feature_vector_id for row in self.rows):
            raise ValueError("feature_vector_ids must match rows")
        if self.feature_versions != tuple(sorted({row.feature_version for row in self.rows})):
            raise ValueError("feature_versions must match rows")
        expected_counts = {split: 0 for split in DatasetSplit}
        for row in self.rows:
            matching_windows = tuple(
                window
                for window in self.split_windows
                if window.start_ts <= row.feature_ts < window.end_ts
            )
            if len(matching_windows) != 1:
                raise ValueError("row feature_ts must match exactly one split window")
            if row.split is not matching_windows[0].split:
                raise ValueError("row split must match split window for feature_ts")
            expected_counts[row.split] += 1
        if self.row_counts_by_split != expected_counts:
            raise ValueError("row_counts_by_split must match rows")
        if self.dataset_hash != build_dataset_hash(
            rows=self.rows,
            split_windows=self.split_windows,
            label_rule=self.label_rule,
            source_feature_snapshot_ids=self.source_feature_snapshot_ids,
        ):
            raise ValueError("dataset_hash is not deterministic")
        if self.dataset_snapshot_id != build_dataset_snapshot_id(dataset_hash=self.dataset_hash):
            raise ValueError("dataset_snapshot_id is not deterministic")
        return self


def build_label_observation_id(
    *, instrument_id: str, venue_id: str, event_ts: datetime, value: Decimal, source_lineage_id: str
) -> str:
    return _stable_id(
        "LABELOBS",
        {
            "event_ts": event_ts.isoformat(),
            "instrument_id": instrument_id,
            "source_lineage_id": source_lineage_id,
            "value": str(value),
            "venue_id": venue_id,
        },
    )


def build_label_rule_id(*, name: str, horizon_seconds: int, method: LabelMethod) -> str:
    return _stable_id(
        "LABELRULE",
        {"horizon_seconds": horizon_seconds, "method": method.value, "name": name},
    )


def build_dataset_row_id(
    *,
    feature_vector_id: str,
    instrument_id: str,
    venue_id: str,
    feature_ts: datetime,
    feature_version: str,
    feature_values: dict[str, FeatureValue],
    feature_input_snapshot_id: str,
    split: DatasetSplit,
    label_rule_id: str,
    label_value: Decimal,
    label_ts: datetime,
    label_observation_id: str,
    source_feature_snapshot_ids: tuple[str, ...],
) -> str:
    return _stable_id(
        "DATASETROW",
        {
            "feature_input_snapshot_id": feature_input_snapshot_id,
            "feature_ts": feature_ts.isoformat(),
            "feature_values": _feature_values_json(feature_values),
            "feature_vector_id": feature_vector_id,
            "feature_version": feature_version,
            "instrument_id": instrument_id,
            "label_observation_id": label_observation_id,
            "label_rule_id": label_rule_id,
            "label_ts": label_ts.isoformat(),
            "label_value": str(label_value),
            "source_feature_snapshot_ids": source_feature_snapshot_ids,
            "split": split.value,
            "venue_id": venue_id,
        },
    )


def build_dataset_hash(
    *,
    rows: tuple[DatasetRow, ...],
    split_windows: tuple[ChronologicalSplitWindow, ...],
    label_rule: LabelRule,
    source_feature_snapshot_ids: tuple[str, ...],
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "label_rule": _model_json(label_rule),
                "rows": tuple(_model_json(row) for row in rows),
                "source_feature_snapshot_ids": source_feature_snapshot_ids,
                "split_windows": tuple(_model_json(window) for window in split_windows),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def build_dataset_snapshot_id(*, dataset_hash: str) -> str:
    return _stable_id("DATASETSNAPSHOT", {"dataset_hash": dataset_hash})


def build_label_rule(*, name: str, horizon_seconds: int, method: LabelMethod) -> LabelRule:
    return LabelRule(
        label_rule_id=build_label_rule_id(
            name=name, horizon_seconds=horizon_seconds, method=method
        ),
        name=name,
        horizon_seconds=horizon_seconds,
        method=method,
    )


def build_label_observation(
    *, instrument_id: str, venue_id: str, event_ts: datetime, value: Decimal, source_lineage_id: str
) -> LabelObservation:
    return LabelObservation(
        observation_id=build_label_observation_id(
            instrument_id=instrument_id,
            venue_id=venue_id,
            event_ts=event_ts,
            value=value,
            source_lineage_id=source_lineage_id,
        ),
        instrument_id=instrument_id,
        venue_id=venue_id,
        event_ts=event_ts,
        value=value,
        source_lineage_id=source_lineage_id,
    )


def row_from_feature_vector(
    *,
    feature_vector: FeatureVector,
    split: DatasetSplit,
    label_rule: LabelRule,
    label_value: Decimal,
    label_ts: datetime,
    label_observation_id: str,
    source_feature_snapshot_ids: tuple[str, ...],
) -> DatasetRow:
    row_id = build_dataset_row_id(
        feature_vector_id=feature_vector.feature_vector_id,
        instrument_id=feature_vector.instrument_id,
        venue_id=feature_vector.venue_id,
        feature_ts=feature_vector.feature_ts,
        feature_version=feature_vector.feature_version,
        feature_values=feature_vector.values,
        feature_input_snapshot_id=feature_vector.input_snapshot_id,
        split=split,
        label_rule_id=label_rule.label_rule_id,
        label_value=label_value,
        label_ts=label_ts,
        label_observation_id=label_observation_id,
        source_feature_snapshot_ids=source_feature_snapshot_ids,
    )
    return DatasetRow(
        row_id=row_id,
        feature_vector_id=feature_vector.feature_vector_id,
        instrument_id=feature_vector.instrument_id,
        venue_id=feature_vector.venue_id,
        feature_ts=feature_vector.feature_ts,
        feature_version=feature_vector.feature_version,
        feature_values=feature_vector.values,
        feature_input_snapshot_id=feature_vector.input_snapshot_id,
        split=split,
        label_rule_id=label_rule.label_rule_id,
        label_value=label_value,
        label_ts=label_ts,
        label_observation_id=label_observation_id,
        source_feature_snapshot_ids=source_feature_snapshot_ids,
    )


def _stable_id(prefix: str, payload: object) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    return f"{prefix}:{digest.upper()}"


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())


def _feature_values_json(values: dict[str, FeatureValue]) -> dict[str, str | None]:
    return {name: None if value is None else str(value) for name, value in values.items()}
