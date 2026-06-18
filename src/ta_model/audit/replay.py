"""Decision replay-by-trace harness for S11 audit evidence.

Traceability:
- FR-015: replay a sampled decision from a trace ID and reconstruct linked
  strategy, risk, paper gateway, accounting, and TCA evidence.
- NFR-004: order replay remains gated by stored independent ``RiskCheckEvent``
  evidence and never accepts raw order intents as gateway input.

Scope:
- Local typed contracts and pure replay orchestration only. No datastore, network,
  broker, Docker/runtime service, live capital, leverage, derivatives, or risk
  approval behavior is introduced.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import ValidationError

from ta_model.audit.trace import DecisionTraceEnvelope, make_decision_trace_envelope
from ta_model.contracts.decisions import StrategyDecision
from ta_model.contracts.execution import (
    ExecutionGatewayLifecycleEvent,
    ExecutionGatewayReport,
)
from ta_model.contracts.forecasts import Forecast
from ta_model.contracts.instrument_master import (
    CanonicalId,
    ContractModel,
    InstrumentMasterSnapshot,
    NonEmptyString,
)
from ta_model.contracts.market_data import OHLCTVBar
from ta_model.contracts.paper import (
    PaperAccountSessionReport,
    PaperAccountStateSource,
    PaperTcaReport,
)
from ta_model.contracts.risk import RiskCheckEvent
from ta_model.contracts.simulation import ExecutionCostModel, OrderIntent, SimulatedAccountState
from ta_model.contracts.streaming import QuoteEvent
from ta_model.execution import (
    make_paper_account_session_report,
    make_paper_tca_report,
    run_paper_gateway_replay,
)

_REPLAY_REQUIREMENTS = ("FR-015", "NFR-004")


class DecisionTraceReplayStatus(StrEnum):
    """Terminal replay harness status for one trace lookup."""

    PASSED = "passed"
    NO_ORDER = "no_order"
    FAILED = "failed"


class DecisionTraceReplayBlockerCode(StrEnum):
    """Fail-closed reason codes emitted by trace replay."""

    MISSING_TRACE_ID = "missing_trace_id"
    DUPLICATE_TRACE_EVIDENCE = "duplicate_trace_evidence"
    MISMATCHED_REQUESTED_TRACE = "mismatched_requested_trace"
    TAMPERED_EVIDENCE = "tampered_envelope_or_evidence"
    MISSING_REPLAY_INPUT = "missing_replay_input"
    RISK_GATEWAY_REPLAY_MISMATCH = "risk_gateway_replay_mismatch"
    PAPER_REPLAY_MISMATCH = "paper_replay_mismatch"
    TCA_REPLAY_MISMATCH = "tca_replay_mismatch"


class DecisionTraceReplayBlocker(ContractModel):
    """Structured failure detail for a closed replay attempt."""

    code: DecisionTraceReplayBlockerCode
    message: NonEmptyString
    expected: NonEmptyString | None = None
    actual: NonEmptyString | None = None


class DecisionTraceReplayEvidence(ContractModel):
    """All stored evidence needed to replay one decision trace locally.

    The harness still validates this evidence from first principles during replay;
    this model only names the narrow resolver payload and does not fetch fixtures,
    persist data, approve risk, or route orders.
    """

    trace_id: CanonicalId
    envelope: DecisionTraceEnvelope
    forecast: Forecast
    decision: StrategyDecision
    order_intent: OrderIntent | None = None
    risk_event: RiskCheckEvent | None = None
    gateway_report: ExecutionGatewayReport | None = None
    paper_account_report: PaperAccountSessionReport | None = None
    paper_tca_report: PaperTcaReport | None = None
    bars: tuple[OHLCTVBar, ...] = ()
    execution_cost_model: ExecutionCostModel | None = None
    instrument_master_snapshot: InstrumentMasterSnapshot | None = None
    starting_account_state: SimulatedAccountState | None = None
    quotes: tuple[QuoteEvent, ...] = ()
    requirement_ids: tuple[NonEmptyString, ...] = _REPLAY_REQUIREMENTS


class DecisionTraceEvidenceResolver(Protocol):
    """Narrow resolver seam for trace evidence lookup."""

    def resolve_trace_evidence(self, trace_id: str) -> Sequence[DecisionTraceReplayEvidence]:
        """Return all evidence records matching ``trace_id``."""


class InMemoryDecisionTraceEvidenceStore:
    """Local deterministic resolver useful for tests and fixture-backed smoke runs."""

    def __init__(self, evidence: Iterable[DecisionTraceReplayEvidence] = ()) -> None:
        self._evidence = tuple(evidence)

    def resolve_trace_evidence(self, trace_id: str) -> tuple[DecisionTraceReplayEvidence, ...]:
        return tuple(evidence for evidence in self._evidence if evidence.trace_id == trace_id)


class DecisionTraceReplayReport(ContractModel):
    """Typed replay report for one trace ID."""

    trace_id: CanonicalId
    status: DecisionTraceReplayStatus
    forecast_id: CanonicalId | None = None
    strategy_decision_id: CanonicalId | None = None
    strategy_decision_hash: str | None = None
    strategy_run_id: CanonicalId | None = None
    risk_run_id: CanonicalId | None = None
    original_gateway_run_id: CanonicalId | None = None
    replayed_gateway_run_id: CanonicalId | None = None
    stored_trace_envelope_id: CanonicalId | None = None
    stored_trace_envelope_hash: str | None = None
    reconstructed_trace_envelope_id: CanonicalId | None = None
    reconstructed_trace_envelope_hash: str | None = None
    stored_no_order_reason: NonEmptyString | None = None
    reconstructed_no_order_reason: NonEmptyString | None = None
    original_gateway_report_id: CanonicalId | None = None
    original_gateway_report_hash: str | None = None
    replayed_gateway_report_id: CanonicalId | None = None
    replayed_gateway_report_hash: str | None = None
    original_gateway_event_id: CanonicalId | None = None
    original_gateway_event_hash: str | None = None
    replayed_gateway_event_id: CanonicalId | None = None
    replayed_gateway_event_hash: str | None = None
    original_gateway_order_id: CanonicalId | None = None
    replayed_gateway_order_id: CanonicalId | None = None
    original_paper_session_report_id: CanonicalId | None = None
    original_paper_session_report_hash: str | None = None
    replayed_paper_session_report_id: CanonicalId | None = None
    replayed_paper_session_report_hash: str | None = None
    original_paper_order_log_ids: tuple[CanonicalId, ...] = ()
    replayed_paper_order_log_ids: tuple[CanonicalId, ...] = ()
    original_paper_fill_log_ids: tuple[CanonicalId, ...] = ()
    replayed_paper_fill_log_ids: tuple[CanonicalId, ...] = ()
    original_paper_rejection_log_ids: tuple[CanonicalId, ...] = ()
    replayed_paper_rejection_log_ids: tuple[CanonicalId, ...] = ()
    original_paper_tca_report_id: CanonicalId | None = None
    original_paper_tca_report_hash: str | None = None
    replayed_paper_tca_report_id: CanonicalId | None = None
    replayed_paper_tca_report_hash: str | None = None
    original_paper_tca_row_ids: tuple[CanonicalId, ...] = ()
    replayed_paper_tca_row_ids: tuple[CanonicalId, ...] = ()
    original_paper_tca_issue_ids: tuple[CanonicalId, ...] = ()
    replayed_paper_tca_issue_ids: tuple[CanonicalId, ...] = ()
    blockers: tuple[DecisionTraceReplayBlocker, ...] = ()
    requirement_ids: tuple[NonEmptyString, ...] = _REPLAY_REQUIREMENTS


def replay_decision_trace_by_id(
    *, trace_id: str, resolver: DecisionTraceEvidenceResolver
) -> DecisionTraceReplayReport:
    """Resolve and replay one decision trace through the paper gateway seam.

    Expected failures return ``DecisionTraceReplayReport(status=FAILED)`` with
    blockers instead of raising so audit gate callers can record closed results.
    """

    requested_trace_id = trace_id.strip()
    if not requested_trace_id:
        return _failure_report(
            trace_id="TRACE:MISSING",
            blocker=DecisionTraceReplayBlocker(
                code=DecisionTraceReplayBlockerCode.MISSING_TRACE_ID,
                message="trace_id is required for decision replay",
            ),
        )

    matches = tuple(resolver.resolve_trace_evidence(requested_trace_id))
    if not matches:
        return _failure_report(
            trace_id=requested_trace_id,
            blocker=DecisionTraceReplayBlocker(
                code=DecisionTraceReplayBlockerCode.MISSING_TRACE_ID,
                message="no trace evidence matched requested trace_id",
                expected=requested_trace_id,
                actual="0 matches",
            ),
        )
    if len(matches) > 1:
        return _failure_report(
            trace_id=requested_trace_id,
            blocker=DecisionTraceReplayBlocker(
                code=DecisionTraceReplayBlockerCode.DUPLICATE_TRACE_EVIDENCE,
                message="multiple trace evidence records matched requested trace_id",
                expected="1 match",
                actual=str(len(matches)),
            ),
        )

    evidence = matches[0]
    trace_blockers = _requested_trace_blockers(
        requested_trace_id=requested_trace_id, evidence=evidence
    )
    if trace_blockers:
        return _report(
            trace_id=requested_trace_id,
            status=DecisionTraceReplayStatus.FAILED,
            evidence=evidence,
            blockers=tuple(trace_blockers),
        )

    stored_envelope, blocker = _validated_stored_envelope(envelope=evidence.envelope)
    if blocker is not None:
        return _report(
            trace_id=requested_trace_id,
            status=DecisionTraceReplayStatus.FAILED,
            evidence=evidence,
            blockers=(blocker,),
        )

    artifact_blockers = _validate_replay_evidence_artifacts(evidence=evidence)
    if artifact_blockers:
        return _report(
            trace_id=requested_trace_id,
            status=DecisionTraceReplayStatus.FAILED,
            evidence=evidence,
            stored_envelope=stored_envelope,
            blockers=tuple(artifact_blockers),
        )

    missing_input_blockers = _missing_order_input_blockers(
        evidence=evidence, stored_envelope=stored_envelope
    )
    if missing_input_blockers:
        return _report(
            trace_id=requested_trace_id,
            status=DecisionTraceReplayStatus.FAILED,
            evidence=evidence,
            stored_envelope=stored_envelope,
            blockers=tuple(missing_input_blockers),
        )

    try:
        original_rebuilt_envelope = _make_envelope_from_evidence(evidence=evidence)
    except (ValueError, ValidationError) as exc:
        return _report(
            trace_id=requested_trace_id,
            status=DecisionTraceReplayStatus.FAILED,
            evidence=evidence,
            stored_envelope=stored_envelope,
            blockers=(
                DecisionTraceReplayBlocker(
                    code=DecisionTraceReplayBlockerCode.TAMPERED_EVIDENCE,
                    message=f"stored trace evidence failed envelope reconstruction: {exc}",
                ),
            ),
        )

    envelope_blockers = _compare_envelope(
        expected=stored_envelope,
        actual=original_rebuilt_envelope,
        code=DecisionTraceReplayBlockerCode.TAMPERED_EVIDENCE,
    )
    if envelope_blockers:
        return _report(
            trace_id=requested_trace_id,
            status=DecisionTraceReplayStatus.FAILED,
            evidence=evidence,
            stored_envelope=stored_envelope,
            reconstructed_envelope=original_rebuilt_envelope,
            blockers=tuple(envelope_blockers),
        )

    if evidence.order_intent is None:
        return _report(
            trace_id=requested_trace_id,
            status=DecisionTraceReplayStatus.NO_ORDER,
            evidence=evidence,
            stored_envelope=stored_envelope,
            reconstructed_envelope=original_rebuilt_envelope,
        )

    order_intent = evidence.order_intent
    risk_event = evidence.risk_event
    gateway_report = evidence.gateway_report
    paper_account_report = evidence.paper_account_report
    paper_tca_report = evidence.paper_tca_report
    if risk_event is None or gateway_report is None:
        raise AssertionError("order replay input validation failed to require risk/gateway")
    if paper_account_report is None or paper_tca_report is None:
        raise AssertionError("order replay input validation failed to require paper evidence")

    try:
        replayed_gateway_report = run_paper_gateway_replay(
            bars=evidence.bars,
            risk_events=(risk_event,),
            run_id=gateway_report.run_id,
            execution_cost_model=evidence.execution_cost_model,
            instrument_master_snapshot=evidence.instrument_master_snapshot,
            starting_account_state=evidence.starting_account_state,
        )
    except (ValueError, ValidationError) as exc:
        return _report(
            trace_id=requested_trace_id,
            status=DecisionTraceReplayStatus.FAILED,
            evidence=evidence,
            stored_envelope=stored_envelope,
            reconstructed_envelope=original_rebuilt_envelope,
            blockers=(
                DecisionTraceReplayBlocker(
                    code=DecisionTraceReplayBlockerCode.RISK_GATEWAY_REPLAY_MISMATCH,
                    message=f"paper gateway replay failed from stored risk evidence: {exc}",
                ),
            ),
        )

    try:
        replayed_paper_report = _rebuild_paper_account_report(
            original=paper_account_report,
            replayed_gateway_report=replayed_gateway_report,
        )
    except (ValueError, ValidationError) as exc:
        return _report(
            trace_id=requested_trace_id,
            status=DecisionTraceReplayStatus.FAILED,
            evidence=evidence,
            stored_envelope=stored_envelope,
            reconstructed_envelope=original_rebuilt_envelope,
            replayed_gateway_report=replayed_gateway_report,
            blockers=(
                DecisionTraceReplayBlocker(
                    code=DecisionTraceReplayBlockerCode.PAPER_REPLAY_MISMATCH,
                    message=f"paper account report rebuild failed: {exc}",
                ),
            ),
        )
    try:
        replayed_tca_report = make_paper_tca_report(
            gateway_report=replayed_gateway_report,
            quotes=evidence.quotes,
        )
        replayed_envelope = make_decision_trace_envelope(
            forecast=evidence.forecast,
            decision=evidence.decision,
            order_intent=order_intent,
            risk_event=risk_event,
            gateway_report=replayed_gateway_report,
            paper_account_report=replayed_paper_report,
            paper_tca_report=replayed_tca_report,
        )
    except (ValueError, ValidationError) as exc:
        return _report(
            trace_id=requested_trace_id,
            status=DecisionTraceReplayStatus.FAILED,
            evidence=evidence,
            stored_envelope=stored_envelope,
            reconstructed_envelope=original_rebuilt_envelope,
            replayed_gateway_report=replayed_gateway_report,
            replayed_paper_report=replayed_paper_report,
            blockers=(
                DecisionTraceReplayBlocker(
                    code=DecisionTraceReplayBlockerCode.TCA_REPLAY_MISMATCH,
                    message=f"TCA report or replay envelope rebuild failed: {exc}",
                ),
            ),
        )

    blockers = [
        *_compare_gateway_reports(expected=gateway_report, actual=replayed_gateway_report),
        *_compare_paper_reports(expected=paper_account_report, actual=replayed_paper_report),
        *_compare_tca_reports(expected=paper_tca_report, actual=replayed_tca_report),
        *_compare_envelope(
            expected=stored_envelope,
            actual=replayed_envelope,
            code=DecisionTraceReplayBlockerCode.TAMPERED_EVIDENCE,
        ),
    ]
    return _report(
        trace_id=requested_trace_id,
        status=(
            DecisionTraceReplayStatus.FAILED if blockers else DecisionTraceReplayStatus.PASSED
        ),
        evidence=evidence,
        stored_envelope=stored_envelope,
        reconstructed_envelope=replayed_envelope,
        replayed_gateway_report=replayed_gateway_report,
        replayed_paper_report=replayed_paper_report,
        replayed_tca_report=replayed_tca_report,
        blockers=tuple(blockers),
    )


def _validated_stored_envelope(
    *, envelope: DecisionTraceEnvelope
) -> tuple[DecisionTraceEnvelope, DecisionTraceReplayBlocker | None]:
    try:
        return DecisionTraceEnvelope.model_validate(envelope.model_dump()), None
    except (ValueError, ValidationError) as exc:
        return envelope, DecisionTraceReplayBlocker(
            code=DecisionTraceReplayBlockerCode.TAMPERED_EVIDENCE,
            message=f"stored trace envelope failed deterministic validation: {exc}",
        )


def _requested_trace_blockers(
    *, requested_trace_id: str, evidence: DecisionTraceReplayEvidence
) -> list[DecisionTraceReplayBlocker]:
    checks: tuple[tuple[str, str, str], ...] = (
        ("evidence.trace_id", evidence.trace_id, requested_trace_id),
        ("envelope.trace_id", evidence.envelope.trace_id, requested_trace_id),
        ("decision.trace_id", evidence.decision.trace_id, requested_trace_id),
    )
    blockers: list[DecisionTraceReplayBlocker] = []
    for label, actual, expected in checks:
        if actual != expected:
            blockers.append(
                DecisionTraceReplayBlocker(
                    code=DecisionTraceReplayBlockerCode.MISMATCHED_REQUESTED_TRACE,
                    message=f"{label} does not match requested trace_id",
                    expected=expected,
                    actual=actual,
                )
            )
    return blockers


def _validate_replay_evidence_artifacts(
    *, evidence: DecisionTraceReplayEvidence
) -> list[DecisionTraceReplayBlocker]:
    artifacts: list[tuple[str, ContractModel]] = [
        ("forecast", evidence.forecast),
        ("strategy_decision", evidence.decision),
    ]
    if evidence.order_intent is not None:
        artifacts.append(("order_intent", evidence.order_intent))
    if evidence.risk_event is not None:
        artifacts.append(("risk_event", evidence.risk_event))
        artifacts.append(("risk_event.request", evidence.risk_event.request))
    if evidence.gateway_report is not None:
        artifacts.append(("gateway_report", evidence.gateway_report))
    if evidence.paper_account_report is not None:
        artifacts.append(("paper_account_report", evidence.paper_account_report))
    if evidence.paper_tca_report is not None:
        artifacts.append(("paper_tca_report", evidence.paper_tca_report))
    if evidence.execution_cost_model is not None:
        artifacts.append(("execution_cost_model", evidence.execution_cost_model))
    if evidence.instrument_master_snapshot is not None:
        artifacts.append(("instrument_master_snapshot", evidence.instrument_master_snapshot))
    if evidence.starting_account_state is not None:
        artifacts.append(("starting_account_state", evidence.starting_account_state))
    artifacts.extend((f"bar[{index}]", bar) for index, bar in enumerate(evidence.bars))
    artifacts.extend((f"quote[{index}]", quote) for index, quote in enumerate(evidence.quotes))

    blockers: list[DecisionTraceReplayBlocker] = []
    for label, artifact in artifacts:
        blocker = _validate_contract_artifact(label=label, artifact=artifact)
        if blocker is not None:
            blockers.append(blocker)
    return blockers


def _validate_contract_artifact(
    *, label: str, artifact: ContractModel
) -> DecisionTraceReplayBlocker | None:
    try:
        type(artifact).model_validate(artifact.model_dump())
    except (TypeError, ValueError, ValidationError) as exc:
        return DecisionTraceReplayBlocker(
            code=DecisionTraceReplayBlockerCode.TAMPERED_EVIDENCE,
            message=f"stored {label} artifact failed deterministic validation: {exc}",
        )
    return None


def _missing_order_input_blockers(
    *, evidence: DecisionTraceReplayEvidence, stored_envelope: DecisionTraceEnvelope
) -> list[DecisionTraceReplayBlocker]:
    order_trace = evidence.order_intent is not None or stored_envelope.order_intent_id is not None
    if not order_trace:
        return []
    missing: list[str] = []
    if evidence.order_intent is None:
        missing.append("order_intent")
    if evidence.risk_event is None:
        missing.append("risk_event")
    if evidence.gateway_report is None:
        missing.append("gateway_report")
    if evidence.paper_account_report is None:
        missing.append("paper_account_report")
    if evidence.paper_tca_report is None:
        missing.append("paper_tca_report")
    if not evidence.bars:
        missing.append("bars")
    if not missing:
        return []
    return [
        DecisionTraceReplayBlocker(
            code=DecisionTraceReplayBlockerCode.MISSING_REPLAY_INPUT,
            message="order trace evidence is missing required replay inputs",
            expected="order_intent,risk_event,gateway_report,paper_account_report,"
            "paper_tca_report,bars",
            actual=",".join(missing),
        )
    ]


def _make_envelope_from_evidence(*, evidence: DecisionTraceReplayEvidence) -> DecisionTraceEnvelope:
    if evidence.order_intent is None:
        return make_decision_trace_envelope(
            forecast=evidence.forecast,
            decision=evidence.decision,
        )
    if (
        evidence.risk_event is None
        or evidence.gateway_report is None
        or evidence.paper_account_report is None
        or evidence.paper_tca_report is None
    ):
        raise ValueError("order trace evidence is missing downstream artifacts")
    return make_decision_trace_envelope(
        forecast=evidence.forecast,
        decision=evidence.decision,
        order_intent=evidence.order_intent,
        risk_event=evidence.risk_event,
        gateway_report=evidence.gateway_report,
        paper_account_report=evidence.paper_account_report,
        paper_tca_report=evidence.paper_tca_report,
    )


def _rebuild_paper_account_report(
    *, original: PaperAccountSessionReport, replayed_gateway_report: ExecutionGatewayReport
) -> PaperAccountSessionReport:
    initial_state = original.initial_account_state
    initial_id = None if initial_state is not None else original.initial_account_state_id
    initial_hash = None if initial_state is not None else original.initial_account_state_hash
    final_state = None
    final_id = None
    final_hash = None
    if (
        replayed_gateway_report.source_replay_final_account_state is None
        and original.final_account_state_source is PaperAccountStateSource.EXPLICIT_LINKAGE
    ):
        final_state = original.final_account_state
        final_id = None if final_state is not None else original.final_account_state_id
        final_hash = None if final_state is not None else original.final_account_state_hash
    return make_paper_account_session_report(
        gateway_report=replayed_gateway_report,
        initial_account_state=initial_state,
        final_account_state=final_state,
        initial_account_state_id=initial_id,
        initial_account_state_hash=initial_hash,
        final_account_state_id=final_id,
        final_account_state_hash=final_hash,
    )


def _compare_envelope(
    *,
    expected: DecisionTraceEnvelope,
    actual: DecisionTraceEnvelope,
    code: DecisionTraceReplayBlockerCode,
) -> list[DecisionTraceReplayBlocker]:
    return _compare_fields(
        code=code,
        label_prefix="trace envelope",
        fields=(
            ("trace_envelope_id", expected.trace_envelope_id, actual.trace_envelope_id),
            ("trace_envelope_hash", expected.trace_envelope_hash, actual.trace_envelope_hash),
            ("trace_id", expected.trace_id, actual.trace_id),
            ("strategy_decision_id", expected.strategy_decision_id, actual.strategy_decision_id),
            ("order_intent_id", expected.order_intent_id, actual.order_intent_id),
            ("risk_check_id", expected.risk_check_id, actual.risk_check_id),
            ("gateway_report_id", expected.gateway_report_id, actual.gateway_report_id),
            ("gateway_event_id", expected.gateway_event_id, actual.gateway_event_id),
            (
                "paper_session_report_id",
                expected.paper_session_report_id,
                actual.paper_session_report_id,
            ),
            ("paper_tca_report_id", expected.paper_tca_report_id, actual.paper_tca_report_id),
            ("paper_fill_log_ids", expected.paper_fill_log_ids, actual.paper_fill_log_ids),
            (
                "paper_rejection_log_ids",
                expected.paper_rejection_log_ids,
                actual.paper_rejection_log_ids,
            ),
            ("paper_tca_row_ids", expected.paper_tca_row_ids, actual.paper_tca_row_ids),
            ("paper_tca_issue_ids", expected.paper_tca_issue_ids, actual.paper_tca_issue_ids),
        ),
    )


def _compare_gateway_reports(
    *, expected: ExecutionGatewayReport, actual: ExecutionGatewayReport
) -> list[DecisionTraceReplayBlocker]:
    blockers = _compare_fields(
        code=DecisionTraceReplayBlockerCode.RISK_GATEWAY_REPLAY_MISMATCH,
        label_prefix="gateway replay",
        fields=(
            ("gateway_report_id", expected.gateway_report_id, actual.gateway_report_id),
            ("gateway_report_hash", expected.gateway_report_hash, actual.gateway_report_hash),
            ("risk_check_ids", expected.risk_check_ids, actual.risk_check_ids),
            (
                "approved_risk_check_ids",
                expected.approved_risk_check_ids,
                actual.approved_risk_check_ids,
            ),
            (
                "blocked_risk_check_ids",
                expected.blocked_risk_check_ids,
                actual.blocked_risk_check_ids,
            ),
        ),
    )
    if len(expected.events) != 1 or len(actual.events) != 1:
        blockers.append(
            DecisionTraceReplayBlocker(
                code=DecisionTraceReplayBlockerCode.RISK_GATEWAY_REPLAY_MISMATCH,
                message="gateway replay event count did not reproduce one trace event",
                expected=str(len(expected.events)),
                actual=str(len(actual.events)),
            )
        )
        return blockers
    expected_event = expected.events[0]
    actual_event = actual.events[0]
    blockers.extend(
        _compare_fields(
            code=DecisionTraceReplayBlockerCode.RISK_GATEWAY_REPLAY_MISMATCH,
            label_prefix="gateway replay",
            fields=(
                (
                    "gateway_event_id",
                    expected_event.gateway_event_id,
                    actual_event.gateway_event_id,
                ),
                (
                    "gateway_event_hash",
                    expected_event.gateway_event_hash,
                    actual_event.gateway_event_hash,
                ),
                (
                    "gateway_order_id",
                    expected_event.gateway_order_id,
                    actual_event.gateway_order_id,
                ),
                ("status", expected_event.status, actual_event.status),
                (
                    "replay_order_result_id",
                    expected_event.replay_order_result_id,
                    actual_event.replay_order_result_id,
                ),
                ("filled_quantity", expected_event.filled_quantity, actual_event.filled_quantity),
                (
                    "remaining_quantity",
                    expected_event.remaining_quantity,
                    actual_event.remaining_quantity,
                ),
                ("fill_price", expected_event.fill_price, actual_event.fill_price),
                ("total_cost", expected_event.total_cost, actual_event.total_cost),
            ),
        )
    )
    return blockers


def _compare_paper_reports(
    *, expected: PaperAccountSessionReport, actual: PaperAccountSessionReport
) -> list[DecisionTraceReplayBlocker]:
    return _compare_fields(
        code=DecisionTraceReplayBlockerCode.PAPER_REPLAY_MISMATCH,
        label_prefix="paper account replay",
        fields=(
            ("session_report_id", expected.session_report_id, actual.session_report_id),
            ("session_report_hash", expected.session_report_hash, actual.session_report_hash),
            ("order_log_ids", expected.order_log_ids, actual.order_log_ids),
            ("fill_log_ids", expected.fill_log_ids, actual.fill_log_ids),
            ("rejection_log_ids", expected.rejection_log_ids, actual.rejection_log_ids),
            ("total_order_count", expected.total_order_count, actual.total_order_count),
            ("filled_order_count", expected.filled_order_count, actual.filled_order_count),
            ("blocked_order_count", expected.blocked_order_count, actual.blocked_order_count),
            ("rejected_order_count", expected.rejected_order_count, actual.rejected_order_count),
            ("unfilled_order_count", expected.unfilled_order_count, actual.unfilled_order_count),
            ("filled_quantity_total", expected.filled_quantity_total, actual.filled_quantity_total),
            ("total_execution_cost", expected.total_execution_cost, actual.total_execution_cost),
        ),
    )


def _compare_tca_reports(
    *, expected: PaperTcaReport, actual: PaperTcaReport
) -> list[DecisionTraceReplayBlocker]:
    return _compare_fields(
        code=DecisionTraceReplayBlockerCode.TCA_REPLAY_MISMATCH,
        label_prefix="paper TCA replay",
        fields=(
            ("tca_report_id", expected.tca_report_id, actual.tca_report_id),
            ("tca_report_hash", expected.tca_report_hash, actual.tca_report_hash),
            ("row_ids", expected.row_ids, actual.row_ids),
            ("issue_ids", expected.issue_ids, actual.issue_ids),
            ("filled_row_count", expected.filled_row_count, actual.filled_row_count),
            ("issue_count", expected.issue_count, actual.issue_count),
            ("error_count", expected.error_count, actual.error_count),
            ("fee_cost_total", expected.fee_cost_total, actual.fee_cost_total),
            ("predicted_total_cost", expected.predicted_total_cost, actual.predicted_total_cost),
            ("realized_total_cost", expected.realized_total_cost, actual.realized_total_cost),
            (
                "total_cost_prediction_error",
                expected.total_cost_prediction_error,
                actual.total_cost_prediction_error,
            ),
        ),
    )


def _compare_fields(
    *,
    code: DecisionTraceReplayBlockerCode,
    label_prefix: str,
    fields: tuple[tuple[str, object, object], ...],
) -> list[DecisionTraceReplayBlocker]:
    blockers: list[DecisionTraceReplayBlocker] = []
    for field_name, expected, actual in fields:
        if expected != actual:
            blockers.append(
                DecisionTraceReplayBlocker(
                    code=code,
                    message=f"{label_prefix} {field_name} did not reproduce",
                    expected=_display(expected),
                    actual=_display(actual),
                )
            )
    return blockers


def _failure_report(
    *, trace_id: str, blocker: DecisionTraceReplayBlocker
) -> DecisionTraceReplayReport:
    return DecisionTraceReplayReport(
        trace_id=trace_id,
        status=DecisionTraceReplayStatus.FAILED,
        blockers=(blocker,),
    )


def _report(
    *,
    trace_id: str,
    status: DecisionTraceReplayStatus,
    evidence: DecisionTraceReplayEvidence | None = None,
    stored_envelope: DecisionTraceEnvelope | None = None,
    reconstructed_envelope: DecisionTraceEnvelope | None = None,
    replayed_gateway_report: ExecutionGatewayReport | None = None,
    replayed_paper_report: PaperAccountSessionReport | None = None,
    replayed_tca_report: PaperTcaReport | None = None,
    blockers: tuple[DecisionTraceReplayBlocker, ...] = (),
) -> DecisionTraceReplayReport:
    original_gateway_event = _matching_report_event(
        gateway_report=evidence.gateway_report if evidence is not None else None,
        risk_event=evidence.risk_event if evidence is not None else None,
        decision=evidence.decision if evidence is not None else None,
    )
    replayed_gateway_event = _matching_report_event(
        gateway_report=replayed_gateway_report,
        risk_event=evidence.risk_event if evidence is not None else None,
        decision=evidence.decision if evidence is not None else None,
    )
    original_envelope = stored_envelope or (evidence.envelope if evidence is not None else None)
    original_paper_report = evidence.paper_account_report if evidence is not None else None
    original_tca_report = evidence.paper_tca_report if evidence is not None else None
    return DecisionTraceReplayReport(
        trace_id=trace_id,
        status=status,
        forecast_id=evidence.forecast.forecast_id if evidence is not None else None,
        strategy_decision_id=evidence.decision.decision_id if evidence is not None else None,
        strategy_decision_hash=evidence.decision.decision_hash if evidence is not None else None,
        strategy_run_id=evidence.decision.strategy_run_id if evidence is not None else None,
        risk_run_id=(
            evidence.risk_event.request.run_id
            if evidence is not None and evidence.risk_event is not None
            else None
        ),
        original_gateway_run_id=(
            evidence.gateway_report.run_id
            if evidence is not None and evidence.gateway_report is not None
            else None
        ),
        replayed_gateway_run_id=(
            replayed_gateway_report.run_id if replayed_gateway_report is not None else None
        ),
        stored_trace_envelope_id=(
            original_envelope.trace_envelope_id if original_envelope is not None else None
        ),
        stored_trace_envelope_hash=(
            original_envelope.trace_envelope_hash if original_envelope is not None else None
        ),
        reconstructed_trace_envelope_id=(
            reconstructed_envelope.trace_envelope_id
            if reconstructed_envelope is not None
            else None
        ),
        reconstructed_trace_envelope_hash=(
            reconstructed_envelope.trace_envelope_hash
            if reconstructed_envelope is not None
            else None
        ),
        stored_no_order_reason=(
            original_envelope.no_order_reason if original_envelope is not None else None
        ),
        reconstructed_no_order_reason=(
            reconstructed_envelope.no_order_reason
            if reconstructed_envelope is not None
            else None
        ),
        original_gateway_report_id=(
            evidence.gateway_report.gateway_report_id
            if evidence is not None and evidence.gateway_report is not None
            else None
        ),
        original_gateway_report_hash=(
            evidence.gateway_report.gateway_report_hash
            if evidence is not None and evidence.gateway_report is not None
            else None
        ),
        replayed_gateway_report_id=(
            replayed_gateway_report.gateway_report_id
            if replayed_gateway_report is not None
            else None
        ),
        replayed_gateway_report_hash=(
            replayed_gateway_report.gateway_report_hash
            if replayed_gateway_report is not None
            else None
        ),
        original_gateway_event_id=(
            original_gateway_event.gateway_event_id if original_gateway_event is not None else None
        ),
        original_gateway_event_hash=(
            original_gateway_event.gateway_event_hash
            if original_gateway_event is not None
            else None
        ),
        replayed_gateway_event_id=(
            replayed_gateway_event.gateway_event_id if replayed_gateway_event is not None else None
        ),
        replayed_gateway_event_hash=(
            replayed_gateway_event.gateway_event_hash
            if replayed_gateway_event is not None
            else None
        ),
        original_gateway_order_id=(
            original_gateway_event.gateway_order_id if original_gateway_event is not None else None
        ),
        replayed_gateway_order_id=(
            replayed_gateway_event.gateway_order_id if replayed_gateway_event is not None else None
        ),
        original_paper_session_report_id=(
            original_paper_report.session_report_id if original_paper_report is not None else None
        ),
        original_paper_session_report_hash=(
            original_paper_report.session_report_hash if original_paper_report is not None else None
        ),
        replayed_paper_session_report_id=(
            replayed_paper_report.session_report_id if replayed_paper_report is not None else None
        ),
        replayed_paper_session_report_hash=(
            replayed_paper_report.session_report_hash if replayed_paper_report is not None else None
        ),
        original_paper_order_log_ids=(
            original_envelope.paper_order_log_ids if original_envelope is not None else ()
        ),
        replayed_paper_order_log_ids=(
            reconstructed_envelope.paper_order_log_ids
            if reconstructed_envelope is not None
            else ()
        ),
        original_paper_fill_log_ids=(
            original_envelope.paper_fill_log_ids if original_envelope is not None else ()
        ),
        replayed_paper_fill_log_ids=(
            reconstructed_envelope.paper_fill_log_ids
            if reconstructed_envelope is not None
            else ()
        ),
        original_paper_rejection_log_ids=(
            original_envelope.paper_rejection_log_ids if original_envelope is not None else ()
        ),
        replayed_paper_rejection_log_ids=(
            reconstructed_envelope.paper_rejection_log_ids
            if reconstructed_envelope is not None
            else ()
        ),
        original_paper_tca_report_id=(
            original_tca_report.tca_report_id if original_tca_report is not None else None
        ),
        original_paper_tca_report_hash=(
            original_tca_report.tca_report_hash if original_tca_report is not None else None
        ),
        replayed_paper_tca_report_id=(
            replayed_tca_report.tca_report_id if replayed_tca_report is not None else None
        ),
        replayed_paper_tca_report_hash=(
            replayed_tca_report.tca_report_hash if replayed_tca_report is not None else None
        ),
        original_paper_tca_row_ids=(
            original_envelope.paper_tca_row_ids if original_envelope is not None else ()
        ),
        replayed_paper_tca_row_ids=(
            reconstructed_envelope.paper_tca_row_ids
            if reconstructed_envelope is not None
            else ()
        ),
        original_paper_tca_issue_ids=(
            original_envelope.paper_tca_issue_ids if original_envelope is not None else ()
        ),
        replayed_paper_tca_issue_ids=(
            reconstructed_envelope.paper_tca_issue_ids
            if reconstructed_envelope is not None
            else ()
        ),
        blockers=blockers,
    )


def _matching_report_event(
    *,
    gateway_report: ExecutionGatewayReport | None,
    risk_event: RiskCheckEvent | None,
    decision: StrategyDecision | None,
) -> ExecutionGatewayLifecycleEvent | None:
    if gateway_report is None or risk_event is None or decision is None:
        return None
    matches = tuple(
        event
        for event in gateway_report.events
        if event.risk_check_id == risk_event.risk_check_id
        and event.risk_check_hash == risk_event.risk_check_hash
        and event.trace_id == decision.trace_id
        and event.source_decision_id == decision.decision_id
    )
    if len(matches) != 1:
        return None
    return matches[0]


def _display(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, tuple):
        return ",".join(_display(item) or "None" for item in value)
    return str(value)
