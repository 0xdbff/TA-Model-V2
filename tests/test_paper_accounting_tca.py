"""S10-002/S10-003 evidence for paper accounting and paper-fill TCA reports."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

import ta_model.contracts as public_contracts
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
from ta_model.contracts.execution import ExecutionGatewayOrderStatus, ExecutionGatewayReport
from ta_model.contracts.paper import (
    PaperAccountSessionReport,
    PaperAccountStateSource,
    PaperRejectionSource,
    PaperTcaIssueCode,
    PaperTcaReport,
    PaperTcaRow,
    TcaReferencePriceSource,
    build_paper_account_state_hash,
    build_paper_account_state_id,
)
from ta_model.contracts.risk import RiskDecisionStatus
from ta_model.contracts.simulation import (
    ReplayRejectReason,
    SimulatedAccountState,
    make_execution_cost_model,
)
from ta_model.contracts.streaming import QuoteEvent
from ta_model.execution import (
    make_paper_account_session_report,
    make_paper_tca_report,
    run_paper_gateway_replay,
)
from ta_model.risk.engine import evaluate_pre_trade_risk


def test_public_exports_include_paper_accounting_and_tca_contracts() -> None:
    assert public_contracts.PaperAccountSessionReport is PaperAccountSessionReport
    assert public_contracts.PaperTcaReport is PaperTcaReport
    assert callable(make_paper_account_session_report)
    assert callable(make_paper_tca_report)


def test_paper_accounting_and_tca_reports_include_fill_quote_cost_linkage() -> None:
    gateway_report, initial_state = _approved_paper_gateway_report(
        run_id="PAPER:S10:ACCOUNTING:TCA",
        order_id="ORDER:S10:ACCOUNTING:TCA",
    )
    event = gateway_report.events[0]
    assert gateway_report.source_replay_final_account_state is not None

    session_report = make_paper_account_session_report(
        gateway_report=gateway_report,
        initial_account_state=initial_state,
    )

    assert session_report.gateway_report_id == gateway_report.gateway_report_id
    assert session_report.initial_account_state == initial_state
    assert session_report.final_account_state_source is PaperAccountStateSource.GATEWAY_REPLAY
    assert session_report.final_account_state == gateway_report.source_replay_final_account_state
    assert session_report.final_account_state_hash == build_paper_account_state_hash(
        account_state=gateway_report.source_replay_final_account_state
    )
    assert session_report.total_order_count == 1
    assert session_report.filled_order_count == 1
    assert session_report.rejection_logs == ()
    assert session_report.order_logs[0].trace_id == event.trace_id
    assert session_report.order_logs[0].risk_check_id == event.risk_check_id
    assert session_report.order_logs[0].client_order_id == event.client_order_id
    assert session_report.fill_logs[0].gateway_event_id == event.gateway_event_id
    assert session_report.fill_logs[0].fee_cost == event.fee_cost
    assert session_report.total_execution_cost == event.total_cost

    tca_report = make_paper_tca_report(
        gateway_report=gateway_report,
        quotes=(_quote(event_ts=event.submitted_at),),
    )

    assert tca_report.gateway_report_hash == gateway_report.gateway_report_hash
    assert tca_report.filled_row_count == 1
    assert tca_report.issues == ()
    row = tca_report.rows[0]
    assert row.quote_id == "QUOTE:S10:ARRIVAL"
    assert row.arrival_bid == Decimal("99.98")
    assert row.arrival_ask == Decimal("100.02")
    assert row.arrival_mid == Decimal("100.00")
    assert row.fill_price == event.fill_price
    assert row.filled_quantity == event.filled_quantity
    assert row.fee_cost == event.fee_cost
    assert row.predicted_spread_cost == event.spread_cost
    assert row.predicted_slippage_cost == event.slippage_cost
    assert row.predicted_spread_slippage_cost == event.spread_cost + event.slippage_cost
    assert row.realized_spread_slippage_cost == event.spread_cost + event.slippage_cost
    assert row.spread_slippage_prediction_error == Decimal("0.00")
    assert row.total_cost_prediction_error == Decimal("0.00000")


def test_paper_accounting_rejects_final_state_that_conflicts_with_gateway_replay() -> None:
    gateway_report, initial_state = _approved_paper_gateway_report(
        run_id="PAPER:S10:ACCOUNTING:CONFLICT",
        order_id="ORDER:S10:ACCOUNTING:CONFLICT",
    )
    mismatched_final_state = account_state(usd=Decimal("999"), btc=Decimal("1"))

    with pytest.raises(ValueError, match="conflicts with gateway-derived state"):
        make_paper_account_session_report(
            gateway_report=gateway_report,
            initial_account_state=initial_state,
            final_account_state=mismatched_final_state,
        )


def test_blocked_only_paper_accounting_defaults_final_state_to_initial() -> None:
    risk_blocked = evaluate_pre_trade_risk(
        request=risk_request(
            order_intent=intent(quantity=Decimal("3"), order_id="ORDER:S10:UNCHANGED")
        ),
        policy=default_policy(),
    )
    initial_state = account_state()
    gateway_report = run_paper_gateway_replay(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(risk_blocked,),
        run_id="PAPER:S10:UNCHANGED",
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=initial_state,
    )

    session_report = make_paper_account_session_report(
        gateway_report=gateway_report,
        initial_account_state=initial_state,
    )

    assert gateway_report.source_replay_report_id is None
    assert gateway_report.source_replay_final_account_state is None
    assert (
        session_report.final_account_state_source
        is PaperAccountStateSource.UNCHANGED_FROM_INITIAL
    )
    assert session_report.final_account_state == initial_state
    assert session_report.final_account_state_id == session_report.initial_account_state_id
    assert session_report.final_account_state_hash == session_report.initial_account_state_hash


def test_approved_fill_without_gateway_final_state_requires_explicit_linkage() -> None:
    approved = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(order_id="ORDER:S10:LINKAGE-ONLY")),
        policy=default_policy(),
    )
    gateway_report = run_paper_gateway_replay(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(approved,),
        run_id="PAPER:S10:LINKAGE-ONLY",
        execution_cost_model=make_execution_cost_model(
            taker_fee_rate=Decimal("0.001"),
            spread_bps=Decimal("2"),
            slippage_bps=Decimal("3"),
        ),
    )
    linked_final_state = account_state()
    linked_hash = build_paper_account_state_hash(account_state=linked_final_state)
    linked_id = build_paper_account_state_id(account_state_hash=linked_hash)

    assert gateway_report.events[0].status is ExecutionGatewayOrderStatus.FILLED
    assert gateway_report.source_replay_final_account_state is None
    with pytest.raises(ValueError, match="explicit final account-state id/hash linkage"):
        make_paper_account_session_report(
            gateway_report=gateway_report,
            initial_account_state=account_state(),
        )

    session_report = make_paper_account_session_report(
        gateway_report=gateway_report,
        initial_account_state=account_state(),
        final_account_state=linked_final_state,
        final_account_state_id=linked_id,
        final_account_state_hash=linked_hash,
    )

    assert session_report.final_account_state_source is PaperAccountStateSource.EXPLICIT_LINKAGE
    assert session_report.final_account_state == linked_final_state


def test_paper_accounting_logs_risk_blocked_and_gateway_rejected_paths() -> None:
    risk_blocked = evaluate_pre_trade_risk(
        request=risk_request(
            order_intent=intent(quantity=Decimal("3"), order_id="ORDER:S10:RISK-BLOCKED")
        ),
        policy=default_policy(),
    )
    gateway_rejected = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(order_id="ORDER:S10:GATEWAY-REJECTED")),
        policy=default_policy(),
    )
    low_cash_state = account_state(usd=Decimal("0"))

    gateway_report = run_paper_gateway_replay(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(risk_blocked, gateway_rejected),
        run_id="PAPER:S10:REJECTIONS",
        execution_cost_model=make_execution_cost_model(
            taker_fee_rate=Decimal("0.001"),
            spread_bps=Decimal("2"),
            slippage_bps=Decimal("3"),
        ),
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=low_cash_state,
    )

    session_report = make_paper_account_session_report(
        gateway_report=gateway_report,
        initial_account_state=low_cash_state,
    )

    assert risk_blocked.final_decision is RiskDecisionStatus.REJECTED
    assert gateway_rejected.final_decision is RiskDecisionStatus.APPROVED
    assert session_report.total_order_count == 2
    assert session_report.blocked_order_count == 1
    assert session_report.rejected_order_count == 1
    assert session_report.fill_logs == ()
    assert {entry.rejection_source for entry in session_report.rejection_logs} == {
        PaperRejectionSource.RISK,
        PaperRejectionSource.GATEWAY_REPLAY,
    }
    replay_rejection = next(
        entry
        for entry in session_report.rejection_logs
        if entry.rejection_source is PaperRejectionSource.GATEWAY_REPLAY
    )
    assert replay_rejection.replay_reject_reason is ReplayRejectReason.INSUFFICIENT_CASH

    tca_report = make_paper_tca_report(gateway_report=gateway_report, quotes=())

    assert tca_report.rows == ()
    assert {issue.code for issue in tca_report.issues} == {
        PaperTcaIssueCode.RISK_BLOCKED,
        PaperTcaIssueCode.GATEWAY_REJECTED,
    }


def test_paper_tca_missing_quote_is_explicit_error_with_fallback_reference() -> None:
    gateway_report, _initial_state = _approved_paper_gateway_report(
        run_id="PAPER:S10:MISSING-QUOTE",
        order_id="ORDER:S10:MISSING-QUOTE",
    )
    event = gateway_report.events[0]
    future_quote = _quote(
        quote_id="QUOTE:S10:FUTURE",
        event_ts=event.submitted_at + timedelta(seconds=1),
    )

    tca_report = make_paper_tca_report(gateway_report=gateway_report, quotes=(future_quote,))

    assert tca_report.filled_row_count == 1
    assert tca_report.issue_count == 1
    assert tca_report.issues[0].code is PaperTcaIssueCode.MISSING_ARRIVAL_QUOTE
    row = tca_report.rows[0]
    assert row.reference_price_source is TcaReferencePriceSource.REPLAY_ARRIVAL_REFERENCE
    assert row.quote_id is None
    assert row.arrival_mid is None
    assert row.fallback_reference_price == event.arrival_reference_price
    assert row.realized_spread_slippage_cost == event.spread_cost + event.slippage_cost


def test_paper_reports_reject_malformed_deterministic_ids_and_hashes() -> None:
    gateway_report, initial_state = _approved_paper_gateway_report(
        run_id="PAPER:S10:BAD-HASH",
        order_id="ORDER:S10:BAD-HASH",
    )
    session_report = make_paper_account_session_report(
        gateway_report=gateway_report,
        initial_account_state=initial_state,
    )
    tca_report = make_paper_tca_report(
        gateway_report=gateway_report,
        quotes=(_quote(event_ts=gateway_report.events[0].submitted_at),),
    )

    with pytest.raises(ValidationError, match="session_report_hash"):
        PaperAccountSessionReport(
            **session_report.model_dump(exclude={"session_report_hash"}),
            session_report_hash="1" * 64,
        )
    with pytest.raises(ValidationError, match="tca_report_id"):
        PaperTcaReport(
            **tca_report.model_dump(exclude={"tca_report_id"}),
            tca_report_id="PAPERTCAREPORT:BROKEN",
        )
    with pytest.raises(ValidationError, match="tca_row_hash"):
        PaperTcaRow(
            **tca_report.rows[0].model_dump(exclude={"tca_row_hash"}),
            tca_row_hash="2" * 64,
        )


def _approved_paper_gateway_report(
    *, run_id: str, order_id: str
) -> tuple[ExecutionGatewayReport, SimulatedAccountState]:
    approved = evaluate_pre_trade_risk(
        request=risk_request(order_intent=intent(order_id=order_id)),
        policy=default_policy(),
    )
    initial_state = account_state()
    gateway_report = run_paper_gateway_replay(
        bars=(bar(0), bar(1), bar(2)),
        risk_events=(approved,),
        run_id=run_id,
        execution_cost_model=make_execution_cost_model(
            taker_fee_rate=Decimal("0.001"),
            spread_bps=Decimal("2"),
            slippage_bps=Decimal("3"),
        ),
        instrument_master_snapshot=load_snapshot(),
        starting_account_state=initial_state,
    )
    assert gateway_report.events[0].status is ExecutionGatewayOrderStatus.FILLED
    assert gateway_report.source_replay_final_account_state is not None
    gateway_final_hash = build_paper_account_state_hash(
        account_state=gateway_report.source_replay_final_account_state
    )
    assert build_paper_account_state_id(account_state_hash=gateway_final_hash).startswith(
        "PAPERACCOUNTSTATE:"
    )
    return gateway_report, initial_state


def _quote(
    *,
    event_ts: datetime,
    quote_id: str = "QUOTE:S10:ARRIVAL",
    best_bid: Decimal = Decimal("99.98"),
    best_ask: Decimal = Decimal("100.02"),
) -> QuoteEvent:
    return QuoteEvent(
        subscription_id="STREAM:S10:BTCUSD",
        source_id="SOURCE:S10:FIXTURE",
        venue_id=VENUE_ID,
        event_ts=event_ts,
        source_ts=event_ts,
        ingest_ts=START + timedelta(minutes=10),
        raw_payload_id=f"RAW:{quote_id}",
        quote_id=quote_id,
        instrument_id=INSTRUMENT_ID,
        best_bid=best_bid,
        best_ask=best_ask,
    )
