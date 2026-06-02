"""Canonical instrument-master contracts.

Traceability:
- FR-003: normalize symbols, assets, venues, tick size, lot size, min notional, and fees.
- NFR-004: preserve auditability with traceable decision/order metadata prerequisites.

Scope:
- S1-001 implements Pydantic v2 schemas and fixture-testable validation only.
- No connector, data pull, paper gateway, live capital, leverage, margin, shorting,
  derivatives, or autonomous model promotion path is introduced here.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, ClassVar, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StringConstraints,
    field_validator,
    model_validator,
)

CanonicalId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z0-9][A-Z0-9._:-]*$",
    ),
]
Symbol = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Z0-9][A-Z0-9._:/-]*$",
    ),
]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PositiveDecimal = Annotated[Decimal, Field(gt=Decimal("0"))]
BoundedRiskFraction = Annotated[Decimal, Field(gt=Decimal("0"), le=Decimal("1"))]


class ContractModel(BaseModel):
    """Base settings shared by schema contracts.

    Unknown fields are rejected so downstream ingestion, simulator, risk, and
    gateway consumers cannot silently accept drifted metadata shapes.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class SourceStampedModel(ContractModel):
    """Common source lineage fields for auditable metadata records."""

    source_id: CanonicalId = Field(
        description=(
            "Approved source/register identifier or explicit fixture source used to derive "
            "this metadata record."
        )
    )
    source_version: NonEmptyString | None = Field(
        default=None,
        description="Source/register version or review handle when available.",
    )
    metadata_ts: AwareDatetime = Field(
        description="Event-time/source-review timestamp for this metadata record."
    )


class AssetType(StrEnum):
    """Canonical asset type families supported by the S1 contract."""

    CRYPTO = "crypto"
    FIAT = "fiat"
    STABLECOIN = "stablecoin"
    EQUITY = "equity"
    FUND = "fund"
    COMMODITY = "commodity"
    INDEX = "index"
    OTHER = "other"


class AssetClassification(StrEnum):
    """Required high-level flags used for asset-agnostic downstream handling."""

    CRYPTO = "crypto"
    FIAT = "fiat"
    STABLECOIN = "stablecoin"
    EQUITY = "equity"


class AssetStatus(StrEnum):
    """Lifecycle status for canonical assets."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DELISTED = "delisted"


class VenueType(StrEnum):
    """Venue families for metadata normalization."""

    EXCHANGE = "exchange"
    BROKER = "broker"
    DATA_VENDOR = "data_vendor"
    SIMULATOR = "simulator"
    PAPER = "paper"


class VenueStatus(StrEnum):
    """Venue operational status.

    Runtime consumers must fail closed on UNKNOWN, HALTED, or MAINTENANCE where
    the status is required for trading decisions.
    """

    ACTIVE = "active"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    HALTED = "halted"
    UNKNOWN = "unknown"
    INACTIVE = "inactive"


class RateLimitScope(StrEnum):
    """Scope to which a rate-limit rule applies."""

    REST = "rest"
    WEBSOCKET = "websocket"
    MARKET_DATA = "market_data"
    ORDER = "order"
    METADATA = "metadata"


class OrderType(StrEnum):
    """Normalized order types understood by downstream gateway contracts."""

    MARKET = "market"
    LIMIT = "limit"
    POST_ONLY_LIMIT = "post_only_limit"


class InstrumentType(StrEnum):
    """Instrument classes permitted in the MVP contract.

    Derivative-specific instruments are intentionally absent until a P2-approved
    derivatives issue adds the required fields and risk controls.
    """

    SPOT = "spot"
    CASH_EQUITY = "cash_equity"
    FUND = "fund"
    INDEX = "index"
    OTHER = "other"


class InstrumentStatus(StrEnum):
    """Trading lifecycle status for a venue-specific instrument."""

    TRADING = "trading"
    PAUSED = "paused"
    HALTED = "halted"
    DELISTED = "delisted"
    UNKNOWN = "unknown"


class AccountType(StrEnum):
    """Account contexts allowed before future limited-live approval."""

    RESEARCH = "research"
    SIMULATION = "simulation"
    PAPER = "paper"


class AccountStatus(StrEnum):
    """Account operational status."""

    ACTIVE = "active"
    DISABLED = "disabled"
    READ_ONLY = "read_only"
    UNKNOWN = "unknown"


class TradingPermission(StrEnum):
    """Least-privilege trading/account permissions captured in account metadata."""

    READ_MARKET_DATA = "read_market_data"
    VIEW_BALANCES = "view_balances"
    PLACE_ORDERS = "place_orders"
    CANCEL_ORDERS = "cancel_orders"


class KeyScope(StrEnum):
    """Credential scope categories allowed by the MVP contract."""

    NONE = "none"
    READ_ONLY = "read_only"
    PAPER_TRADE = "paper_trade"
    TRADE_NO_WITHDRAWAL = "trade_no_withdrawal"


class Asset(SourceStampedModel):
    """Canonical asset metadata shared across venues and instruments."""

    _REQUIRED_CLASSIFICATION_BY_TYPE: ClassVar[dict[AssetType, AssetClassification]] = {
        AssetType.CRYPTO: AssetClassification.CRYPTO,
        AssetType.FIAT: AssetClassification.FIAT,
        AssetType.STABLECOIN: AssetClassification.STABLECOIN,
        AssetType.EQUITY: AssetClassification.EQUITY,
    }

    schema_version: Literal["asset.v1"] = "asset.v1"
    asset_id: CanonicalId
    symbol: Symbol
    name: NonEmptyString
    asset_type: AssetType
    classifications: frozenset[AssetClassification] = Field(min_length=1)
    issuer: NonEmptyString | None = None
    category: NonEmptyString | None = None
    status: AssetStatus

    @model_validator(mode="after")
    def validate_classification_flags(self) -> Self:
        required_classification = self._REQUIRED_CLASSIFICATION_BY_TYPE.get(self.asset_type)
        if (
            required_classification is not None
            and required_classification not in self.classifications
        ):
            msg = (
                f"asset_type={self.asset_type.value!r} requires classification "
                f"{required_classification.value!r}"
            )
            raise ValueError(msg)

        if AssetClassification.STABLECOIN in self.classifications:
            if AssetClassification.CRYPTO not in self.classifications:
                raise ValueError("stablecoin assets must also carry the crypto classification")
            if AssetClassification.FIAT in self.classifications:
                raise ValueError("stablecoin assets cannot also be classified as fiat")

        if (
            AssetClassification.FIAT in self.classifications
            and AssetClassification.CRYPTO in self.classifications
        ):
            raise ValueError("fiat and crypto classifications cannot be combined")

        return self


class ApiEndpointGroup(ContractModel):
    """Named API endpoint group for a venue/source."""

    group_id: CanonicalId
    rest_base_url: NonEmptyString | None = None
    websocket_url: NonEmptyString | None = None
    status_url: NonEmptyString | None = None
    documentation_url: NonEmptyString | None = None

    @model_validator(mode="after")
    def require_endpoint(self) -> Self:
        if self.rest_base_url is None and self.websocket_url is None:
            raise ValueError("api endpoint group requires at least one REST or WebSocket endpoint")
        return self


class RateLimit(ContractModel):
    """Rate-limit rule captured as normalized venue metadata."""

    rate_limit_id: CanonicalId
    scope: RateLimitScope
    limit: PositiveInt = Field(description="Maximum allowed operations in the interval.")
    interval_seconds: PositiveInt
    burst_limit: PositiveInt | None = None


class Venue(SourceStampedModel):
    """Canonical venue metadata consumed by ingestion, risk, and gateway code."""

    schema_version: Literal["venue.v1"] = "venue.v1"
    venue_id: CanonicalId
    name: NonEmptyString
    venue_type: VenueType
    timezone: NonEmptyString
    api_endpoint_group: ApiEndpointGroup
    status: VenueStatus
    rate_limits: tuple[RateLimit, ...] = Field(min_length=1)
    supported_order_types: frozenset[OrderType] = Field(min_length=1)

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_valid_iana_name(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"timezone must be a valid IANA timezone: {value}") from exc
        return value


class Instrument(SourceStampedModel):
    """Venue-specific tradable instrument mapped to canonical assets."""

    schema_version: Literal["instrument.v1"] = "instrument.v1"
    instrument_id: CanonicalId
    venue_id: CanonicalId
    base_asset_id: CanonicalId
    quote_asset_id: CanonicalId
    venue_symbol: Symbol
    canonical_symbol: Symbol
    instrument_type: InstrumentType
    status: InstrumentStatus
    tick_size: PositiveDecimal
    lot_size: PositiveDecimal
    min_notional: PositiveDecimal
    fee_schedule_id: CanonicalId = Field(
        description="Reference to the effective-dated fee schedule implemented in S1-002."
    )
    supported_order_types: frozenset[OrderType] = Field(min_length=1)
    effective_from: AwareDatetime
    effective_to: AwareDatetime | None = None
    is_derivative: Literal[False]
    margin_allowed: Literal[False]
    short_selling_allowed: Literal[False]
    leverage_allowed: Literal[False]

    @model_validator(mode="after")
    def validate_instrument_constraints(self) -> Self:
        if self.base_asset_id == self.quote_asset_id:
            raise ValueError("base_asset_id and quote_asset_id must differ")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self


class AccountRiskLimits(ContractModel):
    """Initial account-level hard risk bounds from the S0 risk policy.

    Values are fractions of paper/simulated NAV. Account-specific limits may be
    stricter than these caps, but widening the caps requires an owner-approved
    risk-policy change.
    """

    max_order_notional_pct: BoundedRiskFraction = Field(le=Decimal("0.025"))
    max_instrument_exposure_pct: BoundedRiskFraction = Field(le=Decimal("0.25"))
    max_strategy_exposure_pct: BoundedRiskFraction = Field(le=Decimal("0.30"))
    max_total_spot_exposure_pct: BoundedRiskFraction = Field(le=Decimal("0.60"))
    min_cash_reserve_pct: BoundedRiskFraction = Field(ge=Decimal("0.30"))
    max_daily_loss_pct: BoundedRiskFraction = Field(le=Decimal("0.02"))
    max_drawdown_pct: BoundedRiskFraction = Field(le=Decimal("0.08"))

    @model_validator(mode="after")
    def validate_relative_limits(self) -> Self:
        if self.max_instrument_exposure_pct > self.max_total_spot_exposure_pct:
            raise ValueError("instrument exposure cap cannot exceed total spot exposure cap")
        if self.max_strategy_exposure_pct > self.max_total_spot_exposure_pct:
            raise ValueError("strategy exposure cap cannot exceed total spot exposure cap")
        return self


class Account(SourceStampedModel):
    """Canonical account metadata for simulation/paper contexts."""

    schema_version: Literal["account.v1"] = "account.v1"
    account_id: CanonicalId
    venue_id: CanonicalId
    account_type: AccountType
    status: AccountStatus
    trading_permissions: frozenset[TradingPermission] = Field(min_length=1)
    fee_tier_id: CanonicalId
    risk_limits: AccountRiskLimits
    key_scope: KeyScope
    live_capital_enabled: Literal[False]
    withdrawals_enabled: Literal[False]
    margin_enabled: Literal[False]
    derivatives_enabled: Literal[False]
    shorting_enabled: Literal[False]

    @model_validator(mode="after")
    def validate_least_privilege_scope(self) -> Self:
        if (
            self.account_type is AccountType.RESEARCH
            and TradingPermission.PLACE_ORDERS in self.trading_permissions
        ):
            raise ValueError("research accounts cannot include order-placement permission")
        if (
            self.key_scope is KeyScope.TRADE_NO_WITHDRAWAL
            and self.account_type is AccountType.RESEARCH
        ):
            raise ValueError("research accounts cannot use trade-capable key scope")
        return self


class InstrumentMasterSnapshot(SourceStampedModel):
    """Point-in-time snapshot of canonical instrument-master metadata."""

    schema_version: Literal["instrument-master.v1"] = "instrument-master.v1"
    snapshot_id: CanonicalId
    created_at: AwareDatetime
    assets: tuple[Asset, ...] = Field(min_length=1)
    venues: tuple[Venue, ...] = Field(min_length=1)
    instruments: tuple[Instrument, ...] = Field(min_length=1)
    accounts: tuple[Account, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        asset_ids = {asset.asset_id for asset in self.assets}
        venue_ids = {venue.venue_id for venue in self.venues}
        venue_order_types = {venue.venue_id: venue.supported_order_types for venue in self.venues}

        self._raise_on_duplicates((asset.asset_id for asset in self.assets), "asset_id")
        self._raise_on_duplicates((venue.venue_id for venue in self.venues), "venue_id")
        self._raise_on_duplicates(
            (instrument.instrument_id for instrument in self.instruments),
            "instrument_id",
        )
        self._raise_on_duplicates((account.account_id for account in self.accounts), "account_id")

        unknown_asset_refs = sorted(
            {
                asset_ref
                for instrument in self.instruments
                for asset_ref in (instrument.base_asset_id, instrument.quote_asset_id)
                if asset_ref not in asset_ids
            }
        )
        if unknown_asset_refs:
            raise ValueError(f"instruments reference unknown asset_id(s): {unknown_asset_refs}")

        unknown_instrument_venues = sorted(
            {
                instrument.venue_id
                for instrument in self.instruments
                if instrument.venue_id not in venue_ids
            }
        )
        if unknown_instrument_venues:
            raise ValueError(
                f"instruments reference unknown venue_id(s): {unknown_instrument_venues}"
            )

        unknown_account_venues = sorted(
            {account.venue_id for account in self.accounts if account.venue_id not in venue_ids}
        )
        if unknown_account_venues:
            raise ValueError(f"accounts reference unknown venue_id(s): {unknown_account_venues}")

        for instrument in self.instruments:
            unsupported_order_types = (
                instrument.supported_order_types - venue_order_types[instrument.venue_id]
            )
            if unsupported_order_types:
                unsupported = sorted(order_type.value for order_type in unsupported_order_types)
                raise ValueError(
                    f"instrument {instrument.instrument_id} has venue-unsupported order types: "
                    f"{unsupported}"
                )

        return self

    @staticmethod
    def _raise_on_duplicates(values: Iterable[str], field_name: str) -> None:
        duplicates = sorted(_duplicates(values))
        if duplicates:
            raise ValueError(f"duplicate {field_name} value(s): {duplicates}")


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return duplicates
