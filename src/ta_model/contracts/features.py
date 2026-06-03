"""Point-in-time feature contracts.

Traceability:
- FR-004: feature vectors carry event-time availability and clean-data lineage.
- FR-005: liquidity/cost feature fixtures carry quote event-time inputs.
- NFR-001: deterministic IDs are derived from event-time inputs, not ingest time.

Scope:
- S4-001 defines shared feature-vector contracts; S4-002 adds fixture-only quote
  inputs for liquidity/cost features. No labels, model, strategy, order,
  paper/live routing, leverage, derivatives, or full quote ingestion scope.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.instrument_master import (
    CanonicalId,
    ContractModel,
    NonEmptyString,
    NonNegativeDecimal,
    PositiveDecimal,
)


class FeatureQualityFlag(StrEnum):
    """Feature-quality flags from docs/07_data_contracts.md plus fail-closed history gaps."""

    MISSING = "missing"
    IMPUTED = "imputed"
    OUTLIER = "outlier"
    STALE = "stale"
    INSUFFICIENT_HISTORY = "insufficient_history"


FeatureValue = Decimal | None


class QuoteFeatureInput(ContractModel):
    """Minimal best-bid/ask feature input aligned to docs/07 quote fields.

    This is fixture-only feature-engine input, not full quote/order-book ingestion.
    Identity intentionally excludes ingest_ts so replay is event-time deterministic.
    """

    quote_feature_input_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    event_ts: AwareDatetime
    best_bid: PositiveDecimal
    best_ask: PositiveDecimal
    bid_size: NonNegativeDecimal | None = None
    ask_size: NonNegativeDecimal | None = None
    source_ts: AwareDatetime | None = None
    ingest_ts: AwareDatetime
    quality_flags: tuple[NonEmptyString, ...]
    raw_payload_id: CanonicalId

    @model_validator(mode="after")
    def quote_is_valid_and_deterministic(self) -> Self:
        if self.best_ask <= self.best_bid:
            raise ValueError("quote must not be crossed or locked")
        if self.quote_feature_input_id != build_quote_feature_input_id(
            instrument_id=self.instrument_id,
            venue_id=self.venue_id,
            event_ts=self.event_ts,
            best_bid=self.best_bid,
            best_ask=self.best_ask,
            bid_size=self.bid_size,
            ask_size=self.ask_size,
            source_ts=self.source_ts,
            quality_flags=self.quality_flags,
            raw_payload_id=self.raw_payload_id,
        ):
            raise ValueError("quote_feature_input_id is not deterministic")
        return self


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


def build_quote_feature_input_id(
    *,
    instrument_id: str,
    venue_id: str,
    event_ts: datetime,
    best_bid: Decimal,
    best_ask: Decimal,
    bid_size: Decimal | None,
    ask_size: Decimal | None,
    source_ts: datetime | None,
    quality_flags: tuple[str, ...],
    raw_payload_id: str,
) -> str:
    """Build a stable quote input ID from market event-time fields, not ingest time."""

    return _stable_id(
        "QUOTEFEATUREINPUT",
        {
            "ask_size": _decimal_to_json(ask_size),
            "best_ask": _decimal_to_json(best_ask),
            "best_bid": _decimal_to_json(best_bid),
            "bid_size": _decimal_to_json(bid_size),
            "event_ts": event_ts.isoformat(),
            "instrument_id": instrument_id,
            "quality_flags": quality_flags,
            "raw_payload_id": raw_payload_id,
            "source_ts": None if source_ts is None else source_ts.isoformat(),
            "venue_id": venue_id,
        },
    )


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
