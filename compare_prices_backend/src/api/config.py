"""
Application configuration module.
Loads settings from environment variables with sensible defaults.
Uses python-dotenv for .env file support.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Settings:
    """
    Application settings loaded from environment variables.
    
    Attributes:
        APP_TITLE: Application title for OpenAPI docs
        APP_DESCRIPTION: Application description for OpenAPI docs
        APP_VERSION: Application version string
        HOST: Server bind host
        PORT: Server bind port
        ALLOWED_ORIGINS: Comma-separated list of allowed CORS origins
        ALLOWED_METHODS: Comma-separated list of allowed HTTP methods
        ALLOWED_HEADERS: Comma-separated list of allowed headers
        CORS_MAX_AGE: CORS preflight cache duration in seconds
        NODE_ENV: Environment mode (development/production)
        LOG_LEVEL: Logging level
        REQUEST_TIMEOUT_MS: Request timeout in milliseconds
        # Firecrawl settings (for future integration)
        FIRECRAWL_API_KEY: API key for Firecrawl service
        FIRECRAWL_ENABLED: Whether to use Firecrawl for real scraping
    """

    def __init__(self):
        """Initialize settings from environment variables."""
        # Server settings
        self.APP_TITLE = "PriceHunt API"
        self.APP_DESCRIPTION = (
            "Game price comparison API that scrapes and compares prices "
            "from 8 Indian gaming stores. Supports new and preowned games."
        )
        self.APP_VERSION = "1.0.0"
        self.HOST = os.getenv("HOST", "0.0.0.0")
        self.PORT = int(os.getenv("PORT", "3001"))

        # CORS settings
        self.ALLOWED_ORIGINS = os.getenv(
            "ALLOWED_ORIGINS", "http://localhost:3000"
        ).split(",")
        self.ALLOWED_METHODS = os.getenv(
            "ALLOWED_METHODS", "GET,POST,PUT,DELETE,PATCH,OPTIONS"
        ).split(",")
        self.ALLOWED_HEADERS = os.getenv(
            "ALLOWED_HEADERS", "Content-Type,Authorization,X-Requested-With"
        ).split(",")
        self.CORS_MAX_AGE = int(os.getenv("CORS_MAX_AGE", "3600"))

        # Application settings
        self.NODE_ENV = os.getenv("NODE_ENV", "development")
        self.LOG_LEVEL = os.getenv("VITE_LOG_LEVEL", "info").upper()
        self.REQUEST_TIMEOUT_MS = int(os.getenv("REQUEST_TIMEOUT_MS", "30000"))

        # Firecrawl settings (for future real scraping integration)
        # Set FIRECRAWL_API_KEY env var to enable real store scraping
        self.FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
        self.FIRECRAWL_ENABLED = os.getenv("FIRECRAWL_ENABLED", "false").lower() == "true"


# PUBLIC_INTERFACE
def get_settings() -> Settings:
    """
    Get application settings instance.
    
    Returns:
        Settings object with configuration loaded from environment
    """
    return Settings()
