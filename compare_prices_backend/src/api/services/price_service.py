"""
Price comparison service module.
Handles orchestration of store adapter queries and statistics computation.
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
    Main price comparison function.
    
    Queries all 8 store adapters concurrently, collects results,
    computes statistics for both new and preowned categories,
    and returns a structured response.
    
    Args:
        query: Game title to search for
        category: Filter - 'new', 'preowned', or 'all'
        
    Returns:
        ComparePricesResponse with results and statistics
    """
    adapters = get_all_store_adapters()
    all_results: List[StoreResult] = []

    # Query all stores concurrently for performance
    tasks = [adapter.search(query, category) for adapter in adapters]

    try:
        store_results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        logger.error("Error during concurrent store queries: %s", str(exc))
        store_results = []

    # Collect results, handling any individual store failures gracefully
    for i, result in enumerate(store_results):
        if isinstance(result, Exception):
            logger.warning(
                "Store adapter '%s' failed: %s",
                adapters[i].store_name,
                str(result),
            )
            continue
        if isinstance(result, list):
            all_results.extend(result)

    # Separate results by condition for stats
    new_results = [r for r in all_results if r.condition == "new"]
    preowned_results = [r for r in all_results if r.condition == "preowned"]

    # Compute statistics per category
    new_stats = compute_price_stats(new_results)
    preowned_stats = compute_price_stats(preowned_results)

    return ComparePricesResponse(
        query=query,
        category=category,
        results=all_results,
        new_stats=new_stats,
        preowned_stats=preowned_stats,
        total_results=len(all_results),
    )
