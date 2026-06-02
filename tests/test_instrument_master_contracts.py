"""Schema evidence for S1-001 instrument-master contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from ta_model.contracts.instrument_master import (
    Account,
    Asset,
    Instrument,
    InstrumentMasterSnapshot,
    Venue,
)

type FixtureModel = type[BaseModel]

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "instrument_master"
MODEL_BY_NAME: dict[str, FixtureModel] = {
    "Account": Account,
    "Asset": Asset,
    "Instrument": Instrument,
    "InstrumentMasterSnapshot": InstrumentMasterSnapshot,
    "Venue": Venue,
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.contract
@pytest.mark.schema
def test_valid_mvp_spot_snapshot_fixture_validates_and_round_trips() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")

    snapshot = InstrumentMasterSnapshot.model_validate(payload)

    assert snapshot.snapshot_id == "S1_001_MVP_SPOT_FIXTURE"
    assert {asset.asset_id for asset in snapshot.assets} == {"BTC", "USD"}
    assert snapshot.instruments[0].instrument_id == "COINBASE_SPOT:BTC-USD"
    assert snapshot.accounts[0].live_capital_enabled is False

    round_tripped = InstrumentMasterSnapshot.model_validate(snapshot.model_dump(mode="json"))
    assert round_tripped == snapshot


@pytest.mark.contract
@pytest.mark.schema
@pytest.mark.parametrize("fixture_path", sorted((FIXTURE_ROOT / "invalid").glob("*.json")))
def test_invalid_record_fixtures_are_rejected(fixture_path: Path) -> None:
    fixture = _load_json(fixture_path)
    model_name = fixture["target_schema"]
    model = MODEL_BY_NAME[model_name]

    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(fixture["payload"])

    error_text = str(exc_info.value)
    for expected_substring in fixture["expected_error_substrings"]:
        assert expected_substring in error_text


@pytest.mark.contract
@pytest.mark.schema
def test_json_schemas_expose_required_canonical_metadata_fields() -> None:
    schema_by_model = {
        "Asset": Asset.model_json_schema(),
        "Venue": Venue.model_json_schema(),
        "Instrument": Instrument.model_json_schema(),
        "Account": Account.model_json_schema(),
    }

    assert {"asset_id", "symbol", "asset_type", "classifications"}.issubset(
        schema_by_model["Asset"]["required"]
    )
    assert {"venue_id", "timezone", "rate_limits", "supported_order_types"}.issubset(
        schema_by_model["Venue"]["required"]
    )
    assert {
        "instrument_id",
        "base_asset_id",
        "quote_asset_id",
        "venue_id",
        "tick_size",
        "lot_size",
        "min_notional",
        "fee_schedule_id",
        "effective_from",
    }.issubset(schema_by_model["Instrument"]["required"])
    assert {"account_id", "venue_id", "trading_permissions", "risk_limits", "key_scope"}.issubset(
        schema_by_model["Account"]["required"]
    )


@pytest.mark.contract
@pytest.mark.schema
def test_contracts_forbid_unknown_fields_to_prevent_silent_drift() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")
    payload["assets"][0]["undocumented_field"] = "must fail"

    with pytest.raises(ValidationError) as exc_info:
        InstrumentMasterSnapshot.model_validate(payload)

    assert "Extra inputs are not permitted" in str(exc_info.value)
