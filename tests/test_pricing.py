from decimal import Decimal

import pytest

from w_agent import (
    CostBudget,
    CostEstimateRequest,
    CostEstimateRoute,
    ModelPrice,
    PriceNotFoundError,
    PriceTable,
    PricingCatalog,
    PricingCostEstimator,
    PricingError,
    TokenUsage,
)


def test_cost_budget_preflight_options_are_explicit_and_normalized():
    budget = CostBudget(
        "1.25",
        "v1",
        estimate_before_call=True,
        require_estimate=True,
        soft_limit_ratio="0.8",
    )

    assert budget.max_cost == Decimal("1.25")
    assert budget.soft_limit_ratio == Decimal("0.8")
    with pytest.raises(ValueError, match="preflight enabled"):
        CostBudget("1", "v1", require_estimate=True)
    with pytest.raises(ValueError, match="between 0 and 1"):
        CostBudget("1", "v1", soft_limit_ratio="1.1")


@pytest.mark.asyncio
async def test_pricing_cost_estimator_covers_bounded_retry_and_failover():
    catalog = PricingCatalog(
        (
            PriceTable(
                "v1",
                "USD",
                (
                    ModelPrice("primary", "chat", "1000000", "2000000"),
                    ModelPrice("fallback", "chat", "3000000", "4000000"),
                ),
            ),
        )
    )

    estimate = await PricingCostEstimator(catalog).estimate(
        CostEstimateRequest(
            (
                CostEstimateRoute("primary", "chat", attempts=2),
                CostEstimateRoute("fallback", "chat", attempts=1),
            ),
            estimated_input_tokens=10,
            max_output_tokens=5,
            price_table_version="v1",
            token_estimator="exact:test",
            input_exact=True,
        )
    )

    assert estimate.primary_attempt.total == Decimal("20")
    assert estimate.replay_envelope.total == Decimal("90")
    assert estimate.route_count == 2
    assert estimate.attempt_count == 3
    assert estimate.conservative is True


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
