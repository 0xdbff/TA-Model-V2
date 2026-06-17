"""Independent pre-trade risk, kill-switch, and risk-gated replay contracts.

Traceability:
- FR-010: risk-check events record evaluated limits and block unsafe orders before
  simulator, paper, or future gateway paths.
- FR-011: kill-switch states are scoped, durable, auditable, and fail closed when
  unknown or unavailable.
- NFR-004: order submission requires a traceable decision and risk approval.

Scope:
- S9 contract foundation for validated simulation/paper paths only.
- No live capital, leverage, derivatives, margin, shorting, market making, HFT,
  autonomous model promotion, new datastore, or runtime service is introduced.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.instrument_master import (
    CanonicalId,
    ContractModel,
    InstrumentMasterSnapshot,
    NonEmptyString,
    NonNegativeDecimal,
    PositiveDecimal,
)
from ta_model.contracts.simulation import OrderIntent, OrderSide, ReplayReport
from ta_model.contracts.stream_health import DataHealthSignal


class RiskDecisionStatus(StrEnum):
    """Final pre-trade risk decision emitted by the independent risk engine."""

    APPROVED = "approved"
    APPROVED_AFTER_CAP = "approved_after_cap"
    REJECTED = "rejected"
    NO_TRADE = "no_trade"
    CANCEL_REDUCE_ONLY_APPROVED = "cancel_reduce_only_approved"


class RiskLimitStatus(StrEnum):
    """Per-limit evaluation severity."""

    PASS = "pass"
    SOFT_BREACH = "soft_breach"
    HARD_BREACH = "hard_breach"


class RiskReasonCode(StrEnum):
    """Stable risk reason codes for audit/replay and forced-breach evidence."""

    PASSED = "passed"
    REQUIRED_STATE_MISSING = "required_state_missing"
    OUTSIDE_MVP_SCOPE = "outside_mvp_scope"
    UNKNOWN_KILL_STATE = "unknown_kill_state"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    ORDER_MAX_NOTIONAL_SOFT = "order_max_notional_soft"
    ORDER_MAX_NOTIONAL_HARD = "order_max_notional_hard"
    POSITION_INSTRUMENT_EXPOSURE_SOFT = "position_instrument_exposure_soft"
    POSITION_INSTRUMENT_EXPOSURE_HARD = "position_instrument_exposure_hard"
    POSITION_STRATEGY_EXPOSURE_SOFT = "position_strategy_exposure_soft"
    POSITION_STRATEGY_EXPOSURE_HARD = "position_strategy_exposure_hard"
    POSITION_TOTAL_SPOT_EXPOSURE_SOFT = "position_total_spot_exposure_soft"
    POSITION_TOTAL_SPOT_EXPOSURE_HARD = "position_total_spot_exposure_hard"
    CASH_RESERVE_HARD = "cash_reserve_hard"
    NO_SHORT_OR_OVERSELL = "no_short_or_oversell"
    DATA_HEALTH_BLOCK = "data_health_block"
    VENUE_STATUS_HARD = "venue_status_hard"
    VENUE_STATUS_SOFT = "venue_status_soft"
    DUPLICATE_IDEMPOTENCY = "duplicate_idempotency"
    ORDER_THROTTLE_SOFT = "order_throttle_soft"
    ORDER_THROTTLE_HARD = "order_throttle_hard"


class KillSwitchScopeType(StrEnum):
    """Scopes from the S0-003 kill-switch state model."""

    GLOBAL = "global"
    ACCOUNT = "account"
    VENUE = "venue"
    INSTRUMENT = "instrument"
    STRATEGY = "strategy"


class KillSwitchState(StrEnum):
    """S0-003 kill-switch states. Most restrictive matching state wins."""

    UNKNOWN_FAIL_CLOSED = "unknown_fail_closed"
    CLEAR = "clear"
    SOFT_LIMITED = "soft_limited"
    PAUSE_NEW_ORDERS = "pause_new_orders"
    REDUCE_ONLY = "reduce_only"
    CANCEL_ONLY = "cancel_only"
    HALTED = "halted"


class KillSwitchTransitionSource(StrEnum):
    """Source category for audited kill-switch transitions."""

    MANUAL = "manual"
    AUTOMATED = "automated"


class OrderIdempotencyState(StrEnum):
    """Order lifecycle states relevant to duplicate-exposure prevention."""

    RECEIVED = "received"
    ACCEPTED = "accepted"
    PLACED = "placed"
    RECONCILED = "reconciled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class OrderThrottleScopeType(StrEnum):
    """Throttle scopes used by the S9 pre-trade risk engine."""

    STRATEGY_INSTRUMENT = "strategy_instrument"
    ACCOUNT = "account"
    VENUE = "venue"


class KillSwitchScope(ContractModel):
    """A scoped kill-switch key."""

    scope_type: KillSwitchScopeType
    scope_id: CanonicalId | None = None

    @model_validator(mode="after")
    def scope_id_matches_scope_type(self) -> Self:
        if self.scope_type is KillSwitchScopeType.GLOBAL and self.scope_id is not None:
            raise ValueError("global kill-switch scope must not set scope_id")
        if self.scope_type is not KillSwitchScopeType.GLOBAL and self.scope_id is None:
            raise ValueError("non-global kill-switch scope requires scope_id")
        return self

    def key(self) -> tuple[KillSwitchScopeType, str | None]:
        """Return a stable hashable key for store lookups."""

        return (self.scope_type, self.scope_id)


class KillSwitchRecord(ContractModel):
    """Audited durable kill-switch transition record."""

    record_id: CanonicalId
    scope: KillSwitchScope
    prior_state: KillSwitchState
    new_state: KillSwitchState
    actor: NonEmptyString
    actor_role: NonEmptyString
    transitioned_at: AwareDatetime
    reason: NonEmptyString
    cancel_open_orders: bool
    source: KillSwitchTransitionSource = KillSwitchTransitionSource.MANUAL
    linked_incident_id: CanonicalId | None = None
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-011", "NFR-004")

    @model_validator(mode="after")
    def identity_is_deterministic(self) -> Self:
        if self.record_id != build_kill_switch_record_id(record=self):
            raise ValueError("kill-switch record_id is not deterministic")
        return self


class KillSwitchSnapshot(ContractModel):
    """Point-in-time effective kill-switch state used by risk checks."""

    snapshot_id: CanonicalId
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluated_at: AwareDatetime
    evaluated_scopes: tuple[KillSwitchScope, ...]
    active_state: KillSwitchState
    active_records: tuple[KillSwitchRecord, ...] = ()
    store_available: bool
    reason: NonEmptyString
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-011", "NFR-004")

    @model_validator(mode="after")
    def snapshot_identity_is_deterministic(self) -> Self:
        if self.active_state is not KillSwitchState.UNKNOWN_FAIL_CLOSED and not self.active_records:
            raise ValueError("non-unknown kill-switch snapshot requires an active record")
        expected_hash = build_kill_switch_snapshot_hash(snapshot=self)
        if self.snapshot_hash != expected_hash:
            raise ValueError("kill-switch snapshot_hash is not deterministic")
        if self.snapshot_id != build_kill_switch_snapshot_id(snapshot_hash=expected_hash):
            raise ValueError("kill-switch snapshot_id is not deterministic")
        return self


class RiskPolicy(ContractModel):
    """Executable S9 default risk-policy thresholds derived from S0-003."""

    policy_id: CanonicalId
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: NonEmptyString
    paper_nav: PositiveDecimal
    max_order_notional_soft_pct: Decimal = Field(default=Decimal("0.01"), gt=0, le=1)
    max_order_notional_hard_pct: Decimal = Field(default=Decimal("0.025"), gt=0, le=1)
    max_instrument_exposure_soft_pct: Decimal = Field(default=Decimal("0.15"), gt=0, le=1)
    max_instrument_exposure_hard_pct: Decimal = Field(default=Decimal("0.25"), gt=0, le=1)
    max_strategy_exposure_soft_pct: Decimal = Field(default=Decimal("0.20"), gt=0, le=1)
    max_strategy_exposure_hard_pct: Decimal = Field(default=Decimal("0.30"), gt=0, le=1)
    max_total_spot_exposure_soft_pct: Decimal = Field(default=Decimal("0.45"), gt=0, le=1)
    max_total_spot_exposure_hard_pct: Decimal = Field(default=Decimal("0.60"), gt=0, le=1)
    min_cash_reserve_pct: Decimal = Field(default=Decimal("0.30"), ge=0, le=1)
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-010", "FR-011", "NFR-004")

    @model_validator(mode="after")
    def policy_is_consistent_and_deterministic(self) -> Self:
        _raise_if_soft_above_hard(
            self.max_order_notional_soft_pct,
            self.max_order_notional_hard_pct,
            "order notional",
        )
        _raise_if_soft_above_hard(
            self.max_instrument_exposure_soft_pct,
            self.max_instrument_exposure_hard_pct,
            "instrument exposure",
        )
        _raise_if_soft_above_hard(
            self.max_strategy_exposure_soft_pct,
            self.max_strategy_exposure_hard_pct,
            "strategy exposure",
        )
        _raise_if_soft_above_hard(
            self.max_total_spot_exposure_soft_pct,
            self.max_total_spot_exposure_hard_pct,
            "total spot exposure",
        )
        expected_hash = build_risk_policy_hash(policy=self)
        if self.policy_hash != expected_hash:
            raise ValueError("risk policy_hash is not deterministic")
        if self.policy_id != build_risk_policy_id(policy_hash=expected_hash):
            raise ValueError("risk policy_id is not deterministic")
        return self


class OrderEffect(ContractModel):
    """Order effect evaluated before any simulator/paper/future gateway call."""

    side: OrderSide
    quantity: PositiveDecimal
    reference_price: PositiveDecimal
    proposed_notional: NonNegativeDecimal
    resulting_position_quantity: Decimal
    resulting_position_notional: NonNegativeDecimal
    resulting_cash: Decimal
    resulting_instrument_exposure_notional: NonNegativeDecimal
    resulting_strategy_exposure_notional: NonNegativeDecimal
    resulting_total_spot_exposure_notional: NonNegativeDecimal
    cash_reserve_pct: Decimal
    risk_increasing: bool


class RiskLimitEvaluation(ContractModel):
    """One evaluated hard/soft risk limit with objective values and thresholds."""

    limit_id: NonEmptyString
    owner: NonEmptyString
    status: RiskLimitStatus
    passed: bool
    current_value: Decimal
    soft_threshold: Decimal | None = None
    hard_threshold: Decimal | None = None
    capped_value: Decimal | None = None
    reason_code: RiskReasonCode

    @model_validator(mode="after")
    def status_matches_passed_flag(self) -> Self:
        if self.passed != (self.status is RiskLimitStatus.PASS):
            raise ValueError("risk limit passed flag must match pass status")
        if self.status is RiskLimitStatus.PASS and self.reason_code is not RiskReasonCode.PASSED:
            raise ValueError("passing risk limit evaluations must use passed reason code")
        if self.status is not RiskLimitStatus.PASS and self.reason_code is RiskReasonCode.PASSED:
            raise ValueError("breached risk limit evaluations require a non-passed reason code")
        return self


class OrderIdempotencyRecord(ContractModel):
    """Existing order/idempotency state consumed by duplicate-exposure checks."""

    record_id: CanonicalId
    idempotency_key: NonEmptyString
    client_order_id: CanonicalId
    trace_id: CanonicalId
    order_intent_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: OrderIdempotencyState
    first_seen_at: AwareDatetime
    updated_at: AwareDatetime
    owner: NonEmptyString = "Execution / risk"
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-010", "NFR-004")

    @model_validator(mode="after")
    def idempotency_record_is_consistent(self) -> Self:
        if self.updated_at < self.first_seen_at:
            raise ValueError("idempotency updated_at must not precede first_seen_at")
        if self.record_id != build_order_idempotency_record_id(record=self):
            raise ValueError("idempotency record_id is not deterministic")
        return self


class OrderThrottleWindow(ContractModel):
    """Scoped order-intent window used by pre-trade throttle checks."""

    scope_type: OrderThrottleScopeType
    scope_id: CanonicalId
    observed_intent_count: int = Field(ge=0)
    soft_limit: int = Field(gt=0)
    hard_limit: int = Field(gt=0)
    window_started_at: AwareDatetime
    window_seconds: int = Field(gt=0)
    owner: NonEmptyString = "Execution / ops"
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-010", "NFR-004")

    @model_validator(mode="after")
    def throttle_window_is_consistent(self) -> Self:
        if self.soft_limit > self.hard_limit:
            raise ValueError("order throttle soft_limit cannot exceed hard_limit")
        return self


class RiskCheckRequest(ContractModel):
    """Complete independent risk-check input for one pre-trade order intent."""

    request_id: CanonicalId
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: CanonicalId
    trace_id: CanonicalId
    source_decision_id: CanonicalId
    decision_ts: AwareDatetime
    risk_check_ts: AwareDatetime
    strategy_version: NonEmptyString
    account_id: CanonicalId
    order_intent: OrderIntent
    idempotency_key: NonEmptyString
    reference_price: PositiveDecimal
    account_equity: PositiveDecimal
    current_cash: NonNegativeDecimal
    current_instrument_position_quantity: NonNegativeDecimal = Decimal("0")
    current_instrument_exposure_notional: NonNegativeDecimal = Decimal("0")
    current_strategy_exposure_notional: NonNegativeDecimal = Decimal("0")
    current_total_spot_exposure_notional: NonNegativeDecimal = Decimal("0")
    instrument_master_snapshot: InstrumentMasterSnapshot
    kill_switch_snapshot: KillSwitchSnapshot
    data_health_signals: tuple[DataHealthSignal, ...] = ()
    idempotency_records: tuple[OrderIdempotencyRecord, ...] = ()
    throttle_windows: tuple[OrderThrottleWindow, ...] = ()
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-010", "FR-011", "NFR-004")

    @model_validator(mode="after")
    def request_is_consistent_and_deterministic(self) -> Self:
        if self.risk_check_ts < self.decision_ts:
            raise ValueError("risk_check_ts must not precede decision_ts")
        if self.trace_id != self.order_intent.trace_id:
            raise ValueError("risk-check trace_id must match order intent trace_id")
        if self.source_decision_id != self.order_intent.source_decision_id:
            raise ValueError("source_decision_id must match order intent source_decision_id")
        if self.order_intent.submitted_at < self.decision_ts:
            raise ValueError("order intent submitted_at must not precede decision_ts")
        if self.order_intent.instrument_id not in {
            instrument.instrument_id for instrument in self.instrument_master_snapshot.instruments
        }:
            raise ValueError("order intent instrument_id must exist in instrument master snapshot")
        expected_hash = build_risk_check_request_hash(request=self)
        if self.request_hash != expected_hash:
            raise ValueError("risk-check request_hash is not deterministic")
        if self.request_id != build_risk_check_request_id(request_hash=expected_hash):
            raise ValueError("risk-check request_id is not deterministic")
        return self


class RiskCheckEvent(ContractModel):
    """Deterministic pre-trade risk approval/rejection evidence event."""

    risk_check_id: CanonicalId
    risk_check_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    request: RiskCheckRequest
    risk_policy_id: CanonicalId
    risk_policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    order_effect: OrderEffect
    limit_evaluations: tuple[RiskLimitEvaluation, ...] = Field(min_length=1)
    active_kill_state: KillSwitchState
    final_decision: RiskDecisionStatus
    reason_codes: tuple[RiskReasonCode, ...]
    approved_order_intent: OrderIntent | None = None
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-010", "FR-011", "NFR-004")

    @model_validator(mode="after")
    def event_is_consistent_and_deterministic(self) -> Self:
        if self.active_kill_state is not self.request.kill_switch_snapshot.active_state:
            raise ValueError("active_kill_state must match kill-switch snapshot")
        expected_reasons = tuple(
            evaluation.reason_code
            for evaluation in self.limit_evaluations
            if evaluation.reason_code is not RiskReasonCode.PASSED
        )
        if self.reason_codes != expected_reasons:
            raise ValueError("risk reason_codes must match breached limit evaluations")
        has_hard_breach = any(
            evaluation.status is RiskLimitStatus.HARD_BREACH
            for evaluation in self.limit_evaluations
        )
        if has_hard_breach and self.final_decision is not RiskDecisionStatus.REJECTED:
            raise ValueError("hard breaches must reject the risk check")
        if self.final_decision in {
            RiskDecisionStatus.APPROVED,
            RiskDecisionStatus.APPROVED_AFTER_CAP,
            RiskDecisionStatus.CANCEL_REDUCE_ONLY_APPROVED,
        }:
            if self.approved_order_intent is None:
                raise ValueError("approved risk decisions require an approved order intent")
        elif self.approved_order_intent is not None:
            raise ValueError("rejected/no-trade risk decisions must not carry an approved intent")
        expected_hash = build_risk_check_event_hash(event=self)
        if self.risk_check_hash != expected_hash:
            raise ValueError("risk_check_hash is not deterministic")
        if self.risk_check_id != build_risk_check_event_id(risk_check_hash=expected_hash):
            raise ValueError("risk_check_id is not deterministic")
        return self


class RiskGatedReplayResult(ContractModel):
    """Evidence that only risk-approved intents were forwarded to real S6 replay."""

    result_id: CanonicalId
    result_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: CanonicalId
    risk_check_ids: tuple[CanonicalId, ...]
    approved_risk_check_ids: tuple[CanonicalId, ...]
    blocked_risk_check_ids: tuple[CanonicalId, ...]
    replay_report: ReplayReport | None = None
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-010", "FR-012", "NFR-004")

    @model_validator(mode="after")
    def replay_result_is_consistent_and_deterministic(self) -> Self:
        partition = (*self.approved_risk_check_ids, *self.blocked_risk_check_ids)
        if len(partition) != len(self.risk_check_ids) or set(partition) != set(self.risk_check_ids):
            raise ValueError("risk-gated replay ids must partition input risk checks")
        if not self.approved_risk_check_ids and self.replay_report is not None:
            raise ValueError("risk-gated replay must not create a replay report without approvals")
        if self.approved_risk_check_ids and self.replay_report is None:
            raise ValueError("approved risk checks require a replay report")
        expected_hash = build_risk_gated_replay_result_hash(result=self)
        if self.result_hash != expected_hash:
            raise ValueError("risk-gated replay result_hash is not deterministic")
        if self.result_id != build_risk_gated_replay_result_id(result_hash=expected_hash):
            raise ValueError("risk-gated replay result_id is not deterministic")
        return self


def make_default_risk_policy(
    *, paper_nav: Decimal, name: str = "s9-default-risk-policy"
) -> RiskPolicy:
    """Build the default S0-003-derived S9 policy with deterministic identity."""

    draft = RiskPolicy.model_construct(
        policy_id="RISKPOLICY:PLACEHOLDER",
        policy_hash="0" * 64,
        name=name,
        paper_nav=paper_nav,
    )
    policy_hash = build_risk_policy_hash(policy=draft)
    return RiskPolicy(
        **draft.model_dump(exclude={"policy_id", "policy_hash"}),
        policy_id=build_risk_policy_id(policy_hash=policy_hash),
        policy_hash=policy_hash,
    )


def make_kill_switch_record(
    *,
    scope: KillSwitchScope,
    prior_state: KillSwitchState,
    new_state: KillSwitchState,
    actor: str,
    actor_role: str,
    transitioned_at: datetime,
    reason: str,
    cancel_open_orders: bool,
    source: KillSwitchTransitionSource = KillSwitchTransitionSource.MANUAL,
    linked_incident_id: str | None = None,
) -> KillSwitchRecord:
    """Build an audited kill-switch transition record with deterministic id."""

    draft = KillSwitchRecord.model_construct(
        record_id="KILLRECORD:PLACEHOLDER",
        scope=scope,
        prior_state=prior_state,
        new_state=new_state,
        actor=actor,
        actor_role=actor_role,
        transitioned_at=transitioned_at,
        reason=reason,
        cancel_open_orders=cancel_open_orders,
        source=source,
        linked_incident_id=linked_incident_id,
    )
    return KillSwitchRecord(
        **draft.model_dump(exclude={"record_id"}),
        record_id=build_kill_switch_record_id(record=draft),
    )


def make_kill_switch_snapshot(
    *,
    evaluated_at: datetime,
    evaluated_scopes: tuple[KillSwitchScope, ...],
    active_state: KillSwitchState,
    active_records: tuple[KillSwitchRecord, ...],
    store_available: bool,
    reason: str,
) -> KillSwitchSnapshot:
    """Build a deterministic effective kill-switch snapshot."""

    draft = KillSwitchSnapshot.model_construct(
        snapshot_id="KILLSNAPSHOT:PLACEHOLDER",
        snapshot_hash="0" * 64,
        evaluated_at=evaluated_at,
        evaluated_scopes=evaluated_scopes,
        active_state=active_state,
        active_records=active_records,
        store_available=store_available,
        reason=reason,
    )
    snapshot_hash = build_kill_switch_snapshot_hash(snapshot=draft)
    return KillSwitchSnapshot(
        **draft.model_dump(exclude={"snapshot_id", "snapshot_hash"}),
        snapshot_id=build_kill_switch_snapshot_id(snapshot_hash=snapshot_hash),
        snapshot_hash=snapshot_hash,
    )


def make_unknown_kill_switch_snapshot(
    *,
    evaluated_at: datetime,
    evaluated_scopes: tuple[KillSwitchScope, ...],
    store_available: bool = False,
    reason: str = "durable kill-switch state unavailable or uninitialized",
) -> KillSwitchSnapshot:
    """Build the required fail-closed unknown kill-switch snapshot."""

    return make_kill_switch_snapshot(
        evaluated_at=evaluated_at,
        evaluated_scopes=evaluated_scopes,
        active_state=KillSwitchState.UNKNOWN_FAIL_CLOSED,
        active_records=(),
        store_available=store_available,
        reason=reason,
    )


def make_order_idempotency_record(
    *,
    idempotency_key: str,
    client_order_id: str,
    trace_id: str,
    order_intent_hash: str,
    state: OrderIdempotencyState,
    first_seen_at: datetime,
    updated_at: datetime,
) -> OrderIdempotencyRecord:
    """Build deterministic order idempotency state for duplicate checks."""

    draft = OrderIdempotencyRecord.model_construct(
        record_id="IDEMPOTENCY:PLACEHOLDER",
        idempotency_key=idempotency_key,
        client_order_id=client_order_id,
        trace_id=trace_id,
        order_intent_hash=order_intent_hash,
        state=state,
        first_seen_at=first_seen_at,
        updated_at=updated_at,
    )
    return OrderIdempotencyRecord(
        **draft.model_dump(exclude={"record_id"}),
        record_id=build_order_idempotency_record_id(record=draft),
    )


def make_risk_check_request(
    *,
    run_id: str,
    decision_ts: datetime,
    risk_check_ts: datetime,
    strategy_version: str,
    account_id: str,
    order_intent: OrderIntent,
    reference_price: Decimal,
    account_equity: Decimal,
    current_cash: Decimal,
    instrument_master_snapshot: InstrumentMasterSnapshot,
    kill_switch_snapshot: KillSwitchSnapshot,
    idempotency_key: str | None = None,
    current_instrument_position_quantity: Decimal = Decimal("0"),
    current_instrument_exposure_notional: Decimal = Decimal("0"),
    current_strategy_exposure_notional: Decimal = Decimal("0"),
    current_total_spot_exposure_notional: Decimal = Decimal("0"),
    data_health_signals: tuple[DataHealthSignal, ...] = (),
    idempotency_records: tuple[OrderIdempotencyRecord, ...] = (),
    throttle_windows: tuple[OrderThrottleWindow, ...] = (),
) -> RiskCheckRequest:
    """Build a deterministic risk-check request from a real order intent."""

    draft = RiskCheckRequest.model_construct(
        request_id="RISKREQUEST:PLACEHOLDER",
        request_hash="0" * 64,
        run_id=run_id,
        trace_id=order_intent.trace_id,
        source_decision_id=order_intent.source_decision_id,
        decision_ts=decision_ts,
        risk_check_ts=risk_check_ts,
        strategy_version=strategy_version,
        account_id=account_id,
        order_intent=order_intent,
        idempotency_key=idempotency_key or order_intent.client_order_id,
        reference_price=reference_price,
        account_equity=account_equity,
        current_cash=current_cash,
        current_instrument_position_quantity=current_instrument_position_quantity,
        current_instrument_exposure_notional=current_instrument_exposure_notional,
        current_strategy_exposure_notional=current_strategy_exposure_notional,
        current_total_spot_exposure_notional=current_total_spot_exposure_notional,
        instrument_master_snapshot=instrument_master_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        data_health_signals=data_health_signals,
        idempotency_records=idempotency_records,
        throttle_windows=throttle_windows,
    )
    request_hash = build_risk_check_request_hash(request=draft)
    return RiskCheckRequest(
        **draft.model_dump(exclude={"request_id", "request_hash"}),
        request_id=build_risk_check_request_id(request_hash=request_hash),
        request_hash=request_hash,
    )


def make_risk_check_event(
    *,
    request: RiskCheckRequest,
    risk_policy: RiskPolicy,
    order_effect: OrderEffect,
    limit_evaluations: tuple[RiskLimitEvaluation, ...],
    final_decision: RiskDecisionStatus,
    approved_order_intent: OrderIntent | None = None,
) -> RiskCheckEvent:
    """Build a deterministic risk-check event from pure engine output."""

    draft = RiskCheckEvent.model_construct(
        risk_check_id="RISKCHECK:PLACEHOLDER",
        risk_check_hash="0" * 64,
        request=request,
        risk_policy_id=risk_policy.policy_id,
        risk_policy_hash=risk_policy.policy_hash,
        order_effect=order_effect,
        limit_evaluations=limit_evaluations,
        active_kill_state=request.kill_switch_snapshot.active_state,
        final_decision=final_decision,
        reason_codes=tuple(
            evaluation.reason_code
            for evaluation in limit_evaluations
            if evaluation.reason_code is not RiskReasonCode.PASSED
        ),
        approved_order_intent=approved_order_intent,
    )
    risk_check_hash = build_risk_check_event_hash(event=draft)
    return RiskCheckEvent(
        **draft.model_dump(exclude={"risk_check_id", "risk_check_hash"}),
        risk_check_id=build_risk_check_event_id(risk_check_hash=risk_check_hash),
        risk_check_hash=risk_check_hash,
    )


def make_risk_gated_replay_result(
    *,
    run_id: str,
    risk_check_ids: tuple[str, ...],
    approved_risk_check_ids: tuple[str, ...],
    blocked_risk_check_ids: tuple[str, ...],
    replay_report: ReplayReport | None,
) -> RiskGatedReplayResult:
    """Build deterministic evidence for a risk-gated replay run."""

    draft = RiskGatedReplayResult.model_construct(
        result_id="RISKGATEDREPLAY:PLACEHOLDER",
        result_hash="0" * 64,
        run_id=run_id,
        risk_check_ids=risk_check_ids,
        approved_risk_check_ids=approved_risk_check_ids,
        blocked_risk_check_ids=blocked_risk_check_ids,
        replay_report=replay_report,
    )
    result_hash = build_risk_gated_replay_result_hash(result=draft)
    return RiskGatedReplayResult(
        **draft.model_dump(exclude={"result_id", "result_hash"}),
        result_id=build_risk_gated_replay_result_id(result_hash=result_hash),
        result_hash=result_hash,
    )


def build_order_intent_hash(*, order_intent: OrderIntent) -> str:
    """Build a deterministic hash for idempotency and replay evidence."""

    return _hash(_model_json(order_intent))


def build_risk_policy_hash(*, policy: RiskPolicy) -> str:
    return _hash(
        {
            "max_instrument_exposure_hard_pct": str(policy.max_instrument_exposure_hard_pct),
            "max_instrument_exposure_soft_pct": str(policy.max_instrument_exposure_soft_pct),
            "max_order_notional_hard_pct": str(policy.max_order_notional_hard_pct),
            "max_order_notional_soft_pct": str(policy.max_order_notional_soft_pct),
            "max_strategy_exposure_hard_pct": str(policy.max_strategy_exposure_hard_pct),
            "max_strategy_exposure_soft_pct": str(policy.max_strategy_exposure_soft_pct),
            "max_total_spot_exposure_hard_pct": str(policy.max_total_spot_exposure_hard_pct),
            "max_total_spot_exposure_soft_pct": str(policy.max_total_spot_exposure_soft_pct),
            "min_cash_reserve_pct": str(policy.min_cash_reserve_pct),
            "name": policy.name,
            "paper_nav": str(policy.paper_nav),
            "requirement_ids": policy.requirement_ids,
        }
    )


def build_risk_policy_id(*, policy_hash: str) -> str:
    return _stable_id("RISKPOLICY", {"policy_hash": policy_hash})


def build_kill_switch_record_id(*, record: KillSwitchRecord) -> str:
    return _stable_id(
        "KILLRECORD",
        {
            "actor": record.actor,
            "actor_role": record.actor_role,
            "cancel_open_orders": record.cancel_open_orders,
            "linked_incident_id": record.linked_incident_id,
            "new_state": record.new_state.value,
            "prior_state": record.prior_state.value,
            "reason": record.reason,
            "scope": _model_json(record.scope),
            "source": record.source.value,
            "transitioned_at": record.transitioned_at.isoformat(),
        },
    )


def build_kill_switch_snapshot_hash(*, snapshot: KillSwitchSnapshot) -> str:
    return _hash(
        {
            "active_records": tuple(_model_json(record) for record in snapshot.active_records),
            "active_state": snapshot.active_state.value,
            "evaluated_at": snapshot.evaluated_at.isoformat(),
            "evaluated_scopes": tuple(_model_json(scope) for scope in snapshot.evaluated_scopes),
            "reason": snapshot.reason,
            "requirement_ids": snapshot.requirement_ids,
            "store_available": snapshot.store_available,
        }
    )


def build_kill_switch_snapshot_id(*, snapshot_hash: str) -> str:
    return _stable_id("KILLSNAPSHOT", {"snapshot_hash": snapshot_hash})


def build_order_idempotency_record_id(*, record: OrderIdempotencyRecord) -> str:
    return _stable_id(
        "IDEMPOTENCY",
        {
            "client_order_id": record.client_order_id,
            "first_seen_at": record.first_seen_at.isoformat(),
            "idempotency_key": record.idempotency_key,
            "order_intent_hash": record.order_intent_hash,
            "state": record.state.value,
            "trace_id": record.trace_id,
            "updated_at": record.updated_at.isoformat(),
        },
    )


def build_risk_check_request_hash(*, request: RiskCheckRequest) -> str:
    return _hash(
        {
            "account_equity": str(request.account_equity),
            "account_id": request.account_id,
            "current_cash": str(request.current_cash),
            "current_instrument_exposure_notional": str(
                request.current_instrument_exposure_notional
            ),
            "current_instrument_position_quantity": str(
                request.current_instrument_position_quantity
            ),
            "current_strategy_exposure_notional": str(request.current_strategy_exposure_notional),
            "current_total_spot_exposure_notional": str(
                request.current_total_spot_exposure_notional
            ),
            "data_health_signals": tuple(
                _model_json(signal) for signal in request.data_health_signals
            ),
            "decision_ts": request.decision_ts.isoformat(),
            "idempotency_key": request.idempotency_key,
            "idempotency_records": tuple(
                _model_json(record) for record in request.idempotency_records
            ),
            "instrument_master_snapshot": _instrument_master_risk_payload(
                snapshot=request.instrument_master_snapshot
            ),
            "kill_switch_snapshot": _model_json(request.kill_switch_snapshot),
            "order_intent": _model_json(request.order_intent),
            "reference_price": str(request.reference_price),
            "requirement_ids": request.requirement_ids,
            "risk_check_ts": request.risk_check_ts.isoformat(),
            "run_id": request.run_id,
            "source_decision_id": request.source_decision_id,
            "strategy_version": request.strategy_version,
            "throttle_windows": tuple(_model_json(window) for window in request.throttle_windows),
            "trace_id": request.trace_id,
        }
    )


def build_risk_check_request_id(*, request_hash: str) -> str:
    return _stable_id("RISKREQUEST", {"request_hash": request_hash})


def build_risk_check_event_hash(*, event: RiskCheckEvent) -> str:
    return _hash(
        {
            "active_kill_state": event.active_kill_state.value,
            "approved_order_intent": (
                _model_json(event.approved_order_intent)
                if event.approved_order_intent is not None
                else None
            ),
            "final_decision": event.final_decision.value,
            "limit_evaluations": tuple(
                _model_json(evaluation) for evaluation in event.limit_evaluations
            ),
            "order_effect": _model_json(event.order_effect),
            "reason_codes": tuple(reason.value for reason in event.reason_codes),
            "request_hash": event.request.request_hash,
            "request_id": event.request.request_id,
            "requirement_ids": event.requirement_ids,
            "risk_policy_hash": event.risk_policy_hash,
            "risk_policy_id": event.risk_policy_id,
        }
    )


def build_risk_check_event_id(*, risk_check_hash: str) -> str:
    return _stable_id("RISKCHECK", {"risk_check_hash": risk_check_hash})


def build_risk_gated_replay_result_hash(*, result: RiskGatedReplayResult) -> str:
    return _hash(
        {
            "approved_risk_check_ids": result.approved_risk_check_ids,
            "blocked_risk_check_ids": result.blocked_risk_check_ids,
            "replay_report": (
                _model_json(result.replay_report) if result.replay_report is not None else None
            ),
            "requirement_ids": result.requirement_ids,
            "risk_check_ids": result.risk_check_ids,
            "run_id": result.run_id,
        }
    )


def build_risk_gated_replay_result_id(*, result_hash: str) -> str:
    return _stable_id("RISKGATEDREPLAY", {"result_hash": result_hash})


def _raise_if_soft_above_hard(soft: Decimal, hard: Decimal, label: str) -> None:
    if soft > hard:
        raise ValueError(f"{label} soft threshold cannot exceed hard threshold")


def _instrument_master_risk_payload(*, snapshot: InstrumentMasterSnapshot) -> object:
    return {
        "accounts": tuple(
            {
                "account_id": account.account_id,
                "account_type": account.account_type.value,
                "derivatives_enabled": account.derivatives_enabled,
                "live_capital_enabled": account.live_capital_enabled,
                "margin_enabled": account.margin_enabled,
                "risk_limits": {
                    "max_drawdown_pct": str(account.risk_limits.max_drawdown_pct),
                    "max_instrument_exposure_pct": str(
                        account.risk_limits.max_instrument_exposure_pct
                    ),
                    "max_order_notional_pct": str(account.risk_limits.max_order_notional_pct),
                    "max_strategy_exposure_pct": str(
                        account.risk_limits.max_strategy_exposure_pct
                    ),
                    "max_total_spot_exposure_pct": str(
                        account.risk_limits.max_total_spot_exposure_pct
                    ),
                    "min_cash_reserve_pct": str(account.risk_limits.min_cash_reserve_pct),
                },
                "shorting_enabled": account.shorting_enabled,
                "status": account.status.value,
                "trading_permissions": tuple(
                    sorted(permission.value for permission in account.trading_permissions)
                ),
                "venue_id": account.venue_id,
            }
            for account in sorted(snapshot.accounts, key=lambda item: item.account_id)
        ),
        "created_at": snapshot.created_at.isoformat(),
        "instrument_constraints": tuple(
            {
                "constraint_id": constraint.constraint_id,
                "effective_from": constraint.effective_from.isoformat(),
                "effective_to": (
                    constraint.effective_to.isoformat()
                    if constraint.effective_to is not None
                    else None
                ),
                "instrument_id": constraint.instrument_id,
                "lot_size": str(constraint.lot_size),
                "max_order_notional": (
                    str(constraint.max_order_notional)
                    if constraint.max_order_notional is not None
                    else None
                ),
                "max_order_quantity": (
                    str(constraint.max_order_quantity)
                    if constraint.max_order_quantity is not None
                    else None
                ),
                "min_notional": str(constraint.min_notional),
                "min_order_quantity": (
                    str(constraint.min_order_quantity)
                    if constraint.min_order_quantity is not None
                    else None
                ),
                "tick_size": str(constraint.tick_size),
            }
            for constraint in sorted(
                snapshot.instrument_constraints,
                key=lambda item: item.constraint_id,
            )
        ),
        "instruments": tuple(
            {
                "instrument_id": instrument.instrument_id,
                "instrument_type": instrument.instrument_type.value,
                "is_derivative": instrument.is_derivative,
                "leverage_allowed": instrument.leverage_allowed,
                "lot_size": str(instrument.lot_size),
                "margin_allowed": instrument.margin_allowed,
                "min_notional": str(instrument.min_notional),
                "short_selling_allowed": instrument.short_selling_allowed,
                "status": instrument.status.value,
                "supported_order_types": tuple(
                    sorted(order_type.value for order_type in instrument.supported_order_types)
                ),
                "tick_size": str(instrument.tick_size),
                "venue_id": instrument.venue_id,
            }
            for instrument in sorted(snapshot.instruments, key=lambda item: item.instrument_id)
        ),
        "snapshot_id": snapshot.snapshot_id,
        "venues": tuple(
            {
                "status": venue.status.value,
                "supported_order_types": tuple(
                    sorted(order_type.value for order_type in venue.supported_order_types)
                ),
                "venue_id": venue.venue_id,
            }
            for venue in sorted(snapshot.venues, key=lambda item: item.venue_id)
        ),
    }


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())
