"""
Store scrapers implementation for all 8 Indian game stores, registry-dispatch pattern.

MAINTAINER NOTE (2024-06): Store DOM/HTML structures may change at any time.
If real-time scraping yields zero results, always check:
- The product selector(s) for each store may be out of date.
- Use browser "Inspect Element" to confirm the current product-list container and details.
- Add/update selectors as needed.
- Always log a snippet of raw HTML and the URL in zero-result scrapes for easy debugging.

Each store's scraper is a class inheriting from BaseStoreAdapter. All parsing
uses Playwright browser-based rendering for robust scraping.

Contract:
  Input: query (str), category (str) as received by /compare-prices
  Output: List[StoreResult] with store, title, price, url, image, in_stock, and condition

Error and timeout handling: All scrapers are robust, log warnings on failure, and return [].

DEBUG_SCRAPER_ERRORS:
  When the DEBUG_SCRAPER_ERRORS env var is set to "true", every scraper will append
  a synthetic StoreResult with a [DEBUG: …] title to the response whenever:
    - fetch_with_playwright returns None (Playwright failed / no network)
    - The HTML parser finds no matching products (selector mismatch)
  This makes scraping failures visible directly in the /compare-prices API response
  without needing to inspect server logs.

  IMPORTANT: DEBUG_SCRAPER_ERRORS is read FRESH from settings on every search() call
  (via _is_debug_mode() helper) so that the flag respects the .env value at runtime,
  not just at import time.

To add a new scraper, subclass BaseStoreAdapter and register it in STORE_SCRAPER_REGISTRY.

All real scraping logic is here, adapters/store_adapter.py is just orchestration.
"""

import logging
from typing import List, Optional
from bs4 import BeautifulSoup

from src.api.models import StoreResult
from src.api.adapters.base_adapter import BaseStoreAdapter
from src.api.adapters.playwright_client import fetch_with_playwright
from src.api.adapters.parse_utils import (
    extract_price,
    extract_discount_percent,
    compute_price_from_mrp_and_discount,
)
from src.api.config import get_settings

logger = logging.getLogger(__name__)

# ------------ Store Scraper Registry --------------

STORE_SCRAPER_REGISTRY = {}


def register_scraper(store_name):
    """Decorator to register a scraper class for a given store name."""
    def decorator(cls):
        STORE_SCRAPER_REGISTRY[store_name] = cls
        return cls
    return decorator


def _is_debug_mode() -> bool:
    """
    Read the DEBUG_SCRAPER_ERRORS flag fresh from settings on each invocation.

    Reading fresh (rather than caching at module load) ensures the flag
    always reflects the .env value even when env vars are late-loaded or
    changed between requests in test scenarios.

    Returns:
        True if DEBUG_SCRAPER_ERRORS is enabled, False otherwise.
    """
    return bool(getattr(get_settings(), "DEBUG_SCRAPER_ERRORS", False))


def _make_debug_result(store_name: str, reason: str, url: str) -> StoreResult:
    """
    Build a synthetic StoreResult that surfaces a scraping failure in the API response.

    This result has a [DEBUG: …] title so consumers can identify it as a diagnostic
    entry rather than a real price result.  price=None, in_stock=False.

    Args:
        store_name: Name of the store whose scraper failed
        reason: Human-readable description of the failure (e.g. "Playwright returned None",
                "No products found; selector: div.product-card")
        url: The URL that was attempted

    Returns:
        StoreResult instance marked as debug / not-in-stock with no price.
    """
    return StoreResult(
        store_name=store_name,
        title=f"[DEBUG: {reason}]",
        price=None,
        original_price=None,
        discount_percent=None,
        url=url,
        image_url=None,
        in_stock=False,
        condition="new",
    )


# ----------- GamesTheShop Scraper --------------

@register_scraper("GamesTheShop")
class GamesTheShopAdapter(BaseStoreAdapter):
    """Playwright-based scraper for GamesTheShop (gamestheshop.com)."""

    store_name = "GamesTheShop"
    base_url = "https://www.gamestheshop.com"
    search_template = base_url + "/search/?text={query}"

    async def search(self, query: str, category: str = "all") -> List[StoreResult]:
        """
        Scrape GamesTheShop for the game query using Playwright-based browser.

        Args:
            query: Normalised (lower-cased, stripped) game title.
            category: Condition filter — "new", "preowned", or "all".

        Returns:
            List of StoreResult objects; may contain debug entries when
            DEBUG_SCRAPER_ERRORS is enabled.
        """
        search_url = self.search_template.format(query=query.replace(" ", "+"))
        html = await fetch_with_playwright(search_url, store_name=self.store_name)

        if not html:
            logger.warning(
                "GamesTheShopAdapter: No HTML returned for store=%s url=%s",
                self.store_name, search_url,
            )
            if _is_debug_mode():
                return [_make_debug_result(
                    self.store_name,
                    "Playwright returned None (network/browser failure)",
                    search_url,
                )]
            return []

        soup = BeautifulSoup(html, "lxml")
        results: List[StoreResult] = []

        # Selector: ul.product-list > li
        # NOTE: If store HTML has changed, update this selector.
        product_items = soup.select("ul.product-list > li")

        if not product_items:
            logger.warning(
                "GamesTheShopAdapter: No products found for query='%s' url=%s; "
                "HTML length=%d. HTML excerpt:\n%s",
                query, search_url, len(html), html[:1000],
            )
            if _is_debug_mode():
                results.append(_make_debug_result(
                    self.store_name,
                    "No products found; selector: ul.product-list > li",
                    search_url,
                ))

        for prod_li in product_items:
            try:
                title = prod_li.select_one(".product-title").get_text(strip=True)
                url = self.base_url + prod_li.select_one("a")["href"]
                image_url = prod_li.select_one(".product-img img")["src"]
                price_str = prod_li.select_one(".product-price strong").get_text(strip=True)
                orig_price_str = prod_li.select_one(".product-price del")
                orig_price = (
                    extract_price(orig_price_str.get_text(strip=True))
                    if orig_price_str else None
                )
                price = extract_price(price_str)
                in_stock_tag = prod_li.select_one(".actions input[type=submit]")
                in_stock = bool(
                    in_stock_tag and "add to cart" in in_stock_tag.get("value", "").lower()
                )
                preowned_tag = prod_li.select_one(".label-preowned")
                is_preowned = preowned_tag is not None

                if category in ("all", "new") and not is_preowned:
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title,
                        price=price,
                        original_price=orig_price if orig_price and orig_price > price else None,
                        discount_percent=(
                            round((1 - price / orig_price) * 100, 1)
                            if orig_price and orig_price > price else None
                        ),
                        url=url,
                        image_url=image_url,
                        in_stock=in_stock,
                        condition="new",
                    ))
                if category in ("all", "preowned") and is_preowned:
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title + " (Pre-Owned)",
                        price=price,
                        original_price=orig_price,
                        discount_percent=None,
                        url=url,
                        image_url=image_url,
                        in_stock=in_stock,
                        condition="preowned",
                    ))
            except Exception as ex:
                logger.warning("GamesTheShop parse error: %s", ex)

        return results


# ----------- GameNation Scraper --------------

@register_scraper("GameNation")
class GameNationAdapter(BaseStoreAdapter):
    """Playwright-based scraper for GameNation (gamenation.in)."""

    store_name = "GameNation"
    base_url = "https://www.gamenation.in"
    search_template = base_url + "/search?type=product&q={query}"

    async def search(self, query: str, category: str = "all") -> List[StoreResult]:
        """
        Scrape GameNation for the game query.

        Args:
            query: Normalised game title.
            category: Condition filter.

        Returns:
            List of StoreResult objects; may contain debug entries.
        """
        search_url = self.search_template.format(query=query.replace(" ", "+"))
        html = await fetch_with_playwright(search_url, store_name=self.store_name)

        if not html:
            logger.warning(
                "GameNationAdapter: No HTML returned for store=%s url=%s",
                self.store_name, search_url,
            )
            if _is_debug_mode():
                return [_make_debug_result(
                    self.store_name,
                    "Playwright returned None (network/browser failure)",
                    search_url,
                )]
            return []

        soup = BeautifulSoup(html, "lxml")
        results: List[StoreResult] = []

        # Selector: div.product-card
        cards = soup.select("div.product-card")

        if not cards:
            logger.warning(
                "GameNationAdapter: No products found for query='%s' url=%s",
                query, search_url,
            )
            if _is_debug_mode():
                results.append(_make_debug_result(
                    self.store_name,
                    "No products found; selector: div.product-card",
                    search_url,
                ))

        for card in cards:
            try:
                title = card.select_one(".product-title").get_text(strip=True)
                url = self.base_url + card.select_one("a")["href"]
                image_url = card.select_one(".product-img img")["src"]
                price_str = card.select_one(".product-price").get_text(strip=True)
                orig_price_tag = card.select_one(".product-price s")
                orig_price = (
                    extract_price(orig_price_tag.get_text(strip=True))
                    if orig_price_tag else None
                )
                price = extract_price(price_str)

                if card.select_one(".preowned-label"):
                    if category in ("all", "preowned"):
                        results.append(StoreResult(
                            store_name=self.store_name,
                            title=title + " (Pre-Owned)",
                            price=price,
                            original_price=orig_price,
                            discount_percent=None,
                            url=url,
                            image_url=image_url,
                            in_stock=True,
                            condition="preowned",
                        ))
                else:
                    if category in ("all", "new"):
                        results.append(StoreResult(
                            store_name=self.store_name,
                            title=title,
                            price=price,
                            original_price=(
                                orig_price if orig_price and orig_price > price else None
                            ),
                            discount_percent=(
                                round((1 - price / orig_price) * 100, 1)
                                if orig_price and orig_price > price else None
                            ),
                            url=url,
                            image_url=image_url,
                            in_stock=True,
                            condition="new",
                        ))
            except Exception as ex:
                logger.warning("GameNation parse error: %s", ex)

        return results


# ----------- Amazon.in Scraper --------------

@register_scraper("Amazon.in")
class AmazonIndiaAdapter(BaseStoreAdapter):
    """Playwright-based scraper for Amazon India (amazon.in)."""

    store_name = "Amazon.in"
    base_url = "https://www.amazon.in"
    search_template = base_url + "/s?k={query}&i=videogames"

    async def search(self, query: str, category: str = "all") -> List[StoreResult]:
        """
        Scrape Amazon India for the game query.

        Args:
            query: Normalised game title.
            category: Condition filter.

        Returns:
            List of StoreResult objects; may contain debug entries.
        """
        search_url = self.search_template.format(query=query.replace(" ", "+"))
        html = await fetch_with_playwright(search_url, store_name=self.store_name)

        if not html:
            logger.warning(
                "AmazonIndiaAdapter: No HTML returned for store=%s url=%s",
                self.store_name, search_url,
            )
            if _is_debug_mode():
                return [_make_debug_result(
                    self.store_name,
                    "Playwright returned None (network/browser failure)",
                    search_url,
                )]
            return []

        soup = BeautifulSoup(html, "lxml")
        results: List[StoreResult] = []

        # Selector: .s-result-item[data-component-type='s-search-result']
        # NOTE: If Amazon search DOM changes, update this selector.
        items = soup.select(".s-result-item[data-component-type='s-search-result']")

        if not items:
            logger.warning(
                "AmazonIndiaAdapter: No products parsed for query='%s' url=%s; "
                "HTML length=%d. HTML snippet:\n%s",
                query, search_url, len(html), html[:1000],
            )
            if _is_debug_mode():
                results.append(_make_debug_result(
                    self.store_name,
                    "No products found; selector: .s-result-item[data-component-type='s-search-result']",
                    search_url,
                ))

        for item in items:
            try:
                link_tag = item.select_one("h2 a")
                url = self.base_url + link_tag.get("href")
                title = link_tag.get_text(strip=True)

                image_url: Optional[str] = None
                img_tag = item.select_one("img.s-image")
                if img_tag:
                    image_url = img_tag.get("src") or img_tag.get("data-image")

                price_whole = item.select_one("span.a-price-whole")
                price_frac = item.select_one("span.a-price-fraction")
                price_str = ""
                if price_whole:
                    price_str += price_whole.text.strip()
                if price_frac:
                    price_str += "." + price_frac.text.strip()

                orig_price_tag = item.select_one(
                    "span.a-price.a-text-price span.a-offscreen"
                )
                orig_price = extract_price(orig_price_tag.text) if orig_price_tag else None
                discount_tag = item.select_one(
                    "span.saving-badge, span.a-letter-space+span"
                )
                discount_percent = (
                    extract_discount_percent(discount_tag.text) if discount_tag else None
                )

                # Prefer extracted price; fallback to MRP minus discount
                price = extract_price(price_str) or compute_price_from_mrp_and_discount(
                    orig_price, discount_percent
                )
                if price is None:
                    continue

                # Amazon does not show preowned; always "new"
                if category in ("all", "new"):
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title,
                        price=price,
                        original_price=(
                            orig_price if orig_price and orig_price > price else None
                        ),
                        discount_percent=(
                            discount_percent or (
                                round((1 - price / orig_price) * 100, 1)
                                if orig_price and orig_price > price else None
                            )
                        ),
                        url=url,
                        image_url=image_url,
                        in_stock=True,
                        condition="new",
                    ))
            except Exception as ex:
                logger.warning("AmazonIndia parse error: %s", ex)

        return results


# ----------- Flipkart Scraper --------------

@register_scraper("Flipkart")
class FlipkartAdapter(BaseStoreAdapter):
    """Playwright-based scraper for Flipkart (flipkart.com)."""

    store_name = "Flipkart"
    base_url = "https://www.flipkart.com"
    search_template = base_url + "/search?q={query}"

    async def search(self, query: str, category: str = "all") -> List[StoreResult]:
        """
        Scrape Flipkart for the game query.

        Args:
            query: Normalised game title.
            category: Condition filter.

        Returns:
            List of StoreResult objects; may contain debug entries.
        """
        search_url = self.search_template.format(query=query.replace(" ", "+"))
        html = await fetch_with_playwright(search_url, store_name=self.store_name)

        if not html:
            logger.warning(
                "FlipkartAdapter: No HTML returned for store=%s url=%s",
                self.store_name, search_url,
            )
            if _is_debug_mode():
                return [_make_debug_result(
                    self.store_name,
                    "Playwright returned None (network/browser failure)",
                    search_url,
                )]
            return []

        soup = BeautifulSoup(html, "lxml")
        results: List[StoreResult] = []
        found_any = False

        for row in soup.select("div._1AtVbE"):
            try:
                anchor = row.select_one("a.s1Q9rs, a.IRpwTa, a._2rpwqI, a._2UzuFa")
                if anchor is None:
                    continue
                found_any = True
                title = anchor.text.strip()
                url = self.base_url + anchor["href"]
                image_url: Optional[str] = None
                img_tag = row.select_one("img._396cs4._3exPp9")
                if img_tag:
                    image_url = img_tag.get("src")
                price_tag = row.select_one("div._30jeq3")
                orig_tag = row.select_one("div._3I9_wc")
                price = extract_price(price_tag.text) if price_tag else None
                orig_price = extract_price(orig_tag.text) if orig_tag else None

                # Flipkart does not list preowned games; always "new"
                if category in ("all", "new") and price:
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title,
                        price=price,
                        original_price=(
                            orig_price if orig_price and orig_price > price else None
                        ),
                        discount_percent=(
                            round((1 - price / orig_price) * 100, 1)
                            if orig_price and orig_price > price else None
                        ),
                        url=url,
                        image_url=image_url,
                        in_stock=True,
                        condition="new",
                    ))
            except Exception as ex:
                logger.warning("Flipkart parse error: %s", ex)

        if not found_any:
            logger.warning(
                "FlipkartAdapter: No products found for query='%s' url=%s",
                query, search_url,
            )
            if _is_debug_mode():
                results.append(_make_debug_result(
                    self.store_name,
                    "No products found; selector: div._1AtVbE a.s1Q9rs|IRpwTa",
                    search_url,
                ))

        return results


# ----------- Mcube Games Scraper --------------

@register_scraper("Mcube Games")
class McubeGamesAdapter(BaseStoreAdapter):
    """Playwright-based scraper for Mcube Games (mcubegames.com)."""

    store_name = "Mcube Games"
    base_url = "https://mcubegames.com"
    search_template = base_url + "/search?q={query}"

    async def search(self, query: str, category: str = "all") -> List[StoreResult]:
        """
        Scrape Mcube Games for the game query.

        Args:
            query: Normalised game title.
            category: Condition filter.

        Returns:
            List of StoreResult objects; may contain debug entries.
        """
        search_url = self.search_template.format(query=query.replace(" ", "+"))
        html = await fetch_with_playwright(search_url, store_name=self.store_name)

        if not html:
            logger.warning(
                "McubeGamesAdapter: No HTML returned for store=%s url=%s",
                self.store_name, search_url,
            )
            if _is_debug_mode():
                return [_make_debug_result(
                    self.store_name,
                    "Playwright returned None (network/browser failure)",
                    search_url,
                )]
            return []

        soup = BeautifulSoup(html, "lxml")
        results: List[StoreResult] = []
        cards = soup.select("div.product-card")

        if not cards:
            logger.warning(
                "McubeGamesAdapter: No products found for query='%s' url=%s",
                query, search_url,
            )
            if _is_debug_mode():
                results.append(_make_debug_result(
                    self.store_name,
                    "No products found; selector: div.product-card",
                    search_url,
                ))

        for card in cards:
            try:
                title = card.select_one(".product-title").get_text(strip=True)
                url = self.base_url + card.select_one("a")["href"]
                image_url = card.select_one(".product-img img")["src"]
                price_tag = card.select_one(".product-price strong")
                orig_price_tag = card.select_one(".product-price del")
                is_preowned = (
                    "preowned" in title.lower() or card.select_one(".preowned-label")
                )
                price = extract_price(price_tag.text) if price_tag else None
                orig_price = extract_price(orig_price_tag.text) if orig_price_tag else None

                if is_preowned and category in ("all", "preowned"):
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title + " (Pre-Owned)",
                        price=price,
                        original_price=orig_price,
                        discount_percent=None,
                        url=url,
                        image_url=image_url,
                        in_stock=True,
                        condition="preowned",
                    ))
                if not is_preowned and category in ("all", "new"):
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title,
                        price=price,
                        original_price=(
                            orig_price if orig_price and orig_price > price else None
                        ),
                        discount_percent=(
                            round((1 - price / orig_price) * 100, 1)
                            if orig_price and orig_price > price else None
                        ),
                        url=url,
                        image_url=image_url,
                        in_stock=True,
                        condition="new",
                    ))
            except Exception as ex:
                logger.warning("McubeGames parse error: %s", ex)

        return results


# ----------- GameShort.in Scraper --------------

@register_scraper("GameShort.in")
class GameShortInAdapter(BaseStoreAdapter):
    """Playwright-based scraper for GameShort.in."""

    store_name = "GameShort.in"
    base_url = "https://gameshort.in"
    search_template = base_url + "/search?q={query}"

    async def search(self, query: str, category: str = "all") -> List[StoreResult]:
        """
        Scrape GameShort.in for the game query.

        Args:
            query: Normalised game title.
            category: Condition filter.

        Returns:
            List of StoreResult objects; may contain debug entries.
        """
        search_url = self.search_template.format(query=query.replace(" ", "+"))
        html = await fetch_with_playwright(search_url, store_name=self.store_name)

        if not html:
            logger.warning(
                "GameShortInAdapter: No HTML returned for store=%s url=%s",
                self.store_name, search_url,
            )
            if _is_debug_mode():
                return [_make_debug_result(
                    self.store_name,
                    "Playwright returned None (network/browser failure)",
                    search_url,
                )]
            return []

        soup = BeautifulSoup(html, "lxml")
        results: List[StoreResult] = []
        cards = soup.select("div.product-card")

        if not cards:
            logger.warning(
                "GameShortInAdapter: No products found for query='%s' url=%s",
                query, search_url,
            )
            if _is_debug_mode():
                results.append(_make_debug_result(
                    self.store_name,
                    "No products found; selector: div.product-card",
                    search_url,
                ))

        for card in cards:
            try:
                title = card.select_one(".product-title").get_text(strip=True)
                url = self.base_url + card.select_one("a")["href"]
                image_url = card.select_one(".product-image img")["src"]
                price_tag = card.select_one(".product-price strong")
                orig_price_tag = card.select_one(".product-price del")
                is_preowned = (
                    "preowned" in title.lower() or card.select_one(".preowned-label")
                )
                price = extract_price(price_tag.text) if price_tag else None
                orig_price = extract_price(orig_price_tag.text) if orig_price_tag else None

                if is_preowned and category in ("all", "preowned"):
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title + " (Pre-Owned)",
                        price=price,
                        original_price=orig_price,
                        discount_percent=None,
                        url=url,
                        image_url=image_url,
                        in_stock=True,
                        condition="preowned",
                    ))
                if not is_preowned and category in ("all", "new"):
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title,
                        price=price,
                        original_price=(
                            orig_price if orig_price and orig_price > price else None
                        ),
                        discount_percent=(
                            round((1 - price / orig_price) * 100, 1)
                            if orig_price and orig_price > price else None
                        ),
                        url=url,
                        image_url=image_url,
                        in_stock=True,
                        condition="new",
                    ))
            except Exception as ex:
                logger.warning("GameShort.in parse error: %s", ex)

        return results


# ----------- Dacby Scraper --------------

@register_scraper("Dacby")
class DacbyAdapter(BaseStoreAdapter):
    """Playwright-based scraper for Dacby (dacby.com)."""

    store_name = "Dacby"
    base_url = "https://dacby.com"
    search_template = base_url + "/search?type=product&q={query}"

    async def search(self, query: str, category: str = "all") -> List[StoreResult]:
        """
        Scrape Dacby for the game query.

        Args:
            query: Normalised game title.
            category: Condition filter.

        Returns:
            List of StoreResult objects; may contain debug entries.
        """
        search_url = self.search_template.format(query=query.replace(" ", "+"))
        html = await fetch_with_playwright(search_url, store_name=self.store_name)

        if not html:
            logger.warning(
                "DacbyAdapter: No HTML returned for store=%s url=%s",
                self.store_name, search_url,
            )
            if _is_debug_mode():
                return [_make_debug_result(
                    self.store_name,
                    "Playwright returned None (network/browser failure)",
                    search_url,
                )]
            return []

        soup = BeautifulSoup(html, "lxml")
        results: List[StoreResult] = []
        prods = soup.select("div.product-card")

        if not prods:
            logger.warning(
                "DacbyAdapter: No products found for query='%s' url=%s",
                query, search_url,
            )
            if _is_debug_mode():
                results.append(_make_debug_result(
                    self.store_name,
                    "No products found; selector: div.product-card",
                    search_url,
                ))

        for prod in prods:
            try:
                title = prod.select_one(".product-title").get_text(strip=True)
                url = self.base_url + prod.select_one("a")["href"]
                image_url = prod.select_one(".product-img img")["src"]
                price_tag = prod.select_one(".product-price strong")
                orig_price_tag = prod.select_one(".product-price del")
                preowned_flag = (
                    "preowned" in title.lower() or prod.select_one(".preowned-label")
                )
                price = extract_price(price_tag.text) if price_tag else None
                orig_price = extract_price(orig_price_tag.text) if orig_price_tag else None

                if preowned_flag and category in ("all", "preowned"):
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title + " (Pre-Owned)",
                        price=price,
                        original_price=orig_price,
                        discount_percent=None,
                        url=url,
                        image_url=image_url,
                        in_stock=True,
                        condition="preowned",
                    ))
                if not preowned_flag and category in ("all", "new"):
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title,
                        price=price,
                        original_price=(
                            orig_price if orig_price and orig_price > price else None
                        ),
                        discount_percent=(
                            round((1 - price / orig_price) * 100, 1)
                            if orig_price and orig_price > price else None
                        ),
                        url=url,
                        image_url=image_url,
                        in_stock=True,
                        condition="new",
                    ))
            except Exception as ex:
                logger.warning("Dacby parse error: %s", ex)

        return results


# ----------- HG World Scraper --------------

@register_scraper("HG World")
class HGWorldAdapter(BaseStoreAdapter):
    """Playwright-based scraper for HG World (hgworld.in)."""

    store_name = "HG World"
    base_url = "https://hgworld.in"
    search_template = base_url + "/search?q={query}"

    async def search(self, query: str, category: str = "all") -> List[StoreResult]:
        """
        Scrape HG World for the game query.

        Args:
            query: Normalised game title.
            category: Condition filter.

        Returns:
            List of StoreResult objects; may contain debug entries.
        """
        search_url = self.search_template.format(query=query.replace(" ", "+"))
        html = await fetch_with_playwright(search_url, store_name=self.store_name)

        if not html:
            logger.warning(
                "HGWorldAdapter: No HTML returned for store=%s url=%s",
                self.store_name, search_url,
            )
            if _is_debug_mode():
                return [_make_debug_result(
                    self.store_name,
                    "Playwright returned None (network/browser failure)",
                    search_url,
                )]
            return []

        soup = BeautifulSoup(html, "lxml")
        results: List[StoreResult] = []
        cards = soup.select("div.product-card")

        if not cards:
            logger.warning(
                "HGWorldAdapter: No products found for query='%s' url=%s",
                query, search_url,
            )
            if _is_debug_mode():
                results.append(_make_debug_result(
                    self.store_name,
                    "No products found; selector: div.product-card",
                    search_url,
                ))

        for card in cards:
            try:
                title = card.select_one(".product-title").get_text(strip=True)
                url = self.base_url + card.select_one("a")["href"]
                image_url = card.select_one(".product-img img")["src"]
                price_tag = card.select_one(".product-price strong")
                orig_price_tag = card.select_one(".product-price del")
                preowned_flag = (
                    "preowned" in title.lower() or card.select_one(".preowned-label")
                )
                price = extract_price(price_tag.text) if price_tag else None
                orig_price = extract_price(orig_price_tag.text) if orig_price_tag else None

                if preowned_flag and category in ("all", "preowned"):
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title + " (Pre-Owned)",
                        price=price,
                        original_price=orig_price,
                        discount_percent=None,
                        url=url,
                        image_url=image_url,
                        in_stock=True,
                        condition="preowned",
                    ))
                if not preowned_flag and category in ("all", "new"):
                    results.append(StoreResult(
                        store_name=self.store_name,
                        title=title,
                        price=price,
                        original_price=(
                            orig_price if orig_price and orig_price > price else None
                        ),
                        discount_percent=(
                            round((1 - price / orig_price) * 100, 1)
                            if orig_price and orig_price > price else None
                        ),
                        url=url,
                        image_url=image_url,
                        in_stock=True,
                        condition="new",
                    ))
            except Exception as ex:
                logger.warning("HGWorld parse error: %s", ex)

        return results
