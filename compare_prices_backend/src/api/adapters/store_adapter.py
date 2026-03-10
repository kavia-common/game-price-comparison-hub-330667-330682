"""
Unified store adapter module dispatches to real-time store scrapers.

Implements get_all_store_adapters() which returns one adapter per supported store.
Internally uses registry-based store scrapers for robust, reusable scraping.

All I/O and parsing logic are in scrapers.py; this file is the orchestration point.

Contract:
  Input: (none, uses SUPPORTED_STORES)
  Output: List[BaseStoreAdapter] (one per store)
  Errors: Logs warning if a store is not implemented.
"""

import logging
from typing import List

from src.api.adapters.base_adapter import BaseStoreAdapter
from src.api.adapters.mock_data import SUPPORTED_STORES
from src.api.adapters.scrapers import STORE_SCRAPER_REGISTRY

logger = logging.getLogger(__name__)

# PUBLIC_INTERFACE
def get_all_store_adapters() -> List[BaseStoreAdapter]:
    """
    Create and return one adapter instance for every supported store.
    Uses real scraper adapters with robust error handling.

    Returns:
        List of store adapter instances, one per store
    """
    adapters = []
    for store_name in SUPPORTED_STORES:
        scraper_cls = STORE_SCRAPER_REGISTRY.get(store_name)
        if scraper_cls:
            adapters.append(scraper_cls())
        else:
            logger.warning("No scraper implemented for store: %s", store_name)
    return adapters
