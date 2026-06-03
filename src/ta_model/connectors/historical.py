"""Contract-first historical connector interface.

S2-001 intentionally exposes only a protocol that future approved-source adapters
must implement. It performs no network calls and cannot approve a data source by itself.
"""

from __future__ import annotations

from typing import Protocol

from ta_model.contracts.market_data import HistoricalBackfillPage, HistoricalBackfillRequest


class HistoricalConnector(Protocol):
    """Protocol for historical OHLCTV and trade backfill connectors."""

    @property
    def source_id(self) -> str:
        """Source-register identifier implemented by this connector."""

    def backfill_ohlctv(
        self, request: HistoricalBackfillRequest
    ) -> tuple[HistoricalBackfillPage, ...]:
        """Return validated OHLCTV pages for an approved historical request."""

    def backfill_trades(
        self, request: HistoricalBackfillRequest
    ) -> tuple[HistoricalBackfillPage, ...]:
        """Return validated trade pages for an approved historical request."""
