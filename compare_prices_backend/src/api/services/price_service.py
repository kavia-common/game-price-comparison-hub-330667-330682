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

# --- Fallback Mock Data Imports ---
from src.api.adapters.mock_data import MOCK_GAME_CATALOG, SUPPORTED_STORES

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
    Main price comparison function (with robust canonical fallback).

    CONTRACT (documented, versioned, and enforced):

    Inputs:
        query (str): Raw user-provided game title (e.g., "GTA V")
        category (str): Filter - 'new', 'preowned', or 'all'
    Outputs:
        ComparePricesResponse with:
            - results: List[StoreResult], never None
            - new_stats, preowned_stats: PriceStats, fully computed if possible
            - total_results: int, length of results
            - original query echoed as .query
    Errors:
        - Logs and skips individual store failures, recovers as many live results as possible.
        - If all live store adapters yield zero results, checks for fallback:
            - If the normalized query matches a key in MOCK_GAME_CATALOG,
              use that mock data as synthetic StoreResults for the supported stores.
            - If the query is not recognized, returns contract-compliant empty response.
        - All pathways are logged with contextual messages (including fallback trigger).
    Invariants:
        - Query is normalized once (strip/lower, trimmed).
        - All StoreResult conditions are respected.
        - Fallback flows never break public API contract.
    Observability:
        - Start/end logs, fallback trigger log, failure logs with adequate context.

    This design maintains a single durable, testable, and search-friendly entrypoint,
    and ensures both real-time and test/demo usage are supported robustly.

    """
    adapters = get_all_store_adapters()
    all_results: List[StoreResult] = []

    # Query normalization step (single-control-point, reuse-protective)
    normalized_query = query.strip().lower()
    logger.info("PriceHuntFlow: START price comparison | original_query='%s' | normalized_query='%s' | category='%s'",
                query, normalized_query, category)

    # --- Canonical real scrape step ---
    tasks = [adapter.search(normalized_query, category) for adapter in adapters]
    try:
        store_results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        logger.error("PriceHuntFlow: ERROR during concurrent store queries: %s", str(exc))
        store_results = []

    # Collect results, handling any individual store failures gracefully
    for i, result in enumerate(store_results):
        if isinstance(result, Exception):
            logger.warning(
                "PriceHuntFlow: Store adapter '%s' failed: %s",
                adapters[i].store_name,
                str(result),
            )
            continue
        if isinstance(result, list):
            all_results.extend(result)

    # --- Fallback: If no actual store results, but query matches mock catalog, use mock data ---
    if not all_results and normalized_query in MOCK_GAME_CATALOG:
        logger.info("PriceHuntFlow: FALLBACK activated for query='%s' (mock data used)", normalized_query)
        mock_results: List[StoreResult] = []
        catalog = MOCK_GAME_CATALOG[normalized_query]
        for store in SUPPORTED_STORES:
            item = catalog.get(store)
            if item:
                # Respect category and create separate StoreResult for new/preowned
                if category in ("all", "new") and item.get("new_price") is not None:
                    mock_results.append(StoreResult(
                        store_name=store,
                        title=item.get("title", normalized_query),
                        price=item.get("new_price"),
                        original_price=item.get("original_price"),
                        discount_percent=None,
                        url=item.get("url"),
                        image_url=item.get("image_url"),
                        in_stock=item.get("in_stock", True),
                        condition="new"
                    ))
                if category in ("all", "preowned") and item.get("preowned_price") is not None:
                    mock_results.append(StoreResult(
                        store_name=store,
                        title=item.get("title", normalized_query) + " (Pre-Owned)",
                        price=item.get("preowned_price"),
                        original_price=item.get("original_price"),
                        discount_percent=None,
                        url=item.get("url"),
                        image_url=item.get("image_url"),
                        in_stock=item.get("in_stock", True),
                        condition="preowned"
                    ))
        all_results = mock_results

    # Separate results by condition for stats
    new_results = [r for r in all_results if r.condition == "new"]
    preowned_results = [r for r in all_results if r.condition == "preowned"]

    new_stats = compute_price_stats(new_results)
    preowned_stats = compute_price_stats(preowned_results)

    logger.info("PriceHuntFlow: END | results=%d | query='%s' | fallback=%s",
                len(all_results), query, "yes" if not all_results and normalized_query in MOCK_GAME_CATALOG else "no")

    return ComparePricesResponse(
        query=query,
        category=category,
        results=all_results,
        new_stats=new_stats,
        preowned_stats=preowned_stats,
        total_results=len(all_results),
    )
