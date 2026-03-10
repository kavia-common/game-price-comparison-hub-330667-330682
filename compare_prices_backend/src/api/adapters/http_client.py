"""
Shared HTTP client for store scrapers.

Provides a reusable, async HTTP fetch function with:
- Configurable timeouts (per-request and global)
- Rotating User-Agent headers to reduce blocking
- Structured error handling with context
- Connection pooling via aiohttp

Contract:
    Input:  URL (str), optional timeout (int seconds)
    Output: Response text (str) on success
    Errors: Returns None on any network/timeout failure (logged with context)
    Side effects: HTTP GET to external URL

All store scrapers use this single fetch function to avoid duplicating
HTTP logic across adapters.
"""

import asyncio
import logging
import random
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Rotating user-agent pool to reduce chance of being blocked
_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
        "Gecko/20100101 Firefox/126.0"
    ),
]

# Default timeout for individual store requests (seconds)
DEFAULT_TIMEOUT_SECONDS = 15


def _get_headers() -> dict:
    """
    Build request headers with a random User-Agent.

    Returns:
        Dictionary of HTTP headers suitable for a browser-like GET request.
    """
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }


# PUBLIC_INTERFACE
async def fetch_page(
    url: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    store_name: str = "unknown",
) -> Optional[str]:
    """
    Fetch a web page asynchronously and return its HTML text.

    Uses aiohttp with a per-request timeout. On any failure (network error,
    timeout, non-200 status), logs a warning and returns None so the caller
    can gracefully degrade.

    Args:
        url: Full URL to fetch
        timeout_seconds: Maximum seconds to wait for the response
        store_name: Name of the store (for logging context)

    Returns:
        HTML text of the page, or None on failure
    """
    logger.info("fetch_page START store=%s url=%s timeout=%ds", store_name, url, timeout_seconds)

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=_get_headers()) as session:
            async with session.get(url, ssl=False) as response:
                if response.status != 200:
                    logger.warning(
                        "fetch_page NON_200 store=%s url=%s status=%d",
                        store_name, url, response.status,
                    )
                    return None
                text = await response.text()
                logger.info(
                    "fetch_page SUCCESS store=%s url=%s bytes=%d",
                    store_name, url, len(text),
                )
                return text

    except asyncio.TimeoutError:
        logger.warning("fetch_page TIMEOUT store=%s url=%s", store_name, url)
        return None
    except aiohttp.ClientError as exc:
        logger.warning("fetch_page CLIENT_ERROR store=%s url=%s error=%s", store_name, url, str(exc))
        return None
    except Exception as exc:
        logger.error(
            "fetch_page UNEXPECTED_ERROR store=%s url=%s error=%s",
            store_name, url, str(exc), exc_info=True,
        )
        return None
