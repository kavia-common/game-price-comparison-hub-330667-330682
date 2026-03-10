"""
Base adapter class for store integrations.
All store adapters inherit from this base class.
Designed for future Firecrawl API integration.
"""

from abc import ABC, abstractmethod
from typing import List

from src.api.models import StoreResult


class BaseStoreAdapter(ABC):
    """
    Abstract base class for all store adapters.
    
    Each store adapter is responsible for fetching and parsing
    game price data from a specific Indian game store.
    
    Currently returns mock data. When Firecrawl integration is enabled,
    subclasses will use the Firecrawl API to scrape real store pages.
    
    Attributes:
        store_name: Display name of the store
        base_url: Base URL of the store website
        firecrawl_ready: Whether the adapter supports Firecrawl scraping
    """

    store_name: str = ""
    base_url: str = ""
    firecrawl_ready: bool = False

    @abstractmethod
    async def search(self, query: str, category: str = "all") -> List[StoreResult]:
        """
        Search for a game on this store.
        
        Args:
            query: The game title to search for
            category: Filter by condition - 'new', 'preowned', or 'all'
        
        Returns:
            List of StoreResult objects with price information
        """
        pass

    def _normalize_query(self, query: str) -> str:
        """
        Normalize a search query for consistent matching.
        
        Args:
            query: Raw search query string
            
        Returns:
            Lowercased, stripped query string
        """
        return query.strip().lower()
