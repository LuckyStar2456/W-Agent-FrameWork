from decimal import Decimal

import pytest

from w_agent import (
    ModelPrice,
    PriceNotFoundError,
    PriceTable,
    PricingCatalog,
    PricingError,
    TokenUsage,
)


def test_versioned_price_table_quotes_cached_and_uncached_tokens_exactly():
    table = PriceTable(
        "2026-09-18",
        "usd",
        (
            ModelPrice(
                "provider",
                "model",
                input_per_million="2",
                output_per_million="4",
                cached_input_per_million="1",
            ),
        ),
    )

    cost = table.quote("provider", "model", TokenUsage(1000, 200, 400))

    assert cost.currency == "USD"
    assert cost.price_table_version == "2026-09-18"
    assert cost.input_cost == Decimal("0.0012")
    assert cost.cached_input_cost == Decimal("0.0004")
    assert cost.output_cost == Decimal("0.0008")
    assert cost.total == Decimal("0.0024")


def test_pricing_catalog_requires_explicit_unique_versions_and_model_rates():
    table = PriceTable(
        "v1",
        "USD",
        (ModelPrice("provider", "model", "1", "2"),),
    )
    catalog = PricingCatalog((table,))

    assert catalog.quote("v1", "provider", "model", TokenUsage(1, 1)).total > 0
    with pytest.raises(PriceNotFoundError):
        catalog.quote("v1", "provider", "other", TokenUsage(1, 1))
    with pytest.raises(PricingError, match="already exists"):
        catalog.register(table)


def test_price_table_rejects_invalid_cached_usage_and_duplicate_rates():
    with pytest.raises(PricingError, match="duplicate"):
        PriceTable(
            "v1",
            "USD",
            (
                ModelPrice("provider", "model", "1", "2"),
                ModelPrice("provider", "model", "3", "4"),
            ),
        )
    table = PriceTable(
        "v1",
        "USD",
        (ModelPrice("provider", "model", "1", "2"),),
    )
    with pytest.raises(PricingError, match="cannot exceed"):
        table.quote("provider", "model", TokenUsage(1, 0, 2))
