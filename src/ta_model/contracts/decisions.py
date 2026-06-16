"""Strategy decision contracts for forecast-to-trade/no-trade handoff.

Traceability:
- FR-009: decision objects include expected return, expected cost, net edge,
  uncertainty, and machine-readable reason codes for trade and no-trade paths.
- FR-015/NFR-004: deterministic IDs, hashes, trace IDs, and forecast lineage make
  decisions auditable and replay-ready.

Scope:
- S8 decision contract only. No risk approval, order routing, paper/live gateway,
  leverage, derivatives, shorts, margin, HFT, or live capital path is introduced.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString


class StrategyDecisionAction(StrEnum):
    """Bounded S8 strategy action set for MVP long-only spot readiness."""

    BUY = "buy"
    NO_TRADE = "no_trade"


class StrategyDecisionReasonCode(StrEnum):
    """Machine-readable reason for a trade or first-class no-trade decision."""

    TRADE_POSITIVE_NET_EDGE = "trade_positive_net_edge"
    INSUFFICIENT_NET_EDGE = "insufficient_net_edge"
    COST_THRESHOLD = "cost_threshold"
    UNCERTAINTY_THRESHOLD = "uncertainty_threshold"
    NON_POSITIVE_EXPECTED_RETURN = "non_positive_expected_return"
    UNSUPPORTED_FORECAST = "unsupported_forecast"


class ExpectedReturnSource(StrEnum):
    """Forecast field used by the S8 expected-net-edge policy."""

    MEDIAN_QUANTILE = "median_quantile"


class StrategySizingStatus(StrEnum):
    """Sizing state before S8-003 sizing and S9 independent risk approval."""

    PLACEHOLDER_PENDING_RISK = "placeholder_pending_independent_risk"


class StrategyRiskApprovalStatus(StrEnum):
    """Risk approval state carried by S8 decisions without approving risk."""

    NOT_EVALUATED = "not_evaluated"


class StrategyDecisionPolicy(ContractModel):
    """Explicit assumptions for converting forecasts into strategy decisions."""

    policy_id: CanonicalId
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: NonEmptyString
    expected_return_source: ExpectedReturnSource = ExpectedReturnSource.MEDIAN_QUANTILE
    expected_return_quantile: Decimal = Field(default=Decimal("0.5"), gt=0, lt=1)
    expected_cost: Decimal = Field(ge=Decimal("0"))
    max_expected_cost: Decimal = Field(ge=Decimal("0"))
    uncertainty_buffer_multiplier: Decimal = Field(default=Decimal("1"), ge=Decimal("0"))
    max_uncertainty: Decimal = Field(ge=Decimal("0"))
    min_net_edge: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-009", "FR-015")

    @field_validator(
        "expected_return_quantile",
        "expected_cost",
        "max_expected_cost",
        "uncertainty_buffer_multiplier",
        "max_uncertainty",
        "min_net_edge",
    )
    @classmethod
    def decimals_are_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("strategy decision policy decimals must be finite")
        return value

    @model_validator(mode="after")
    def policy_identity_is_deterministic(self) -> Self:
        expected_hash = build_strategy_decision_policy_hash(policy=self)
        if self.policy_hash != expected_hash:
            raise ValueError("policy_hash is not deterministic")
        if self.policy_id != build_strategy_decision_policy_id(policy_hash=expected_hash):
            raise ValueError("policy_id is not deterministic")
        return self


class StrategySizingProposal(ContractModel):
    """Sizing placeholder carried to future sizing/risk work without approval."""

    sizing_status: StrategySizingStatus = StrategySizingStatus.PLACEHOLDER_PENDING_RISK
    proposed_notional: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    proposed_quantity: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    approved_notional: Decimal | None = Field(default=None, ge=Decimal("0"))
    approved_quantity: Decimal | None = Field(default=None, ge=Decimal("0"))
    risk_approval_status: StrategyRiskApprovalStatus = StrategyRiskApprovalStatus.NOT_EVALUATED
    risk_approval_id: CanonicalId | None = None

    @field_validator(
        "proposed_notional",
        "proposed_quantity",
        "approved_notional",
        "approved_quantity",
    )
    @classmethod
    def sizing_decimals_are_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("sizing decimals must be finite")
        return value

    @model_validator(mode="after")
    def s8_does_not_approve_risk(self) -> Self:
        if (
            self.approved_notional is not None
            or self.approved_quantity is not None
            or self.risk_approval_id is not None
            or self.risk_approval_status is not StrategyRiskApprovalStatus.NOT_EVALUATED
        ):
            raise ValueError("S8 decisions must not carry independent risk approval")
        return self


class StrategyDecision(ContractModel):
    """Auditable trade/no-trade strategy decision produced from one forecast."""

    decision_id: CanonicalId
    decision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    trace_id: CanonicalId
    strategy_run_id: CanonicalId
    policy_id: CanonicalId
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_forecast_id: CanonicalId
    dataset_snapshot_id: CanonicalId
    dataset_row_id: CanonicalId
    feature_vector_id: CanonicalId
    feature_input_snapshot_id: CanonicalId
    feature_version: NonEmptyString
    source_feature_snapshot_ids: tuple[CanonicalId, ...] = ()
    instrument_id: CanonicalId
    venue_id: CanonicalId
    feature_ts: AwareDatetime
    decision_ts: AwareDatetime = Field(
        description="Event-time decision timestamp; must not precede forecast feature_ts."
    )
    label_rule_id: CanonicalId
    split: DatasetSplit
    training_run_id: CanonicalId
    model_version_id: CanonicalId
    model_version_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: StrategyDecisionAction
    expected_return: Decimal
    expected_cost: Decimal = Field(ge=Decimal("0"))
    uncertainty: Decimal = Field(ge=Decimal("0"))
    uncertainty_buffer: Decimal = Field(ge=Decimal("0"))
    net_edge: Decimal
    reason_code: StrategyDecisionReasonCode
    sizing: StrategySizingProposal = Field(default_factory=StrategySizingProposal)
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-009", "FR-015")

    @field_validator(
        "expected_return",
        "expected_cost",
        "uncertainty",
        "uncertainty_buffer",
        "net_edge",
    )
    @classmethod
    def economics_are_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("strategy decision economics must be finite")
        return value

    @model_validator(mode="after")
    def decision_is_consistent_and_deterministic(self) -> Self:
        if self.split is DatasetSplit.TRAIN:
            raise ValueError("strategy decisions require out-of-sample forecasts")
        if self.decision_ts < self.feature_ts:
            raise ValueError("decision_ts must not precede feature_ts")
        if self.net_edge != self.expected_return - self.expected_cost - self.uncertainty_buffer:
            raise ValueError(
                "net_edge must equal expected_return minus expected_cost minus uncertainty_buffer"
            )
        expected_trace_id = build_strategy_trace_id(
            strategy_run_id=self.strategy_run_id,
            source_forecast_id=self.source_forecast_id,
            policy_hash=self.policy_hash,
            decision_ts=self.decision_ts,
        )
        if self.trace_id != expected_trace_id:
            raise ValueError("trace_id is not deterministic")
        if self.action is StrategyDecisionAction.BUY:
            if self.reason_code is not StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE:
                raise ValueError("buy decisions require trade_positive_net_edge reason")
            if self.expected_return <= 0 or self.net_edge <= 0:
                raise ValueError("buy decisions require positive expected return and net edge")
        else:
            if self.reason_code is StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE:
                raise ValueError("no-trade decisions require a no-trade reason")
            if self.sizing.proposed_notional != 0 or self.sizing.proposed_quantity != 0:
                raise ValueError("no-trade decisions must keep proposed size at zero")
        expected_hash = build_strategy_decision_hash(decision=self)
        if self.decision_hash != expected_hash:
            raise ValueError("decision_hash is not deterministic")
        if self.decision_id != build_strategy_decision_id(decision_hash=expected_hash):
            raise ValueError("decision_id is not deterministic")
        return self


class StrategyDecisionReasonCount(ContractModel):
    """Deterministic reason-code accounting from real StrategyDecision objects."""

    reason_code: StrategyDecisionReasonCode
    count: int = Field(gt=0)


def make_strategy_decision_policy(
    *,
    name: str,
    expected_cost: Decimal,
    max_expected_cost: Decimal,
    max_uncertainty: Decimal,
    min_net_edge: Decimal = Decimal("0"),
    uncertainty_buffer_multiplier: Decimal = Decimal("1"),
    expected_return_quantile: Decimal = Decimal("0.5"),
    expected_return_source: ExpectedReturnSource = ExpectedReturnSource.MEDIAN_QUANTILE,
    requirement_ids: tuple[str, ...] = ("FR-009", "FR-015"),
) -> StrategyDecisionPolicy:
    """Build a strategy decision policy with deterministic identity."""

    draft = StrategyDecisionPolicy.model_construct(
        policy_id="STRATEGYPOLICY:PLACEHOLDER",
        policy_hash="0" * 64,
        name=name,
        expected_return_source=expected_return_source,
        expected_return_quantile=expected_return_quantile,
        expected_cost=expected_cost,
        max_expected_cost=max_expected_cost,
        uncertainty_buffer_multiplier=uncertainty_buffer_multiplier,
        max_uncertainty=max_uncertainty,
        min_net_edge=min_net_edge,
        requirement_ids=requirement_ids,
    )
    policy_hash = build_strategy_decision_policy_hash(policy=draft)
    return StrategyDecisionPolicy(
        **draft.model_dump(exclude={"policy_id", "policy_hash"}),
        policy_id=build_strategy_decision_policy_id(policy_hash=policy_hash),
        policy_hash=policy_hash,
    )


def build_strategy_decision_policy_hash(*, policy: StrategyDecisionPolicy) -> str:
    return _hash(
        {
            "expected_cost": str(policy.expected_cost),
            "expected_return_quantile": str(policy.expected_return_quantile),
            "expected_return_source": policy.expected_return_source.value,
            "max_expected_cost": str(policy.max_expected_cost),
            "max_uncertainty": str(policy.max_uncertainty),
            "min_net_edge": str(policy.min_net_edge),
            "name": policy.name,
            "requirement_ids": policy.requirement_ids,
            "uncertainty_buffer_multiplier": str(policy.uncertainty_buffer_multiplier),
        }
    )


def build_strategy_decision_policy_id(*, policy_hash: str) -> str:
    return _stable_id("STRATEGYPOLICY", {"policy_hash": policy_hash})


def build_strategy_trace_id(
    *, strategy_run_id: str, source_forecast_id: str, policy_hash: str, decision_ts: datetime
) -> str:
    return _stable_id(
        "TRACE",
        {
            "decision_ts": decision_ts.isoformat(),
            "policy_hash": policy_hash,
            "source_forecast_id": source_forecast_id,
            "strategy_run_id": strategy_run_id,
        },
    )


def build_strategy_decision_hash(*, decision: StrategyDecision) -> str:
    return _hash(
        {
            "action": decision.action.value,
            "dataset_row_id": decision.dataset_row_id,
            "dataset_snapshot_id": decision.dataset_snapshot_id,
            "decision_ts": decision.decision_ts.isoformat(),
            "expected_cost": str(decision.expected_cost),
            "expected_return": str(decision.expected_return),
            "feature_input_snapshot_id": decision.feature_input_snapshot_id,
            "feature_ts": decision.feature_ts.isoformat(),
            "feature_vector_id": decision.feature_vector_id,
            "feature_version": decision.feature_version,
            "instrument_id": decision.instrument_id,
            "label_rule_id": decision.label_rule_id,
            "model_version_hash": decision.model_version_hash,
            "model_version_id": decision.model_version_id,
            "net_edge": str(decision.net_edge),
            "policy_hash": decision.policy_hash,
            "policy_id": decision.policy_id,
            "reason_code": decision.reason_code.value,
            "requirement_ids": decision.requirement_ids,
            "sizing": _model_json(decision.sizing),
            "source_feature_snapshot_ids": decision.source_feature_snapshot_ids,
            "source_forecast_id": decision.source_forecast_id,
            "split": decision.split.value,
            "strategy_run_id": decision.strategy_run_id,
            "trace_id": decision.trace_id,
            "training_run_id": decision.training_run_id,
            "uncertainty": str(decision.uncertainty),
            "uncertainty_buffer": str(decision.uncertainty_buffer),
            "venue_id": decision.venue_id,
        }
    )


def build_strategy_decision_id(*, decision_hash: str) -> str:
    return _stable_id("STRATEGYDECISION", {"decision_hash": decision_hash})


def build_strategy_decision_reason_counts(
    *, decisions: tuple[StrategyDecision, ...]
) -> tuple[StrategyDecisionReasonCount, ...]:
    """Build deterministic non-zero reason-code counts from decisions."""

    counts: dict[StrategyDecisionReasonCode, int] = {}
    for decision in decisions:
        counts[decision.reason_code] = counts.get(decision.reason_code, 0) + 1
    return tuple(
        StrategyDecisionReasonCount(reason_code=reason_code, count=counts[reason_code])
        for reason_code in sorted(counts, key=lambda item: item.value)
    )


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())
