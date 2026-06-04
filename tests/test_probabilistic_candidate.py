"""Evidence for S7-002 probabilistic candidate outputs."""

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
    ForecastQuantile,
    ProbabilisticCandidateOutput,
    build_forecast_id,
    build_probabilistic_output_hash,
    build_probabilistic_output_id,
)
from ta_model.contracts.training import build_training_config, build_training_run_id
from ta_model.datasets.snapshots import build_chronological_dataset_snapshot
from ta_model.training.probabilistic_candidate import (
    ProbabilisticCandidateError,
    train_probabilistic_candidate,
)
from ta_model.training.runner import run_training

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
INSTRUMENT_ID = "FIXTURE_SPOT:BTC-USD"
VENUE_ID = "FIXTURE_SPOT"
FEATURE_VERSION = "fixture-pit-1.0.0"
CODE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _feature(index: int, one_bar_return: str) -> FeatureVector:
    feature_ts = START + timedelta(minutes=index)
    values: dict[str, FeatureValue] = {
        "close": Decimal("100"),
        "one_bar_return": Decimal(one_bar_return),
    }
    input_snapshot_id = f"FEATUREINPUT:S7-002:{index}:{one_bar_return}"
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


def _snapshot(*, oos_sequence_value: str = "0.5") -> DatasetSnapshot:
    sequence_values = ("-0.5", "-0.5", "0.5", "0.5", oos_sequence_value, "0.5", "0.5", "0.5")
    features = tuple(_feature(index, value) for index, value in enumerate(sequence_values))
    observation_values = ("100", "90", "80", "120", "160", "105", "106", "107", "108")
    observations = tuple(
        build_label_observation(
            instrument_id=INSTRUMENT_ID,
            venue_id=VENUE_ID,
            event_ts=START + timedelta(minutes=index),
            value=Decimal(value),
            source_lineage_id=f"LABELSOURCE:S7-002:{index}:{value}",
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
        source_feature_snapshot_ids=("FEATURESNAPSHOT:S7-002",),
    )


def _candidate_output(
    *, seed: int = 7, name: str = "s7-002-reference"
) -> ProbabilisticCandidateOutput:
    snapshot = _snapshot()
    training_run = run_training(
        snapshot=snapshot,
        config=build_training_config(name=name, seed=seed),
        code_commit=CODE_COMMIT,
    )
    return train_probabilistic_candidate(snapshot=snapshot, training_run=training_run)


def test_probabilistic_candidate_outputs_are_deterministic_and_valid() -> None:
    first = _candidate_output()
    second = _candidate_output()

    assert first == second
    assert first.forecasts
    assert {forecast.split for forecast in first.forecasts} == {
        DatasetSplit.VALIDATION,
        DatasetSplit.TEST,
    }
    for forecast in first.forecasts:
        assert sum(forecast.probabilities.values(), Decimal("0")) == Decimal("1")
        assert tuple(quantile.level for quantile in forecast.quantiles) == (
            Decimal("0.1"),
            Decimal("0.5"),
            Decimal("0.9"),
        )
        assert (
            forecast.quantiles[0].value
            <= forecast.quantiles[1].value
            <= forecast.quantiles[2].value
        )
        assert forecast.uncertainty >= Decimal("0")
        assert forecast.calibration_status == "sequence_conditioned_train_only"
        assert forecast.training_run_id == first.training_run_id
        assert forecast.training_run_hash == first.training_run_hash
        assert forecast.model_version_id == first.model_version_id
        assert forecast.model_version_hash == first.model_version_hash


def test_candidate_lineage_changes_when_dataset_config_commit_or_seed_changes() -> None:
    snapshot = _snapshot()
    config = build_training_config(name="s7-002-reference", seed=7)
    baseline_run = run_training(snapshot=snapshot, config=config, code_commit=CODE_COMMIT)
    baseline = train_probabilistic_candidate(snapshot=snapshot, training_run=baseline_run)

    changed_seed_run = run_training(
        snapshot=snapshot,
        config=build_training_config(name="s7-002-reference", seed=8),
        code_commit=CODE_COMMIT,
    )
    changed_config_run = run_training(
        snapshot=snapshot,
        config=build_training_config(name="s7-002-reference-v2", seed=7),
        code_commit=CODE_COMMIT,
    )
    changed_dataset = _snapshot(oos_sequence_value="-2")
    changed_dataset_run = run_training(
        snapshot=changed_dataset, config=config, code_commit=CODE_COMMIT
    )
    changed_commit_run = run_training(
        snapshot=snapshot, config=config, code_commit="fedcba9876543210"
    )

    assert baseline.output_id != train_probabilistic_candidate(
        snapshot=snapshot, training_run=changed_seed_run
    ).output_id
    assert baseline.output_id != train_probabilistic_candidate(
        snapshot=snapshot, training_run=changed_config_run
    ).output_id
    assert baseline.output_id != train_probabilistic_candidate(
        snapshot=changed_dataset, training_run=changed_dataset_run
    ).output_id
    assert baseline.output_id != train_probabilistic_candidate(
        snapshot=snapshot, training_run=changed_commit_run
    ).output_id


def test_invalid_forecast_contracts_are_rejected() -> None:
    forecast = _candidate_output().forecasts[0]

    with pytest.raises(ValidationError, match="probabilities must sum to 1"):
        Forecast(**(forecast.model_dump() | {"probabilities": {"negative": "0.5", "up": "0.6"}}))

    with pytest.raises(ValidationError, match="quantile values must be monotonic"):
        Forecast(
            **(
                forecast.model_dump()
                | {
                    "forecast_id": forecast.forecast_id,
                    "quantiles": (
                        ForecastQuantile(level=Decimal("0.1"), value=Decimal("2")),
                        ForecastQuantile(level=Decimal("0.5"), value=Decimal("1")),
                    ),
                }
            )
        )

    with pytest.raises(ValidationError, match="finite"):
        Forecast(**(forecast.model_dump() | {"uncertainty": Decimal("NaN")}))

    payload = forecast.model_dump()
    payload.pop("calibration_status")
    with pytest.raises(ValidationError):
        Forecast(**payload)


def test_forecast_lineage_hash_conflicts_are_rejected_even_with_rebuilt_id() -> None:
    forecast = _candidate_output().forecasts[0]
    conflicting_training_hash = "1" * 64
    payload = forecast.model_dump() | {"training_run_hash": conflicting_training_hash}
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

    with pytest.raises(ValidationError, match="training_run_id must match training_run_hash"):
        Forecast(**payload)

    matching_training_id = build_training_run_id(training_run_hash=conflicting_training_hash)
    payload = forecast.model_dump() | {
        "training_run_hash": conflicting_training_hash,
        "training_run_id": matching_training_id,
    }
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
    malformed_forecast = Forecast(**payload)
    output = _candidate_output()
    output_payload = output.model_dump() | {"forecasts": (malformed_forecast,)}
    output_payload["forecast_ids"] = (malformed_forecast.forecast_id,)
    output_payload["output_hash"] = build_probabilistic_output_hash(
        dataset_snapshot_id=output_payload["dataset_snapshot_id"],
        dataset_hash=output_payload["dataset_hash"],
        training_run_id=output_payload["training_run_id"],
        training_run_hash=output_payload["training_run_hash"],
        model_version_id=output_payload["model_version_id"],
        model_version_hash=output_payload["model_version_hash"],
        forecasts=(malformed_forecast,),
    )
    output_payload["output_id"] = build_probabilistic_output_id(
        output_hash=output_payload["output_hash"]
    )
    with pytest.raises(ValidationError, match="forecast training_run_id must match output"):
        ProbabilisticCandidateOutput(**output_payload)


def test_output_rejects_empty_and_nested_hash_conflicts_with_rebuilt_hash() -> None:
    output = _candidate_output()

    with pytest.raises(ValidationError):
        ProbabilisticCandidateOutput(
            **(output.model_dump() | {"forecast_ids": (), "forecasts": ()})
        )

    payload = output.model_dump() | {"training_run_hash": "2" * 64}
    payload["output_hash"] = build_probabilistic_output_hash(
        dataset_snapshot_id=payload["dataset_snapshot_id"],
        dataset_hash=payload["dataset_hash"],
        training_run_id=payload["training_run_id"],
        training_run_hash=payload["training_run_hash"],
        model_version_id=payload["model_version_id"],
        model_version_hash=payload["model_version_hash"],
        forecasts=output.forecasts,
    )
    payload["output_id"] = build_probabilistic_output_id(output_hash=payload["output_hash"])
    with pytest.raises(ValidationError, match="forecast training_run_hash must match output"):
        ProbabilisticCandidateOutput(**payload)


def test_out_of_sample_split_enforcement() -> None:
    snapshot = _snapshot()
    training_run = run_training(
        snapshot=snapshot,
        config=build_training_config(name="s7-002-reference", seed=7),
        code_commit=CODE_COMMIT,
    )

    with pytest.raises(ProbabilisticCandidateError, match="out-of-sample"):
        train_probabilistic_candidate(
            snapshot=snapshot,
            training_run=training_run,
            evaluation_splits=(DatasetSplit.TRAIN,),
        )


def test_oos_feature_sequence_changes_forecasts_without_training_on_oos_labels() -> None:
    baseline = _candidate_output()
    changed_oos_snapshot = _snapshot(oos_sequence_value="-2")
    changed_oos_run = run_training(
        snapshot=changed_oos_snapshot,
        config=build_training_config(name="s7-002-reference", seed=7),
        code_commit=CODE_COMMIT,
    )
    changed_oos = train_probabilistic_candidate(
        snapshot=changed_oos_snapshot, training_run=changed_oos_run
    )

    assert baseline.output_id != changed_oos.output_id
    assert baseline.forecasts[0].probabilities != changed_oos.forecasts[0].probabilities
    assert baseline.forecasts[0].quantiles != changed_oos.forecasts[0].quantiles
    assert baseline.forecasts[0].uncertainty != changed_oos.forecasts[0].uncertainty

    assert baseline.forecasts[2].probabilities == changed_oos.forecasts[2].probabilities
    assert baseline.forecasts[2].quantiles == changed_oos.forecasts[2].quantiles
    assert baseline.forecasts[2].uncertainty == changed_oos.forecasts[2].uncertainty
