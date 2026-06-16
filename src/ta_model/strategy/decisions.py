"""Expected net-edge strategy policy for S8 forecast decisions.

Traceability:
- FR-009: converts S7 Forecast objects into trade/no-trade StrategyDecision
  objects with expected return, expected cost, net edge, uncertainty, and reason.
- FR-010: applies deterministic pre-risk sizing inputs without approving risk.
- FR-015/NFR-004: preserves forecast lineage and deterministic trace IDs for audit
  and later replay.

Scope:
- Produces decisions and pre-risk sizing proposals only. It does not approve risk,
  submit/simulate orders, route to gateways, or introduce live-capital behavior.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.decisions import (
    ExpectedReturnSource,
    StrategyDecision,
    StrategyDecisionAction,
    StrategyDecisionPolicy,
    StrategyDecisionReasonCode,
    StrategyDecisionReasonCount,
    StrategySizingInputs,
    StrategySizingProposal,
    StrategySizingReasonCode,
    StrategySizingStatus,
    build_strategy_decision_hash,
    build_strategy_decision_id,
    build_strategy_decision_reason_counts,
    build_strategy_trace_id,
)
from ta_model.contracts.forecasts import Forecast


class StrategyDecisionError(ValueError):
    """Raised when a forecast cannot enter the S8 strategy decision policy."""


def decide_expected_net_edge(
    *,
    forecast: Forecast,
    policy: StrategyDecisionPolicy,
    strategy_run_id: str,
    decision_ts: datetime,
    sizing_inputs: StrategySizingInputs | None = None,
) -> StrategyDecision:
    """Convert one S7 Forecast into an auditable S8 trade/no-trade decision.

    Expected net edge is computed as:
    ``expected_return - expected_cost - uncertainty_buffer`` where
    ``uncertainty_buffer = forecast.uncertainty * policy.uncertainty_buffer_multiplier``.
    """

    if forecast.split is DatasetSplit.TRAIN:
        raise StrategyDecisionError("strategy decisions require out-of-sample forecasts")

    extracted_expected_return = _expected_return_from_forecast(forecast=forecast, policy=policy)
    unsupported_forecast = extracted_expected_return is None
    expected_return = (
        extracted_expected_return if extracted_expected_return is not None else Decimal("0")
    )
    expected_cost = policy.expected_cost
    uncertainty = forecast.uncertainty
    uncertainty_buffer = uncertainty * policy.uncertainty_buffer_multiplier
    net_edge = expected_return - expected_cost - uncertainty_buffer
    action, reason_code = _classify_decision(
        expected_return=expected_return,
        expected_cost=expected_cost,
        uncertainty=uncertainty,
        net_edge=net_edge,
        policy=policy,
        unsupported_forecast=unsupported_forecast,
    )
    if _drawdown_blocks_size(action=action, sizing_inputs=sizing_inputs):
        action = StrategyDecisionAction.NO_TRADE
        reason_code = StrategyDecisionReasonCode.DRAWDOWN_THRESHOLD
    sizing = propose_pre_risk_size(
        action=action,
        reason_code=reason_code,
        expected_cost=expected_cost,
        uncertainty=uncertainty,
        policy=policy,
        sizing_inputs=sizing_inputs,
    )
    trace_id = build_strategy_trace_id(
        strategy_run_id=strategy_run_id,
        source_forecast_id=forecast.forecast_id,
        policy_hash=policy.policy_hash,
        decision_ts=decision_ts,
    )
    draft = StrategyDecision.model_construct(
        decision_id="STRATEGYDECISION:PLACEHOLDER",
        decision_hash="0" * 64,
        trace_id=trace_id,
        strategy_run_id=strategy_run_id,
        policy_id=policy.policy_id,
        policy_hash=policy.policy_hash,
        source_forecast_id=forecast.forecast_id,
        dataset_snapshot_id=forecast.dataset_snapshot_id,
        dataset_row_id=forecast.dataset_row_id,
        feature_vector_id=forecast.feature_vector_id,
        feature_input_snapshot_id=forecast.feature_input_snapshot_id,
        feature_version=forecast.feature_version,
        source_feature_snapshot_ids=forecast.source_feature_snapshot_ids,
        instrument_id=forecast.instrument_id,
        venue_id=forecast.venue_id,
        feature_ts=forecast.feature_ts,
        decision_ts=decision_ts,
        label_rule_id=forecast.label_rule_id,
        split=forecast.split,
        training_run_id=forecast.training_run_id,
        model_version_id=forecast.model_version_id,
        model_version_hash=forecast.model_version_hash,
        action=action,
        expected_return=expected_return,
        expected_cost=expected_cost,
        uncertainty=uncertainty,
        uncertainty_buffer=uncertainty_buffer,
        net_edge=net_edge,
        reason_code=reason_code,
        sizing=sizing,
        requirement_ids=_decision_requirement_ids(policy=policy, sizing_inputs=sizing_inputs),
    )
    decision_hash = build_strategy_decision_hash(decision=draft)
    return StrategyDecision(
        **draft.model_dump(exclude={"decision_id", "decision_hash"}),
        decision_id=build_strategy_decision_id(decision_hash=decision_hash),
        decision_hash=decision_hash,
    )


def propose_pre_risk_size(
    *,
    action: StrategyDecisionAction,
    reason_code: StrategyDecisionReasonCode,
    expected_cost: Decimal,
    uncertainty: Decimal,
    policy: StrategyDecisionPolicy,
    sizing_inputs: StrategySizingInputs | None,
) -> StrategySizingProposal:
    """Build a deterministic S8 pre-risk size without independent approval.

    The base budget is reduced by cost, uncertainty, and drawdown multipliers.
    A zero output is a blocked proposal, not a risk-approved order.
    """

    if sizing_inputs is None:
        return StrategySizingProposal()
    if action is StrategyDecisionAction.NO_TRADE:
        return StrategySizingProposal(
            sizing_status=StrategySizingStatus.BLOCKED_BEFORE_INDEPENDENT_RISK,
            sizing_inputs=sizing_inputs,
            sizing_reason_codes=(_sizing_block_reason(reason_code),),
            pre_risk_multiplier=Decimal("0"),
            proposed_notional=Decimal("0"),
            proposed_quantity=Decimal("0"),
        )
    if sizing_inputs.risk_budget_notional == 0:
        return StrategySizingProposal(
            sizing_status=StrategySizingStatus.BLOCKED_BEFORE_INDEPENDENT_RISK,
            sizing_inputs=sizing_inputs,
            sizing_reason_codes=(StrategySizingReasonCode.ZERO_RISK_BUDGET,),
            pre_risk_multiplier=Decimal("0"),
            proposed_notional=Decimal("0"),
            proposed_quantity=Decimal("0"),
        )

    cost_multiplier = _threshold_multiplier(
        value=expected_cost, threshold=policy.max_expected_cost
    )
    uncertainty_multiplier = _threshold_multiplier(
        value=uncertainty, threshold=policy.max_uncertainty
    )
    drawdown_multiplier = _threshold_multiplier(
        value=sizing_inputs.current_drawdown, threshold=sizing_inputs.max_drawdown
    )
    pre_risk_multiplier = cost_multiplier * uncertainty_multiplier * drawdown_multiplier
    reason_codes = _sizing_reduction_reasons(
        expected_cost=expected_cost,
        cost_multiplier=cost_multiplier,
        uncertainty=uncertainty,
        uncertainty_multiplier=uncertainty_multiplier,
        current_drawdown=sizing_inputs.current_drawdown,
        drawdown_multiplier=drawdown_multiplier,
    )
    if pre_risk_multiplier == 0:
        return StrategySizingProposal(
            sizing_status=StrategySizingStatus.BLOCKED_BEFORE_INDEPENDENT_RISK,
            sizing_inputs=sizing_inputs,
            sizing_reason_codes=reason_codes,
            pre_risk_multiplier=pre_risk_multiplier,
            proposed_notional=Decimal("0"),
            proposed_quantity=Decimal("0"),
        )

    proposed_notional = sizing_inputs.risk_budget_notional * pre_risk_multiplier
    return StrategySizingProposal(
        sizing_status=StrategySizingStatus.PROPOSED_PENDING_INDEPENDENT_RISK,
        sizing_inputs=sizing_inputs,
        sizing_reason_codes=(*reason_codes, StrategySizingReasonCode.POSITIVE_PRE_RISK_SIZE),
        pre_risk_multiplier=pre_risk_multiplier,
        proposed_notional=proposed_notional,
        proposed_quantity=proposed_notional / sizing_inputs.reference_price,
    )


def summarize_decision_reason_codes(
    decisions: tuple[StrategyDecision, ...]
) -> tuple[StrategyDecisionReasonCount, ...]:
    """Return deterministic reason-code distribution from real decisions."""

    return build_strategy_decision_reason_counts(decisions=decisions)


def _expected_return_from_forecast(
    *, forecast: Forecast, policy: StrategyDecisionPolicy
) -> Decimal | None:
    if policy.expected_return_source is not ExpectedReturnSource.MEDIAN_QUANTILE:
        return None
    matches = tuple(
        quantile.value
        for quantile in forecast.quantiles
        if quantile.level == policy.expected_return_quantile
    )
    if len(matches) != 1:
        return None
    return matches[0]


def _classify_decision(
    *,
    expected_return: Decimal,
    expected_cost: Decimal,
    uncertainty: Decimal,
    net_edge: Decimal,
    policy: StrategyDecisionPolicy,
    unsupported_forecast: bool,
) -> tuple[StrategyDecisionAction, StrategyDecisionReasonCode]:
    if unsupported_forecast:
        return StrategyDecisionAction.NO_TRADE, StrategyDecisionReasonCode.UNSUPPORTED_FORECAST
    if expected_return <= 0:
        return (
            StrategyDecisionAction.NO_TRADE,
            StrategyDecisionReasonCode.NON_POSITIVE_EXPECTED_RETURN,
        )
    if _breaches_threshold(value=expected_cost, threshold=policy.max_expected_cost):
        return StrategyDecisionAction.NO_TRADE, StrategyDecisionReasonCode.COST_THRESHOLD
    if _breaches_threshold(value=uncertainty, threshold=policy.max_uncertainty):
        return StrategyDecisionAction.NO_TRADE, StrategyDecisionReasonCode.UNCERTAINTY_THRESHOLD
    if net_edge <= policy.min_net_edge:
        return StrategyDecisionAction.NO_TRADE, StrategyDecisionReasonCode.INSUFFICIENT_NET_EDGE
    return StrategyDecisionAction.BUY, StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE


def _drawdown_blocks_size(
    *, action: StrategyDecisionAction, sizing_inputs: StrategySizingInputs | None
) -> bool:
    return (
        action is StrategyDecisionAction.BUY
        and sizing_inputs is not None
        and sizing_inputs.current_drawdown >= sizing_inputs.max_drawdown
    )


def _threshold_multiplier(*, value: Decimal, threshold: Decimal) -> Decimal:
    if threshold == 0:
        return Decimal("1") if value == 0 else Decimal("0")
    multiplier = Decimal("1") - (value / threshold)
    if multiplier <= 0:
        return Decimal("0")
    if multiplier >= 1:
        return Decimal("1")
    return multiplier


def _breaches_threshold(*, value: Decimal, threshold: Decimal) -> bool:
    if threshold == 0:
        return value > 0
    return value >= threshold


def _sizing_reduction_reasons(
    *,
    expected_cost: Decimal,
    cost_multiplier: Decimal,
    uncertainty: Decimal,
    uncertainty_multiplier: Decimal,
    current_drawdown: Decimal,
    drawdown_multiplier: Decimal,
) -> tuple[StrategySizingReasonCode, ...]:
    reason_codes: list[StrategySizingReasonCode] = []
    if expected_cost > 0:
        reason_codes.append(
            StrategySizingReasonCode.COST_BLOCK
            if cost_multiplier == 0
            else StrategySizingReasonCode.COST_REDUCTION
        )
    if uncertainty > 0:
        reason_codes.append(
            StrategySizingReasonCode.UNCERTAINTY_BLOCK
            if uncertainty_multiplier == 0
            else StrategySizingReasonCode.UNCERTAINTY_REDUCTION
        )
    if current_drawdown > 0:
        reason_codes.append(
            StrategySizingReasonCode.DRAWDOWN_BLOCK
            if drawdown_multiplier == 0
            else StrategySizingReasonCode.DRAWDOWN_REDUCTION
        )
    return tuple(reason_codes)


def _sizing_block_reason(reason_code: StrategyDecisionReasonCode) -> StrategySizingReasonCode:
    if reason_code is StrategyDecisionReasonCode.COST_THRESHOLD:
        return StrategySizingReasonCode.COST_BLOCK
    if reason_code is StrategyDecisionReasonCode.UNCERTAINTY_THRESHOLD:
        return StrategySizingReasonCode.UNCERTAINTY_BLOCK
    if reason_code is StrategyDecisionReasonCode.DRAWDOWN_THRESHOLD:
        return StrategySizingReasonCode.DRAWDOWN_BLOCK
    return StrategySizingReasonCode.NO_TRADE_ACTION


def _decision_requirement_ids(
    *, policy: StrategyDecisionPolicy, sizing_inputs: StrategySizingInputs | None
) -> tuple[str, ...]:
    if sizing_inputs is None:
        return tuple(str(requirement_id) for requirement_id in policy.requirement_ids)
    requirement_ids = (*policy.requirement_ids, *sizing_inputs.requirement_ids)
    return tuple(dict.fromkeys(str(requirement_id) for requirement_id in requirement_ids))
