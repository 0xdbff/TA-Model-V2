"""Evidence for S7-003 MLflow registry state and rollback metadata contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import ValidationError

from ta_model.contracts.datasets import DatasetSplit, build_dataset_snapshot_id
from ta_model.contracts.model_registry import (
    MlflowRegistryReference,
    ModelRegistryRecord,
    ModelRegistryState,
    RegistryApprovalMetadata,
    RegistryReviewMetadata,
    ReviewDecision,
    build_candidate_registry_record,
    build_model_registry_record,
    build_registry_record_hash,
    build_registry_record_id,
    build_registry_transition,
    build_rollback_pointer,
)
from ta_model.contracts.training import (
    TrainingArtifactReference,
    TrainingMetric,
    TrainingRunResult,
    TrainingRunStatus,
    build_training_artifact_reference,
    build_training_config,
    build_training_run_hash,
    build_training_run_id,
)

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
CODE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def test_candidate_registry_record_maps_training_lineage_and_is_deterministic() -> None:
    training_run = _training_run()
    first = build_candidate_registry_record(
        training_run=training_run,
        model_name="s7-reference-model",
        model_version="1",
        mlflow=_mlflow_reference(),
        created_by="registry-operator",
        created_at=NOW,
        state_reason="initial candidate registration after reproducible training run",
    )
    second = build_candidate_registry_record(
        training_run=training_run,
        model_name="s7-reference-model",
        model_version="1",
        mlflow=_mlflow_reference(),
        created_by="registry-operator",
        created_at=NOW,
        state_reason="initial candidate registration after reproducible training run",
    )

    assert first.registry_record_id == second.registry_record_id
    assert first.registry_record_hash == second.registry_record_hash
    assert first.model_version_id == second.model_version_id
    assert first.current_state is ModelRegistryState.CANDIDATE
    assert first.training_run_id == training_run.training_run_id
    assert first.training_run_hash == training_run.training_run_hash
    assert first.dataset_snapshot_id == training_run.dataset_snapshot_id
    assert first.dataset_hash == training_run.dataset_hash
    assert first.training_config_id == training_run.training_config.training_config_id
    assert first.training_config_hash == training_run.training_config.training_config_hash
    assert first.auto_promotion_enabled is False


def test_champion_registry_record_requires_approved_review_and_rollback_pointer() -> None:
    candidate = _candidate_record()
    rollback_pointer = build_rollback_pointer(
        target_model_version_id=candidate.model_version_id,
        target_registry_record_id=candidate.registry_record_id,
        target_state=ModelRegistryState.CANDIDATE,
        reason="restore prior candidate if champion gate is rolled back",
    )
    champion = build_model_registry_record(
        training_run=_training_run(),
        model_name="s7-reference-model",
        model_version="2",
        current_state=ModelRegistryState.CHAMPION,
        mlflow=_mlflow_reference(model_version="2"),
        created_by="registry-operator",
        created_at=NOW,
        state_reason="human-approved champion metadata fixture",
        rollback_pointer=rollback_pointer,
        review=_review(ReviewDecision.APPROVED),
        approval=_approval(),
    )

    assert champion.current_state is ModelRegistryState.CHAMPION
    assert champion.rollback_pointer == rollback_pointer
    assert champion.review is not None
    assert champion.review.decision is ReviewDecision.APPROVED
    assert champion.approval is not None
    assert champion.auto_promotion_enabled is False


def test_champion_and_shadow_fail_closed_without_rollback_review_or_approval() -> None:
    with pytest.raises(ValidationError, match="champion/shadow states require rollback_pointer"):
        build_model_registry_record(
            training_run=_training_run(),
            model_name="s7-reference-model",
            model_version="2",
            current_state=ModelRegistryState.CHAMPION,
            mlflow=_mlflow_reference(model_version="2"),
            created_by="registry-operator",
            created_at=NOW,
            state_reason="invalid champion fixture",
        )

    candidate = _candidate_record()
    rollback_pointer = build_rollback_pointer(
        target_model_version_id=candidate.model_version_id,
        target_registry_record_id=candidate.registry_record_id,
        target_state=ModelRegistryState.CANDIDATE,
        reason="rollback target for invalid shadow fixture",
    )
    with pytest.raises(ValidationError, match="champion/shadow states require review and approval"):
        build_model_registry_record(
            training_run=_training_run(),
            model_name="s7-reference-model",
            model_version="3",
            current_state=ModelRegistryState.SHADOW,
            mlflow=_mlflow_reference(model_version="3"),
            created_by="registry-operator",
            created_at=NOW,
            state_reason="invalid shadow fixture",
            rollback_pointer=rollback_pointer,
        )


def test_invalid_transition_and_auto_promotion_are_rejected() -> None:
    candidate = _candidate_record()
    with pytest.raises(ValidationError, match="candidate state is created as a record"):
        build_registry_transition(
            registry_record_id=candidate.registry_record_id,
            model_version_id=candidate.model_version_id,
            from_state=ModelRegistryState.REJECTED,
            to_state=ModelRegistryState.CANDIDATE,
            actor="registry-operator",
            occurred_at=NOW,
            reason="invalid resurrection to candidate",
        )

    with pytest.raises(ValidationError):
        ModelRegistryRecord.model_validate(
            {**candidate.model_dump(mode="json"), "auto_promotion_enabled": True}
        )


def test_transition_to_champion_is_deterministic_and_requires_human_metadata() -> None:
    candidate = _candidate_record()
    rollback_pointer = build_rollback_pointer(
        target_model_version_id=candidate.model_version_id,
        target_registry_record_id=candidate.registry_record_id,
        target_state=ModelRegistryState.CANDIDATE,
        reason="rollback champion to candidate fixture",
    )
    first = build_registry_transition(
        registry_record_id=candidate.registry_record_id,
        model_version_id=candidate.model_version_id,
        from_state=ModelRegistryState.CANDIDATE,
        to_state=ModelRegistryState.CHAMPION,
        actor="registry-operator",
        occurred_at=NOW,
        reason="human-approved champion transition fixture",
        rollback_pointer=rollback_pointer,
        review=_review(ReviewDecision.APPROVED),
        approval=_approval(),
    )
    second = build_registry_transition(
        registry_record_id=candidate.registry_record_id,
        model_version_id=candidate.model_version_id,
        from_state=ModelRegistryState.CANDIDATE,
        to_state=ModelRegistryState.CHAMPION,
        actor="registry-operator",
        occurred_at=NOW,
        reason="human-approved champion transition fixture",
        rollback_pointer=rollback_pointer,
        review=_review(ReviewDecision.APPROVED),
        approval=_approval(),
    )

    assert first.transition_id == second.transition_id
    assert first.transition_hash == second.transition_hash
    assert first.auto_promotion_enabled is False

    with pytest.raises(ValidationError, match="champion/shadow states require rollback_pointer"):
        build_registry_transition(
            registry_record_id=candidate.registry_record_id,
            model_version_id=candidate.model_version_id,
            from_state=ModelRegistryState.CANDIDATE,
            to_state=ModelRegistryState.CHAMPION,
            actor="registry-operator",
            occurred_at=NOW,
            reason="invalid autonomous champion transition",
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ({"training_run_id": "TRAINRUN:BADBADBADBADBADBADBADBADBADBAD12"}, "training_run_id"),
        (
            {"training_config_id": "TRAINCONFIG:BADBADBADBADBADBADBADBADBADBAD"},
            "training_config_id",
        ),
        (
            {"dataset_snapshot_id": "DATASETSNAPSHOT:BADBADBADBADBADBADBADBADBAD"},
            "dataset_snapshot_id",
        ),
        ({"mlflow": {"registered_model_name": "different-model"}}, "registered_model_name"),
        ({"mlflow": {"model_version": "99"}}, "model_version"),
    ),
)
def test_rebuilt_record_identity_still_rejects_lineage_mismatches(
    mutation: dict[str, object], match: str
) -> None:
    payload = _candidate_record().model_dump(mode="json")
    _deep_update(payload, mutation)
    _rebuild_record_identity(payload)

    with pytest.raises(ValidationError, match=match):
        ModelRegistryRecord.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (({"metrics": []}, "at least one metric"), ({"artifacts": []}, "artifact reference")),
)
def test_registry_record_requires_metrics_and_artifacts(
    mutation: dict[str, object], match: str
) -> None:
    payload = _candidate_record().model_dump(mode="json")
    _deep_update(payload, mutation)
    _rebuild_record_identity(payload)

    with pytest.raises(ValidationError, match=match):
        ModelRegistryRecord.model_validate(payload)


def test_champion_shadow_reviewer_and_approver_must_be_distinct() -> None:
    candidate = _candidate_record()
    rollback_pointer = build_rollback_pointer(
        target_model_version_id=candidate.model_version_id,
        target_registry_record_id=candidate.registry_record_id,
        target_state=ModelRegistryState.CANDIDATE,
        reason="rollback target for governance fixture",
    )

    with pytest.raises(ValidationError, match="reviewer and approver must be distinct"):
        build_model_registry_record(
            training_run=_training_run(),
            model_name="s7-reference-model",
            model_version="2",
            current_state=ModelRegistryState.CHAMPION,
            mlflow=_mlflow_reference(model_version="2"),
            created_by="registry-operator",
            created_at=NOW,
            state_reason="invalid same-actor champion metadata fixture",
            rollback_pointer=rollback_pointer,
            review=_review(ReviewDecision.APPROVED),
            approval=_approval(approved_by="model-risk-reviewer"),
        )


def test_champion_shadow_approval_timestamp_must_not_precede_review() -> None:
    candidate = _candidate_record()
    rollback_pointer = build_rollback_pointer(
        target_model_version_id=candidate.model_version_id,
        target_registry_record_id=candidate.registry_record_id,
        target_state=ModelRegistryState.CANDIDATE,
        reason="rollback target for timestamp fixture",
    )

    with pytest.raises(ValidationError, match="approval timestamp must not precede review"):
        build_model_registry_record(
            training_run=_training_run(),
            model_name="s7-reference-model",
            model_version="2",
            current_state=ModelRegistryState.SHADOW,
            mlflow=_mlflow_reference(model_version="2"),
            created_by="registry-operator",
            created_at=NOW,
            state_reason="invalid approval timestamp shadow fixture",
            rollback_pointer=rollback_pointer,
            review=_review(ReviewDecision.APPROVED),
            approval=_approval(approved_at=datetime(2026, 5, 1, 11, 59, tzinfo=UTC)),
        )


def _candidate_record() -> ModelRegistryRecord:
    return build_candidate_registry_record(
        training_run=_training_run(),
        model_name="s7-reference-model",
        model_version="1",
        mlflow=_mlflow_reference(),
        created_by="registry-operator",
        created_at=NOW,
        state_reason="initial candidate registration after reproducible training run",
    )


def _training_run() -> TrainingRunResult:
    config = build_training_config(name="s7-003-reference", seed=7)
    dataset_hash = "a" * 64
    dataset_snapshot_id = build_dataset_snapshot_id(dataset_hash=dataset_hash)
    metrics = (
        TrainingMetric(name="train_label_mean", split=DatasetSplit.TRAIN, value=Decimal("0.10")),
        TrainingMetric(
            name="validation_mae", split=DatasetSplit.VALIDATION, value=Decimal("0.02")
        ),
    )
    artifacts = (
        build_training_artifact_reference(
            name="reference_model",
            uri="s3://ta-model-v2-mlflow-artifacts/local/reference-model.json",
            payload={"kind": "reference", "seed": 7},
        ),
    )
    run_hash = build_training_run_hash(
        dataset_snapshot_id=dataset_snapshot_id,
        dataset_hash=dataset_hash,
        training_config=config,
        code_commit=CODE_COMMIT,
        seed=config.seed,
        status=TrainingRunStatus.RUNNER_EVIDENCE_ONLY,
        metrics=metrics,
        artifacts=artifacts,
    )
    return TrainingRunResult(
        training_run_id=build_training_run_id(training_run_hash=run_hash),
        training_run_hash=run_hash,
        dataset_snapshot_id=dataset_snapshot_id,
        dataset_hash=dataset_hash,
        training_config=config,
        code_commit=CODE_COMMIT,
        seed=config.seed,
        metrics=metrics,
        artifacts=artifacts,
    )


def _mlflow_reference(*, model_version: str = "1") -> MlflowRegistryReference:
    return MlflowRegistryReference(
        tracking_uri="http://mlflow:5000",
        experiment_name="s7-registry-foundations",
        run_id="mlflow-run-s7-003-fixture",
        run_uri="mlflow://experiments/s7-registry-foundations/runs/mlflow-run-s7-003-fixture",
        artifact_uri="s3://ta-model-v2-mlflow-artifacts/local/mlflow-run-s7-003-fixture",
        registered_model_name="s7-reference-model",
        model_version=model_version,
        model_uri=f"models:/s7-reference-model/{model_version}",
    )


def _review(decision: ReviewDecision) -> RegistryReviewMetadata:
    return RegistryReviewMetadata(
        reviewed_by="model-risk-reviewer",
        reviewed_at=NOW,
        decision=decision,
        reason="reviewed fixture metadata and rollback evidence",
        checklist_id="CHECKLIST:S7-003-REVIEW",
    )


def _approval(
    *, approved_by: str = "model-governance-owner", approved_at: datetime = NOW
) -> RegistryApprovalMetadata:
    return RegistryApprovalMetadata(
        approved_by=approved_by,
        approved_at=approved_at,
        reason="approved fixture promotion metadata with rollback pointer",
        approval_id="APPROVAL:S7-003-CHAMPION-FIXTURE",
    )


def _deep_update(payload: dict[str, object], mutation: dict[str, object]) -> None:
    for key, value in mutation.items():
        current = payload.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            _deep_update(current, value)
        else:
            payload[key] = value


def _rebuild_record_identity(payload: dict[str, object]) -> None:
    metrics_payload = cast("list[dict[str, Any]]", payload["metrics"])
    artifacts_payload = cast("list[dict[str, Any]]", payload["artifacts"])
    record_hash = build_registry_record_hash(
        model_version_id=str(payload["model_version_id"]),
        model_name=str(payload["model_name"]),
        model_version=str(payload["model_version"]),
        training_run_id=str(payload["training_run_id"]),
        training_run_hash=str(payload["training_run_hash"]),
        dataset_snapshot_id=str(payload["dataset_snapshot_id"]),
        dataset_hash=str(payload["dataset_hash"]),
        training_config_id=str(payload["training_config_id"]),
        training_config_hash=str(payload["training_config_hash"]),
        code_commit=str(payload["code_commit"]),
        seed=int(cast("int | str", payload["seed"])),
        metrics=tuple(TrainingMetric.model_validate(metric) for metric in metrics_payload),
        artifacts=tuple(
            TrainingArtifactReference.model_validate(artifact) for artifact in artifacts_payload
        ),
        current_state=ModelRegistryState(str(payload["current_state"])),
        mlflow=MlflowRegistryReference.model_validate(payload["mlflow"]),
        created_by=str(payload["created_by"]),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        state_reason=str(payload["state_reason"]),
        rollback_pointer=None,
        review=None,
        approval=None,
    )
    payload["registry_record_hash"] = record_hash
    payload["registry_record_id"] = build_registry_record_id(registry_record_hash=record_hash)
