"""S11-003/S11-004 audit gate run-ID reproducibility evidence."""

from __future__ import annotations

from decimal import Decimal

from risk_test_helpers import account_state, bar, default_policy, load_snapshot, risk_request
from ta_model.audit import (
    AuditGateRecommendation,
    AuditGateRunConfig,
    AuditGateSamplePolicy,
    AuditGateValidationBlockerCode,
    AuditGateValidationStatus,
    DecisionTraceReplayBlockerCode,
    DecisionTraceReplayEvidence,
    DecisionTraceReplayStatus,
    InMemoryDecisionTraceEvidenceStore,
    build_order_intent_from_strategy_decision,
    make_audit_gate_run_config,
    make_decision_trace_envelope,
    run_audit_gate_validation,
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

    assert report.status is AuditGateValidationStatus.PASSED
    assert report.recommendation is AuditGateRecommendation.READY_FOR_REVIEW
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


def test_audit_gate_validation_reports_missing_and_tampered_blockers() -> None:
    source = _approved_replay_evidence()
    tampered_forecast = source.forecast.model_copy(update={"uncertainty": Decimal("0.123")})
    tampered = source.model_copy(update={"forecast": tampered_forecast})

    report = run_audit_gate_validation(
        trace_ids=(tampered.trace_id, "TRACE:S11:GATE-MISSING"),
        resolver=InMemoryDecisionTraceEvidenceStore((tampered,)),
        config=_gate_config(minimum_sample_count=2, require_no_order_sample=False),
    )

    assert report.status is AuditGateValidationStatus.FAILED
    assert report.recommendation is AuditGateRecommendation.BLOCKED
    assert report.sample_count == 2
    assert report.failed_count == 2
    assert report.passed_count == 0
    assert report.no_order_count == 0
    assert report.blocker_count >= 2
    assert all(
        blocker.code is AuditGateValidationBlockerCode.SAMPLE_REPLAY_FAILED
        or blocker.code is AuditGateValidationBlockerCode.SAMPLE_POLICY_NOT_MET
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


def _gate_config(
    *, minimum_sample_count: int = 3, require_no_order_sample: bool = True
) -> AuditGateRunConfig:
    return make_audit_gate_run_config(
        code_commit="3418ec7b12e6d3710f546a144295718834c15ef8",
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
