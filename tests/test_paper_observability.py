"""S10-004 dashboard smoke and alert-routing evidence tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import ta_model.contracts as public_contracts
import ta_model.observability as public_observability
from risk_test_helpers import (
    INSTRUMENT_ID,
    START,
    VENUE_ID,
    account_state,
    bar,
    default_policy,
    intent,
    load_snapshot,
    risk_request,
)
from ta_model.contracts.datasets import DatasetSplit, build_dataset_snapshot_id
from ta_model.contracts.decisions import (
    StrategyDecisionReasonCode,
    StrategyDecisionReasonCount,
)
from ta_model.contracts.evaluation import (
    StrategyGateReport,
    StrategyGateUtilityObservation,
    build_strategy_gate_report_hash,
    build_strategy_gate_report_id,
)
from ta_model.contracts.execution import ExecutionGatewayReport
from ta_model.contracts.forecasts import build_model_version_id, build_probabilistic_output_id
from ta_model.contracts.model_validation import (
    BaselineEvidenceReference,
    ModelComparison,
    ModelGateRecommendation,
    ModelMetricSet,
    ModelValidationReport,
    QuantileCoverageMetric,
    UncertaintySummary,
    build_model_validation_report_hash,
    build_model_validation_report_id,
)
from ta_model.contracts.observability import (
    PaperReadinessAlertCategory,
    PaperReadinessMetricStatus,
    PaperReadinessObservabilityReport,
    PaperReadinessSignalGroup,
    make_paper_readiness_dashboard_panel,
)
from ta_model.contracts.paper import PaperAccountSessionReport, PaperTcaReport
from ta_model.contracts.risk import KillSwitchState, LossRiskTelemetry, RiskCheckEvent
from ta_model.contracts.simulation import SimulatedAccountState, make_execution_cost_model
from ta_model.contracts.stream_health import (
    DataHealthGate,
    DataHealthSignal,
    StreamHealthEvaluator,
    StreamHealthPolicy,
)
from ta_model.contracts.streaming import QuoteEvent, TradeEvent
from ta_model.contracts.training import build_training_run_id
from ta_model.execution import (
    make_paper_account_session_report,
    make_paper_tca_report,
    run_paper_gateway_replay,
)
from ta_model.observability import (
    METRIC_DATA_STALE_COUNT,
    build_paper_readiness_observability_report,
    load_paper_readiness_alert_rules,
    load_paper_readiness_dashboard_spec,
)
from ta_model.risk.engine import evaluate_pre_trade_risk

CONFIG_ROOT = Path("configs/observability")
DASHBOARD_CONFIG = CONFIG_ROOT / "paper_readiness_dashboard.json"
ALERT_CONFIG = CONFIG_ROOT / "paper_readiness_alerts.json"


def test_public_exports_include_paper_readiness_observability_contracts() -> None:
    assert (
        public_contracts.PaperReadinessObservabilityReport
        is PaperReadinessObservabilityReport
    )
    assert public_contracts.PaperReadinessAlertCategory is PaperReadinessAlertCategory
    assert callable(public_observability.build_paper_readiness_observability_report)
    assert callable(public_observability.load_paper_readiness_dashboard_spec)


def test_committed_dashboard_and_alert_configs_validate_required_groups_and_routes() -> None:
    dashboard = load_paper_readiness_dashboard_spec(DASHBOARD_CONFIG)
    alert_rules = load_paper_readiness_alert_rules(ALERT_CONFIG)

    assert {panel.group for panel in dashboard.panels} == set(PaperReadinessSignalGroup)
    assert all(panel.metric_ids for panel in dashboard.panels)
    assert all(panel.source_contracts for panel in dashboard.panels)
    assert METRIC_DATA_STALE_COUNT in {
        metric_id for panel in dashboard.panels for metric_id in panel.metric_ids
    }
    assert {
        PaperReadinessAlertCategory.DATA_STALE,
        PaperReadinessAlertCategory.EXECUTION_TCA_ERROR,
        PaperReadinessAlertCategory.ORDER_REJECT,
        PaperReadinessAlertCategory.PORTFOLIO_DRAWDOWN,
        PaperReadinessAlertCategory.RISK_KILL_SWITCH,
    }.issubset({rule.category for rule in alert_rules})
    assert all(rule.route.owner for rule in alert_rules)
    for panel in dashboard.panels:
        _assert_repo_local_runbook_link_resolves(panel.runbook_url)
    for rule in alert_rules:
        _assert_repo_local_runbook_link_resolves(rule.route.runbook_url)


def test_dashboard_panels_reject_non_runbook_links() -> None:
    with pytest.raises(ValueError, match="runbook_url"):
        make_paper_readiness_dashboard_panel(
            group=PaperReadinessSignalGroup.DATA_HEALTH,
            title="Invalid paper-readiness panel",
            description="Panel URL must resolve to a runbook path or approved HTTPS URL.",
            metric_ids=("paper.invalid.metric",),
            source_contracts=("DataHealthSignal",),
            runbook_url="file:///tmp/not-a-runbook.md",
        )


def test_healthy_fixture_populates_dashboard_metrics_without_routed_alerts() -> None:
    gateway_report, session_report, tca_report, risk_events = _healthy_paper_reports()

    report = build_paper_readiness_observability_report(
        generated_at=START + timedelta(minutes=5),
        data_health_signals=(_healthy_data_signal(),),
        model_validation_report=_model_validation_report(),
        strategy_gate_report=_strategy_gate_report(),
        paper_account_report=session_report,
        paper_tca_report=tca_report,
        execution_gateway_report=gateway_report,
        risk_events=risk_events,
        dashboard=load_paper_readiness_dashboard_spec(DASHBOARD_CONFIG),
        alert_rules=load_paper_readiness_alert_rules(ALERT_CONFIG),
    )

    assert report.routed_alerts == ()
    assert {metric.group for metric in report.metric_evidence} == set(PaperReadinessSignalGroup)
    assert all(
        metric.status is PaperReadinessMetricStatus.HEALTHY
        for metric in report.metric_evidence
    )
    assert report.source_report_ids
    assert gateway_report.gateway_report_id in report.source_report_ids
    assert session_report.session_report_id in report.source_report_ids
    assert tca_report.tca_report_id in report.source_report_ids
    assert all(metric.source_links for metric in report.metric_evidence)


def test_breached_fixture_routes_required_alerts_with_source_and_runbook_linkage() -> None:
    gateway_report, session_report, tca_report, risk_events = _breached_paper_reports()

    report = build_paper_readiness_observability_report(
        generated_at=START + timedelta(minutes=6),
        data_health_signals=(_stale_data_signal(),),
        model_validation_report=_model_validation_report(),
        strategy_gate_report=_strategy_gate_report(),
        paper_account_report=session_report,
        paper_tca_report=tca_report,
        execution_gateway_report=gateway_report,
        risk_events=risk_events,
        dashboard=load_paper_readiness_dashboard_spec(DASHBOARD_CONFIG),
        alert_rules=load_paper_readiness_alert_rules(ALERT_CONFIG),
    )

    routed_categories = {alert.category for alert in report.routed_alerts}
    assert {
        PaperReadinessAlertCategory.DATA_STALE,
        PaperReadinessAlertCategory.EXECUTION_TCA_ERROR,
        PaperReadinessAlertCategory.ORDER_REJECT,
        PaperReadinessAlertCategory.PORTFOLIO_DRAWDOWN,
        PaperReadinessAlertCategory.RISK_KILL_SWITCH,
    }.issubset(routed_categories)
    assert any(alert.trace_ids for alert in report.routed_alerts)
    for alert in report.routed_alerts:
        assert alert.owner
        assert alert.severity.value in {"warning", "critical"}
        assert alert.current_value > alert.threshold
        assert alert.metric_id
        _assert_repo_local_runbook_link_resolves(alert.runbook_url)
        assert alert.source_ids
        if alert.category is PaperReadinessAlertCategory.DATA_STALE:
            assert any(link.source_event_id for link in alert.source_links)
        else:
            assert alert.run_ids or alert.report_ids
        serialized = alert.model_dump_json().lower()
        assert "secret" not in serialized
        assert "password" not in serialized
        assert "token" not in serialized


def _assert_repo_local_runbook_link_resolves(runbook_url: str) -> None:
    path_text, anchor = runbook_url.split("#", maxsplit=1)

    assert path_text.startswith("docs/runbooks/")
    assert anchor
    path = Path(path_text)
    assert path.is_file()
    heading_anchors = {
        _markdown_anchor(line.lstrip("#").strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("#")
    }
    assert anchor in heading_anchors


def _markdown_anchor(heading: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in heading)
    return "-".join(part for part in normalized.split("-") if part)


def _healthy_paper_reports() -> tuple[
    ExecutionGatewayReport,
    PaperAccountSessionReport,
    PaperTcaReport,
    tuple[RiskCheckEvent, ...],
]:
    approved = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(order_id="ORDER:S10:OBS:OK")),
        policy=default_policy(),
    )
    initial_state = account_state()
    gateway_report = _gateway_report(
        run_id="PAPER:S10:OBS:HEALTHY",
        risk_events=(approved,),
        starting_account_state=initial_state,
    )
    session_report = make_paper_account_session_report(
        gateway_report=gateway_report,
        initial_account_state=initial_state,
    )
    tca_report = make_paper_tca_report(
        gateway_report=gateway_report,
        quotes=(_quote(event_ts=gateway_report.events[0].submitted_at),),
    )
    return gateway_report, session_report, tca_report, (approved,)


def _breached_paper_reports() -> tuple[
    ExecutionGatewayReport,
    PaperAccountSessionReport,
    PaperTcaReport,
    tuple[RiskCheckEvent, ...],
]:
    gateway_rejected = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(order_id="ORDER:S10:OBS:REJECT")),
        policy=default_policy(),
    )
    kill_blocked = evaluate_pre_trade_risk(
        request=risk_request(
            order_intent=intent(order_id="ORDER:S10:OBS:KILL"),
            kill_state=KillSwitchState.PAUSE_NEW_ORDERS,
        ),
        policy=default_policy(),
    )
    drawdown_blocked = evaluate_pre_trade_risk(
        request=risk_request(
            order_intent=intent(order_id="ORDER:S10:OBS:DRAWDOWN"),
            loss_risk=LossRiskTelemetry(max_drawdown_pct=Decimal("0.06")),
        ),
        policy=default_policy(),
    )
    risk_events = (gateway_rejected, kill_blocked, drawdown_blocked)
    initial_state = account_state(usd=Decimal("0"))
    gateway_report = _gateway_report(
        run_id="PAPER:S10:OBS:BREACHED",
        risk_events=risk_events,
        starting_account_state=initial_state,
    )
    session_report = make_paper_account_session_report(
        gateway_report=gateway_report,
        initial_account_state=initial_state,
    )
    tca_report = make_paper_tca_report(gateway_report=gateway_report, quotes=())
    return gateway_report, session_report, tca_report, risk_events


def _gateway_report(
    *,
    run_id: str,
    risk_events: tuple[RiskCheckEvent, ...],
    starting_account_state: SimulatedAccountState,
) -> ExecutionGatewayReport:
    return run_paper_gateway_replay(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=risk_events,
        run_id=run_id,
        execution_cost_model=make_execution_cost_model(
            taker_fee_rate=Decimal("0.001"),
            spread_bps=Decimal("2"),
            slippage_bps=Decimal("3"),
        ),
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=starting_account_state,
    )


def _healthy_data_signal() -> DataHealthSignal:
    record = StreamHealthEvaluator().evaluate(
        _trade(trade_id="TRADE:S10:OBS:OK"),
        evaluation_ts=START,
    )
    return DataHealthGate().evaluate(record)


def _stale_data_signal() -> DataHealthSignal:
    record = StreamHealthEvaluator(StreamHealthPolicy(max_event_age=timedelta(seconds=5))).evaluate(
        _trade(trade_id="TRADE:S10:OBS:STALE"),
        evaluation_ts=START + timedelta(seconds=6),
    )
    return DataHealthGate().evaluate(record)


def _trade(*, trade_id: str) -> TradeEvent:
    return TradeEvent(
        subscription_id="STREAM:S10:OBS",
        source_id="SOURCE:S10:OBS",
        venue_id=VENUE_ID,
        event_ts=START,
        source_ts=START,
        ingest_ts=START + timedelta(milliseconds=2),
        raw_payload_id=f"RAW:{trade_id}",
        trade_id=trade_id,
        instrument_id=INSTRUMENT_ID,
        price=Decimal("100"),
        quantity=Decimal("1"),
        sequence=1,
    )


def _quote(*, event_ts: datetime) -> QuoteEvent:
    return QuoteEvent(
        subscription_id="STREAM:S10:OBS",
        source_id="SOURCE:S10:OBS",
        venue_id=VENUE_ID,
        event_ts=event_ts,
        source_ts=event_ts,
        ingest_ts=event_ts + timedelta(milliseconds=2),
        raw_payload_id="RAW:QUOTE:S10:OBS",
        quote_id="QUOTE:S10:OBS:ARRIVAL",
        instrument_id=INSTRUMENT_ID,
        best_bid=Decimal("99.98"),
        best_ask=Decimal("100.02"),
    )


def _model_validation_report() -> ModelValidationReport:
    dataset_hash = "a" * 64
    training_hash = "b" * 64
    model_hash = "c" * 64
    forecast_hash = "d" * 64
    dataset_id = build_dataset_snapshot_id(dataset_hash=dataset_hash)
    training_run_id = build_training_run_id(training_run_hash=training_hash)
    model_version_id = build_model_version_id(model_version_hash=model_hash)
    forecast_output_id = build_probabilistic_output_id(output_hash=forecast_hash)
    candidate_metrics = ModelMetricSet(
        observation_count=12,
        nll=Decimal("0.40"),
        brier=Decimal("0.10"),
        calibration_error=Decimal("0.01"),
    )
    baseline_metrics = ModelMetricSet(
        observation_count=12,
        nll=Decimal("0.60"),
        brier=Decimal("0.20"),
        calibration_error=Decimal("0.03"),
    )
    comparison = ModelComparison(
        comparator_name="s10_reference_baseline",
        comparator_description="deterministic S10 observability fixture baseline",
        metrics=baseline_metrics,
        candidate_nll_delta=Decimal("-0.20"),
        candidate_brier_delta=Decimal("-0.10"),
        candidate_improved_nll=True,
        candidate_improved_brier=True,
    )
    quantiles = (
        QuantileCoverageMetric(
            level=Decimal("0.1"),
            observed_coverage=Decimal("0.1"),
            coverage_error=Decimal("0.0"),
        ),
        QuantileCoverageMetric(
            level=Decimal("0.5"),
            observed_coverage=Decimal("0.5"),
            coverage_error=Decimal("0.0"),
        ),
        QuantileCoverageMetric(
            level=Decimal("0.9"),
            observed_coverage=Decimal("0.9"),
            coverage_error=Decimal("0.0"),
        ),
    )
    baseline_evidence = BaselineEvidenceReference(
        scorecard_id="EVALSCORECARD:S10OBSERVABILITY0000000000000000",
        scorecard_hash="e" * 64,
        gate_report_path="docs/reports/gates/S5-004_baseline_gate_report.md",
        scorecard_report_path="docs/reports/gates/S5-003_evaluation_scorecard_report.md",
    )
    requirement_ids = ("FR-008", "FR-014", "FR-007", "NFR-005")
    evaluated_splits = (DatasetSplit.VALIDATION,)
    evaluated_forecast_ids = ("FORECAST:S10:OBS:1", "FORECAST:S10:OBS:2")
    uncertainty_summary = UncertaintySummary(
        mean_uncertainty=Decimal("0.01"),
        min_uncertainty=Decimal("0.005"),
        max_uncertainty=Decimal("0.020"),
    )
    recommendation = ModelGateRecommendation.CONTINUE_RESEARCH
    reasons = ("fixture remains forecast-only and does not auto-promote",)
    caveats = ("forecast-only fixture; does not route orders",)
    report_hash = build_model_validation_report_hash(
        requirement_ids=requirement_ids,
        dataset_snapshot_id=dataset_id,
        dataset_hash=dataset_hash,
        training_run_id=training_run_id,
        training_run_hash=training_hash,
        model_version_id=model_version_id,
        model_version_hash=model_hash,
        forecast_output_id=forecast_output_id,
        forecast_output_hash=forecast_hash,
        evaluated_splits=evaluated_splits,
        evaluated_forecast_ids=evaluated_forecast_ids,
        candidate_metrics=candidate_metrics,
        quantile_coverage=quantiles,
        uncertainty_summary=uncertainty_summary,
        train_prior_baseline=comparison,
        sequence_ablation=comparison,
        baseline_evidence=baseline_evidence,
        registry_metadata=None,
        recommendation=recommendation,
        reasons=reasons,
        caveats=caveats,
    )
    return ModelValidationReport(
        report_id=build_model_validation_report_id(report_hash=report_hash),
        report_hash=report_hash,
        requirement_ids=requirement_ids,
        dataset_snapshot_id=dataset_id,
        dataset_hash=dataset_hash,
        training_run_id=training_run_id,
        training_run_hash=training_hash,
        model_version_id=model_version_id,
        model_version_hash=model_hash,
        forecast_output_id=forecast_output_id,
        forecast_output_hash=forecast_hash,
        evaluated_splits=evaluated_splits,
        evaluated_forecast_ids=evaluated_forecast_ids,
        candidate_metrics=candidate_metrics,
        quantile_coverage=quantiles,
        uncertainty_summary=uncertainty_summary,
        train_prior_baseline=comparison,
        sequence_ablation=comparison,
        baseline_evidence=baseline_evidence,
        registry_metadata=None,
        recommendation=recommendation,
        reasons=reasons,
        caveats=caveats,
    )


def _strategy_gate_report() -> StrategyGateReport:
    observations = (
        StrategyGateUtilityObservation(
            decision_id="DECISION:S10:OBS:TAKEN",
            realized_return=Decimal("0.010"),
        ),
        StrategyGateUtilityObservation(
            decision_id="DECISION:S10:OBS:SKIPPED",
            realized_return=Decimal("0.000"),
        ),
    )
    draft = StrategyGateReport.model_construct(
        report_id="STRATEGYGATE:PLACEHOLDER",
        report_hash="0" * 64,
        input_decision_ids=("DECISION:S10:OBS:TAKEN", "DECISION:S10:OBS:SKIPPED"),
        input_decision_hashes=("f" * 64, "1" * 64),
        observation_count=2,
        taken_count=1,
        skipped_count=1,
        taken_mean_utility=Decimal("0.010"),
        skipped_mean_opportunity_utility=Decimal("-0.002"),
        skipped_vs_taken_mean_utility=Decimal("-0.012"),
        turnover_proxy_notional=Decimal("100"),
        cost_drag_notional=Decimal("1.000"),
        reason_counts=(
            StrategyDecisionReasonCount(
                reason_code=StrategyDecisionReasonCode.TRADE_POSITIVE_NET_EDGE,
                count=1,
            ),
            StrategyDecisionReasonCount(
                reason_code=StrategyDecisionReasonCode.INSUFFICIENT_NET_EDGE,
                count=1,
            ),
        ),
        utility_observations=observations,
        requirement_ids=("FR-009", "FR-014"),
        caveats=(
            "S10 observability fixture only; it does not approve risk.",
            "No-trade is logged as first-class strategy evidence.",
        ),
    )
    report_hash = build_strategy_gate_report_hash(report=draft)
    return StrategyGateReport(
        **draft.model_dump(exclude={"report_id", "report_hash"}),
        report_id=build_strategy_gate_report_id(report_hash=report_hash),
        report_hash=report_hash,
    )
