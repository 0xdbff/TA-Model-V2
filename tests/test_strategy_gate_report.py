"""Evidence for S8-004 strategy gate report from real decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.decisions import (
    StrategyDecision,
    StrategyDecisionAction,
    StrategyDecisionPolicy,
    StrategyDecisionReasonCode,
    StrategyRiskApprovalStatus,
    StrategySizingInputs,
    make_strategy_decision_policy,
)
from ta_model.contracts.evaluation import (
    StrategyGateUtilityObservation,
    build_strategy_gate_report_hash,
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
from ta_model.evaluation import build_strategy_gate_report
from ta_model.evaluation.strategy_gate import StrategyGateReportBuildError
from ta_model.strategy.decisions import decide_expected_net_edge

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"
VENUE_ID = "FIXTURE_SPOT"
FEATURE_VERSION = "s8-strategy-gate-fixture-1.0.0"
DATASET_HASH = "c" * 64
TRAINING_HASH = "d" * 64
CANDIDATE_NAME = "s8-strategy-gate-fixture"
TRAINING_RUN_ID = build_training_run_id(training_run_hash=TRAINING_HASH)
MODEL_VERSION_HASH = build_model_version_hash(
    training_run_id=TRAINING_RUN_ID,
    training_run_hash=TRAINING_HASH,
    candidate_name=CANDIDATE_NAME,
)
MODEL_VERSION_ID = build_model_version_id(model_version_hash=MODEL_VERSION_HASH)


def _forecast(*, median: str, uncertainty: str = "0.000") -> Forecast:
    median_value = Decimal(median)
    row_id = f"DATASETROW:S8-GATE:{median}:{uncertainty}"
    quantiles = (
        ForecastQuantile(level=Decimal("0.1"), value=median_value - Decimal("0.010")),
        ForecastQuantile(level=Decimal("0.5"), value=median_value),
        ForecastQuantile(level=Decimal("0.9"), value=median_value + Decimal("0.010")),
    )
    calibration_metadata = {"candidate_name": CANDIDATE_NAME, "fixture": "s8-gate"}
    forecast_id = build_forecast_id(
        dataset_snapshot_id="DATASETSNAPSHOT:S8-GATE",
        dataset_hash=DATASET_HASH,
        dataset_row_id=row_id,
        split=DatasetSplit.VALIDATION,
        training_run_id=TRAINING_RUN_ID,
        training_run_hash=TRAINING_HASH,
        model_version_id=MODEL_VERSION_ID,
        model_version_hash=MODEL_VERSION_HASH,
        probabilities={"negative": Decimal("0.25"), "non_negative": Decimal("0.75")},
        quantiles=quantiles,
        uncertainty=Decimal(uncertainty),
        calibration_status=CalibrationStatus.SEQUENCE_CONDITIONED_TRAIN_ONLY,
        calibration_metadata=calibration_metadata,
    )
    return Forecast(
        forecast_id=forecast_id,
        dataset_snapshot_id="DATASETSNAPSHOT:S8-GATE",
        dataset_hash=DATASET_HASH,
        dataset_row_id=row_id,
        feature_vector_id=f"FEATUREVECTOR:S8-GATE:{median}:{uncertainty}",
        feature_input_snapshot_id="FEATUREINPUT:S8-GATE",
        feature_version=FEATURE_VERSION,
        source_feature_snapshot_ids=("FEATURESNAPSHOT:S8-GATE",),
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        feature_ts=START,
        label_rule_id="LABELRULE:FUTURE_1M_RETURN",
        split=DatasetSplit.VALIDATION,
        training_run_id=TRAINING_RUN_ID,
        training_run_hash=TRAINING_HASH,
        model_version_id=MODEL_VERSION_ID,
        model_version_hash=MODEL_VERSION_HASH,
        probabilities={"negative": Decimal("0.25"), "non_negative": Decimal("0.75")},
        quantiles=quantiles,
        uncertainty=Decimal(uncertainty),
        calibration_status=CalibrationStatus.SEQUENCE_CONDITIONED_TRAIN_ONLY,
        calibration_metadata=calibration_metadata,
    )


def _policy(*, expected_cost: str = "0.002") -> StrategyDecisionPolicy:
    return make_strategy_decision_policy(
        name=f"s8-strategy-gate-{expected_cost}",
        expected_cost=Decimal(expected_cost),
        max_expected_cost=Decimal("0.004"),
        max_uncertainty=Decimal("0.040"),
        min_net_edge=Decimal("0.001"),
        uncertainty_buffer_multiplier=Decimal("0"),
    )


def _sizing_inputs() -> StrategySizingInputs:
    return StrategySizingInputs(
        risk_budget_notional=Decimal("10000"),
        reference_price=Decimal("100"),
        max_drawdown=Decimal("0.20"),
    )


def _decision(
    *, median: str, expected_cost: str = "0.002", strategy_run_suffix: str
) -> StrategyDecision:
    return decide_expected_net_edge(
        forecast=_forecast(median=median),
        policy=_policy(expected_cost=expected_cost),
        strategy_run_id=f"STRATEGYRUN:S8-GATE:{strategy_run_suffix}",
        decision_ts=START + timedelta(minutes=1),
        sizing_inputs=_sizing_inputs(),
    )


def _fixture_decisions() -> tuple[StrategyDecision, ...]:
    return (
        _decision(median="0.050", strategy_run_suffix="TAKEN-A"),
        _decision(median="0.040", strategy_run_suffix="TAKEN-B"),
        _decision(median="0.003", strategy_run_suffix="SKIPPED-EDGE"),
        _decision(median="0.050", expected_cost="0.010", strategy_run_suffix="SKIPPED-COST"),
    )


def _utility_observations(
    decisions: tuple[StrategyDecision, ...]
) -> tuple[StrategyGateUtilityObservation, ...]:
    realized_by_suffix = {
        "TAKEN-A": Decimal("0.040"),
        "TAKEN-B": Decimal("0.030"),
        "SKIPPED-EDGE": Decimal("0.000"),
        "SKIPPED-COST": Decimal("0.005"),
    }
    observations: list[StrategyGateUtilityObservation] = []
    for decision in decisions:
        suffix = decision.strategy_run_id.rsplit(":", maxsplit=1)[-1]
        observations.append(
            StrategyGateUtilityObservation(
                decision_id=decision.decision_id,
                realized_return=realized_by_suffix[suffix],
            )
        )
    return tuple(observations)


def test_strategy_gate_report_evaluates_real_decisions_and_reason_distribution() -> None:
    decisions = _fixture_decisions()

    report = build_strategy_gate_report(
        decisions, utility_observations=_utility_observations(decisions)
    )

    assert all(isinstance(decision, StrategyDecision) for decision in decisions)
    assert report.report_id.startswith("STRATEGYGATE:")
    assert report.report_hash == build_strategy_gate_report_hash(report=report)
    assert report.observation_count == 4
    assert report.taken_count == 2
    assert report.skipped_count == 2
    assert report.taken_mean_utility == Decimal("0.033")
    assert report.skipped_mean_opportunity_utility == Decimal("-0.0035")
    assert report.skipped_vs_taken_mean_utility == Decimal("-0.0365")
    assert report.turnover_proxy_notional == Decimal("10000.0")
    assert report.cost_drag_notional == Decimal("20.0000")
    assert {item.reason_code: item.count for item in report.reason_counts} == {
        StrategyDecisionReasonCode.COST_THRESHOLD: 1,
        StrategyDecisionReasonCode.INSUFFICIENT_NET_EDGE: 1,
        StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE: 2,
    }


def test_strategy_gate_report_id_and_hash_are_deterministic_for_same_inputs() -> None:
    decisions = _fixture_decisions()
    observations = _utility_observations(decisions)

    first = build_strategy_gate_report(decisions, utility_observations=observations)
    second = build_strategy_gate_report(
        tuple(reversed(decisions)), utility_observations=observations
    )

    assert first.report_id == second.report_id
    assert first.report_hash == second.report_hash
    assert first.input_decision_ids == second.input_decision_ids


def test_strategy_gate_report_makes_no_risk_or_promotion_claim() -> None:
    decisions = _fixture_decisions()

    report = build_strategy_gate_report(
        decisions, utility_observations=_utility_observations(decisions)
    )

    assert report.requirement_ids == ("FR-009", "FR-014")
    assert "risk_approval" not in report.model_dump_json()
    assert "promotion" not in report.model_dump_json()
    assert all(
        decision.sizing.risk_approval_status is StrategyRiskApprovalStatus.NOT_EVALUATED
        for decision in decisions
    )
    assert all(decision.sizing.risk_approval_id is None for decision in decisions)
    assert all(
        decision.sizing.proposed_notional > 0
        for decision in decisions
        if decision.action is StrategyDecisionAction.BUY
    )


def test_strategy_gate_report_requires_covered_taken_and_skipped_decisions() -> None:
    decisions = _fixture_decisions()

    with pytest.raises(StrategyGateReportBuildError, match="cover every decision"):
        build_strategy_gate_report(
            decisions, utility_observations=_utility_observations(decisions)[:-1]
        )

    taken_only = tuple(
        decision for decision in decisions if decision.action is StrategyDecisionAction.BUY
    )
    with pytest.raises(StrategyGateReportBuildError, match="taken and one skipped"):
        build_strategy_gate_report(
            taken_only, utility_observations=_utility_observations(taken_only)
        )
