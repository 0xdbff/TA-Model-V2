"""Paper accounting/session and TCA builders over S10 gateway evidence."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from ta_model.contracts.execution import (
    ExecutionFillMode,
    ExecutionGatewayKind,
    ExecutionGatewayLifecycleEvent,
    ExecutionGatewayOrderStatus,
    ExecutionGatewayReport,
)
from ta_model.contracts.paper import (
    PaperAccountSessionReport,
    PaperAccountStateSource,
    PaperFillLogEntry,
    PaperOrderLifecycleLogEntry,
    PaperRejectionLogEntry,
    PaperRejectionSource,
    PaperTcaIssue,
    PaperTcaIssueCode,
    PaperTcaIssueSeverity,
    PaperTcaReport,
    PaperTcaRow,
    TcaReferencePriceSource,
    build_paper_account_session_report_hash,
    build_paper_account_session_report_id,
    build_paper_account_state_hash,
    build_paper_account_state_id,
    build_paper_fill_log_hash,
    build_paper_fill_log_id,
    build_paper_order_lifecycle_log_hash,
    build_paper_order_lifecycle_log_id,
    build_paper_rejection_log_hash,
    build_paper_rejection_log_id,
    build_paper_tca_issue_hash,
    build_paper_tca_issue_id,
    build_paper_tca_report_hash,
    build_paper_tca_report_id,
    build_paper_tca_row_hash,
    build_paper_tca_row_id,
)
from ta_model.contracts.simulation import OrderSide, SimulatedAccountState
from ta_model.contracts.streaming import QuoteEvent

_ACCOUNT_REPORT_REQUIREMENTS = ("FR-010", "FR-013", "FR-015", "NFR-004")
_ORDER_LOG_REQUIREMENTS = ("FR-013", "FR-015", "NFR-004")
_FILL_LOG_REQUIREMENTS = ("FR-013", "FR-014", "FR-015")
_REJECTION_LOG_REQUIREMENTS = ("FR-010", "FR-013", "FR-015")
_TCA_REQUIREMENTS = ("FR-013", "FR-014", "US-011")

_FILLED_STATUSES = {
    ExecutionGatewayOrderStatus.FILLED,
    ExecutionGatewayOrderStatus.PARTIALLY_FILLED,
}
_REJECTION_STATUSES = {
    ExecutionGatewayOrderStatus.BLOCKED,
    ExecutionGatewayOrderStatus.REJECTED,
    ExecutionGatewayOrderStatus.UNFILLED,
}


def make_paper_account_session_report(
    *,
    gateway_report: ExecutionGatewayReport,
    initial_account_state: SimulatedAccountState | None = None,
    final_account_state: SimulatedAccountState | None = None,
    initial_account_state_id: str | None = None,
    initial_account_state_hash: str | None = None,
    final_account_state_id: str | None = None,
    final_account_state_hash: str | None = None,
) -> PaperAccountSessionReport:
    """Build deterministic paper account/session logs from gateway/risk evidence.

    The builder accepts gateway evidence and account-state inputs only. It does not
    accept raw order intents or place orders, so the independent risk/gateway seam
    remains mandatory.
    """

    _require_paper_gateway_report(gateway_report)
    initial_id, initial_hash = _resolve_account_state_identity(
        account_state=initial_account_state,
        account_state_id=initial_account_state_id,
        account_state_hash=initial_account_state_hash,
        label="initial",
    )
    resolved_final_state, final_id, final_hash, final_source = _resolve_final_account_state(
        gateway_report=gateway_report,
        initial_account_state=initial_account_state,
        final_account_state=final_account_state,
        final_account_state_id=final_account_state_id,
        final_account_state_hash=final_account_state_hash,
    )
    order_logs = tuple(
        _make_order_lifecycle_log_entry(gateway_report=gateway_report, event=event)
        for event in gateway_report.events
    )
    fill_logs = tuple(
        _make_fill_log_entry(gateway_report=gateway_report, event=event)
        for event in gateway_report.events
        if event.status in _FILLED_STATUSES
    )
    rejection_logs = tuple(
        _make_rejection_log_entry(gateway_report=gateway_report, event=event)
        for event in gateway_report.events
        if event.status in _REJECTION_STATUSES
    )
    draft = PaperAccountSessionReport.model_construct(
        session_report_id="PAPERSESSION:PLACEHOLDER",
        session_report_hash="0" * 64,
        run_id=gateway_report.run_id,
        gateway_report_id=gateway_report.gateway_report_id,
        gateway_report_hash=gateway_report.gateway_report_hash,
        gateway_kind=gateway_report.gateway_kind,
        fill_mode=gateway_report.fill_mode,
        source_risk_gated_replay_result_id=gateway_report.source_risk_gated_replay_result_id,
        source_risk_gated_replay_result_hash=gateway_report.source_risk_gated_replay_result_hash,
        source_replay_report_id=gateway_report.source_replay_report_id,
        source_replay_report_hash=gateway_report.source_replay_report_hash,
        initial_account_state_id=initial_id,
        initial_account_state_hash=initial_hash,
        final_account_state_id=final_id,
        final_account_state_hash=final_hash,
        final_account_state_source=final_source,
        initial_account_state=initial_account_state,
        final_account_state=resolved_final_state,
        order_log_ids=tuple(entry.order_log_id for entry in order_logs),
        fill_log_ids=tuple(entry.fill_log_id for entry in fill_logs),
        rejection_log_ids=tuple(entry.rejection_log_id for entry in rejection_logs),
        order_logs=order_logs,
        fill_logs=fill_logs,
        rejection_logs=rejection_logs,
        total_order_count=len(order_logs),
        filled_order_count=_count_order_logs(order_logs, ExecutionGatewayOrderStatus.FILLED),
        partially_filled_order_count=_count_order_logs(
            order_logs, ExecutionGatewayOrderStatus.PARTIALLY_FILLED
        ),
        blocked_order_count=_count_order_logs(order_logs, ExecutionGatewayOrderStatus.BLOCKED),
        rejected_order_count=_count_order_logs(order_logs, ExecutionGatewayOrderStatus.REJECTED),
        unfilled_order_count=_count_order_logs(order_logs, ExecutionGatewayOrderStatus.UNFILLED),
        filled_quantity_total=sum((entry.filled_quantity for entry in fill_logs), Decimal("0")),
        fee_cost_total=sum((entry.fee_cost for entry in fill_logs), Decimal("0")),
        spread_cost_total=sum((entry.spread_cost for entry in fill_logs), Decimal("0")),
        slippage_cost_total=sum((entry.slippage_cost for entry in fill_logs), Decimal("0")),
        total_execution_cost=sum((entry.total_cost for entry in fill_logs), Decimal("0")),
        requirement_ids=_ACCOUNT_REPORT_REQUIREMENTS,
    )
    report_hash = build_paper_account_session_report_hash(report=draft)
    return PaperAccountSessionReport(
        **draft.model_dump(exclude={"session_report_id", "session_report_hash"}),
        session_report_id=build_paper_account_session_report_id(report_hash=report_hash),
        session_report_hash=report_hash,
    )


def make_paper_tca_report(
    *, gateway_report: ExecutionGatewayReport, quotes: Iterable[QuoteEvent]
) -> PaperTcaReport:
    """Build deterministic paper-fill TCA rows plus explicit issue/error rows."""

    _require_paper_gateway_report(gateway_report)
    quote_tuple = tuple(quotes)
    rows: list[PaperTcaRow] = []
    issues: list[PaperTcaIssue] = []
    for event in gateway_report.events:
        if event.status in _FILLED_STATUSES:
            arrival_quote = _arrival_quote_for_event(event=event, quotes=quote_tuple)
            if arrival_quote is None:
                issues.append(
                    _make_tca_issue(
                        gateway_report=gateway_report,
                        event=event,
                        code=PaperTcaIssueCode.MISSING_ARRIVAL_QUOTE,
                        message=(
                            "no arrival quote at or before submitted_at; "
                            "using replay arrival_reference_price fallback"
                        ),
                    )
                )
            rows.append(
                _make_tca_row(
                    gateway_report=gateway_report,
                    event=event,
                    arrival_quote=arrival_quote,
                )
            )
        elif event.status is ExecutionGatewayOrderStatus.BLOCKED:
            issues.append(
                _make_tca_issue(
                    gateway_report=gateway_report,
                    event=event,
                    code=PaperTcaIssueCode.RISK_BLOCKED,
                    message="risk-blocked/no-trade gateway event has no fill for TCA",
                )
            )
        elif event.status is ExecutionGatewayOrderStatus.REJECTED:
            issues.append(
                _make_tca_issue(
                    gateway_report=gateway_report,
                    event=event,
                    code=PaperTcaIssueCode.GATEWAY_REJECTED,
                    message="gateway replay rejected the approved paper order; no fill for TCA",
                )
            )
        elif event.status is ExecutionGatewayOrderStatus.UNFILLED:
            issues.append(
                _make_tca_issue(
                    gateway_report=gateway_report,
                    event=event,
                    code=PaperTcaIssueCode.GATEWAY_UNFILLED,
                    message=(
                        "gateway replay left the approved paper order unfilled; "
                        "no fill for TCA"
                    ),
                )
            )

    row_tuple = tuple(rows)
    issue_tuple = tuple(issues)
    draft = PaperTcaReport.model_construct(
        tca_report_id="PAPERTCAREPORT:PLACEHOLDER",
        tca_report_hash="0" * 64,
        run_id=gateway_report.run_id,
        gateway_report_id=gateway_report.gateway_report_id,
        gateway_report_hash=gateway_report.gateway_report_hash,
        gateway_kind=gateway_report.gateway_kind,
        fill_mode=gateway_report.fill_mode,
        row_ids=tuple(row.tca_row_id for row in row_tuple),
        issue_ids=tuple(issue.issue_id for issue in issue_tuple),
        rows=row_tuple,
        issues=issue_tuple,
        filled_row_count=len(row_tuple),
        issue_count=len(issue_tuple),
        error_count=sum(
            1 for issue in issue_tuple if issue.severity is PaperTcaIssueSeverity.ERROR
        ),
        fee_cost_total=sum((row.fee_cost for row in row_tuple), Decimal("0")),
        predicted_total_cost=sum((row.predicted_total_cost for row in row_tuple), Decimal("0")),
        realized_total_cost=sum((row.realized_total_cost for row in row_tuple), Decimal("0")),
        total_cost_prediction_error=sum(
            (row.total_cost_prediction_error for row in row_tuple), Decimal("0")
        ),
        requirement_ids=_TCA_REQUIREMENTS,
    )
    report_hash = build_paper_tca_report_hash(report=draft)
    return PaperTcaReport(
        **draft.model_dump(exclude={"tca_report_id", "tca_report_hash"}),
        tca_report_id=build_paper_tca_report_id(report_hash=report_hash),
        tca_report_hash=report_hash,
    )


def _make_order_lifecycle_log_entry(
    *, gateway_report: ExecutionGatewayReport, event: ExecutionGatewayLifecycleEvent
) -> PaperOrderLifecycleLogEntry:
    draft = PaperOrderLifecycleLogEntry.model_construct(
        order_log_id="PAPERORDERLOG:PLACEHOLDER",
        order_log_hash="0" * 64,
        gateway_report_id=gateway_report.gateway_report_id,
        gateway_report_hash=gateway_report.gateway_report_hash,
        gateway_event_id=event.gateway_event_id,
        gateway_event_hash=event.gateway_event_hash,
        gateway_order_id=event.gateway_order_id,
        run_id=event.run_id,
        risk_check_id=event.risk_check_id,
        risk_check_hash=event.risk_check_hash,
        risk_decision=event.risk_decision,
        risk_reason_codes=event.risk_reason_codes,
        client_order_id=event.client_order_id,
        trace_id=event.trace_id,
        source_decision_id=event.source_decision_id,
        instrument_id=event.instrument_id,
        venue_id=event.venue_id,
        side=event.side,
        order_type=event.order_type,
        requested_quantity=event.requested_quantity,
        gateway_quantity=event.gateway_quantity,
        submitted_at=event.submitted_at,
        status=event.status,
        replay_status=event.replay_status,
        replay_reject_reason=event.replay_reject_reason,
        requirement_ids=_ORDER_LOG_REQUIREMENTS,
    )
    entry_hash = build_paper_order_lifecycle_log_hash(entry=draft)
    return PaperOrderLifecycleLogEntry(
        **draft.model_dump(exclude={"order_log_id", "order_log_hash"}),
        order_log_id=build_paper_order_lifecycle_log_id(entry_hash=entry_hash),
        order_log_hash=entry_hash,
    )


def _make_fill_log_entry(
    *, gateway_report: ExecutionGatewayReport, event: ExecutionGatewayLifecycleEvent
) -> PaperFillLogEntry:
    if event.status not in _FILLED_STATUSES:
        raise ValueError("fill logs require filled gateway status")
    if event.gateway_order_id is None or event.replay_order_result_id is None:
        raise ValueError("filled paper events require gateway order and replay result ids")
    if (
        event.fill_price is None
        or event.fill_event_open_ts is None
        or event.fill_event_close_ts is None
        or event.fill_event_source_ts is None
        or event.fill_raw_payload_id is None
        or event.arrival_reference_price is None
        or event.effective_fill_price is None
    ):
        raise ValueError("filled paper events require complete fill attribution")
    draft = PaperFillLogEntry.model_construct(
        fill_log_id="PAPERFILLLOG:PLACEHOLDER",
        fill_log_hash="0" * 64,
        gateway_report_id=gateway_report.gateway_report_id,
        gateway_report_hash=gateway_report.gateway_report_hash,
        gateway_event_id=event.gateway_event_id,
        gateway_event_hash=event.gateway_event_hash,
        gateway_order_id=event.gateway_order_id,
        run_id=event.run_id,
        risk_check_id=event.risk_check_id,
        risk_check_hash=event.risk_check_hash,
        client_order_id=event.client_order_id,
        trace_id=event.trace_id,
        source_decision_id=event.source_decision_id,
        instrument_id=event.instrument_id,
        venue_id=event.venue_id,
        side=event.side,
        order_type=event.order_type,
        status=event.status,
        replay_order_result_id=event.replay_order_result_id,
        fill_price=event.fill_price,
        filled_quantity=event.filled_quantity,
        remaining_quantity=event.remaining_quantity,
        fill_event_open_ts=event.fill_event_open_ts,
        fill_event_close_ts=event.fill_event_close_ts,
        fill_event_source_ts=event.fill_event_source_ts,
        fill_raw_payload_id=event.fill_raw_payload_id,
        cost_model_id=event.cost_model_id,
        cost_model_hash=event.cost_model_hash,
        latency_bars=event.latency_bars,
        eligible_event_index=event.eligible_event_index,
        fill_attempt_event_index=event.fill_attempt_event_index,
        arrival_reference_price=event.arrival_reference_price,
        effective_fill_price=event.effective_fill_price,
        reference_notional=event.reference_notional,
        effective_notional=event.effective_notional,
        fee_cost=event.fee_cost,
        spread_cost=event.spread_cost,
        slippage_cost=event.slippage_cost,
        total_cost=event.total_cost,
        requirement_ids=_FILL_LOG_REQUIREMENTS,
    )
    entry_hash = build_paper_fill_log_hash(entry=draft)
    return PaperFillLogEntry(
        **draft.model_dump(exclude={"fill_log_id", "fill_log_hash"}),
        fill_log_id=build_paper_fill_log_id(entry_hash=entry_hash),
        fill_log_hash=entry_hash,
    )


def _make_rejection_log_entry(
    *, gateway_report: ExecutionGatewayReport, event: ExecutionGatewayLifecycleEvent
) -> PaperRejectionLogEntry:
    if event.status not in _REJECTION_STATUSES:
        raise ValueError("rejection logs require blocked/rejected/unfilled gateway status")
    rejection_source = (
        PaperRejectionSource.RISK
        if event.status is ExecutionGatewayOrderStatus.BLOCKED
        else PaperRejectionSource.GATEWAY_REPLAY
    )
    draft = PaperRejectionLogEntry.model_construct(
        rejection_log_id="PAPERREJECTLOG:PLACEHOLDER",
        rejection_log_hash="0" * 64,
        gateway_report_id=gateway_report.gateway_report_id,
        gateway_report_hash=gateway_report.gateway_report_hash,
        gateway_event_id=event.gateway_event_id,
        gateway_event_hash=event.gateway_event_hash,
        gateway_order_id=event.gateway_order_id,
        run_id=event.run_id,
        risk_check_id=event.risk_check_id,
        risk_check_hash=event.risk_check_hash,
        risk_decision=event.risk_decision,
        risk_reason_codes=event.risk_reason_codes,
        replay_reject_reason=event.replay_reject_reason,
        rejection_source=rejection_source,
        client_order_id=event.client_order_id,
        trace_id=event.trace_id,
        source_decision_id=event.source_decision_id,
        instrument_id=event.instrument_id,
        venue_id=event.venue_id,
        side=event.side,
        order_type=event.order_type,
        requested_quantity=event.requested_quantity,
        gateway_quantity=event.gateway_quantity,
        remaining_quantity=event.remaining_quantity,
        submitted_at=event.submitted_at,
        status=event.status,
        requirement_ids=_REJECTION_LOG_REQUIREMENTS,
    )
    entry_hash = build_paper_rejection_log_hash(entry=draft)
    return PaperRejectionLogEntry(
        **draft.model_dump(exclude={"rejection_log_id", "rejection_log_hash"}),
        rejection_log_id=build_paper_rejection_log_id(entry_hash=entry_hash),
        rejection_log_hash=entry_hash,
    )


def _make_tca_row(
    *,
    gateway_report: ExecutionGatewayReport,
    event: ExecutionGatewayLifecycleEvent,
    arrival_quote: QuoteEvent | None,
) -> PaperTcaRow:
    if event.status not in _FILLED_STATUSES:
        raise ValueError("TCA rows require filled gateway status")
    if event.gateway_order_id is None:
        raise ValueError("TCA rows require gateway order id")
    if (
        event.fill_price is None
        or event.fill_event_open_ts is None
        or event.fill_event_close_ts is None
        or event.fill_event_source_ts is None
        or event.arrival_reference_price is None
    ):
        raise ValueError("TCA rows require filled price and reference attribution")

    arrival_bid = arrival_quote.best_bid if arrival_quote is not None else None
    arrival_ask = arrival_quote.best_ask if arrival_quote is not None else None
    arrival_mid = (
        (arrival_quote.best_bid + arrival_quote.best_ask) / Decimal("2")
        if arrival_quote is not None
        else None
    )
    reference_price = arrival_mid if arrival_mid is not None else event.arrival_reference_price
    reference_source = (
        TcaReferencePriceSource.ARRIVAL_QUOTE_MID
        if arrival_mid is not None
        else TcaReferencePriceSource.REPLAY_ARRIVAL_REFERENCE
    )
    realized_spread_slippage_cost = _adverse_cost(
        side=event.side,
        reference_price=reference_price,
        fill_price=event.fill_price,
        filled_quantity=event.filled_quantity,
    )
    predicted_spread_slippage_cost = event.spread_cost + event.slippage_cost
    predicted_total_cost = event.fee_cost + predicted_spread_slippage_cost
    realized_total_cost = event.fee_cost + realized_spread_slippage_cost
    draft = PaperTcaRow.model_construct(
        tca_row_id="PAPERTCAROW:PLACEHOLDER",
        tca_row_hash="0" * 64,
        gateway_report_id=gateway_report.gateway_report_id,
        gateway_report_hash=gateway_report.gateway_report_hash,
        gateway_event_id=event.gateway_event_id,
        gateway_event_hash=event.gateway_event_hash,
        gateway_order_id=event.gateway_order_id,
        run_id=event.run_id,
        risk_check_id=event.risk_check_id,
        risk_check_hash=event.risk_check_hash,
        client_order_id=event.client_order_id,
        trace_id=event.trace_id,
        source_decision_id=event.source_decision_id,
        instrument_id=event.instrument_id,
        venue_id=event.venue_id,
        side=event.side,
        status=event.status,
        submitted_at=event.submitted_at,
        quote_id=arrival_quote.quote_id if arrival_quote is not None else None,
        quote_event_ts=arrival_quote.event_ts if arrival_quote is not None else None,
        quote_source_ts=arrival_quote.source_ts if arrival_quote is not None else None,
        quote_ingest_ts=arrival_quote.ingest_ts if arrival_quote is not None else None,
        arrival_bid=arrival_bid,
        arrival_ask=arrival_ask,
        arrival_mid=arrival_mid,
        fallback_reference_price=event.arrival_reference_price,
        reference_price_source=reference_source,
        fill_price=event.fill_price,
        filled_quantity=event.filled_quantity,
        fill_event_open_ts=event.fill_event_open_ts,
        fill_event_close_ts=event.fill_event_close_ts,
        fill_event_source_ts=event.fill_event_source_ts,
        fee_cost=event.fee_cost,
        predicted_spread_cost=event.spread_cost,
        predicted_slippage_cost=event.slippage_cost,
        predicted_spread_slippage_cost=predicted_spread_slippage_cost,
        predicted_total_cost=predicted_total_cost,
        realized_spread_slippage_cost=realized_spread_slippage_cost,
        realized_total_cost=realized_total_cost,
        spread_slippage_prediction_error=(
            realized_spread_slippage_cost - predicted_spread_slippage_cost
        ),
        total_cost_prediction_error=realized_total_cost - predicted_total_cost,
        requirement_ids=_TCA_REQUIREMENTS,
    )
    row_hash = build_paper_tca_row_hash(row=draft)
    return PaperTcaRow(
        **draft.model_dump(exclude={"tca_row_id", "tca_row_hash"}),
        tca_row_id=build_paper_tca_row_id(row_hash=row_hash),
        tca_row_hash=row_hash,
    )


def _make_tca_issue(
    *,
    gateway_report: ExecutionGatewayReport,
    event: ExecutionGatewayLifecycleEvent,
    code: PaperTcaIssueCode,
    message: str,
) -> PaperTcaIssue:
    draft = PaperTcaIssue.model_construct(
        issue_id="PAPERTCAISSUE:PLACEHOLDER",
        issue_hash="0" * 64,
        severity=PaperTcaIssueSeverity.ERROR,
        code=code,
        message=message,
        gateway_report_id=gateway_report.gateway_report_id,
        gateway_report_hash=gateway_report.gateway_report_hash,
        gateway_event_id=event.gateway_event_id,
        gateway_event_hash=event.gateway_event_hash,
        run_id=event.run_id,
        risk_check_id=event.risk_check_id,
        client_order_id=event.client_order_id,
        trace_id=event.trace_id,
        instrument_id=event.instrument_id,
        venue_id=event.venue_id,
        status=event.status,
        requirement_ids=_TCA_REQUIREMENTS,
    )
    issue_hash = build_paper_tca_issue_hash(issue=draft)
    return PaperTcaIssue(
        **draft.model_dump(exclude={"issue_id", "issue_hash"}),
        issue_id=build_paper_tca_issue_id(issue_hash=issue_hash),
        issue_hash=issue_hash,
    )


def _arrival_quote_for_event(
    *, event: ExecutionGatewayLifecycleEvent, quotes: tuple[QuoteEvent, ...]
) -> QuoteEvent | None:
    candidates = tuple(
        quote
        for quote in quotes
        if quote.instrument_id == event.instrument_id
        and quote.venue_id == event.venue_id
        and quote.event_ts <= event.submitted_at
    )
    if not candidates:
        return None
    return max(candidates, key=lambda quote: (quote.event_ts, quote.quote_id))


def _adverse_cost(
    *, side: OrderSide, reference_price: Decimal, fill_price: Decimal, filled_quantity: Decimal
) -> Decimal:
    if side is OrderSide.BUY:
        return (fill_price - reference_price) * filled_quantity
    return (reference_price - fill_price) * filled_quantity


def _resolve_account_state_identity(
    *,
    account_state: SimulatedAccountState | None,
    account_state_id: str | None,
    account_state_hash: str | None,
    label: str,
) -> tuple[str, str]:
    if account_state is not None:
        computed_hash = build_paper_account_state_hash(account_state=account_state)
        computed_id = build_paper_account_state_id(account_state_hash=computed_hash)
        if account_state_hash is not None and account_state_hash != computed_hash:
            raise ValueError(f"{label}_account_state_hash does not match embedded state")
        if account_state_id is not None and account_state_id != computed_id:
            raise ValueError(f"{label}_account_state_id does not match embedded state")
        return computed_id, computed_hash
    if account_state_id is None or account_state_hash is None:
        raise ValueError(
            f"{label} account state requires an embedded state or explicit id/hash linkage"
        )
    return account_state_id, account_state_hash


def _resolve_final_account_state(
    *,
    gateway_report: ExecutionGatewayReport,
    initial_account_state: SimulatedAccountState | None,
    final_account_state: SimulatedAccountState | None,
    final_account_state_id: str | None,
    final_account_state_hash: str | None,
) -> tuple[SimulatedAccountState | None, str, str, PaperAccountStateSource]:
    gateway_final_state = gateway_report.source_replay_final_account_state
    if gateway_final_state is not None:
        _raise_if_supplied_final_conflicts_with_gateway(
            gateway_final_state=gateway_final_state,
            final_account_state=final_account_state,
            final_account_state_id=final_account_state_id,
            final_account_state_hash=final_account_state_hash,
        )
        final_hash = build_paper_account_state_hash(account_state=gateway_final_state)
        return (
            gateway_final_state,
            build_paper_account_state_id(account_state_hash=final_hash),
            final_hash,
            PaperAccountStateSource.GATEWAY_REPLAY,
        )

    if _has_filled_events(gateway_report):
        if final_account_state_id is None or final_account_state_hash is None:
            raise ValueError(
                "approved paper fills without replay-derived final account state require "
                "explicit final account-state id/hash linkage"
            )
        if final_account_state is not None:
            supplied_hash = build_paper_account_state_hash(account_state=final_account_state)
            supplied_id = build_paper_account_state_id(account_state_hash=supplied_hash)
            if final_account_state_hash != supplied_hash or final_account_state_id != supplied_id:
                raise ValueError(
                    "explicit final account-state linkage conflicts with supplied state"
                )
        return (
            final_account_state,
            final_account_state_id,
            final_account_state_hash,
            PaperAccountStateSource.EXPLICIT_LINKAGE,
        )

    if (
        final_account_state is not None
        or final_account_state_id is not None
        or final_account_state_hash is not None
    ):
        final_id, final_hash = _resolve_account_state_identity(
            account_state=final_account_state,
            account_state_id=final_account_state_id,
            account_state_hash=final_account_state_hash,
            label="final",
        )
        return final_account_state, final_id, final_hash, PaperAccountStateSource.EXPLICIT_LINKAGE

    if initial_account_state is None:
        raise ValueError(
            "unchanged paper accounting requires initial account state or explicit final linkage"
        )
    initial_hash = build_paper_account_state_hash(account_state=initial_account_state)
    return (
        initial_account_state,
        build_paper_account_state_id(account_state_hash=initial_hash),
        initial_hash,
        PaperAccountStateSource.UNCHANGED_FROM_INITIAL,
    )


def _raise_if_supplied_final_conflicts_with_gateway(
    *,
    gateway_final_state: SimulatedAccountState,
    final_account_state: SimulatedAccountState | None,
    final_account_state_id: str | None,
    final_account_state_hash: str | None,
) -> None:
    gateway_final_hash = build_paper_account_state_hash(account_state=gateway_final_state)
    gateway_final_id = build_paper_account_state_id(account_state_hash=gateway_final_hash)
    if final_account_state is not None:
        supplied_hash = build_paper_account_state_hash(account_state=final_account_state)
        if supplied_hash != gateway_final_hash:
            raise ValueError("supplied final account state conflicts with gateway-derived state")
    if final_account_state_hash is not None and final_account_state_hash != gateway_final_hash:
        raise ValueError("supplied final account state hash conflicts with gateway-derived state")
    if final_account_state_id is not None and final_account_state_id != gateway_final_id:
        raise ValueError("supplied final account state id conflicts with gateway-derived state")


def _has_filled_events(gateway_report: ExecutionGatewayReport) -> bool:
    return any(event.status in _FILLED_STATUSES for event in gateway_report.events)


def _require_paper_gateway_report(gateway_report: ExecutionGatewayReport) -> None:
    if gateway_report.gateway_kind is not ExecutionGatewayKind.PAPER:
        raise ValueError("paper accounting/TCA builders require paper gateway reports")
    if gateway_report.fill_mode is not ExecutionFillMode.PAPER_SIMULATED_FILL:
        raise ValueError("paper accounting/TCA builders require paper_simulated_fill reports")


def _count_order_logs(
    order_logs: tuple[PaperOrderLifecycleLogEntry, ...], status: ExecutionGatewayOrderStatus
) -> int:
    return sum(1 for entry in order_logs if entry.status is status)
