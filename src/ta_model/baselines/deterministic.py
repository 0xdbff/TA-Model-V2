"""Cash, buy-and-hold, and equal-weight basket baselines over DatasetSnapshot rows."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from ta_model.contracts.baselines import (
    BaselineConfig,
    BaselineKind,
    BaselineReport,
    BaselineRow,
    BaselineSplitSummary,
    build_baseline_report_hash,
    build_baseline_report_id,
    build_baseline_row_id,
)
from ta_model.contracts.datasets import DatasetRow, DatasetSnapshot, DatasetSplit, LabelMethod


class BaselineBuildError(ValueError):
    """Raised when deterministic baseline inputs cannot be evaluated safely."""


def run_baseline(snapshot: DatasetSnapshot, config: BaselineConfig) -> BaselineReport:
    """Run one deterministic baseline over a chronological dataset snapshot.

    Position decisions use row feature values available at ``feature_ts``. Future labels are
    consumed only as realized outcomes for the already-selected deterministic exposure.
    """

    if not snapshot.rows:
        raise BaselineBuildError("at least one dataset row is required")
    if config.kind is BaselineKind.CASH:
        rows = tuple(_cash_row(row) for row in snapshot.rows)
    elif config.kind is BaselineKind.BUY_AND_HOLD:
        rows = tuple(
            _invested_row(
                row=row,
                kind=config.kind,
                target_weight=Decimal("1"),
                previous_weight=(
                    Decimal("0")
                    if _is_first_instrument_row(snapshot.rows, row)
                    else Decimal("1")
                ),
                config=config,
                label_method=snapshot.label_rule.method,
            )
            for row in snapshot.rows
        )
    elif config.kind is BaselineKind.EQUAL_WEIGHT_BASKET:
        rows = _equal_weight_rows(snapshot=snapshot, config=config)
    else:  # pragma: no cover - exhaustive for StrEnum members, retained for fail-closed safety.
        raise BaselineBuildError(f"unsupported baseline kind: {config.kind}")

    summaries = _summaries(rows)
    cost_assumption = (
        "Uses point-in-time cost feature preference "
        f"{config.cost_feature_preference}; missing cost features default to zero. "
        "round_trip_taker_cost_bps is converted from bps to return units; taker_fee_rate "
        "is used as a return-rate proxy. No S6 slippage/TCA claim is made."
    )
    report_hash = build_baseline_report_hash(
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        dataset_hash=snapshot.dataset_hash,
        baseline_config=config,
        rows=rows,
        summaries_by_split=summaries,
        cost_assumption=cost_assumption,
    )
    return BaselineReport(
        baseline_report_id=build_baseline_report_id(baseline_report_hash=report_hash),
        baseline_report_hash=report_hash,
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        dataset_hash=snapshot.dataset_hash,
        baseline_config=config,
        row_ids=tuple(row.baseline_row_id for row in rows),
        rows=rows,
        summaries_by_split=summaries,
        cost_assumption=cost_assumption,
    )


def _cash_row(row: DatasetRow) -> BaselineRow:
    realized_return = Decimal("0")
    return _build_row(
        row=row,
        kind=BaselineKind.CASH,
        target_weight=Decimal("0"),
        realized_return=realized_return,
        turnover=Decimal("0"),
        cost_rate=Decimal("0"),
        no_trade_reason="cash_no_trade_baseline",
    )


def _equal_weight_rows(
    *, snapshot: DatasetSnapshot, config: BaselineConfig
) -> tuple[BaselineRow, ...]:
    rows_by_split_ts: dict[tuple[DatasetSplit, str], list[DatasetRow]] = defaultdict(list)
    for row in snapshot.rows:
        rows_by_split_ts[(row.split, row.feature_ts.isoformat())].append(row)

    previous_weights: dict[str, Decimal] = {}
    output: list[BaselineRow] = []
    for row in snapshot.rows:
        peers = rows_by_split_ts[(row.split, row.feature_ts.isoformat())]
        target_weight = Decimal("1") / Decimal(len(peers))
        previous_weight = previous_weights.get(row.instrument_id, Decimal("0"))
        output.append(
            _invested_row(
                row=row,
                kind=BaselineKind.EQUAL_WEIGHT_BASKET,
                target_weight=target_weight,
                previous_weight=previous_weight,
                config=config,
                label_method=snapshot.label_rule.method,
            )
        )
        previous_weights[row.instrument_id] = target_weight
    return tuple(output)


def _invested_row(
    *,
    row: DatasetRow,
    kind: BaselineKind,
    target_weight: Decimal,
    previous_weight: Decimal,
    config: BaselineConfig,
    label_method: LabelMethod,
) -> BaselineRow:
    turnover = abs(target_weight - previous_weight)
    cost_rate = _cost_rate(row=row, config=config)
    return _build_row(
        row=row,
        kind=kind,
        target_weight=target_weight,
        realized_return=_realized_return(row=row, label_method=label_method),
        turnover=turnover,
        cost_rate=cost_rate,
        no_trade_reason=None,
    )


def _build_row(
    *,
    row: DatasetRow,
    kind: BaselineKind,
    target_weight: Decimal,
    realized_return: Decimal,
    turnover: Decimal,
    cost_rate: Decimal,
    no_trade_reason: str | None,
) -> BaselineRow:
    exposure = abs(target_weight)
    cost_return = turnover * cost_rate
    net_return = (target_weight * realized_return) - cost_return
    baseline_row_id = build_baseline_row_id(
        dataset_row_id=row.row_id,
        split=row.split,
        instrument_id=row.instrument_id,
        venue_id=row.venue_id,
        feature_ts=row.feature_ts,
        baseline_kind=kind,
        target_weight=target_weight,
        exposure=exposure,
        realized_return=realized_return,
        turnover=turnover,
        cost_rate=cost_rate,
        cost_return=cost_return,
        net_return=net_return,
        no_trade_reason=no_trade_reason,
    )
    return BaselineRow(
        baseline_row_id=baseline_row_id,
        dataset_row_id=row.row_id,
        split=row.split,
        instrument_id=row.instrument_id,
        venue_id=row.venue_id,
        feature_ts=row.feature_ts,
        baseline_kind=kind,
        target_weight=target_weight,
        exposure=exposure,
        realized_return=realized_return,
        turnover=turnover,
        cost_rate=cost_rate,
        cost_return=cost_return,
        net_return=net_return,
        no_trade_reason=no_trade_reason,
    )


def _realized_return(*, row: DatasetRow, label_method: LabelMethod) -> Decimal:
    if label_method is LabelMethod.FUTURE_RETURN:
        return row.label_value
    close = row.feature_values.get("close")
    if close is None:
        raise BaselineBuildError("close feature is required for future-value labels")
    if close <= 0:
        raise BaselineBuildError("close feature must be positive when present")
    return (row.label_value / close) - Decimal("1")


def _cost_rate(*, row: DatasetRow, config: BaselineConfig) -> Decimal:
    for feature_name in config.cost_feature_preference:
        value = row.feature_values.get(feature_name)
        if value is None:
            continue
        if value < 0:
            raise BaselineBuildError("cost feature must be non-negative")
        if feature_name.endswith("_bps"):
            return value / Decimal("10000")
        return value
    return Decimal("0")


def _is_first_instrument_row(rows: tuple[DatasetRow, ...], candidate: DatasetRow) -> bool:
    for row in rows:
        if row.instrument_id == candidate.instrument_id:
            return row.row_id == candidate.row_id
    raise BaselineBuildError("candidate row not present in snapshot")


def _summaries(rows: tuple[BaselineRow, ...]) -> tuple[BaselineSplitSummary, ...]:
    summaries: list[BaselineSplitSummary] = []
    for split in DatasetSplit:
        split_rows = tuple(row for row in rows if row.split is split)
        row_count = len(split_rows)
        if row_count == 0:
            summaries.append(
                BaselineSplitSummary(
                    split=split,
                    row_count=0,
                    gross_return_sum=Decimal("0"),
                    net_return_sum=Decimal("0"),
                    turnover_sum=Decimal("0"),
                    cost_return_sum=Decimal("0"),
                    average_exposure=Decimal("0"),
                )
            )
            continue
        summaries.append(
            BaselineSplitSummary(
                split=split,
                row_count=row_count,
                gross_return_sum=sum(
                    (row.target_weight * row.realized_return for row in split_rows), Decimal("0")
                ),
                net_return_sum=sum((row.net_return for row in split_rows), Decimal("0")),
                turnover_sum=sum((row.turnover for row in split_rows), Decimal("0")),
                cost_return_sum=sum((row.cost_return for row in split_rows), Decimal("0")),
                average_exposure=sum((row.exposure for row in split_rows), Decimal("0"))
                / Decimal(row_count),
            )
        )
    return tuple(summaries)
