"""S11-001 evidence for trace propagation across real S8-S10 seams."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import NamedTuple

import pytest
from pydantic import ValidationError

import ta_model.audit as public_audit
from risk_test_helpers import (
    INSTRUMENT_ID,
    START,
    VENUE_ID,
    account_state,
    bar,
    default_policy,
    load_snapshot,
    risk_request,
)
from ta_model.audit import (
    DecisionTraceEnvelope,
    StrategyOrderIntentBuildError,
    build_decision_trace_envelope_hash,
    build_decision_trace_envelope_id,
    build_order_intent_client_order_id,
    build_order_intent_from_strategy_decision,
    make_decision_trace_envelope,
)
from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.decisions import (
    StrategyDecision,
    StrategyDecisionPolicy,
    StrategySizingInputs,
    make_strategy_decision_policy,
)
from ta_model.contracts.execution import (
    ExecutionGatewayLifecycleEvent,
    ExecutionGatewayOrderStatus,
    ExecutionGatewayReport,
    build_execution_gateway_event_hash,
    build_execution_gateway_event_id,
    build_execution_gateway_order_id,
    build_execution_gateway_report_hash,
    build_execution_gateway_report_id,
)
from ta_model.contracts.forecasts import (
    CalibrationStatus,
    Forecast,
    ForecastQuantile,
    build_forecast_id,
    build_model_version_hash,
    build_model_version_id,
)
from ta_model.contracts.paper import (
    PaperAccountSessionReport,
    PaperFillLogEntry,
    PaperOrderLifecycleLogEntry,
    PaperTcaReport,
    PaperTcaRow,
    build_paper_account_session_report_hash,
    build_paper_account_session_report_id,
    build_paper_fill_log_hash,
    build_paper_fill_log_id,
    build_paper_order_lifecycle_log_hash,
    build_paper_order_lifecycle_log_id,
    build_paper_tca_report_hash,
    build_paper_tca_report_id,
    build_paper_tca_row_hash,
    build_paper_tca_row_id,
)
from ta_model.contracts.risk import RiskCheckEvent, RiskCheckRequest, RiskDecisionStatus
from ta_model.contracts.simulation import OrderIntent, make_execution_cost_model
from ta_model.contracts.streaming import QuoteEvent
from ta_model.contracts.training import build_training_run_id
from ta_model.execution import (
    make_paper_account_session_report,
    make_paper_tca_report,
    run_paper_gateway_replay,
)
from ta_model.risk.engine import evaluate_pre_trade_risk
from ta_model.strategy.decisions import decide_expected_net_edge

DATASET_HASH = "c" * 64
TRAINING_HASH = "d" * 64
CANDIDATE_NAME = "s11-audit-trace-fixture"
TRAINING_RUN_ID = build_training_run_id(training_run_hash=TRAINING_HASH)
MODEL_VERSION_HASH = build_model_version_hash(
    training_run_id=TRAINING_RUN_ID,
    training_run_hash=TRAINING_HASH,
    candidate_name=CANDIDATE_NAME,
)
MODEL_VERSION_ID = build_model_version_id(model_version_hash=MODEL_VERSION_HASH)
FEATURE_VERSION = "s11-audit-trace-fixture-1.0.0"


class ApprovedTraceEvidence(NamedTuple):
    forecast: Forecast
    decision: StrategyDecision
    order_intent: OrderIntent
    risk_event: RiskCheckEvent
    gateway_report: ExecutionGatewayReport
    session_report: PaperAccountSessionReport
    tca_report: PaperTcaReport


def test_public_audit_exports_and_trace_envelope_identity_are_deterministic() -> None:
    evidence = _approved_trace_evidence()

    envelope = _envelope(evidence)
    duplicate = _envelope(evidence)

    assert public_audit.DecisionTraceEnvelope is DecisionTraceEnvelope
    assert public_audit.build_order_intent_from_strategy_decision is (
        build_order_intent_from_strategy_decision
    )
    assert envelope == duplicate
    assert envelope.trace_envelope_hash == build_decision_trace_envelope_hash(
        envelope=envelope
    )
    assert envelope.trace_envelope_id == build_decision_trace_envelope_id(
        trace_envelope_hash=envelope.trace_envelope_hash
    )
    assert envelope.requirement_ids == ("FR-015", "NFR-004")
    with pytest.raises(ValidationError, match="trace_envelope_hash"):
        DecisionTraceEnvelope(
            **envelope.model_dump(exclude={"trace_envelope_hash"}),
            trace_envelope_hash="1" * 64,
        )


def test_strategy_buy_trace_flows_through_risk_gateway_paper_and_envelope() -> None:
    evidence = _approved_trace_evidence()
    trace_id = evidence.decision.trace_id
    gateway_event = evidence.gateway_report.events[0]
    order_log = evidence.session_report.order_logs[0]
    fill_log = evidence.session_report.fill_logs[0]
    tca_row = evidence.tca_report.rows[0]

    assert evidence.order_intent.trace_id == trace_id
    assert evidence.order_intent.source_decision_id == evidence.decision.decision_id
    assert evidence.risk_event.request.order_intent == evidence.order_intent
    assert evidence.risk_event.approved_order_intent is not None
    assert evidence.risk_event.approved_order_intent.trace_id == trace_id
    assert gateway_event.trace_id == trace_id
    assert gateway_event.source_decision_id == evidence.decision.decision_id
    assert order_log.trace_id == trace_id
    assert order_log.source_decision_id == evidence.decision.decision_id
    assert fill_log.trace_id == trace_id
    assert fill_log.source_decision_id == evidence.decision.decision_id
    assert tca_row.trace_id == trace_id
    assert tca_row.source_decision_id == evidence.decision.decision_id

    envelope = _envelope(evidence)

    assert envelope.trace_id == trace_id
    assert envelope.forecast.forecast_id == evidence.forecast.forecast_id
    assert envelope.forecast.dataset_hash == evidence.forecast.dataset_hash
    assert envelope.forecast.training_run_hash == evidence.forecast.training_run_hash
    assert envelope.forecast.model_version_hash == evidence.forecast.model_version_hash
    assert envelope.strategy_decision_id == evidence.decision.decision_id
    assert envelope.strategy_decision_hash == evidence.decision.decision_hash
    assert envelope.order_intent_id == evidence.order_intent.client_order_id
    assert envelope.risk_request_id == evidence.risk_event.request.request_id
    assert envelope.risk_check_id == evidence.risk_event.risk_check_id
    assert envelope.gateway_report_id == evidence.gateway_report.gateway_report_id
    assert envelope.gateway_event_id == gateway_event.gateway_event_id
    assert envelope.paper_session_report_id == evidence.session_report.session_report_id
    assert envelope.paper_order_log_ids == (order_log.order_log_id,)
    assert envelope.paper_fill_log_ids == (fill_log.fill_log_id,)
    assert envelope.paper_tca_report_id == evidence.tca_report.tca_report_id
    assert envelope.paper_tca_row_ids == (tca_row.tca_row_id,)


def test_no_trade_and_zero_size_decisions_do_not_create_orders_and_remain_auditable() -> None:
    no_trade_forecast = _forecast(median="0.003")
    no_trade_decision = _decision(forecast=no_trade_forecast, sizing_inputs=_sizing_inputs())

    with pytest.raises(StrategyOrderIntentBuildError, match="no-trade"):
        build_order_intent_from_strategy_decision(decision=no_trade_decision)

    no_trade_envelope = make_decision_trace_envelope(
        forecast=no_trade_forecast,
        decision=no_trade_decision,
    )

    assert no_trade_envelope.order_intent_id is None
    assert no_trade_envelope.no_order_reason == "strategy_no_trade:insufficient_net_edge"
    assert no_trade_envelope.risk_check_id is None
    assert no_trade_envelope.paper_order_log_ids == ()

    zero_size_forecast = _forecast(median="0.050", uncertainty="0.000")
    zero_size_decision = _decision(forecast=zero_size_forecast, sizing_inputs=None)

    with pytest.raises(StrategyOrderIntentBuildError, match="positive pre-risk sizing"):
        build_order_intent_from_strategy_decision(decision=zero_size_decision)

    zero_size_envelope = make_decision_trace_envelope(
        forecast=zero_size_forecast,
        decision=zero_size_decision,
    )

    assert zero_size_envelope.order_intent_id is None
    assert zero_size_envelope.no_order_reason == (
        "zero_pre_risk_size:placeholder_pending_independent_risk"
    )
    assert zero_size_envelope.risk_request_id is None
    assert zero_size_envelope.paper_tca_report_id is None


def test_mismatched_trace_or_source_ids_are_rejected_by_risk_and_audit_validation() -> None:
    evidence = _approved_trace_evidence()

    with pytest.raises(ValidationError, match="risk-check trace_id"):
        RiskCheckRequest(
            **evidence.risk_event.request.model_dump(exclude={"trace_id"}),
            trace_id="TRACE:S11:MISMATCH",
        )
    with pytest.raises(ValidationError, match="source_decision_id"):
        RiskCheckRequest(
            **evidence.risk_event.request.model_dump(exclude={"source_decision_id"}),
            source_decision_id="STRATEGYDECISION:S11-MISMATCH",
        )

    tampered_trace_intent = OrderIntent(
        **evidence.order_intent.model_dump(exclude={"trace_id"}),
        trace_id="TRACE:S11:TAMPERED",
    )
    with pytest.raises(ValueError, match="order intent trace_id"):
        make_decision_trace_envelope(
            forecast=evidence.forecast,
            decision=evidence.decision,
            order_intent=tampered_trace_intent,
            risk_event=evidence.risk_event,
            gateway_report=evidence.gateway_report,
            paper_account_report=evidence.session_report,
            paper_tca_report=evidence.tca_report,
        )

    tampered_source_intent = OrderIntent(
        **evidence.order_intent.model_dump(exclude={"source_decision_id"}),
        source_decision_id="STRATEGYDECISION:S11-TAMPERED",
    )
    with pytest.raises(ValueError, match="source_decision_id"):
        make_decision_trace_envelope(
            forecast=evidence.forecast,
            decision=evidence.decision,
            order_intent=tampered_source_intent,
            risk_event=evidence.risk_event,
            gateway_report=evidence.gateway_report,
            paper_account_report=evidence.session_report,
            paper_tca_report=evidence.tca_report,
        )


def test_gateway_order_identity_spoof_is_rejected_after_deterministic_report_rebuild() -> None:
    evidence = _approved_trace_evidence()
    spoofed_gateway_report = _gateway_report_with_spoofed_client_order_id(
        report=evidence.gateway_report,
        client_order_id="ORDERINTENT:S11-SPOOFED",
    )
    spoofed_session_report = make_paper_account_session_report(
        gateway_report=spoofed_gateway_report,
        initial_account_state=account_state(),
    )
    spoofed_tca_report = make_paper_tca_report(
        gateway_report=spoofed_gateway_report,
        quotes=(_quote(event_ts=spoofed_gateway_report.events[0].submitted_at),),
    )

    assert spoofed_gateway_report.events[0].risk_check_id == evidence.risk_event.risk_check_id
    assert spoofed_gateway_report.events[0].trace_id == evidence.decision.trace_id
    assert spoofed_gateway_report.events[0].source_decision_id == evidence.decision.decision_id
    assert spoofed_gateway_report.events[0].client_order_id != evidence.order_intent.client_order_id

    with pytest.raises(ValueError, match="gateway client_order_id"):
        make_decision_trace_envelope(
            forecast=evidence.forecast,
            decision=evidence.decision,
            order_intent=evidence.order_intent,
            risk_event=evidence.risk_event,
            gateway_report=spoofed_gateway_report,
            paper_account_report=spoofed_session_report,
            paper_tca_report=spoofed_tca_report,
        )


def test_risk_blocked_trace_envelope_links_rejection_and_tca_issue_without_fill() -> None:
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
        run_id="PAPER:S11:TRACE-BLOCKED",
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

    assert risk_event.final_decision is RiskDecisionStatus.REJECTED
    assert gateway_report.events[0].status is ExecutionGatewayOrderStatus.BLOCKED
    assert envelope.risk_decision is RiskDecisionStatus.REJECTED
    assert envelope.gateway_order_id is None
    assert envelope.paper_fill_log_ids == ()
    assert envelope.paper_rejection_log_ids == (session_report.rejection_logs[0].rejection_log_id,)
    assert envelope.paper_tca_row_ids == ()
    assert envelope.paper_tca_issue_ids == (tca_report.issues[0].issue_id,)


def test_paper_order_log_identity_spoof_is_rejected_with_correct_gateway() -> None:
    evidence = _approved_trace_evidence()
    spoofed_session_report = _paper_session_report_with_spoofed_order_log_client_order_id(
        report=evidence.session_report,
        client_order_id="ORDERINTENT:S11-PAPER-ORDER-SPOOFED",
    )

    with pytest.raises(ValueError, match="paper order log client_order_id"):
        make_decision_trace_envelope(
            forecast=evidence.forecast,
            decision=evidence.decision,
            order_intent=evidence.order_intent,
            risk_event=evidence.risk_event,
            gateway_report=evidence.gateway_report,
            paper_account_report=spoofed_session_report,
            paper_tca_report=evidence.tca_report,
        )


def test_paper_fill_log_identity_spoof_is_rejected_with_correct_gateway() -> None:
    evidence = _approved_trace_evidence()
    spoofed_session_report = _paper_session_report_with_spoofed_fill_log_client_order_id(
        report=evidence.session_report,
        client_order_id="ORDERINTENT:S11-PAPER-FILL-SPOOFED",
    )

    with pytest.raises(ValueError, match="paper fill log client_order_id"):
        make_decision_trace_envelope(
            forecast=evidence.forecast,
            decision=evidence.decision,
            order_intent=evidence.order_intent,
            risk_event=evidence.risk_event,
            gateway_report=evidence.gateway_report,
            paper_account_report=spoofed_session_report,
            paper_tca_report=evidence.tca_report,
        )


def test_paper_tca_row_identity_spoof_is_rejected_with_correct_gateway() -> None:
    evidence = _approved_trace_evidence()
    spoofed_tca_report = _paper_tca_report_with_spoofed_row_client_order_id(
        report=evidence.tca_report,
        client_order_id="ORDERINTENT:S11-PAPER-TCA-SPOOFED",
    )

    with pytest.raises(ValueError, match="paper TCA row client_order_id"):
        make_decision_trace_envelope(
            forecast=evidence.forecast,
            decision=evidence.decision,
            order_intent=evidence.order_intent,
            risk_event=evidence.risk_event,
            gateway_report=evidence.gateway_report,
            paper_account_report=evidence.session_report,
            paper_tca_report=spoofed_tca_report,
        )


def _approved_trace_evidence() -> ApprovedTraceEvidence:
    forecast = _forecast(median="0.050", uncertainty="0.000")
    decision = _decision(forecast=forecast, sizing_inputs=_sizing_inputs())
    order_intent = build_order_intent_from_strategy_decision(
        decision=decision,
        submitted_at=decision.decision_ts,
    )
    assert order_intent.client_order_id == build_order_intent_client_order_id(
        decision=decision,
        submitted_at=decision.decision_ts,
        order_type=order_intent.order_type,
    )
    risk_event = evaluate_pre_trade_risk(
        request=risk_request(order_intent=order_intent, decision_ts=decision.decision_ts),
        policy=default_policy(),
    )
    assert risk_event.final_decision is RiskDecisionStatus.APPROVED
    initial_state = account_state()
    gateway_report = run_paper_gateway_replay(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(risk_event,),
        run_id="PAPER:S11:TRACE-CONTRACT",
        execution_cost_model=make_execution_cost_model(
            taker_fee_rate=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
        ),
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=initial_state,
    )
    assert gateway_report.events[0].status is ExecutionGatewayOrderStatus.FILLED
    session_report = make_paper_account_session_report(
        gateway_report=gateway_report,
        initial_account_state=initial_state,
    )
    tca_report = make_paper_tca_report(
        gateway_report=gateway_report,
        quotes=(_quote(event_ts=gateway_report.events[0].submitted_at),),
    )
    return ApprovedTraceEvidence(
        forecast=forecast,
        decision=decision,
        order_intent=order_intent,
        risk_event=risk_event,
        gateway_report=gateway_report,
        session_report=session_report,
        tca_report=tca_report,
    )


def _envelope(evidence: ApprovedTraceEvidence) -> DecisionTraceEnvelope:
    return make_decision_trace_envelope(
        forecast=evidence.forecast,
        decision=evidence.decision,
        order_intent=evidence.order_intent,
        risk_event=evidence.risk_event,
        gateway_report=evidence.gateway_report,
        paper_account_report=evidence.session_report,
        paper_tca_report=evidence.tca_report,
    )


def _gateway_report_with_spoofed_client_order_id(
    *, report: ExecutionGatewayReport, client_order_id: str
) -> ExecutionGatewayReport:
    event = report.events[0]
    draft_event = event.model_copy(
        update={
            "gateway_event_id": "GATEWAYEVENT:PLACEHOLDER",
            "gateway_event_hash": "0" * 64,
            "client_order_id": client_order_id,
            "gateway_order_id": None,
        }
    )
    gateway_order_id = (
        None
        if draft_event.status is ExecutionGatewayOrderStatus.BLOCKED
        else build_execution_gateway_order_id(event=draft_event)
    )
    draft_event = draft_event.model_copy(update={"gateway_order_id": gateway_order_id})
    gateway_event_hash = build_execution_gateway_event_hash(event=draft_event)
    spoofed_event = ExecutionGatewayLifecycleEvent.model_validate(
        draft_event.model_dump(exclude={"gateway_event_id", "gateway_event_hash"})
        | {
            "gateway_event_id": build_execution_gateway_event_id(
                event_hash=gateway_event_hash
            ),
            "gateway_event_hash": gateway_event_hash,
        }
    )
    draft_report = report.model_copy(
        update={
            "gateway_report_id": "GATEWAYREPORT:PLACEHOLDER",
            "gateway_report_hash": "0" * 64,
            "gateway_event_ids": (spoofed_event.gateway_event_id,),
            "events": (spoofed_event,),
        }
    )
    gateway_report_hash = build_execution_gateway_report_hash(report=draft_report)
    return ExecutionGatewayReport.model_validate(
        draft_report.model_dump(exclude={"gateway_report_id", "gateway_report_hash"})
        | {
            "gateway_report_id": build_execution_gateway_report_id(
                report_hash=gateway_report_hash
            ),
            "gateway_report_hash": gateway_report_hash,
        }
    )


def _paper_session_report_with_spoofed_order_log_client_order_id(
    *, report: PaperAccountSessionReport, client_order_id: str
) -> PaperAccountSessionReport:
    spoofed_order_log = _paper_order_log_with_client_order_id(
        entry=report.order_logs[0],
        client_order_id=client_order_id,
    )
    return _paper_session_report_with_logs(
        report=report,
        order_logs=(spoofed_order_log,),
        fill_logs=report.fill_logs,
    )


def _paper_session_report_with_spoofed_fill_log_client_order_id(
    *, report: PaperAccountSessionReport, client_order_id: str
) -> PaperAccountSessionReport:
    spoofed_fill_log = _paper_fill_log_with_client_order_id(
        entry=report.fill_logs[0],
        client_order_id=client_order_id,
    )
    return _paper_session_report_with_logs(
        report=report,
        order_logs=report.order_logs,
        fill_logs=(spoofed_fill_log,),
    )


def _paper_order_log_with_client_order_id(
    *, entry: PaperOrderLifecycleLogEntry, client_order_id: str
) -> PaperOrderLifecycleLogEntry:
    draft = entry.model_copy(
        update={
            "order_log_id": "PAPERORDERLOG:PLACEHOLDER",
            "order_log_hash": "0" * 64,
            "client_order_id": client_order_id,
        }
    )
    entry_hash = build_paper_order_lifecycle_log_hash(entry=draft)
    return PaperOrderLifecycleLogEntry.model_validate(
        draft.model_dump(exclude={"order_log_id", "order_log_hash"})
        | {
            "order_log_id": build_paper_order_lifecycle_log_id(entry_hash=entry_hash),
            "order_log_hash": entry_hash,
        }
    )


def _paper_fill_log_with_client_order_id(
    *, entry: PaperFillLogEntry, client_order_id: str
) -> PaperFillLogEntry:
    draft = entry.model_copy(
        update={
            "fill_log_id": "PAPERFILLLOG:PLACEHOLDER",
            "fill_log_hash": "0" * 64,
            "client_order_id": client_order_id,
        }
    )
    entry_hash = build_paper_fill_log_hash(entry=draft)
    return PaperFillLogEntry.model_validate(
        draft.model_dump(exclude={"fill_log_id", "fill_log_hash"})
        | {
            "fill_log_id": build_paper_fill_log_id(entry_hash=entry_hash),
            "fill_log_hash": entry_hash,
        }
    )


def _paper_session_report_with_logs(
    *,
    report: PaperAccountSessionReport,
    order_logs: tuple[PaperOrderLifecycleLogEntry, ...],
    fill_logs: tuple[PaperFillLogEntry, ...],
) -> PaperAccountSessionReport:
    draft = report.model_copy(
        update={
            "session_report_id": "PAPERSESSION:PLACEHOLDER",
            "session_report_hash": "0" * 64,
            "order_log_ids": tuple(entry.order_log_id for entry in order_logs),
            "fill_log_ids": tuple(entry.fill_log_id for entry in fill_logs),
            "order_logs": order_logs,
            "fill_logs": fill_logs,
        }
    )
    report_hash = build_paper_account_session_report_hash(report=draft)
    return PaperAccountSessionReport.model_validate(
        draft.model_dump(exclude={"session_report_id", "session_report_hash"})
        | {
            "session_report_id": build_paper_account_session_report_id(
                report_hash=report_hash
            ),
            "session_report_hash": report_hash,
        }
    )


def _paper_tca_report_with_spoofed_row_client_order_id(
    *, report: PaperTcaReport, client_order_id: str
) -> PaperTcaReport:
    spoofed_row = _paper_tca_row_with_client_order_id(
        row=report.rows[0],
        client_order_id=client_order_id,
    )
    draft = report.model_copy(
        update={
            "tca_report_id": "PAPERTCAREPORT:PLACEHOLDER",
            "tca_report_hash": "0" * 64,
            "row_ids": (spoofed_row.tca_row_id,),
            "rows": (spoofed_row,),
        }
    )
    report_hash = build_paper_tca_report_hash(report=draft)
    return PaperTcaReport.model_validate(
        draft.model_dump(exclude={"tca_report_id", "tca_report_hash"})
        | {
            "tca_report_id": build_paper_tca_report_id(report_hash=report_hash),
            "tca_report_hash": report_hash,
        }
    )


def _paper_tca_row_with_client_order_id(
    *, row: PaperTcaRow, client_order_id: str
) -> PaperTcaRow:
    draft = row.model_copy(
        update={
            "tca_row_id": "PAPERTCAROW:PLACEHOLDER",
            "tca_row_hash": "0" * 64,
            "client_order_id": client_order_id,
        }
    )
    row_hash = build_paper_tca_row_hash(row=draft)
    return PaperTcaRow.model_validate(
        draft.model_dump(exclude={"tca_row_id", "tca_row_hash"})
        | {
            "tca_row_id": build_paper_tca_row_id(row_hash=row_hash),
            "tca_row_hash": row_hash,
        }
    )


def _decision(
    *, forecast: Forecast, sizing_inputs: StrategySizingInputs | None
) -> StrategyDecision:
    return decide_expected_net_edge(
        forecast=forecast,
        policy=_policy(),
        strategy_run_id="STRATEGYRUN:S11-AUDIT-TRACE",
        decision_ts=START + timedelta(minutes=1),
        sizing_inputs=sizing_inputs,
    )


def _forecast(*, median: str, uncertainty: str = "0.010") -> Forecast:
    median_value = Decimal(median)
    row_id = f"DATASETROW:S11-AUDIT:{median}:{uncertainty}"
    quantiles = (
        ForecastQuantile(level=Decimal("0.1"), value=median_value - Decimal("0.010")),
        ForecastQuantile(level=Decimal("0.5"), value=median_value),
        ForecastQuantile(level=Decimal("0.9"), value=median_value + Decimal("0.010")),
    )
    probabilities = {"negative": Decimal("0.25"), "non_negative": Decimal("0.75")}
    calibration_metadata = {
        "candidate_name": CANDIDATE_NAME,
        "fixture": "s11-audit-trace",
    }
    forecast_id = build_forecast_id(
        dataset_snapshot_id="DATASETSNAPSHOT:S11-AUDIT",
        dataset_hash=DATASET_HASH,
        dataset_row_id=row_id,
        split=DatasetSplit.VALIDATION,
        training_run_id=TRAINING_RUN_ID,
        training_run_hash=TRAINING_HASH,
        model_version_id=MODEL_VERSION_ID,
        model_version_hash=MODEL_VERSION_HASH,
        probabilities=probabilities,
        quantiles=quantiles,
        uncertainty=Decimal(uncertainty),
        calibration_status=CalibrationStatus.SEQUENCE_CONDITIONED_TRAIN_ONLY,
        calibration_metadata=calibration_metadata,
    )
    return Forecast(
        forecast_id=forecast_id,
        dataset_snapshot_id="DATASETSNAPSHOT:S11-AUDIT",
        dataset_hash=DATASET_HASH,
        dataset_row_id=row_id,
        feature_vector_id=f"FEATUREVECTOR:S11-AUDIT:{median}:{uncertainty}",
        feature_input_snapshot_id="FEATUREINPUT:S11-AUDIT",
        feature_version=FEATURE_VERSION,
        source_feature_snapshot_ids=("FEATURESNAPSHOT:S11-AUDIT",),
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        feature_ts=START,
        label_rule_id="LABELRULE:FUTURE_1M_RETURN",
        split=DatasetSplit.VALIDATION,
        training_run_id=TRAINING_RUN_ID,
        training_run_hash=TRAINING_HASH,
        model_version_id=MODEL_VERSION_ID,
        model_version_hash=MODEL_VERSION_HASH,
        probabilities=probabilities,
        quantiles=quantiles,
        uncertainty=Decimal(uncertainty),
        calibration_status=CalibrationStatus.SEQUENCE_CONDITIONED_TRAIN_ONLY,
        calibration_metadata=calibration_metadata,
    )


def _policy() -> StrategyDecisionPolicy:
    return make_strategy_decision_policy(
        name="s11-audit-expected-net-edge-fixture",
        expected_cost=Decimal("0"),
        max_expected_cost=Decimal("0.004"),
        max_uncertainty=Decimal("0.040"),
        min_net_edge=Decimal("0.001"),
        uncertainty_buffer_multiplier=Decimal("0.5"),
    )


def _sizing_inputs(*, risk_budget_notional: str = "100") -> StrategySizingInputs:
    return StrategySizingInputs(
        risk_budget_notional=Decimal(risk_budget_notional),
        reference_price=Decimal("100"),
        current_drawdown=Decimal("0"),
        max_drawdown=Decimal("0.20"),
    )


def _quote(*, event_ts: datetime) -> QuoteEvent:
    return QuoteEvent(
        subscription_id="STREAM:S11:BTCUSD",
        source_id="SOURCE:S11:FIXTURE",
        venue_id=VENUE_ID,
        event_ts=event_ts,
        source_ts=event_ts,
        ingest_ts=START + timedelta(minutes=10),
        raw_payload_id="RAW:S11:QUOTE",
        quote_id="QUOTE:S11:ARRIVAL",
        instrument_id=INSTRUMENT_ID,
        best_bid=Decimal("99.98"),
        best_ask=Decimal("100.02"),
    )
