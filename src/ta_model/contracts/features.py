"""Point-in-time feature contracts.

Traceability:
- FR-004: feature vectors carry event-time availability and clean-data lineage.
- NFR-001: deterministic IDs are derived from event-time inputs, not ingest time.

Scope:
- S4-001 defines TA feature contracts only; no labels, model, strategy, order,
  paper/live routing, leverage, derivatives, or liquidity/cost feature scope.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString


class FeatureQualityFlag(StrEnum):
    """Feature-quality flags from docs/07_data_contracts.md plus fail-closed history gaps."""

    MISSING = "missing"
    IMPUTED = "imputed"
    OUTLIER = "outlier"
    STALE = "stale"
    INSUFFICIENT_HISTORY = "insufficient_history"


FeatureValue = Decimal | None


class FeatureVector(ContractModel):
    """Feature schema from docs/07_data_contracts.md with deterministic identity."""

    feature_vector_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    feature_ts: AwareDatetime
    feature_version: NonEmptyString
    lookback_window: NonEmptyString
    values: dict[str, FeatureValue] = Field(min_length=1)
    input_snapshot_id: CanonicalId
    quality_flags: tuple[FeatureQualityFlag, ...]

    @model_validator(mode="after")
    def feature_vector_id_is_deterministic(self) -> Self:
        if self.feature_vector_id != build_feature_vector_id(
            instrument_id=self.instrument_id,
            venue_id=self.venue_id,
            feature_ts=self.feature_ts,
            feature_version=self.feature_version,
            lookback_window=self.lookback_window,
            values=self.values,
            input_snapshot_id=self.input_snapshot_id,
            quality_flags=self.quality_flags,
        ):
            raise ValueError("feature_vector_id is not deterministic")
        return self


class FeatureSnapshot(ContractModel):
    """Minimal deterministic handoff evidence for S4-001 feature-vector batches."""

    feature_snapshot_id: CanonicalId
    feature_version: NonEmptyString
    instrument_id: CanonicalId
    venue_id: CanonicalId
    vector_ids: tuple[CanonicalId, ...]
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def snapshot_hash_is_deterministic(self) -> Self:
        expected_hash = build_feature_snapshot_hash(vector_ids=self.vector_ids)
        if self.snapshot_hash != expected_hash:
            raise ValueError("snapshot_hash is not deterministic")
        if self.feature_snapshot_id != build_feature_snapshot_id(
            feature_version=self.feature_version,
            instrument_id=self.instrument_id,
            venue_id=self.venue_id,
            snapshot_hash=self.snapshot_hash,
        ):
            raise ValueError("feature_snapshot_id is not deterministic")
        return self


def build_feature_vector_id(
    *,
    instrument_id: str,
    venue_id: str,
    feature_ts: datetime,
    feature_version: str,
    lookback_window: str,
    values: dict[str, FeatureValue],
    input_snapshot_id: str,
    quality_flags: tuple[FeatureQualityFlag, ...],
) -> str:
    """Build a stable feature-vector ID from event-time values and lineage."""

    return _stable_id(
        "FEATURE",
        {
            "feature_ts": feature_ts.isoformat(),
            "feature_version": feature_version,
            "input_snapshot_id": input_snapshot_id,
            "instrument_id": instrument_id,
            "lookback_window": lookback_window,
            "quality_flags": tuple(flag.value for flag in quality_flags),
            "values": {name: _decimal_to_json(value) for name, value in values.items()},
            "venue_id": venue_id,
        },
    )


def build_feature_input_snapshot_id(*, record_ids: tuple[str, ...]) -> str:
    """Build minimal clean-data lineage ID for bars available at feature_ts."""

    return _stable_id("FEATUREINPUT", {"record_ids": record_ids})


def build_feature_snapshot(
    vector_ids: tuple[str, ...], *, vectors: tuple[FeatureVector, ...]
) -> FeatureSnapshot:
    """Build deterministic minimal snapshot evidence from feature-vector IDs."""

    if len(vectors) == 0:
        raise ValueError("at least one feature vector is required")
    if vector_ids != tuple(vector.feature_vector_id for vector in vectors):
        raise ValueError("vector_ids must match feature vectors")
    first = vectors[0]
    if not all(vector.feature_version == first.feature_version for vector in vectors):
        raise ValueError("all feature vectors must share feature_version")
    if not all(vector.instrument_id == first.instrument_id for vector in vectors):
        raise ValueError("all feature vectors must share instrument_id")
    if not all(vector.venue_id == first.venue_id for vector in vectors):
        raise ValueError("all feature vectors must share venue_id")
    snapshot_hash = build_feature_snapshot_hash(vector_ids=vector_ids)
    return FeatureSnapshot(
        feature_snapshot_id=build_feature_snapshot_id(
            feature_version=first.feature_version,
            instrument_id=first.instrument_id,
            venue_id=first.venue_id,
            snapshot_hash=snapshot_hash,
        ),
        feature_version=first.feature_version,
        instrument_id=first.instrument_id,
        venue_id=first.venue_id,
        vector_ids=vector_ids,
        snapshot_hash=snapshot_hash,
    )


def build_feature_snapshot_hash(*, vector_ids: tuple[str, ...]) -> str:
    return hashlib.sha256(
        json.dumps({"vector_ids": vector_ids}, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def build_feature_snapshot_id(
    *, feature_version: str, instrument_id: str, venue_id: str, snapshot_hash: str
) -> str:
    return _stable_id(
        "FEATURESNAPSHOT",
        {
            "feature_version": feature_version,
            "instrument_id": instrument_id,
            "snapshot_hash": snapshot_hash,
            "venue_id": venue_id,
        },
    )


def _stable_id(prefix: str, payload: object) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    return f"{prefix}:{digest.upper()}"


def _decimal_to_json(value: FeatureValue) -> str | None:
    return None if value is None else str(value)
