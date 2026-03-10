"""
Pydantic models for the PriceHunt compare-prices API.
Defines structured response models for price comparison results,
store results, price statistics, and error responses.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class StoreResult(BaseModel):
    """
    Represents a single price result from a game store.
    
    Attributes:
        store_name: Name of the store (e.g., "GamesTheShop", "Amazon.in")
        title: Game title as listed on the store
        price: Price of the game in INR (None if unavailable)
        original_price: Original/MRP price before discount (None if no discount)
        discount_percent: Discount percentage (None if no discount)
        url: Direct link to the product page
        image_url: URL of the product image (None if unavailable)
        in_stock: Whether the game is currently in stock
        condition: Condition of the game ("new" or "preowned")
    """
    store_name: str = Field(..., description="Name of the game store")
    title: str = Field(..., description="Game title as listed on the store")
    price: Optional[float] = Field(None, description="Price in INR")
    original_price: Optional[float] = Field(None, description="Original/MRP price before discount")
    discount_percent: Optional[float] = Field(None, description="Discount percentage if applicable")
    url: str = Field(..., description="Direct link to the product page")
    image_url: Optional[str] = Field(None, description="URL of the product image")
    in_stock: bool = Field(True, description="Whether the game is in stock")
    condition: str = Field("new", description="Condition: 'new' or 'preowned'")


class PriceStats(BaseModel):
    """
    Aggregated price statistics for a set of store results.

    Attributes:
        lowest_price: The minimum price found across all stores
        highest_price: The maximum price found across all stores
        average_price: The mean price across all stores
        store_count: Number of stores with available prices
        best_deal_store: Name of the store with the lowest price
    """
    lowest_price: Optional[float] = Field(None, description="Minimum price found")
    highest_price: Optional[float] = Field(None, description="Maximum price found")
    average_price: Optional[float] = Field(None, description="Average price across stores")
    store_count: int = Field(0, description="Number of stores with available prices")
    best_deal_store: Optional[str] = Field(None, description="Store with the lowest price")


class ComparePricesResponse(BaseModel):
    """
    Full response model for the /compare-prices endpoint.

    Attributes:
        query: The original search query
        category: Category filter applied ('new' or 'preowned')
        results: List of individual store results
        new_stats: Price statistics for new condition results
        preowned_stats: Price statistics for preowned condition results
        total_results: Total number of results returned
    """
    query: str = Field(..., description="The original search query")
    category: str = Field("new", description="Category filter applied: 'new' or 'preowned'")
    results: List[StoreResult] = Field(default_factory=list, description="List of store price results")
    new_stats: PriceStats = Field(default_factory=PriceStats, description="Stats for new game prices")
    preowned_stats: PriceStats = Field(default_factory=PriceStats, description="Stats for preowned game prices")
    total_results: int = Field(0, description="Total number of results returned")


class ComparePricesRequest(BaseModel):
    """
    Request model for the /compare-prices endpoint.

    Attributes:
        query: The game title to search for
        category: Optional category filter ('new', 'preowned', or 'all')
    """
    query: str = Field(..., description="Game title to search for", min_length=1, max_length=200)
    category: str = Field("all", description="Category filter: 'new', 'preowned', or 'all'")


class ErrorResponse(BaseModel):
    """
    Standard error response model.

    Attributes:
        detail: Error message description
        status_code: HTTP status code
    """
    detail: str = Field(..., description="Error description")
    status_code: int = Field(..., description="HTTP status code")


class HealthResponse(BaseModel):
    """
    Health check response model.

    Attributes:
        status: Service health status
        message: Descriptive health message
        version: API version string
    """
    status: str = Field("ok", description="Service status")
    message: str = Field("Healthy", description="Health message")
    version: str = Field("1.0.0", description="API version")
