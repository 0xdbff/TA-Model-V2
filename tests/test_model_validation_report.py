"""Evidence for S7-004 model validation/gate reporting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ta_model.contracts.datasets import (
    ChronologicalSplitWindow,
    DatasetSnapshot,
    DatasetSplit,
    LabelMethod,
    build_label_observation,
    build_label_rule,
)
from ta_model.contracts.features import FeatureValue, FeatureVector, build_feature_vector_id
from ta_model.contracts.forecasts import (
    Forecast,
    ProbabilisticCandidateOutput,
    build_forecast_id,
    build_probabilistic_output_hash,
    build_probabilistic_output_id,
)
from ta_model.contracts.model_validation import (
    BaselineEvidenceReference,
    ModelGateRecommendation,
    ModelValidationReport,
)
from ta_model.contracts.training import build_training_config
from ta_model.datasets.snapshots import build_chronological_dataset_snapshot
from ta_model.training.probabilistic_candidate import train_probabilistic_candidate
from ta_model.training.runner import run_training
from ta_model.validation.model_validation import ModelValidationError, build_model_validation_report

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"
VENUE_ID = "FIXTURE_SPOT"
FEATURE_VERSION = "fixture-pit-1.0.0"
CODE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
S5_SCORECARD_ID = "EVALSCORECARD:BC0F9618311E62E8739A80410D68483D"


def test_model_validation_report_computes_metrics_and_is_deterministic() -> None:
    snapshot, output = _candidate_output()

    first = build_model_validation_report(
        snapshot=snapshot, candidate_output=output, baseline_evidence=_baseline_evidence()
    )
    second = build_model_validation_report(
        snapshot=snapshot, candidate_output=output, baseline_evidence=_baseline_evidence()
    )

    assert first == second
    assert first.report_id == second.report_id
    assert first.requirement_ids == ("FR-008", "FR-014", "FR-007", "NFR-005")
    assert first.candidate_metrics.observation_count == 4
    assert first.candidate_metrics.nll == Decimal("0.0")
    assert first.candidate_metrics.brier == Decimal("0.0")
    assert first.candidate_metrics.calibration_error == Decimal("0.0")
    assert first.train_prior_baseline.metrics.nll == Decimal("0.69314718056")
    assert first.sequence_ablation.comparator_name == "ablated_global_prior_no_sequence"
    assert first.no_auto_promotion is True


def test_report_contract_rejects_rebuilt_wrong_hash() -> None:
    snapshot, output = _candidate_output()
    report = build_model_validation_report(
        snapshot=snapshot, candidate_output=output, baseline_evidence=_baseline_evidence()
    )

    with pytest.raises(ValidationError, match="report_hash is not deterministic"):
        ModelValidationReport(**(report.model_dump() | {"report_hash": "0" * 64}))


def test_forecast_dataset_alignment_failure_is_fail_closed() -> None:
    snapshot, output = _candidate_output()
    forecast = output.forecasts[0]
    payload = forecast.model_dump() | {"feature_ts": snapshot.rows[-1].feature_ts}
    payload["forecast_id"] = build_forecast_id(
        dataset_snapshot_id=payload["dataset_snapshot_id"],
        dataset_hash=payload["dataset_hash"],
        dataset_row_id=payload["dataset_row_id"],
        split=payload["split"],
        training_run_id=payload["training_run_id"],
        training_run_hash=payload["training_run_hash"],
        model_version_id=payload["model_version_id"],
        model_version_hash=payload["model_version_hash"],
        probabilities=payload["probabilities"],
        quantiles=forecast.quantiles,
        uncertainty=payload["uncertainty"],
        calibration_status=payload["calibration_status"],
        calibration_metadata=payload["calibration_metadata"],
    )
    bad_forecast = Forecast(**payload)
    bad_forecasts = (bad_forecast, *output.forecasts[1:])
    bad_hash = build_probabilistic_output_hash(
        dataset_snapshot_id=output.dataset_snapshot_id,
        dataset_hash=output.dataset_hash,
        training_run_id=output.training_run_id,
        training_run_hash=output.training_run_hash,
        model_version_id=output.model_version_id,
        model_version_hash=output.model_version_hash,
        forecasts=bad_forecasts,
    )
    bad_output = ProbabilisticCandidateOutput(
        **(
            output.model_dump()
            | {
                "output_id": build_probabilistic_output_id(output_hash=bad_hash),
                "output_hash": bad_hash,
                "forecasts": bad_forecasts,
                "forecast_ids": output.forecast_ids,
            }
        )
    )

    with pytest.raises(ModelValidationError, match="alignment mismatch: feature_ts"):
        build_model_validation_report(
            snapshot=snapshot, candidate_output=bad_output, baseline_evidence=_baseline_evidence()
        )


def test_missing_baseline_evidence_is_fail_closed() -> None:
    snapshot, output = _candidate_output()
    missing = BaselineEvidenceReference(
        scorecard_id=S5_SCORECARD_ID,
        gate_report_path="docs/reports/gates/missing_s5_gate.md",
        scorecard_report_path="docs/reports/gates/S5-003_evaluation_scorecard_report.md",
    )

    with pytest.raises(ModelValidationError, match="fixed S5 baseline evidence is missing"):
        build_model_validation_report(
            snapshot=snapshot, candidate_output=output, baseline_evidence=missing
        )


def test_ablation_quantile_coverage_and_no_promotion_semantics() -> None:
    snapshot, output = _candidate_output()
    report = build_model_validation_report(
        snapshot=snapshot, candidate_output=output, baseline_evidence=_baseline_evidence()
    )

    assert report.recommendation is ModelGateRecommendation.CONTINUE_RESEARCH
    assert report.sequence_ablation.metrics == report.train_prior_baseline.metrics
    assert tuple(metric.level for metric in report.quantile_coverage) == (
        Decimal("0.1"),
        Decimal("0.5"),
        Decimal("0.9"),
    )
    assert tuple(metric.observed_coverage for metric in report.quantile_coverage) == (
        Decimal("1"),
        Decimal("1"),
        Decimal("1"),
    )
    assert any("insufficient for promotion" in reason for reason in report.reasons)
    assert any("does not route orders" in caveat for caveat in report.caveats)


def _candidate_output() -> tuple[DatasetSnapshot, ProbabilisticCandidateOutput]:
    snapshot = _snapshot()
    training_run = run_training(
        snapshot=snapshot,
        config=build_training_config(name="s7-004-reference", seed=7),
        code_commit=CODE_COMMIT,
    )
    return snapshot, train_probabilistic_candidate(snapshot=snapshot, training_run=training_run)


def _baseline_evidence() -> BaselineEvidenceReference:
    return BaselineEvidenceReference(
        scorecard_id=S5_SCORECARD_ID,
        gate_report_path="docs/reports/gates/S5-004_baseline_gate_report.md",
        scorecard_report_path="docs/reports/gates/S5-003_evaluation_scorecard_report.md",
    )


def _feature(index: int, one_bar_return: str) -> FeatureVector:
    feature_ts = START + timedelta(minutes=index)
    values: dict[str, FeatureValue] = {
        "close": Decimal("100"),
        "one_bar_return": Decimal(one_bar_return),
    }
    input_snapshot_id = f"FEATUREINPUT:S7-004:{index}:{one_bar_return}"
    feature_vector_id = build_feature_vector_id(
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        feature_ts=feature_ts,
        feature_version=FEATURE_VERSION,
        lookback_window="fixture-2-bars",
        values=values,
        input_snapshot_id=input_snapshot_id,
        quality_flags=(),
    )
    return FeatureVector(
        feature_vector_id=feature_vector_id,
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        feature_ts=feature_ts,
        feature_version=FEATURE_VERSION,
        lookback_window="fixture-2-bars",
        values=values,
        input_snapshot_id=input_snapshot_id,
        quality_flags=(),
    )


def _snapshot() -> DatasetSnapshot:
    sequence_values = ("-0.5", "-0.5", "0.5", "0.5", "0.5", "0.5", "0.5", "0.5")
    features = tuple(_feature(index, value) for index, value in enumerate(sequence_values))
    observation_values = ("100", "90", "80", "120", "160", "105", "106", "107", "108")
    observations = tuple(
        build_label_observation(
            instrument_id=INSTRUMENT_ID,
            venue_id=VENUE_ID,
            event_ts=START + timedelta(minutes=index),
            value=Decimal(value),
            source_lineage_id=f"LABELSOURCE:S7-004:{index}:{value}",
        )
        for index, value in enumerate(observation_values)
    )
    return build_chronological_dataset_snapshot(
        feature_vectors=features,
        label_observations=observations,
        split_windows=(
            ChronologicalSplitWindow(
                split=DatasetSplit.TRAIN,
                start_ts=START,
                end_ts=START + timedelta(minutes=4),
            ),
            ChronologicalSplitWindow(
                split=DatasetSplit.VALIDATION,
                start_ts=START + timedelta(minutes=4),
                end_ts=START + timedelta(minutes=6),
            ),
            ChronologicalSplitWindow(
                split=DatasetSplit.TEST,
                start_ts=START + timedelta(minutes=6),
                end_ts=START + timedelta(minutes=8),
            ),
        ),
        label_rule=build_label_rule(
            name="future_1m", horizon_seconds=60, method=LabelMethod.FUTURE_RETURN
        ),
        source_feature_snapshot_ids=("FEATURESNAPSHOT:S7-004",),
    )
