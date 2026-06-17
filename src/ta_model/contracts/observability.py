"""Paper-readiness dashboard and alert evidence contracts.

Traceability:
- FR-014: dashboard metric evidence covers model, strategy, portfolio, engine/TCA,
  and risk signals separately for paper readiness.
- RISK-014: alert evidence includes owner, severity, thresholds, runbook links, and
  source linkage so operational blind spots are detectable.
- NFR-004/NFR-006: routed alerts preserve trace/risk/data-health source evidence and
  stale-feed fail-closed linkage.

Scope:
- Deterministic observability artifacts only. No full web UI, broker/network calls,
  new runtime service, leverage, derivatives, live capital, or autonomous promotion
  path is introduced.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString


class PaperReadinessSignalGroup(StrEnum):
    """Required paper-readiness dashboard signal groups."""

    DATA_HEALTH = "data_health"
    MODEL_VALIDATION = "model_validation"
    STRATEGY = "strategy"
    PORTFOLIO = "portfolio"
    EXECUTION = "execution"
    RISK = "risk"


class PaperReadinessMetricStatus(StrEnum):
    """Metric state used by dashboard smoke and alert routing evidence."""

    HEALTHY = "healthy"
    BREACHED = "breached"
    UNAVAILABLE = "unavailable"


class PaperReadinessAlertSeverity(StrEnum):
    """Small severity set for paper-readiness alert routes."""

    WARNING = "warning"
    CRITICAL = "critical"


class PaperReadinessAlertCategory(StrEnum):
    """Actionable paper-readiness alert families."""

    DATA_STALE = "data_stale"
    EXECUTION_TCA_ERROR = "execution_tca_error"
    ORDER_REJECT = "order_reject"
    PORTFOLIO_DRAWDOWN = "portfolio_drawdown"
    PORTFOLIO_ACCOUNTING = "portfolio_accounting"
    RISK_KILL_SWITCH = "risk_kill_switch"
    RISK_PRE_TRADE_BLOCK = "risk_pre_trade_block"


class PaperReadinessAlertOperator(StrEnum):
    """Supported deterministic alert threshold comparisons."""

    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    EQUAL = "eq"


_REQUIRED_GROUPS: frozenset[PaperReadinessSignalGroup] = frozenset(
    PaperReadinessSignalGroup
)


class PaperReadinessMetricSourceLink(ContractModel):
    """Source contract/report/run/trace linkage for one metric or alert."""

    source_contract: NonEmptyString
    source_id: NonEmptyString
    source_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    report_id: NonEmptyString | None = None
    report_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    run_id: NonEmptyString | None = None
    trace_id: NonEmptyString | None = None
    source_event_id: NonEmptyString | None = None
    source_metric_ids: tuple[NonEmptyString, ...] = ()
    source_fields: tuple[NonEmptyString, ...] = Field(min_length=1)
    requirement_ids: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def report_id_and_hash_are_paired(self) -> Self:
        if (self.report_id is None) != (self.report_hash is None):
            raise ValueError("report_id and report_hash must be set together")
        return self


class PaperReadinessDashboardPanel(ContractModel):
    """One minimal dashboard panel definition for paper-readiness smoke evidence."""

    panel_id: CanonicalId
    panel_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    group: PaperReadinessSignalGroup
    title: NonEmptyString
    description: NonEmptyString
    metric_ids: tuple[NonEmptyString, ...] = Field(min_length=1)
    source_contracts: tuple[NonEmptyString, ...] = Field(min_length=1)
    runbook_url: NonEmptyString
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-014", "RISK-014")

    @model_validator(mode="after")
    def panel_identity_is_deterministic(self) -> Self:
        _validate_runbook_link(self.runbook_url)
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("dashboard panel metric_ids must be unique")
        expected_hash = build_paper_readiness_dashboard_panel_hash(panel=self)
        if self.panel_hash != expected_hash:
            raise ValueError("panel_hash is not deterministic")
        if self.panel_id != build_paper_readiness_dashboard_panel_id(panel_hash=expected_hash):
            raise ValueError("panel_id is not deterministic")
        return self


class PaperReadinessDashboardSpec(ContractModel):
    """Stable paper-readiness dashboard specification covering all required groups."""

    dashboard_id: CanonicalId
    dashboard_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    title: NonEmptyString
    version: NonEmptyString
    panel_ids: tuple[CanonicalId, ...]
    panels: tuple[PaperReadinessDashboardPanel, ...] = Field(min_length=1)
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-014", "RISK-014")

    @model_validator(mode="after")
    def dashboard_identity_is_deterministic(self) -> Self:
        if self.panel_ids != tuple(panel.panel_id for panel in self.panels):
            raise ValueError("dashboard panel_ids must match panels")
        groups = {panel.group for panel in self.panels}
        if groups != _REQUIRED_GROUPS:
            raise ValueError("paper-readiness dashboard must cover all six signal groups")
        metric_ids = tuple(metric_id for panel in self.panels for metric_id in panel.metric_ids)
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("dashboard metric IDs must be unique across panels")
        expected_hash = build_paper_readiness_dashboard_spec_hash(dashboard=self)
        if self.dashboard_hash != expected_hash:
            raise ValueError("dashboard_hash is not deterministic")
        if self.dashboard_id != build_paper_readiness_dashboard_spec_id(
            dashboard_hash=expected_hash
        ):
            raise ValueError("dashboard_id is not deterministic")
        return self


class PaperReadinessAlertRoute(ContractModel):
    """Owner/channel/runbook route for an actionable paper-readiness alert."""

    route_id: CanonicalId
    route_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    category: PaperReadinessAlertCategory
    owner: NonEmptyString
    severity: PaperReadinessAlertSeverity
    channel: NonEmptyString
    runbook_url: NonEmptyString
    requirement_ids: tuple[NonEmptyString, ...] = ("RISK-014",)

    @model_validator(mode="after")
    def route_identity_is_deterministic(self) -> Self:
        _validate_runbook_link(self.runbook_url)
        expected_hash = build_paper_readiness_alert_route_hash(route=self)
        if self.route_hash != expected_hash:
            raise ValueError("route_hash is not deterministic")
        if self.route_id != build_paper_readiness_alert_route_id(route_hash=expected_hash):
            raise ValueError("route_id is not deterministic")
        return self


class PaperReadinessAlertRule(ContractModel):
    """Threshold rule binding one metric to a deterministic alert route."""

    rule_id: CanonicalId
    rule_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    category: PaperReadinessAlertCategory
    group: PaperReadinessSignalGroup
    metric_id: NonEmptyString
    operator: PaperReadinessAlertOperator
    threshold: Decimal
    route: PaperReadinessAlertRoute
    description: NonEmptyString
    source_contracts: tuple[NonEmptyString, ...] = Field(min_length=1)
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-014", "RISK-014")

    @model_validator(mode="after")
    def rule_identity_is_deterministic(self) -> Self:
        if self.route.category is not self.category:
            raise ValueError("alert route category must match rule category")
        expected_hash = build_paper_readiness_alert_rule_hash(rule=self)
        if self.rule_hash != expected_hash:
            raise ValueError("rule_hash is not deterministic")
        if self.rule_id != build_paper_readiness_alert_rule_id(rule_hash=expected_hash):
            raise ValueError("rule_id is not deterministic")
        return self


class PaperReadinessMetricEvidence(ContractModel):
    """One dashboard metric sample derived from project report contracts."""

    metric_id: NonEmptyString
    group: PaperReadinessSignalGroup
    label: NonEmptyString
    current_value: Decimal
    threshold: Decimal | None = None
    status: PaperReadinessMetricStatus
    source_links: tuple[PaperReadinessMetricSourceLink, ...] = Field(min_length=1)
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-014", "RISK-014")

    @model_validator(mode="after")
    def breached_metrics_carry_thresholds(self) -> Self:
        if self.status is PaperReadinessMetricStatus.BREACHED and self.threshold is None:
            raise ValueError("breached metric evidence requires threshold")
        return self


class PaperReadinessAlertEvent(ContractModel):
    """Routed alert evidence with current/threshold and source/run/trace linkage."""

    alert_id: CanonicalId
    alert_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    category: PaperReadinessAlertCategory
    group: PaperReadinessSignalGroup
    rule_id: CanonicalId
    route_id: CanonicalId
    metric_id: NonEmptyString
    owner: NonEmptyString
    severity: PaperReadinessAlertSeverity
    current_value: Decimal
    threshold: Decimal
    operator: PaperReadinessAlertOperator
    runbook_url: NonEmptyString
    source_links: tuple[PaperReadinessMetricSourceLink, ...] = Field(min_length=1)
    run_ids: tuple[NonEmptyString, ...]
    trace_ids: tuple[NonEmptyString, ...]
    report_ids: tuple[NonEmptyString, ...]
    source_ids: tuple[NonEmptyString, ...]
    message: NonEmptyString
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-014", "RISK-014")

    @model_validator(mode="after")
    def alert_identity_is_deterministic(self) -> Self:
        _validate_runbook_link(self.runbook_url)
        if self.run_ids != _unique_sorted(link.run_id for link in self.source_links):
            raise ValueError("alert run_ids must match source links")
        if self.trace_ids != _unique_sorted(link.trace_id for link in self.source_links):
            raise ValueError("alert trace_ids must match source links")
        if self.report_ids != _unique_sorted(link.report_id for link in self.source_links):
            raise ValueError("alert report_ids must match source links")
        if self.source_ids != _unique_sorted(link.source_id for link in self.source_links):
            raise ValueError("alert source_ids must match source links")
        expected_hash = build_paper_readiness_alert_event_hash(alert=self)
        if self.alert_hash != expected_hash:
            raise ValueError("alert_hash is not deterministic")
        if self.alert_id != build_paper_readiness_alert_event_id(alert_hash=expected_hash):
            raise ValueError("alert_id is not deterministic")
        return self


class PaperReadinessObservabilityReport(ContractModel):
    """Deterministic S10 dashboard-smoke and alert-routing evidence report."""

    observability_report_id: CanonicalId
    observability_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    generated_at: AwareDatetime
    dashboard: PaperReadinessDashboardSpec
    alert_rule_ids: tuple[CanonicalId, ...]
    alert_rules: tuple[PaperReadinessAlertRule, ...]
    metric_ids: tuple[NonEmptyString, ...]
    metric_evidence: tuple[PaperReadinessMetricEvidence, ...]
    routed_alert_ids: tuple[CanonicalId, ...]
    routed_alerts: tuple[PaperReadinessAlertEvent, ...] = ()
    source_report_ids: tuple[NonEmptyString, ...]
    source_run_ids: tuple[NonEmptyString, ...]
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-014", "RISK-014")

    @model_validator(mode="after")
    def report_identity_is_deterministic(self) -> Self:
        if self.alert_rule_ids != tuple(rule.rule_id for rule in self.alert_rules):
            raise ValueError("alert_rule_ids must match alert_rules")
        if self.metric_ids != tuple(metric.metric_id for metric in self.metric_evidence):
            raise ValueError("metric_ids must match metric_evidence")
        if self.routed_alert_ids != tuple(alert.alert_id for alert in self.routed_alerts):
            raise ValueError("routed_alert_ids must match routed_alerts")

        dashboard_metric_ids = tuple(
            metric_id for panel in self.dashboard.panels for metric_id in panel.metric_ids
        )
        if set(dashboard_metric_ids) != set(self.metric_ids):
            raise ValueError("metric evidence must cover every dashboard metric")

        rule_ids = set(self.alert_rule_ids)
        metric_ids = set(self.metric_ids)
        for alert in self.routed_alerts:
            if alert.rule_id not in rule_ids:
                raise ValueError("routed alerts must reference configured alert rules")
            if alert.metric_id not in metric_ids:
                raise ValueError("routed alerts must reference dashboard metric evidence")

        metric_links = tuple(
            link for metric in self.metric_evidence for link in metric.source_links
        )
        if self.source_report_ids != _unique_sorted(link.report_id for link in metric_links):
            raise ValueError("source_report_ids must match metric source links")
        if self.source_run_ids != _unique_sorted(link.run_id for link in metric_links):
            raise ValueError("source_run_ids must match metric source links")

        expected_hash = build_paper_readiness_observability_report_hash(report=self)
        if self.observability_report_hash != expected_hash:
            raise ValueError("observability_report_hash is not deterministic")
        if self.observability_report_id != build_paper_readiness_observability_report_id(
            report_hash=expected_hash
        ):
            raise ValueError("observability_report_id is not deterministic")
        return self


def make_paper_readiness_dashboard_panel(
    *,
    group: PaperReadinessSignalGroup,
    title: str,
    description: str,
    metric_ids: tuple[str, ...],
    source_contracts: tuple[str, ...],
    runbook_url: str,
    requirement_ids: tuple[str, ...] = ("FR-014", "RISK-014"),
) -> PaperReadinessDashboardPanel:
    """Build a deterministic dashboard panel definition."""

    draft = PaperReadinessDashboardPanel.model_construct(
        panel_id="PAPERDASHPANEL:PLACEHOLDER",
        panel_hash="0" * 64,
        group=group,
        title=title,
        description=description,
        metric_ids=metric_ids,
        source_contracts=source_contracts,
        runbook_url=runbook_url,
        requirement_ids=requirement_ids,
    )
    panel_hash = build_paper_readiness_dashboard_panel_hash(panel=draft)
    return PaperReadinessDashboardPanel(
        **draft.model_dump(exclude={"panel_id", "panel_hash"}),
        panel_id=build_paper_readiness_dashboard_panel_id(panel_hash=panel_hash),
        panel_hash=panel_hash,
    )


def make_paper_readiness_dashboard_spec(
    *,
    title: str,
    version: str,
    panels: tuple[PaperReadinessDashboardPanel, ...],
    requirement_ids: tuple[str, ...] = ("FR-014", "RISK-014"),
) -> PaperReadinessDashboardSpec:
    """Build the deterministic paper-readiness dashboard specification."""

    draft = PaperReadinessDashboardSpec.model_construct(
        dashboard_id="PAPERDASHBOARD:PLACEHOLDER",
        dashboard_hash="0" * 64,
        title=title,
        version=version,
        panel_ids=tuple(panel.panel_id for panel in panels),
        panels=panels,
        requirement_ids=requirement_ids,
    )
    dashboard_hash = build_paper_readiness_dashboard_spec_hash(dashboard=draft)
    return PaperReadinessDashboardSpec(
        **draft.model_dump(exclude={"dashboard_id", "dashboard_hash"}),
        dashboard_id=build_paper_readiness_dashboard_spec_id(dashboard_hash=dashboard_hash),
        dashboard_hash=dashboard_hash,
    )


def make_paper_readiness_alert_route(
    *,
    category: PaperReadinessAlertCategory,
    owner: str,
    severity: PaperReadinessAlertSeverity,
    channel: str,
    runbook_url: str,
    requirement_ids: tuple[str, ...] = ("RISK-014",),
) -> PaperReadinessAlertRoute:
    """Build a deterministic alert route."""

    draft = PaperReadinessAlertRoute.model_construct(
        route_id="PAPERALERTROUTE:PLACEHOLDER",
        route_hash="0" * 64,
        category=category,
        owner=owner,
        severity=severity,
        channel=channel,
        runbook_url=runbook_url,
        requirement_ids=requirement_ids,
    )
    route_hash = build_paper_readiness_alert_route_hash(route=draft)
    return PaperReadinessAlertRoute(
        **draft.model_dump(exclude={"route_id", "route_hash"}),
        route_id=build_paper_readiness_alert_route_id(route_hash=route_hash),
        route_hash=route_hash,
    )


def make_paper_readiness_alert_rule(
    *,
    category: PaperReadinessAlertCategory,
    group: PaperReadinessSignalGroup,
    metric_id: str,
    operator: PaperReadinessAlertOperator,
    threshold: Decimal,
    route: PaperReadinessAlertRoute,
    description: str,
    source_contracts: tuple[str, ...],
    requirement_ids: tuple[str, ...] = ("FR-014", "RISK-014"),
) -> PaperReadinessAlertRule:
    """Build a deterministic alert threshold rule."""

    draft = PaperReadinessAlertRule.model_construct(
        rule_id="PAPERALERTRULE:PLACEHOLDER",
        rule_hash="0" * 64,
        category=category,
        group=group,
        metric_id=metric_id,
        operator=operator,
        threshold=threshold,
        route=route,
        description=description,
        source_contracts=source_contracts,
        requirement_ids=requirement_ids,
    )
    rule_hash = build_paper_readiness_alert_rule_hash(rule=draft)
    return PaperReadinessAlertRule(
        **draft.model_dump(exclude={"rule_id", "rule_hash"}),
        rule_id=build_paper_readiness_alert_rule_id(rule_hash=rule_hash),
        rule_hash=rule_hash,
    )


def make_paper_readiness_alert_event(
    *,
    rule: PaperReadinessAlertRule,
    metric: PaperReadinessMetricEvidence,
) -> PaperReadinessAlertEvent:
    """Build a deterministic routed alert from a breached metric and rule."""

    route = rule.route
    draft = PaperReadinessAlertEvent.model_construct(
        alert_id="PAPERALERT:PLACEHOLDER",
        alert_hash="0" * 64,
        category=rule.category,
        group=rule.group,
        rule_id=rule.rule_id,
        route_id=route.route_id,
        metric_id=rule.metric_id,
        owner=route.owner,
        severity=route.severity,
        current_value=metric.current_value,
        threshold=rule.threshold,
        operator=rule.operator,
        runbook_url=route.runbook_url,
        source_links=metric.source_links,
        run_ids=_unique_sorted(link.run_id for link in metric.source_links),
        trace_ids=_unique_sorted(link.trace_id for link in metric.source_links),
        report_ids=_unique_sorted(link.report_id for link in metric.source_links),
        source_ids=_unique_sorted(link.source_id for link in metric.source_links),
        message=(
            f"{rule.category.value} breached: {rule.metric_id}="
            f"{metric.current_value} {rule.operator.value} {rule.threshold}"
        ),
        requirement_ids=rule.requirement_ids,
    )
    alert_hash = build_paper_readiness_alert_event_hash(alert=draft)
    return PaperReadinessAlertEvent(
        **draft.model_dump(exclude={"alert_id", "alert_hash"}),
        alert_id=build_paper_readiness_alert_event_id(alert_hash=alert_hash),
        alert_hash=alert_hash,
    )


def make_paper_readiness_observability_report(
    *,
    generated_at: AwareDatetime,
    dashboard: PaperReadinessDashboardSpec,
    alert_rules: tuple[PaperReadinessAlertRule, ...],
    metric_evidence: tuple[PaperReadinessMetricEvidence, ...],
    routed_alerts: tuple[PaperReadinessAlertEvent, ...],
    requirement_ids: tuple[str, ...] = ("FR-014", "RISK-014"),
) -> PaperReadinessObservabilityReport:
    """Build deterministic dashboard-smoke and routed-alert evidence."""

    metric_links = tuple(link for metric in metric_evidence for link in metric.source_links)
    draft = PaperReadinessObservabilityReport.model_construct(
        observability_report_id="PAPEROBS:PLACEHOLDER",
        observability_report_hash="0" * 64,
        generated_at=generated_at,
        dashboard=dashboard,
        alert_rule_ids=tuple(rule.rule_id for rule in alert_rules),
        alert_rules=alert_rules,
        metric_ids=tuple(metric.metric_id for metric in metric_evidence),
        metric_evidence=metric_evidence,
        routed_alert_ids=tuple(alert.alert_id for alert in routed_alerts),
        routed_alerts=routed_alerts,
        source_report_ids=_unique_sorted(link.report_id for link in metric_links),
        source_run_ids=_unique_sorted(link.run_id for link in metric_links),
        requirement_ids=requirement_ids,
    )
    report_hash = build_paper_readiness_observability_report_hash(report=draft)
    return PaperReadinessObservabilityReport(
        **draft.model_dump(
            exclude={"observability_report_id", "observability_report_hash"}
        ),
        observability_report_id=build_paper_readiness_observability_report_id(
            report_hash=report_hash
        ),
        observability_report_hash=report_hash,
    )


def build_paper_readiness_dashboard_panel_hash(
    *, panel: PaperReadinessDashboardPanel
) -> str:
    return _hash(_model_payload(panel, exclude={"panel_id", "panel_hash"}))


def build_paper_readiness_dashboard_panel_id(*, panel_hash: str) -> str:
    return _stable_id("PAPERDASHPANEL", {"panel_hash": panel_hash})


def build_paper_readiness_dashboard_spec_hash(
    *, dashboard: PaperReadinessDashboardSpec
) -> str:
    return _hash(_model_payload(dashboard, exclude={"dashboard_id", "dashboard_hash"}))


def build_paper_readiness_dashboard_spec_id(*, dashboard_hash: str) -> str:
    return _stable_id("PAPERDASHBOARD", {"dashboard_hash": dashboard_hash})


def build_paper_readiness_alert_route_hash(*, route: PaperReadinessAlertRoute) -> str:
    return _hash(_model_payload(route, exclude={"route_id", "route_hash"}))


def build_paper_readiness_alert_route_id(*, route_hash: str) -> str:
    return _stable_id("PAPERALERTROUTE", {"route_hash": route_hash})


def build_paper_readiness_alert_rule_hash(*, rule: PaperReadinessAlertRule) -> str:
    return _hash(_model_payload(rule, exclude={"rule_id", "rule_hash"}))


def build_paper_readiness_alert_rule_id(*, rule_hash: str) -> str:
    return _stable_id("PAPERALERTRULE", {"rule_hash": rule_hash})


def build_paper_readiness_alert_event_hash(*, alert: PaperReadinessAlertEvent) -> str:
    return _hash(_model_payload(alert, exclude={"alert_id", "alert_hash"}))


def build_paper_readiness_alert_event_id(*, alert_hash: str) -> str:
    return _stable_id("PAPERALERT", {"alert_hash": alert_hash})


def build_paper_readiness_observability_report_hash(
    *, report: PaperReadinessObservabilityReport
) -> str:
    return _hash(
        _model_payload(
            report,
            exclude={"observability_report_id", "observability_report_hash"},
        )
    )


def build_paper_readiness_observability_report_id(*, report_hash: str) -> str:
    return _stable_id("PAPEROBS", {"report_hash": report_hash})


def _validate_runbook_link(runbook_url: str) -> None:
    if not (runbook_url.startswith("docs/runbooks/") or runbook_url.startswith("https://")):
        raise ValueError(
            "alert/dashboard runbook_url must be a docs/runbooks/ path or https URL"
        )


def _unique_sorted(values: Iterable[str | None]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value is not None}))


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_payload(model: ContractModel, *, exclude: set[str]) -> object:
    return json.loads(model.model_dump_json(exclude=exclude))
