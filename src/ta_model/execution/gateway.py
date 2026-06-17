"""Risk-gated simulator and paper gateway adapters for S10.

Both adapters accept independent ``RiskCheckEvent`` evidence only.  The paper path
is explicitly simulated-fill paper mode and delegates fill/rejection semantics to the
existing event-time replay path so it cannot drift from simulator behavior.
"""

from __future__ import annotations

from collections.abc import Iterable

from ta_model.contracts.execution import (
    ExecutionFillMode,
    ExecutionGatewayKind,
    ExecutionGatewayReport,
    make_execution_gateway_lifecycle_event,
    make_execution_gateway_report,
)
from ta_model.contracts.instrument_master import InstrumentMasterSnapshot
from ta_model.contracts.market_data import OHLCTVBar
from ta_model.contracts.risk import RiskCheckEvent, RiskDecisionStatus
from ta_model.contracts.simulation import (
    ExecutionCostModel,
    ReplayOrderResult,
    SimulatedAccountState,
)
from ta_model.risk.replay import replay_risk_approved_market_orders

_APPROVED_DECISIONS = {
    RiskDecisionStatus.APPROVED,
    RiskDecisionStatus.APPROVED_AFTER_CAP,
    RiskDecisionStatus.CANCEL_REDUCE_ONLY_APPROVED,
}

_SIMULATOR_REQUIREMENTS = ("FR-010", "FR-012", "NFR-004", "TFR-008")
_PAPER_REQUIREMENTS = ("FR-010", "FR-013", "NFR-004", "TFR-008")


def run_simulator_gateway_replay(
    *,
    bars: Iterable[OHLCTVBar],
    risk_events: Iterable[RiskCheckEvent],
    run_id: str,
    execution_cost_model: ExecutionCostModel | None = None,
    instrument_master_snapshot: InstrumentMasterSnapshot | None = None,
    starting_account_state: SimulatedAccountState | None = None,
) -> ExecutionGatewayReport:
    """Run simulator gateway lifecycle reporting through the S9 risk-gated replay seam."""

    return _run_risk_gated_gateway(
        bars=bars,
        risk_events=risk_events,
        run_id=run_id,
        gateway_kind=ExecutionGatewayKind.SIMULATOR,
        fill_mode=ExecutionFillMode.EVENT_TIME_REPLAY,
        requirement_ids=_SIMULATOR_REQUIREMENTS,
        execution_cost_model=execution_cost_model,
        instrument_master_snapshot=instrument_master_snapshot,
        starting_account_state=starting_account_state,
    )


def run_paper_gateway_replay(
    *,
    bars: Iterable[OHLCTVBar],
    risk_events: Iterable[RiskCheckEvent],
    run_id: str,
    execution_cost_model: ExecutionCostModel | None = None,
    instrument_master_snapshot: InstrumentMasterSnapshot | None = None,
    starting_account_state: SimulatedAccountState | None = None,
) -> ExecutionGatewayReport:
    """Run the paper gateway with simulated fills only from approved risk evidence.

    This is not a live broker adapter and performs no network calls.  The function
    intentionally accepts ``RiskCheckEvent`` values rather than raw order intents so
    rejected, kill-switch, stale-feed, or duplicate-idempotency events cannot bypass
    the independent risk engine.
    """

    return _run_risk_gated_gateway(
        bars=bars,
        risk_events=risk_events,
        run_id=run_id,
        gateway_kind=ExecutionGatewayKind.PAPER,
        fill_mode=ExecutionFillMode.PAPER_SIMULATED_FILL,
        requirement_ids=_PAPER_REQUIREMENTS,
        execution_cost_model=execution_cost_model,
        instrument_master_snapshot=instrument_master_snapshot,
        starting_account_state=starting_account_state,
    )


def _run_risk_gated_gateway(
    *,
    bars: Iterable[OHLCTVBar],
    risk_events: Iterable[RiskCheckEvent],
    run_id: str,
    gateway_kind: ExecutionGatewayKind,
    fill_mode: ExecutionFillMode,
    requirement_ids: tuple[str, ...],
    execution_cost_model: ExecutionCostModel | None,
    instrument_master_snapshot: InstrumentMasterSnapshot | None,
    starting_account_state: SimulatedAccountState | None,
) -> ExecutionGatewayReport:
    event_tuple = tuple(risk_events)
    risk_gated_replay = replay_risk_approved_market_orders(
        bars=bars,
        risk_events=event_tuple,
        run_id=run_id,
        execution_cost_model=execution_cost_model,
        instrument_master_snapshot=instrument_master_snapshot,
        starting_account_state=starting_account_state,
    )
    replay_results_by_risk_id = _replay_results_by_risk_id(
        risk_events=event_tuple,
        replay_results=(
            risk_gated_replay.replay_report.results
            if risk_gated_replay.replay_report is not None
            else ()
        ),
    )
    lifecycle_events = tuple(
        make_execution_gateway_lifecycle_event(
            gateway_kind=gateway_kind,
            fill_mode=fill_mode,
            run_id=run_id,
            risk_event=risk_event,
            replay_result=replay_results_by_risk_id.get(risk_event.risk_check_id),
            requirement_ids=requirement_ids,
        )
        for risk_event in event_tuple
    )
    return make_execution_gateway_report(
        run_id=run_id,
        gateway_kind=gateway_kind,
        fill_mode=fill_mode,
        risk_gated_replay_result=risk_gated_replay,
        events=lifecycle_events,
        requirement_ids=requirement_ids,
    )


def _replay_results_by_risk_id(
    *,
    risk_events: tuple[RiskCheckEvent, ...],
    replay_results: tuple[ReplayOrderResult, ...],
) -> dict[str, ReplayOrderResult]:
    approved_risk_ids = tuple(
        risk_event.risk_check_id
        for risk_event in risk_events
        if risk_event.final_decision in _APPROVED_DECISIONS
        and risk_event.approved_order_intent is not None
    )
    if len(approved_risk_ids) != len(replay_results):
        raise ValueError("approved risk events and replay results must align")
    return dict(zip(approved_risk_ids, replay_results, strict=True))
