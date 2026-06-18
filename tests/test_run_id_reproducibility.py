"""S11-003/S11-004 audit gate run-ID reproducibility evidence."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

import ta_model.audit as audit_api
from risk_test_helpers import account_state, bar, default_policy, load_snapshot, risk_request
from ta_model.audit import (
    AuditGateRunConfig,
    AuditGateSamplePolicy,
    DecisionTraceReplayBlockerCode,
    DecisionTraceReplayEvidence,
    DecisionTraceReplayReport,
    DecisionTraceReplayStatus,
    InMemoryDecisionTraceEvidenceStore,
    build_decision_trace_envelope_id,
    build_order_intent_from_strategy_decision,
    make_audit_gate_run_config,
    make_decision_trace_envelope,
    replay_decision_trace_by_id,
    run_audit_gate_validation,
)
from ta_model.audit.gate import (
    _make_audit_gate_trace_sample_result,
    _make_audit_gate_validation_report,
    make_audit_gate_run_manifest,
)
from ta_model.contracts.execution import ExecutionGatewayOrderStatus
from ta_model.contracts.risk import RiskDecisionStatus
from ta_model.execution import (
    make_paper_account_session_report,
    make_paper_tca_report,
    run_paper_gateway_replay,
)
from ta_model.risk.engine import evaluate_pre_trade_risk
from test_audit_replay import _approved_replay_evidence, _no_trade_replay_evidence
from test_audit_trace_contracts import _decision, _forecast, _sizing_inputs


def test_run_id_reproducibility_smoke_replays_same_evidence_exactly() -> None:
    evidence = _gate_evidence()
    config = _gate_config()
    trace_ids = tuple(item.trace_id for item in evidence)
    resolver = InMemoryDecisionTraceEvidenceStore(evidence)

    first = run_audit_gate_validation(trace_ids=trace_ids, resolver=resolver, config=config)
    second = run_audit_gate_validation(trace_ids=trace_ids, resolver=resolver, config=config)

    assert first.audit_run_id == second.audit_run_id
    assert first.manifest.manifest_hash == second.manifest.manifest_hash
    assert first.report_id == second.report_id
    assert first.report_hash == second.report_hash
    assert first.sample_count == second.sample_count == 3
    assert first.passed_count == second.passed_count == 2
    assert first.no_order_count == second.no_order_count == 1
    assert first.failed_count == second.failed_count == 0
    assert first.blocker_count == second.blocker_count == 0
    assert tuple(sample.replay_report_id for sample in first.samples) == tuple(
        sample.replay_report_id for sample in second.samples
    )
    assert tuple(sample.replay_report_hash for sample in first.samples) == tuple(
        sample.replay_report_hash for sample in second.samples
    )
    assert tuple(sample.sample_result_id for sample in first.samples) == tuple(
        sample.sample_result_id for sample in second.samples
    )
    assert first.model_dump() == second.model_dump()


def test_audit_gate_validation_passes_mixed_fill_blocked_and_no_trade_samples() -> None:
    approved, blocked, no_trade = _gate_evidence()
    report = run_audit_gate_validation(
        trace_ids=(approved.trace_id, blocked.trace_id, no_trade.trace_id),
        resolver=InMemoryDecisionTraceEvidenceStore((approved, blocked, no_trade)),
        config=_gate_config(),
    )

    assert report.status.value == "passed"
    assert report.recommendation.value == "ready_for_audit_review"
    assert report.requirement_ids == ("FR-015", "NFR-004", "NFR-005")
    assert report.sample_count == 3
    assert report.passed_count == 2
    assert report.no_order_count == 1
    assert report.failed_count == 0
    assert report.blockers == ()
    assert tuple(sample.replay_status for sample in report.samples) == (
        DecisionTraceReplayStatus.PASSED,
        DecisionTraceReplayStatus.PASSED,
        DecisionTraceReplayStatus.NO_ORDER,
    )
    assert blocked.risk_event is not None
    assert blocked.risk_event.final_decision is RiskDecisionStatus.REJECTED
    assert blocked.gateway_report is not None
    assert blocked.gateway_report.events[0].status is ExecutionGatewayOrderStatus.BLOCKED
    assert report.samples[1].replay_report.original_gateway_order_id is None
    assert report.samples[2].stored_trace_envelope_id == no_trade.envelope.trace_envelope_id
    assert report.samples[2].replay_report.forecast_id == no_trade.forecast.forecast_id
    assert report.samples[2].replay_report.strategy_decision_id == no_trade.decision.decision_id
    assert report.samples[2].replay_report.strategy_decision_hash == no_trade.decision.decision_hash
    assert report.samples[2].replay_report.stored_no_order_reason == (
        no_trade.envelope.no_order_reason
    )
    assert report.samples[2].replay_report.reconstructed_no_order_reason == (
        no_trade.envelope.no_order_reason
    )


def test_public_audit_api_uses_resolver_backed_gate_entrypoint_only() -> None:
    expected_public_names = {
        "AuditGateRunConfig",
        "AuditGateSampleMethod",
        "AuditGateSamplePolicy",
        "AuditGateToleranceMode",
        "AuditGateTolerancePolicy",
        "make_audit_gate_run_config",
        "run_audit_gate_validation",
    }
    for name in expected_public_names:
        assert hasattr(audit_api, name)
        assert name in audit_api.__all__

    blocked_public_names = {
        "AuditGateRecommendation",
        "AuditGateRunManifest",
        "AuditGateTraceSampleResult",
        "AuditGateValidationBlocker",
        "AuditGateValidationBlockerCode",
        "AuditGateValidationReport",
        "AuditGateValidationStatus",
        "build_audit_gate_config_hash",
        "build_audit_gate_run_manifest_hash",
        "build_audit_gate_trace_sample_result_hash",
        "build_audit_gate_trace_sample_result_id",
        "build_audit_gate_validation_report_hash",
        "build_audit_gate_validation_report_id",
        "build_audit_run_id",
        "build_decision_trace_replay_report_hash",
        "build_decision_trace_replay_report_id",
        "make_audit_gate_run_manifest",
        "make_audit_gate_trace_sample_result",
        "make_audit_gate_validation_report",
    }
    for name in blocked_public_names:
        assert not hasattr(audit_api, name)
        assert name not in audit_api.__all__


def test_audit_gate_validation_reports_missing_and_tampered_blockers() -> None:
    source = _approved_replay_evidence()
    tampered_forecast = source.forecast.model_copy(update={"uncertainty": Decimal("0.123")})
    tampered = source.model_copy(update={"forecast": tampered_forecast})

    report = run_audit_gate_validation(
        trace_ids=(tampered.trace_id, "TRACE:S11:GATE-MISSING"),
        resolver=InMemoryDecisionTraceEvidenceStore((tampered,)),
        config=_gate_config(minimum_sample_count=2, require_no_order_sample=False),
    )

    assert report.status.value == "failed"
    assert report.recommendation.value == "blocked_until_replay_blockers_resolved"
    assert report.sample_count == 2
    assert report.failed_count == 2
    assert report.passed_count == 0
    assert report.no_order_count == 0
    assert report.blocker_count >= 2
    assert all(
        blocker.code.value == "sample_replay_failed"
        or blocker.code.value == "sample_policy_not_met"
        for blocker in report.blockers
    )
    assert DecisionTraceReplayBlockerCode.TAMPERED_EVIDENCE.value in {
        blocker.replay_blocker_code for blocker in report.blockers
    }
    assert DecisionTraceReplayBlockerCode.MISSING_TRACE_ID.value in {
        blocker.replay_blocker_code for blocker in report.blockers
    }
    assert report.samples[0].replay_status is DecisionTraceReplayStatus.FAILED
    assert report.samples[1].replay_status is DecisionTraceReplayStatus.FAILED


def test_duplicate_trace_ids_fail_policy_and_do_not_satisfy_minimum_sample_count() -> None:
    evidence = _approved_replay_evidence()

    report = run_audit_gate_validation(
        trace_ids=(evidence.trace_id, evidence.trace_id, evidence.trace_id),
        resolver=InMemoryDecisionTraceEvidenceStore((evidence,)),
        config=_gate_config(minimum_sample_count=3, require_no_order_sample=False),
    )

    assert report.status.value == "failed"
    assert report.passed_count == 3
    assert report.failed_count == 0
    assert report.blocker_count >= 2
    assert any("unique" in blocker.message for blocker in report.blockers)
    assert any(
        blocker.message == "unique non-empty sample count is below the configured minimum"
        and blocker.actual == "1"
        for blocker in report.blockers
    )


def test_blank_trace_id_cannot_silently_pass_sample_policy() -> None:
    report = run_audit_gate_validation(
        trace_ids=("   ",),
        resolver=InMemoryDecisionTraceEvidenceStore(()),
        config=_gate_config(minimum_sample_count=1, require_no_order_sample=False),
    )

    assert report.status.value == "failed"
    assert report.manifest.trace_id_policy_errors == (
        "explicit trace_id at sample index 0 must be non-empty",
    )
    assert report.failed_count == 1
    assert any("non-empty" in blocker.message for blocker in report.blockers)
    assert any(blocker.actual == "0" for blocker in report.blockers)


def test_fabricated_pass_replay_report_cannot_create_pass_gate_sample() -> None:
    fabricated = DecisionTraceReplayReport(
        trace_id="TRACE:S11:FABRICATED-PASS",
        status=DecisionTraceReplayStatus.PASSED,
    )

    with pytest.raises(ValueError, match="stored and reconstructed trace envelope"):
        _make_audit_gate_trace_sample_result(sample_index=0, replay_report=fabricated)


def test_envelope_only_fabricated_pass_replay_report_cannot_create_pass_gate_sample() -> None:
    envelope_hash = "a" * 64
    envelope_id = build_decision_trace_envelope_id(trace_envelope_hash=envelope_hash)
    fabricated = DecisionTraceReplayReport(
        trace_id="TRACE:S11:FABRICATED-ENVELOPE-ONLY",
        status=DecisionTraceReplayStatus.PASSED,
        strategy_run_id="STRATEGYRUN:S11-FABRICATED",
        stored_trace_envelope_id=envelope_id,
        stored_trace_envelope_hash=envelope_hash,
        reconstructed_trace_envelope_id=envelope_id,
        reconstructed_trace_envelope_hash=envelope_hash,
    )

    with pytest.raises(ValueError, match="order replay evidence"):
        _make_audit_gate_trace_sample_result(sample_index=0, replay_report=fabricated)


def test_envelope_only_fabricated_no_order_replay_report_cannot_create_pass_gate_sample() -> None:
    envelope_hash = "b" * 64
    envelope_id = build_decision_trace_envelope_id(trace_envelope_hash=envelope_hash)
    fabricated = DecisionTraceReplayReport(
        trace_id="TRACE:S11:FABRICATED-NO-ORDER",
        status=DecisionTraceReplayStatus.NO_ORDER,
        strategy_run_id="STRATEGYRUN:S11-FABRICATED",
        stored_trace_envelope_id=envelope_id,
        stored_trace_envelope_hash=envelope_hash,
        reconstructed_trace_envelope_id=envelope_id,
        reconstructed_trace_envelope_hash=envelope_hash,
    )

    with pytest.raises(ValueError, match="decision evidence"):
        _make_audit_gate_trace_sample_result(sample_index=0, replay_report=fabricated)


def test_zero_sample_policy_is_rejected_and_empty_trace_set_fails_gate() -> None:
    with pytest.raises(ValidationError):
        AuditGateSamplePolicy(minimum_sample_count=0)

    report = run_audit_gate_validation(
        trace_ids=(),
        resolver=InMemoryDecisionTraceEvidenceStore(()),
        config=_gate_config(minimum_sample_count=1, require_no_order_sample=False),
    )

    assert report.status.value == "failed"
    assert report.sample_count == 0
    assert report.blocker_count == 1
    assert report.blockers[0].message == (
        "unique non-empty sample count is below the configured minimum"
    )
    assert report.blockers[0].actual == "0"


def test_sample_manifest_trace_mismatch_fails_report_validation() -> None:
    evidence = _approved_replay_evidence()
    replay_report = replay_decision_trace_by_id(
        trace_id=evidence.trace_id,
        resolver=InMemoryDecisionTraceEvidenceStore((evidence,)),
    )
    sample = _make_audit_gate_trace_sample_result(
        sample_index=0,
        replay_report=replay_report,
    )
    mismatched_manifest = make_audit_gate_run_manifest(
        config=_gate_config(minimum_sample_count=1, require_no_order_sample=False),
        trace_ids=("TRACE:S11:MANIFEST-MISMATCH",),
    )

    with pytest.raises(ValueError, match="sample trace IDs must match manifest"):
        _make_audit_gate_validation_report(manifest=mismatched_manifest, samples=(sample,))


def _gate_config(
    *, minimum_sample_count: int = 3, require_no_order_sample: bool = True
) -> AuditGateRunConfig:
    return make_audit_gate_run_config(
        code_commit="fixture-s11-repro-gate-code-commit",
        code_ref="agent/s11-repro-gate-6f17",
        sample_policy=AuditGateSamplePolicy(
            description="S11 audit gate fixture: approved-fill, risk-blocked, no-trade",
            minimum_sample_count=minimum_sample_count,
            require_no_order_sample=require_no_order_sample,
            require_all_replays_passing=True,
        ),
    )


def _gate_evidence() -> tuple[
    DecisionTraceReplayEvidence,
    DecisionTraceReplayEvidence,
    DecisionTraceReplayEvidence,
]:
    approved = _approved_replay_evidence()
    blocked = _risk_blocked_replay_evidence()
    no_trade = _no_trade_replay_evidence()
    assert len({approved.trace_id, blocked.trace_id, no_trade.trace_id}) == 3
    return approved, blocked, no_trade


def _risk_blocked_replay_evidence() -> DecisionTraceReplayEvidence:
    forecast = _forecast(median="0.060", uncertainty="0.000")
    decision = _decision(
        forecast=forecast,
        sizing_inputs=_sizing_inputs(risk_budget_notional="300"),
    )
    order_intent = build_order_intent_from_strategy_decision(
        decision=decision,
        submitted_at=decision.decision_ts,
    )
    risk_event = evaluate_pre_trade_risk(
        request=risk_request(order_intent=order_intent, decision_ts=decision.decision_ts),
        policy=default_policy(),
    )
    initial_state = account_state()
    gateway_report = run_paper_gateway_replay(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(risk_event,),
        run_id="PAPER:S11:GATE-BLOCKED",
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=initial_state,
    )
    session_report = make_paper_account_session_report(
        gateway_report=gateway_report,
        initial_account_state=initial_state,
    )
    tca_report = make_paper_tca_report(gateway_report=gateway_report, quotes=())
    envelope = make_decision_trace_envelope(
        forecast=forecast,
        decision=decision,
        order_intent=order_intent,
        risk_event=risk_event,
        gateway_report=gateway_report,
        paper_account_report=session_report,
        paper_tca_report=tca_report,
    )
    return DecisionTraceReplayEvidence(
        trace_id=decision.trace_id,
        envelope=envelope,
        forecast=forecast,
        decision=decision,
        order_intent=order_intent,
        risk_event=risk_event,
        gateway_report=gateway_report,
        paper_account_report=session_report,
        paper_tca_report=tca_report,
        bars=(bar(0), bar(1), bar(2)),
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=initial_state,
        quotes=(),
    )
