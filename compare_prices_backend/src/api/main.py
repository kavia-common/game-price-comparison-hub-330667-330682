"""
PriceHunt API - Main application entry point.

FastAPI application for comparing game prices across 8 Indian gaming stores:
GamesTheShop, GameNation, Amazon.in, Flipkart, Mcube Games,
GameShort.in, Dacby, and HG World.

Features:
- /compare-prices endpoint with structured response and price statistics
- Mock adapter layer (Firecrawl-ready) for all 8 stores
- Health check endpoint
- CORS configuration from environment variables
- Comprehensive error handling

WebSocket Note:
  No WebSocket endpoints are currently defined. Future real-time
  price tracking may use WebSocket connections.
"""

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from src.api.config import get_settings
from src.api.models import (
    ComparePricesResponse,
    ErrorResponse,
    HealthResponse,
)
from src.api.services.price_service import compare_prices

# Load settings from environment
settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# OpenAPI tags for route grouping
openapi_tags = [
    {
        "name": "Health",
        "description": "Health check and status endpoints",
    },
    {
        "name": "Price Comparison",
        "description": "Endpoints for comparing game prices across Indian gaming stores",
    },
]

# Create FastAPI application with metadata
app = FastAPI(
    title=settings.APP_TITLE,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    openapi_tags=openapi_tags,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)

# Configure CORS middleware using environment settings.
# allow_credentials is False because the API does not use cookies or
# HTTP-auth.  Setting it to True while the origin list may contain a
# wildcard causes browsers to reject the response (CORS spec violation).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=settings.ALLOWED_METHODS,
    allow_headers=settings.ALLOWED_HEADERS,
    max_age=settings.CORS_MAX_AGE,
)


# PUBLIC_INTERFACE
@app.get(
    "/",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health Check",
    description="Returns the health status and version of the PriceHunt API.",
)
def health_check():
    """
    Health check endpoint.

    Returns the current health status, a message, and the API version.
    Used by load balancers and monitoring systems.

    Returns:
        HealthResponse: Service health status with version info
    """
    return HealthResponse(
        status="ok",
        message="PriceHunt API is running",
        version=settings.APP_VERSION,
    )


# PUBLIC_INTERFACE
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Detailed Health Check",
    description="Returns detailed health status including Firecrawl readiness.",
)
async def detailed_health_check():
    """
    Detailed health check endpoint.

    Returns health status along with configuration details
    such as Firecrawl and Ollama integration status.

    Returns:
        HealthResponse: Detailed service health status
    """
    firecrawl_status = "enabled" if settings.FIRECRAWL_ENABLED else "mock_mode"

    # Check Ollama availability when enabled
    ollama_status = "disabled"
    if getattr(settings, "OLLAMA_ENABLED", False):
        try:
            from src.api.services.ollama_client import check_ollama_health
            is_healthy = await check_ollama_health()
            ollama_status = "connected" if is_healthy else "unreachable"
        except Exception:
            ollama_status = "error"

    return HealthResponse(
        status="ok",
        message=(
            f"PriceHunt API is running "
            f"(scraping: {firecrawl_status}, ollama: {ollama_status})"
        ),
        version=settings.APP_VERSION,
    )


# PUBLIC_INTERFACE
@app.get(
    "/compare-prices",
    response_model=ComparePricesResponse,
    tags=["Price Comparison"],
    summary="Compare Game Prices",
    description=(
        "Search for a game and compare prices across 8 Indian gaming stores. "
        "Returns structured results with price, title, URL, image, and "
        "aggregated statistics by category (new/preowned)."
    ),
    responses={
        200: {
            "description": "Successful price comparison results",
            "model": ComparePricesResponse,
        },
        400: {
            "description": "Invalid query parameters",
            "model": ErrorResponse,
        },
        500: {
            "description": "Internal server error during price comparison",
            "model": ErrorResponse,
        },
    },
)
async def compare_prices_endpoint(
    query: str = Query(
        ...,
        min_length=1,
        max_length=200,
        description="Game title to search for (e.g., 'God of War Ragnarok')",
        examples=["God of War Ragnarok", "Spider-Man 2", "Elden Ring"],
    ),
    category: Optional[str] = Query(
        "all",
        description="Filter by condition: 'new', 'preowned', or 'all'",
        examples=["new", "preowned", "all"],
    ),
):
    """
    Compare game prices across all 8 Indian gaming stores.

    Searches GamesTheShop, GameNation, Amazon.in, Flipkart, Mcube Games,
    GameShort.in, Dacby, and HG World for the specified game title.

    Returns structured results including:
    - Individual store prices with URLs and images
    - Aggregated price statistics for new games
    - Aggregated price statistics for preowned games
    - Best deal identification

    Args:
        query: Game title to search for
        category: Optional filter - 'new', 'preowned', or 'all' (default: 'all')

    Returns:
        ComparePricesResponse: Structured comparison results with stats

    Raises:
        HTTPException 400: If category value is invalid
        HTTPException 500: If an unexpected error occurs during comparison
    """
    # Validate category parameter
    valid_categories = ("new", "preowned", "all")
    if category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{category}'. Must be one of: {', '.join(valid_categories)}",
        )

    logger.info("Price comparison request: query='%s', category='%s'", query, category)

    try:
        # Execute price comparison across all stores
        response = await compare_prices(query=query, category=category)
        logger.info(
            "Price comparison completed: %d results for '%s'",
            response.total_results,
            query,
        )
        return response

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as exc:
        logger.error(
            "Unexpected error during price comparison for '%s': %s",
            query,
            str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while comparing prices. Please try again.",
        )
