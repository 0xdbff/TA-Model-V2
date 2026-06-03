"""Deterministic baseline result contracts.

Traceability:
- FR-007: baseline reports include cash/no-trade, buy-and-hold, and basket outputs.
- FR-014: outputs expose returns, exposure, turnover, and costs for later scorecards.
- NFR-001: decisions use only DatasetRow feature_ts feature values; labels are outcomes.
- NFR-005: deterministic config/result IDs support reproducible reruns.

Scope:
- S5-001 fixture/local baseline outputs only. No orders, simulator gateway, paper/live
  routing, leverage, derivatives, shorting, margin, or autonomous model promotion.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString


class BaselineKind(StrEnum):
    """Supported deterministic S5 baseline families."""

    CASH = "cash_no_trade"
    BUY_AND_HOLD = "buy_and_hold"
    EQUAL_WEIGHT_BASKET = "equal_weight_basket"
    TA_HEURISTIC = "ta_heuristic"
    SIMPLE_ML = "simple_ml"


class BaselineConfig(ContractModel):
    """Reproducible baseline configuration shared by S5 baseline families."""

    baseline_config_id: CanonicalId
    baseline_config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: NonEmptyString
    kind: BaselineKind
    cost_feature_preference: tuple[NonEmptyString, ...] = (
        "round_trip_taker_cost_bps",
        "taker_fee_rate",
    )
    parameters: tuple[NonEmptyString, ...] = ()
    seed: int = 0

    @model_validator(mode="after")
    def config_identity_is_deterministic(self) -> Self:
        expected_hash = build_baseline_config_hash(
            name=self.name,
            kind=self.kind,
            cost_feature_preference=self.cost_feature_preference,
            parameters=self.parameters,
            seed=self.seed,
        )
        if self.baseline_config_hash != expected_hash:
            raise ValueError("baseline_config_hash is not deterministic")
        if self.baseline_config_id != build_baseline_config_id(
            baseline_config_hash=self.baseline_config_hash
        ):
            raise ValueError("baseline_config_id is not deterministic")
        return self


class BaselineRow(ContractModel):
    """One event-time baseline output row for later scorecard consumption."""

    baseline_row_id: CanonicalId
    dataset_row_id: CanonicalId
    split: DatasetSplit
    instrument_id: CanonicalId
    venue_id: CanonicalId
    feature_ts: AwareDatetime
    baseline_kind: BaselineKind
    target_weight: Decimal
    exposure: Decimal
    realized_return: Decimal
    turnover: Decimal
    cost_rate: Decimal = Field(ge=Decimal("0"))
    cost_return: Decimal = Field(ge=Decimal("0"))
    net_return: Decimal
    no_trade_reason: NonEmptyString | None = None

    @model_validator(mode="after")
    def row_identity_is_deterministic(self) -> Self:
        if self.baseline_row_id != build_baseline_row_id(
            dataset_row_id=self.dataset_row_id,
            split=self.split,
            instrument_id=self.instrument_id,
            venue_id=self.venue_id,
            feature_ts=self.feature_ts,
            baseline_kind=self.baseline_kind,
            target_weight=self.target_weight,
            exposure=self.exposure,
            realized_return=self.realized_return,
            turnover=self.turnover,
            cost_rate=self.cost_rate,
            cost_return=self.cost_return,
            net_return=self.net_return,
            no_trade_reason=self.no_trade_reason,
        ):
            raise ValueError("baseline_row_id is not deterministic")
        return self


class BaselineSplitSummary(ContractModel):
    """Minimal per-split/window summary; S5-003 owns full metric scorecards."""

    split: DatasetSplit
    row_count: int = Field(ge=0)
    gross_return_sum: Decimal
    net_return_sum: Decimal
    turnover_sum: Decimal = Field(ge=Decimal("0"))
    cost_return_sum: Decimal = Field(ge=Decimal("0"))
    average_exposure: Decimal


class BaselineReport(ContractModel):
    """Deterministic baseline run artifact with dataset/config lineage."""

    baseline_report_id: CanonicalId
    baseline_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_snapshot_id: CanonicalId
    dataset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    baseline_config: BaselineConfig
    row_ids: tuple[CanonicalId, ...]
    rows: tuple[BaselineRow, ...]
    summaries_by_split: tuple[BaselineSplitSummary, ...]
    cost_assumption: NonEmptyString

    @model_validator(mode="after")
    def report_identity_is_deterministic(self) -> Self:
        if self.row_ids != tuple(row.baseline_row_id for row in self.rows):
            raise ValueError("row_ids must match rows")
        expected_hash = build_baseline_report_hash(
            dataset_snapshot_id=self.dataset_snapshot_id,
            dataset_hash=self.dataset_hash,
            baseline_config=self.baseline_config,
            rows=self.rows,
            summaries_by_split=self.summaries_by_split,
            cost_assumption=self.cost_assumption,
        )
        if self.baseline_report_hash != expected_hash:
            raise ValueError("baseline_report_hash is not deterministic")
        if self.baseline_report_id != build_baseline_report_id(
            baseline_report_hash=self.baseline_report_hash
        ):
            raise ValueError("baseline_report_id is not deterministic")
        return self


def build_baseline_config(
    *,
    name: str,
    kind: BaselineKind,
    cost_feature_preference: tuple[str, ...] = ("round_trip_taker_cost_bps", "taker_fee_rate"),
    parameters: tuple[str, ...] = (),
    seed: int = 0,
) -> BaselineConfig:
    config_hash = build_baseline_config_hash(
        name=name,
        kind=kind,
        cost_feature_preference=cost_feature_preference,
        parameters=parameters,
        seed=seed,
    )
    return BaselineConfig(
        baseline_config_id=build_baseline_config_id(baseline_config_hash=config_hash),
        baseline_config_hash=config_hash,
        name=name,
        kind=kind,
        cost_feature_preference=cost_feature_preference,
        parameters=parameters,
        seed=seed,
    )


def build_baseline_config_hash(
    *,
    name: str,
    kind: BaselineKind,
    cost_feature_preference: tuple[str, ...],
    parameters: tuple[str, ...],
    seed: int,
) -> str:
    return _hash(
        {
            "cost_feature_preference": cost_feature_preference,
            "kind": kind.value,
            "name": name,
            "parameters": parameters,
            "seed": seed,
        }
    )


def build_baseline_config_id(*, baseline_config_hash: str) -> str:
    return _stable_id("BASELINECONFIG", {"baseline_config_hash": baseline_config_hash})


def build_baseline_row_id(
    *,
    dataset_row_id: str,
    split: DatasetSplit,
    instrument_id: str,
    venue_id: str,
    feature_ts: datetime,
    baseline_kind: BaselineKind,
    target_weight: Decimal,
    exposure: Decimal,
    realized_return: Decimal,
    turnover: Decimal,
    cost_rate: Decimal,
    cost_return: Decimal,
    net_return: Decimal,
    no_trade_reason: str | None,
) -> str:
    return _stable_id(
        "BASELINEROW",
        {
            "baseline_kind": baseline_kind.value,
            "cost_rate": str(cost_rate),
            "cost_return": str(cost_return),
            "dataset_row_id": dataset_row_id,
            "exposure": str(exposure),
            "feature_ts": feature_ts.isoformat(),
            "instrument_id": instrument_id,
            "net_return": str(net_return),
            "no_trade_reason": no_trade_reason,
            "realized_return": str(realized_return),
            "split": split.value,
            "target_weight": str(target_weight),
            "turnover": str(turnover),
            "venue_id": venue_id,
        },
    )


def build_baseline_report_hash(
    *,
    dataset_snapshot_id: str,
    dataset_hash: str,
    baseline_config: BaselineConfig,
    rows: tuple[BaselineRow, ...],
    summaries_by_split: tuple[BaselineSplitSummary, ...],
    cost_assumption: str,
) -> str:
    return _hash(
        {
            "baseline_config": _model_json(baseline_config),
            "cost_assumption": cost_assumption,
            "dataset_hash": dataset_hash,
            "dataset_snapshot_id": dataset_snapshot_id,
            "rows": tuple(_model_json(row) for row in rows),
            "summaries_by_split": tuple(_model_json(summary) for summary in summaries_by_split),
        }
    )


def build_baseline_report_id(*, baseline_report_hash: str) -> str:
    return _stable_id("BASELINEREPORT", {"baseline_report_hash": baseline_report_hash})


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}:{_hash(payload)[:32].upper()}"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_json(model: ContractModel) -> object:
    return json.loads(model.model_dump_json())
