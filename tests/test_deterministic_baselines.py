"""Evidence for S5-001 deterministic baseline contracts and runners."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ta_model.baselines.deterministic import BaselineBuildError, run_baseline
from ta_model.contracts.baselines import BaselineKind, build_baseline_config
from ta_model.contracts.datasets import (
    ChronologicalSplitWindow,
    DatasetRow,
    DatasetSnapshot,
    DatasetSplit,
    LabelMethod,
    LabelRule,
    build_dataset_hash,
    build_dataset_row_id,
    build_dataset_snapshot_id,
    build_label_rule,
)
from ta_model.contracts.features import FeatureValue, build_feature_vector_id

START = datetime(2026, 1, 1, tzinfo=UTC)
VENUE_ID = "FIXTURE_SPOT"
FEATURE_VERSION = "s5-baseline-fixture-1.0.0"
SOURCE_FEATURE_SNAPSHOT_ID = "FEATURESNAPSHOT:S5-001"


def _snapshot(
    *,
    instruments: tuple[str, ...] = ("FIXTURE_SPOT:BTC-USD",),
    closes: tuple[str, ...] = ("100", "101", "102"),
    label_values: tuple[str, ...] = ("101", "102", "103"),
    label_method: LabelMethod = LabelMethod.FUTURE_VALUE,
    extra_values: dict[str, FeatureValue] | None = None,
) -> DatasetSnapshot:
    label_rule = build_label_rule(name="future_1m", horizon_seconds=60, method=label_method)
    rows: list[DatasetRow] = []
    for index, (close, label_value) in enumerate(zip(closes, label_values, strict=True)):
        feature_ts = START + timedelta(minutes=index)
        split = (
            DatasetSplit.TRAIN
            if index == 0
            else DatasetSplit.VALIDATION
            if index == 1
            else DatasetSplit.TEST
        )
        for instrument_id in instruments:
            values: dict[str, FeatureValue] = {"close": Decimal(close)}
            if extra_values is not None:
                values.update(extra_values)
            input_snapshot_id = f"FEATUREINPUT:S5-001:{instrument_id}:{index}"
            feature_vector_id = build_feature_vector_id(
                instrument_id=instrument_id,
                venue_id=VENUE_ID,
                feature_ts=feature_ts,
                feature_version=FEATURE_VERSION,
                lookback_window="fixture-3-bars",
                values=values,
                input_snapshot_id=input_snapshot_id,
                quality_flags=(),
            )
            label_ts = feature_ts + timedelta(minutes=1)
            label_observation_id = f"LABELOBS:S5-001:{instrument_id}:{index}"
            row_id = build_dataset_row_id(
                feature_vector_id=feature_vector_id,
                instrument_id=instrument_id,
                venue_id=VENUE_ID,
                feature_ts=feature_ts,
                feature_version=FEATURE_VERSION,
                feature_values=values,
                feature_input_snapshot_id=input_snapshot_id,
                split=split,
                label_rule_id=label_rule.label_rule_id,
                label_value=Decimal(label_value),
                label_ts=label_ts,
                label_observation_id=label_observation_id,
                source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
            )
            rows.append(
                DatasetRow(
                    row_id=row_id,
                    feature_vector_id=feature_vector_id,
                    instrument_id=instrument_id,
                    venue_id=VENUE_ID,
                    feature_ts=feature_ts,
                    feature_version=FEATURE_VERSION,
                    feature_values=values,
                    feature_input_snapshot_id=input_snapshot_id,
                    split=split,
                    label_rule_id=label_rule.label_rule_id,
                    label_value=Decimal(label_value),
                    label_ts=label_ts,
                    label_observation_id=label_observation_id,
                    source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
                )
            )
    return _build_snapshot(rows=tuple(rows), label_rule=label_rule)


def _build_snapshot(*, rows: tuple[DatasetRow, ...], label_rule: LabelRule) -> DatasetSnapshot:
    split_windows = (
        ChronologicalSplitWindow(
            split=DatasetSplit.TRAIN,
            start_ts=START,
            end_ts=START + timedelta(minutes=1),
        ),
        ChronologicalSplitWindow(
            split=DatasetSplit.VALIDATION,
            start_ts=START + timedelta(minutes=1),
            end_ts=START + timedelta(minutes=2),
        ),
        ChronologicalSplitWindow(
            split=DatasetSplit.TEST,
            start_ts=START + timedelta(minutes=2),
            end_ts=START + timedelta(minutes=3),
        ),
    )
    dataset_hash = build_dataset_hash(
        rows=rows,
        split_windows=split_windows,
        label_rule=label_rule,
        source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
    )
    return DatasetSnapshot(
        dataset_snapshot_id=build_dataset_snapshot_id(dataset_hash=dataset_hash),
        dataset_hash=dataset_hash,
        feature_versions=(FEATURE_VERSION,),
        feature_vector_ids=tuple(row.feature_vector_id for row in rows),
        source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
        split_windows=split_windows,
        label_rule=label_rule,
        row_ids=tuple(row.row_id for row in rows),
        row_counts_by_split={
            DatasetSplit.TRAIN: sum(row.split is DatasetSplit.TRAIN for row in rows),
            DatasetSplit.VALIDATION: sum(row.split is DatasetSplit.VALIDATION for row in rows),
            DatasetSplit.TEST: sum(row.split is DatasetSplit.TEST for row in rows),
        },
        rows=rows,
    )


def test_cash_no_trade_baseline_is_explicit_zero_exposure_turnover_and_cost() -> None:
    report = run_baseline(
        _snapshot(), build_baseline_config(name="cash", kind=BaselineKind.CASH)
    )

    assert {row.target_weight for row in report.rows} == {Decimal("0")}
    assert {row.exposure for row in report.rows} == {Decimal("0")}
    assert {row.turnover for row in report.rows} == {Decimal("0")}
    assert {row.cost_return for row in report.rows} == {Decimal("0")}
    assert {row.net_return for row in report.rows} == {Decimal("0")}
    assert {row.no_trade_reason for row in report.rows} == {"cash_no_trade_baseline"}


def test_buy_and_hold_uses_event_time_rows_and_point_in_time_cost_feature() -> None:
    report = run_baseline(
        _snapshot(extra_values={"round_trip_taker_cost_bps": Decimal("10")}),
        build_baseline_config(name="buy-hold", kind=BaselineKind.BUY_AND_HOLD),
    )

    assert report.rows[0].target_weight == Decimal("1")
    assert report.rows[0].turnover == Decimal("1")
    assert report.rows[0].cost_rate == Decimal("0.001")
    assert report.rows[0].realized_return == Decimal("0.01")
    assert report.rows[0].net_return == Decimal("0.009")
    assert report.rows[1].turnover == Decimal("0")


def test_missing_cost_features_default_to_zero_without_claiming_tca() -> None:
    report = run_baseline(
        _snapshot(), build_baseline_config(name="buy-hold", kind=BaselineKind.BUY_AND_HOLD)
    )

    assert {row.cost_rate for row in report.rows} == {Decimal("0")}
    assert "No S6 slippage/TCA claim" in report.cost_assumption


def test_equal_weight_basket_allocates_deterministically_across_instruments() -> None:
    report = run_baseline(
        _snapshot(instruments=("FIXTURE_SPOT:BTC-USD", "FIXTURE_SPOT:ETH-USD")),
        build_baseline_config(name="equal-weight", kind=BaselineKind.EQUAL_WEIGHT_BASKET),
    )

    train_rows = tuple(row for row in report.rows if row.split is DatasetSplit.TRAIN)
    assert [row.instrument_id for row in train_rows] == [
        "FIXTURE_SPOT:BTC-USD",
        "FIXTURE_SPOT:ETH-USD",
    ]
    assert {row.target_weight for row in train_rows} == {Decimal("0.5")}
    assert sum((row.exposure for row in train_rows), Decimal("0")) == Decimal("1.0")


def test_future_return_labels_do_not_require_close_and_are_not_repriced() -> None:
    snapshot = _snapshot(
        label_values=("0.01", "0.02", "0.03"), label_method=LabelMethod.FUTURE_RETURN
    )
    report = run_baseline(
        snapshot, build_baseline_config(name="buy-hold", kind=BaselineKind.BUY_AND_HOLD)
    )

    assert report.rows[0].realized_return == Decimal("0.01")


def test_baseline_ids_hashes_are_deterministic() -> None:
    snapshot = _snapshot()
    config = build_baseline_config(name="equal-weight", kind=BaselineKind.EQUAL_WEIGHT_BASKET)

    first = run_baseline(snapshot, config)
    second = run_baseline(snapshot, config)

    assert first.baseline_report_id == second.baseline_report_id
    assert first.baseline_report_hash == second.baseline_report_hash
    assert first.row_ids == second.row_ids
    assert first.dataset_snapshot_id == snapshot.dataset_snapshot_id
    assert first.dataset_hash == snapshot.dataset_hash
    assert first.baseline_config.baseline_config_id == config.baseline_config_id


def test_bad_inputs_fail_closed() -> None:
    snapshot = _snapshot(closes=("0", "101", "102"))
    with pytest.raises(BaselineBuildError, match="close feature must be positive"):
        run_baseline(
            snapshot, build_baseline_config(name="buy-hold", kind=BaselineKind.BUY_AND_HOLD)
        )

    negative_cost_snapshot = _snapshot(extra_values={"taker_fee_rate": Decimal("-0.01")})
    with pytest.raises(BaselineBuildError, match="cost feature must be non-negative"):
        run_baseline(
            negative_cost_snapshot,
            build_baseline_config(name="buy-hold", kind=BaselineKind.BUY_AND_HOLD),
        )

    label_rule = build_label_rule(
        name="future_1m", horizon_seconds=60, method=LabelMethod.FUTURE_VALUE
    )
    split_windows = (
        ChronologicalSplitWindow(
            split=DatasetSplit.TRAIN,
            start_ts=START,
            end_ts=START + timedelta(minutes=1),
        ),
    )
    dataset_hash = build_dataset_hash(
        rows=(),
        split_windows=split_windows,
        label_rule=label_rule,
        source_feature_snapshot_ids=(),
    )
    empty_snapshot = DatasetSnapshot(
        dataset_snapshot_id=build_dataset_snapshot_id(dataset_hash=dataset_hash),
        dataset_hash=dataset_hash,
        feature_versions=(),
        feature_vector_ids=(),
        split_windows=split_windows,
        label_rule=label_rule,
        row_ids=(),
        row_counts_by_split={
            DatasetSplit.TRAIN: 0,
            DatasetSplit.VALIDATION: 0,
            DatasetSplit.TEST: 0,
        },
        rows=(),
    )
    with pytest.raises(BaselineBuildError, match="at least one dataset row"):
        run_baseline(empty_snapshot, build_baseline_config(name="cash", kind=BaselineKind.CASH))
