"""
Shared Playwright client utility for real browser-based scraping.

Provides a reusable async fetch/render function for robust real-time scraping of
JavaScript-heavy game store pages as required by /compare-prices.

Features:
- Async launch of Playwright and Chromium headless browser
- Explicit per-request timeout/cancel support
- Robust error and resource handling (always closes browser/page)
- Returns HTML after DOM is loaded (sufficient for BeautifulSoup scraping)
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

BUG FIX NOTE (2024-06):
    Previously used wait_until="networkidle" which caused ALL stores to return
    None because e-commerce pages continuously fire background XHR requests
    (analytics, ads, tracking pixels) and never reach a "network idle" state.
    Playwright would time out after 30 s for every store.

    Fix: Use wait_until="domcontentloaded" — fires as soon as the HTML DOM is
    fully parsed. This is all BeautifulSoup needs to extract product listings.
    Also added --disable-dev-shm-usage and --disable-setuid-sandbox flags for
    better compatibility with container/Docker environments (prevents shared
    memory exhaustion that can cause silent browser launch failures).
"""

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
    Fetch and render a web page using Playwright (headless Chromium), returning HTML.

    Uses wait_until="domcontentloaded" (not "networkidle") so that pages with
    persistent background network activity (analytics, ads, tracking pixels) do
    not cause timeouts. The DOM content is sufficient for BeautifulSoup scraping.

    Args:
        url: Full URL to fetch
        timeout_seconds: Maximum seconds to wait for DOM content to load
        store_name: Name of the store (for logging context)

    Returns:
        HTML text of the rendered page, or None on error/timeout
    """
    logger.info(
        "playwright_fetch START store=%s url=%s timeout=%ds",
        store_name, url, timeout_seconds,
    )
    try:
        async with async_playwright() as p:
            # Launch Chromium with flags suitable for container/sandbox environments:
            # --no-sandbox:            required in most Docker/CI environments
            # --disable-gpu:           not needed in headless; avoids GPU init errors
            # --disable-dev-shm-usage: prevents /dev/shm size issues in containers
            # --disable-setuid-sandbox: additional sandbox disable for unprivileged users
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-setuid-sandbox",
                ],
            )
            page = await browser.new_page()
            try:
                # KEY FIX: Use "domcontentloaded" instead of "networkidle".
                #
                # "networkidle" waits until no network requests fire for 500 ms.
                # E-commerce pages never reach that state (analytics/ads/tracking
                # keep firing), so every store call would timeout and return None.
                #
                # "domcontentloaded" fires as soon as the HTML is fully parsed —
                # which is sufficient for BeautifulSoup product extraction.
                await page.goto(
                    url,
                    timeout=timeout_seconds * 1000,
                    wait_until="domcontentloaded",
                )
                html = await page.content()
                logger.info(
                    "playwright_fetch SUCCESS store=%s url=%s bytes=%d",
                    store_name, url, len(html),
                )
                return html
            except Exception as ex:
                logger.warning(
                    "playwright_fetch ERROR during navigation/store=%s url=%s: %s",
                    store_name, url, str(ex),
                )
            finally:
                await page.close()
                await browser.close()
    except Exception as ex:
        logger.error(
            "playwright_fetch FAIL! Could not launch browser/store=%s url=%s error=%s",
            store_name, url, str(ex), exc_info=True,
        )
    return None
