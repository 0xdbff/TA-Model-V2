"""Simulation and event-time replay contracts.

Traceability:
- FR-012: historical replay consumes validated market data by event-time availability.
- NFR-001: replay prohibits same-bar/lookahead fills and records deterministic evidence.

Scope:
- S6-001 implements a minimal OHLCTV historical replay foundation only.
- No paper/live gateway, risk engine, costs/slippage model, leverage, derivatives,
  margin, shorting, market making, HFT, or live capital path is introduced.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.instrument_master import (
    CanonicalId,
    ContractModel,
    NonEmptyString,
    OrderType,
    PositiveDecimal,
)


class OrderSide(StrEnum):
    """Spot order side understood by simulator and future gateway contracts."""

    BUY = "buy"
    SELL = "sell"


class ReplayFillStatus(StrEnum):
    """Replay outcome state for one order intent."""

    FILLED = "filled"
    UNFILLED = "unfilled"
    REJECTED = "rejected"


class ReplayRejectReason(StrEnum):
    """Machine-readable fail-closed replay reasons."""

    UNSUPPORTED_ORDER_TYPE = "unsupported_order_type"
    NO_FUTURE_ELIGIBLE_EVENT = "no_future_eligible_event"


class OrderIntent(ContractModel):
    """Auditable order intent emitted by a strategy decision for historical replay."""

    client_order_id: CanonicalId
    trace_id: CanonicalId
    source_decision_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    side: OrderSide
    order_type: OrderType
    quantity: PositiveDecimal
    submitted_at: AwareDatetime = Field(
        description="Event-time submission after the source decision became market-available."
    )
    limit_price: PositiveDecimal | None = None

    @model_validator(mode="after")
    def order_type_fields_are_consistent(self) -> Self:
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market orders must not set limit_price")
        if self.order_type is not OrderType.MARKET and self.limit_price is None:
            raise ValueError("limit-style orders require limit_price")
        return self


class ReplayOrderResult(ContractModel):
    """Deterministic replay result for one order intent."""

    replay_order_result_id: CanonicalId
    client_order_id: CanonicalId
    trace_id: CanonicalId
    source_decision_id: CanonicalId
    instrument_id: CanonicalId
    venue_id: CanonicalId
    side: OrderSide
    order_type: OrderType
    quantity: PositiveDecimal
    submitted_at: AwareDatetime
    status: ReplayFillStatus
    reason: ReplayRejectReason | None = None
    fill_price: Decimal | None = Field(default=None, ge=Decimal("0"))
    filled_quantity: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    fill_event_open_ts: AwareDatetime | None = None
    fill_event_close_ts: AwareDatetime | None = None
    fill_event_source_ts: AwareDatetime | None = None
    fill_raw_payload_id: CanonicalId | None = None

    @model_validator(mode="after")
    def result_is_consistent_and_deterministic(self) -> Self:
        if self.status is ReplayFillStatus.FILLED:
            if self.reason is not None:
                raise ValueError("filled replay result must not set reason")
            if self.fill_price is None or self.fill_price <= 0:
                raise ValueError("filled replay result requires positive fill_price")
            if self.filled_quantity != self.quantity:
                raise ValueError("filled replay result must fill full market quantity")
            if (
                self.fill_event_open_ts is None
                or self.fill_event_close_ts is None
                or self.fill_event_source_ts is None
                or self.fill_raw_payload_id is None
            ):
                raise ValueError("filled replay result requires fill event lineage")
        else:
            if self.reason is None:
                raise ValueError("unfilled/rejected replay result requires reason")
            if self.fill_price is not None or self.filled_quantity != 0:
                raise ValueError("unfilled/rejected replay result must not carry a fill")
        if self.replay_order_result_id != build_replay_order_result_id(result=self):
            raise ValueError("replay_order_result_id is not deterministic")
        return self


class ReplayReport(ContractModel):
    """Deterministic S6 replay evidence artifact."""

    replay_report_id: CanonicalId
    replay_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: CanonicalId
    market_data_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    result_ids: tuple[CanonicalId, ...]
    results: tuple[ReplayOrderResult, ...]
    requirement_ids: tuple[NonEmptyString, ...] = ("FR-012", "NFR-001")

    @model_validator(mode="after")
    def report_identity_is_deterministic(self) -> Self:
        if self.result_ids != tuple(result.replay_order_result_id for result in self.results):
            raise ValueError("result_ids must match results")
        expected_hash = build_replay_report_hash(
            run_id=self.run_id,
            market_data_hash=self.market_data_hash,
            results=self.results,
            requirement_ids=self.requirement_ids,
        )
        if self.replay_report_hash != expected_hash:
            raise ValueError("replay_report_hash is not deterministic")
        if self.replay_report_id != build_replay_report_id(
            replay_report_hash=self.replay_report_hash
        ):
            raise ValueError("replay_report_id is not deterministic")
        return self


def build_replay_order_result_id(*, result: ReplayOrderResult) -> str:
    return _stable_id(
        "REPLAYORDER",
        {
            "client_order_id": result.client_order_id,
            "fill_event_close_ts": _iso(result.fill_event_close_ts),
            "fill_event_open_ts": _iso(result.fill_event_open_ts),
            "fill_event_source_ts": _iso(result.fill_event_source_ts),
            "fill_price": _decimal(result.fill_price),
            "fill_raw_payload_id": result.fill_raw_payload_id,
            "filled_quantity": str(result.filled_quantity),
            "instrument_id": result.instrument_id,
            "order_type": result.order_type.value,
            "quantity": str(result.quantity),
            "reason": result.reason.value if result.reason is not None else None,
            "side": result.side.value,
            "source_decision_id": result.source_decision_id,
            "status": result.status.value,
            "submitted_at": result.submitted_at.isoformat(),
            "trace_id": result.trace_id,
            "venue_id": result.venue_id,
        },
    )


def build_replay_report_hash(
    *,
    run_id: str,
    market_data_hash: str,
    results: tuple[ReplayOrderResult, ...],
    requirement_ids: tuple[str, ...],
) -> str:
    return _hash(
        {
            "market_data_hash": market_data_hash,
            "requirement_ids": requirement_ids,
            "results": tuple(_model_json(result) for result in results),
            "run_id": run_id,
        }
    )


def build_replay_report_id(*, replay_report_hash: str) -> str:
    return _stable_id("REPLAYREPORT", {"replay_report_hash": replay_report_hash})


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
