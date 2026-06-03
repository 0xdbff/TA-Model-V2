"""Evidence for S5-003 baseline evaluation scorecards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from ta_model.baselines.deterministic import run_baseline
from ta_model.contracts.baselines import BaselineKind, BaselineReport, build_baseline_config
from ta_model.contracts.datasets import (
    ChronologicalSplitWindow,
    DatasetRow,
    DatasetSnapshot,
    DatasetSplit,
    LabelMethod,
    build_dataset_hash,
    build_dataset_row_id,
    build_dataset_snapshot_id,
    build_label_rule,
)
from ta_model.contracts.evaluation import EvaluationMetric, MetricAssumptions, MetricStatus
from ta_model.contracts.features import FeatureValue, build_feature_vector_id
from ta_model.evaluation.baseline_gate import validate_s5_baseline_gate
from ta_model.evaluation.scorecard import EvaluationBuildError, build_evaluation_scorecard

START = datetime(2026, 1, 1, tzinfo=UTC)
VENUE_ID = "FIXTURE_SPOT"
FEATURE_VERSION = "s5-scorecard-fixture-1.0.0"
SOURCE_FEATURE_SNAPSHOT_ID = "FEATURESNAPSHOT:S5-003"


def _report(kind: BaselineKind, *, label_values: tuple[str, ...] | None = None) -> BaselineReport:
    snapshot = _snapshot(
        label_values=label_values,
        per_index_values=(
            {
                "one_bar_return": Decimal("0.01"),
                "momentum_3": Decimal("0.01"),
                "round_trip_taker_cost_bps": Decimal("10"),
            },
            {
                "one_bar_return": Decimal("0.02"),
                "momentum_3": Decimal("0.02"),
                "round_trip_taker_cost_bps": Decimal("10"),
            },
            {
                "one_bar_return": Decimal("-0.01"),
                "momentum_3": Decimal("-0.01"),
                "round_trip_taker_cost_bps": Decimal("10"),
            },
            {
                "one_bar_return": Decimal("0.03"),
                "momentum_3": Decimal("0.03"),
                "round_trip_taker_cost_bps": Decimal("10"),
            },
            {
                "one_bar_return": Decimal("-0.02"),
                "momentum_3": Decimal("-0.02"),
                "round_trip_taker_cost_bps": Decimal("10"),
            },
            {
                "one_bar_return": Decimal("0.04"),
                "momentum_3": Decimal("0.04"),
                "round_trip_taker_cost_bps": Decimal("10"),
            },
        ),
    )
    return run_baseline(
        snapshot,
        build_baseline_config(name=kind.value, kind=kind),
    )


def _snapshot(
    *,
    per_index_values: tuple[dict[str, FeatureValue], ...],
    label_values: tuple[str, ...] | None,
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
    instrument_id = "FIXTURE_SPOT:BTC-USD"
    for index, extra_values in enumerate(per_index_values):
        feature_ts = START + timedelta(minutes=index)
        close = Decimal("100") + Decimal(index)
        label_value = (
            Decimal(label_values[index]) if label_values is not None else close + Decimal("1")
        )
        values: dict[str, FeatureValue] = {"close": close, **extra_values}
        input_snapshot_id = f"FEATUREINPUT:S5-003:{index}"
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
        row_id = build_dataset_row_id(
            feature_vector_id=feature_vector_id,
            instrument_id=instrument_id,
            venue_id=VENUE_ID,
            feature_ts=feature_ts,
            feature_version=FEATURE_VERSION,
            feature_values=values,
            feature_input_snapshot_id=input_snapshot_id,
            split=split_by_index[index],
            label_rule_id=label_rule.label_rule_id,
            label_value=label_value,
            label_ts=label_ts,
            label_observation_id=f"LABELOBS:S5-003:{index}",
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
                split=split_by_index[index],
                label_rule_id=label_rule.label_rule_id,
                label_value=label_value,
                label_ts=label_ts,
                label_observation_id=f"LABELOBS:S5-003:{index}",
                source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
            )
        )
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
    row_tuple = tuple(rows)
    dataset_hash = build_dataset_hash(
        rows=row_tuple,
        split_windows=split_windows,
        label_rule=label_rule,
        source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
    )
    return DatasetSnapshot(
        dataset_snapshot_id=build_dataset_snapshot_id(dataset_hash=dataset_hash),
        dataset_hash=dataset_hash,
        feature_versions=(FEATURE_VERSION,),
        feature_vector_ids=tuple(row.feature_vector_id for row in row_tuple),
        source_feature_snapshot_ids=(SOURCE_FEATURE_SNAPSHOT_ID,),
        split_windows=split_windows,
        label_rule=label_rule,
        row_ids=tuple(row.row_id for row in row_tuple),
        row_counts_by_split={
            split: sum(row.split is split for row in row_tuple) for split in DatasetSplit
        },
        rows=row_tuple,
    )


def _temp_gate_evidence(tmp_path: Path, scorecard_id: str, scorecard_hash: str) -> tuple[str, ...]:
    s5_001 = tmp_path / "S5-001_deterministic_baselines_report.md"
    s5_002 = tmp_path / "S5-002_ta_ml_baselines_report.md"
    s5_003 = tmp_path / "S5-003_evaluation_scorecard_report.md"
    s5_001.write_text("S5-001 evidence", encoding="utf-8")
    s5_002.write_text("S5-002 evidence", encoding="utf-8")
    s5_003.write_text(
        f"Scorecard ID: `{scorecard_id}`\nScorecard hash: `{scorecard_hash}`\n",
        encoding="utf-8",
    )
    return (str(s5_001), str(s5_002), str(s5_003))


def test_scorecard_consumes_s5_baseline_reports_and_propagates_costs_turnover_exposure() -> None:
    cash = _report(BaselineKind.CASH)
    buy_hold = _report(BaselineKind.BUY_AND_HOLD)
    basket = _report(BaselineKind.EQUAL_WEIGHT_BASKET)
    ta = _report(BaselineKind.TA_HEURISTIC)
    simple_ml = _report(BaselineKind.SIMPLE_ML)

    scorecard = build_evaluation_scorecard(
        (cash, buy_hold, basket, ta, simple_ml), benchmark_report=cash
    )

    assert scorecard.scorecard_id.startswith("EVALSCORECARD:")
    assert scorecard.input_baseline_report_ids == tuple(
        report.baseline_report_id for report in (cash, buy_hold, basket, ta, simple_ml)
    )
    buy_hold_train = next(
        score
        for score in scorecard.scores
        if score.baseline_report_id == buy_hold.baseline_report_id
        and score.split is DatasetSplit.TRAIN
    )
    assert buy_hold_train.net_return.status is MetricStatus.AVAILABLE
    assert buy_hold_train.net_return.value == Decimal("0.018990099009900990099009901")
    assert buy_hold_train.cost_return_sum.value == Decimal("0.001")
    assert buy_hold_train.turnover_sum.value == Decimal("1")
    assert buy_hold_train.average_exposure.value == Decimal("1")
    assert buy_hold_train.benchmark_relative_net_return.value == buy_hold_train.net_return.value
    assert buy_hold_train.sortino.status is MetricStatus.NOT_APPLICABLE
    assert buy_hold_train.sortino.reason == "no downside returns make Sortino undefined"
    assert buy_hold_train.max_drawdown.value == Decimal("0")
    assert buy_hold_train.calmar.reason == "no drawdown makes Calmar undefined"


def test_flat_cash_no_trade_metrics_are_explicitly_undefined_not_zero_success() -> None:
    cash = _report(BaselineKind.CASH)

    scorecard = build_evaluation_scorecard((cash,), benchmark_report=cash)
    cash_train = next(score for score in scorecard.scores if score.split is DatasetSplit.TRAIN)

    assert cash_train.net_return.value == Decimal("0")
    assert cash_train.sharpe.status is MetricStatus.NOT_APPLICABLE
    assert cash_train.sharpe.reason == "zero volatility makes Sharpe undefined"
    assert cash_train.sortino.status is MetricStatus.NOT_APPLICABLE
    assert cash_train.max_drawdown.value == Decimal("0")
    assert cash_train.calmar.status is MetricStatus.NOT_APPLICABLE
    assert cash_train.benchmark_relative_net_return.value == Decimal("0")


def test_loss_window_computes_drawdown_cvar_and_available_risk_metrics() -> None:
    cash = _report(
        BaselineKind.CASH,
        label_values=("99", "98", "102", "103", "104", "105"),
    )
    buy_hold = _report(
        BaselineKind.BUY_AND_HOLD,
        label_values=("99", "98", "102", "103", "104", "105"),
    )

    scorecard = build_evaluation_scorecard((buy_hold,), benchmark_report=cash)
    train = next(score for score in scorecard.scores if score.split is DatasetSplit.TRAIN)

    assert train.max_drawdown.status is MetricStatus.AVAILABLE
    assert train.max_drawdown.value is not None and train.max_drawdown.value < 0
    assert train.cvar.value == min(
        row.net_return for row in buy_hold.rows if row.split is DatasetSplit.TRAIN
    )
    assert train.sharpe.status is MetricStatus.AVAILABLE
    assert train.sortino.status is MetricStatus.AVAILABLE
    assert train.calmar.status is MetricStatus.AVAILABLE


def test_benchmark_hash_is_captured_when_benchmark_is_not_scored_report() -> None:
    cash = _report(BaselineKind.CASH)
    buy_hold = _report(BaselineKind.BUY_AND_HOLD)

    scorecard = build_evaluation_scorecard((buy_hold,), benchmark_report=cash)

    assert scorecard.input_baseline_report_ids == (buy_hold.baseline_report_id,)
    assert scorecard.input_baseline_report_hashes == (buy_hold.baseline_report_hash,)
    assert cash.baseline_report_id not in scorecard.input_baseline_report_ids
    assert scorecard.benchmark_config.benchmark_report_id == cash.baseline_report_id
    assert scorecard.benchmark_config.benchmark_report_hash == cash.baseline_report_hash


def test_empty_split_metrics_are_not_applicable_with_reason() -> None:
    snapshot_without_test = _snapshot(
        label_values=None,
        per_index_values=(
            {"one_bar_return": Decimal("0.01"), "round_trip_taker_cost_bps": Decimal("10")},
            {"one_bar_return": Decimal("0.02"), "round_trip_taker_cost_bps": Decimal("10")},
            {"one_bar_return": Decimal("0.03"), "round_trip_taker_cost_bps": Decimal("10")},
            {"one_bar_return": Decimal("0.04"), "round_trip_taker_cost_bps": Decimal("10")},
        ),
    )
    cash_without_test = run_baseline(
        snapshot_without_test,
        build_baseline_config(name=BaselineKind.CASH.value, kind=BaselineKind.CASH),
    )

    scorecard = build_evaluation_scorecard((cash_without_test,), benchmark_report=cash_without_test)
    test_score = next(score for score in scorecard.scores if score.split is DatasetSplit.TEST)
    assert test_score.observation_count == 0
    assert test_score.net_return.reason == "empty split test"
    assert (
        test_score.benchmark_relative_net_return.reason
        == "empty split has no benchmark-relative return"
    )


def test_benchmark_alignment_mismatch_fails_closed() -> None:
    cash = _report(BaselineKind.CASH)
    buy_hold = _report(BaselineKind.BUY_AND_HOLD)
    reversed_cash = cash.model_copy(update={"rows": tuple(reversed(cash.rows))})

    with pytest.raises(EvaluationBuildError, match="benchmark alignment mismatch"):
        build_evaluation_scorecard((buy_hold,), benchmark_report=reversed_cash)


def test_scorecard_ids_and_hashes_are_deterministic() -> None:
    cash = _report(BaselineKind.CASH)
    buy_hold = _report(BaselineKind.BUY_AND_HOLD)
    assumptions = MetricAssumptions(cvar_tail_probability=Decimal("0.10"))

    first = build_evaluation_scorecard(
        (cash, buy_hold), benchmark_report=cash, assumptions=assumptions
    )
    second = build_evaluation_scorecard(
        (cash, buy_hold), benchmark_report=cash, assumptions=assumptions
    )

    assert first.scorecard_id == second.scorecard_id
    assert first.scorecard_hash == second.scorecard_hash
    assert first.input_baseline_report_hashes == (
        cash.baseline_report_hash,
        buy_hold.baseline_report_hash,
    )


def test_missing_baseline_reports_are_rejected() -> None:
    cash = _report(BaselineKind.CASH)

    with pytest.raises(EvaluationBuildError, match="at least one baseline report is required"):
        build_evaluation_scorecard((), benchmark_report=cash)


def test_s5_baseline_gate_passes_complete_scorecard_with_cited_evidence() -> None:
    reports = tuple(_report(kind) for kind in BaselineKind)
    scorecard = build_evaluation_scorecard(reports, benchmark_report=reports[0])

    gate = validate_s5_baseline_gate(
        scorecard,
        evidence_paths=(
            "docs/reports/gates/S5-001_deterministic_baselines_report.md",
            "docs/reports/gates/S5-002_ta_ml_baselines_report.md",
            "docs/reports/gates/S5-003_evaluation_scorecard_report.md",
        ),
    )

    assert gate.status == "PASS"
    assert gate.blockers == ()
    assert "benchmark-relative net return" in gate.required_metric_families
    assert "simple_ml" in gate.required_baselines


def test_s5_baseline_gate_blocks_missing_simple_ml_baseline() -> None:
    reports = tuple(
        _report(kind) for kind in BaselineKind if kind is not BaselineKind.SIMPLE_ML
    )
    scorecard = build_evaluation_scorecard(reports, benchmark_report=reports[0])

    gate = validate_s5_baseline_gate(
        scorecard,
        evidence_paths=(
            "docs/reports/gates/S5-001_deterministic_baselines_report.md",
            "docs/reports/gates/S5-002_ta_ml_baselines_report.md",
            "docs/reports/gates/S5-003_evaluation_scorecard_report.md",
        ),
    )

    assert gate.status == "BLOCKED"
    assert "missing required baseline simple_ml" in gate.blockers


def test_s5_baseline_gate_uses_stable_kind_not_spoofed_display_names(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(
        label_values=None,
        per_index_values=tuple(
            {
                "one_bar_return": Decimal("0.01"),
                "round_trip_taker_cost_bps": Decimal("10"),
            }
            for _ in range(6)
        ),
    )
    spoofed_cash_reports = tuple(
        run_baseline(snapshot, build_baseline_config(name=kind.value, kind=BaselineKind.CASH))
        for kind in BaselineKind
    )
    scorecard = build_evaluation_scorecard(
        spoofed_cash_reports, benchmark_report=spoofed_cash_reports[0]
    )

    gate = validate_s5_baseline_gate(
        scorecard,
        evidence_paths=_temp_gate_evidence(
            tmp_path, scorecard.scorecard_id, scorecard.scorecard_hash
        ),
    )

    assert gate.status == "BLOCKED"
    assert "missing required baseline buy_and_hold" in gate.blockers
    assert "missing required baseline equal_weight_basket" in gate.blockers
    assert "missing required baseline ta_heuristic" in gate.blockers
    assert "missing required baseline simple_ml" in gate.blockers


def test_s5_baseline_gate_blocks_train_only_required_baseline_splits(
    tmp_path: Path,
) -> None:
    reports = tuple(_report(kind) for kind in BaselineKind)
    scorecard = build_evaluation_scorecard(reports, benchmark_report=reports[0])
    train_only_scorecard = scorecard.model_copy(
        update={
            "scores": tuple(
                score for score in scorecard.scores if score.split is DatasetSplit.TRAIN
            )
        }
    )

    gate = validate_s5_baseline_gate(
        train_only_scorecard,
        evidence_paths=_temp_gate_evidence(
            tmp_path,
            train_only_scorecard.scorecard_id,
            train_only_scorecard.scorecard_hash,
        ),
    )

    assert gate.status == "BLOCKED"
    assert "missing required baseline split cash_no_trade/validation" in gate.blockers
    assert "missing required baseline split buy_and_hold/test" in gate.blockers
    assert "missing required baseline split simple_ml/test" in gate.blockers


def test_s5_baseline_gate_blocks_duplicate_required_baseline_split(
    tmp_path: Path,
) -> None:
    reports = tuple(_report(kind) for kind in BaselineKind)
    scorecard = build_evaluation_scorecard(reports, benchmark_report=reports[0])
    cash_train = next(
        score
        for score in scorecard.scores
        if score.baseline_kind is BaselineKind.CASH and score.split is DatasetSplit.TRAIN
    )
    duplicated_scorecard = scorecard.model_copy(
        update={"scores": (cash_train, *scorecard.scores)}
    )

    gate = validate_s5_baseline_gate(
        duplicated_scorecard,
        evidence_paths=_temp_gate_evidence(
            tmp_path,
            duplicated_scorecard.scorecard_id,
            duplicated_scorecard.scorecard_hash,
        ),
    )

    assert gate.status == "BLOCKED"
    assert "duplicate baseline split cash_no_trade/train" in gate.blockers


def test_s5_baseline_gate_blocks_missing_evidence_report() -> None:
    reports = tuple(_report(kind) for kind in BaselineKind)
    scorecard = build_evaluation_scorecard(reports, benchmark_report=reports[0])

    gate = validate_s5_baseline_gate(
        scorecard,
        evidence_paths=(
            "docs/reports/gates/S5-001_deterministic_baselines_report.md",
            "docs/reports/gates/S5-003_evaluation_scorecard_report.md",
        ),
    )

    assert gate.status == "BLOCKED"
    assert "missing required evidence report S5-002" in gate.blockers


def test_s5_baseline_gate_blocks_nonexistent_evidence_path() -> None:
    reports = tuple(_report(kind) for kind in BaselineKind)
    scorecard = build_evaluation_scorecard(reports, benchmark_report=reports[0])

    gate = validate_s5_baseline_gate(
        scorecard,
        evidence_paths=(
            "docs/reports/gates/S5-001_deterministic_baselines_report.md",
            "docs/reports/gates/S5-002_ta_ml_baselines_report.md",
            "docs/reports/gates/S5-003_missing_scorecard_report.md",
        ),
    )

    assert gate.status == "BLOCKED"
    assert any("evidence path does not exist" in blocker for blocker in gate.blockers)


def test_s5_baseline_gate_blocks_stale_scorecard_evidence(tmp_path: Path) -> None:
    reports = tuple(_report(kind) for kind in BaselineKind)
    scorecard = build_evaluation_scorecard(reports, benchmark_report=reports[0])
    evidence_paths = _temp_gate_evidence(
        tmp_path,
        "EVALSCORECARD:STALESTALESTALESTALESTALESTALEST",
        "0" * 64,
    )

    gate = validate_s5_baseline_gate(scorecard, evidence_paths=evidence_paths)

    assert gate.status == "BLOCKED"
    assert "S5-003 evidence does not match scorecard_id" in gate.blockers
    assert "S5-003 evidence does not match scorecard_hash" in gate.blockers


def test_s5_baseline_gate_blocks_missing_benchmark_relative_metric() -> None:
    reports = tuple(_report(kind) for kind in BaselineKind)
    scorecard = build_evaluation_scorecard(reports, benchmark_report=reports[0])
    first_score = scorecard.scores[0].model_copy(
        update={
            "benchmark_relative_net_return": EvaluationMetric(
                value=None,
                status=MetricStatus.BLOCKED,
                reason="benchmark alignment mismatch",
            )
        }
    )
    blocked_scorecard = scorecard.model_copy(
        update={"scores": (first_score, *scorecard.scores[1:])}
    )

    gate = validate_s5_baseline_gate(
        blocked_scorecard,
        evidence_paths=(
            "docs/reports/gates/S5-001_deterministic_baselines_report.md",
            "docs/reports/gates/S5-002_ta_ml_baselines_report.md",
            "docs/reports/gates/S5-003_evaluation_scorecard_report.md",
        ),
    )

    assert gate.status == "BLOCKED"
    assert any("benchmark-relative net return is blocked" in blocker for blocker in gate.blockers)


def test_s5_baseline_gate_accepts_undefined_risk_metrics_with_reasons() -> None:
    reports = tuple(_report(kind) for kind in BaselineKind)
    scorecard = build_evaluation_scorecard(reports, benchmark_report=reports[0])

    assert any(score.sortino.status is MetricStatus.NOT_APPLICABLE for score in scorecard.scores)
    assert any(score.calmar.status is MetricStatus.NOT_APPLICABLE for score in scorecard.scores)
    gate = validate_s5_baseline_gate(
        scorecard,
        evidence_paths=(
            "docs/reports/gates/S5-001_deterministic_baselines_report.md",
            "docs/reports/gates/S5-002_ta_ml_baselines_report.md",
            "docs/reports/gates/S5-003_evaluation_scorecard_report.md",
        ),
    )

    assert gate.status == "PASS"
