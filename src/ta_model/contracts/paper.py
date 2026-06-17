"""Paper accounting and TCA report contracts for S10 paper readiness.

Traceability:
- FR-013: paper account/session artifacts log orders, fills, rejections, TCA, and
  account-state linkage from paper gateway evidence.
- FR-014: TCA rows expose predicted and realized execution costs separately from the
  gateway lifecycle report.
- FR-015: trace/risk/client-order linkages preserve sampled decision reconstruction.
- NFR-004: orders and fills remain tied to independent risk approval/block evidence.

Scope:
- Structured deterministic artifacts only; no live capital, broker/network calls,
  persistence service, leverage, derivatives, margin, shorting, market making, HFT,
  dashboards, alerts, or autonomous model promotion path is introduced.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.execution import (
    ExecutionFillMode,
    ExecutionGatewayKind,
    ExecutionGatewayOrderStatus,
)
from ta_model.contracts.instrument_master import (
    CanonicalId,
    ContractModel,
    NonEmptyString,
    NonNegativeDecimal,
    OrderType,
    PositiveDecimal,
)
from ta_model.contracts.risk import RiskDecisionStatus, RiskReasonCode
from ta_model.contracts.simulation import (
    OrderSide,
    ReplayFillStatus,
    ReplayRejectReason,
    SimulatedAccountState,
)


class PaperRejectionSource(StrEnum):
    """Source family for an explicit paper rejection/blocked log row."""

    RISK = "risk"
    GATEWAY_REPLAY = "gateway_replay"


class PaperAccountStateSource(StrEnum):
    """How final paper account state evidence was obtained for the session report."""

    GATEWAY_REPLAY = "gateway_replay"
    UNCHANGED_FROM_INITIAL = "unchanged_from_initial"
    EXPLICIT_LINKAGE = "explicit_linkage"


class TcaReferencePriceSource(StrEnum):
    """Reference price source used for realized TCA calculations."""

    ARRIVAL_QUOTE_MID = "arrival_quote_mid"
    REPLAY_ARRIVAL_REFERENCE = "replay_arrival_reference"


class PaperTcaIssueSeverity(StrEnum):
    """Severity levels for TCA issue/error rows."""

    ERROR = "error"


class PaperTcaIssueCode(StrEnum):
    """Machine-readable TCA report issue/error codes."""

    MISSING_ARRIVAL_QUOTE = "missing_arrival_quote"
    RISK_BLOCKED = "risk_blocked"
    GATEWAY_REJECTED = "gateway_rejected"
    GATEWAY_UNFILLED = "gateway_unfilled"


_FILLED_STATUSES = {
    ExecutionGatewayOrderStatus.FILLED,
    ExecutionGatewayOrderStatus.PARTIALLY_FILLED,
}
_REJECTION_STATUSES = {
    ExecutionGatewayOrderStatus.BLOCKED,
    ExecutionGatewayOrderStatus.REJECTED,
    ExecutionGatewayOrderStatus.UNFILLED,
}


class PaperOrderLifecycleLogEntry(ContractModel):
    """Auditable order lifecycle row derived from one gateway lifecycle event."""

    order_log_id: CanonicalId
    order_log_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_report_id: CanonicalId
    gateway_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_event_id: CanonicalId
    gateway_event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_order_id: CanonicalId | None = None
    run_id: CanonicalId
    risk_check_id: CanonicalId
    risk_check_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    risk_decision: RiskDecisionStatus
    risk_reason_codes: tuple[RiskReasonCode, ...]
    client_order_id: CanonicalId
    trace_id: CanonicalId
    source_decision_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    side: OrderSide
    order_type: OrderType
    requested_quantity: PositiveDecimal
    gateway_quantity: PositiveDecimal
    submitted_at: AwareDatetime
    status: ExecutionGatewayOrderStatus
    replay_status: ReplayFillStatus | None = None
    replay_reject_reason: ReplayRejectReason | None = None
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-013", "FR-015", "NFR-004")

    @model_validator(mode="after")
    def lifecycle_log_identity_is_deterministic(self) -> Self:
        if self.status is ExecutionGatewayOrderStatus.BLOCKED:
            if self.gateway_order_id is not None or self.replay_status is not None:
                raise ValueError("blocked lifecycle logs must not carry placement evidence")
        elif self.gateway_order_id is None or self.replay_status is None:
            raise ValueError("non-blocked lifecycle logs require gateway/replay evidence")
        expected_hash = build_paper_order_lifecycle_log_hash(entry=self)
        if self.order_log_hash != expected_hash:
            raise ValueError("order_log_hash is not deterministic")
        if self.order_log_id != build_paper_order_lifecycle_log_id(entry_hash=expected_hash):
            raise ValueError("order_log_id is not deterministic")
        return self


class PaperFillLogEntry(ContractModel):
    """Paper fill row with replay/gateway cost attribution and trace linkage."""

    fill_log_id: CanonicalId
    fill_log_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_report_id: CanonicalId
    gateway_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_event_id: CanonicalId
    gateway_event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_order_id: CanonicalId
    run_id: CanonicalId
    risk_check_id: CanonicalId
    risk_check_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    client_order_id: CanonicalId
    trace_id: CanonicalId
    source_decision_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    side: OrderSide
    order_type: OrderType
    status: ExecutionGatewayOrderStatus
    replay_order_result_id: CanonicalId
    fill_price: PositiveDecimal
    filled_quantity: PositiveDecimal
    remaining_quantity: NonNegativeDecimal = Decimal("0")
    fill_event_open_ts: AwareDatetime
    fill_event_close_ts: AwareDatetime
    fill_event_source_ts: AwareDatetime
    fill_raw_payload_id: CanonicalId
    cost_model_id: CanonicalId | None = None
    cost_model_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    latency_bars: int = Field(ge=0)
    eligible_event_index: int | None = Field(default=None, ge=0)
    fill_attempt_event_index: int | None = Field(default=None, ge=0)
    arrival_reference_price: PositiveDecimal
    effective_fill_price: PositiveDecimal
    reference_notional: NonNegativeDecimal
    effective_notional: NonNegativeDecimal
    fee_cost: NonNegativeDecimal = Decimal("0")
    spread_cost: NonNegativeDecimal = Decimal("0")
    slippage_cost: NonNegativeDecimal = Decimal("0")
    total_cost: NonNegativeDecimal = Decimal("0")
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-013", "FR-014", "FR-015")

    @model_validator(mode="after")
    def fill_log_identity_is_deterministic(self) -> Self:
        if self.status not in _FILLED_STATUSES:
            raise ValueError("fill logs require filled or partially_filled gateway status")
        if (self.cost_model_id is None) != (self.cost_model_hash is None):
            raise ValueError("cost_model_id and cost_model_hash must be set together")
        if self.effective_fill_price != self.fill_price:
            raise ValueError("effective_fill_price must match fill_price")
        if self.reference_notional != self.arrival_reference_price * self.filled_quantity:
            raise ValueError("reference_notional must match arrival price times fill quantity")
        if self.effective_notional != self.effective_fill_price * self.filled_quantity:
            raise ValueError("effective_notional must match effective price times fill quantity")
        if self.total_cost != self.fee_cost + self.spread_cost + self.slippage_cost:
            raise ValueError("total_cost must equal fee_cost plus spread_cost plus slippage_cost")
        expected_hash = build_paper_fill_log_hash(entry=self)
        if self.fill_log_hash != expected_hash:
            raise ValueError("fill_log_hash is not deterministic")
        if self.fill_log_id != build_paper_fill_log_id(entry_hash=expected_hash):
            raise ValueError("fill_log_id is not deterministic")
        return self


class PaperRejectionLogEntry(ContractModel):
    """Explicit blocked/rejected/unfilled paper order row."""

    rejection_log_id: CanonicalId
    rejection_log_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_report_id: CanonicalId
    gateway_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_event_id: CanonicalId
    gateway_event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_order_id: CanonicalId | None = None
    run_id: CanonicalId
    risk_check_id: CanonicalId
    risk_check_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    risk_decision: RiskDecisionStatus
    risk_reason_codes: tuple[RiskReasonCode, ...]
    replay_reject_reason: ReplayRejectReason | None = None
    rejection_source: PaperRejectionSource
    client_order_id: CanonicalId
    trace_id: CanonicalId
    source_decision_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    side: OrderSide
    order_type: OrderType
    requested_quantity: PositiveDecimal
    gateway_quantity: PositiveDecimal
    remaining_quantity: NonNegativeDecimal
    submitted_at: AwareDatetime
    status: ExecutionGatewayOrderStatus
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-010", "FR-013", "FR-015")

    @model_validator(mode="after")
    def rejection_log_identity_is_deterministic(self) -> Self:
        if self.status not in _REJECTION_STATUSES:
            raise ValueError("rejection logs require blocked, rejected, or unfilled status")
        if self.rejection_source is PaperRejectionSource.RISK:
            if self.status is not ExecutionGatewayOrderStatus.BLOCKED:
                raise ValueError("risk-sourced rejection logs must be blocked gateway events")
            if self.replay_reject_reason is not None:
                raise ValueError("risk-sourced rejection logs require risk/no-trade reasons only")
        else:
            if self.status is ExecutionGatewayOrderStatus.BLOCKED:
                raise ValueError("gateway replay rejection logs cannot be risk-blocked events")
            if self.replay_reject_reason is None:
                raise ValueError("gateway replay rejection logs require replay_reject_reason")
        expected_hash = build_paper_rejection_log_hash(entry=self)
        if self.rejection_log_hash != expected_hash:
            raise ValueError("rejection_log_hash is not deterministic")
        if self.rejection_log_id != build_paper_rejection_log_id(entry_hash=expected_hash):
            raise ValueError("rejection_log_id is not deterministic")
        return self


class PaperAccountSessionReport(ContractModel):
    """Deterministic paper account/session report built from gateway evidence."""

    session_report_id: CanonicalId
    session_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: CanonicalId
    gateway_report_id: CanonicalId
    gateway_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_kind: ExecutionGatewayKind
    fill_mode: ExecutionFillMode
    source_risk_gated_replay_result_id: CanonicalId
    source_risk_gated_replay_result_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_replay_report_id: CanonicalId | None = None
    source_replay_report_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    initial_account_state_id: CanonicalId
    initial_account_state_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    final_account_state_id: CanonicalId
    final_account_state_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    final_account_state_source: PaperAccountStateSource
    initial_account_state: SimulatedAccountState | None = None
    final_account_state: SimulatedAccountState | None = None
    order_log_ids: tuple[CanonicalId, ...]
    fill_log_ids: tuple[CanonicalId, ...]
    rejection_log_ids: tuple[CanonicalId, ...]
    order_logs: tuple[PaperOrderLifecycleLogEntry, ...]
    fill_logs: tuple[PaperFillLogEntry, ...] = ()
    rejection_logs: tuple[PaperRejectionLogEntry, ...] = ()
    total_order_count: int = Field(ge=0)
    filled_order_count: int = Field(ge=0)
    partially_filled_order_count: int = Field(ge=0)
    blocked_order_count: int = Field(ge=0)
    rejected_order_count: int = Field(ge=0)
    unfilled_order_count: int = Field(ge=0)
    filled_quantity_total: NonNegativeDecimal = Decimal("0")
    fee_cost_total: NonNegativeDecimal = Decimal("0")
    spread_cost_total: NonNegativeDecimal = Decimal("0")
    slippage_cost_total: NonNegativeDecimal = Decimal("0")
    total_execution_cost: NonNegativeDecimal = Decimal("0")
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-010", "FR-013", "FR-015", "NFR-004")

    @model_validator(mode="after")
    def session_report_identity_is_deterministic(self) -> Self:
        if self.gateway_kind is not ExecutionGatewayKind.PAPER:
            raise ValueError("paper account session reports require paper gateway kind")
        if self.fill_mode is not ExecutionFillMode.PAPER_SIMULATED_FILL:
            raise ValueError("paper account session reports require paper_simulated_fill mode")
        if (self.source_replay_report_id is None) != (self.source_replay_report_hash is None):
            raise ValueError("source replay report id/hash must be set together")
        self._validate_account_state_linkage()
        self._validate_logs_and_totals()
        expected_hash = build_paper_account_session_report_hash(report=self)
        if self.session_report_hash != expected_hash:
            raise ValueError("session_report_hash is not deterministic")
        if self.session_report_id != build_paper_account_session_report_id(
            report_hash=expected_hash
        ):
            raise ValueError("session_report_id is not deterministic")
        return self

    def _validate_account_state_linkage(self) -> None:
        if self.initial_account_state is not None:
            expected_hash = build_paper_account_state_hash(
                account_state=self.initial_account_state
            )
            if self.initial_account_state_hash != expected_hash:
                raise ValueError("initial_account_state_hash does not match embedded state")
            if self.initial_account_state_id != build_paper_account_state_id(
                account_state_hash=expected_hash
            ):
                raise ValueError("initial_account_state_id does not match embedded state")
        if self.final_account_state is not None:
            expected_hash = build_paper_account_state_hash(account_state=self.final_account_state)
            if self.final_account_state_hash != expected_hash:
                raise ValueError("final_account_state_hash does not match embedded state")
            if self.final_account_state_id != build_paper_account_state_id(
                account_state_hash=expected_hash
            ):
                raise ValueError("final_account_state_id does not match embedded state")
        if self.initial_account_state is not None and self.final_account_state is not None:
            if self.initial_account_state.account_id != self.final_account_state.account_id:
                raise ValueError("initial/final account states must refer to the same account")
        if self.final_account_state_source is PaperAccountStateSource.GATEWAY_REPLAY:
            if self.final_account_state is None:
                raise ValueError("gateway-replay final account state requires embedded state")
        elif self.final_account_state_source is PaperAccountStateSource.UNCHANGED_FROM_INITIAL:
            if self.initial_account_state is None or self.final_account_state is None:
                raise ValueError("unchanged final account state requires embedded states")
            if self.initial_account_state_hash != self.final_account_state_hash:
                raise ValueError("unchanged final account state must match initial state hash")
            if self.initial_account_state_id != self.final_account_state_id:
                raise ValueError("unchanged final account state must match initial state id")

    def _validate_logs_and_totals(self) -> None:
        if self.order_log_ids != tuple(entry.order_log_id for entry in self.order_logs):
            raise ValueError("order_log_ids must match order_logs")
        if self.fill_log_ids != tuple(entry.fill_log_id for entry in self.fill_logs):
            raise ValueError("fill_log_ids must match fill_logs")
        if self.rejection_log_ids != tuple(entry.rejection_log_id for entry in self.rejection_logs):
            raise ValueError("rejection_log_ids must match rejection_logs")
        self._validate_report_linkage(self.order_logs, self.fill_logs, self.rejection_logs)
        if self.total_order_count != len(self.order_logs):
            raise ValueError("total_order_count must match order_logs")
        if self.filled_order_count != _count_status(
            self.order_logs, ExecutionGatewayOrderStatus.FILLED
        ):
            raise ValueError("filled_order_count must match order_logs")
        if self.partially_filled_order_count != _count_status(
            self.order_logs, ExecutionGatewayOrderStatus.PARTIALLY_FILLED
        ):
            raise ValueError("partially_filled_order_count must match order_logs")
        if self.blocked_order_count != _count_status(
            self.order_logs, ExecutionGatewayOrderStatus.BLOCKED
        ):
            raise ValueError("blocked_order_count must match order_logs")
        if self.rejected_order_count != _count_status(
            self.order_logs, ExecutionGatewayOrderStatus.REJECTED
        ):
            raise ValueError("rejected_order_count must match order_logs")
        if self.unfilled_order_count != _count_status(
            self.order_logs, ExecutionGatewayOrderStatus.UNFILLED
        ):
            raise ValueError("unfilled_order_count must match order_logs")
        if self.filled_quantity_total != sum(
            (entry.filled_quantity for entry in self.fill_logs), Decimal("0")
        ):
            raise ValueError("filled_quantity_total must match fill logs")
        if self.fee_cost_total != sum((entry.fee_cost for entry in self.fill_logs), Decimal("0")):
            raise ValueError("fee_cost_total must match fill logs")
        if self.spread_cost_total != sum(
            (entry.spread_cost for entry in self.fill_logs), Decimal("0")
        ):
            raise ValueError("spread_cost_total must match fill logs")
        if self.slippage_cost_total != sum(
            (entry.slippage_cost for entry in self.fill_logs), Decimal("0")
        ):
            raise ValueError("slippage_cost_total must match fill logs")
        if self.total_execution_cost != sum(
            (entry.total_cost for entry in self.fill_logs), Decimal("0")
        ):
            raise ValueError("total_execution_cost must match fill logs")

    def _validate_report_linkage(
        self,
        order_logs: tuple[PaperOrderLifecycleLogEntry, ...],
        fill_logs: tuple[PaperFillLogEntry, ...],
        rejection_logs: tuple[PaperRejectionLogEntry, ...],
    ) -> None:
        for order_entry in order_logs:
            self._validate_one_log_linkage(
                run_id=order_entry.run_id,
                gateway_report_id=order_entry.gateway_report_id,
                gateway_report_hash=order_entry.gateway_report_hash,
            )
        for fill_entry in fill_logs:
            self._validate_one_log_linkage(
                run_id=fill_entry.run_id,
                gateway_report_id=fill_entry.gateway_report_id,
                gateway_report_hash=fill_entry.gateway_report_hash,
            )
        for rejection_entry in rejection_logs:
            self._validate_one_log_linkage(
                run_id=rejection_entry.run_id,
                gateway_report_id=rejection_entry.gateway_report_id,
                gateway_report_hash=rejection_entry.gateway_report_hash,
            )

    def _validate_one_log_linkage(
        self, *, run_id: str, gateway_report_id: str, gateway_report_hash: str
    ) -> None:
        if run_id != self.run_id:
            raise ValueError("log run_id must match session report")
        if gateway_report_id != self.gateway_report_id:
            raise ValueError("log gateway_report_id must match session report")
        if gateway_report_hash != self.gateway_report_hash:
            raise ValueError("log gateway_report_hash must match session report")


class PaperTcaRow(ContractModel):
    """Filled paper execution TCA row with quote and prediction-error evidence."""

    tca_row_id: CanonicalId
    tca_row_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_report_id: CanonicalId
    gateway_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_event_id: CanonicalId
    gateway_event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_order_id: CanonicalId
    run_id: CanonicalId
    risk_check_id: CanonicalId
    risk_check_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    client_order_id: CanonicalId
    trace_id: CanonicalId
    source_decision_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    side: OrderSide
    status: ExecutionGatewayOrderStatus
    submitted_at: AwareDatetime
    quote_id: NonEmptyString | None = None
    quote_event_ts: AwareDatetime | None = None
    quote_source_ts: AwareDatetime | None = None
    quote_ingest_ts: AwareDatetime | None = None
    arrival_bid: NonNegativeDecimal | None = None
    arrival_ask: NonNegativeDecimal | None = None
    arrival_mid: NonNegativeDecimal | None = None
    fallback_reference_price: PositiveDecimal
    reference_price_source: TcaReferencePriceSource
    fill_price: PositiveDecimal
    filled_quantity: PositiveDecimal
    fill_event_open_ts: AwareDatetime
    fill_event_close_ts: AwareDatetime
    fill_event_source_ts: AwareDatetime
    fee_cost: NonNegativeDecimal = Decimal("0")
    predicted_spread_cost: NonNegativeDecimal = Decimal("0")
    predicted_slippage_cost: NonNegativeDecimal = Decimal("0")
    predicted_spread_slippage_cost: NonNegativeDecimal = Decimal("0")
    predicted_total_cost: NonNegativeDecimal = Decimal("0")
    realized_spread_slippage_cost: Decimal = Decimal("0")
    realized_total_cost: Decimal = Decimal("0")
    spread_slippage_prediction_error: Decimal = Decimal("0")
    total_cost_prediction_error: Decimal = Decimal("0")
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-013", "FR-014", "US-011")

    @model_validator(mode="after")
    def tca_row_identity_is_deterministic(self) -> Self:
        if self.status not in _FILLED_STATUSES:
            raise ValueError("TCA rows require filled or partially_filled gateway status")
        quote_values = (
            self.quote_id,
            self.quote_event_ts,
            self.quote_ingest_ts,
            self.arrival_bid,
            self.arrival_ask,
            self.arrival_mid,
        )
        if self.reference_price_source is TcaReferencePriceSource.ARRIVAL_QUOTE_MID:
            if any(value is None for value in quote_values):
                raise ValueError("arrival quote reference rows require complete quote fields")
        elif self.quote_source_ts is not None or any(value is not None for value in quote_values):
            raise ValueError("fallback reference rows must not carry arrival quote fields")
        if self.predicted_spread_slippage_cost != (
            self.predicted_spread_cost + self.predicted_slippage_cost
        ):
            raise ValueError("predicted_spread_slippage_cost must match predicted components")
        if self.predicted_total_cost != self.fee_cost + self.predicted_spread_slippage_cost:
            raise ValueError("predicted_total_cost must equal fees plus predicted spread/slippage")
        if self.realized_total_cost != self.fee_cost + self.realized_spread_slippage_cost:
            raise ValueError("realized_total_cost must equal fees plus realized spread/slippage")
        if self.spread_slippage_prediction_error != (
            self.realized_spread_slippage_cost - self.predicted_spread_slippage_cost
        ):
            raise ValueError("spread_slippage_prediction_error must match realized-predicted")
        if self.total_cost_prediction_error != (
            self.realized_total_cost - self.predicted_total_cost
        ):
            raise ValueError("total_cost_prediction_error must match realized-predicted")
        expected_hash = build_paper_tca_row_hash(row=self)
        if self.tca_row_hash != expected_hash:
            raise ValueError("tca_row_hash is not deterministic")
        if self.tca_row_id != build_paper_tca_row_id(row_hash=expected_hash):
            raise ValueError("tca_row_id is not deterministic")
        return self


class PaperTcaIssue(ContractModel):
    """Explicit TCA issue/error row for missing quote, blocked, rejected, or unfilled events."""

    issue_id: CanonicalId
    issue_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    severity: PaperTcaIssueSeverity
    code: PaperTcaIssueCode
    message: NonEmptyString
    gateway_report_id: CanonicalId
    gateway_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_event_id: CanonicalId
    gateway_event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: CanonicalId
    risk_check_id: CanonicalId
    client_order_id: CanonicalId
    trace_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    status: ExecutionGatewayOrderStatus
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-013", "FR-014", "US-011")

    @model_validator(mode="after")
    def issue_identity_is_deterministic(self) -> Self:
        if self.code is PaperTcaIssueCode.MISSING_ARRIVAL_QUOTE:
            if self.status not in _FILLED_STATUSES:
                raise ValueError("missing quote TCA issues require a filled gateway event")
        elif self.code is PaperTcaIssueCode.RISK_BLOCKED:
            if self.status is not ExecutionGatewayOrderStatus.BLOCKED:
                raise ValueError("risk-blocked TCA issues require blocked gateway status")
        elif self.code is PaperTcaIssueCode.GATEWAY_REJECTED:
            if self.status is not ExecutionGatewayOrderStatus.REJECTED:
                raise ValueError("gateway-rejected TCA issues require rejected gateway status")
        elif self.status is not ExecutionGatewayOrderStatus.UNFILLED:
            raise ValueError("gateway-unfilled TCA issues require unfilled gateway status")
        expected_hash = build_paper_tca_issue_hash(issue=self)
        if self.issue_hash != expected_hash:
            raise ValueError("issue_hash is not deterministic")
        if self.issue_id != build_paper_tca_issue_id(issue_hash=expected_hash):
            raise ValueError("issue_id is not deterministic")
        return self


class PaperTcaReport(ContractModel):
    """Deterministic TCA artifact for paper gateway fills and explicit error rows."""

    tca_report_id: CanonicalId
    tca_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: CanonicalId
    gateway_report_id: CanonicalId
    gateway_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_kind: ExecutionGatewayKind
    fill_mode: ExecutionFillMode
    row_ids: tuple[CanonicalId, ...]
    issue_ids: tuple[CanonicalId, ...]
    rows: tuple[PaperTcaRow, ...] = ()
    issues: tuple[PaperTcaIssue, ...] = ()
    filled_row_count: int = Field(ge=0)
    issue_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    fee_cost_total: NonNegativeDecimal = Decimal("0")
    predicted_total_cost: NonNegativeDecimal = Decimal("0")
    realized_total_cost: Decimal = Decimal("0")
    total_cost_prediction_error: Decimal = Decimal("0")
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-013", "FR-014", "US-011")

    @model_validator(mode="after")
    def tca_report_identity_is_deterministic(self) -> Self:
        if self.gateway_kind is not ExecutionGatewayKind.PAPER:
            raise ValueError("paper TCA reports require paper gateway kind")
        if self.fill_mode is not ExecutionFillMode.PAPER_SIMULATED_FILL:
            raise ValueError("paper TCA reports require paper_simulated_fill mode")
        if self.row_ids != tuple(row.tca_row_id for row in self.rows):
            raise ValueError("row_ids must match rows")
        if self.issue_ids != tuple(issue.issue_id for issue in self.issues):
            raise ValueError("issue_ids must match issues")
        for row in self.rows:
            if row.run_id != self.run_id:
                raise ValueError("TCA row run_id must match report")
            if row.gateway_report_id != self.gateway_report_id:
                raise ValueError("TCA row gateway_report_id must match report")
            if row.gateway_report_hash != self.gateway_report_hash:
                raise ValueError("TCA row gateway_report_hash must match report")
        for issue in self.issues:
            if issue.run_id != self.run_id:
                raise ValueError("TCA issue run_id must match report")
            if issue.gateway_report_id != self.gateway_report_id:
                raise ValueError("TCA issue gateway_report_id must match report")
            if issue.gateway_report_hash != self.gateway_report_hash:
                raise ValueError("TCA issue gateway_report_hash must match report")
        if self.filled_row_count != len(self.rows):
            raise ValueError("filled_row_count must match rows")
        if self.issue_count != len(self.issues):
            raise ValueError("issue_count must match issues")
        if self.error_count != sum(
            1 for issue in self.issues if issue.severity is PaperTcaIssueSeverity.ERROR
        ):
            raise ValueError("error_count must match error issues")
        if self.fee_cost_total != sum((row.fee_cost for row in self.rows), Decimal("0")):
            raise ValueError("fee_cost_total must match rows")
        if self.predicted_total_cost != sum(
            (row.predicted_total_cost for row in self.rows), Decimal("0")
        ):
            raise ValueError("predicted_total_cost must match rows")
        if self.realized_total_cost != sum(
            (row.realized_total_cost for row in self.rows), Decimal("0")
        ):
            raise ValueError("realized_total_cost must match rows")
        if self.total_cost_prediction_error != sum(
            (row.total_cost_prediction_error for row in self.rows), Decimal("0")
        ):
            raise ValueError("total_cost_prediction_error must match rows")
        expected_hash = build_paper_tca_report_hash(report=self)
        if self.tca_report_hash != expected_hash:
            raise ValueError("tca_report_hash is not deterministic")
        if self.tca_report_id != build_paper_tca_report_id(report_hash=expected_hash):
            raise ValueError("tca_report_id is not deterministic")
        return self


def build_paper_account_state_hash(*, account_state: SimulatedAccountState) -> str:
    return _hash(_model_json(account_state))


def build_paper_account_state_id(*, account_state_hash: str) -> str:
    return _stable_id("PAPERACCOUNTSTATE", {"account_state_hash": account_state_hash})


def build_paper_order_lifecycle_log_hash(*, entry: PaperOrderLifecycleLogEntry) -> str:
    return _hash(_model_payload(entry, exclude={"order_log_id", "order_log_hash"}))


def build_paper_order_lifecycle_log_id(*, entry_hash: str) -> str:
    return _stable_id("PAPERORDERLOG", {"order_log_hash": entry_hash})


def build_paper_fill_log_hash(*, entry: PaperFillLogEntry) -> str:
    return _hash(_model_payload(entry, exclude={"fill_log_id", "fill_log_hash"}))


def build_paper_fill_log_id(*, entry_hash: str) -> str:
    return _stable_id("PAPERFILLLOG", {"fill_log_hash": entry_hash})


def build_paper_rejection_log_hash(*, entry: PaperRejectionLogEntry) -> str:
    return _hash(_model_payload(entry, exclude={"rejection_log_id", "rejection_log_hash"}))


def build_paper_rejection_log_id(*, entry_hash: str) -> str:
    return _stable_id("PAPERREJECTLOG", {"rejection_log_hash": entry_hash})


def build_paper_account_session_report_hash(*, report: PaperAccountSessionReport) -> str:
    return _hash(_model_payload(report, exclude={"session_report_id", "session_report_hash"}))


def build_paper_account_session_report_id(*, report_hash: str) -> str:
    return _stable_id("PAPERSESSION", {"session_report_hash": report_hash})


def build_paper_tca_row_hash(*, row: PaperTcaRow) -> str:
    return _hash(_model_payload(row, exclude={"tca_row_id", "tca_row_hash"}))


def build_paper_tca_row_id(*, row_hash: str) -> str:
    return _stable_id("PAPERTCAROW", {"tca_row_hash": row_hash})


def build_paper_tca_issue_hash(*, issue: PaperTcaIssue) -> str:
    return _hash(_model_payload(issue, exclude={"issue_id", "issue_hash"}))


def build_paper_tca_issue_id(*, issue_hash: str) -> str:
    return _stable_id("PAPERTCAISSUE", {"issue_hash": issue_hash})


def build_paper_tca_report_hash(*, report: PaperTcaReport) -> str:
    return _hash(_model_payload(report, exclude={"tca_report_id", "tca_report_hash"}))


def build_paper_tca_report_id(*, report_hash: str) -> str:
    return _stable_id("PAPERTCAREPORT", {"tca_report_hash": report_hash})


def _count_status(
    entries: tuple[PaperOrderLifecycleLogEntry, ...], status: ExecutionGatewayOrderStatus
) -> int:
    return sum(1 for entry in entries if entry.status is status)


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())


def _model_payload(model: ContractModel, *, exclude: set[str]) -> object:
    return json.loads(model.model_dump_json(exclude=exclude))
