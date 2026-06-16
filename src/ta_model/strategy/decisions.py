"""Expected net-edge strategy policy for S8 forecast decisions.

Traceability:
- FR-009: converts S7 Forecast objects into trade/no-trade StrategyDecision
  objects with expected return, expected cost, net edge, uncertainty, and reason.
- FR-015/NFR-004: preserves forecast lineage and deterministic trace IDs for audit
  and later replay.

Scope:
- Produces decisions only. It does not size beyond placeholders, approve risk,
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
    StrategySizingProposal,
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
        sizing=StrategySizingProposal(),
        requirement_ids=("FR-009", "FR-015"),
    )
    decision_hash = build_strategy_decision_hash(decision=draft)
    return StrategyDecision(
        **draft.model_dump(exclude={"decision_id", "decision_hash"}),
        decision_id=build_strategy_decision_id(decision_hash=decision_hash),
        decision_hash=decision_hash,
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
    if expected_cost > policy.max_expected_cost:
        return StrategyDecisionAction.NO_TRADE, StrategyDecisionReasonCode.COST_THRESHOLD
    if uncertainty > policy.max_uncertainty:
        return StrategyDecisionAction.NO_TRADE, StrategyDecisionReasonCode.UNCERTAINTY_THRESHOLD
    if net_edge <= policy.min_net_edge:
        return StrategyDecisionAction.NO_TRADE, StrategyDecisionReasonCode.INSUFFICIENT_NET_EDGE
    return StrategyDecisionAction.BUY, StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE
