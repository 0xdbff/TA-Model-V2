"""Audit gate validation reports over replay-by-trace evidence.

Traceability:
- FR-015: gate samples are replayed from explicit trace IDs through the audit
  replay harness before being counted as validation evidence.
- NFR-004: blockers preserve trace/replay failure details instead of hiding
  failed or no-order decisions.
- NFR-005: run/config/manifest/report identifiers are deterministic so the same
  stored evidence and configuration reproduce the same gate evidence.

Scope:
- Local typed contracts and pure report builders only. No datastore, network,
  Docker/runtime service, live capital, leverage, derivatives, or dependency
  changes are introduced.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from ta_model.audit.replay import (
    DecisionTraceEvidenceResolver,
    DecisionTraceReplayReport,
    DecisionTraceReplayStatus,
    replay_decision_trace_by_id,
)
from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString

_AUDIT_GATE_REQUIREMENTS = ("FR-015", "NFR-004", "NFR-005")
_HASH_RE = r"^[a-f0-9]{64}$"


class AuditGateSampleMethod(StrEnum):
    """Supported audit sample selection methods for the MVP gate."""

    EXPLICIT_TRACE_IDS = "explicit_trace_ids"


class AuditGateToleranceMode(StrEnum):
    """Supported replay comparison tolerance policies."""

    EXACT = "exact"


class AuditGateValidationStatus(StrEnum):
    """Terminal audit gate report status."""

    PASSED = "passed"
    FAILED = "failed"


class AuditGateRecommendation(StrEnum):
    """Human-readable recommendation derived from gate blockers."""

    READY_FOR_REVIEW = "ready_for_audit_review"
    BLOCKED = "blocked_until_replay_blockers_resolved"


class AuditGateValidationBlockerCode(StrEnum):
    """Gate-level failure codes."""

    SAMPLE_REPLAY_FAILED = "sample_replay_failed"
    SAMPLE_POLICY_NOT_MET = "sample_policy_not_met"


class AuditGateSamplePolicy(ContractModel):
    """How audit gate samples were selected and what coverage is required."""

    method: AuditGateSampleMethod = AuditGateSampleMethod.EXPLICIT_TRACE_IDS
    description: NonEmptyString = "explicit deterministic S11 trace sample"
    minimum_sample_count: int = Field(default=1, ge=0)
    require_no_order_sample: bool = False
    require_all_replays_passing: bool = True


class AuditGateTolerancePolicy(ContractModel):
    """How replay metrics are compared for reproducibility."""

    mode: AuditGateToleranceMode = AuditGateToleranceMode.EXACT
    metric_tolerance: NonEmptyString = "0"
    description: NonEmptyString = "exact equality for deterministic fixture replay"


class AuditGateRunConfig(ContractModel):
    """Deterministic gate configuration independent from selected trace IDs."""

    config_hash: str = Field(pattern=_HASH_RE)
    code_commit: NonEmptyString
    code_ref: NonEmptyString
    sample_policy: AuditGateSamplePolicy = Field(default_factory=AuditGateSamplePolicy)
    tolerance_policy: AuditGateTolerancePolicy = Field(default_factory=AuditGateTolerancePolicy)
    requirement_ids: tuple[NonEmptyString, ...] = _AUDIT_GATE_REQUIREMENTS

    @model_validator(mode="after")
    def config_hash_is_deterministic(self) -> Self:
        expected_hash = build_audit_gate_config_hash(config=self)
        if self.config_hash != expected_hash:
            raise ValueError("config_hash is not deterministic")
        return self


class AuditGateRunManifest(ContractModel):
    """Deterministic run manifest for one explicit trace sample set."""

    audit_run_id: CanonicalId
    manifest_hash: str = Field(pattern=_HASH_RE)
    config_hash: str = Field(pattern=_HASH_RE)
    code_commit: NonEmptyString
    code_ref: NonEmptyString
    sample_policy: AuditGateSamplePolicy
    tolerance_policy: AuditGateTolerancePolicy
    trace_ids: tuple[CanonicalId, ...] = ()
    requirement_ids: tuple[NonEmptyString, ...] = _AUDIT_GATE_REQUIREMENTS

    @model_validator(mode="after")
    def manifest_identity_is_deterministic(self) -> Self:
        config_draft = AuditGateRunConfig.model_construct(
            config_hash=self.config_hash,
            code_commit=self.code_commit,
            code_ref=self.code_ref,
            sample_policy=self.sample_policy,
            tolerance_policy=self.tolerance_policy,
            requirement_ids=self.requirement_ids,
        )
        expected_config_hash = build_audit_gate_config_hash(config=config_draft)
        if self.config_hash != expected_config_hash:
            raise ValueError("manifest config_hash does not match embedded config")
        expected_hash = build_audit_gate_run_manifest_hash(manifest=self)
        if self.manifest_hash != expected_hash:
            raise ValueError("manifest_hash is not deterministic")
        if self.audit_run_id != build_audit_run_id(manifest_hash=expected_hash):
            raise ValueError("audit_run_id is not deterministic")
        return self


class AuditGateValidationBlocker(ContractModel):
    """Gate-level blocker, optionally linked to a replay blocker."""

    code: AuditGateValidationBlockerCode
    message: NonEmptyString
    trace_id: CanonicalId | None = None
    replay_blocker_code: NonEmptyString | None = None
    expected: NonEmptyString | None = None
    actual: NonEmptyString | None = None


class AuditGateTraceSampleResult(ContractModel):
    """One sampled trace plus the replay report used as gate evidence."""

    sample_result_id: CanonicalId
    sample_result_hash: str = Field(pattern=_HASH_RE)
    sample_index: int = Field(ge=0)
    trace_id: CanonicalId
    replay_status: DecisionTraceReplayStatus
    replay_report_id: CanonicalId
    replay_report_hash: str = Field(pattern=_HASH_RE)
    stored_trace_envelope_id: CanonicalId | None = None
    stored_trace_envelope_hash: str | None = Field(default=None, pattern=_HASH_RE)
    reconstructed_trace_envelope_id: CanonicalId | None = None
    reconstructed_trace_envelope_hash: str | None = Field(default=None, pattern=_HASH_RE)
    replay_report: DecisionTraceReplayReport
    requirement_ids: tuple[NonEmptyString, ...] = _AUDIT_GATE_REQUIREMENTS

    @model_validator(mode="after")
    def sample_identity_is_deterministic(self) -> Self:
        if self.trace_id != self.replay_report.trace_id:
            raise ValueError("sample trace_id must match replay report trace_id")
        if self.replay_status is not self.replay_report.status:
            raise ValueError("sample replay_status must match replay report status")
        expected_replay_hash = build_decision_trace_replay_report_hash(
            report=self.replay_report
        )
        if self.replay_report_hash != expected_replay_hash:
            raise ValueError("replay_report_hash is not deterministic")
        if self.replay_report_id != build_decision_trace_replay_report_id(
            report_hash=expected_replay_hash
        ):
            raise ValueError("replay_report_id is not deterministic")
        expected_hash = build_audit_gate_trace_sample_result_hash(sample=self)
        if self.sample_result_hash != expected_hash:
            raise ValueError("sample_result_hash is not deterministic")
        if self.sample_result_id != build_audit_gate_trace_sample_result_id(
            sample_result_hash=expected_hash
        ):
            raise ValueError("sample_result_id is not deterministic")
        return self


class AuditGateValidationReport(ContractModel):
    """Deterministic audit gate validation report for sampled replay evidence."""

    report_id: CanonicalId
    report_hash: str = Field(pattern=_HASH_RE)
    audit_run_id: CanonicalId
    manifest: AuditGateRunManifest
    sample_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    no_order_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    samples: tuple[AuditGateTraceSampleResult, ...] = ()
    blockers: tuple[AuditGateValidationBlocker, ...] = ()
    status: AuditGateValidationStatus
    recommendation: AuditGateRecommendation
    requirement_ids: tuple[NonEmptyString, ...] = _AUDIT_GATE_REQUIREMENTS

    @model_validator(mode="after")
    def report_identity_and_metrics_are_deterministic(self) -> Self:
        if self.audit_run_id != self.manifest.audit_run_id:
            raise ValueError("report audit_run_id must match manifest")
        if self.sample_count != len(self.samples):
            raise ValueError("sample_count must match samples")
        if self.passed_count != _count_samples(
            samples=self.samples, status=DecisionTraceReplayStatus.PASSED
        ):
            raise ValueError("passed_count must match samples")
        if self.no_order_count != _count_samples(
            samples=self.samples, status=DecisionTraceReplayStatus.NO_ORDER
        ):
            raise ValueError("no_order_count must match samples")
        if self.failed_count != _count_samples(
            samples=self.samples, status=DecisionTraceReplayStatus.FAILED
        ):
            raise ValueError("failed_count must match samples")
        if self.blocker_count != len(self.blockers):
            raise ValueError("blocker_count must match blockers")
        expected_status = (
            AuditGateValidationStatus.FAILED
            if self.blockers or self.failed_count
            else AuditGateValidationStatus.PASSED
        )
        if self.status is not expected_status:
            raise ValueError("status must be derived from blockers and failed_count")
        expected_recommendation = (
            AuditGateRecommendation.BLOCKED
            if expected_status is AuditGateValidationStatus.FAILED
            else AuditGateRecommendation.READY_FOR_REVIEW
        )
        if self.recommendation is not expected_recommendation:
            raise ValueError("recommendation must be derived from status")
        expected_hash = build_audit_gate_validation_report_hash(report=self)
        if self.report_hash != expected_hash:
            raise ValueError("report_hash is not deterministic")
        if self.report_id != build_audit_gate_validation_report_id(report_hash=expected_hash):
            raise ValueError("report_id is not deterministic")
        return self


def make_audit_gate_run_config(
    *,
    code_commit: str,
    code_ref: str,
    sample_policy: AuditGateSamplePolicy | None = None,
    tolerance_policy: AuditGateTolerancePolicy | None = None,
    requirement_ids: tuple[str, ...] = _AUDIT_GATE_REQUIREMENTS,
) -> AuditGateRunConfig:
    """Build a deterministic audit gate run config."""

    draft = AuditGateRunConfig.model_construct(
        config_hash="0" * 64,
        code_commit=code_commit,
        code_ref=code_ref,
        sample_policy=sample_policy or AuditGateSamplePolicy(),
        tolerance_policy=tolerance_policy or AuditGateTolerancePolicy(),
        requirement_ids=requirement_ids,
    )
    config_hash = build_audit_gate_config_hash(config=draft)
    return AuditGateRunConfig(
        **draft.model_dump(exclude={"config_hash"}),
        config_hash=config_hash,
    )


def make_audit_gate_run_manifest(
    *, config: AuditGateRunConfig, trace_ids: Sequence[str]
) -> AuditGateRunManifest:
    """Build a deterministic run manifest from config and explicit trace IDs."""

    normalized_trace_ids = tuple(_normalize_trace_id(trace_id) for trace_id in trace_ids)
    draft = AuditGateRunManifest.model_construct(
        audit_run_id="AUDITRUN:PLACEHOLDER",
        manifest_hash="0" * 64,
        config_hash=config.config_hash,
        code_commit=config.code_commit,
        code_ref=config.code_ref,
        sample_policy=config.sample_policy,
        tolerance_policy=config.tolerance_policy,
        trace_ids=normalized_trace_ids,
        requirement_ids=config.requirement_ids,
    )
    manifest_hash = build_audit_gate_run_manifest_hash(manifest=draft)
    return AuditGateRunManifest(
        **draft.model_dump(exclude={"audit_run_id", "manifest_hash"}),
        audit_run_id=build_audit_run_id(manifest_hash=manifest_hash),
        manifest_hash=manifest_hash,
    )


def run_audit_gate_validation(
    *,
    trace_ids: Sequence[str],
    resolver: DecisionTraceEvidenceResolver,
    config: AuditGateRunConfig,
) -> AuditGateValidationReport:
    """Replay explicit trace IDs and return deterministic audit gate evidence."""

    manifest = make_audit_gate_run_manifest(config=config, trace_ids=trace_ids)
    samples = tuple(
        make_audit_gate_trace_sample_result(
            sample_index=index,
            replay_report=replay_decision_trace_by_id(trace_id=trace_id, resolver=resolver),
        )
        for index, trace_id in enumerate(manifest.trace_ids)
    )
    return make_audit_gate_validation_report(manifest=manifest, samples=samples)


def make_audit_gate_trace_sample_result(
    *, sample_index: int, replay_report: DecisionTraceReplayReport
) -> AuditGateTraceSampleResult:
    """Wrap one replay report with deterministic sample IDs/hashes."""

    replay_report_hash = build_decision_trace_replay_report_hash(report=replay_report)
    draft = AuditGateTraceSampleResult.model_construct(
        sample_result_id="AUDITSAMPLE:PLACEHOLDER",
        sample_result_hash="0" * 64,
        sample_index=sample_index,
        trace_id=replay_report.trace_id,
        replay_status=replay_report.status,
        replay_report_id=build_decision_trace_replay_report_id(
            report_hash=replay_report_hash
        ),
        replay_report_hash=replay_report_hash,
        stored_trace_envelope_id=replay_report.stored_trace_envelope_id,
        stored_trace_envelope_hash=replay_report.stored_trace_envelope_hash,
        reconstructed_trace_envelope_id=replay_report.reconstructed_trace_envelope_id,
        reconstructed_trace_envelope_hash=replay_report.reconstructed_trace_envelope_hash,
        replay_report=replay_report,
        requirement_ids=_AUDIT_GATE_REQUIREMENTS,
    )
    sample_hash = build_audit_gate_trace_sample_result_hash(sample=draft)
    return AuditGateTraceSampleResult(
        **draft.model_dump(exclude={"sample_result_id", "sample_result_hash"}),
        sample_result_id=build_audit_gate_trace_sample_result_id(
            sample_result_hash=sample_hash
        ),
        sample_result_hash=sample_hash,
    )


def make_audit_gate_validation_report(
    *,
    manifest: AuditGateRunManifest,
    samples: Sequence[AuditGateTraceSampleResult],
) -> AuditGateValidationReport:
    """Build the deterministic aggregate gate report for sampled replay evidence."""

    sample_tuple = tuple(samples)
    blockers = tuple(_gate_blockers(manifest=manifest, samples=sample_tuple))
    failed_count = _count_samples(
        samples=sample_tuple, status=DecisionTraceReplayStatus.FAILED
    )
    status = (
        AuditGateValidationStatus.FAILED
        if blockers or failed_count
        else AuditGateValidationStatus.PASSED
    )
    draft = AuditGateValidationReport.model_construct(
        report_id="AUDITGATEREPORT:PLACEHOLDER",
        report_hash="0" * 64,
        audit_run_id=manifest.audit_run_id,
        manifest=manifest,
        sample_count=len(sample_tuple),
        passed_count=_count_samples(
            samples=sample_tuple, status=DecisionTraceReplayStatus.PASSED
        ),
        no_order_count=_count_samples(
            samples=sample_tuple, status=DecisionTraceReplayStatus.NO_ORDER
        ),
        failed_count=failed_count,
        blocker_count=len(blockers),
        samples=sample_tuple,
        blockers=blockers,
        status=status,
        recommendation=(
            AuditGateRecommendation.BLOCKED
            if status is AuditGateValidationStatus.FAILED
            else AuditGateRecommendation.READY_FOR_REVIEW
        ),
        requirement_ids=manifest.requirement_ids,
    )
    report_hash = build_audit_gate_validation_report_hash(report=draft)
    return AuditGateValidationReport(
        **draft.model_dump(exclude={"report_id", "report_hash"}),
        report_id=build_audit_gate_validation_report_id(report_hash=report_hash),
        report_hash=report_hash,
    )


def build_audit_gate_config_hash(*, config: AuditGateRunConfig) -> str:
    return _hash(_model_payload(config, exclude={"config_hash"}))


def build_audit_gate_run_manifest_hash(*, manifest: AuditGateRunManifest) -> str:
    return _hash(_model_payload(manifest, exclude={"audit_run_id", "manifest_hash"}))


def build_audit_run_id(*, manifest_hash: str) -> str:
    return _stable_id("AUDITRUN", {"manifest_hash": manifest_hash})


def build_decision_trace_replay_report_hash(*, report: DecisionTraceReplayReport) -> str:
    return _hash(_model_payload(report, exclude=set()))


def build_decision_trace_replay_report_id(*, report_hash: str) -> str:
    return _stable_id("AUDITREPLAY", {"report_hash": report_hash})


def build_audit_gate_trace_sample_result_hash(*, sample: AuditGateTraceSampleResult) -> str:
    return _hash(
        _model_payload(sample, exclude={"sample_result_id", "sample_result_hash"})
    )


def build_audit_gate_trace_sample_result_id(*, sample_result_hash: str) -> str:
    return _stable_id("AUDITSAMPLE", {"sample_result_hash": sample_result_hash})


def build_audit_gate_validation_report_hash(*, report: AuditGateValidationReport) -> str:
    return _hash(_model_payload(report, exclude={"report_id", "report_hash"}))


def build_audit_gate_validation_report_id(*, report_hash: str) -> str:
    return _stable_id("AUDITGATEREPORT", {"report_hash": report_hash})


def _gate_blockers(
    *, manifest: AuditGateRunManifest, samples: tuple[AuditGateTraceSampleResult, ...]
) -> list[AuditGateValidationBlocker]:
    blockers: list[AuditGateValidationBlocker] = []
    for sample in samples:
        if sample.replay_status is not DecisionTraceReplayStatus.FAILED:
            continue
        if sample.replay_report.blockers:
            blockers.extend(_replay_blockers(sample=sample))
        else:
            blockers.append(
                AuditGateValidationBlocker(
                    code=AuditGateValidationBlockerCode.SAMPLE_REPLAY_FAILED,
                    trace_id=sample.trace_id,
                    message="sample replay failed without a replay blocker",
                )
            )

    policy = manifest.sample_policy
    if len(samples) < policy.minimum_sample_count:
        blockers.append(
            AuditGateValidationBlocker(
                code=AuditGateValidationBlockerCode.SAMPLE_POLICY_NOT_MET,
                message="sample count is below the configured minimum",
                expected=str(policy.minimum_sample_count),
                actual=str(len(samples)),
            )
        )
    no_order_count = _count_samples(samples=samples, status=DecisionTraceReplayStatus.NO_ORDER)
    if policy.require_no_order_sample and no_order_count == 0:
        blockers.append(
            AuditGateValidationBlocker(
                code=AuditGateValidationBlockerCode.SAMPLE_POLICY_NOT_MET,
                message="sample policy requires at least one no-order/no-trade trace",
                expected="at least 1 no_order sample",
                actual="0",
            )
        )
    if policy.require_all_replays_passing and any(
        sample.replay_status is DecisionTraceReplayStatus.FAILED for sample in samples
    ):
        blockers.append(
            AuditGateValidationBlocker(
                code=AuditGateValidationBlockerCode.SAMPLE_POLICY_NOT_MET,
                message="sample policy requires all replay samples to pass or no-order",
                expected="0 failed samples",
                actual=str(
                    _count_samples(samples=samples, status=DecisionTraceReplayStatus.FAILED)
                ),
            )
        )
    return blockers


def _replay_blockers(sample: AuditGateTraceSampleResult) -> list[AuditGateValidationBlocker]:
    blockers: list[AuditGateValidationBlocker] = []
    for replay_blocker in sample.replay_report.blockers:
        blockers.append(
            AuditGateValidationBlocker(
                code=AuditGateValidationBlockerCode.SAMPLE_REPLAY_FAILED,
                trace_id=sample.trace_id,
                replay_blocker_code=replay_blocker.code.value,
                message=replay_blocker.message,
                expected=replay_blocker.expected,
                actual=replay_blocker.actual,
            )
        )
    return blockers


def _count_samples(
    *, samples: tuple[AuditGateTraceSampleResult, ...], status: DecisionTraceReplayStatus
) -> int:
    return sum(1 for sample in samples if sample.replay_status is status)


def _normalize_trace_id(trace_id: str) -> str:
    normalized = trace_id.strip()
    return normalized or "TRACE:MISSING"


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_payload(model: ContractModel, *, exclude: set[str]) -> object:
    return json.loads(model.model_dump_json(exclude=exclude))
