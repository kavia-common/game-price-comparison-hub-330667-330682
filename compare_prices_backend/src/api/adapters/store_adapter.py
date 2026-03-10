"""
Unified store adapter that queries all 8 Indian game stores.
Currently returns mock data; structured for easy Firecrawl API integration.

When Firecrawl is enabled, each store's search method will:
1. Construct a search URL for the store
2. Call Firecrawl API to scrape the page
3. Parse the structured response into StoreResult objects
"""

import logging
from typing import List

from src.api.models import StoreResult
from src.api.adapters.base_adapter import BaseStoreAdapter
from src.api.adapters.mock_data import MOCK_GAME_CATALOG, SUPPORTED_STORES

logger = logging.getLogger(__name__)


class MockStoreAdapter(BaseStoreAdapter):
    """
    Mock adapter for a single game store.
    Returns pre-defined mock data for development and testing.
    
    Designed to be replaced with Firecrawl-based scraping adapters.
    Each instance represents one of the 8 supported Indian game stores.
    
    Attributes:
        store_name: Name of the game store
        base_url: Base URL of the store (placeholder for mock)
        firecrawl_ready: Flag indicating Firecrawl readiness
    """

    def __init__(self, store_name: str, base_url: str = ""):
        """
        Initialize mock store adapter.
        
        Args:
            store_name: Display name of the store
            base_url: Base URL of the store website
        """
        self.store_name = store_name
        self.base_url = base_url
        self.firecrawl_ready = True  # Ready for Firecrawl integration

    async def search(self, query: str, category: str = "all") -> List[StoreResult]:
        """
        Search for a game in mock data for this store.
        
        Performs fuzzy matching against the mock catalog. Returns results
        filtered by category (new/preowned/all).
        
        Args:
            query: The game title to search for
            category: Filter - 'new', 'preowned', or 'all'
            
        Returns:
            List of StoreResult objects matching the query and category
        """
        results = []
        normalized_query = self._normalize_query(query)

        # Search through mock catalog for matching games
        for game_key, stores_data in MOCK_GAME_CATALOG.items():
            # Fuzzy match: check if query terms appear in the game key
            if not self._matches_query(normalized_query, game_key):
                continue

            if self.store_name not in stores_data:
                continue

            store_data = stores_data[self.store_name]

            # Generate results based on category filter
            if category in ("all", "new") and store_data.get("new_price") is not None:
                discount = None
                if store_data.get("original_price") and store_data.get("new_price"):
                    discount = round(
                        (1 - store_data["new_price"] / store_data["original_price"]) * 100, 1
                    )

                results.append(
                    StoreResult(
                        store_name=self.store_name,
                        title=store_data["title"],
                        price=store_data["new_price"],
                        original_price=store_data.get("original_price"),
                        discount_percent=discount,
                        url=store_data["url"],
                        image_url=store_data.get("image_url"),
                        in_stock=store_data.get("in_stock", True),
                        condition="new",
                    )
                )

            if category in ("all", "preowned") and store_data.get("preowned_price") is not None:
                results.append(
                    StoreResult(
                        store_name=self.store_name,
                        title=store_data["title"] + " (Pre-Owned)",
                        price=store_data["preowned_price"],
                        original_price=store_data.get("new_price"),
                        discount_percent=None,
                        url=store_data["url"],
                        image_url=store_data.get("image_url"),
                        in_stock=store_data.get("in_stock", True),
                        condition="preowned",
                    )
                )

        return results

    def _matches_query(self, query: str, game_key: str) -> bool:
        """
        Check if a search query matches a game catalog key.
        Uses simple substring matching for mock data.
        
        Args:
            query: Normalized search query
            game_key: Game key from the mock catalog
            
        Returns:
            True if the query matches the game key
        """
        # Split query into terms and check if all terms appear in the game key
        query_terms = query.split()
        return all(term in game_key for term in query_terms)


# PUBLIC_INTERFACE
def get_all_store_adapters() -> List[MockStoreAdapter]:
    """
    Create and return adapter instances for all 8 supported stores.
    
    Returns:
        List of MockStoreAdapter instances, one per store
    """
    store_configs = {
        "GamesTheShop": "https://www.gamestheshop.com",
        "GameNation": "https://www.gamenation.in",
        "Amazon.in": "https://www.amazon.in",
        "Flipkart": "https://www.flipkart.com",
        "Mcube Games": "https://mcubegames.com",
        "GameShort.in": "https://gameshort.in",
        "Dacby": "https://dacby.com",
        "HG World": "https://hgworld.in",
    }

    adapters = []
    for store_name in SUPPORTED_STORES:
        base_url = store_configs.get(store_name, "")
        adapters.append(MockStoreAdapter(store_name=store_name, base_url=base_url))

    return adapters
