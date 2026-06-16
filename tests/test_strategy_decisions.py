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


def _decision(
    *,
    median: str = "0.020",
    uncertainty: str = "0.010",
    policy: StrategyDecisionPolicy | None = None,
    strategy_run_id: str = "STRATEGYRUN:S8-DECISION",
    quantiles: tuple[ForecastQuantile, ...] | None = None,
) -> StrategyDecision:
    return decide_expected_net_edge(
        forecast=_forecast(median=median, uncertainty=uncertainty, quantiles=quantiles),
        policy=policy or _policy(),
        strategy_run_id=strategy_run_id,
        decision_ts=START + timedelta(minutes=1),
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
    assert decision.action is public_contracts.StrategyDecisionAction.BUY
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
