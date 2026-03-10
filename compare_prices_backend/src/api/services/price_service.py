"""
Price comparison service module.
Handles orchestration of store adapter queries and statistics computation.

ComparePricesFlow is the single canonical entrypoint for all price-comparison requests.

Scraping strategy:
  1. Always attempt live Playwright-based scraping via store adapters.
  2. If OLLAMA_ENABLED=true AND step 1 returns zero priced results, attempt
     LLM-based extraction via the Ollama service as a smart fallback.
  3. If USE_MOCK_FALLBACK=true (env var) AND all scrapers (and LLM extraction)
     return zero real (priced) results, fall back to the mock catalog so the UI
     remains functional in sandboxed environments.
  4. DEBUG_SCRAPER_ERRORS=true surfaces per-store failure reasons directly in the
     API response as synthetic StoreResult entries with [DEBUG: …] titles.
     These entries have price=None and are filtered out of price statistics.

Flow Name: ComparePricesFlow
Entrypoint: async compare_prices(query, category)
Callers: Only the FastAPI /compare-prices route in main.py.
"""

import asyncio
import logging
from typing import List

from src.api.config import get_settings
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

    Only results with a non-None, positive price contribute to statistics.
    Debug entries (price=None) are silently ignored.

    Args:
        results: List of StoreResult objects to analyze.

    Returns:
        PriceStats object with computed statistics; all fields None/0 when no
        priced results are present.
    """
    # Filter results that have valid prices; debug entries have price=None
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


def _has_real_results(results: List[StoreResult]) -> bool:
    """
    Return True if *results* contains at least one entry with a real price.

    Debug/placeholder entries (price=None) produced when DEBUG_SCRAPER_ERRORS
    is enabled do not count as real results.

    Args:
        results: List of StoreResult objects from all scraper adapters.

    Returns:
        True when any result has price > 0, False otherwise.
    """
    return any(r.price is not None and r.price > 0 for r in results)


# PUBLIC_INTERFACE
async def compare_prices(query: str, category: str = "all") -> ComparePricesResponse:
    """
    Main price comparison flow entrypoint (ComparePricesFlow).

    Runs live Playwright-based scraping against all 8 supported Indian gaming stores
    concurrently.  When USE_MOCK_FALLBACK=true and all stores return zero priced
    results the function transparently falls back to the bundled mock catalog so the
    API always returns useful data in sandboxed environments.

    Flow Name: ComparePricesFlow

    CONTRACT:
    Inputs:
        query (str)    - Game title (arbitrary non-empty string).  Normalised
                         (lower-cased, stripped) before being passed to adapters.
        category (str) - "new", "preowned", or "all".  Validated at the HTTP boundary
                         in main.py before this function is called.
    Outputs:
        ComparePricesResponse — always a well-formed model, even on total failure.
    Errors:
        - Individual store failures are caught, logged, and skipped.
        - A complete gather failure logs an error and returns empty results.
        - Never raises; the caller (FastAPI route) wraps this in its own try/except.
    Side effects:
        - Launches Playwright Chromium browser processes (one per store, concurrently).
        - Logs: flow start, per-store failures, fallback activation, flow end.

    Invariants:
        - Mock fallback is only triggered when USE_MOCK_FALLBACK=true AND no priced
          results were obtained from live scraping.
        - Debug entries (price=None) from DEBUG_SCRAPER_ERRORS are kept in the results
          list for observability but are excluded from PriceStats calculations.
        - Output is contract-compliant regardless of upstream failures.

    Observability:
        - Logs flow start/end with result counts.
        - Logs each store failure with store name and error.
        - Logs mock fallback activation (with reason).

    Args:
        query: Game title to search for.
        category: Condition filter — "new", "preowned", or "all".

    Returns:
        ComparePricesResponse with aggregated results and price statistics.
    """
    settings = get_settings()
    use_mock_fallback: bool = bool(getattr(settings, "USE_MOCK_FALLBACK", False))

    adapters = get_all_store_adapters()
    all_results: List[StoreResult] = []

    # --- Query normalisation (single control-point) --------------------------
    normalized_query = query.strip().lower()
    logger.info(
        "ComparePricesFlow: START | original_query='%s' | "
        "normalized_query='%s' | category='%s' | mock_fallback=%s",
        query, normalized_query, category, use_mock_fallback,
    )

    # --- Live scrape step — all stores in parallel ---------------------------
    tasks = [adapter.search(normalized_query, category) for adapter in adapters]
    try:
        store_results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        logger.error(
            "ComparePricesFlow: ERROR during concurrent store queries: %s", str(exc)
        )
        store_results = []

    for i, result in enumerate(store_results):
        if isinstance(result, Exception):
            logger.warning(
                "ComparePricesFlow: Store adapter '%s' raised exception: %s",
                adapters[i].store_name,
                str(result),
            )
            continue
        if isinstance(result, list):
            all_results.extend(result)

    # --- LLM extraction fallback (Ollama) ------------------------------------
    # When OLLAMA_ENABLED=true and standard CSS-selector scraping returned zero
    # priced results, attempt LLM-based extraction using the Ollama service.
    # This handles selector drift without needing code changes.
    ollama_enabled: bool = bool(getattr(settings, "OLLAMA_ENABLED", False))
    if ollama_enabled and not _has_real_results(all_results):
        logger.info(
            "ComparePricesFlow: OLLAMA_EXTRACTION attempting — standard scraping "
            "returned zero priced results for query='%s'",
            query,
        )
        try:
            from src.api.services.llm_extractor import extract_products_with_llm  # noqa: PLC0415
            from src.api.adapters.playwright_client import fetch_with_playwright  # noqa: PLC0415

            # Re-scrape a representative store page and feed HTML to LLM
            # Use the first adapter's search URL as a target
            if adapters:
                sample_adapter = adapters[0]
                search_url = getattr(sample_adapter, "search_template", "").format(
                    query=normalized_query.replace(" ", "+")
                )
                if search_url:
                    html = await fetch_with_playwright(
                        search_url,
                        store_name=sample_adapter.store_name,
                    )
                    if html:
                        llm_results = await extract_products_with_llm(
                            html=html,
                            store_name=sample_adapter.store_name,
                            store_base_url=getattr(sample_adapter, "base_url", ""),
                            query=normalized_query,
                            category=category,
                        )
                        if llm_results:
                            all_results = llm_results + [
                                r for r in all_results if r.price is None
                            ]
                            logger.info(
                                "ComparePricesFlow: OLLAMA_EXTRACTION returned %d results "
                                "for query='%s'",
                                len(llm_results), query,
                            )
        except Exception as exc:
            logger.warning(
                "ComparePricesFlow: OLLAMA_EXTRACTION failed for query='%s': %s",
                query, str(exc),
            )

    # --- Mock fallback -------------------------------------------------------
    # Activate when: flag is set AND no live results with a real price came back.
    # This keeps the UI functional in sandboxed / CI environments where external
    # websites are unreachable.
    if use_mock_fallback and not _has_real_results(all_results):
        logger.warning(
            "ComparePricesFlow: MOCK_FALLBACK activated — all stores returned zero "
            "priced results for query='%s'. Serving mock catalog data.",
            query,
        )
        # Import locally to avoid circular imports at module load time.
        from src.api.adapters.mock_data import mock_search  # noqa: PLC0415
        mock_results = mock_search(normalized_query, category)
        if mock_results:
            # Prepend mock results before any debug entries so real (mock) prices
            # appear first in the response.
            all_results = mock_results + [
                r for r in all_results if r.price is None  # keep debug entries
            ]
            logger.info(
                "ComparePricesFlow: MOCK_FALLBACK returned %d results for query='%s'",
                len(mock_results), query,
            )
        else:
            logger.warning(
                "ComparePricesFlow: MOCK_FALLBACK found no catalog match for query='%s'",
                query,
            )

    # --- Compute statistics (excludes debug/placeholder entries) -------------
    new_results = [r for r in all_results if r.condition == "new"]
    preowned_results = [r for r in all_results if r.condition == "preowned"]

    new_stats = compute_price_stats(new_results)
    preowned_stats = compute_price_stats(preowned_results)

    logger.info(
        "ComparePricesFlow: END | total_results=%d (priced=%d) | query='%s'",
        len(all_results),
        sum(1 for r in all_results if r.price is not None and r.price > 0),
        query,
    )

    return ComparePricesResponse(
        query=query,
        category=category,
        results=all_results,
        new_stats=new_stats,
        preowned_stats=preowned_stats,
        total_results=len(all_results),
    )
