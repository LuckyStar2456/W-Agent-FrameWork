"""Explicit, versioned model pricing and deterministic cost calculation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Mapping, Protocol

from .types import TokenUsage

_MILLION = Decimal(1_000_000)


class PricingError(ValueError):
    """A price table is invalid or cannot price a model attempt."""


class PriceNotFoundError(PricingError):
    """No explicit rate exists for a provider/model pair."""


def _amount(value: Decimal | str | int | float, label: str) -> Decimal:
    if isinstance(value, bool):
        raise PricingError(f"{label} must be a finite decimal")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise PricingError(f"{label} must be a finite decimal") from error
    if not amount.is_finite() or amount < 0:
        raise PricingError(f"{label} must be a non-negative finite decimal")
    return amount


def _identity(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise PricingError(f"{label} must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Per-million-token rates for one exact provider/model identity."""

    provider: str
    model: str
    input_per_million: Decimal | str | int | float
    output_per_million: Decimal | str | int | float
    cached_input_per_million: Decimal | str | int | float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _identity(self.provider, "provider"))
        object.__setattr__(self, "model", _identity(self.model, "model"))
        input_rate = _amount(self.input_per_million, "input rate")
        object.__setattr__(self, "input_per_million", input_rate)
        object.__setattr__(
            self,
            "output_per_million",
            _amount(self.output_per_million, "output rate"),
        )
        object.__setattr__(
            self,
            "cached_input_per_million",
            input_rate
            if self.cached_input_per_million is None
            else _amount(self.cached_input_per_million, "cached-input rate"),
        )


@dataclass(frozen=True, slots=True)
class ModelCost:
    """Exact cost for one attempt or an aggregate from one table version."""

    currency: str
    price_table_version: str
    input_cost: Decimal | str | int | float = Decimal(0)
    output_cost: Decimal | str | int | float = Decimal(0)
    cached_input_cost: Decimal | str | int | float = Decimal(0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", _identity(self.currency, "currency").upper())
        object.__setattr__(
            self,
            "price_table_version",
            _identity(self.price_table_version, "price-table version"),
        )
        for name in ("input_cost", "output_cost", "cached_input_cost"):
            object.__setattr__(self, name, _amount(getattr(self, name), name))

    @property
    def total(self) -> Decimal:
        return self.input_cost + self.output_cost + self.cached_input_cost

    def add(self, other: "ModelCost") -> "ModelCost":
        if (
            self.currency != other.currency
            or self.price_table_version != other.price_table_version
        ):
            raise PricingError("cost values use different currencies or table versions")
        return ModelCost(
            self.currency,
            self.price_table_version,
            self.input_cost + other.input_cost,
            self.output_cost + other.output_cost,
            self.cached_input_cost + other.cached_input_cost,
        )


@dataclass(frozen=True, slots=True)
class PriceTable:
    """Immutable exact-match price table with an application-owned version."""

    version: str
    currency: str
    prices: tuple[ModelPrice, ...]
    _index: Mapping[tuple[str, str], ModelPrice] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _identity(self.version, "price-table version"))
        object.__setattr__(self, "currency", _identity(self.currency, "currency").upper())
        prices = tuple(self.prices)
        if not prices:
            raise PricingError("price table needs at least one model price")
        index: dict[tuple[str, str], ModelPrice] = {}
        for price in prices:
            key = (price.provider, price.model)
            if key in index:
                raise PricingError("price table contains a duplicate provider/model")
            index[key] = price
        object.__setattr__(self, "prices", prices)
        object.__setattr__(self, "_index", MappingProxyType(index))

    def zero(self) -> ModelCost:
        return ModelCost(self.currency, self.version)

    def quote(self, provider: str, model: str, usage: TokenUsage) -> ModelCost:
        try:
            price = self._index[(provider, model)]
        except KeyError as error:
            raise PriceNotFoundError(
                f"no price for provider {provider!r} model {model!r}"
            ) from error
        if usage.cached_input_tokens > usage.input_tokens:
            raise PricingError("cached input tokens cannot exceed input tokens")
        uncached_tokens = usage.input_tokens - usage.cached_input_tokens
        return ModelCost(
            self.currency,
            self.version,
            Decimal(uncached_tokens) * price.input_per_million / _MILLION,
            Decimal(usage.output_tokens) * price.output_per_million / _MILLION,
            Decimal(usage.cached_input_tokens)
            * price.cached_input_per_million
            / _MILLION,
        )


class PricingResolver(Protocol):
    """Replaceable version lookup and quotation contract."""

    def table(self, version: str) -> PriceTable: ...

    def quote(
        self,
        version: str,
        provider: str,
        model: str,
        usage: TokenUsage,
    ) -> ModelCost: ...


class PricingCatalog:
    """Small in-process registry; applications may replace the protocol entirely."""

    def __init__(self, tables: tuple[PriceTable, ...] = ()) -> None:
        self._tables: dict[str, PriceTable] = {}
        for table in tables:
            self.register(table)

    def register(self, table: PriceTable) -> None:
        if table.version in self._tables:
            raise PricingError(f"price-table version {table.version!r} already exists")
        self._tables[table.version] = table

    def table(self, version: str) -> PriceTable:
        try:
            return self._tables[version]
        except KeyError as error:
            raise PricingError(f"price-table version {version!r} is unavailable") from error

    def quote(
        self,
        version: str,
        provider: str,
        model: str,
        usage: TokenUsage,
    ) -> ModelCost:
        return self.table(version).quote(provider, model, usage)
