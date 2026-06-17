"""Evidence for S9-001 risk-check contract completeness and determinism."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

import ta_model.contracts as public_contracts
from risk_test_helpers import default_policy, risk_request
from ta_model.contracts.risk import (
    KillSwitchState,
    RiskCheckEvent,
    RiskDecisionStatus,
    RiskLimitStatus,
    RiskReasonCode,
    build_risk_check_event_hash,
)
from ta_model.risk.engine import evaluate_pre_trade_risk


def test_public_risk_contract_exports_are_available() -> None:
    assert public_contracts.RiskPolicy is not None
    assert public_contracts.RiskCheckRequest is not None
    assert public_contracts.RiskCheckEvent is RiskCheckEvent
    assert public_contracts.KillSwitchState is KillSwitchState
    assert public_contracts.make_default_risk_policy is not None


def test_risk_check_event_records_required_limit_evidence_and_final_decision() -> None:
    request = risk_request()
    policy = default_policy()

    event = evaluate_pre_trade_risk(request=request, policy=policy)

    assert event.final_decision is RiskDecisionStatus.APPROVED
    assert event.active_kill_state is KillSwitchState.CLEAR
    assert event.request.trace_id == request.trace_id
    assert event.request.decision_ts == request.decision_ts
    assert event.request.risk_check_ts == request.risk_check_ts
    assert event.request.strategy_version == "strategy:s9-risk-fixture:1.0.0"
    assert event.request.order_intent.instrument_id == "COINBASE_SPOT:BTC-USD"
    assert event.request.order_intent.venue_id == "COINBASE_SPOT"
    assert event.request.account_id == "PAPER_COINBASE_SPOT_001"
    assert event.order_effect.proposed_notional == Decimal("100")
    assert event.order_effect.resulting_cash == Decimal("9900")
    assert event.order_effect.risk_increasing is True
    assert event.reason_codes == ()

    evaluations = {item.limit_id: item for item in event.limit_evaluations}
    assert evaluations["order.max_notional"].current_value == Decimal("100")
    assert evaluations["order.max_notional"].soft_threshold == Decimal("100.00")
    assert evaluations["order.max_notional"].hard_threshold == Decimal("250.000")
    assert evaluations["order.max_notional"].status is RiskLimitStatus.PASS
    assert evaluations["order.max_notional"].passed is True
    assert evaluations["order.max_notional"].reason_code is RiskReasonCode.PASSED
    assert evaluations["order.max_notional"].owner == "Risk / execution"
    assert evaluations["kill_switch.active_state"].current_value == Decimal("0")
    assert evaluations["kill_switch.active_state"].status is RiskLimitStatus.PASS
    assert evaluations["execution.duplicate_idempotency"].status is RiskLimitStatus.PASS


def test_risk_check_ids_and_hashes_are_deterministic_and_tamper_evident() -> None:
    request = risk_request()
    policy = default_policy()

    first = evaluate_pre_trade_risk(request=request, policy=policy)
    second = evaluate_pre_trade_risk(request=request, policy=policy)

    assert first.risk_check_id == second.risk_check_id
    assert first.risk_check_hash == second.risk_check_hash
    assert first.risk_check_hash == build_risk_check_event_hash(event=first)

    tampered = first.model_dump()
    tampered["risk_policy_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="risk_check_hash"):
        RiskCheckEvent.model_validate(tampered)
