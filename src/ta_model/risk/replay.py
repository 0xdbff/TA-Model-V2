"""Risk-gated seam for S6 event-time replay.

Raw replay remains the low-level simulator helper. This seam is the S9 path that
forwards only independently approved order intents to the real S6 replay engine.
"""

from __future__ import annotations

from collections.abc import Iterable

from ta_model.contracts.instrument_master import InstrumentMasterSnapshot
from ta_model.contracts.market_data import OHLCTVBar
from ta_model.contracts.risk import (
    RiskCheckEvent,
    RiskDecisionStatus,
    RiskGatedReplayResult,
    make_risk_gated_replay_result,
)
from ta_model.contracts.simulation import ExecutionCostModel, OrderIntent, SimulatedAccountState
from ta_model.simulation.replay import replay_ohlctv_market_orders

_APPROVED_DECISIONS = {
    RiskDecisionStatus.APPROVED,
    RiskDecisionStatus.APPROVED_AFTER_CAP,
    RiskDecisionStatus.CANCEL_REDUCE_ONLY_APPROVED,
}


def replay_risk_approved_market_orders(
    *,
    bars: Iterable[OHLCTVBar],
    risk_events: Iterable[RiskCheckEvent],
    run_id: str,
    execution_cost_model: ExecutionCostModel | None = None,
    instrument_master_snapshot: InstrumentMasterSnapshot | None = None,
    starting_account_state: SimulatedAccountState | None = None,
) -> RiskGatedReplayResult:
    """Replay only intents with deterministic independent risk approval."""

    event_tuple = tuple(risk_events)
    approved_events: list[RiskCheckEvent] = []
    blocked_events: list[RiskCheckEvent] = []
    approved_intents: list[OrderIntent] = []
    for event in event_tuple:
        if event.final_decision in _APPROVED_DECISIONS and event.approved_order_intent is not None:
            approved_events.append(event)
            approved_intents.append(event.approved_order_intent)
        else:
            blocked_events.append(event)

    replay_report = None
    if approved_intents:
        replay_report = replay_ohlctv_market_orders(
            bars=bars,
            order_intents=tuple(approved_intents),
            run_id=run_id,
            execution_cost_model=execution_cost_model,
            instrument_master_snapshot=instrument_master_snapshot,
            starting_account_state=starting_account_state,
        )

    return make_risk_gated_replay_result(
        run_id=run_id,
        risk_check_ids=tuple(event.risk_check_id for event in event_tuple),
        approved_risk_check_ids=tuple(event.risk_check_id for event in approved_events),
        blocked_risk_check_ids=tuple(event.risk_check_id for event in blocked_events),
        replay_report=replay_report,
    )
