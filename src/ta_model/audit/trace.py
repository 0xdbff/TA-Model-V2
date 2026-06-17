"""S11 audit trace envelope and strategy-to-order seam.

Traceability:
- FR-015: one trace ID can reference the forecast/model/training, strategy,
  risk, gateway, paper accounting, and TCA evidence needed for reconstruction.
- NFR-004: order evidence remains tied to a strategy decision and independent
  risk approval/block event before paper gateway/accounting artifacts are linked.

Scope:
- Local typed contracts and pure builders only. No datastore, network, broker,
  live capital, leverage, derivatives, or risk approval behavior is introduced.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator

from ta_model.contracts.decisions import (
    StrategyDecision,
    StrategyDecisionAction,
    StrategySizingStatus,
)
from ta_model.contracts.execution import (
    ExecutionGatewayLifecycleEvent,
    ExecutionGatewayOrderStatus,
    ExecutionGatewayReport,
)
from ta_model.contracts.forecasts import Forecast
from ta_model.contracts.instrument_master import (
    CanonicalId,
    ContractModel,
    NonEmptyString,
    OrderType,
)
from ta_model.contracts.paper import PaperAccountSessionReport, PaperTcaReport
from ta_model.contracts.risk import RiskCheckEvent, RiskDecisionStatus, build_order_intent_hash
from ta_model.contracts.simulation import OrderIntent, OrderSide

_AUDIT_REQUIREMENTS = ("FR-015", "NFR-004")
_HASH_RE = r"^[a-f0-9]{64}$"
_FILLED_GATEWAY_STATUSES = {
    ExecutionGatewayOrderStatus.FILLED,
    ExecutionGatewayOrderStatus.PARTIALLY_FILLED,
}


class StrategyOrderIntentBuildError(ValueError):
    """Raised when a strategy decision cannot produce an order intent safely."""


class ForecastTraceReference(ContractModel):
    """Immutable pre-strategy/model lineage referenced by a decision trace."""

    forecast_id: CanonicalId
    dataset_snapshot_id: CanonicalId
    dataset_hash: str = Field(pattern=_HASH_RE)
    dataset_row_id: CanonicalId
    feature_vector_id: CanonicalId
    feature_input_snapshot_id: CanonicalId
    feature_version: NonEmptyString
    source_feature_snapshot_ids: tuple[CanonicalId, ...] = ()
    training_run_id: CanonicalId
    training_run_hash: str = Field(pattern=_HASH_RE)
    model_version_id: CanonicalId
    model_version_hash: str = Field(pattern=_HASH_RE)


class DecisionTraceEnvelope(ContractModel):
    """Audit bundle that links one trace ID to deterministic evidence artifacts."""

    trace_envelope_id: CanonicalId
    trace_envelope_hash: str = Field(pattern=_HASH_RE)
    trace_id: CanonicalId
    forecast: ForecastTraceReference
    strategy_decision_id: CanonicalId
    strategy_decision_hash: str = Field(pattern=_HASH_RE)
    strategy_run_id: CanonicalId
    policy_id: CanonicalId
    policy_hash: str = Field(pattern=_HASH_RE)
    no_order_reason: NonEmptyString | None = None
    order_intent_id: CanonicalId | None = None
    order_intent_hash: str | None = Field(default=None, pattern=_HASH_RE)
    risk_run_id: CanonicalId | None = None
    risk_request_id: CanonicalId | None = None
    risk_request_hash: str | None = Field(default=None, pattern=_HASH_RE)
    risk_check_id: CanonicalId | None = None
    risk_check_hash: str | None = Field(default=None, pattern=_HASH_RE)
    risk_decision: RiskDecisionStatus | None = None
    gateway_run_id: CanonicalId | None = None
    gateway_report_id: CanonicalId | None = None
    gateway_report_hash: str | None = Field(default=None, pattern=_HASH_RE)
    gateway_event_id: CanonicalId | None = None
    gateway_event_hash: str | None = Field(default=None, pattern=_HASH_RE)
    gateway_order_id: CanonicalId | None = None
    paper_run_id: CanonicalId | None = None
    paper_session_report_id: CanonicalId | None = None
    paper_session_report_hash: str | None = Field(default=None, pattern=_HASH_RE)
    paper_order_log_ids: tuple[CanonicalId, ...] = ()
    paper_fill_log_ids: tuple[CanonicalId, ...] = ()
    paper_rejection_log_ids: tuple[CanonicalId, ...] = ()
    paper_tca_report_id: CanonicalId | None = None
    paper_tca_report_hash: str | None = Field(default=None, pattern=_HASH_RE)
    paper_tca_row_ids: tuple[CanonicalId, ...] = ()
    paper_tca_issue_ids: tuple[CanonicalId, ...] = ()
    requirement_ids: tuple[NonEmptyString, ...] = _AUDIT_REQUIREMENTS

    @model_validator(mode="after")
    def envelope_is_complete_and_deterministic(self) -> Self:
        self._validate_ref_pair(
            self.order_intent_id,
            self.order_intent_hash,
            "order intent",
            required=False,
        )
        has_order = self.order_intent_id is not None
        if has_order:
            self._validate_order_trace_is_complete()
        else:
            self._validate_no_order_trace_has_no_downstream_artifacts()
        if self.gateway_run_id is not None and self.paper_run_id is not None:
            if self.gateway_run_id != self.paper_run_id:
                raise ValueError("paper_run_id must match gateway_run_id")
        expected_hash = build_decision_trace_envelope_hash(envelope=self)
        if self.trace_envelope_hash != expected_hash:
            raise ValueError("trace_envelope_hash is not deterministic")
        if self.trace_envelope_id != build_decision_trace_envelope_id(
            trace_envelope_hash=expected_hash
        ):
            raise ValueError("trace_envelope_id is not deterministic")
        return self

    def _validate_order_trace_is_complete(self) -> None:
        if self.no_order_reason is not None:
            raise ValueError("order trace envelopes must not set no_order_reason")
        if self.risk_run_id is None or self.gateway_run_id is None or self.paper_run_id is None:
            raise ValueError("order trace envelopes require risk, gateway, and paper run IDs")
        if self.risk_decision is None:
            raise ValueError("order trace envelopes require a risk decision")
        self._validate_ref_pair(self.risk_request_id, self.risk_request_hash, "risk request")
        self._validate_ref_pair(self.risk_check_id, self.risk_check_hash, "risk check")
        self._validate_ref_pair(self.gateway_report_id, self.gateway_report_hash, "gateway report")
        self._validate_ref_pair(self.gateway_event_id, self.gateway_event_hash, "gateway event")
        self._validate_ref_pair(
            self.paper_session_report_id,
            self.paper_session_report_hash,
            "paper session report",
        )
        self._validate_ref_pair(self.paper_tca_report_id, self.paper_tca_report_hash, "TCA report")
        if not self.paper_order_log_ids:
            raise ValueError("order trace envelopes require at least one paper order log")

    def _validate_no_order_trace_has_no_downstream_artifacts(self) -> None:
        if self.no_order_reason is None:
            raise ValueError("no-order trace envelopes require no_order_reason")
        downstream_values = (
            self.risk_run_id,
            self.risk_request_id,
            self.risk_request_hash,
            self.risk_check_id,
            self.risk_check_hash,
            self.risk_decision,
            self.gateway_run_id,
            self.gateway_report_id,
            self.gateway_report_hash,
            self.gateway_event_id,
            self.gateway_event_hash,
            self.gateway_order_id,
            self.paper_run_id,
            self.paper_session_report_id,
            self.paper_session_report_hash,
            self.paper_tca_report_id,
            self.paper_tca_report_hash,
        )
        if any(value is not None for value in downstream_values):
            raise ValueError("no-order trace envelopes must not carry downstream order artifacts")
        downstream_ids = (
            *self.paper_order_log_ids,
            *self.paper_fill_log_ids,
            *self.paper_rejection_log_ids,
            *self.paper_tca_row_ids,
            *self.paper_tca_issue_ids,
        )
        if downstream_ids:
            raise ValueError("no-order trace envelopes must not carry paper log/TCA IDs")

    @staticmethod
    def _validate_ref_pair(
        artifact_id: str | None,
        artifact_hash: str | None,
        label: str,
        *,
        required: bool = True,
    ) -> None:
        if (artifact_id is None) != (artifact_hash is None):
            raise ValueError(f"{label} id/hash must be set together")
        if required and artifact_id is None:
            raise ValueError(f"{label} id/hash are required")


def build_order_intent_from_strategy_decision(
    *,
    decision: StrategyDecision,
    submitted_at: datetime | None = None,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
) -> OrderIntent:
    """Create a deterministic pre-risk order intent from a positive BUY decision.

    The builder only emits an ``OrderIntent``. It does not approve risk, route,
    submit, simulate, or paper-trade the order.
    """

    if decision.action is StrategyDecisionAction.NO_TRADE:
        raise StrategyOrderIntentBuildError("no-trade decisions cannot create order intents")
    if decision.sizing.sizing_status is not StrategySizingStatus.PROPOSED_PENDING_INDEPENDENT_RISK:
        raise StrategyOrderIntentBuildError(
            "positive pre-risk sizing is required to create an order intent"
        )
    if decision.sizing.proposed_notional <= 0 or decision.sizing.proposed_quantity <= 0:
        raise StrategyOrderIntentBuildError(
            "positive pre-risk sizing is required to create an order intent"
        )
    actual_submitted_at = submitted_at or decision.decision_ts
    if actual_submitted_at < decision.decision_ts:
        raise StrategyOrderIntentBuildError("submitted_at must not precede decision_ts")
    return OrderIntent(
        client_order_id=build_order_intent_client_order_id(
            decision=decision,
            submitted_at=actual_submitted_at,
            order_type=order_type,
            limit_price=limit_price,
        ),
        trace_id=decision.trace_id,
        source_decision_id=decision.decision_id,
        instrument_id=decision.instrument_id,
        venue_id=decision.venue_id,
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=decision.sizing.proposed_quantity,
        submitted_at=actual_submitted_at,
        limit_price=limit_price,
    )


def build_order_intent_client_order_id(
    *,
    decision: StrategyDecision,
    submitted_at: datetime,
    order_type: OrderType,
    limit_price: Decimal | None = None,
) -> str:
    """Build the deterministic client order ID for the strategy/order seam."""

    return _stable_id(
        "ORDERINTENT",
        {
            "decision_hash": decision.decision_hash,
            "decision_id": decision.decision_id,
            "instrument_id": decision.instrument_id,
            "limit_price": _decimal(limit_price),
            "order_type": order_type.value,
            "proposed_quantity": str(decision.sizing.proposed_quantity),
            "submitted_at": submitted_at.isoformat(),
            "trace_id": decision.trace_id,
            "venue_id": decision.venue_id,
        },
    )


def make_decision_trace_envelope(
    *,
    forecast: Forecast,
    decision: StrategyDecision,
    order_intent: OrderIntent | None = None,
    risk_event: RiskCheckEvent | None = None,
    gateway_report: ExecutionGatewayReport | None = None,
    paper_account_report: PaperAccountSessionReport | None = None,
    paper_tca_report: PaperTcaReport | None = None,
) -> DecisionTraceEnvelope:
    """Build a deterministic trace envelope from real evidence objects."""

    _validate_forecast_decision_lineage(forecast=forecast, decision=decision)
    forecast_ref = _forecast_reference_from_forecast(forecast)
    if order_intent is None:
        if any(
            artifact is not None
            for artifact in (risk_event, gateway_report, paper_account_report, paper_tca_report)
        ):
            raise ValueError("no-order trace envelopes cannot include downstream artifacts")
        no_order_reason = _no_order_reason(decision)
        if no_order_reason is None:
            raise ValueError("no-order trace envelopes require no-trade or zero-size decision")
        return _build_trace_envelope(
            forecast_ref=forecast_ref,
            decision=decision,
            no_order_reason=no_order_reason,
        )

    if risk_event is None or gateway_report is None:
        raise ValueError("order trace envelopes require risk and gateway evidence")
    if paper_account_report is None or paper_tca_report is None:
        raise ValueError("order trace envelopes require paper account and TCA evidence")
    _validate_order_intent_matches_decision(order_intent=order_intent, decision=decision)
    _validate_risk_event_matches_order(
        risk_event=risk_event,
        order_intent=order_intent,
        decision=decision,
    )
    gateway_event = _matching_gateway_event(
        gateway_report=gateway_report,
        risk_event=risk_event,
        decision=decision,
    )
    paper_order_log_ids, paper_fill_log_ids, paper_rejection_log_ids = _paper_account_ids_for_event(
        paper_account_report=paper_account_report,
        gateway_report=gateway_report,
        gateway_event=gateway_event,
    )
    paper_tca_row_ids, paper_tca_issue_ids = _paper_tca_ids_for_event(
        paper_tca_report=paper_tca_report,
        gateway_report=gateway_report,
        gateway_event=gateway_event,
    )
    return _build_trace_envelope(
        forecast_ref=forecast_ref,
        decision=decision,
        order_intent=order_intent,
        risk_event=risk_event,
        gateway_report=gateway_report,
        gateway_event=gateway_event,
        paper_account_report=paper_account_report,
        paper_tca_report=paper_tca_report,
        paper_order_log_ids=paper_order_log_ids,
        paper_fill_log_ids=paper_fill_log_ids,
        paper_rejection_log_ids=paper_rejection_log_ids,
        paper_tca_row_ids=paper_tca_row_ids,
        paper_tca_issue_ids=paper_tca_issue_ids,
    )


def build_decision_trace_envelope_hash(*, envelope: DecisionTraceEnvelope) -> str:
    return _hash(
        _model_payload(
            envelope,
            exclude={"trace_envelope_id", "trace_envelope_hash"},
        )
    )


def build_decision_trace_envelope_id(*, trace_envelope_hash: str) -> str:
    return _stable_id("AUDITTRACE", {"trace_envelope_hash": trace_envelope_hash})


def _build_trace_envelope(
    *,
    forecast_ref: ForecastTraceReference,
    decision: StrategyDecision,
    no_order_reason: str | None = None,
    order_intent: OrderIntent | None = None,
    risk_event: RiskCheckEvent | None = None,
    gateway_report: ExecutionGatewayReport | None = None,
    gateway_event: ExecutionGatewayLifecycleEvent | None = None,
    paper_account_report: PaperAccountSessionReport | None = None,
    paper_tca_report: PaperTcaReport | None = None,
    paper_order_log_ids: tuple[str, ...] = (),
    paper_fill_log_ids: tuple[str, ...] = (),
    paper_rejection_log_ids: tuple[str, ...] = (),
    paper_tca_row_ids: tuple[str, ...] = (),
    paper_tca_issue_ids: tuple[str, ...] = (),
) -> DecisionTraceEnvelope:
    draft = DecisionTraceEnvelope.model_construct(
        trace_envelope_id="AUDITTRACE:PLACEHOLDER",
        trace_envelope_hash="0" * 64,
        trace_id=decision.trace_id,
        forecast=forecast_ref,
        strategy_decision_id=decision.decision_id,
        strategy_decision_hash=decision.decision_hash,
        strategy_run_id=decision.strategy_run_id,
        policy_id=decision.policy_id,
        policy_hash=decision.policy_hash,
        no_order_reason=no_order_reason,
        order_intent_id=order_intent.client_order_id if order_intent is not None else None,
        order_intent_hash=(
            build_order_intent_hash(order_intent=order_intent)
            if order_intent is not None
            else None
        ),
        risk_run_id=risk_event.request.run_id if risk_event is not None else None,
        risk_request_id=risk_event.request.request_id if risk_event is not None else None,
        risk_request_hash=risk_event.request.request_hash if risk_event is not None else None,
        risk_check_id=risk_event.risk_check_id if risk_event is not None else None,
        risk_check_hash=risk_event.risk_check_hash if risk_event is not None else None,
        risk_decision=risk_event.final_decision if risk_event is not None else None,
        gateway_run_id=gateway_report.run_id if gateway_report is not None else None,
        gateway_report_id=(
            gateway_report.gateway_report_id if gateway_report is not None else None
        ),
        gateway_report_hash=(
            gateway_report.gateway_report_hash if gateway_report is not None else None
        ),
        gateway_event_id=(gateway_event.gateway_event_id if gateway_event is not None else None),
        gateway_event_hash=(
            gateway_event.gateway_event_hash if gateway_event is not None else None
        ),
        gateway_order_id=(gateway_event.gateway_order_id if gateway_event is not None else None),
        paper_run_id=(paper_account_report.run_id if paper_account_report is not None else None),
        paper_session_report_id=(
            paper_account_report.session_report_id if paper_account_report is not None else None
        ),
        paper_session_report_hash=(
            paper_account_report.session_report_hash if paper_account_report is not None else None
        ),
        paper_order_log_ids=paper_order_log_ids,
        paper_fill_log_ids=paper_fill_log_ids,
        paper_rejection_log_ids=paper_rejection_log_ids,
        paper_tca_report_id=(
            paper_tca_report.tca_report_id if paper_tca_report is not None else None
        ),
        paper_tca_report_hash=(
            paper_tca_report.tca_report_hash if paper_tca_report is not None else None
        ),
        paper_tca_row_ids=paper_tca_row_ids,
        paper_tca_issue_ids=paper_tca_issue_ids,
        requirement_ids=_AUDIT_REQUIREMENTS,
    )
    envelope_hash = build_decision_trace_envelope_hash(envelope=draft)
    return DecisionTraceEnvelope(
        **draft.model_dump(exclude={"trace_envelope_id", "trace_envelope_hash"}),
        trace_envelope_id=build_decision_trace_envelope_id(
            trace_envelope_hash=envelope_hash
        ),
        trace_envelope_hash=envelope_hash,
    )


def _forecast_reference_from_forecast(forecast: Forecast) -> ForecastTraceReference:
    return ForecastTraceReference(
        forecast_id=forecast.forecast_id,
        dataset_snapshot_id=forecast.dataset_snapshot_id,
        dataset_hash=forecast.dataset_hash,
        dataset_row_id=forecast.dataset_row_id,
        feature_vector_id=forecast.feature_vector_id,
        feature_input_snapshot_id=forecast.feature_input_snapshot_id,
        feature_version=forecast.feature_version,
        source_feature_snapshot_ids=forecast.source_feature_snapshot_ids,
        training_run_id=forecast.training_run_id,
        training_run_hash=forecast.training_run_hash,
        model_version_id=forecast.model_version_id,
        model_version_hash=forecast.model_version_hash,
    )


def _validate_forecast_decision_lineage(*, forecast: Forecast, decision: StrategyDecision) -> None:
    checks = (
        (forecast.forecast_id, decision.source_forecast_id, "forecast_id"),
        (forecast.dataset_snapshot_id, decision.dataset_snapshot_id, "dataset_snapshot_id"),
        (forecast.dataset_row_id, decision.dataset_row_id, "dataset_row_id"),
        (forecast.feature_vector_id, decision.feature_vector_id, "feature_vector_id"),
        (
            forecast.feature_input_snapshot_id,
            decision.feature_input_snapshot_id,
            "feature_input_snapshot_id",
        ),
        (forecast.feature_version, decision.feature_version, "feature_version"),
        (
            forecast.source_feature_snapshot_ids,
            decision.source_feature_snapshot_ids,
            "source_feature_snapshot_ids",
        ),
        (forecast.instrument_id, decision.instrument_id, "instrument_id"),
        (forecast.venue_id, decision.venue_id, "venue_id"),
        (forecast.feature_ts, decision.feature_ts, "feature_ts"),
        (forecast.label_rule_id, decision.label_rule_id, "label_rule_id"),
        (forecast.split, decision.split, "split"),
        (forecast.training_run_id, decision.training_run_id, "training_run_id"),
        (forecast.model_version_id, decision.model_version_id, "model_version_id"),
        (forecast.model_version_hash, decision.model_version_hash, "model_version_hash"),
    )
    for forecast_value, decision_value, label in checks:
        if forecast_value != decision_value:
            raise ValueError(f"forecast {label} must match strategy decision lineage")


def _validate_order_intent_matches_decision(
    *, order_intent: OrderIntent, decision: StrategyDecision
) -> None:
    if order_intent.trace_id != decision.trace_id:
        raise ValueError("order intent trace_id must match strategy decision trace_id")
    if order_intent.source_decision_id != decision.decision_id:
        raise ValueError("order intent source_decision_id must match strategy decision_id")
    if order_intent.instrument_id != decision.instrument_id:
        raise ValueError("order intent instrument_id must match strategy decision")
    if order_intent.venue_id != decision.venue_id:
        raise ValueError("order intent venue_id must match strategy decision")
    if order_intent.side is not OrderSide.BUY:
        raise ValueError("MVP strategy order intents must be BUY only")
    if order_intent.quantity != decision.sizing.proposed_quantity:
        raise ValueError("order intent quantity must match proposed pre-risk quantity")
    if order_intent.submitted_at < decision.decision_ts:
        raise ValueError("order intent submitted_at must not precede decision_ts")
    expected_id = build_order_intent_client_order_id(
        decision=decision,
        submitted_at=order_intent.submitted_at,
        order_type=order_intent.order_type,
        limit_price=order_intent.limit_price,
    )
    if order_intent.client_order_id != expected_id:
        raise ValueError("order intent client_order_id is not deterministic")


def _validate_risk_event_matches_order(
    *, risk_event: RiskCheckEvent, order_intent: OrderIntent, decision: StrategyDecision
) -> None:
    if risk_event.request.trace_id != decision.trace_id:
        raise ValueError("risk event trace_id must match strategy decision trace_id")
    if risk_event.request.source_decision_id != decision.decision_id:
        raise ValueError("risk event source_decision_id must match strategy decision_id")
    if risk_event.request.order_intent != order_intent:
        raise ValueError("risk event request must embed the audited order intent")
    if risk_event.approved_order_intent is not None:
        if risk_event.approved_order_intent.trace_id != decision.trace_id:
            raise ValueError("approved risk intent trace_id must match strategy decision")
        if risk_event.approved_order_intent.source_decision_id != decision.decision_id:
            raise ValueError("approved risk intent source_decision_id must match decision")


def _matching_gateway_event(
    *,
    gateway_report: ExecutionGatewayReport,
    risk_event: RiskCheckEvent,
    decision: StrategyDecision,
) -> ExecutionGatewayLifecycleEvent:
    matches = tuple(
        event
        for event in gateway_report.events
        if event.risk_check_id == risk_event.risk_check_id
        and event.risk_check_hash == risk_event.risk_check_hash
        and event.trace_id == decision.trace_id
        and event.source_decision_id == decision.decision_id
    )
    if len(matches) != 1:
        raise ValueError("gateway report must contain exactly one matching trace event")
    return matches[0]


def _paper_account_ids_for_event(
    *,
    paper_account_report: PaperAccountSessionReport,
    gateway_report: ExecutionGatewayReport,
    gateway_event: ExecutionGatewayLifecycleEvent,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if paper_account_report.gateway_report_id != gateway_report.gateway_report_id:
        raise ValueError("paper account report gateway_report_id must match gateway report")
    if paper_account_report.gateway_report_hash != gateway_report.gateway_report_hash:
        raise ValueError("paper account report gateway_report_hash must match gateway report")
    order_logs = tuple(
        entry
        for entry in paper_account_report.order_logs
        if entry.gateway_event_id == gateway_event.gateway_event_id
        and entry.gateway_event_hash == gateway_event.gateway_event_hash
        and entry.trace_id == gateway_event.trace_id
        and entry.source_decision_id == gateway_event.source_decision_id
    )
    if len(order_logs) != 1:
        raise ValueError("paper account report must contain one matching order log")
    fill_logs = tuple(
        entry
        for entry in paper_account_report.fill_logs
        if entry.gateway_event_id == gateway_event.gateway_event_id
        and entry.gateway_event_hash == gateway_event.gateway_event_hash
        and entry.trace_id == gateway_event.trace_id
        and entry.source_decision_id == gateway_event.source_decision_id
    )
    rejection_logs = tuple(
        entry
        for entry in paper_account_report.rejection_logs
        if entry.gateway_event_id == gateway_event.gateway_event_id
        and entry.gateway_event_hash == gateway_event.gateway_event_hash
        and entry.trace_id == gateway_event.trace_id
        and entry.source_decision_id == gateway_event.source_decision_id
    )
    if gateway_event.status in _FILLED_GATEWAY_STATUSES:
        if not fill_logs:
            raise ValueError("filled paper trace requires a matching fill log")
    elif not rejection_logs:
        raise ValueError("blocked/rejected paper trace requires a matching rejection log")
    return (
        tuple(entry.order_log_id for entry in order_logs),
        tuple(entry.fill_log_id for entry in fill_logs),
        tuple(entry.rejection_log_id for entry in rejection_logs),
    )


def _paper_tca_ids_for_event(
    *,
    paper_tca_report: PaperTcaReport,
    gateway_report: ExecutionGatewayReport,
    gateway_event: ExecutionGatewayLifecycleEvent,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if paper_tca_report.gateway_report_id != gateway_report.gateway_report_id:
        raise ValueError("paper TCA report gateway_report_id must match gateway report")
    if paper_tca_report.gateway_report_hash != gateway_report.gateway_report_hash:
        raise ValueError("paper TCA report gateway_report_hash must match gateway report")
    rows = tuple(
        row
        for row in paper_tca_report.rows
        if row.gateway_event_id == gateway_event.gateway_event_id
        and row.gateway_event_hash == gateway_event.gateway_event_hash
        and row.trace_id == gateway_event.trace_id
        and row.source_decision_id == gateway_event.source_decision_id
    )
    issues = tuple(
        issue
        for issue in paper_tca_report.issues
        if issue.gateway_event_id == gateway_event.gateway_event_id
        and issue.gateway_event_hash == gateway_event.gateway_event_hash
        and issue.trace_id == gateway_event.trace_id
    )
    if gateway_event.status in _FILLED_GATEWAY_STATUSES:
        if not rows:
            raise ValueError("filled paper trace requires a matching TCA row")
    elif not issues:
        raise ValueError("blocked/rejected paper trace requires a matching TCA issue")
    return tuple(row.tca_row_id for row in rows), tuple(issue.issue_id for issue in issues)


def _no_order_reason(decision: StrategyDecision) -> str | None:
    if decision.action is StrategyDecisionAction.NO_TRADE:
        return f"strategy_no_trade:{decision.reason_code.value}"
    if decision.sizing.proposed_notional == 0 or decision.sizing.proposed_quantity == 0:
        return f"zero_pre_risk_size:{decision.sizing.sizing_status.value}"
    return None


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_payload(model: ContractModel, *, exclude: set[str]) -> object:
    return json.loads(model.model_dump_json(exclude=exclude))


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
