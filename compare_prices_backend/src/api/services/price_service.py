"""
Price comparison service module.
Handles orchestration of store adapter queries and statistics computation.
Enforces Playwright-only, real live scraping. No mock or fallback logic remains.
"""

import asyncio
import logging
from typing import List

from src.api.models import (
    StoreResult,
    PriceStats,
    ComparePricesResponse,
)
from src.api.adapters.store_adapter import get_all_store_adapters

logger = logging.getLogger(__name__)


# PUBLIC_INTERFACE
def compute_price_stats(results: List[StoreResult]) -> PriceStats:
    """
    Compute aggregated price statistics from a list of store results.
    
    Calculates min, max, average prices and identifies the best deal store
    from the provided results list.
    
    Args:
        results: List of StoreResult objects to analyze
        
    Returns:
        PriceStats object with computed statistics
    """
    # Filter results that have valid prices
    priced_results = [r for r in results if r.price is not None and r.price > 0]

    if not priced_results:
        return PriceStats(
            lowest_price=None,
            highest_price=None,
            average_price=None,
            store_count=0,
            best_deal_store=None,
        )

    prices = [r.price for r in priced_results]
    lowest = min(prices)
    highest = max(prices)
    average = round(sum(prices) / len(prices), 2)

    # Find the store with the lowest price
    best_deal = min(priced_results, key=lambda r: r.price)

    return PriceStats(
        lowest_price=lowest,
        highest_price=highest,
        average_price=average,
        store_count=len(priced_results),
        best_deal_store=best_deal.store_name,
    )


# PUBLIC_INTERFACE
async def compare_prices(query: str, category: str = "all") -> ComparePricesResponse:
    """
    Main price comparison flow entrypoint.
    Enforces live Playwright-based scraping only (no mock or test data, no fallback).

    Flow Name: ComparePricesFlow

    Entrypoint: async compare_prices(query: str, category: str = "all")
    Callers: Only called from FastAPI /compare-prices endpoint in main.py.

    CONTRACT:
    Inputs:
        query (str): Game title (arbitrary, non-empty string)
        category (str): "new", "preowned", or "all" (validated at boundary)
    Outputs:
        ComparePricesResponse (see models.py for field invariants)
    Errors:
        - Skips and logs individual store failures and continues.
        - On total system failure, returns empty results but with fully-formed response model.
    Side effects:
        - Logs flow start, each store's outcome, and completion (with diagnostics).

    Invariants:
        - All results are from live Playwright-powered scrapes.
        - No fallback to mock or "test" data is ever performed.
        - Contract-compliant output regardless of failures upstream.

    Observability:
        - Logs: flow start, each store failure, summary of completion.

    Debugging: In case of all-store failures, inspect logs for Playwright/service errors and review selectors,
    as no test or fallback mode is available.

    """
    adapters = get_all_store_adapters()
    all_results: List[StoreResult] = []

    # Query normalization step (single-control-point, reuse-protective)
    normalized_query = query.strip().lower()
    logger.info("ComparePricesFlow: START price comparison | original_query='%s' | normalized_query='%s' | category='%s'",
                query, normalized_query, category)

    # --- Canonical real scrape step, no fallback paths ---
    tasks = [adapter.search(normalized_query, category) for adapter in adapters]
    try:
        store_results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        logger.error("ComparePricesFlow: ERROR during concurrent store queries: %s", str(exc))
        store_results = []

    for i, result in enumerate(store_results):
        if isinstance(result, Exception):
            logger.warning(
                "ComparePricesFlow: Store adapter '%s' failed: %s",
                adapters[i].store_name,
                str(result),
            )
            continue
        if isinstance(result, list):
            all_results.extend(result)

    # Separate results by condition for stats
    new_results = [r for r in all_results if r.condition == "new"]
    preowned_results = [r for r in all_results if r.condition == "preowned"]

    new_stats = compute_price_stats(new_results)
    preowned_stats = compute_price_stats(preowned_results)

    logger.info("ComparePricesFlow: END | results=%d | query='%s'",
                len(all_results), query)

    return ComparePricesResponse(
        query=query,
        category=category,
        results=all_results,
        new_stats=new_stats,
        preowned_stats=preowned_stats,
        total_results=len(all_results),
    )
