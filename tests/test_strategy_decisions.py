"""Evidence for S8-001/S8-002 strategy decision contracts and policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

import ta_model.contracts as public_contracts
import ta_model.strategy as public_strategy
from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.decisions import (
    StrategyDecision,
    StrategyDecisionAction,
    StrategyDecisionPolicy,
    StrategyDecisionReasonCode,
    StrategyRiskApprovalStatus,
    StrategySizingInputs,
    StrategySizingProposal,
    StrategySizingReasonCode,
    StrategySizingStatus,
    build_strategy_decision_hash,
    build_strategy_decision_id,
    make_strategy_decision_policy,
)
from ta_model.contracts.forecasts import (
    CalibrationStatus,
    Forecast,
    ForecastQuantile,
    build_forecast_id,
    build_model_version_hash,
    build_model_version_id,
)
from ta_model.contracts.training import build_training_run_id
from ta_model.strategy.decisions import StrategyDecisionError, decide_expected_net_edge

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"
VENUE_ID = "FIXTURE_SPOT"
FEATURE_VERSION = "s8-decision-fixture-1.0.0"
DATASET_HASH = "a" * 64
TRAINING_HASH = "b" * 64
CANDIDATE_NAME = "s8-forecast-policy-fixture"
TRAINING_RUN_ID = build_training_run_id(training_run_hash=TRAINING_HASH)
MODEL_VERSION_HASH = build_model_version_hash(
    training_run_id=TRAINING_RUN_ID,
    training_run_hash=TRAINING_HASH,
    candidate_name=CANDIDATE_NAME,
)
MODEL_VERSION_ID = build_model_version_id(model_version_hash=MODEL_VERSION_HASH)


def _forecast(
    *,
    median: str = "0.020",
    uncertainty: str = "0.010",
    quantiles: tuple[ForecastQuantile, ...] | None = None,
    split: DatasetSplit = DatasetSplit.VALIDATION,
) -> Forecast:
    median_value = Decimal(median)
    row_id = f"DATASETROW:S8-DECISION:{median}:{uncertainty}:{split.name}"
    forecast_quantiles = quantiles or (
        ForecastQuantile(level=Decimal("0.1"), value=median_value - Decimal("0.010")),
        ForecastQuantile(level=Decimal("0.5"), value=median_value),
        ForecastQuantile(level=Decimal("0.9"), value=median_value + Decimal("0.010")),
    )
    calibration_metadata = {
        "candidate_name": CANDIDATE_NAME,
        "fixture": "s8-decision-policy",
    }
    forecast_id = build_forecast_id(
        dataset_snapshot_id="DATASETSNAPSHOT:S8-DECISION",
        dataset_hash=DATASET_HASH,
        dataset_row_id=row_id,
        split=split,
        training_run_id=TRAINING_RUN_ID,
        training_run_hash=TRAINING_HASH,
        model_version_id=MODEL_VERSION_ID,
        model_version_hash=MODEL_VERSION_HASH,
        probabilities={"negative": Decimal("0.25"), "non_negative": Decimal("0.75")},
        quantiles=forecast_quantiles,
        uncertainty=Decimal(uncertainty),
        calibration_status=CalibrationStatus.SEQUENCE_CONDITIONED_TRAIN_ONLY,
        calibration_metadata=calibration_metadata,
    )
    return Forecast(
        forecast_id=forecast_id,
        dataset_snapshot_id="DATASETSNAPSHOT:S8-DECISION",
        dataset_hash=DATASET_HASH,
        dataset_row_id=row_id,
        feature_vector_id=f"FEATUREVECTOR:S8-DECISION:{median}:{uncertainty}",
        feature_input_snapshot_id="FEATUREINPUT:S8-DECISION",
        feature_version=FEATURE_VERSION,
        source_feature_snapshot_ids=("FEATURESNAPSHOT:S8-DECISION",),
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        feature_ts=START,
        label_rule_id="LABELRULE:FUTURE_1M_RETURN",
        split=split,
        training_run_id=TRAINING_RUN_ID,
        training_run_hash=TRAINING_HASH,
        model_version_id=MODEL_VERSION_ID,
        model_version_hash=MODEL_VERSION_HASH,
        probabilities={"negative": Decimal("0.25"), "non_negative": Decimal("0.75")},
        quantiles=forecast_quantiles,
        uncertainty=Decimal(uncertainty),
        calibration_status=CalibrationStatus.SEQUENCE_CONDITIONED_TRAIN_ONLY,
        calibration_metadata=calibration_metadata,
    )


def _policy(
    *,
    expected_cost: str = "0.002",
    max_expected_cost: str = "0.004",
    max_uncertainty: str = "0.040",
    min_net_edge: str = "0.001",
    uncertainty_buffer_multiplier: str = "0.5",
) -> StrategyDecisionPolicy:
    return make_strategy_decision_policy(
        name="s8-expected-net-edge-fixture",
        expected_cost=Decimal(expected_cost),
        max_expected_cost=Decimal(max_expected_cost),
        max_uncertainty=Decimal(max_uncertainty),
        min_net_edge=Decimal(min_net_edge),
        uncertainty_buffer_multiplier=Decimal(uncertainty_buffer_multiplier),
    )


def _sizing_inputs(
    *,
    risk_budget_notional: str = "10000",
    reference_price: str = "100",
    current_drawdown: str = "0",
    max_drawdown: str = "0.20",
) -> StrategySizingInputs:
    return StrategySizingInputs(
        risk_budget_notional=Decimal(risk_budget_notional),
        reference_price=Decimal(reference_price),
        current_drawdown=Decimal(current_drawdown),
        max_drawdown=Decimal(max_drawdown),
    )


def _decision(
    *,
    median: str = "0.020",
    uncertainty: str = "0.010",
    policy: StrategyDecisionPolicy | None = None,
    strategy_run_id: str = "STRATEGYRUN:S8-DECISION",
    quantiles: tuple[ForecastQuantile, ...] | None = None,
    sizing_inputs: StrategySizingInputs | None = None,
) -> StrategyDecision:
    return decide_expected_net_edge(
        forecast=_forecast(median=median, uncertainty=uncertainty, quantiles=quantiles),
        policy=policy or _policy(),
        strategy_run_id=strategy_run_id,
        decision_ts=START + timedelta(minutes=1),
        sizing_inputs=sizing_inputs,
    )


def test_public_contract_and_strategy_exports_convert_forecast_to_decision() -> None:
    policy = public_contracts.make_strategy_decision_policy(
        name="s8-public-export-fixture",
        expected_cost=Decimal("0.002"),
        max_expected_cost=Decimal("0.004"),
        max_uncertainty=Decimal("0.040"),
        min_net_edge=Decimal("0.001"),
        uncertainty_buffer_multiplier=Decimal("0.5"),
    )

    decision = public_strategy.decide_expected_net_edge(
        forecast=_forecast(),
        policy=policy,
        strategy_run_id="STRATEGYRUN:S8-PUBLIC",
        decision_ts=START + timedelta(minutes=1),
    )

    assert isinstance(decision, public_contracts.StrategyDecision)
    assert public_contracts.StrategyDecisionPolicy is StrategyDecisionPolicy
    assert public_contracts.StrategySizingInputs is StrategySizingInputs
    assert decision.action is public_contracts.StrategyDecisionAction.BUY
    assert public_strategy.propose_pre_risk_size is not None
    assert public_strategy.summarize_decision_reason_codes((decision,))[0].count == 1


def test_trade_decision_contract_is_complete_and_deterministic() -> None:
    decision = _decision()

    assert decision.action is StrategyDecisionAction.BUY
    assert decision.reason_code is StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE
    assert decision.expected_return == Decimal("0.020")
    assert decision.expected_cost == Decimal("0.002")
    assert decision.uncertainty == Decimal("0.010")
    assert decision.uncertainty_buffer == Decimal("0.0050")
    assert decision.net_edge == Decimal("0.0130")
    assert decision.trace_id.startswith("TRACE:")
    assert decision.decision_hash == build_strategy_decision_hash(decision=decision)
    assert decision.decision_id == build_strategy_decision_id(
        decision_hash=decision.decision_hash
    )
    assert decision.sizing.proposed_notional == 0
    assert decision.sizing.risk_approval_id is None
    assert decision.requirement_ids == ("FR-009", "FR-015")


def test_no_trade_decision_contract_remains_represented_and_evaluable() -> None:
    decision = _decision(median="0.003")

    assert decision.action is StrategyDecisionAction.NO_TRADE
    assert decision.reason_code is StrategyDecisionReasonCode.INSUFFICIENT_NET_EDGE
    assert decision.expected_return == Decimal("0.003")
    assert decision.net_edge == Decimal("-0.0040")
    assert decision.source_forecast_id.startswith("FORECAST:")
    assert decision.sizing.proposed_notional == 0
    assert decision.sizing.proposed_quantity == 0


def test_missing_invalid_or_inconsistent_reason_codes_are_rejected() -> None:
    decision = _decision()
    missing_reason_payload = decision.model_dump()
    missing_reason_payload.pop("reason_code")

    with pytest.raises(ValidationError):
        StrategyDecision(**missing_reason_payload)

    with pytest.raises(ValidationError):
        StrategyDecision(**(decision.model_dump() | {"reason_code": "not_a_reason"}))

    malformed = StrategyDecision.model_construct(
        **decision.model_dump(exclude={"decision_id", "decision_hash", "reason_code", "sizing"}),
        decision_id="STRATEGYDECISION:MALFORMED",
        decision_hash="0" * 64,
        reason_code=StrategyDecisionReasonCode.INSUFFICIENT_NET_EDGE,
        sizing=decision.sizing,
    )
    malformed_hash = build_strategy_decision_hash(decision=malformed)
    with pytest.raises(ValidationError, match="buy decisions require"):
        StrategyDecision(
            **malformed.model_dump(exclude={"decision_id", "decision_hash"}),
            decision_id=build_strategy_decision_id(decision_hash=malformed_hash),
            decision_hash=malformed_hash,
        )


def test_decision_identity_changes_when_economics_or_trace_changes() -> None:
    baseline = _decision()
    changed_economics = _decision(policy=_policy(expected_cost="0.003"))
    changed_trace = _decision(strategy_run_id="STRATEGYRUN:S8-DECISION-ALT")

    assert baseline.decision_id != changed_economics.decision_id
    assert baseline.decision_hash != changed_economics.decision_hash
    assert baseline.trace_id != changed_trace.trace_id
    assert baseline.decision_id != changed_trace.decision_id


def test_train_split_forecasts_are_not_accepted_by_strategy_policy() -> None:
    forecast = _forecast()
    train_forecast = Forecast.model_construct(
        **(forecast.model_dump() | {"split": DatasetSplit.TRAIN})
    )

    with pytest.raises(StrategyDecisionError, match="out-of-sample"):
        decide_expected_net_edge(
            forecast=train_forecast,
            policy=_policy(),
            strategy_run_id="STRATEGYRUN:S8-TRAIN-BLOCK",
            decision_ts=START + timedelta(minutes=1),
        )


def test_positive_expected_net_edge_creates_trade_action() -> None:
    decision = _decision(median="0.050", uncertainty="0.010")

    assert decision.action is StrategyDecisionAction.BUY
    assert decision.reason_code is StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE
    assert decision.net_edge == Decimal("0.0430")


def test_explicit_risk_budget_inputs_create_positive_pre_risk_size() -> None:
    decision = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=_policy(expected_cost="0", max_expected_cost="0.004"),
        sizing_inputs=_sizing_inputs(),
    )

    assert decision.action is StrategyDecisionAction.BUY
    assert decision.sizing.sizing_status is StrategySizingStatus.PROPOSED_PENDING_INDEPENDENT_RISK
    assert decision.sizing.proposed_notional == Decimal("10000")
    assert decision.sizing.proposed_quantity == Decimal("100")
    assert decision.sizing.pre_risk_multiplier == Decimal("1")
    assert decision.sizing.sizing_reason_codes == (
        StrategySizingReasonCode.POSITIVE_PRE_RISK_SIZE,
    )
    assert decision.sizing.risk_approval_status is StrategyRiskApprovalStatus.NOT_EVALUATED
    assert decision.sizing.approved_notional is None
    assert decision.sizing.approved_quantity is None
    assert decision.sizing.risk_approval_id is None
    assert "FR-010" in decision.requirement_ids


def test_zero_cost_or_uncertainty_threshold_allows_zero_value_trade() -> None:
    zero_cost_threshold = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=_policy(expected_cost="0", max_expected_cost="0"),
        sizing_inputs=_sizing_inputs(),
    )
    zero_uncertainty_threshold = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=_policy(expected_cost="0", max_expected_cost="0.004", max_uncertainty="0"),
        sizing_inputs=_sizing_inputs(),
    )

    assert zero_cost_threshold.action is StrategyDecisionAction.BUY
    assert zero_cost_threshold.reason_code is StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE
    assert zero_cost_threshold.sizing.proposed_notional == Decimal("10000")
    assert zero_cost_threshold.sizing.sizing_status is (
        StrategySizingStatus.PROPOSED_PENDING_INDEPENDENT_RISK
    )
    assert zero_uncertainty_threshold.action is StrategyDecisionAction.BUY
    assert zero_uncertainty_threshold.reason_code is (
        StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE
    )
    assert zero_uncertainty_threshold.sizing.proposed_notional == Decimal("10000")
    assert zero_uncertainty_threshold.sizing.sizing_status is (
        StrategySizingStatus.PROPOSED_PENDING_INDEPENDENT_RISK
    )


def test_uncertainty_reduces_pre_risk_size_without_risk_approval() -> None:
    policy = _policy(expected_cost="0", max_expected_cost="0.004", max_uncertainty="0.040")
    low_uncertainty = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=policy,
        sizing_inputs=_sizing_inputs(),
    )
    high_uncertainty = _decision(
        median="0.050",
        uncertainty="0.020",
        policy=policy,
        sizing_inputs=_sizing_inputs(),
    )
    blocked_uncertainty = _decision(
        median="0.100",
        uncertainty="0.050",
        policy=policy,
        sizing_inputs=_sizing_inputs(),
    )
    threshold_uncertainty = _decision(
        median="0.100",
        uncertainty="0.040",
        policy=policy,
        sizing_inputs=_sizing_inputs(),
    )

    assert high_uncertainty.action is StrategyDecisionAction.BUY
    assert low_uncertainty.sizing.proposed_notional == Decimal("10000")
    assert high_uncertainty.sizing.pre_risk_multiplier == Decimal("0.5")
    assert high_uncertainty.sizing.proposed_notional == Decimal("5000.0")
    assert high_uncertainty.sizing.proposed_notional < low_uncertainty.sizing.proposed_notional
    assert (
        StrategySizingReasonCode.UNCERTAINTY_REDUCTION
        in high_uncertainty.sizing.sizing_reason_codes
    )
    assert high_uncertainty.sizing.risk_approval_id is None
    assert blocked_uncertainty.action is StrategyDecisionAction.NO_TRADE
    assert blocked_uncertainty.reason_code is StrategyDecisionReasonCode.UNCERTAINTY_THRESHOLD
    assert blocked_uncertainty.sizing.proposed_notional == 0
    assert blocked_uncertainty.sizing.proposed_quantity == 0
    assert blocked_uncertainty.sizing.sizing_reason_codes == (
        StrategySizingReasonCode.UNCERTAINTY_BLOCK,
    )
    assert threshold_uncertainty.action is StrategyDecisionAction.NO_TRADE
    assert threshold_uncertainty.reason_code is StrategyDecisionReasonCode.UNCERTAINTY_THRESHOLD
    assert threshold_uncertainty.sizing.proposed_notional == 0
    assert threshold_uncertainty.sizing.proposed_quantity == 0
    assert threshold_uncertainty.sizing.sizing_reason_codes == (
        StrategySizingReasonCode.UNCERTAINTY_BLOCK,
    )


def test_cost_reduces_or_blocks_pre_risk_size() -> None:
    base = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=_policy(expected_cost="0", max_expected_cost="0.004"),
        sizing_inputs=_sizing_inputs(),
    )
    reduced = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=_policy(expected_cost="0.002", max_expected_cost="0.004"),
        sizing_inputs=_sizing_inputs(),
    )
    blocked = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=_policy(expected_cost="0.010", max_expected_cost="0.004"),
        sizing_inputs=_sizing_inputs(),
    )
    threshold = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=_policy(expected_cost="0.004", max_expected_cost="0.004"),
        sizing_inputs=_sizing_inputs(),
    )

    assert reduced.sizing.proposed_notional == Decimal("5000.0")
    assert reduced.sizing.proposed_notional < base.sizing.proposed_notional
    assert StrategySizingReasonCode.COST_REDUCTION in reduced.sizing.sizing_reason_codes
    assert blocked.action is StrategyDecisionAction.NO_TRADE
    assert blocked.reason_code is StrategyDecisionReasonCode.COST_THRESHOLD
    assert blocked.sizing.sizing_status is StrategySizingStatus.BLOCKED_BEFORE_INDEPENDENT_RISK
    assert blocked.sizing.proposed_notional == 0
    assert blocked.sizing.proposed_quantity == 0
    assert blocked.sizing.sizing_reason_codes == (StrategySizingReasonCode.COST_BLOCK,)
    assert threshold.action is StrategyDecisionAction.NO_TRADE
    assert threshold.reason_code is StrategyDecisionReasonCode.COST_THRESHOLD
    assert threshold.sizing.proposed_notional == 0
    assert threshold.sizing.proposed_quantity == 0
    assert threshold.sizing.sizing_reason_codes == (StrategySizingReasonCode.COST_BLOCK,)


def test_drawdown_reduces_or_blocks_pre_risk_size() -> None:
    policy = _policy(expected_cost="0", max_expected_cost="0.004", max_uncertainty="0.040")
    base = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=policy,
        sizing_inputs=_sizing_inputs(),
    )
    reduced = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=policy,
        sizing_inputs=_sizing_inputs(current_drawdown="0.10", max_drawdown="0.20"),
    )
    blocked = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=policy,
        sizing_inputs=_sizing_inputs(current_drawdown="0.20", max_drawdown="0.20"),
    )

    assert reduced.action is StrategyDecisionAction.BUY
    assert reduced.sizing.pre_risk_multiplier == Decimal("0.5")
    assert reduced.sizing.proposed_notional == Decimal("5000.0")
    assert reduced.sizing.proposed_notional < base.sizing.proposed_notional
    assert StrategySizingReasonCode.DRAWDOWN_REDUCTION in reduced.sizing.sizing_reason_codes
    assert blocked.action is StrategyDecisionAction.NO_TRADE
    assert blocked.reason_code is StrategyDecisionReasonCode.DRAWDOWN_THRESHOLD
    assert blocked.sizing.sizing_status is StrategySizingStatus.BLOCKED_BEFORE_INDEPENDENT_RISK
    assert blocked.sizing.proposed_notional == 0
    assert blocked.sizing.proposed_quantity == 0
    assert blocked.sizing.sizing_reason_codes == (StrategySizingReasonCode.DRAWDOWN_BLOCK,)


def test_no_trade_and_blocked_decisions_keep_proposed_size_zero() -> None:
    insufficient_edge = _decision(median="0.003", sizing_inputs=_sizing_inputs())
    cost_block = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=_policy(expected_cost="0.010", max_expected_cost="0.004"),
        sizing_inputs=_sizing_inputs(),
    )
    drawdown_block = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=_policy(expected_cost="0", max_expected_cost="0.004"),
        sizing_inputs=_sizing_inputs(current_drawdown="0.25", max_drawdown="0.20"),
    )

    for decision in (insufficient_edge, cost_block, drawdown_block):
        assert decision.action is StrategyDecisionAction.NO_TRADE
        assert decision.sizing.proposed_notional == 0
        assert decision.sizing.proposed_quantity == 0
        assert decision.sizing.risk_approval_status is StrategyRiskApprovalStatus.NOT_EVALUATED
        assert decision.sizing.risk_approval_id is None


def test_sizing_proposal_rejects_risk_approval_fields() -> None:
    with pytest.raises(ValidationError, match="must not carry independent risk approval"):
        StrategySizingProposal(approved_notional=Decimal("1"))

    with pytest.raises(ValidationError, match="must not carry independent risk approval"):
        StrategySizingProposal(approved_quantity=Decimal("1"))

    with pytest.raises(ValidationError, match="must not carry independent risk approval"):
        StrategySizingProposal(risk_approval_id="RISKAPPROVAL:S8-SHOULD-NOT-EXIST")


def test_buy_decision_with_explicit_sizing_inputs_rejects_zero_proposed_size() -> None:
    decision = _decision(
        median="0.050",
        uncertainty="0.000",
        policy=_policy(expected_cost="0", max_expected_cost="0.004"),
        sizing_inputs=_sizing_inputs(),
    )
    zero_size = StrategySizingProposal(
        sizing_status=StrategySizingStatus.BLOCKED_BEFORE_INDEPENDENT_RISK,
        sizing_inputs=_sizing_inputs(),
        sizing_reason_codes=(StrategySizingReasonCode.COST_BLOCK,),
        pre_risk_multiplier=Decimal("0"),
        proposed_notional=Decimal("0"),
        proposed_quantity=Decimal("0"),
    )
    malformed = StrategyDecision.model_construct(
        **decision.model_dump(exclude={"decision_id", "decision_hash", "sizing"}),
        decision_id="STRATEGYDECISION:MALFORMED-ZERO-SIZE",
        decision_hash="0" * 64,
        sizing=zero_size,
    )
    malformed_hash = build_strategy_decision_hash(decision=malformed)

    with pytest.raises(ValidationError, match="positive proposed size"):
        StrategyDecision(
            **malformed.model_dump(exclude={"decision_id", "decision_hash"}),
            decision_id=build_strategy_decision_id(decision_hash=malformed_hash),
            decision_hash=malformed_hash,
        )


def test_cost_uncertainty_nonpositive_and_insufficient_edge_create_no_trade() -> None:
    cost_threshold = _decision(
        median="0.050",
        policy=_policy(expected_cost="0.010", max_expected_cost="0.004"),
    )
    uncertainty_threshold = _decision(
        median="0.100",
        uncertainty="0.050",
        policy=_policy(expected_cost="0.001", max_expected_cost="0.004", max_uncertainty="0.040"),
    )
    nonpositive = _decision(median="0.000")
    insufficient_edge = _decision(
        median="0.008",
        uncertainty="0.002",
        policy=_policy(min_net_edge="0.005"),
    )

    assert cost_threshold.action is StrategyDecisionAction.NO_TRADE
    assert cost_threshold.reason_code is StrategyDecisionReasonCode.COST_THRESHOLD
    assert uncertainty_threshold.reason_code is StrategyDecisionReasonCode.UNCERTAINTY_THRESHOLD
    assert nonpositive.reason_code is StrategyDecisionReasonCode.NON_POSITIVE_EXPECTED_RETURN
    assert insufficient_edge.reason_code is StrategyDecisionReasonCode.INSUFFICIENT_NET_EDGE


def test_unsupported_forecast_without_policy_quantile_is_no_trade() -> None:
    decision = _decision(
        quantiles=(
            ForecastQuantile(level=Decimal("0.25"), value=Decimal("0.010")),
            ForecastQuantile(level=Decimal("0.75"), value=Decimal("0.020")),
        )
    )

    assert decision.action is StrategyDecisionAction.NO_TRADE
    assert decision.reason_code is StrategyDecisionReasonCode.UNSUPPORTED_FORECAST
    assert decision.expected_return == 0


def test_reason_code_distribution_is_built_from_real_decision_objects() -> None:
    decisions = (
        _decision(median="0.050"),
        _decision(median="0.003"),
        _decision(median="0.000"),
        _decision(
            median="0.050",
            policy=_policy(expected_cost="0.010", max_expected_cost="0.004"),
        ),
    )

    summary = public_strategy.summarize_decision_reason_codes(decisions)

    assert all(isinstance(decision, StrategyDecision) for decision in decisions)
    assert {item.reason_code: item.count for item in summary} == {
        StrategyDecisionReasonCode.COST_THRESHOLD: 1,
        StrategyDecisionReasonCode.INSUFFICIENT_NET_EDGE: 1,
        StrategyDecisionReasonCode.NON_POSITIVE_EXPECTED_RETURN: 1,
        StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE: 1,
    }
