"""
Shared Playwright client utility for real browser-based scraping.

Provides a reusable async fetch/render function for robust real-time scraping of
JavaScript-heavy game store pages as required by /compare-prices.

Features:
- Async launch of Playwright and Chromium headless browser
- Explicit per-request timeout/cancel support
- Robust error and resource handling (always closes browser/page)
- Returns final HTML after page load and all network requests (for best accuracy)
- Logs activity per store/URL
- Single function: fetch_with_playwright

Requires: playwright Python package and browsers installed.

Note: Avoid use except where HTTP+BeautifulSoup is blocked or fails.
All store adapters may select HTTP or Playwright adaptively if needed.

Contract:
    Input:  URL (str), timeout (int seconds), store_name (str, for logging)
    Output: Rendered page content (str) on success, None on error/timeout
    Errors: Always logged with context, never raises
    Side effects: launches Chromium browser process

WARNING: This module is heavier than HTTP and should be used conservatively.
"""

import asyncio
import logging
from typing import Optional

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30

# PUBLIC_INTERFACE
async def fetch_with_playwright(
    url: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    store_name: str = "unknown"
) -> Optional[str]:
    """
    Fetch and render a web page using Playwright (headless chromium), returning HTML.

    Args:
        url: Full URL to fetch
        timeout_seconds: Maximum seconds to wait (browser + nav + render)
        store_name: Name of the store (for logging)

    Returns:
        Final HTML text of the rendered page, or None on error/timeout
    """
    logger.info("playwright_fetch START store=%s url=%s timeout=%ds", store_name, url, timeout_seconds)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
            page = await browser.new_page()
            try:
                await page.goto(url, timeout=timeout_seconds * 1000, wait_until="networkidle")
                await asyncio.sleep(2)  # let JS finish if needed
                html = await page.content()
                logger.info("playwright_fetch SUCCESS store=%s url=%s bytes=%d", store_name, url, len(html))
                return html
            except Exception as ex:
                logger.warning("playwright_fetch ERROR during navigation/store=%s url=%s: %s", store_name, url, str(ex))
            finally:
                await page.close()
                await browser.close()
    except Exception as ex:
        logger.error("playwright_fetch FAIL! Could not launch browser/store=%s url=%s error=%s", store_name, url, str(ex), exc_info=True)
    return None
