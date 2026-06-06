"""Schema evidence for S1 instrument-master contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
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
type PayloadMutator = Callable[[dict[str, Any]], None]

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


def _consumer_contract_digest(consumer_view: dict[str, Any]) -> str:
    payload = json.dumps(consumer_view, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decimal_to_contract_string(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _build_s1_004_consumer_contract_view(
    snapshot: InstrumentMasterSnapshot,
) -> dict[str, Any]:
    """Build the stable S1-004 view future consumers can reuse as a test vector."""

    venues_by_id = {venue.venue_id: venue for venue in snapshot.venues}
    fee_schedules_by_id = {fee.fee_schedule_id: fee for fee in snapshot.fee_schedules}
    constraints_by_instrument_id = {
        constraint.instrument_id: constraint for constraint in snapshot.instrument_constraints
    }
    sessions_by_venue_id = {
        venue.venue_id: sorted(
            session.session_id
            for session in snapshot.trading_sessions
            if session.venue_id == venue.venue_id and session.status.value == "active"
        )
        for venue in snapshot.venues
    }
    paper_account_by_venue_id = {
        account.venue_id: account
        for account in snapshot.accounts
        if account.account_type.value == "paper"
    }

    ingestion_contracts: list[dict[str, Any]] = []
    simulator_contracts: list[dict[str, Any]] = []
    risk_contracts: list[dict[str, Any]] = []
    gateway_contracts: list[dict[str, Any]] = []

    for instrument in sorted(snapshot.instruments, key=lambda item: item.instrument_id):
        venue = venues_by_id[instrument.venue_id]
        fee_schedule = fee_schedules_by_id[instrument.fee_schedule_id]
        constraint = constraints_by_instrument_id[instrument.instrument_id]
        paper_account = paper_account_by_venue_id[instrument.venue_id]

        ingestion_contracts.append(
            {
                "active_session_ids": sessions_by_venue_id[instrument.venue_id],
                "base_asset_id": instrument.base_asset_id,
                "canonical_symbol": instrument.canonical_symbol,
                "instrument_id": instrument.instrument_id,
                "market_data_rate_limit_ids": sorted(
                    rate_limit.rate_limit_id for rate_limit in venue.rate_limits
                ),
                "quote_asset_id": instrument.quote_asset_id,
                "source_id": instrument.source_id,
                "venue_id": instrument.venue_id,
                "venue_status": venue.status.value,
                "venue_symbol": instrument.venue_symbol,
                "venue_timezone": venue.timezone,
            }
        )
        simulator_contracts.append(
            {
                "fee_asset_id": fee_schedule.fee_asset_id,
                "fee_schedule_id": fee_schedule.fee_schedule_id,
                "instrument_id": instrument.instrument_id,
                "lot_size": _decimal_to_contract_string(constraint.lot_size),
                "maker_fee_rate": _decimal_to_contract_string(fee_schedule.maker_fee_rate),
                "min_notional": _decimal_to_contract_string(constraint.min_notional),
                "min_order_quantity": _decimal_to_contract_string(
                    constraint.min_order_quantity
                ),
                "status": instrument.status.value,
                "supported_order_types": sorted(
                    order_type.value for order_type in instrument.supported_order_types
                ),
                "taker_fee_rate": _decimal_to_contract_string(fee_schedule.taker_fee_rate),
                "tick_size": _decimal_to_contract_string(constraint.tick_size),
            }
        )
        risk_contracts.append(
            {
                "constraint_id": constraint.constraint_id,
                "instrument_id": instrument.instrument_id,
                "lot_size": _decimal_to_contract_string(constraint.lot_size),
                "max_drawdown_pct": _decimal_to_contract_string(
                    paper_account.risk_limits.max_drawdown_pct
                ),
                "max_order_notional_pct": _decimal_to_contract_string(
                    paper_account.risk_limits.max_order_notional_pct
                ),
                "min_cash_reserve_pct": _decimal_to_contract_string(
                    paper_account.risk_limits.min_cash_reserve_pct
                ),
                "min_notional": _decimal_to_contract_string(constraint.min_notional),
                "min_order_quantity": _decimal_to_contract_string(
                    constraint.min_order_quantity
                ),
                "tick_size": _decimal_to_contract_string(constraint.tick_size),
            }
        )
        gateway_contracts.append(
            {
                "account_id": paper_account.account_id,
                "instrument_id": instrument.instrument_id,
                "is_derivative": instrument.is_derivative,
                "key_scope": paper_account.key_scope.value,
                "leverage_allowed": instrument.leverage_allowed,
                "live_capital_enabled": paper_account.live_capital_enabled,
                "margin_allowed": instrument.margin_allowed,
                "short_selling_allowed": instrument.short_selling_allowed,
                "supported_order_types": sorted(
                    order_type.value for order_type in instrument.supported_order_types
                ),
                "trading_permissions": sorted(
                    permission.value for permission in paper_account.trading_permissions
                ),
            }
        )

    return {
        "created_at": snapshot.created_at.isoformat(),
        "requirement_trace": ["FR-003", "NFR-005"],
        "schema_version": snapshot.schema_version,
        "snapshot_id": snapshot.snapshot_id,
        "source_id": snapshot.source_id,
        "source_version": snapshot.source_version,
        "views": {
            "gateway": gateway_contracts,
            "ingestion": ingestion_contracts,
            "risk": risk_contracts,
            "simulator": simulator_contracts,
        },
    }


def _expire_seed_fee_schedule(payload: dict[str, Any]) -> None:
    payload["created_at"] = "2026-07-01T00:00:00Z"
    payload["fee_schedules"][0]["effective_to"] = "2026-06-15T00:00:00Z"


def _suspend_seed_trading_session(payload: dict[str, Any]) -> None:
    payload["trading_sessions"][0]["status"] = "suspended"


def _expire_seed_instrument_constraint(payload: dict[str, Any]) -> None:
    payload["created_at"] = "2026-07-01T00:00:00Z"
    payload["instrument_constraints"][0]["effective_to"] = "2026-06-15T00:00:00Z"


def _remove_seed_gateway_limit_order_support(payload: dict[str, Any]) -> None:
    payload["venues"][0]["supported_order_types"] = ["market"]


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
def test_s1_004_downstream_consumers_can_derive_required_views_from_seed() -> None:
    payload = _load_json(MVP_SPOT_SEED)

    snapshot = InstrumentMasterSnapshot.model_validate(payload)
    consumer_view = _build_s1_004_consumer_contract_view(snapshot)
    views = consumer_view["views"]

    assert set(views) == {"gateway", "ingestion", "risk", "simulator"}
    assert {record["instrument_id"] for record in views["ingestion"]} == {
        "COINBASE_SPOT:BTC-USD",
        "COINBASE_SPOT:ETH-USD",
        "COINBASE_SPOT:SOL-USD",
    }

    btc_ingestion_contract = views["ingestion"][0]
    assert btc_ingestion_contract == {
        "active_session_ids": ["COINBASE_SPOT_24X7_2026Q2"],
        "base_asset_id": "BTC",
        "canonical_symbol": "BTC-USD",
        "instrument_id": "COINBASE_SPOT:BTC-USD",
        "market_data_rate_limit_ids": ["COINBASE_SPOT_REST_METADATA"],
        "quote_asset_id": "USD",
        "source_id": "S1_003_MAPPING_SEED",
        "venue_id": "COINBASE_SPOT",
        "venue_status": "active",
        "venue_symbol": "BTC-USD",
        "venue_timezone": "UTC",
    }

    btc_simulator_contract = views["simulator"][0]
    assert btc_simulator_contract["maker_fee_rate"] == "0.0060"
    assert btc_simulator_contract["taker_fee_rate"] == "0.0060"
    assert btc_simulator_contract["tick_size"] == "0.01"
    assert btc_simulator_contract["lot_size"] == "0.00000001"
    assert btc_simulator_contract["min_notional"] == "1.00"
    assert btc_simulator_contract["supported_order_types"] == ["limit", "market"]

    btc_constraint = next(
        constraint
        for constraint in snapshot.instrument_constraints
        if constraint.instrument_id == "COINBASE_SPOT:BTC-USD"
    )
    risk_pass = btc_constraint.evaluate_order(
        price=Decimal("65000.00"),
        quantity=Decimal("0.001"),
    )
    risk_fail = btc_constraint.evaluate_order(
        price=Decimal("65000.001"),
        quantity=Decimal("0.000001"),
    )
    assert risk_pass.passed is True
    assert risk_fail.passed is False
    assert risk_fail.reason_codes == (
        ConstraintViolation.PRICE_NOT_ON_TICK,
        ConstraintViolation.NOTIONAL_BELOW_MINIMUM,
    )
    assert views["risk"][0] == {
        "constraint_id": "COINBASE_SPOT:BTC-USD:CONSTRAINTS:2026Q2",
        "instrument_id": "COINBASE_SPOT:BTC-USD",
        "lot_size": "0.00000001",
        "max_drawdown_pct": "0.08",
        "max_order_notional_pct": "0.025",
        "min_cash_reserve_pct": "0.30",
        "min_notional": "1.00",
        "min_order_quantity": "0.00000001",
        "tick_size": "0.01",
    }

    btc_gateway_contract = views["gateway"][0]
    assert btc_gateway_contract["account_id"] == "PAPER_COINBASE_SPOT_001"
    assert btc_gateway_contract["key_scope"] == "paper_trade"
    assert btc_gateway_contract["live_capital_enabled"] is False
    assert btc_gateway_contract["is_derivative"] is False
    assert btc_gateway_contract["margin_allowed"] is False
    assert btc_gateway_contract["short_selling_allowed"] is False
    assert btc_gateway_contract["leverage_allowed"] is False
    assert btc_gateway_contract["supported_order_types"] == ["limit", "market"]
    assert btc_gateway_contract["trading_permissions"] == [
        "cancel_orders",
        "place_orders",
        "read_market_data",
        "view_balances",
    ]


@pytest.mark.contract
@pytest.mark.schema
def test_s1_004_consumer_contract_view_is_reproducible() -> None:
    payload = _load_json(MVP_SPOT_SEED)

    snapshot = InstrumentMasterSnapshot.model_validate(payload)
    consumer_view = _build_s1_004_consumer_contract_view(snapshot)

    assert (
        _consumer_contract_digest(consumer_view)
        == "f5d0694b5ed521e28158b91851a1aac2534b7129b1e09bfe3545c7c687b35b68"
    )


@pytest.mark.contract
@pytest.mark.schema
@pytest.mark.parametrize(
    ("mutate_payload", "expected_error"),
    [
        (
            _expire_seed_fee_schedule,
            "without active effective-dated fee schedules",
        ),
        (
            _suspend_seed_trading_session,
            "no active effective-dated trading session",
        ),
        (
            _expire_seed_instrument_constraint,
            "must have exactly one active effective-dated constraint",
        ),
        (
            _remove_seed_gateway_limit_order_support,
            "venue-unsupported order types",
        ),
    ],
)
def test_s1_004_downstream_consumers_fail_closed_on_missing_required_metadata(
    mutate_payload: PayloadMutator,
    expected_error: str,
) -> None:
    payload = deepcopy(_load_json(MVP_SPOT_SEED))
    mutate_payload(payload)

    with pytest.raises(ValidationError) as exc_info:
        InstrumentMasterSnapshot.model_validate(payload)

    assert expected_error in str(exc_info.value)


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
