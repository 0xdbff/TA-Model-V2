"""Simulation and event-time replay contracts.

Traceability:
- FR-012: historical replay consumes validated market data by event-time availability
  and can attribute fees, spread, slippage, latency, partial fills, and failed fills.
- NFR-001: replay prohibits same-bar/lookahead fills and records deterministic evidence.
- RISK-005: explicit execution-cost configuration prevents fee/slippage underestimation
  from being hidden in gross-only backtests.

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
    NonNegativeDecimal,
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
    PARTIALLY_FILLED = "partially_filled"
    UNFILLED = "unfilled"
    REJECTED = "rejected"


class ReplayRejectReason(StrEnum):
    """Machine-readable fail-closed replay reasons."""

    UNSUPPORTED_ORDER_TYPE = "unsupported_order_type"
    NO_FUTURE_ELIGIBLE_EVENT = "no_future_eligible_event"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"


class ExecutionCostModel(ContractModel):
    """Deterministic OHLCTV execution-cost assumptions for S6-002 replay.

    Rates are deliberately explicit and conservative rather than inferred from
    undocumented venue state.  S6-003 owns venue/cash/inventory enforcement; this
    contract only controls simulated fill/cost realism.
    """

    cost_model_id: CanonicalId
    taker_fee_rate: NonNegativeDecimal = Field(
        description="Taker fee fraction applied to effective filled notional."
    )
    spread_bps: NonNegativeDecimal = Field(
        description="Half-spread style adverse price adjustment in basis points."
    )
    slippage_bps: NonNegativeDecimal = Field(
        description="Additional adverse price adjustment in basis points."
    )
    latency_bars: int = Field(
        default=0,
        ge=0,
        description="Number of future eligible OHLCTV bars to skip before fill attempt.",
    )
    max_participation_rate: Decimal = Field(
        gt=Decimal("0"),
        le=Decimal("1"),
        description="Maximum fraction of eligible bar base_volume available to this order.",
    )
    allow_partial_fills: bool = True

    @model_validator(mode="after")
    def cost_model_identity_is_deterministic(self) -> Self:
        if self.spread_bps + self.slippage_bps >= Decimal("10000"):
            raise ValueError("spread_bps plus slippage_bps must be below 10000")
        if self.cost_model_id != build_execution_cost_model_id(model=self):
            raise ValueError("cost_model_id is not deterministic")
        return self

    @property
    def cost_model_hash(self) -> str:
        return build_execution_cost_model_hash(model=self)


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
    remaining_quantity: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    fill_event_open_ts: AwareDatetime | None = None
    fill_event_close_ts: AwareDatetime | None = None
    fill_event_source_ts: AwareDatetime | None = None
    fill_raw_payload_id: CanonicalId | None = None
    cost_model_id: CanonicalId | None = None
    cost_model_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    latency_bars: int = Field(default=0, ge=0)
    eligible_event_index: int | None = Field(default=None, ge=0)
    fill_attempt_event_index: int | None = Field(default=None, ge=0)
    arrival_reference_price: Decimal | None = Field(default=None, ge=Decimal("0"))
    effective_fill_price: Decimal | None = Field(default=None, ge=Decimal("0"))
    reference_notional: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    effective_notional: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    fee_cost: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    spread_cost: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    slippage_cost: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    total_cost: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))

    @model_validator(mode="after")
    def result_is_consistent_and_deterministic(self) -> Self:
        if self.remaining_quantity != self.quantity - self.filled_quantity:
            raise ValueError("remaining_quantity must equal quantity minus filled_quantity")
        if self.status in {ReplayFillStatus.FILLED, ReplayFillStatus.PARTIALLY_FILLED}:
            if self.reason is not None:
                raise ValueError("filled replay result must not set reason")
            if self.fill_price is None or self.fill_price <= 0:
                raise ValueError("filled replay result requires positive fill_price")
            if self.status is ReplayFillStatus.FILLED and self.filled_quantity != self.quantity:
                raise ValueError("filled replay result must fill full market quantity")
            if self.status is ReplayFillStatus.PARTIALLY_FILLED and not (
                Decimal("0") < self.filled_quantity < self.quantity
            ):
                raise ValueError("partially filled replay result requires partial quantity")
            if (
                self.fill_event_open_ts is None
                or self.fill_event_close_ts is None
                or self.fill_event_source_ts is None
                or self.fill_raw_payload_id is None
            ):
                raise ValueError("filled replay result requires fill event lineage")
            if (
                self.effective_fill_price is not None
                and self.effective_fill_price != self.fill_price
            ):
                raise ValueError("effective_fill_price must match fill_price when present")
        else:
            if self.reason is None:
                raise ValueError("unfilled/rejected replay result requires reason")
            if self.fill_price is not None or self.filled_quantity != 0:
                raise ValueError("unfilled/rejected replay result must not carry a fill")
            if self.remaining_quantity != self.quantity:
                raise ValueError(
                    "unfilled/rejected replay result must leave full quantity remaining"
                )
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
            "arrival_reference_price": _decimal(result.arrival_reference_price),
            "cost_model_hash": result.cost_model_hash,
            "cost_model_id": result.cost_model_id,
            "effective_fill_price": _decimal(result.effective_fill_price),
            "effective_notional": str(result.effective_notional),
            "eligible_event_index": result.eligible_event_index,
            "fee_cost": str(result.fee_cost),
            "fill_raw_payload_id": result.fill_raw_payload_id,
            "fill_attempt_event_index": result.fill_attempt_event_index,
            "filled_quantity": str(result.filled_quantity),
            "instrument_id": result.instrument_id,
            "latency_bars": result.latency_bars,
            "order_type": result.order_type.value,
            "quantity": str(result.quantity),
            "reference_notional": str(result.reference_notional),
            "remaining_quantity": str(result.remaining_quantity),
            "reason": result.reason.value if result.reason is not None else None,
            "side": result.side.value,
            "slippage_cost": str(result.slippage_cost),
            "source_decision_id": result.source_decision_id,
            "spread_cost": str(result.spread_cost),
            "status": result.status.value,
            "submitted_at": result.submitted_at.isoformat(),
            "total_cost": str(result.total_cost),
            "trace_id": result.trace_id,
            "venue_id": result.venue_id,
        },
    )


def build_execution_cost_model_hash(*, model: ExecutionCostModel) -> str:
    return _hash(
        {
            "allow_partial_fills": model.allow_partial_fills,
            "latency_bars": model.latency_bars,
            "max_participation_rate": str(model.max_participation_rate),
            "slippage_bps": str(model.slippage_bps),
            "spread_bps": str(model.spread_bps),
            "taker_fee_rate": str(model.taker_fee_rate),
        }
    )


def build_execution_cost_model_id(*, model: ExecutionCostModel) -> str:
    return _stable_id("COSTMODEL", build_execution_cost_model_hash(model=model))


def make_execution_cost_model(
    *,
    taker_fee_rate: Decimal,
    spread_bps: Decimal,
    slippage_bps: Decimal,
    latency_bars: int = 0,
    max_participation_rate: Decimal = Decimal("1"),
    allow_partial_fills: bool = True,
) -> ExecutionCostModel:
    """Build a cost model with deterministic id from its explicit assumptions."""

    draft = ExecutionCostModel.model_construct(
        cost_model_id="COSTMODEL:PLACEHOLDER",
        taker_fee_rate=taker_fee_rate,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        latency_bars=latency_bars,
        max_participation_rate=max_participation_rate,
        allow_partial_fills=allow_partial_fills,
    )
    return ExecutionCostModel(
        **draft.model_dump(exclude={"cost_model_id"}),
        cost_model_id=build_execution_cost_model_id(model=draft),
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
