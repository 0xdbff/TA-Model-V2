"""Schema evidence for S1 instrument-master contracts."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

from ta_model.contracts.instrument_master import (
    Account,
    Asset,
    ConstraintViolation,
    FeeSchedule,
    Instrument,
    InstrumentConstraint,
    InstrumentMasterSnapshot,
    TradingSession,
    Venue,
)

type FixtureModel = type[BaseModel]

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "instrument_master"
PROJECT_ROOT = Path(__file__).parents[1]
MVP_SPOT_SEED = PROJECT_ROOT / "configs" / "instrument_master" / "mvp_spot_seed.json"
MODEL_BY_NAME: dict[str, FixtureModel] = {
    "Account": Account,
    "Asset": Asset,
    "FeeSchedule": FeeSchedule,
    "Instrument": Instrument,
    "InstrumentConstraint": InstrumentConstraint,
    "InstrumentMasterSnapshot": InstrumentMasterSnapshot,
    "TradingSession": TradingSession,
    "Venue": Venue,
}


def _load_json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.contract
@pytest.mark.schema
def test_valid_mvp_spot_snapshot_fixture_validates_and_round_trips() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")

    snapshot = InstrumentMasterSnapshot.model_validate(payload)

    assert snapshot.snapshot_id == "S1_002_MVP_SPOT_CONSTRAINT_FIXTURE"
    assert {asset.asset_id for asset in snapshot.assets} == {"BTC", "ETH", "SOL", "USD"}
    assert {instrument.instrument_id for instrument in snapshot.instruments} == {
        "COINBASE_SPOT:BTC-USD",
        "COINBASE_SPOT:ETH-USD",
        "COINBASE_SPOT:SOL-USD",
    }
    assert {fee.fee_schedule_id for fee in snapshot.fee_schedules} == {
        "COINBASE_SPOT_STANDARD_FEES_2026Q1"
    }
    assert {session.session_id for session in snapshot.trading_sessions} == {
        "COINBASE_SPOT_24X7_2026Q1"
    }
    assert len(snapshot.instrument_constraints) == len(snapshot.instruments)
    assert snapshot.accounts[0].live_capital_enabled is False

    round_tripped = InstrumentMasterSnapshot.model_validate(snapshot.model_dump(mode="json"))
    assert round_tripped == snapshot


@pytest.mark.contract
@pytest.mark.schema
def test_s1_003_mvp_seed_maps_canonical_instruments_to_venue_symbols() -> None:
    payload = _load_json(MVP_SPOT_SEED)

    snapshot = InstrumentMasterSnapshot.model_validate(payload)

    assert snapshot.snapshot_id == "S1_003_MVP_SPOT_MAPPING_SEED"
    expected_mapping = {
        "COINBASE_SPOT:BTC-USD": (
            "BTC-USD",
            "COINBASE_SPOT",
            "BTC-USD",
            "BTC",
            "USD",
            Decimal("0.01"),
            Decimal("0.00000001"),
            Decimal("1.00"),
        ),
        "COINBASE_SPOT:ETH-USD": (
            "ETH-USD",
            "COINBASE_SPOT",
            "ETH-USD",
            "ETH",
            "USD",
            Decimal("0.01"),
            Decimal("0.00000001"),
            Decimal("1.00"),
        ),
        "COINBASE_SPOT:SOL-USD": (
            "SOL-USD",
            "COINBASE_SPOT",
            "SOL-USD",
            "SOL",
            "USD",
            Decimal("0.01"),
            Decimal("0.000001"),
            Decimal("1.00"),
        ),
    }
    actual_mapping = {
        instrument.instrument_id: (
            instrument.canonical_symbol,
            instrument.venue_id,
            instrument.venue_symbol,
            instrument.base_asset_id,
            instrument.quote_asset_id,
            instrument.tick_size,
            instrument.lot_size,
            instrument.min_notional,
        )
        for instrument in snapshot.instruments
    }

    assert actual_mapping == expected_mapping
    assert len(snapshot.instruments) == 3
    assert {instrument.fee_schedule_id for instrument in snapshot.instruments} == {
        "COINBASE_SPOT_STANDARD_FEES_2026Q2"
    }
    assert {session.session_id for session in snapshot.trading_sessions} == {
        "COINBASE_SPOT_24X7_2026Q2"
    }
    assert {instrument.instrument_type.value for instrument in snapshot.instruments} == {"spot"}
    assert {instrument.status.value for instrument in snapshot.instruments} == {"trading"}
    assert not any(instrument.is_derivative for instrument in snapshot.instruments)
    assert not any(instrument.margin_allowed for instrument in snapshot.instruments)
    assert not any(instrument.short_selling_allowed for instrument in snapshot.instruments)
    assert not any(instrument.leverage_allowed for instrument in snapshot.instruments)
    assert {asset.source_id for asset in snapshot.assets} == {"S1_003_MAPPING_SEED"}
    assert {venue.source_id for venue in snapshot.venues} == {"S1_003_MAPPING_SEED"}
    assert {instrument.source_id for instrument in snapshot.instruments} == {
        "S1_003_MAPPING_SEED"
    }
    seed_account = snapshot.accounts[0]
    assert seed_account.live_capital_enabled is False
    assert seed_account.withdrawals_enabled is False
    assert seed_account.margin_enabled is False
    assert seed_account.derivatives_enabled is False
    assert seed_account.shorting_enabled is False


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
        "FeeSchedule": FeeSchedule.model_json_schema(),
        "TradingSession": TradingSession.model_json_schema(),
        "InstrumentConstraint": InstrumentConstraint.model_json_schema(),
        "Instrument": Instrument.model_json_schema(),
        "InstrumentMasterSnapshot": InstrumentMasterSnapshot.model_json_schema(),
        "Account": Account.model_json_schema(),
    }

    assert {"asset_id", "symbol", "asset_type", "classifications"}.issubset(
        schema_by_model["Asset"]["required"]
    )
    assert {"venue_id", "timezone", "rate_limits", "supported_order_types"}.issubset(
        schema_by_model["Venue"]["required"]
    )
    assert {
        "fee_schedule_id",
        "venue_id",
        "fee_tier_id",
        "maker_fee_rate",
        "taker_fee_rate",
        "effective_from",
    }.issubset(schema_by_model["FeeSchedule"]["required"])
    assert {
        "session_id",
        "venue_id",
        "timezone",
        "days_of_week",
        "status",
        "effective_from",
    }.issubset(schema_by_model["TradingSession"]["required"])
    assert {
        "constraint_id",
        "instrument_id",
        "tick_size",
        "lot_size",
        "min_notional",
        "effective_from",
    }.issubset(schema_by_model["InstrumentConstraint"]["required"])
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
    assert {"fee_schedules", "trading_sessions", "instrument_constraints"}.issubset(
        schema_by_model["InstrumentMasterSnapshot"]["required"]
    )


@pytest.mark.contract
@pytest.mark.schema
def test_effective_dated_constraints_match_current_instrument_fields() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")

    snapshot = InstrumentMasterSnapshot.model_validate(payload)

    constraint_by_instrument = {
        constraint.instrument_id: constraint for constraint in snapshot.instrument_constraints
    }
    assert set(constraint_by_instrument) == {
        instrument.instrument_id for instrument in snapshot.instruments
    }
    for instrument in snapshot.instruments:
        constraint = constraint_by_instrument[instrument.instrument_id]
        assert constraint.tick_size == instrument.tick_size
        assert constraint.lot_size == instrument.lot_size
        assert constraint.min_notional == instrument.min_notional


@pytest.mark.contract
@pytest.mark.schema
def test_instrument_constraint_order_validation_reports_reason_codes() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")
    snapshot = InstrumentMasterSnapshot.model_validate(payload)
    btc_constraint = next(
        constraint
        for constraint in snapshot.instrument_constraints
        if constraint.instrument_id == "COINBASE_SPOT:BTC-USD"
    )

    passing = btc_constraint.evaluate_order(
        price=Decimal("65000.01"),
        quantity=Decimal("0.00100000"),
    )
    assert passing.passed is True
    assert passing.reason_codes == ()

    failing = btc_constraint.evaluate_order(
        price=Decimal("65000.001"),
        quantity=Decimal("0.00000100"),
    )
    assert failing.passed is False
    assert ConstraintViolation.PRICE_NOT_ON_TICK in failing.reason_codes
    assert ConstraintViolation.NOTIONAL_BELOW_MINIMUM in failing.reason_codes


@pytest.mark.contract
@pytest.mark.schema
def test_snapshot_rejects_constraint_mismatch_with_instrument_fields() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")
    payload["instrument_constraints"][0]["min_notional"] = "2.00"

    with pytest.raises(ValidationError) as exc_info:
        InstrumentMasterSnapshot.model_validate(payload)

    assert "does not match active effective-dated constraint" in str(exc_info.value)


@pytest.mark.contract
@pytest.mark.schema
def test_snapshot_rejects_overlapping_effective_constraint_windows() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")
    overlapping_constraint = dict(payload["instrument_constraints"][0])
    overlapping_constraint["constraint_id"] = "COINBASE_SPOT:BTC-USD:CONSTRAINTS:OVERLAP"
    overlapping_constraint["effective_from"] = "2026-01-15T00:00:00Z"
    payload["instrument_constraints"].append(overlapping_constraint)

    with pytest.raises(ValidationError) as exc_info:
        InstrumentMasterSnapshot.model_validate(payload)

    assert "overlapping effective windows for instrument constraint" in str(exc_info.value)


@pytest.mark.contract
@pytest.mark.schema
def test_snapshot_rejects_missing_active_trading_session() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")
    payload["trading_sessions"][0]["status"] = "suspended"

    with pytest.raises(ValidationError) as exc_info:
        InstrumentMasterSnapshot.model_validate(payload)

    assert "no active effective-dated trading session" in str(exc_info.value)


@pytest.mark.contract
@pytest.mark.schema
def test_snapshot_rejects_account_without_active_fee_schedule() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")
    payload["created_at"] = "2026-02-01T00:00:00Z"
    payload["fee_schedules"][0]["effective_to"] = "2026-01-15T00:00:00Z"

    with pytest.raises(ValidationError) as exc_info:
        InstrumentMasterSnapshot.model_validate(payload)

    assert "without active effective-dated fee schedules" in str(exc_info.value)


@pytest.mark.contract
@pytest.mark.schema
def test_snapshot_rejects_instrument_without_active_fee_schedule() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")
    payload["created_at"] = "2026-02-01T00:00:00Z"
    payload["fee_schedules"][0]["effective_to"] = "2026-01-15T00:00:00Z"
    payload["accounts"] = []

    with pytest.raises(ValidationError) as exc_info:
        InstrumentMasterSnapshot.model_validate(payload)

    assert "exactly one active effective-dated fee schedule" in str(exc_info.value)


@pytest.mark.contract
@pytest.mark.schema
def test_contracts_forbid_unknown_fields_to_prevent_silent_drift() -> None:
    payload = _load_json(FIXTURE_ROOT / "valid" / "mvp_spot_snapshot.json")
    payload["assets"][0]["undocumented_field"] = "must fail"

    with pytest.raises(ValidationError) as exc_info:
        InstrumentMasterSnapshot.model_validate(payload)

    assert "Extra inputs are not permitted" in str(exc_info.value)
