"""Deterministic S5 baselines over DatasetSnapshot rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
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
    _validate_row_order(snapshot.rows)
    lineage_note = "No learned parameters."
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
                    if _is_first_instrument_split_row(snapshot.rows, row)
                    else Decimal("1")
                ),
                config=config,
                label_method=snapshot.label_rule.method,
            )
            for row in snapshot.rows
        )
    elif config.kind is BaselineKind.EQUAL_WEIGHT_BASKET:
        rows = _equal_weight_rows(snapshot=snapshot, config=config)
    elif config.kind is BaselineKind.TA_HEURISTIC:
        rows = _signal_rows(snapshot=snapshot, config=config, policy=_ta_signal)
    elif config.kind is BaselineKind.SIMPLE_ML:
        model = _fit_simple_ml(snapshot=snapshot)
        lineage_note = (
            "Simple ML fit uses train split only; "
            f"feature={model.feature_name}, threshold={model.threshold}, "
            f"train_label_mean={model.positive_label_mean}."
        )
        rows = _signal_rows(
            snapshot=snapshot,
            config=config,
            policy=lambda row: _simple_ml_signal(row=row, model=model),
        )
    else:  # pragma: no cover - exhaustive for StrEnum members, retained for fail-closed safety.
        raise BaselineBuildError(f"unsupported baseline kind: {config.kind}")

    summaries = _summaries(rows)
    cost_assumption = (
        "Uses point-in-time cost feature preference "
        f"{config.cost_feature_preference}; missing cost features default to zero. "
        "round_trip_taker_cost_bps is converted from bps to return units; taker_fee_rate "
        "is used as a return-rate proxy. No S6 slippage/TCA claim is made. "
        f"Config parameters: {config.parameters}. {lineage_note}"
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

    previous_weights: dict[tuple[DatasetSplit, str], Decimal] = {}
    output: list[BaselineRow] = []
    for row in snapshot.rows:
        peers = rows_by_split_ts[(row.split, row.feature_ts.isoformat())]
        target_weight = Decimal("1") / Decimal(len(peers))
        previous_key = (row.split, row.instrument_id)
        previous_weight = previous_weights.get(previous_key, Decimal("0"))
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
        previous_weights[previous_key] = target_weight
    return tuple(output)


def _signal_rows(
    *,
    snapshot: DatasetSnapshot,
    config: BaselineConfig,
    policy: SignalPolicy,
) -> tuple[BaselineRow, ...]:
    previous_weights: dict[tuple[DatasetSplit, str], Decimal] = {}
    output: list[BaselineRow] = []
    for row in snapshot.rows:
        signal = policy(row)
        target_weight = Decimal("1") if signal.trade else Decimal("0")
        previous_key = (row.split, row.instrument_id)
        previous_weight = previous_weights.get(previous_key, Decimal("0"))
        if target_weight < 0 or target_weight > 1:
            raise BaselineBuildError("target weight must be long-only in [0, 1]")
        output.append(
            _invested_row(
                row=row,
                kind=config.kind,
                target_weight=target_weight,
                previous_weight=previous_weight,
                config=config,
                label_method=snapshot.label_rule.method,
                no_trade_reason=signal.no_trade_reason,
            )
        )
        previous_weights[previous_key] = target_weight
    return tuple(output)


def _invested_row(
    *,
    row: DatasetRow,
    kind: BaselineKind,
    target_weight: Decimal,
    previous_weight: Decimal,
    config: BaselineConfig,
    label_method: LabelMethod,
    no_trade_reason: str | None = None,
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
        no_trade_reason=no_trade_reason,
    )


class Signal:
    """Long-only point-in-time signal decision."""

    def __init__(self, *, trade: bool, no_trade_reason: str | None) -> None:
        self.trade = trade
        self.no_trade_reason = no_trade_reason


type SignalPolicy = Callable[[DatasetRow], Signal]


def _ta_signal(row: DatasetRow) -> Signal:
    signal_feature = _first_numeric_feature(row, ("momentum_3", "one_bar_return"))
    if signal_feature is None:
        return Signal(trade=False, no_trade_reason="ta_missing_signal_feature")
    _, value = signal_feature
    if value <= 0:
        return Signal(trade=False, no_trade_reason="ta_non_positive_signal")
    return Signal(trade=True, no_trade_reason=None)


class SimpleMLModel:
    """Pure-Python train-split threshold model lineage."""

    def __init__(
        self, *, feature_name: str, threshold: Decimal, positive_label_mean: Decimal
    ) -> None:
        self.feature_name = feature_name
        self.threshold = threshold
        self.positive_label_mean = positive_label_mean


def _fit_simple_ml(*, snapshot: DatasetSnapshot) -> SimpleMLModel:
    train_rows = tuple(row for row in snapshot.rows if row.split is DatasetSplit.TRAIN)
    if not train_rows:
        raise BaselineBuildError("simple ML baseline requires train split rows")
    feature_name = "one_bar_return"
    train_features = tuple(_numeric_feature(row, feature_name) for row in train_rows)
    usable_rows = tuple(
        (row, value)
        for row, value in zip(train_rows, train_features, strict=True)
        if value is not None
    )
    if not usable_rows:
        raise BaselineBuildError("simple ML baseline requires train split numeric features")
    threshold = sum((value for _, value in usable_rows), Decimal("0")) / Decimal(len(usable_rows))
    train_returns = tuple(
        _realized_return(row=row, label_method=snapshot.label_rule.method) for row, _ in usable_rows
    )
    positive_label_mean = sum(train_returns, Decimal("0")) / Decimal(len(train_returns))
    return SimpleMLModel(
        feature_name=feature_name,
        threshold=threshold,
        positive_label_mean=positive_label_mean,
    )


def _simple_ml_signal(*, row: DatasetRow, model: SimpleMLModel) -> Signal:
    value = _numeric_feature(row, model.feature_name)
    if value is None:
        return Signal(trade=False, no_trade_reason="ml_missing_signal_feature")
    if model.positive_label_mean <= 0:
        return Signal(trade=False, no_trade_reason="ml_train_mean_not_positive")
    if value <= model.threshold:
        return Signal(trade=False, no_trade_reason="ml_below_train_threshold")
    return Signal(trade=True, no_trade_reason=None)


def _first_numeric_feature(
    row: DatasetRow, feature_names: tuple[str, ...]
) -> tuple[str, Decimal] | None:
    for feature_name in feature_names:
        value = _numeric_feature(row, feature_name)
        if value is not None:
            return feature_name, value
    return None


def _numeric_feature(row: DatasetRow, feature_name: str) -> Decimal | None:
    value = row.feature_values.get(feature_name)
    if value is None:
        return None
    return value


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


def _is_first_instrument_split_row(
    rows: tuple[DatasetRow, ...], candidate: DatasetRow
) -> bool:
    for row in rows:
        if row.split is candidate.split and row.instrument_id == candidate.instrument_id:
            return row.row_id == candidate.row_id
    raise BaselineBuildError("candidate row not present in snapshot")


def _validate_row_order(rows: tuple[DatasetRow, ...]) -> None:
    previous_row: DatasetRow | None = None
    for row in rows:
        if previous_row is not None and row.feature_ts < previous_row.feature_ts:
            raise BaselineBuildError("dataset rows must be chronological by feature_ts")
        previous_row = row


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
