"""Probabilistic forecast contracts for first S7 candidate outputs.

Traceability:
- FR-008: emits probabilistic model/candidate outputs with auditable lineage.
- FR-014: forecast rows expose probabilities, quantiles, uncertainty, and calibration
  metadata for downstream evaluation.
- NFR-005: deterministic forecast IDs and output hashes support reproducible reruns.

Scope:
- S7-002 candidate outputs only. No registry state transitions, model promotion,
  paper/live routing, leverage, derivatives, online self-update, or live capital.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString
from ta_model.contracts.training import build_training_run_id


class CalibrationStatus(StrEnum):
    """Calibration state carried by every forecast output."""

    UNCALIBRATED = "uncalibrated"
    TRAIN_PRIOR_ONLY = "train_prior_only"
    SEQUENCE_CONDITIONED_TRAIN_ONLY = "sequence_conditioned_train_only"
    CALIBRATED = "calibrated"


class ForecastQuantile(ContractModel):
    """One quantile prediction for the supervised label distribution."""

    level: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"))
    value: Decimal

    @field_validator("level", "value")
    @classmethod
    def decimals_are_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("quantile levels and values must be finite")
        return value


class Forecast(ContractModel):
    """One strict probabilistic forecast with dataset, feature, and run lineage."""

    forecast_id: CanonicalId
    dataset_snapshot_id: CanonicalId
    dataset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_row_id: CanonicalId
    feature_vector_id: CanonicalId
    feature_input_snapshot_id: CanonicalId
    feature_version: NonEmptyString
    source_feature_snapshot_ids: tuple[CanonicalId, ...] = ()
    instrument_id: CanonicalId
    venue_id: CanonicalId
    feature_ts: AwareDatetime
    label_rule_id: CanonicalId
    split: DatasetSplit
    training_run_id: CanonicalId
    training_run_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_version_id: CanonicalId
    model_version_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    probabilities: dict[NonEmptyString, Decimal] = Field(min_length=2)
    quantiles: tuple[ForecastQuantile, ...] = Field(min_length=1)
    uncertainty: Decimal = Field(ge=Decimal("0"))
    calibration_status: CalibrationStatus
    calibration_metadata: dict[NonEmptyString, NonEmptyString] = Field(min_length=1)

    @field_validator("probabilities")
    @classmethod
    def probabilities_are_valid(cls, values: dict[str, Decimal]) -> dict[str, Decimal]:
        total = Decimal("0")
        for probability in values.values():
            if not probability.is_finite():
                raise ValueError("probabilities must be finite")
            if probability < Decimal("0") or probability > Decimal("1"):
                raise ValueError("probabilities must be between 0 and 1")
            total += probability
        if total != Decimal("1"):
            raise ValueError("probabilities must sum to 1")
        return values

    @field_validator("uncertainty")
    @classmethod
    def uncertainty_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("uncertainty must be finite")
        return value

    @model_validator(mode="after")
    def forecast_identity_and_quantiles_are_valid(self) -> Self:
        previous_level: Decimal | None = None
        previous_value: Decimal | None = None
        for quantile in self.quantiles:
            if previous_level is not None and quantile.level <= previous_level:
                raise ValueError("quantile levels must be strictly increasing")
            if previous_value is not None and quantile.value < previous_value:
                raise ValueError("quantile values must be monotonic")
            previous_level = quantile.level
            previous_value = quantile.value
        if self.split is DatasetSplit.TRAIN:
            raise ValueError("forecasts must be out-of-sample")
        if self.training_run_id != build_training_run_id(
            training_run_hash=self.training_run_hash
        ):
            raise ValueError("training_run_id must match training_run_hash")
        candidate_name = self.calibration_metadata.get("candidate_name")
        if candidate_name is None:
            raise ValueError("calibration_metadata requires candidate_name")
        expected_model_version_hash = build_model_version_hash(
            training_run_id=self.training_run_id,
            training_run_hash=self.training_run_hash,
            candidate_name=candidate_name,
        )
        if self.model_version_hash != expected_model_version_hash:
            raise ValueError("model_version_hash must match training run and candidate")
        if self.model_version_id != build_model_version_id(
            model_version_hash=self.model_version_hash
        ):
            raise ValueError("model_version_id must match model_version_hash")
        expected_id = build_forecast_id(
            dataset_snapshot_id=self.dataset_snapshot_id,
            dataset_hash=self.dataset_hash,
            dataset_row_id=self.dataset_row_id,
            split=self.split,
            training_run_id=self.training_run_id,
            training_run_hash=self.training_run_hash,
            model_version_id=self.model_version_id,
            model_version_hash=self.model_version_hash,
            probabilities=self.probabilities,
            quantiles=self.quantiles,
            uncertainty=self.uncertainty,
            calibration_status=self.calibration_status,
            calibration_metadata=self.calibration_metadata,
        )
        if self.forecast_id != expected_id:
            raise ValueError("forecast_id is not deterministic")
        return self


class ProbabilisticCandidateOutput(ContractModel):
    """Deterministic S7-002 candidate forecast artifact."""

    output_id: CanonicalId
    output_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_snapshot_id: CanonicalId
    dataset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_run_id: CanonicalId
    training_run_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_version_id: CanonicalId
    model_version_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    forecast_ids: tuple[CanonicalId, ...] = Field(min_length=1)
    forecasts: tuple[Forecast, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def output_identity_is_deterministic(self) -> Self:
        if self.forecast_ids != tuple(forecast.forecast_id for forecast in self.forecasts):
            raise ValueError("forecast_ids must match forecasts")
        for forecast in self.forecasts:
            if forecast.dataset_snapshot_id != self.dataset_snapshot_id:
                raise ValueError("forecast dataset_snapshot_id must match output")
            if forecast.dataset_hash != self.dataset_hash:
                raise ValueError("forecast dataset_hash must match output")
            if forecast.training_run_id != self.training_run_id:
                raise ValueError("forecast training_run_id must match output")
            if forecast.training_run_hash != self.training_run_hash:
                raise ValueError("forecast training_run_hash must match output")
            if forecast.model_version_id != self.model_version_id:
                raise ValueError("forecast model_version_id must match output")
            if forecast.model_version_hash != self.model_version_hash:
                raise ValueError("forecast model_version_hash must match output")
        expected_hash = build_probabilistic_output_hash(
            dataset_snapshot_id=self.dataset_snapshot_id,
            dataset_hash=self.dataset_hash,
            training_run_id=self.training_run_id,
            training_run_hash=self.training_run_hash,
            model_version_id=self.model_version_id,
            model_version_hash=self.model_version_hash,
            forecasts=self.forecasts,
        )
        if self.output_hash != expected_hash:
            raise ValueError("output_hash is not deterministic")
        if self.output_id != build_probabilistic_output_id(output_hash=expected_hash):
            raise ValueError("output_id is not deterministic")
        return self


def build_model_version_hash(
    *, training_run_id: str, training_run_hash: str, candidate_name: str
) -> str:
    return _hash(
        {
            "candidate_name": candidate_name,
            "scope": "s7-002-non-promotable-probabilistic-candidate",
            "training_run_hash": training_run_hash,
            "training_run_id": training_run_id,
        }
    )


def build_model_version_id(*, model_version_hash: str) -> str:
    return _stable_id("MODELVERSION", {"model_version_hash": model_version_hash})


def build_forecast_id(
    *,
    dataset_snapshot_id: str,
    dataset_hash: str,
    dataset_row_id: str,
    split: DatasetSplit,
    training_run_id: str,
    training_run_hash: str,
    model_version_id: str,
    model_version_hash: str,
    probabilities: dict[str, Decimal],
    quantiles: tuple[ForecastQuantile, ...],
    uncertainty: Decimal,
    calibration_status: CalibrationStatus,
    calibration_metadata: dict[str, str],
) -> str:
    return _stable_id(
        "FORECAST",
        {
            "calibration_metadata": calibration_metadata,
            "calibration_status": calibration_status.value,
            "dataset_hash": dataset_hash,
            "dataset_row_id": dataset_row_id,
            "dataset_snapshot_id": dataset_snapshot_id,
            "model_version_hash": model_version_hash,
            "model_version_id": model_version_id,
            "probabilities": {key: str(value) for key, value in sorted(probabilities.items())},
            "quantiles": tuple(_model_json(quantile) for quantile in quantiles),
            "split": split.value,
            "training_run_hash": training_run_hash,
            "training_run_id": training_run_id,
            "uncertainty": str(uncertainty),
        },
    )


def build_probabilistic_output_hash(
    *,
    dataset_snapshot_id: str,
    dataset_hash: str,
    training_run_id: str,
    training_run_hash: str,
    model_version_id: str,
    model_version_hash: str,
    forecasts: tuple[Forecast, ...],
) -> str:
    return _hash(
        {
            "dataset_hash": dataset_hash,
            "dataset_snapshot_id": dataset_snapshot_id,
            "forecasts": tuple(_model_json(forecast) for forecast in forecasts),
            "model_version_hash": model_version_hash,
            "model_version_id": model_version_id,
            "training_run_hash": training_run_hash,
            "training_run_id": training_run_id,
        }
    )


def build_probabilistic_output_id(*, output_hash: str) -> str:
    return _stable_id("PROBOUTPUT", {"output_hash": output_hash})


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())
