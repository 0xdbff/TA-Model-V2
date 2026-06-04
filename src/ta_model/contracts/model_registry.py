"""Auditable S7 MLflow model-registry metadata contracts.

Traceability:
- FR-008: maps training-run lineage into governed candidate registry entries.
- FR-019: preserves rollback pointers and human approval metadata for promotion states.
- NFR-005: deterministic IDs and hashes support replayable registry audit evidence.

Scope:
- S7-003 registry metadata/state foundations only. No candidate forecasting,
  validation reporting, model serving, online updates, auto-promotion, live capital,
  leverage, margin, shorting, derivatives, or risk-engine bypass is introduced here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.datasets import build_dataset_snapshot_id
from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString
from ta_model.contracts.training import (
    TrainingArtifactReference,
    TrainingMetric,
    TrainingRunResult,
    build_training_config_id,
    build_training_run_id,
    validate_code_commit,
)


class ModelRegistryState(StrEnum):
    """Governed model-registry lifecycle states."""

    CANDIDATE = "candidate"
    CHAMPION = "champion"
    SHADOW = "shadow"
    ARCHIVE = "archive"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    """Human review outcomes for state changes and entries."""

    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class MlflowRegistryReference(ContractModel):
    """Project-owned MLflow URI metadata without depending on MLflow objects."""

    tracking_uri: NonEmptyString
    experiment_name: NonEmptyString
    run_id: NonEmptyString
    run_uri: NonEmptyString
    artifact_uri: NonEmptyString
    registered_model_name: NonEmptyString
    model_version: NonEmptyString
    model_uri: NonEmptyString


class RegistryReviewMetadata(ContractModel):
    """Actor/timestamp/reason metadata for human registry review."""

    reviewed_by: NonEmptyString
    reviewed_at: AwareDatetime
    decision: ReviewDecision
    reason: NonEmptyString
    checklist_id: CanonicalId | None = None


class RegistryApprovalMetadata(ContractModel):
    """Explicit human approval metadata for promotion-capable states."""

    approved_by: NonEmptyString
    approved_at: AwareDatetime
    reason: NonEmptyString
    approval_id: CanonicalId


class RegistryRollbackPointer(ContractModel):
    """Rollback target required for champion/shadow state evidence."""

    rollback_pointer_id: CanonicalId
    target_model_version_id: CanonicalId
    target_registry_record_id: CanonicalId
    target_state: ModelRegistryState
    reason: NonEmptyString

    @model_validator(mode="after")
    def pointer_identity_is_deterministic(self) -> Self:
        expected_id = build_rollback_pointer_id(
            target_model_version_id=self.target_model_version_id,
            target_registry_record_id=self.target_registry_record_id,
            target_state=self.target_state,
            reason=self.reason,
        )
        if self.rollback_pointer_id != expected_id:
            raise ValueError("rollback_pointer_id is not deterministic")
        return self


class ModelRegistryRecord(ContractModel):
    """Auditable registry record derived from a TrainingRunResult."""

    registry_record_id: CanonicalId
    registry_record_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_version_id: CanonicalId
    source_model_version_id: CanonicalId | None = None
    source_model_version_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    model_name: NonEmptyString
    model_version: NonEmptyString
    training_run_id: CanonicalId
    training_run_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_snapshot_id: CanonicalId
    dataset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_config_id: CanonicalId
    training_config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_commit: NonEmptyString
    seed: int = Field(ge=0)
    metrics: tuple[TrainingMetric, ...]
    artifacts: tuple[TrainingArtifactReference, ...]
    current_state: ModelRegistryState
    mlflow: MlflowRegistryReference
    created_by: NonEmptyString
    created_at: AwareDatetime
    state_reason: NonEmptyString
    rollback_pointer: RegistryRollbackPointer | None = None
    review: RegistryReviewMetadata | None = None
    approval: RegistryApprovalMetadata | None = None
    auto_promotion_enabled: Literal[False] = False

    @model_validator(mode="after")
    def record_is_fail_closed_and_deterministic(self) -> Self:
        validate_code_commit(self.code_commit)
        if not self.metrics:
            raise ValueError("registry records require at least one metric")
        if not self.artifacts:
            raise ValueError("registry records require at least one artifact reference")
        if self.training_run_id != build_training_run_id(training_run_hash=self.training_run_hash):
            raise ValueError("training_run_id does not match training_run_hash")
        if self.training_config_id != build_training_config_id(
            training_config_hash=self.training_config_hash
        ):
            raise ValueError("training_config_id does not match training_config_hash")
        if self.dataset_snapshot_id != build_dataset_snapshot_id(dataset_hash=self.dataset_hash):
            raise ValueError("dataset_snapshot_id does not match dataset_hash")
        if self.mlflow.registered_model_name != self.model_name:
            raise ValueError("mlflow registered_model_name must match model_name")
        if self.mlflow.model_version != self.model_version:
            raise ValueError("mlflow model_version must match model_version")
        if (self.source_model_version_id is None) != (self.source_model_version_hash is None):
            raise ValueError("source model version lineage requires both id and hash")
        _validate_governance_metadata(
            state=self.current_state,
            rollback_pointer=self.rollback_pointer,
            review=self.review,
            approval=self.approval,
        )
        expected_model_version_id = build_model_version_id(
            model_name=self.model_name,
            model_version=self.model_version,
            training_run_hash=self.training_run_hash,
        )
        if self.model_version_id != expected_model_version_id:
            raise ValueError("model_version_id is not deterministic")
        expected_hash = build_registry_record_hash(
            model_version_id=self.model_version_id,
            source_model_version_id=self.source_model_version_id,
            source_model_version_hash=self.source_model_version_hash,
            model_name=self.model_name,
            model_version=self.model_version,
            training_run_id=self.training_run_id,
            training_run_hash=self.training_run_hash,
            dataset_snapshot_id=self.dataset_snapshot_id,
            dataset_hash=self.dataset_hash,
            training_config_id=self.training_config_id,
            training_config_hash=self.training_config_hash,
            code_commit=self.code_commit,
            seed=self.seed,
            metrics=self.metrics,
            artifacts=self.artifacts,
            current_state=self.current_state,
            mlflow=self.mlflow,
            created_by=self.created_by,
            created_at=self.created_at,
            state_reason=self.state_reason,
            rollback_pointer=self.rollback_pointer,
            review=self.review,
            approval=self.approval,
        )
        if self.registry_record_hash != expected_hash:
            raise ValueError("registry_record_hash is not deterministic")
        if self.registry_record_id != build_registry_record_id(registry_record_hash=expected_hash):
            raise ValueError("registry_record_id is not deterministic")
        return self


class ModelRegistryTransition(ContractModel):
    """Auditable state transition request; never autonomous promotion."""

    transition_id: CanonicalId
    transition_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    registry_record_id: CanonicalId
    model_version_id: CanonicalId
    from_state: ModelRegistryState
    to_state: ModelRegistryState
    actor: NonEmptyString
    occurred_at: AwareDatetime
    reason: NonEmptyString
    rollback_pointer: RegistryRollbackPointer | None = None
    review: RegistryReviewMetadata | None = None
    approval: RegistryApprovalMetadata | None = None
    auto_promotion_enabled: Literal[False] = False

    @model_validator(mode="after")
    def transition_is_fail_closed_and_deterministic(self) -> Self:
        if self.from_state == self.to_state:
            raise ValueError("registry transitions must change state")
        if self.to_state is ModelRegistryState.CANDIDATE:
            raise ValueError("candidate state is created as a record, not promoted by transition")
        terminal_states = {ModelRegistryState.ARCHIVE, ModelRegistryState.REJECTED}
        promotion_states = {ModelRegistryState.CHAMPION, ModelRegistryState.SHADOW}
        if self.from_state in terminal_states and self.to_state in promotion_states:
            message = "archive/rejected records cannot transition directly to champion or shadow"
            raise ValueError(message)
        _validate_governance_metadata(
            state=self.to_state,
            rollback_pointer=self.rollback_pointer,
            review=self.review,
            approval=self.approval,
        )
        expected_hash = build_registry_transition_hash(
            registry_record_id=self.registry_record_id,
            model_version_id=self.model_version_id,
            from_state=self.from_state,
            to_state=self.to_state,
            actor=self.actor,
            occurred_at=self.occurred_at,
            reason=self.reason,
            rollback_pointer=self.rollback_pointer,
            review=self.review,
            approval=self.approval,
        )
        if self.transition_hash != expected_hash:
            raise ValueError("transition_hash is not deterministic")
        if self.transition_id != build_registry_transition_id(transition_hash=expected_hash):
            raise ValueError("transition_id is not deterministic")
        return self


def build_candidate_registry_record(
    *,
    training_run: TrainingRunResult,
    model_name: str,
    model_version: str,
    mlflow: MlflowRegistryReference,
    created_by: str,
    created_at: datetime,
    state_reason: str,
    source_model_version_id: str | None = None,
    source_model_version_hash: str | None = None,
) -> ModelRegistryRecord:
    """Create a deterministic candidate record from training lineage."""

    return build_model_registry_record(
        training_run=training_run,
        model_name=model_name,
        model_version=model_version,
        current_state=ModelRegistryState.CANDIDATE,
        mlflow=mlflow,
        created_by=created_by,
        created_at=created_at,
        state_reason=state_reason,
        source_model_version_id=source_model_version_id,
        source_model_version_hash=source_model_version_hash,
    )


def build_model_registry_record(
    *,
    training_run: TrainingRunResult,
    model_name: str,
    model_version: str,
    current_state: ModelRegistryState,
    mlflow: MlflowRegistryReference,
    created_by: str,
    created_at: datetime,
    state_reason: str,
    source_model_version_id: str | None = None,
    source_model_version_hash: str | None = None,
    rollback_pointer: RegistryRollbackPointer | None = None,
    review: RegistryReviewMetadata | None = None,
    approval: RegistryApprovalMetadata | None = None,
) -> ModelRegistryRecord:
    model_version_id = build_model_version_id(
        model_name=model_name,
        model_version=model_version,
        training_run_hash=training_run.training_run_hash,
    )
    record_hash = build_registry_record_hash(
        model_version_id=model_version_id,
        source_model_version_id=source_model_version_id,
        source_model_version_hash=source_model_version_hash,
        model_name=model_name,
        model_version=model_version,
        training_run_id=training_run.training_run_id,
        training_run_hash=training_run.training_run_hash,
        dataset_snapshot_id=training_run.dataset_snapshot_id,
        dataset_hash=training_run.dataset_hash,
        training_config_id=training_run.training_config.training_config_id,
        training_config_hash=training_run.training_config.training_config_hash,
        code_commit=training_run.code_commit,
        seed=training_run.seed,
        metrics=training_run.metrics,
        artifacts=training_run.artifacts,
        current_state=current_state,
        mlflow=mlflow,
        created_by=created_by,
        created_at=created_at,
        state_reason=state_reason,
        rollback_pointer=rollback_pointer,
        review=review,
        approval=approval,
    )
    return ModelRegistryRecord(
        registry_record_id=build_registry_record_id(registry_record_hash=record_hash),
        registry_record_hash=record_hash,
        model_version_id=model_version_id,
        source_model_version_id=source_model_version_id,
        source_model_version_hash=source_model_version_hash,
        model_name=model_name,
        model_version=model_version,
        training_run_id=training_run.training_run_id,
        training_run_hash=training_run.training_run_hash,
        dataset_snapshot_id=training_run.dataset_snapshot_id,
        dataset_hash=training_run.dataset_hash,
        training_config_id=training_run.training_config.training_config_id,
        training_config_hash=training_run.training_config.training_config_hash,
        code_commit=training_run.code_commit,
        seed=training_run.seed,
        metrics=training_run.metrics,
        artifacts=training_run.artifacts,
        current_state=current_state,
        mlflow=mlflow,
        created_by=created_by,
        created_at=created_at,
        state_reason=state_reason,
        rollback_pointer=rollback_pointer,
        review=review,
        approval=approval,
    )


def build_registry_transition(
    *,
    registry_record_id: str,
    model_version_id: str,
    from_state: ModelRegistryState,
    to_state: ModelRegistryState,
    actor: str,
    occurred_at: datetime,
    reason: str,
    rollback_pointer: RegistryRollbackPointer | None = None,
    review: RegistryReviewMetadata | None = None,
    approval: RegistryApprovalMetadata | None = None,
) -> ModelRegistryTransition:
    transition_hash = build_registry_transition_hash(
        registry_record_id=registry_record_id,
        model_version_id=model_version_id,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        occurred_at=occurred_at,
        reason=reason,
        rollback_pointer=rollback_pointer,
        review=review,
        approval=approval,
    )
    return ModelRegistryTransition(
        transition_id=build_registry_transition_id(transition_hash=transition_hash),
        transition_hash=transition_hash,
        registry_record_id=registry_record_id,
        model_version_id=model_version_id,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        occurred_at=occurred_at,
        reason=reason,
        rollback_pointer=rollback_pointer,
        review=review,
        approval=approval,
    )


def build_rollback_pointer(
    *,
    target_model_version_id: str,
    target_registry_record_id: str,
    target_state: ModelRegistryState,
    reason: str,
) -> RegistryRollbackPointer:
    return RegistryRollbackPointer(
        rollback_pointer_id=build_rollback_pointer_id(
            target_model_version_id=target_model_version_id,
            target_registry_record_id=target_registry_record_id,
            target_state=target_state,
            reason=reason,
        ),
        target_model_version_id=target_model_version_id,
        target_registry_record_id=target_registry_record_id,
        target_state=target_state,
        reason=reason,
    )


def build_model_version_id(*, model_name: str, model_version: str, training_run_hash: str) -> str:
    return _stable_id(
        "MODELVERSION",
        {
            "model_name": model_name,
            "model_version": model_version,
            "training_run_hash": training_run_hash,
        },
    )


def build_registry_record_id(*, registry_record_hash: str) -> str:
    return _stable_id("REGISTRYRECORD", {"registry_record_hash": registry_record_hash})


def build_registry_transition_id(*, transition_hash: str) -> str:
    return _stable_id("REGISTRYTRANSITION", {"transition_hash": transition_hash})


def build_rollback_pointer_id(
    *,
    target_model_version_id: str,
    target_registry_record_id: str,
    target_state: ModelRegistryState,
    reason: str,
) -> str:
    return _stable_id(
        "ROLLBACKPTR",
        {
            "reason": reason,
            "target_model_version_id": target_model_version_id,
            "target_registry_record_id": target_registry_record_id,
            "target_state": target_state.value,
        },
    )


def build_registry_record_hash(
    *,
    model_version_id: str,
    model_name: str,
    model_version: str,
    training_run_id: str,
    training_run_hash: str,
    dataset_snapshot_id: str,
    dataset_hash: str,
    training_config_id: str,
    training_config_hash: str,
    code_commit: str,
    seed: int,
    metrics: tuple[TrainingMetric, ...],
    artifacts: tuple[TrainingArtifactReference, ...],
    current_state: ModelRegistryState,
    mlflow: MlflowRegistryReference,
    created_by: str,
    created_at: datetime,
    state_reason: str,
    source_model_version_id: str | None = None,
    source_model_version_hash: str | None = None,
    rollback_pointer: RegistryRollbackPointer | None = None,
    review: RegistryReviewMetadata | None = None,
    approval: RegistryApprovalMetadata | None = None,
) -> str:
    payload = {
        "approval": _optional_model_json(approval),
        "artifacts": tuple(_model_json(artifact) for artifact in artifacts),
        "code_commit": validate_code_commit(code_commit),
        "created_at": created_at.isoformat(),
        "created_by": created_by,
        "current_state": current_state.value,
        "dataset_hash": dataset_hash,
        "dataset_snapshot_id": dataset_snapshot_id,
        "metrics": tuple(_model_json(metric) for metric in metrics),
        "mlflow": _model_json(mlflow),
        "model_name": model_name,
        "model_version": model_version,
        "model_version_id": model_version_id,
        "review": _optional_model_json(review),
        "rollback_pointer": _optional_model_json(rollback_pointer),
        "seed": seed,
        "state_reason": state_reason,
        "training_config_hash": training_config_hash,
        "training_config_id": training_config_id,
        "training_run_hash": training_run_hash,
        "training_run_id": training_run_id,
    }
    if source_model_version_id is not None or source_model_version_hash is not None:
        payload["source_model_version_hash"] = source_model_version_hash
        payload["source_model_version_id"] = source_model_version_id
    return _hash(payload)


def build_registry_transition_hash(
    *,
    registry_record_id: str,
    model_version_id: str,
    from_state: ModelRegistryState,
    to_state: ModelRegistryState,
    actor: str,
    occurred_at: datetime,
    reason: str,
    rollback_pointer: RegistryRollbackPointer | None,
    review: RegistryReviewMetadata | None,
    approval: RegistryApprovalMetadata | None,
) -> str:
    return _hash(
        {
            "actor": actor,
            "approval": _optional_model_json(approval),
            "from_state": from_state.value,
            "model_version_id": model_version_id,
            "occurred_at": occurred_at.isoformat(),
            "reason": reason,
            "registry_record_id": registry_record_id,
            "review": _optional_model_json(review),
            "rollback_pointer": _optional_model_json(rollback_pointer),
            "to_state": to_state.value,
        }
    )


def _validate_governance_metadata(
    *,
    state: ModelRegistryState,
    rollback_pointer: RegistryRollbackPointer | None,
    review: RegistryReviewMetadata | None,
    approval: RegistryApprovalMetadata | None,
) -> None:
    if state in {ModelRegistryState.CHAMPION, ModelRegistryState.SHADOW}:
        if rollback_pointer is None:
            raise ValueError("champion/shadow states require rollback_pointer")
        if review is None or approval is None:
            raise ValueError("champion/shadow states require review and approval metadata")
        if review.decision is not ReviewDecision.APPROVED:
            raise ValueError("champion/shadow review decision must be approved")
        if review.reviewed_by == approval.approved_by:
            raise ValueError("champion/shadow reviewer and approver must be distinct")
        if approval.approved_at < review.reviewed_at:
            raise ValueError("champion/shadow approval timestamp must not precede review")
    if state is ModelRegistryState.REJECTED:
        if review is None or review.decision is not ReviewDecision.REJECTED:
            raise ValueError("rejected state requires rejected review metadata")
        if approval is not None:
            raise ValueError("rejected state must not include approval metadata")
    if state is ModelRegistryState.CANDIDATE and approval is not None:
        raise ValueError("candidate state must not include promotion approval metadata")


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())


def _optional_model_json(model: ContractModel | None) -> object | None:
    if model is None:
        return None
    return _model_json(model)
