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


def _windowed_snapshot(
    *,
    instruments: tuple[str, ...] = ("FIXTURE_SPOT:BTC-USD",),
    extra_values: dict[str, FeatureValue] | None = None,
    per_index_values: tuple[dict[str, FeatureValue], ...] | None = None,
    label_values: tuple[str, ...] | None = None,
) -> DatasetSnapshot:
    label_rule = build_label_rule(
        name="future_1m", horizon_seconds=60, method=LabelMethod.FUTURE_VALUE
    )
    rows: list[DatasetRow] = []
    split_by_index = {
        0: DatasetSplit.TRAIN,
        1: DatasetSplit.TRAIN,
        2: DatasetSplit.VALIDATION,
        3: DatasetSplit.VALIDATION,
        4: DatasetSplit.TEST,
        5: DatasetSplit.TEST,
    }
    for index in range(6):
        feature_ts = START + timedelta(minutes=index)
        close = Decimal("100") + Decimal(index)
        label_value = (
            Decimal(label_values[index]) if label_values is not None else close + Decimal("1")
        )
        for instrument_id in instruments:
            values: dict[str, FeatureValue] = {"close": close}
            if extra_values is not None:
                values.update(extra_values)
            if per_index_values is not None:
                values.update(per_index_values[index])
            input_snapshot_id = f"FEATUREINPUT:S5-001:WINDOW:{instrument_id}:{index}"
            feature_vector_id = build_feature_vector_id(
                instrument_id=instrument_id,
                venue_id=VENUE_ID,
                feature_ts=feature_ts,
                feature_version=FEATURE_VERSION,
                lookback_window="fixture-6-bars",
                values=values,
                input_snapshot_id=input_snapshot_id,
                quality_flags=(),
            )
            label_ts = feature_ts + timedelta(minutes=1)
            label_observation_id = f"LABELOBS:S5-001:WINDOW:{instrument_id}:{index}"
            split = split_by_index[index]
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
                label_value=label_value,
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
                    label_value=label_value,
                    label_ts=label_ts,
                    label_observation_id=label_observation_id,
                    source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
                )
            )
    return _build_windowed_snapshot(rows=tuple(rows), label_rule=label_rule)


def _build_windowed_snapshot(
    *, rows: tuple[DatasetRow, ...], label_rule: LabelRule
) -> DatasetSnapshot:
    split_windows = (
        ChronologicalSplitWindow(
            split=DatasetSplit.TRAIN,
            start_ts=START,
            end_ts=START + timedelta(minutes=2),
        ),
        ChronologicalSplitWindow(
            split=DatasetSplit.VALIDATION,
            start_ts=START + timedelta(minutes=2),
            end_ts=START + timedelta(minutes=4),
        ),
        ChronologicalSplitWindow(
            split=DatasetSplit.TEST,
            start_ts=START + timedelta(minutes=4),
            end_ts=START + timedelta(minutes=6),
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
    assert report.rows[1].turnover == Decimal("1")


def test_buy_and_hold_resets_entry_turnover_and_cost_at_each_split() -> None:
    report = run_baseline(
        _windowed_snapshot(extra_values={"round_trip_taker_cost_bps": Decimal("10")}),
        build_baseline_config(name="buy-hold", kind=BaselineKind.BUY_AND_HOLD),
    )

    first_by_split = {
        DatasetSplit.TRAIN: START,
        DatasetSplit.VALIDATION: START + timedelta(minutes=2),
        DatasetSplit.TEST: START + timedelta(minutes=4),
    }
    for split, feature_ts in first_by_split.items():
        first_row = next(
            row for row in report.rows if row.split is split and row.feature_ts == feature_ts
        )
        second_row = next(
            row
            for row in report.rows
            if row.split is split and row.feature_ts == feature_ts + timedelta(minutes=1)
        )
        assert first_row.turnover == Decimal("1")
        assert first_row.cost_return == Decimal("0.001")
        assert second_row.turnover == Decimal("0")
        assert second_row.cost_return == Decimal("0")


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


def test_equal_weight_basket_resets_turnover_per_instrument_at_each_split() -> None:
    report = run_baseline(
        _windowed_snapshot(
            instruments=("FIXTURE_SPOT:BTC-USD", "FIXTURE_SPOT:ETH-USD"),
            extra_values={"round_trip_taker_cost_bps": Decimal("10")},
        ),
        build_baseline_config(name="equal-weight", kind=BaselineKind.EQUAL_WEIGHT_BASKET),
    )

    first_timestamps = {
        DatasetSplit.TRAIN: START,
        DatasetSplit.VALIDATION: START + timedelta(minutes=2),
        DatasetSplit.TEST: START + timedelta(minutes=4),
    }
    for split, first_ts in first_timestamps.items():
        entry_rows = tuple(
            row for row in report.rows if row.split is split and row.feature_ts == first_ts
        )
        next_rows = tuple(
            row
            for row in report.rows
            if row.split is split and row.feature_ts == first_ts + timedelta(minutes=1)
        )
        assert len(entry_rows) == 2
        assert {row.turnover for row in entry_rows} == {Decimal("0.5")}
        assert {row.cost_return for row in entry_rows} == {Decimal("0.0005")}
        assert len(next_rows) == 2
        assert {row.turnover for row in next_rows} == {Decimal("0")}
        assert {row.cost_return for row in next_rows} == {Decimal("0")}


def test_ta_heuristic_is_point_in_time_long_only_and_keeps_no_trade_rows() -> None:
    snapshot = _windowed_snapshot(
        per_index_values=(
            {},
            {"one_bar_return": Decimal("-0.01")},
            {"one_bar_return": Decimal("0.02")},
            {"momentum_3": Decimal("0.03"), "one_bar_return": Decimal("-0.02")},
            {"momentum_3": Decimal("0")},
            {"momentum_3": Decimal("0.04")},
        ),
        extra_values={"round_trip_taker_cost_bps": Decimal("10")},
    )

    config = build_baseline_config(name="ta", kind=BaselineKind.TA_HEURISTIC)
    report = run_baseline(snapshot, config)
    repeated = run_baseline(snapshot, config)

    assert len(report.rows) == len(snapshot.rows)
    assert report.baseline_report_id == repeated.baseline_report_id
    assert report.row_ids == repeated.row_ids
    assert {row.target_weight for row in report.rows} <= {Decimal("0"), Decimal("1")}
    assert report.rows[0].no_trade_reason == "ta_missing_signal_feature"
    assert report.rows[1].no_trade_reason == "ta_non_positive_signal"
    assert report.rows[2].target_weight == Decimal("1")
    assert report.rows[2].no_trade_reason is None
    assert report.rows[2].turnover == Decimal("1")
    assert report.rows[2].cost_return == Decimal("0.001")
    assert report.rows[3].target_weight == Decimal("1")
    assert report.rows[3].turnover == Decimal("0")
    assert report.rows[4].no_trade_reason == "ta_non_positive_signal"
    assert report.rows[5].target_weight == Decimal("1")


def test_simple_ml_fits_train_only_and_validation_test_labels_do_not_change_decisions() -> None:
    features: tuple[dict[str, FeatureValue], ...] = (
        {"one_bar_return": Decimal("-0.01")},
        {"one_bar_return": Decimal("0.01")},
        {"one_bar_return": Decimal("0.02")},
        {"one_bar_return": Decimal("-0.02")},
        {"one_bar_return": Decimal("0.03")},
        {},
    )
    base = _windowed_snapshot(per_index_values=features)
    changed_outcome_labels = _windowed_snapshot(
        per_index_values=features,
        label_values=("101", "102", "1", "999", "2", "999"),
    )

    config = build_baseline_config(
        name="simple-ml",
        kind=BaselineKind.SIMPLE_ML,
        parameters=("fixed_feature=one_bar_return", "fit_split=train"),
    )
    first = run_baseline(base, config)
    second = run_baseline(changed_outcome_labels, config)

    assert "Simple ML fit uses train split only" in first.cost_assumption
    assert [row.target_weight for row in first.rows] == [row.target_weight for row in second.rows]
    assert [row.no_trade_reason for row in first.rows] == [
        row.no_trade_reason for row in second.rows
    ]
    assert [row.target_weight for row in first.rows] == [
        Decimal("0"),
        Decimal("1"),
        Decimal("1"),
        Decimal("0"),
        Decimal("1"),
        Decimal("0"),
    ]
    assert first.rows[5].no_trade_reason == "ml_missing_signal_feature"


def test_simple_ml_fails_closed_without_train_features_and_uses_train_labels_only() -> None:
    no_train_features = _windowed_snapshot(
        per_index_values=(
            {},
            {},
            {"one_bar_return": Decimal("0.02")},
            {"one_bar_return": Decimal("0.02")},
            {"one_bar_return": Decimal("0.02")},
            {"one_bar_return": Decimal("0.02")},
        )
    )
    with pytest.raises(BaselineBuildError, match="train split numeric features"):
        run_baseline(
            no_train_features,
            build_baseline_config(name="simple-ml", kind=BaselineKind.SIMPLE_ML),
        )

    negative_train_labels = _windowed_snapshot(
        per_index_values=tuple({"one_bar_return": Decimal("0.02")} for _ in range(6)),
        label_values=("99", "99", "999", "999", "999", "999"),
    )
    report = run_baseline(
        negative_train_labels,
        build_baseline_config(name="simple-ml", kind=BaselineKind.SIMPLE_ML),
    )

    assert {row.target_weight for row in report.rows} == {Decimal("0")}
    assert {row.no_trade_reason for row in report.rows} == {"ml_train_mean_not_positive"}


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

    ordered_snapshot = _windowed_snapshot()
    non_chronological_snapshot = _build_windowed_snapshot(
        rows=tuple(reversed(ordered_snapshot.rows)), label_rule=ordered_snapshot.label_rule
    )
    with pytest.raises(BaselineBuildError, match="chronological by feature_ts"):
        run_baseline(
            non_chronological_snapshot,
            build_baseline_config(name="buy-hold", kind=BaselineKind.BUY_AND_HOLD),
        )
