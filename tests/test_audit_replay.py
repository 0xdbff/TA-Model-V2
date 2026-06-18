"""S11-002 evidence for replaying decisions by trace ID."""

from __future__ import annotations

from decimal import Decimal

from risk_test_helpers import (
    account_state,
    bar,
    default_policy,
    load_snapshot,
    risk_request,
)
from ta_model.audit import (
    DecisionTraceReplayBlockerCode,
    DecisionTraceReplayEvidence,
    DecisionTraceReplayStatus,
    InMemoryDecisionTraceEvidenceStore,
    build_order_intent_from_strategy_decision,
    make_decision_trace_envelope,
    replay_decision_trace_by_id,
)
from ta_model.audit.trace import DecisionTraceEnvelope
from ta_model.contracts.execution import ExecutionGatewayOrderStatus
from ta_model.contracts.risk import RiskDecisionStatus
from ta_model.contracts.simulation import make_execution_cost_model
from ta_model.execution import (
    make_paper_account_session_report,
    make_paper_tca_report,
    run_paper_gateway_replay,
)
from ta_model.risk.engine import evaluate_pre_trade_risk
from test_audit_trace_contracts import (
    _approved_trace_evidence,
    _decision,
    _forecast,
    _gateway_report_with_spoofed_client_order_id,
    _quote,
    _sizing_inputs,
)


def test_approved_paper_fill_replay_by_trace_reproduces_audit_artifacts() -> None:
    evidence = _approved_replay_evidence()

    report = replay_decision_trace_by_id(
        trace_id=evidence.trace_id,
        resolver=InMemoryDecisionTraceEvidenceStore((evidence,)),
    )

    assert report.status is DecisionTraceReplayStatus.PASSED
    assert report.blockers == ()
    assert report.requirement_ids == ("FR-015", "NFR-004")
    assert report.stored_trace_envelope_id == evidence.envelope.trace_envelope_id
    assert report.reconstructed_trace_envelope_id == evidence.envelope.trace_envelope_id
    assert report.original_gateway_report_id == report.replayed_gateway_report_id
    assert report.original_gateway_report_hash == report.replayed_gateway_report_hash
    assert report.original_gateway_event_id == report.replayed_gateway_event_id
    assert report.original_gateway_order_id == report.replayed_gateway_order_id
    assert report.original_paper_session_report_id == report.replayed_paper_session_report_id
    assert report.original_paper_tca_report_id == report.replayed_paper_tca_report_id
    assert report.original_paper_fill_log_ids == report.replayed_paper_fill_log_ids
    assert report.original_paper_tca_row_ids == report.replayed_paper_tca_row_ids


def test_risk_blocked_trace_replay_preserves_blocked_status_and_audit_links() -> None:
    evidence = _blocked_replay_evidence()

    report = replay_decision_trace_by_id(
        trace_id=evidence.trace_id,
        resolver=InMemoryDecisionTraceEvidenceStore((evidence,)),
    )

    assert report.status is DecisionTraceReplayStatus.PASSED
    assert evidence.risk_event is not None
    assert evidence.risk_event.final_decision is RiskDecisionStatus.REJECTED
    assert evidence.gateway_report is not None
    assert evidence.gateway_report.events[0].status is ExecutionGatewayOrderStatus.BLOCKED
    assert report.original_gateway_order_id is None
    assert report.replayed_gateway_order_id is None
    assert report.original_paper_fill_log_ids == ()
    assert report.replayed_paper_fill_log_ids == ()
    assert report.original_paper_rejection_log_ids == report.replayed_paper_rejection_log_ids
    assert report.original_paper_tca_issue_ids == report.replayed_paper_tca_issue_ids


def test_no_trade_trace_reconstructs_without_gateway_replay() -> None:
    evidence = _no_trade_replay_evidence()

    report = replay_decision_trace_by_id(
        trace_id=evidence.trace_id,
        resolver=InMemoryDecisionTraceEvidenceStore((evidence,)),
    )

    assert report.status is DecisionTraceReplayStatus.NO_ORDER
    assert report.blockers == ()
    assert report.reconstructed_trace_envelope_id == evidence.envelope.trace_envelope_id
    assert report.original_gateway_report_id is None
    assert report.replayed_gateway_report_id is None
    assert report.original_paper_order_log_ids == ()
    assert report.replayed_paper_order_log_ids == ()


def test_missing_trace_id_fails_closed() -> None:
    report = replay_decision_trace_by_id(
        trace_id="TRACE:S11:DOES-NOT-EXIST",
        resolver=InMemoryDecisionTraceEvidenceStore(()),
    )

    assert report.status is DecisionTraceReplayStatus.FAILED
    assert report.blockers[0].code is DecisionTraceReplayBlockerCode.MISSING_TRACE_ID
    assert report.replayed_gateway_report_id is None


def test_missing_order_trace_replay_inputs_fail_closed() -> None:
    evidence = _approved_replay_evidence().model_copy(update={"bars": ()})

    report = replay_decision_trace_by_id(
        trace_id=evidence.trace_id,
        resolver=InMemoryDecisionTraceEvidenceStore((evidence,)),
    )

    assert report.status is DecisionTraceReplayStatus.FAILED
    assert report.blockers[0].code is DecisionTraceReplayBlockerCode.MISSING_REPLAY_INPUT
    assert "bars" in (report.blockers[0].actual or "")
    assert report.replayed_gateway_report_id is None


def test_tampered_envelope_hash_fails_closed_before_gateway_replay() -> None:
    evidence = _approved_replay_evidence()
    tampered_envelope = evidence.envelope.model_copy(update={"trace_envelope_hash": "1" * 64})
    tampered = evidence.model_copy(update={"envelope": tampered_envelope})

    report = replay_decision_trace_by_id(
        trace_id=tampered.trace_id,
        resolver=InMemoryDecisionTraceEvidenceStore((tampered,)),
    )

    assert report.status is DecisionTraceReplayStatus.FAILED
    assert report.blockers[0].code is DecisionTraceReplayBlockerCode.TAMPERED_EVIDENCE
    assert report.replayed_gateway_report_id is None


def test_tampered_gateway_client_order_evidence_fails_closed() -> None:
    evidence = _approved_replay_evidence()
    assert evidence.gateway_report is not None
    spoofed_gateway_report = _gateway_report_with_spoofed_client_order_id(
        report=evidence.gateway_report,
        client_order_id="ORDERINTENT:S11-REPLAY-SPOOFED",
    )
    tampered = evidence.model_copy(update={"gateway_report": spoofed_gateway_report})

    report = replay_decision_trace_by_id(
        trace_id=tampered.trace_id,
        resolver=InMemoryDecisionTraceEvidenceStore((tampered,)),
    )

    assert report.status is DecisionTraceReplayStatus.FAILED
    assert report.blockers[0].code is DecisionTraceReplayBlockerCode.TAMPERED_EVIDENCE
    assert "gateway client_order_id" in report.blockers[0].message
    assert report.replayed_gateway_report_id is None


def test_duplicate_trace_evidence_fails_closed() -> None:
    evidence = _approved_replay_evidence()

    report = replay_decision_trace_by_id(
        trace_id=evidence.trace_id,
        resolver=InMemoryDecisionTraceEvidenceStore((evidence, evidence)),
    )

    assert report.status is DecisionTraceReplayStatus.FAILED
    assert report.blockers[0].code is DecisionTraceReplayBlockerCode.DUPLICATE_TRACE_EVIDENCE


def test_resolver_returning_wrong_trace_fails_closed() -> None:
    evidence = _approved_replay_evidence()
    requested_trace_id = "TRACE:S11:WRONG-REQUEST"

    report = replay_decision_trace_by_id(
        trace_id=requested_trace_id,
        resolver=_WrongTraceResolver(evidence),
    )

    assert report.status is DecisionTraceReplayStatus.FAILED
    assert report.blockers[0].code is DecisionTraceReplayBlockerCode.MISMATCHED_REQUESTED_TRACE
    assert report.blockers[0].expected == requested_trace_id
    assert report.replayed_gateway_report_id is None


class _WrongTraceResolver:
    def __init__(self, evidence: DecisionTraceReplayEvidence) -> None:
        self._evidence = evidence

    def resolve_trace_evidence(self, trace_id: str) -> tuple[DecisionTraceReplayEvidence, ...]:
        return (self._evidence,)


def _approved_replay_evidence() -> DecisionTraceReplayEvidence:
    source = _approved_trace_evidence()
    envelope = make_decision_trace_envelope(
        forecast=source.forecast,
        decision=source.decision,
        order_intent=source.order_intent,
        risk_event=source.risk_event,
        gateway_report=source.gateway_report,
        paper_account_report=source.session_report,
        paper_tca_report=source.tca_report,
    )
    return DecisionTraceReplayEvidence(
        trace_id=source.decision.trace_id,
        envelope=envelope,
        forecast=source.forecast,
        decision=source.decision,
        order_intent=source.order_intent,
        risk_event=source.risk_event,
        gateway_report=source.gateway_report,
        paper_account_report=source.session_report,
        paper_tca_report=source.tca_report,
        bars=(bar(0), bar(1), bar(2)),
        execution_cost_model=make_execution_cost_model(
            taker_fee_rate=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
        ),
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=account_state(),
        quotes=(_quote(event_ts=source.gateway_report.events[0].submitted_at),),
    )


def _blocked_replay_evidence() -> DecisionTraceReplayEvidence:
    forecast = _forecast(median="0.050", uncertainty="0.000")
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
        run_id="PAPER:S11:REPLAY-BLOCKED",
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


def _no_trade_replay_evidence() -> DecisionTraceReplayEvidence:
    forecast = _forecast(median="0.003")
    decision = _decision(forecast=forecast, sizing_inputs=_sizing_inputs())
    envelope = make_decision_trace_envelope(forecast=forecast, decision=decision)
    assert isinstance(envelope, DecisionTraceEnvelope)
    return DecisionTraceReplayEvidence(
        trace_id=decision.trace_id,
        envelope=envelope,
        forecast=forecast,
        decision=decision,
    )
