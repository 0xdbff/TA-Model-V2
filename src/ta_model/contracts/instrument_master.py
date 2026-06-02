"""Canonical instrument-master contracts.

Traceability:
- FR-003: normalize symbols, assets, venues, tick size, lot size, min notional, and fees.
- FR-010: provide fail-closed metadata prerequisites for independent pre-trade controls.
- NFR-004: preserve auditability with traceable decision/order metadata prerequisites.

Scope:
- S1-001 implements canonical asset, venue, instrument, account, and snapshot schemas.
- S1-002 adds effective-dated fee schedules, venue sessions, and instrument constraints.
- No connector, data pull, paper gateway, live capital, leverage, margin, shorting,
  derivatives, or autonomous model promotion path is introduced here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, ClassVar, Literal, Protocol, Self, TypeVar
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
NonNegativeDecimal = Annotated[Decimal, Field(ge=Decimal("0"))]
BoundedFeeRate = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("0.05"))]
BoundedRiskFraction = Annotated[Decimal, Field(gt=Decimal("0"), le=Decimal("1"))]


class EffectiveDated(Protocol):
    """Protocol for records with half-open effective-time windows."""

    effective_from: datetime
    effective_to: datetime | None


TEffective = TypeVar("TEffective", bound=EffectiveDated)


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


class DayOfWeek(StrEnum):
    """Normalized trading-session day names."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class TradingSessionStatus(StrEnum):
    """Effective-dated venue-session status used by fail-closed consumers."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class ConstraintViolation(StrEnum):
    """Machine-readable instrument-constraint validation reason codes."""

    NON_POSITIVE_PRICE = "non_positive_price"
    NON_POSITIVE_QUANTITY = "non_positive_quantity"
    PRICE_NOT_ON_TICK = "price_not_on_tick"
    QUANTITY_NOT_ON_LOT = "quantity_not_on_lot"
    QUANTITY_BELOW_MINIMUM = "quantity_below_minimum"
    QUANTITY_ABOVE_MAXIMUM = "quantity_above_maximum"
    NOTIONAL_BELOW_MINIMUM = "notional_below_minimum"
    NOTIONAL_ABOVE_MAXIMUM = "notional_above_maximum"


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


class FeeSchedule(SourceStampedModel):
    """Effective-dated trading fee schedule for cost and risk consumers.

    Rates are non-negative fractions of notional. Rebates are intentionally not
    represented in the MVP contract so early simulations and risk checks do not
    depend on optimistic negative-cost assumptions.
    """

    schema_version: Literal["fee-schedule.v1"] = "fee-schedule.v1"
    fee_schedule_id: CanonicalId
    venue_id: CanonicalId
    fee_tier_id: CanonicalId
    maker_fee_rate: BoundedFeeRate
    taker_fee_rate: BoundedFeeRate
    fee_asset_id: CanonicalId | None = Field(
        default=None,
        description="Asset used for fixed/minimum fees when applicable.",
    )
    min_fee: NonNegativeDecimal = Decimal("0")
    effective_from: AwareDatetime
    effective_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_fee_schedule_window(self) -> Self:
        _validate_effective_window(
            self.effective_from,
            self.effective_to,
            "fee schedule",
        )
        if self.min_fee > 0 and self.fee_asset_id is None:
            raise ValueError("fee_asset_id is required when min_fee is greater than zero")
        return self


class TradingSession(SourceStampedModel):
    """Effective-dated venue session contract.

    Sessions are venue-level metadata so ingestion, simulator, risk, and gateway
    consumers can fail closed when no active trading window is known.
    """

    schema_version: Literal["trading-session.v1"] = "trading-session.v1"
    session_id: CanonicalId
    venue_id: CanonicalId
    name: NonEmptyString
    timezone: NonEmptyString
    days_of_week: frozenset[DayOfWeek] = Field(min_length=1)
    is_24x7: bool = False
    open_time: time | None = None
    close_time: time | None = None
    status: TradingSessionStatus
    effective_from: AwareDatetime
    effective_to: AwareDatetime | None = None

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_valid_iana_name(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"timezone must be a valid IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def validate_session_window(self) -> Self:
        _validate_effective_window(
            self.effective_from,
            self.effective_to,
            "trading session",
        )

        if self.is_24x7:
            if self.days_of_week != frozenset(DayOfWeek):
                raise ValueError("24x7 trading sessions must include every day of week")
            if self.open_time is not None or self.close_time is not None:
                raise ValueError("24x7 trading sessions must not set open_time or close_time")
            return self

        if self.open_time is None or self.close_time is None:
            raise ValueError("non-24x7 trading sessions require open_time and close_time")
        if self.open_time == self.close_time:
            raise ValueError("open_time and close_time must differ for non-24x7 sessions")
        return self


class ConstraintValidationResult(ContractModel):
    """Deterministic result from validating a proposed order against constraints."""

    instrument_id: CanonicalId
    constraint_id: CanonicalId
    price: Decimal
    quantity: Decimal
    notional: Decimal
    passed: bool
    reason_codes: tuple[ConstraintViolation, ...]


class InstrumentConstraint(SourceStampedModel):
    """Effective-dated tick, lot, and notional constraints for an instrument."""

    schema_version: Literal["instrument-constraint.v1"] = "instrument-constraint.v1"
    constraint_id: CanonicalId
    instrument_id: CanonicalId
    tick_size: PositiveDecimal
    lot_size: PositiveDecimal
    min_notional: PositiveDecimal
    min_order_quantity: PositiveDecimal | None = None
    max_order_quantity: PositiveDecimal | None = None
    max_order_notional: PositiveDecimal | None = None
    effective_from: AwareDatetime
    effective_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_constraint_window_and_bounds(self) -> Self:
        _validate_effective_window(
            self.effective_from,
            self.effective_to,
            "instrument constraint",
        )
        if (
            self.min_order_quantity is not None
            and self.max_order_quantity is not None
            and self.max_order_quantity < self.min_order_quantity
        ):
            raise ValueError("max_order_quantity cannot be below min_order_quantity")
        if self.max_order_notional is not None and self.max_order_notional < self.min_notional:
            raise ValueError("max_order_notional cannot be below min_notional")
        return self

    def evaluate_order(self, *, price: Decimal, quantity: Decimal) -> ConstraintValidationResult:
        """Validate a proposed price/quantity against venue instrument constraints."""

        reason_codes: list[ConstraintViolation] = []
        notional = price * quantity

        if price <= 0:
            reason_codes.append(ConstraintViolation.NON_POSITIVE_PRICE)
        elif not _is_decimal_multiple(price, self.tick_size):
            reason_codes.append(ConstraintViolation.PRICE_NOT_ON_TICK)

        if quantity <= 0:
            reason_codes.append(ConstraintViolation.NON_POSITIVE_QUANTITY)
        else:
            minimum_quantity = self.min_order_quantity or self.lot_size
            if quantity < minimum_quantity:
                reason_codes.append(ConstraintViolation.QUANTITY_BELOW_MINIMUM)
            if not _is_decimal_multiple(quantity, self.lot_size):
                reason_codes.append(ConstraintViolation.QUANTITY_NOT_ON_LOT)
            if self.max_order_quantity is not None and quantity > self.max_order_quantity:
                reason_codes.append(ConstraintViolation.QUANTITY_ABOVE_MAXIMUM)

        if price > 0 and quantity > 0:
            if notional < self.min_notional:
                reason_codes.append(ConstraintViolation.NOTIONAL_BELOW_MINIMUM)
            if self.max_order_notional is not None and notional > self.max_order_notional:
                reason_codes.append(ConstraintViolation.NOTIONAL_ABOVE_MAXIMUM)

        return ConstraintValidationResult(
            instrument_id=self.instrument_id,
            constraint_id=self.constraint_id,
            price=price,
            quantity=quantity,
            notional=notional,
            passed=not reason_codes,
            reason_codes=tuple(reason_codes),
        )


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
    fee_schedules: tuple[FeeSchedule, ...] = Field(min_length=1)
    trading_sessions: tuple[TradingSession, ...] = Field(min_length=1)
    instrument_constraints: tuple[InstrumentConstraint, ...] = Field(min_length=1)
    instruments: tuple[Instrument, ...] = Field(min_length=1)
    accounts: tuple[Account, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        asset_ids = {asset.asset_id for asset in self.assets}
        venue_ids = {venue.venue_id for venue in self.venues}
        venue_order_types = {venue.venue_id: venue.supported_order_types for venue in self.venues}
        instrument_ids = {instrument.instrument_id for instrument in self.instruments}
        fee_schedule_ids = {fee_schedule.fee_schedule_id for fee_schedule in self.fee_schedules}
        fee_schedule_refs_by_venue = {
            (fee_schedule.venue_id, fee_schedule.fee_schedule_id)
            for fee_schedule in self.fee_schedules
        }
        fee_tier_refs_by_venue = {
            (fee_schedule.venue_id, fee_schedule.fee_tier_id)
            for fee_schedule in self.fee_schedules
        }

        self._raise_on_duplicates((asset.asset_id for asset in self.assets), "asset_id")
        self._raise_on_duplicates((venue.venue_id for venue in self.venues), "venue_id")
        self._raise_on_duplicates(
            (fee_schedule.fee_schedule_id for fee_schedule in self.fee_schedules),
            "fee_schedule_id",
        )
        self._raise_on_duplicates(
            (session.session_id for session in self.trading_sessions),
            "trading_session_id",
        )
        self._raise_on_duplicates(
            (constraint.constraint_id for constraint in self.instrument_constraints),
            "instrument_constraint_id",
        )
        self._raise_on_duplicates(
            (instrument.instrument_id for instrument in self.instruments),
            "instrument_id",
        )
        self._raise_on_duplicates((account.account_id for account in self.accounts), "account_id")

        _raise_on_overlapping_effective_windows(
            self.fee_schedules,
            key_func=lambda fee_schedule: f"{fee_schedule.venue_id}/{fee_schedule.fee_tier_id}",
            label="fee schedule",
        )
        _raise_on_overlapping_effective_windows(
            self.instrument_constraints,
            key_func=lambda constraint: constraint.instrument_id,
            label="instrument constraint",
        )

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

        unknown_fee_schedule_venues = sorted(
            {
                fee_schedule.venue_id
                for fee_schedule in self.fee_schedules
                if fee_schedule.venue_id not in venue_ids
            }
        )
        if unknown_fee_schedule_venues:
            raise ValueError(
                f"fee schedules reference unknown venue_id(s): {unknown_fee_schedule_venues}"
            )

        unknown_fee_assets = sorted(
            {
                fee_schedule.fee_asset_id
                for fee_schedule in self.fee_schedules
                if fee_schedule.fee_asset_id is not None
                and fee_schedule.fee_asset_id not in asset_ids
            }
        )
        if unknown_fee_assets:
            raise ValueError(
                f"fee schedules reference unknown fee_asset_id(s): {unknown_fee_assets}"
            )

        unknown_session_venues = sorted(
            {
                session.venue_id
                for session in self.trading_sessions
                if session.venue_id not in venue_ids
            }
        )
        if unknown_session_venues:
            raise ValueError(
                f"trading sessions reference unknown venue_id(s): {unknown_session_venues}"
            )

        unknown_constraint_instruments = sorted(
            {
                constraint.instrument_id
                for constraint in self.instrument_constraints
                if constraint.instrument_id not in instrument_ids
            }
        )
        if unknown_constraint_instruments:
            raise ValueError(
                "instrument constraints reference unknown instrument_id(s): "
                f"{unknown_constraint_instruments}"
            )

        unknown_instrument_fee_schedules = sorted(
            {
                instrument.fee_schedule_id
                for instrument in self.instruments
                if instrument.fee_schedule_id not in fee_schedule_ids
            }
        )
        if unknown_instrument_fee_schedules:
            raise ValueError(
                "instruments reference unknown fee_schedule_id(s): "
                f"{unknown_instrument_fee_schedules}"
            )

        accounts_without_fee_schedule = sorted(
            {
                account.account_id
                for account in self.accounts
                if (account.venue_id, account.fee_tier_id) not in fee_schedule_refs_by_venue
                and (account.venue_id, account.fee_tier_id) not in fee_tier_refs_by_venue
            }
        )
        if accounts_without_fee_schedule:
            raise ValueError(
                "accounts reference fee_tier_id values without venue fee schedules: "
                f"{accounts_without_fee_schedule}"
            )

        accounts_without_active_fee_schedule = sorted(
            {
                account.account_id
                for account in self.accounts
                if not any(
                    fee_schedule.venue_id == account.venue_id
                    and (
                        account.fee_tier_id
                        in {fee_schedule.fee_schedule_id, fee_schedule.fee_tier_id}
                    )
                    and _is_effective(fee_schedule, self.created_at)
                    for fee_schedule in self.fee_schedules
                )
            }
        )
        if accounts_without_active_fee_schedule:
            raise ValueError(
                "accounts reference fee_tier_id values without active effective-dated "
                f"fee schedules at snapshot time: {accounts_without_active_fee_schedule}"
            )

        missing_active_session_venues = sorted(
            {
                venue.venue_id
                for venue in self.venues
                if not any(
                    session.venue_id == venue.venue_id
                    and session.status is TradingSessionStatus.ACTIVE
                    and _is_effective(session, self.created_at)
                    for session in self.trading_sessions
                )
            }
        )
        if missing_active_session_venues:
            raise ValueError(
                "venues have no active effective-dated trading session at snapshot time: "
                f"{missing_active_session_venues}"
            )

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

            active_fee_schedules = [
                fee_schedule
                for fee_schedule in self.fee_schedules
                if fee_schedule.fee_schedule_id == instrument.fee_schedule_id
                and fee_schedule.venue_id == instrument.venue_id
                and _is_effective(fee_schedule, self.created_at)
            ]
            if len(active_fee_schedules) != 1:
                raise ValueError(
                    f"instrument {instrument.instrument_id} must reference exactly one active "
                    "effective-dated fee schedule at snapshot time"
                )

            active_constraints = [
                constraint
                for constraint in self.instrument_constraints
                if constraint.instrument_id == instrument.instrument_id
                and _is_effective(constraint, self.created_at)
            ]
            if len(active_constraints) != 1:
                raise ValueError(
                    f"instrument {instrument.instrument_id} must have exactly one active "
                    "effective-dated constraint at snapshot time"
                )
            active_constraint = active_constraints[0]
            if (
                instrument.tick_size != active_constraint.tick_size
                or instrument.lot_size != active_constraint.lot_size
                or instrument.min_notional != active_constraint.min_notional
            ):
                raise ValueError(
                    f"instrument {instrument.instrument_id} tick_size/lot_size/min_notional "
                    "does not match active effective-dated constraint"
                )

        return self

    @staticmethod
    def _raise_on_duplicates(values: Iterable[str], field_name: str) -> None:
        duplicates = sorted(_duplicates(values))
        if duplicates:
            raise ValueError(f"duplicate {field_name} value(s): {duplicates}")


def _validate_effective_window(
    effective_from: datetime,
    effective_to: datetime | None,
    record_name: str,
) -> None:
    if effective_to is not None and effective_to <= effective_from:
        raise ValueError(f"{record_name} effective_to must be after effective_from")


def _is_effective(record: EffectiveDated, as_of: datetime) -> bool:
    return record.effective_from <= as_of and (
        record.effective_to is None or as_of < record.effective_to
    )


def _raise_on_overlapping_effective_windows(
    records: Iterable[TEffective],
    *,
    key_func: Callable[[TEffective], str],
    label: str,
) -> None:
    windows_by_key: dict[str, list[TEffective]] = {}
    for record in records:
        windows_by_key.setdefault(key_func(record), []).append(record)

    for key, windows in windows_by_key.items():
        previous: TEffective | None = None
        for current in sorted(windows, key=lambda record: record.effective_from):
            if previous is not None:
                previous_end = previous.effective_to
                if previous_end is None or current.effective_from < previous_end:
                    raise ValueError(f"overlapping effective windows for {label} {key}")
            previous = current


def _is_decimal_multiple(value: Decimal, increment: Decimal) -> bool:
    return increment > 0 and value % increment == 0


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return duplicates
