"""Evidence for S7-002 probabilistic candidate outputs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from ta_model.contracts.datasets import DatasetSplit
from ta_model.contracts.forecasts import Forecast, ForecastQuantile
from ta_model.contracts.training import build_training_config
from ta_model.training.probabilistic_candidate import (
    ProbabilisticCandidateError,
    train_probabilistic_candidate,
)
from ta_model.training.runner import run_training
from test_training_runner import CODE_COMMIT, _snapshot


def _candidate_output(*, seed: int = 7, name: str = "s7-002-reference") -> Any:
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
        assert forecast.calibration_status == "train_prior_only"
        assert forecast.training_run_id == first.training_run_id
        assert forecast.model_version_id == first.model_version_id


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
    changed_dataset = _snapshot(last_close="999")
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

    with pytest.raises(ValidationError, match="forecast_id is not deterministic"):
        Forecast(**(forecast.model_dump() | {"training_run_id": "TRAINRUN:DIFFERENT"}))


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


def test_candidate_uses_train_labels_only_for_fitted_distribution() -> None:
    baseline = _candidate_output()
    changed_oos_snapshot = _snapshot(last_close="999")
    changed_oos_run = run_training(
        snapshot=changed_oos_snapshot,
        config=build_training_config(name="s7-002-reference", seed=7),
        code_commit=CODE_COMMIT,
    )
    changed_oos = train_probabilistic_candidate(
        snapshot=changed_oos_snapshot, training_run=changed_oos_run
    )

    assert baseline.output_id != changed_oos.output_id
    assert baseline.forecasts[0].probabilities == changed_oos.forecasts[0].probabilities
    assert baseline.forecasts[0].quantiles == changed_oos.forecasts[0].quantiles
    assert baseline.forecasts[0].uncertainty == changed_oos.forecasts[0].uncertainty
