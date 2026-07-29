"""Shared simulator/paper execution gateway lifecycle contracts.

Traceability:
- FR-010: gateway lifecycle evidence is produced only from independent risk events.
- FR-013: paper gateway emits auditable paper-mode order/fill/rejection evidence.
- NFR-004: every gateway event carries traceable decision and risk approval/block data.
- TFR-008: simulator and paper paths share the same lifecycle report/event shape.

Scope:
- S10-001 adds a risk-gated simulator/paper lifecycle contract foundation only.
- Paper fills are simulated via the existing event-time replay path; no live capital,
  network gateway, leverage, derivatives, margin, shorting, market making, or HFT path
  is introduced.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.instrument_master import (
    CanonicalId,
    ContractModel,
    NonEmptyString,
    NonNegativeDecimal,
    OrderType,
    PositiveDecimal,
)
from ta_model.contracts.risk import (
    RiskCheckEvent,
    RiskDecisionStatus,
    RiskGatedReplayResult,
    RiskReasonCode,
)
from ta_model.contracts.simulation import (
    OrderSide,
    ReplayFillStatus,
    ReplayOrderResult,
    ReplayRejectReason,
    SimulatedAccountState,
)


class ExecutionGatewayKind(StrEnum):
    """Gateway families covered by the S10 shared lifecycle contract."""

    SIMULATOR = "simulator"
    PAPER = "paper"


class ExecutionFillMode(StrEnum):
    """Fill source semantics for a gateway lifecycle report."""

    EVENT_TIME_REPLAY = "event_time_replay"
    PAPER_SIMULATED_FILL = "paper_simulated_fill"


class ExecutionGatewayOrderStatus(StrEnum):
    """Terminal lifecycle state for one risk-gated gateway order attempt."""

    BLOCKED = "blocked"
    REJECTED = "rejected"
    UNFILLED = "unfilled"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"


_APPROVED_RISK_DECISIONS = {
    RiskDecisionStatus.APPROVED,
    RiskDecisionStatus.APPROVED_AFTER_CAP,
    RiskDecisionStatus.CANCEL_REDUCE_ONLY_APPROVED,
}

_REPLAY_TO_GATEWAY_STATUS = {
    ReplayFillStatus.FILLED: ExecutionGatewayOrderStatus.FILLED,
    ReplayFillStatus.PARTIALLY_FILLED: ExecutionGatewayOrderStatus.PARTIALLY_FILLED,
    ReplayFillStatus.UNFILLED: ExecutionGatewayOrderStatus.UNFILLED,
    ReplayFillStatus.REJECTED: ExecutionGatewayOrderStatus.REJECTED,
}


class ExecutionGatewayLifecycleEvent(ContractModel):
    """Auditable lifecycle event emitted by simulator and paper gateway paths.

    A blocked event is the only valid output for rejected/no-trade risk checks.  Filled
    and rejected/unfilled gateway events require an approved risk event and the real S6
    replay result that produced the simulated fill/rejection semantics.
    """

    gateway_event_id: CanonicalId
    gateway_event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_order_id: CanonicalId | None = None
    gateway_kind: ExecutionGatewayKind
    fill_mode: ExecutionFillMode
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
    replay_order_result_id: CanonicalId | None = None
    replay_status: ReplayFillStatus | None = None
    replay_reject_reason: ReplayRejectReason | None = None
    fill_price: Decimal | None = Field(default=None, ge=Decimal("0"))
    filled_quantity: NonNegativeDecimal = Decimal("0")
    remaining_quantity: NonNegativeDecimal = Decimal("0")
    fill_event_open_ts: AwareDatetime | None = None
    fill_event_close_ts: AwareDatetime | None = None
    fill_event_source_ts: AwareDatetime | None = None
    fill_raw_payload_id: CanonicalId | None = None
    cost_model_id: CanonicalId | None = None
    cost_model_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    latency_bars: int = Field(default=0, ge=0)
    eligible_event_index: int | None = Field(default=None, ge=0)
    fill_attempt_event_index: int | None = Field(default=None, ge=0)
    arrival_reference_price: Decimal | None = Field(default=None, ge=Decimal("0"))
    effective_fill_price: Decimal | None = Field(default=None, ge=Decimal("0"))
    reference_notional: NonNegativeDecimal = Decimal("0")
    effective_notional: NonNegativeDecimal = Decimal("0")
    fee_cost: NonNegativeDecimal = Decimal("0")
    spread_cost: NonNegativeDecimal = Decimal("0")
    slippage_cost: NonNegativeDecimal = Decimal("0")
    total_cost: NonNegativeDecimal = Decimal("0")
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-010", "NFR-004", "TFR-008")

    @model_validator(mode="after")
    def lifecycle_event_is_consistent_and_deterministic(self) -> Self:
        _validate_gateway_fill_mode(gateway_kind=self.gateway_kind, fill_mode=self.fill_mode)
        if (self.cost_model_id is None) != (self.cost_model_hash is None):
            raise ValueError("cost_model_id and cost_model_hash must be set together")
        if self.total_cost != self.fee_cost + self.spread_cost + self.slippage_cost:
            raise ValueError("total_cost must equal fee_cost plus spread_cost plus slippage_cost")
        if self.total_cost > 0 and (self.cost_model_id is None or self.cost_model_hash is None):
            raise ValueError("positive execution costs require cost model identity")
        if self.remaining_quantity != self.gateway_quantity - self.filled_quantity:
            raise ValueError("remaining_quantity must equal gateway_quantity minus filled_quantity")

        risk_approved = self.risk_decision in _APPROVED_RISK_DECISIONS
        if self.status is ExecutionGatewayOrderStatus.BLOCKED:
            if risk_approved:
                raise ValueError("approved risk decisions cannot emit blocked gateway events")
            self._validate_blocked_event()
        else:
            if not risk_approved:
                raise ValueError("non-blocked gateway events require approved risk evidence")
            self._validate_replay_backed_event()

        expected_hash = build_execution_gateway_event_hash(event=self)
        if self.gateway_event_hash != expected_hash:
            raise ValueError("gateway_event_hash is not deterministic")
        if self.gateway_event_id != build_execution_gateway_event_id(event_hash=expected_hash):
            raise ValueError("gateway_event_id is not deterministic")
        return self

    def _validate_blocked_event(self) -> None:
        if self.gateway_order_id is not None:
            raise ValueError("blocked risk events must not create a gateway_order_id")
        if self.replay_order_result_id is not None or self.replay_status is not None:
            raise ValueError("blocked risk events must not carry replay result evidence")
        if self.replay_reject_reason is not None:
            raise ValueError("blocked risk events use risk reasons, not replay reject reasons")
        if self.filled_quantity != 0 or self.remaining_quantity != self.gateway_quantity:
            raise ValueError("blocked risk events must not carry fills")
        if (
            self.fill_price is not None
            or self.fill_event_open_ts is not None
            or self.fill_event_close_ts is not None
            or self.fill_event_source_ts is not None
            or self.fill_raw_payload_id is not None
            or self.cost_model_id is not None
            or self.cost_model_hash is not None
            or self.latency_bars != 0
            or self.eligible_event_index is not None
            or self.fill_attempt_event_index is not None
            or self.arrival_reference_price is not None
            or self.effective_fill_price is not None
            or self.reference_notional != 0
            or self.effective_notional != 0
            or self.fee_cost != 0
            or self.spread_cost != 0
            or self.slippage_cost != 0
            or self.total_cost != 0
        ):
            raise ValueError("blocked risk events must not carry placement or fill attribution")

    def _validate_replay_backed_event(self) -> None:
        if self.gateway_order_id is None:
            raise ValueError("approved gateway events require a gateway_order_id")
        if self.gateway_order_id != build_execution_gateway_order_id(event=self):
            raise ValueError("gateway_order_id is not deterministic")
        if self.replay_order_result_id is None or self.replay_status is None:
            raise ValueError("approved gateway events require replay result evidence")
        expected_status = _REPLAY_TO_GATEWAY_STATUS[self.replay_status]
        if self.status is not expected_status:
            raise ValueError("gateway status must match replay result status")
        if self.status in {
            ExecutionGatewayOrderStatus.FILLED,
            ExecutionGatewayOrderStatus.PARTIALLY_FILLED,
        }:
            self._validate_filled_event()
        else:
            self._validate_unfilled_or_rejected_event()

    def _validate_filled_event(self) -> None:
        if self.replay_reject_reason is not None:
            raise ValueError("filled gateway event must not set replay_reject_reason")
        if self.fill_price is None or self.fill_price <= 0:
            raise ValueError("filled gateway event requires positive fill_price")
        if self.status is ExecutionGatewayOrderStatus.FILLED:
            if self.filled_quantity != self.gateway_quantity:
                raise ValueError("filled gateway event must fill full gateway quantity")
        elif not (Decimal("0") < self.filled_quantity < self.gateway_quantity):
            raise ValueError("partially filled gateway event requires partial quantity")
        if (
            self.fill_event_open_ts is None
            or self.fill_event_close_ts is None
            or self.fill_event_source_ts is None
            or self.fill_raw_payload_id is None
        ):
            raise ValueError("filled gateway event requires fill event lineage")
        if self.arrival_reference_price is None or self.effective_fill_price is None:
            raise ValueError("filled gateway event requires price attribution")
        if self.effective_fill_price != self.fill_price:
            raise ValueError("effective_fill_price must match fill_price when present")
        if self.reference_notional != self.arrival_reference_price * self.filled_quantity:
            raise ValueError("reference_notional must match arrival price times fill quantity")
        if self.effective_notional != self.effective_fill_price * self.filled_quantity:
            raise ValueError("effective_notional must match effective price times fill quantity")

    def _validate_unfilled_or_rejected_event(self) -> None:
        if self.replay_reject_reason is None:
            raise ValueError("unfilled/rejected gateway event requires replay_reject_reason")
        if self.fill_price is not None or self.filled_quantity != 0:
            raise ValueError("unfilled/rejected gateway event must not carry a fill")
        if (
            self.fill_event_open_ts is not None
            or self.fill_event_close_ts is not None
            or self.fill_event_source_ts is not None
            or self.fill_raw_payload_id is not None
            or self.arrival_reference_price is not None
            or self.effective_fill_price is not None
            or self.reference_notional != 0
            or self.effective_notional != 0
            or self.fee_cost != 0
            or self.spread_cost != 0
            or self.slippage_cost != 0
            or self.total_cost != 0
        ):
            raise ValueError("unfilled/rejected gateway event must not carry fill attribution")
        if self.remaining_quantity != self.gateway_quantity:
            raise ValueError("unfilled/rejected gateway event must leave full quantity remaining")


class ExecutionGatewayReport(ContractModel):
    """Shared simulator/paper lifecycle report produced from risk-gated replay."""

    gateway_report_id: CanonicalId
    gateway_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: CanonicalId
    gateway_kind: ExecutionGatewayKind
    fill_mode: ExecutionFillMode
    risk_check_ids: tuple[CanonicalId, ...]
    approved_risk_check_ids: tuple[CanonicalId, ...]
    blocked_risk_check_ids: tuple[CanonicalId, ...]
    gateway_event_ids: tuple[CanonicalId, ...]
    events: tuple[ExecutionGatewayLifecycleEvent, ...]
    source_risk_gated_replay_result_id: CanonicalId
    source_risk_gated_replay_result_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_replay_report_id: CanonicalId | None = None
    source_replay_report_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_replay_final_account_state_id: CanonicalId | None = None
    source_replay_final_account_state_hash: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )
    source_replay_final_account_state: SimulatedAccountState | None = None
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-010", "NFR-004", "TFR-008")

    @model_validator(mode="after")
    def lifecycle_report_is_consistent_and_deterministic(self) -> Self:
        _validate_gateway_fill_mode(gateway_kind=self.gateway_kind, fill_mode=self.fill_mode)
        if self.gateway_event_ids != tuple(event.gateway_event_id for event in self.events):
            raise ValueError("gateway_event_ids must match events")
        if self.risk_check_ids != tuple(event.risk_check_id for event in self.events):
            raise ValueError("risk_check_ids must match lifecycle events")

        approved_ids = tuple(
            event.risk_check_id
            for event in self.events
            if event.status is not ExecutionGatewayOrderStatus.BLOCKED
        )
        blocked_ids = tuple(
            event.risk_check_id
            for event in self.events
            if event.status is ExecutionGatewayOrderStatus.BLOCKED
        )
        if self.approved_risk_check_ids != approved_ids:
            raise ValueError("approved_risk_check_ids must match non-blocked events")
        if self.blocked_risk_check_ids != blocked_ids:
            raise ValueError("blocked_risk_check_ids must match blocked events")
        partition = (*self.approved_risk_check_ids, *self.blocked_risk_check_ids)
        if len(partition) != len(self.risk_check_ids) or set(partition) != set(self.risk_check_ids):
            raise ValueError("gateway risk ids must partition input risk checks")

        for event in self.events:
            if event.run_id != self.run_id:
                raise ValueError("event run_id must match gateway report")
            if event.gateway_kind is not self.gateway_kind or event.fill_mode is not self.fill_mode:
                raise ValueError("event gateway kind/fill mode must match gateway report")
            if event.requirement_ids != self.requirement_ids:
                raise ValueError("event requirement_ids must match gateway report")

        if (self.source_replay_report_id is None) != (self.source_replay_report_hash is None):
            raise ValueError("source replay report id/hash must be set together")
        self._validate_final_account_state_linkage()
        if self.approved_risk_check_ids and self.source_replay_report_id is None:
            raise ValueError("approved gateway reports require a source replay report")
        if not self.approved_risk_check_ids and self.source_replay_report_id is not None:
            raise ValueError("blocked-only gateway reports must not carry a source replay report")

        expected_hash = build_execution_gateway_report_hash(report=self)
        if self.gateway_report_hash != expected_hash:
            raise ValueError("gateway_report_hash is not deterministic")
        if self.gateway_report_id != build_execution_gateway_report_id(report_hash=expected_hash):
            raise ValueError("gateway_report_id is not deterministic")
        return self

    def _validate_final_account_state_linkage(self) -> None:
        if self.source_replay_report_id is None:
            if (
                self.source_replay_final_account_state_id is not None
                or self.source_replay_final_account_state_hash is not None
                or self.source_replay_final_account_state is not None
            ):
                raise ValueError(
                    "blocked-only gateway reports must not carry source replay account state"
                )
            return
        if self.source_replay_final_account_state is None:
            if (
                self.source_replay_final_account_state_id is not None
                or self.source_replay_final_account_state_hash is not None
            ):
                raise ValueError(
                    "source replay account state id/hash require embedded account state"
                )
            return
        expected_hash = build_execution_gateway_account_state_hash(
            account_state=self.source_replay_final_account_state
        )
        if self.source_replay_final_account_state_hash != expected_hash:
            raise ValueError("source replay final account state hash is not deterministic")
        if self.source_replay_final_account_state_id != build_execution_gateway_account_state_id(
            account_state_hash=expected_hash
        ):
            raise ValueError("source replay final account state id is not deterministic")


def make_execution_gateway_lifecycle_event(
    *,
    gateway_kind: ExecutionGatewayKind,
    fill_mode: ExecutionFillMode,
    run_id: str,
    risk_event: RiskCheckEvent,
    replay_result: ReplayOrderResult | None,
    requirement_ids: tuple[str, ...],
) -> ExecutionGatewayLifecycleEvent:
    """Build a deterministic gateway lifecycle event from risk and replay evidence."""

    _validate_gateway_fill_mode(gateway_kind=gateway_kind, fill_mode=fill_mode)
    if replay_result is None:
        order_intent = risk_event.request.order_intent
        status = ExecutionGatewayOrderStatus.BLOCKED
        replay_status = None
        gateway_order_id = None
    else:
        if risk_event.approved_order_intent is None:
            raise ValueError("replay-backed gateway events require approved risk intent")
        order_intent = risk_event.approved_order_intent
        status = _REPLAY_TO_GATEWAY_STATUS[replay_result.status]
        replay_status = replay_result.status
        gateway_order_id = build_execution_gateway_order_id_from_parts(
            gateway_kind=gateway_kind,
            run_id=run_id,
            risk_check_id=risk_event.risk_check_id,
            client_order_id=order_intent.client_order_id,
        )

    draft = ExecutionGatewayLifecycleEvent.model_construct(
        gateway_event_id="GATEWAYEVENT:PLACEHOLDER",
        gateway_event_hash="0" * 64,
        gateway_order_id=gateway_order_id,
        gateway_kind=gateway_kind,
        fill_mode=fill_mode,
        run_id=run_id,
        risk_check_id=risk_event.risk_check_id,
        risk_check_hash=risk_event.risk_check_hash,
        risk_decision=risk_event.final_decision,
        risk_reason_codes=risk_event.reason_codes,
        client_order_id=order_intent.client_order_id,
        trace_id=order_intent.trace_id,
        source_decision_id=order_intent.source_decision_id,
        instrument_id=order_intent.instrument_id,
        venue_id=order_intent.venue_id,
        side=order_intent.side,
        order_type=order_intent.order_type,
        requested_quantity=risk_event.request.order_intent.quantity,
        gateway_quantity=order_intent.quantity,
        submitted_at=order_intent.submitted_at,
        status=status,
        replay_order_result_id=(
            replay_result.replay_order_result_id if replay_result is not None else None
        ),
        replay_status=replay_status,
        replay_reject_reason=replay_result.reason if replay_result is not None else None,
        fill_price=replay_result.fill_price if replay_result is not None else None,
        filled_quantity=(
            replay_result.filled_quantity if replay_result is not None else Decimal("0")
        ),
        remaining_quantity=(
            replay_result.remaining_quantity if replay_result is not None else order_intent.quantity
        ),
        fill_event_open_ts=(
            replay_result.fill_event_open_ts if replay_result is not None else None
        ),
        fill_event_close_ts=(
            replay_result.fill_event_close_ts if replay_result is not None else None
        ),
        fill_event_source_ts=(
            replay_result.fill_event_source_ts if replay_result is not None else None
        ),
        fill_raw_payload_id=(
            replay_result.fill_raw_payload_id if replay_result is not None else None
        ),
        cost_model_id=replay_result.cost_model_id if replay_result is not None else None,
        cost_model_hash=replay_result.cost_model_hash if replay_result is not None else None,
        latency_bars=replay_result.latency_bars if replay_result is not None else 0,
        eligible_event_index=(
            replay_result.eligible_event_index if replay_result is not None else None
        ),
        fill_attempt_event_index=(
            replay_result.fill_attempt_event_index if replay_result is not None else None
        ),
        arrival_reference_price=(
            replay_result.arrival_reference_price if replay_result is not None else None
        ),
        effective_fill_price=(
            replay_result.effective_fill_price if replay_result is not None else None
        ),
        reference_notional=(
            replay_result.reference_notional if replay_result is not None else Decimal("0")
        ),
        effective_notional=(
            replay_result.effective_notional if replay_result is not None else Decimal("0")
        ),
        fee_cost=replay_result.fee_cost if replay_result is not None else Decimal("0"),
        spread_cost=replay_result.spread_cost if replay_result is not None else Decimal("0"),
        slippage_cost=(
            replay_result.slippage_cost if replay_result is not None else Decimal("0")
        ),
        total_cost=replay_result.total_cost if replay_result is not None else Decimal("0"),
        requirement_ids=requirement_ids,
    )
    event_hash = build_execution_gateway_event_hash(event=draft)
    return ExecutionGatewayLifecycleEvent(
        **draft.model_dump(exclude={"gateway_event_id", "gateway_event_hash"}),
        gateway_event_id=build_execution_gateway_event_id(event_hash=event_hash),
        gateway_event_hash=event_hash,
    )


def make_execution_gateway_report(
    *,
    run_id: str,
    gateway_kind: ExecutionGatewayKind,
    fill_mode: ExecutionFillMode,
    risk_gated_replay_result: RiskGatedReplayResult,
    events: tuple[ExecutionGatewayLifecycleEvent, ...],
    requirement_ids: tuple[str, ...],
) -> ExecutionGatewayReport:
    """Build a deterministic shared lifecycle report from risk-gated replay output."""

    _validate_gateway_fill_mode(gateway_kind=gateway_kind, fill_mode=fill_mode)
    source_replay_report = risk_gated_replay_result.replay_report
    source_final_account_state = (
        source_replay_report.final_account_state if source_replay_report is not None else None
    )
    source_final_account_state_hash = (
        build_execution_gateway_account_state_hash(account_state=source_final_account_state)
        if source_final_account_state is not None
        else None
    )
    draft = ExecutionGatewayReport.model_construct(
        gateway_report_id="GATEWAYREPORT:PLACEHOLDER",
        gateway_report_hash="0" * 64,
        run_id=run_id,
        gateway_kind=gateway_kind,
        fill_mode=fill_mode,
        risk_check_ids=risk_gated_replay_result.risk_check_ids,
        approved_risk_check_ids=risk_gated_replay_result.approved_risk_check_ids,
        blocked_risk_check_ids=risk_gated_replay_result.blocked_risk_check_ids,
        gateway_event_ids=tuple(event.gateway_event_id for event in events),
        events=events,
        source_risk_gated_replay_result_id=risk_gated_replay_result.result_id,
        source_risk_gated_replay_result_hash=risk_gated_replay_result.result_hash,
        source_replay_report_id=(
            source_replay_report.replay_report_id if source_replay_report is not None else None
        ),
        source_replay_report_hash=(
            source_replay_report.replay_report_hash if source_replay_report is not None else None
        ),
        source_replay_final_account_state_id=(
            build_execution_gateway_account_state_id(
                account_state_hash=source_final_account_state_hash
            )
            if source_final_account_state_hash is not None
            else None
        ),
        source_replay_final_account_state_hash=source_final_account_state_hash,
        source_replay_final_account_state=source_final_account_state,
        requirement_ids=requirement_ids,
    )
    report_hash = build_execution_gateway_report_hash(report=draft)
    return ExecutionGatewayReport(
        **draft.model_dump(exclude={"gateway_report_id", "gateway_report_hash"}),
        gateway_report_id=build_execution_gateway_report_id(report_hash=report_hash),
        gateway_report_hash=report_hash,
    )


def build_execution_gateway_order_id(*, event: ExecutionGatewayLifecycleEvent) -> str:
    return build_execution_gateway_order_id_from_parts(
        gateway_kind=event.gateway_kind,
        run_id=event.run_id,
        risk_check_id=event.risk_check_id,
        client_order_id=event.client_order_id,
    )


def build_execution_gateway_order_id_from_parts(
    *, gateway_kind: ExecutionGatewayKind, run_id: str, risk_check_id: str, client_order_id: str
) -> str:
    return _stable_id(
        "GATEWAYORDER",
        {
            "client_order_id": client_order_id,
            "gateway_kind": gateway_kind.value,
            "risk_check_id": risk_check_id,
            "run_id": run_id,
        },
    )


def build_execution_gateway_event_hash(*, event: ExecutionGatewayLifecycleEvent) -> str:
    return _hash(
        {
            "arrival_reference_price": _decimal(event.arrival_reference_price),
            "client_order_id": event.client_order_id,
            "cost_model_hash": event.cost_model_hash,
            "cost_model_id": event.cost_model_id,
            "effective_fill_price": _decimal(event.effective_fill_price),
            "effective_notional": str(event.effective_notional),
            "eligible_event_index": event.eligible_event_index,
            "fee_cost": str(event.fee_cost),
            "fill_attempt_event_index": event.fill_attempt_event_index,
            "fill_event_close_ts": _iso(event.fill_event_close_ts),
            "fill_event_open_ts": _iso(event.fill_event_open_ts),
            "fill_event_source_ts": _iso(event.fill_event_source_ts),
            "fill_mode": event.fill_mode.value,
            "fill_price": _decimal(event.fill_price),
            "fill_raw_payload_id": event.fill_raw_payload_id,
            "filled_quantity": str(event.filled_quantity),
            "gateway_kind": event.gateway_kind.value,
            "gateway_order_id": event.gateway_order_id,
            "gateway_quantity": str(event.gateway_quantity),
            "instrument_id": event.instrument_id,
            "latency_bars": event.latency_bars,
            "order_type": event.order_type.value,
            "reference_notional": str(event.reference_notional),
            "remaining_quantity": str(event.remaining_quantity),
            "replay_order_result_id": event.replay_order_result_id,
            "replay_reject_reason": (
                event.replay_reject_reason.value
                if event.replay_reject_reason is not None
                else None
            ),
            "replay_status": event.replay_status.value if event.replay_status is not None else None,
            "requested_quantity": str(event.requested_quantity),
            "requirement_ids": event.requirement_ids,
            "risk_check_hash": event.risk_check_hash,
            "risk_check_id": event.risk_check_id,
            "risk_decision": event.risk_decision.value,
            "risk_reason_codes": tuple(reason.value for reason in event.risk_reason_codes),
            "run_id": event.run_id,
            "side": event.side.value,
            "slippage_cost": str(event.slippage_cost),
            "source_decision_id": event.source_decision_id,
            "spread_cost": str(event.spread_cost),
            "status": event.status.value,
            "submitted_at": event.submitted_at.isoformat(),
            "total_cost": str(event.total_cost),
            "trace_id": event.trace_id,
            "venue_id": event.venue_id,
        }
    )


def build_execution_gateway_event_id(*, event_hash: str) -> str:
    return _stable_id("GATEWAYEVENT", {"gateway_event_hash": event_hash})


def build_execution_gateway_report_hash(*, report: ExecutionGatewayReport) -> str:
    return _hash(
        {
            "approved_risk_check_ids": report.approved_risk_check_ids,
            "blocked_risk_check_ids": report.blocked_risk_check_ids,
            "events": tuple(_model_json(event) for event in report.events),
            "fill_mode": report.fill_mode.value,
            "gateway_event_ids": report.gateway_event_ids,
            "gateway_kind": report.gateway_kind.value,
            "requirement_ids": report.requirement_ids,
            "risk_check_ids": report.risk_check_ids,
            "run_id": report.run_id,
            "source_replay_report_hash": report.source_replay_report_hash,
            "source_replay_report_id": report.source_replay_report_id,
            "source_replay_final_account_state": (
                _model_json(report.source_replay_final_account_state)
                if report.source_replay_final_account_state is not None
                else None
            ),
            "source_replay_final_account_state_hash": (
                report.source_replay_final_account_state_hash
            ),
            "source_replay_final_account_state_id": report.source_replay_final_account_state_id,
            "source_risk_gated_replay_result_hash": report.source_risk_gated_replay_result_hash,
            "source_risk_gated_replay_result_id": report.source_risk_gated_replay_result_id,
        }
    )


def build_execution_gateway_report_id(*, report_hash: str) -> str:
    return _stable_id("GATEWAYREPORT", {"gateway_report_hash": report_hash})


def build_execution_gateway_account_state_hash(
    *, account_state: SimulatedAccountState
) -> str:
    return _hash(_model_json(account_state))


def build_execution_gateway_account_state_id(*, account_state_hash: str) -> str:
    return _stable_id("GATEWAYACCOUNTSTATE", {"account_state_hash": account_state_hash})


def _validate_gateway_fill_mode(
    *, gateway_kind: ExecutionGatewayKind, fill_mode: ExecutionFillMode
) -> None:
    if gateway_kind is ExecutionGatewayKind.PAPER:
        if fill_mode is not ExecutionFillMode.PAPER_SIMULATED_FILL:
            raise ValueError("paper gateway reports must use paper_simulated_fill mode")
    elif fill_mode is not ExecutionFillMode.EVENT_TIME_REPLAY:
        raise ValueError("simulator gateway reports must use event_time_replay mode")


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())


def _iso(value: AwareDatetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
