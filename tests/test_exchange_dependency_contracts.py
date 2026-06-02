"""Dependency and source-register evidence for exchange connector enablement."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

PROJECT_ROOT = Path(__file__).parents[1]
SOURCE_REGISTER = PROJECT_ROOT / "docs" / "source_license_register.csv"


class CcxtExchange(Protocol):
    """Minimal offline surface expected from a CCXT exchange instance."""

    id: str
    name: str
    has: Mapping[str, object]
    urls: Mapping[str, object]


class CcxtExchangeFactory(Protocol):
    """Factory shape exposed by CCXT exchange classes."""

    def __call__(self, config: Mapping[str, object] | None = None) -> CcxtExchange: ...


def test_ccxt_dependency_exposes_binance_spot_rest_capabilities_without_network() -> None:
    """CCXT can construct Binance metadata offline without credentials or I/O."""

    ccxt_module = import_module("ccxt")
    binance_factory = cast("CcxtExchangeFactory", vars(ccxt_module)["binance"])

    exchange = binance_factory({"enableRateLimit": True})

    api_urls = cast("Mapping[str, object]", exchange.urls["api"])

    assert exchange.id == "binance"
    assert exchange.name == "Binance"
    assert exchange.has["fetchOHLCV"] is True
    assert exchange.has["fetchTrades"] is True
    assert "public" in api_urls


def test_binance_source_register_entry_remains_blocked_pending_review() -> None:
    """Binance support is registered but not approved for ingestion or paper use."""

    with SOURCE_REGISTER.open(newline="", encoding="utf-8") as register_file:
        rows = {
            row["source_id"]: row
            for row in csv.DictReader(register_file)
            if row["source_id"] == "binance_spot_market_data"
        }

    binance_row = rows["binance_spot_market_data"]

    assert binance_row["source_type"] == "official_venue_market_data"
    assert binance_row["priority_scope"] == "P0"
    assert "FR-003" in binance_row["requirement_trace"]
    assert "REST_via_ccxt" in binance_row["access_method"]
    assert binance_row["license_review_status"] == "not_started"
    assert binance_row["approved_use_status"] == "blocked_pending_review"
    assert binance_row["production_use_status"] == "not_approved_for_production"
    assert "no ingestion paper use or production use until approved" in binance_row[
        "decision_notes"
    ]
