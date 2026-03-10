"""
LLM-based extraction service for PriceHunt.

Uses the Ollama LLM service to extract structured game price data from raw
HTML content scraped from store pages. This provides an alternative extraction
path alongside the BeautifulSoup CSS-selector-based scrapers.

When OLLAMA_ENABLED is true and the Ollama service is reachable, the system
can use LLM extraction as a fallback when CSS-selector-based parsing yields
zero results (selector drift), or as the primary extraction method.

Contract:
    Input:  Raw HTML (str), store_name (str), query (str), category (str)
    Output: List[StoreResult] on success, empty list on failure
    Errors: Never raises; logs warnings and returns [] on any failure
    Side effects: HTTP call to Ollama service via ollama_client

Flow Name: LLMExtractionFlow
"""

import json
import logging
from typing import List, Optional

from src.api.config import get_settings
from src.api.models import StoreResult
from src.api.services.ollama_client import generate_text

logger = logging.getLogger(__name__)

# Extraction prompt template.
# The LLM is asked to return a JSON array of product objects from the HTML.
_EXTRACTION_PROMPT_TEMPLATE = """You are a precise data extraction assistant. Extract game product listings from the following HTML content from the store "{store_name}".

For each product found, extract:
- title: the game title
- price: the selling price in INR as a number (no currency symbols)
- original_price: the original/MRP price if shown (null if not available)
- url: the product page URL (use relative URL if absolute not available)
- image_url: the product image URL (null if not available)
- in_stock: true or false
- condition: "new" or "preowned" based on product labels

Return ONLY a valid JSON array of objects with these fields. No explanation, no markdown, just the JSON array.
If no products are found, return an empty array: []

Search query: "{query}"
Category filter: "{category}"

HTML content (truncated to first 8000 chars):
{html_content}

JSON array:"""


# PUBLIC_INTERFACE
async def extract_products_with_llm(
    html: str,
    store_name: str,
    store_base_url: str,
    query: str,
    category: str = "all",
) -> List[StoreResult]:
    """
    Extract game product listings from HTML using the Ollama LLM service.

    Sends the HTML content (truncated to 8000 chars to stay within context
    limits) to the LLM with a structured extraction prompt. Parses the JSON
    response into StoreResult objects.

    This function is designed to be called as a fallback when CSS-selector-based
    parsing fails due to HTML structure changes (selector drift).

    Args:
        html: Raw HTML content from the store page.
        store_name: Name of the store (e.g. "GamesTheShop").
        store_base_url: Base URL of the store for resolving relative URLs.
        query: The search query used.
        category: Category filter — "new", "preowned", or "all".

    Returns:
        List of StoreResult objects extracted from the HTML.
        Returns empty list if extraction fails or Ollama is unavailable.
    """
    settings = get_settings()

    if not settings.OLLAMA_ENABLED:
        logger.debug(
            "llm_extractor: OLLAMA_ENABLED=false, skipping LLM extraction for store=%s",
            store_name,
        )
        return []

    # Truncate HTML to avoid exceeding model context window
    html_truncated = html[:8000]

    prompt = _EXTRACTION_PROMPT_TEMPLATE.format(
        store_name=store_name,
        query=query,
        category=category,
        html_content=html_truncated,
    )

    logger.info(
        "llm_extractor: extract START | store=%s | query='%s' | html_len=%d",
        store_name, query, len(html),
    )

    response_text = await generate_text(prompt)

    if response_text is None:
        logger.warning(
            "llm_extractor: extract FAILED — Ollama returned None for store=%s",
            store_name,
        )
        return []

    # Parse the JSON response from the LLM
    return _parse_llm_response(response_text, store_name, store_base_url, category)


def _parse_llm_response(
    response_text: str,
    store_name: str,
    store_base_url: str,
    category: str,
) -> List[StoreResult]:
    """
    Parse the raw LLM text response into a list of StoreResult objects.

    Handles common LLM output quirks such as markdown fences around JSON.

    Args:
        response_text: Raw text from the LLM.
        store_name: Store name for the StoreResult objects.
        store_base_url: Base URL for resolving relative product URLs.
        category: Category filter to apply.

    Returns:
        List of StoreResult objects, or empty list on parse failure.
    """
    # Strip markdown code fences if the LLM wrapped the JSON
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (with optional language tag)
        first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
        cleaned = cleaned[first_newline + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        products = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning(
            "llm_extractor: JSON parse error for store=%s | error=%s | raw=%s",
            store_name, str(exc), response_text[:500],
        )
        return []

    if not isinstance(products, list):
        logger.warning(
            "llm_extractor: Expected JSON array, got %s for store=%s",
            type(products).__name__, store_name,
        )
        return []

    results: List[StoreResult] = []

    for item in products:
        if not isinstance(item, dict):
            continue

        try:
            title = str(item.get("title", "")).strip()
            if not title:
                continue

            price = _safe_float(item.get("price"))
            original_price = _safe_float(item.get("original_price"))
            url = str(item.get("url", "")).strip()
            image_url = item.get("image_url")
            in_stock = bool(item.get("in_stock", True))
            condition = str(item.get("condition", "new")).lower()

            # Resolve relative URLs
            if url and not url.startswith("http"):
                url = store_base_url.rstrip("/") + "/" + url.lstrip("/")
            if image_url and not str(image_url).startswith("http"):
                image_url = store_base_url.rstrip("/") + "/" + str(image_url).lstrip("/")

            # Validate condition
            if condition not in ("new", "preowned"):
                condition = "new"

            # Apply category filter
            if category != "all" and condition != category:
                continue

            # Compute discount
            discount_percent = None
            if original_price and price and original_price > price:
                discount_percent = round((1 - price / original_price) * 100, 1)

            results.append(StoreResult(
                store_name=store_name,
                title=title,
                price=price,
                original_price=original_price if original_price and price and original_price > price else None,
                discount_percent=discount_percent,
                url=url,
                image_url=str(image_url) if image_url else None,
                in_stock=in_stock,
                condition=condition,
            ))

        except Exception as exc:
            logger.warning(
                "llm_extractor: Error building StoreResult for store=%s item=%s | error=%s",
                store_name, str(item)[:200], str(exc),
            )

    logger.info(
        "llm_extractor: extract DONE | store=%s | products_extracted=%d",
        store_name, len(results),
    )
    return results


def _safe_float(value) -> Optional[float]:
    """
    Safely convert a value to float, returning None on failure.

    Handles strings with currency symbols, commas, and None values.

    Args:
        value: Any value that might represent a number.

    Returns:
        Float value or None if conversion is not possible.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove common currency formatting
        import re
        cleaned = re.sub(r'[₹$,Rs.INR\s]', '', value, flags=re.IGNORECASE)
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None
