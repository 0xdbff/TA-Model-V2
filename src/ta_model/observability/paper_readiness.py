"""Paper-readiness dashboard smoke and alert-routing evidence builders."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from pydantic import Field, model_validator

from ta_model.contracts.evaluation import StrategyGateReport
from ta_model.contracts.execution import ExecutionGatewayReport
from ta_model.contracts.instrument_master import ContractModel, NonEmptyString
from ta_model.contracts.model_validation import ModelGateRecommendation, ModelValidationReport
from ta_model.contracts.observability import (
    PaperReadinessAlertCategory,
    PaperReadinessAlertOperator,
    PaperReadinessAlertRule,
    PaperReadinessAlertSeverity,
    PaperReadinessDashboardSpec,
    PaperReadinessMetricEvidence,
    PaperReadinessMetricSourceLink,
    PaperReadinessMetricStatus,
    PaperReadinessObservabilityReport,
    PaperReadinessSignalGroup,
    make_paper_readiness_alert_event,
    make_paper_readiness_alert_route,
    make_paper_readiness_alert_rule,
    make_paper_readiness_dashboard_panel,
    make_paper_readiness_dashboard_spec,
    make_paper_readiness_observability_report,
)
from ta_model.contracts.paper import (
    PaperAccountSessionReport,
    PaperAccountStateSource,
    PaperRejectionSource,
    PaperTcaReport,
)
from ta_model.contracts.risk import (
    KillSwitchState,
    RiskCheckEvent,
    RiskDecisionStatus,
    RiskLimitStatus,
    RiskReasonCode,
)
from ta_model.contracts.stream_health import DataHealthReasonCode, DataHealthSignal

METRIC_DATA_STALE_COUNT = "paper.data.stale_critical_feed_count"
METRIC_DATA_BLOCKED_COUNT = "paper.data.blocked_signal_count"
METRIC_MODEL_CALIBRATION_ERROR = "paper.model.calibration_error"
METRIC_MODEL_VALIDATION_BLOCKER_COUNT = "paper.model.validation_blocker_count"
METRIC_STRATEGY_NO_TRADE_QUALITY_DELTA = "paper.strategy.no_trade_quality_delta"
METRIC_STRATEGY_COST_DRAG_NOTIONAL = "paper.strategy.cost_drag_notional"
METRIC_PORTFOLIO_TOTAL_EXECUTION_COST = "paper.portfolio.total_execution_cost"
METRIC_PORTFOLIO_MAX_DRAWDOWN_PCT = "paper.portfolio.max_drawdown_pct"
METRIC_PORTFOLIO_ACCOUNT_STATE_LINKAGE_GAP = "paper.portfolio.account_state_linkage_gap"
METRIC_EXECUTION_TCA_ERROR_COUNT = "paper.execution.tca_error_count"
METRIC_EXECUTION_ORDER_REJECT_COUNT = "paper.execution.order_reject_count"
METRIC_EXECUTION_COST_PREDICTION_ERROR_ABS = "paper.execution.cost_prediction_error_abs"
METRIC_RISK_KILL_SWITCH_BLOCK_COUNT = "paper.risk.kill_switch_block_count"
METRIC_RISK_PRE_TRADE_BLOCK_COUNT = "paper.risk.pre_trade_block_count"
METRIC_RISK_HARD_BREACH_COUNT = "paper.risk.hard_breach_count"

_DEFAULT_DASHBOARD_CONFIG: dict[str, object] = {
    "title": "S10 paper-readiness dashboard",
    "version": "s10-004-v1",
    "panels": [
        {
            "group": "data_health",
            "title": "Data health and freshness",
            "description": "Critical stream freshness and fail-closed data-health signals.",
            "metric_ids": [METRIC_DATA_STALE_COUNT, METRIC_DATA_BLOCKED_COUNT],
            "source_contracts": ["DataHealthSignal", "StreamHealthRecord"],
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#data-health-and-stale-feeds"
            ),
            "requirement_ids": ["FR-002", "NFR-006", "RISK-014"],
        },
        {
            "group": "model_validation",
            "title": "Model validation, calibration, and drift readiness",
            "description": "Forecast validation and calibration readiness from model gate reports.",
            "metric_ids": [
                METRIC_MODEL_CALIBRATION_ERROR,
                METRIC_MODEL_VALIDATION_BLOCKER_COUNT,
            ],
            "source_contracts": ["ModelValidationReport"],
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#model-validation-readiness"
            ),
            "requirement_ids": ["FR-014", "RISK-014"],
        },
        {
            "group": "strategy",
            "title": "Strategy and no-trade quality",
            "description": "No-trade utility and cost-drag evidence from strategy gate reports.",
            "metric_ids": [
                METRIC_STRATEGY_NO_TRADE_QUALITY_DELTA,
                METRIC_STRATEGY_COST_DRAG_NOTIONAL,
            ],
            "source_contracts": ["StrategyGateReport"],
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#strategy-gate-and-no-trade-quality"
            ),
            "requirement_ids": ["FR-009", "FR-014", "RISK-014"],
        },
        {
            "group": "portfolio",
            "title": "Portfolio and paper account state",
            "description": (
                "Account-state linkage, execution cost totals, and drawdown-like risk "
                "telemetry."
            ),
            "metric_ids": [
                METRIC_PORTFOLIO_TOTAL_EXECUTION_COST,
                METRIC_PORTFOLIO_MAX_DRAWDOWN_PCT,
                METRIC_PORTFOLIO_ACCOUNT_STATE_LINKAGE_GAP,
            ],
            "source_contracts": ["PaperAccountSessionReport", "RiskCheckEvent"],
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#portfolio-accounting-and-drawdown"
            ),
            "requirement_ids": ["FR-013", "FR-014", "RISK-014"],
        },
        {
            "group": "execution",
            "title": "Execution, TCA, rejects, and slippage",
            "description": "Paper TCA errors, order rejects, and cost prediction error evidence.",
            "metric_ids": [
                METRIC_EXECUTION_TCA_ERROR_COUNT,
                METRIC_EXECUTION_ORDER_REJECT_COUNT,
                METRIC_EXECUTION_COST_PREDICTION_ERROR_ABS,
            ],
            "source_contracts": [
                "ExecutionGatewayReport",
                "PaperAccountSessionReport",
                "PaperTcaReport",
            ],
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#execution-tca-and-order-rejects"
            ),
            "requirement_ids": ["FR-013", "FR-014", "US-011", "RISK-014"],
        },
        {
            "group": "risk",
            "title": "Risk, kill-switch, and pre-trade blocks",
            "description": (
                "Independent risk, kill-switch, and hard-breach evidence before paper "
                "gateway."
            ),
            "metric_ids": [
                METRIC_RISK_KILL_SWITCH_BLOCK_COUNT,
                METRIC_RISK_PRE_TRADE_BLOCK_COUNT,
                METRIC_RISK_HARD_BREACH_COUNT,
            ],
            "source_contracts": ["RiskCheckEvent", "PaperAccountSessionReport"],
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#risk-kill-switch-and-pre-trade-blocks"
            ),
            "requirement_ids": ["FR-010", "FR-011", "NFR-004", "RISK-014"],
        },
    ],
}

_DEFAULT_ALERT_CONFIG: dict[str, object] = {
    "rules": [
        {
            "category": "data_stale",
            "group": "data_health",
            "metric_id": METRIC_DATA_STALE_COUNT,
            "operator": "gt",
            "threshold": "0",
            "owner": "Data / risk",
            "severity": "critical",
            "channel": "paper-readiness-ops",
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#data-health-and-stale-feeds"
            ),
            "description": "Critical feed stale signal must fail closed for affected scope.",
            "source_contracts": ["DataHealthSignal"],
            "requirement_ids": ["NFR-006", "RISK-014"],
        },
        {
            "category": "execution_tca_error",
            "group": "execution",
            "metric_id": METRIC_EXECUTION_TCA_ERROR_COUNT,
            "operator": "gt",
            "threshold": "0",
            "owner": "Execution / risk",
            "severity": "critical",
            "channel": "paper-readiness-ops",
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#execution-tca-and-order-rejects"
            ),
            "description": (
                "Paper TCA errors require execution review before paper-readiness claim."
            ),
            "source_contracts": ["PaperTcaReport"],
            "requirement_ids": ["FR-014", "US-011", "RISK-014"],
        },
        {
            "category": "order_reject",
            "group": "execution",
            "metric_id": METRIC_EXECUTION_ORDER_REJECT_COUNT,
            "operator": "gt",
            "threshold": "0",
            "owner": "Execution / ops",
            "severity": "warning",
            "channel": "paper-readiness-ops",
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#execution-tca-and-order-rejects"
            ),
            "description": "Gateway replay rejects require routing to execution operations.",
            "source_contracts": ["PaperAccountSessionReport", "ExecutionGatewayReport"],
            "requirement_ids": ["FR-013", "FR-014", "RISK-014"],
        },
        {
            "category": "portfolio_drawdown",
            "group": "portfolio",
            "metric_id": METRIC_PORTFOLIO_MAX_DRAWDOWN_PCT,
            "operator": "gt",
            "threshold": "0.05",
            "owner": "Risk / product",
            "severity": "warning",
            "channel": "paper-readiness-ops",
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#portfolio-accounting-and-drawdown"
            ),
            "description": "Drawdown-like portfolio risk telemetry crossed paper soft threshold.",
            "source_contracts": ["RiskCheckEvent"],
            "requirement_ids": ["FR-014", "RISK-014"],
        },
        {
            "category": "portfolio_accounting",
            "group": "portfolio",
            "metric_id": METRIC_PORTFOLIO_ACCOUNT_STATE_LINKAGE_GAP,
            "operator": "gt",
            "threshold": "0",
            "owner": "Portfolio / ops",
            "severity": "warning",
            "channel": "paper-readiness-ops",
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#portfolio-accounting-and-drawdown"
            ),
            "description": "Paper account final state needs stronger computed/replay linkage.",
            "source_contracts": ["PaperAccountSessionReport"],
            "requirement_ids": ["FR-013", "FR-014", "RISK-014"],
        },
        {
            "category": "risk_kill_switch",
            "group": "risk",
            "metric_id": METRIC_RISK_KILL_SWITCH_BLOCK_COUNT,
            "operator": "gt",
            "threshold": "0",
            "owner": "Risk / ops",
            "severity": "critical",
            "channel": "paper-readiness-ops",
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#risk-kill-switch-and-pre-trade-blocks"
            ),
            "description": "Kill-switch or unknown kill state blocked paper-path risk checks.",
            "source_contracts": ["RiskCheckEvent"],
            "requirement_ids": ["FR-010", "FR-011", "NFR-004", "RISK-014"],
        },
        {
            "category": "risk_pre_trade_block",
            "group": "risk",
            "metric_id": METRIC_RISK_PRE_TRADE_BLOCK_COUNT,
            "operator": "gt",
            "threshold": "0",
            "owner": "Risk",
            "severity": "warning",
            "channel": "paper-readiness-ops",
            "runbook_url": (
                "docs/runbooks/paper-readiness/README.md#risk-kill-switch-and-pre-trade-blocks"
            ),
            "description": "Independent risk engine blocked or no-traded paper-path requests.",
            "source_contracts": ["RiskCheckEvent"],
            "requirement_ids": ["FR-010", "NFR-004", "RISK-014"],
        },
    ]
}


class PaperReadinessConfigError(ValueError):
    """Raised when committed dashboard/alert config is invalid."""


class _DashboardPanelConfig(ContractModel):
    group: PaperReadinessSignalGroup
    title: NonEmptyString
    description: NonEmptyString
    metric_ids: tuple[NonEmptyString, ...] = Field(min_length=1)
    source_contracts: tuple[NonEmptyString, ...] = Field(min_length=1)
    runbook_url: NonEmptyString
    requirement_ids: tuple[NonEmptyString, ...] = Field(min_length=1)


class _DashboardConfig(ContractModel):
    title: NonEmptyString
    version: NonEmptyString
    panels: tuple[_DashboardPanelConfig, ...] = Field(min_length=1)


class _AlertRuleConfig(ContractModel):
    category: PaperReadinessAlertCategory
    group: PaperReadinessSignalGroup
    metric_id: NonEmptyString
    operator: PaperReadinessAlertOperator
    threshold: Decimal
    owner: NonEmptyString
    severity: PaperReadinessAlertSeverity
    channel: NonEmptyString
    runbook_url: NonEmptyString
    description: NonEmptyString
    source_contracts: tuple[NonEmptyString, ...] = Field(min_length=1)
    requirement_ids: tuple[NonEmptyString, ...] = Field(min_length=1)


class _AlertConfig(ContractModel):
    rules: tuple[_AlertRuleConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def metric_ids_are_unique_per_category(self) -> _AlertConfig:
        category_metric_pairs = tuple((rule.category, rule.metric_id) for rule in self.rules)
        if len(set(category_metric_pairs)) != len(category_metric_pairs):
            raise ValueError("alert config contains duplicate category/metric rules")
        return self


def load_paper_readiness_dashboard_spec(path: str | Path) -> PaperReadinessDashboardSpec:
    """Load and validate a committed paper-readiness dashboard config artifact."""

    return make_paper_readiness_dashboard_spec_from_config(_load_json_object(path))


def load_paper_readiness_alert_rules(path: str | Path) -> tuple[PaperReadinessAlertRule, ...]:
    """Load and validate committed paper-readiness alert config artifacts."""

    return make_paper_readiness_alert_rules_from_config(_load_json_object(path))


def make_default_paper_readiness_dashboard_spec() -> PaperReadinessDashboardSpec:
    """Return the built-in minimal S10 paper-readiness dashboard specification."""

    return make_paper_readiness_dashboard_spec_from_config(_DEFAULT_DASHBOARD_CONFIG)


def make_default_paper_readiness_alert_rules() -> tuple[PaperReadinessAlertRule, ...]:
    """Return the built-in S10 paper-readiness alert rules/routes."""

    return make_paper_readiness_alert_rules_from_config(_DEFAULT_ALERT_CONFIG)


def make_paper_readiness_dashboard_spec_from_config(
    config: Mapping[str, object]
) -> PaperReadinessDashboardSpec:
    """Validate dashboard config and build deterministic typed panel/spec contracts."""

    parsed = _DashboardConfig.model_validate(config)
    panels = tuple(
        make_paper_readiness_dashboard_panel(
            group=panel.group,
            title=panel.title,
            description=panel.description,
            metric_ids=tuple(str(metric_id) for metric_id in panel.metric_ids),
            source_contracts=tuple(str(source) for source in panel.source_contracts),
            runbook_url=panel.runbook_url,
            requirement_ids=tuple(str(requirement) for requirement in panel.requirement_ids),
        )
        for panel in parsed.panels
    )
    return make_paper_readiness_dashboard_spec(
        title=parsed.title,
        version=parsed.version,
        panels=panels,
    )


def make_paper_readiness_alert_rules_from_config(
    config: Mapping[str, object]
) -> tuple[PaperReadinessAlertRule, ...]:
    """Validate alert config and build deterministic alert rules/routes."""

    parsed = _AlertConfig.model_validate(config)
    rules: list[PaperReadinessAlertRule] = []
    for rule_config in parsed.rules:
        route = make_paper_readiness_alert_route(
            category=rule_config.category,
            owner=rule_config.owner,
            severity=rule_config.severity,
            channel=rule_config.channel,
            runbook_url=rule_config.runbook_url,
            requirement_ids=tuple(str(requirement) for requirement in rule_config.requirement_ids),
        )
        rules.append(
            make_paper_readiness_alert_rule(
                category=rule_config.category,
                group=rule_config.group,
                metric_id=rule_config.metric_id,
                operator=rule_config.operator,
                threshold=rule_config.threshold,
                route=route,
                description=rule_config.description,
                source_contracts=tuple(str(source) for source in rule_config.source_contracts),
                requirement_ids=tuple(
                    str(requirement) for requirement in rule_config.requirement_ids
                ),
            )
        )
    return tuple(rules)


def build_paper_readiness_observability_report(
    *,
    generated_at: datetime,
    data_health_signals: tuple[DataHealthSignal, ...],
    model_validation_report: ModelValidationReport,
    strategy_gate_report: StrategyGateReport,
    paper_account_report: PaperAccountSessionReport,
    paper_tca_report: PaperTcaReport,
    execution_gateway_report: ExecutionGatewayReport,
    risk_events: tuple[RiskCheckEvent, ...],
    dashboard: PaperReadinessDashboardSpec | None = None,
    alert_rules: tuple[PaperReadinessAlertRule, ...] | None = None,
) -> PaperReadinessObservabilityReport:
    """Build deterministic S10 dashboard smoke and alert-routing evidence.

    Inputs are existing project contracts/reports only. This function does not emit
    telemetry to a runtime service, place orders, or route live notifications.
    """

    _validate_report_linkage(
        execution_gateway_report=execution_gateway_report,
        paper_account_report=paper_account_report,
        paper_tca_report=paper_tca_report,
    )
    selected_dashboard = dashboard or make_default_paper_readiness_dashboard_spec()
    selected_rules = alert_rules or make_default_paper_readiness_alert_rules()
    metric_evidence = _build_metric_evidence(
        data_health_signals=data_health_signals,
        model_validation_report=model_validation_report,
        strategy_gate_report=strategy_gate_report,
        paper_account_report=paper_account_report,
        paper_tca_report=paper_tca_report,
        execution_gateway_report=execution_gateway_report,
        risk_events=risk_events,
    )
    metric_by_id = {metric.metric_id: metric for metric in metric_evidence}
    routed_alerts = tuple(
        make_paper_readiness_alert_event(rule=rule, metric=metric_by_id[rule.metric_id])
        for rule in selected_rules
        if rule.metric_id in metric_by_id and _rule_breaches(rule, metric_by_id[rule.metric_id])
    )
    return make_paper_readiness_observability_report(
        generated_at=generated_at,
        dashboard=selected_dashboard,
        alert_rules=selected_rules,
        metric_evidence=metric_evidence,
        routed_alerts=routed_alerts,
    )


def _build_metric_evidence(
    *,
    data_health_signals: tuple[DataHealthSignal, ...],
    model_validation_report: ModelValidationReport,
    strategy_gate_report: StrategyGateReport,
    paper_account_report: PaperAccountSessionReport,
    paper_tca_report: PaperTcaReport,
    execution_gateway_report: ExecutionGatewayReport,
    risk_events: tuple[RiskCheckEvent, ...],
) -> tuple[PaperReadinessMetricEvidence, ...]:
    data_links = _data_health_links(data_health_signals)
    model_link = _report_link(
        source_contract="ModelValidationReport",
        report_id=model_validation_report.report_id,
        report_hash=model_validation_report.report_hash,
        source_fields=("candidate_metrics", "recommendation"),
        requirement_ids=model_validation_report.requirement_ids,
    )
    strategy_link = _report_link(
        source_contract="StrategyGateReport",
        report_id=strategy_gate_report.report_id,
        report_hash=strategy_gate_report.report_hash,
        source_fields=(
            "skipped_vs_taken_mean_utility",
            "cost_drag_notional",
        ),
        requirement_ids=strategy_gate_report.requirement_ids,
    )
    account_link = _paper_account_report_link(paper_account_report)
    tca_link = _paper_tca_report_link(paper_tca_report)
    gateway_link = _gateway_report_link(execution_gateway_report)
    risk_links = _risk_event_links(risk_events)

    stale_count = Decimal(
        sum(
            1
            for signal in data_health_signals
            if DataHealthReasonCode.CRITICAL_FRESHNESS_STALE in signal.reason_codes
        )
    )
    blocked_data_count = Decimal(sum(1 for signal in data_health_signals if signal.blocks_trading))
    model_blockers = Decimal(
        1 if model_validation_report.recommendation is ModelGateRecommendation.BLOCKED else 0
    )
    max_drawdown = max(
        (event.request.loss_risk.max_drawdown_pct for event in risk_events),
        default=Decimal("0"),
    )
    account_linkage_gap = Decimal(
        1
        if paper_account_report.final_account_state_source
        is PaperAccountStateSource.EXPLICIT_LINKAGE
        else 0
    )
    gateway_reject_count = Decimal(
        sum(
            1
            for entry in paper_account_report.rejection_logs
            if entry.rejection_source is PaperRejectionSource.GATEWAY_REPLAY
        )
    )
    kill_switch_blocks = Decimal(
        sum(
            1
            for event in risk_events
            if RiskReasonCode.KILL_SWITCH_ACTIVE in event.reason_codes
            or event.active_kill_state
            not in {KillSwitchState.CLEAR, KillSwitchState.SOFT_LIMITED}
        )
    )
    pre_trade_blocks = Decimal(
        sum(
            1
            for event in risk_events
            if event.final_decision
            in {RiskDecisionStatus.REJECTED, RiskDecisionStatus.NO_TRADE}
        )
    )
    hard_breach_count = Decimal(
        sum(
            1
            for event in risk_events
            for evaluation in event.limit_evaluations
            if evaluation.status is RiskLimitStatus.HARD_BREACH
        )
    )

    return (
        _metric(
            metric_id=METRIC_DATA_STALE_COUNT,
            group=PaperReadinessSignalGroup.DATA_HEALTH,
            label="Critical stale feed signals",
            current_value=stale_count,
            threshold=Decimal("0"),
            source_links=data_links,
        ),
        _metric(
            metric_id=METRIC_DATA_BLOCKED_COUNT,
            group=PaperReadinessSignalGroup.DATA_HEALTH,
            label="Data-health blocks",
            current_value=blocked_data_count,
            threshold=Decimal("0"),
            source_links=data_links,
        ),
        _metric(
            metric_id=METRIC_MODEL_CALIBRATION_ERROR,
            group=PaperReadinessSignalGroup.MODEL_VALIDATION,
            label="Model calibration error",
            current_value=model_validation_report.candidate_metrics.calibration_error,
            threshold=Decimal("0.05"),
            source_links=(model_link,),
        ),
        _metric(
            metric_id=METRIC_MODEL_VALIDATION_BLOCKER_COUNT,
            group=PaperReadinessSignalGroup.MODEL_VALIDATION,
            label="Model validation blockers",
            current_value=model_blockers,
            threshold=Decimal("0"),
            source_links=(model_link,),
        ),
        _metric(
            metric_id=METRIC_STRATEGY_NO_TRADE_QUALITY_DELTA,
            group=PaperReadinessSignalGroup.STRATEGY,
            label="Skipped-vs-taken no-trade utility delta",
            current_value=strategy_gate_report.skipped_vs_taken_mean_utility,
            threshold=Decimal("0.005"),
            source_links=(strategy_link,),
        ),
        _metric(
            metric_id=METRIC_STRATEGY_COST_DRAG_NOTIONAL,
            group=PaperReadinessSignalGroup.STRATEGY,
            label="Strategy cost-drag notional",
            current_value=strategy_gate_report.cost_drag_notional,
            threshold=None,
            source_links=(strategy_link,),
        ),
        _metric(
            metric_id=METRIC_PORTFOLIO_TOTAL_EXECUTION_COST,
            group=PaperReadinessSignalGroup.PORTFOLIO,
            label="Paper account execution-cost total",
            current_value=paper_account_report.total_execution_cost,
            threshold=None,
            source_links=(account_link,),
        ),
        _metric(
            metric_id=METRIC_PORTFOLIO_MAX_DRAWDOWN_PCT,
            group=PaperReadinessSignalGroup.PORTFOLIO,
            label="Max drawdown telemetry",
            current_value=max_drawdown,
            threshold=Decimal("0.05"),
            source_links=risk_links,
        ),
        _metric(
            metric_id=METRIC_PORTFOLIO_ACCOUNT_STATE_LINKAGE_GAP,
            group=PaperReadinessSignalGroup.PORTFOLIO,
            label="Explicit-only account-state linkage gap",
            current_value=account_linkage_gap,
            threshold=Decimal("0"),
            source_links=(account_link,),
        ),
        _metric(
            metric_id=METRIC_EXECUTION_TCA_ERROR_COUNT,
            group=PaperReadinessSignalGroup.EXECUTION,
            label="Paper TCA error rows",
            current_value=Decimal(paper_tca_report.error_count),
            threshold=Decimal("0"),
            source_links=(tca_link, gateway_link),
        ),
        _metric(
            metric_id=METRIC_EXECUTION_ORDER_REJECT_COUNT,
            group=PaperReadinessSignalGroup.EXECUTION,
            label="Gateway replay order rejects",
            current_value=gateway_reject_count,
            threshold=Decimal("0"),
            source_links=(account_link, gateway_link),
        ),
        _metric(
            metric_id=METRIC_EXECUTION_COST_PREDICTION_ERROR_ABS,
            group=PaperReadinessSignalGroup.EXECUTION,
            label="Absolute paper TCA cost prediction error",
            current_value=abs(paper_tca_report.total_cost_prediction_error),
            threshold=None,
            source_links=(tca_link,),
        ),
        _metric(
            metric_id=METRIC_RISK_KILL_SWITCH_BLOCK_COUNT,
            group=PaperReadinessSignalGroup.RISK,
            label="Kill-switch risk blocks",
            current_value=kill_switch_blocks,
            threshold=Decimal("0"),
            source_links=risk_links,
        ),
        _metric(
            metric_id=METRIC_RISK_PRE_TRADE_BLOCK_COUNT,
            group=PaperReadinessSignalGroup.RISK,
            label="Independent pre-trade blocked/no-trade events",
            current_value=pre_trade_blocks,
            threshold=Decimal("0"),
            source_links=risk_links,
        ),
        _metric(
            metric_id=METRIC_RISK_HARD_BREACH_COUNT,
            group=PaperReadinessSignalGroup.RISK,
            label="Risk hard-breach evaluations",
            current_value=hard_breach_count,
            threshold=Decimal("0"),
            source_links=risk_links,
        ),
    )


def _metric(
    *,
    metric_id: str,
    group: PaperReadinessSignalGroup,
    label: str,
    current_value: Decimal,
    threshold: Decimal | None,
    source_links: tuple[PaperReadinessMetricSourceLink, ...],
) -> PaperReadinessMetricEvidence:
    breached = threshold is not None and current_value > threshold
    return PaperReadinessMetricEvidence(
        metric_id=metric_id,
        group=group,
        label=label,
        current_value=current_value,
        threshold=threshold,
        status=(
            PaperReadinessMetricStatus.BREACHED
            if breached
            else PaperReadinessMetricStatus.HEALTHY
        ),
        source_links=source_links,
    )


def _rule_breaches(
    rule: PaperReadinessAlertRule, metric: PaperReadinessMetricEvidence
) -> bool:
    value = metric.current_value
    threshold = rule.threshold
    if rule.operator is PaperReadinessAlertOperator.GREATER_THAN:
        return value > threshold
    if rule.operator is PaperReadinessAlertOperator.GREATER_THAN_OR_EQUAL:
        return value >= threshold
    if rule.operator is PaperReadinessAlertOperator.LESS_THAN:
        return value < threshold
    if rule.operator is PaperReadinessAlertOperator.LESS_THAN_OR_EQUAL:
        return value <= threshold
    return value == threshold


def _data_health_links(
    signals: tuple[DataHealthSignal, ...]
) -> tuple[PaperReadinessMetricSourceLink, ...]:
    if not signals:
        return (
            PaperReadinessMetricSourceLink(
                source_contract="DataHealthSignal",
                source_id="DATAHEALTH:NO-SIGNALS",
                source_fields=("data_health_signals",),
                requirement_ids=("NFR-006", "RISK-014"),
            ),
        )
    return tuple(
        PaperReadinessMetricSourceLink(
            source_contract="DataHealthSignal",
            source_id=signal.signal_id,
            source_event_id=signal.source_health_event_id,
            source_metric_ids=tuple(metric.value for metric in signal.source_metric_names),
            source_fields=("status", "reason_codes", "blocks_trading"),
            requirement_ids=("NFR-006", "RISK-014"),
        )
        for signal in signals
    )


def _risk_event_links(
    risk_events: tuple[RiskCheckEvent, ...]
) -> tuple[PaperReadinessMetricSourceLink, ...]:
    if not risk_events:
        return (
            PaperReadinessMetricSourceLink(
                source_contract="RiskCheckEvent",
                source_id="RISKCHECK:NO-EVENTS",
                source_fields=("risk_events",),
                requirement_ids=("FR-010", "NFR-004", "RISK-014"),
            ),
        )
    return tuple(
        PaperReadinessMetricSourceLink(
            source_contract="RiskCheckEvent",
            source_id=event.risk_check_id,
            source_hash=event.risk_check_hash,
            run_id=event.request.run_id,
            trace_id=event.request.trace_id,
            source_event_id=event.risk_check_id,
            source_metric_ids=tuple(evaluation.limit_id for evaluation in event.limit_evaluations),
            source_fields=(
                "active_kill_state",
                "final_decision",
                "reason_codes",
                "limit_evaluations",
                "request.loss_risk.max_drawdown_pct",
            ),
            requirement_ids=event.requirement_ids,
        )
        for event in risk_events
    )


def _report_link(
    *,
    source_contract: str,
    report_id: str,
    report_hash: str,
    source_fields: tuple[str, ...],
    requirement_ids: tuple[str, ...],
    run_id: str | None = None,
    source_metric_ids: tuple[str, ...] = (),
) -> PaperReadinessMetricSourceLink:
    return PaperReadinessMetricSourceLink(
        source_contract=source_contract,
        source_id=report_id,
        source_hash=report_hash,
        report_id=report_id,
        report_hash=report_hash,
        run_id=run_id,
        source_metric_ids=source_metric_ids,
        source_fields=source_fields,
        requirement_ids=requirement_ids,
    )


def _paper_account_report_link(
    report: PaperAccountSessionReport,
) -> PaperReadinessMetricSourceLink:
    return _report_link(
        source_contract="PaperAccountSessionReport",
        report_id=report.session_report_id,
        report_hash=report.session_report_hash,
        run_id=report.run_id,
        source_fields=(
            "total_execution_cost",
            "rejected_order_count",
            "blocked_order_count",
            "final_account_state_source",
        ),
        requirement_ids=report.requirement_ids,
        source_metric_ids=(
            "total_execution_cost",
            "rejected_order_count",
            "final_account_state_source",
        ),
    )


def _paper_tca_report_link(report: PaperTcaReport) -> PaperReadinessMetricSourceLink:
    return _report_link(
        source_contract="PaperTcaReport",
        report_id=report.tca_report_id,
        report_hash=report.tca_report_hash,
        run_id=report.run_id,
        source_fields=(
            "error_count",
            "issue_ids",
            "total_cost_prediction_error",
        ),
        requirement_ids=report.requirement_ids,
        source_metric_ids=("error_count", "total_cost_prediction_error"),
    )


def _gateway_report_link(report: ExecutionGatewayReport) -> PaperReadinessMetricSourceLink:
    trace_ids = tuple(sorted({event.trace_id for event in report.events}))
    return _report_link(
        source_contract="ExecutionGatewayReport",
        report_id=report.gateway_report_id,
        report_hash=report.gateway_report_hash,
        run_id=report.run_id,
        source_fields=("events.status", "gateway_event_ids"),
        requirement_ids=report.requirement_ids,
        source_metric_ids=tuple(event.status.value for event in report.events),
    ).model_copy(update={"trace_id": trace_ids[0] if len(trace_ids) == 1 else None})


def _validate_report_linkage(
    *,
    execution_gateway_report: ExecutionGatewayReport,
    paper_account_report: PaperAccountSessionReport,
    paper_tca_report: PaperTcaReport,
) -> None:
    expected_id = execution_gateway_report.gateway_report_id
    expected_hash = execution_gateway_report.gateway_report_hash
    if paper_account_report.gateway_report_id != expected_id:
        raise ValueError("paper account report does not link to execution gateway report")
    if paper_account_report.gateway_report_hash != expected_hash:
        raise ValueError("paper account report hash does not link to execution gateway report")
    if paper_tca_report.gateway_report_id != expected_id:
        raise ValueError("paper TCA report does not link to execution gateway report")
    if paper_tca_report.gateway_report_hash != expected_hash:
        raise ValueError("paper TCA report hash does not link to execution gateway report")


def _load_json_object(path: str | Path) -> Mapping[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PaperReadinessConfigError("paper readiness config must be a JSON object")
    return cast(Mapping[str, object], payload)
