"""Reproducible S7 training-run contracts.

Traceability:
- FR-008: creates the auditable run foundation for later probabilistic candidates.
- FR-007: keeps baseline prerequisite lineage available without training a candidate here.
- NFR-005: run IDs resolve dataset snapshot, config, code commit, seed, metrics, and artifacts.

Scope:
- S7-001 runner scaffolding only. No MLflow registry states, model promotion,
  paper/live routing, leverage, derivatives, online self-update, or live capital.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString


class TrainerKind(StrEnum):
    """Supported S7-001 runner evidence trainers."""

    REFERENCE_MEAN_LABEL = "reference_mean_label"


class TrainingRunStatus(StrEnum):
    """Explicit non-promotion semantics for S7-001 outputs."""

    RUNNER_EVIDENCE_ONLY = "runner_evidence_only"


class TrainingConfig(ContractModel):
    """Deterministic training-run configuration."""

    training_config_id: CanonicalId
    training_config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: NonEmptyString
    trainer_kind: TrainerKind = TrainerKind.REFERENCE_MEAN_LABEL
    runner_version: NonEmptyString = "s7-001-training-runner-v1"
    train_split: DatasetSplit = DatasetSplit.TRAIN
    evaluation_splits: tuple[DatasetSplit, ...] = (DatasetSplit.VALIDATION, DatasetSplit.TEST)
    parameters: tuple[NonEmptyString, ...] = ()
    seed: int = Field(ge=0)

    @model_validator(mode="after")
    def config_identity_is_deterministic(self) -> Self:
        if self.train_split is not DatasetSplit.TRAIN:
            raise ValueError("training runner requires train_split=train")
        if not self.evaluation_splits:
            raise ValueError("at least one evaluation split is required")
        if len(set(self.evaluation_splits)) != len(self.evaluation_splits):
            raise ValueError("evaluation_splits must be unique")
        expected_hash = build_training_config_hash(
            name=self.name,
            trainer_kind=self.trainer_kind,
            runner_version=self.runner_version,
            train_split=self.train_split,
            evaluation_splits=self.evaluation_splits,
            parameters=self.parameters,
            seed=self.seed,
        )
        if self.training_config_hash != expected_hash:
            raise ValueError("training_config_hash is not deterministic")
        if self.training_config_id != build_training_config_id(training_config_hash=expected_hash):
            raise ValueError("training_config_id is not deterministic")
        return self


class TrainingMetric(ContractModel):
    """One deterministic training-run metric."""

    name: NonEmptyString
    split: DatasetSplit
    value: Decimal

    @field_validator("value")
    @classmethod
    def value_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("metric values must be finite")
        return value


class TrainingArtifactReference(ContractModel):
    """Auditable deterministic artifact reference."""

    name: NonEmptyString
    uri: NonEmptyString
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: NonEmptyString = "application/json"


class TrainingRunResult(ContractModel):
    """Deterministic S7-001 training-run result."""

    training_run_id: CanonicalId
    training_run_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_snapshot_id: CanonicalId
    dataset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_config: TrainingConfig
    code_commit: NonEmptyString
    seed: int = Field(ge=0)
    status: TrainingRunStatus = TrainingRunStatus.RUNNER_EVIDENCE_ONLY
    metrics: tuple[TrainingMetric, ...]
    artifacts: tuple[TrainingArtifactReference, ...]

    @model_validator(mode="after")
    def result_identity_is_deterministic(self) -> Self:
        if self.seed != self.training_config.seed:
            raise ValueError("run seed must match training_config seed")
        if not self.metrics:
            raise ValueError("training runs require at least one metric")
        if not self.artifacts:
            raise ValueError("training runs require at least one artifact reference")
        if len({(metric.split, metric.name) for metric in self.metrics}) != len(self.metrics):
            raise ValueError("metric names must be unique per split")
        if len({artifact.name for artifact in self.artifacts}) != len(self.artifacts):
            raise ValueError("artifact names must be unique")
        expected_hash = build_training_run_hash(
            dataset_snapshot_id=self.dataset_snapshot_id,
            dataset_hash=self.dataset_hash,
            training_config=self.training_config,
            code_commit=self.code_commit,
            seed=self.seed,
            status=self.status,
            metrics=self.metrics,
            artifacts=self.artifacts,
        )
        if self.training_run_hash != expected_hash:
            raise ValueError("training_run_hash is not deterministic")
        if self.training_run_id != build_training_run_id(training_run_hash=expected_hash):
            raise ValueError("training_run_id is not deterministic")
        return self


def build_training_config(
    *,
    name: str,
    trainer_kind: TrainerKind = TrainerKind.REFERENCE_MEAN_LABEL,
    runner_version: str = "s7-001-training-runner-v1",
    train_split: DatasetSplit = DatasetSplit.TRAIN,
    evaluation_splits: tuple[DatasetSplit, ...] = (DatasetSplit.VALIDATION, DatasetSplit.TEST),
    parameters: tuple[str, ...] = (),
    seed: int = 0,
) -> TrainingConfig:
    config_hash = build_training_config_hash(
        name=name,
        trainer_kind=trainer_kind,
        runner_version=runner_version,
        train_split=train_split,
        evaluation_splits=evaluation_splits,
        parameters=parameters,
        seed=seed,
    )
    return TrainingConfig(
        training_config_id=build_training_config_id(training_config_hash=config_hash),
        training_config_hash=config_hash,
        name=name,
        trainer_kind=trainer_kind,
        runner_version=runner_version,
        train_split=train_split,
        evaluation_splits=evaluation_splits,
        parameters=parameters,
        seed=seed,
    )


def build_training_config_hash(
    *,
    name: str,
    trainer_kind: TrainerKind,
    runner_version: str,
    train_split: DatasetSplit,
    evaluation_splits: tuple[DatasetSplit, ...],
    parameters: tuple[str, ...],
    seed: int,
) -> str:
    return _hash(
        {
            "evaluation_splits": tuple(split.value for split in evaluation_splits),
            "name": name,
            "parameters": parameters,
            "runner_version": runner_version,
            "seed": seed,
            "train_split": train_split.value,
            "trainer_kind": trainer_kind.value,
        }
    )


def build_training_config_id(*, training_config_hash: str) -> str:
    return _stable_id("TRAINCONFIG", {"training_config_hash": training_config_hash})


def build_training_artifact_reference(
    *, name: str, uri: str, payload: object, media_type: str = "application/json"
) -> TrainingArtifactReference:
    return TrainingArtifactReference(
        name=name,
        uri=uri,
        content_hash=_hash(payload),
        media_type=media_type,
    )


def build_training_run_hash(
    *,
    dataset_snapshot_id: str,
    dataset_hash: str,
    training_config: TrainingConfig,
    code_commit: str,
    seed: int,
    status: TrainingRunStatus,
    metrics: tuple[TrainingMetric, ...],
    artifacts: tuple[TrainingArtifactReference, ...],
) -> str:
    return _hash(
        {
            "artifacts": tuple(_model_json(artifact) for artifact in artifacts),
            "code_commit": code_commit,
            "dataset_hash": dataset_hash,
            "dataset_snapshot_id": dataset_snapshot_id,
            "metrics": tuple(_model_json(metric) for metric in metrics),
            "seed": seed,
            "status": status.value,
            "training_config": _model_json(training_config),
        }
    )


def build_training_run_id(*, training_run_hash: str) -> str:
    return _stable_id("TRAINRUN", {"training_run_hash": training_run_hash})


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())
