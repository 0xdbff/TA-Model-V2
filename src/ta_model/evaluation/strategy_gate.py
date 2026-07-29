"""Build S8 strategy gate reports from real StrategyDecision objects.

Traceability:
- FR-009: evaluates trade/no-trade decisions and reason-code distributions.
- FR-014: reports strategy-quality metrics separately from model metrics.

Scope: local validation only; no order routing, paper/live gateway, risk approval,
model promotion, leverage, derivatives, shorts, margin, or live capital path.
"""

from __future__ import annotations

from decimal import Decimal

from ta_model.contracts.decisions import (
    StrategyDecision,
    StrategyDecisionAction,
    build_strategy_decision_reason_counts,
)
from ta_model.contracts.evaluation import (
    StrategyGateReport,
    StrategyGateUtilityObservation,
    build_strategy_gate_report_hash,
    build_strategy_gate_report_id,
)


class StrategyGateReportBuildError(ValueError):
    """Raised when strategy decisions cannot be safely evaluated."""


def build_strategy_gate_report(
    decisions: tuple[StrategyDecision, ...],
    *,
    utility_observations: tuple[StrategyGateUtilityObservation, ...],
) -> StrategyGateReport:
    """Evaluate skipped-vs-taken utility, turnover, cost drag, and reasons."""

    if not decisions:
        raise StrategyGateReportBuildError("at least one strategy decision is required")
    observations_by_decision_id = _observations_by_decision_id(utility_observations)
    missing_observations = tuple(
        decision.decision_id
        for decision in decisions
        if decision.decision_id not in observations_by_decision_id
    )
    if missing_observations:
        raise StrategyGateReportBuildError("utility observations must cover every decision")
    extra_observations = tuple(
        decision_id
        for decision_id in observations_by_decision_id
        if decision_id not in {decision.decision_id for decision in decisions}
    )
    if extra_observations:
        raise StrategyGateReportBuildError("utility observations include unknown decisions")

    ordered_decisions = tuple(sorted(decisions, key=lambda decision: decision.decision_id))
    ordered_observations = tuple(
        observations_by_decision_id[decision.decision_id] for decision in ordered_decisions
    )
    taken_utilities: list[Decimal] = []
    skipped_utilities: list[Decimal] = []
    turnover_proxy_notional = Decimal("0")
    cost_drag_notional = Decimal("0")
    for decision, observation in zip(ordered_decisions, ordered_observations, strict=True):
        net_utility = observation.realized_return - decision.expected_cost - observation.cash_return
        if decision.action is StrategyDecisionAction.BUY:
            taken_utilities.append(net_utility)
            turnover_proxy_notional += decision.sizing.proposed_notional
            cost_drag_notional += decision.sizing.proposed_notional * decision.expected_cost
        else:
            skipped_utilities.append(net_utility)

    if not taken_utilities or not skipped_utilities:
        raise StrategyGateReportBuildError(
            "strategy gate report requires at least one taken and one skipped decision"
        )
    taken_mean_utility = _mean(tuple(taken_utilities))
    skipped_mean_opportunity_utility = _mean(tuple(skipped_utilities))
    skipped_vs_taken_mean_utility = skipped_mean_opportunity_utility - taken_mean_utility
    draft = StrategyGateReport.model_construct(
        report_id="STRATEGYGATE:PLACEHOLDER",
        report_hash="0" * 64,
        input_decision_ids=tuple(decision.decision_id for decision in ordered_decisions),
        input_decision_hashes=tuple(decision.decision_hash for decision in ordered_decisions),
        observation_count=len(ordered_decisions),
        taken_count=len(taken_utilities),
        skipped_count=len(skipped_utilities),
        taken_mean_utility=taken_mean_utility,
        skipped_mean_opportunity_utility=skipped_mean_opportunity_utility,
        skipped_vs_taken_mean_utility=skipped_vs_taken_mean_utility,
        turnover_proxy_notional=turnover_proxy_notional,
        cost_drag_notional=cost_drag_notional,
        reason_counts=build_strategy_decision_reason_counts(decisions=ordered_decisions),
        utility_observations=ordered_observations,
        requirement_ids=("FR-009", "FR-014"),
    )
    report_hash = build_strategy_gate_report_hash(report=draft)
    return StrategyGateReport(
        **draft.model_dump(exclude={"report_id", "report_hash"}),
        report_id=build_strategy_gate_report_id(report_hash=report_hash),
        report_hash=report_hash,
    )


def _observations_by_decision_id(
    utility_observations: tuple[StrategyGateUtilityObservation, ...],
) -> dict[str, StrategyGateUtilityObservation]:
    observations_by_decision_id: dict[str, StrategyGateUtilityObservation] = {}
    for observation in utility_observations:
        if observation.decision_id in observations_by_decision_id:
            raise StrategyGateReportBuildError("duplicate utility observation decision_id")
        observations_by_decision_id[observation.decision_id] = observation
    return observations_by_decision_id


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))
