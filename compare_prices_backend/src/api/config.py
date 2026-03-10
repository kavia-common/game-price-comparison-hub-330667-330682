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
        FIRECRAWL_API_KEY: API key for Firecrawl service
        FIRECRAWL_ENABLED: Whether to use Firecrawl for real scraping
        OLLAMA_BASE_URL: Base URL of the Ollama REST API
        OLLAMA_MODEL: Model name to use for LLM extraction
        OLLAMA_ENABLED: Whether LLM-based extraction is enabled
        OLLAMA_TIMEOUT: Timeout in seconds for Ollama API calls
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

        # CORS settings - merge ALLOWED_ORIGINS with FRONTEND_URL so the
        # frontend origin is always permitted even if not listed explicitly.
        #
        # IMPORTANT: Do NOT add a wildcard "*" to this list.
        # The CORS middleware uses allow_credentials=False, but mixing
        # wildcard with explicit origins causes inconsistent
        # Access-Control-Allow-Origin headers between preflight (OPTIONS)
        # and actual requests, which browsers reject.
        # Instead, list every permitted origin explicitly and the
        # middleware will reflect the matched origin back to the browser.
        raw_origins = os.getenv(
            "ALLOWED_ORIGINS", "http://localhost:3000"
        ).split(",")
        frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
        combined = [o.strip() for o in raw_origins if o.strip()]
        if frontend_url and frontend_url not in combined:
            combined.append(frontend_url)
        # Ensure common development origins are always allowed
        for dev_origin in ["http://localhost:3000", "http://localhost:4000"]:
            if dev_origin not in combined:
                combined.append(dev_origin)
        self.ALLOWED_ORIGINS = combined

        self.ALLOWED_METHODS = os.getenv(
            "ALLOWED_METHODS", "GET,POST,PUT,DELETE,PATCH,OPTIONS"
        ).split(",")
        self.ALLOWED_HEADERS = os.getenv(
            "ALLOWED_HEADERS",
            "Content-Type,Authorization,X-Requested-With,Accept,Accept-Language,Content-Language"
        ).split(",")
        self.CORS_MAX_AGE = int(os.getenv("CORS_MAX_AGE", "3600"))

        # Application settings
        self.NODE_ENV = os.getenv("NODE_ENV", "development")
        self.LOG_LEVEL = os.getenv("VITE_LOG_LEVEL", "info").upper()
        self.REQUEST_TIMEOUT_MS = int(os.getenv("REQUEST_TIMEOUT_MS", "30000"))

        # Firecrawl settings (for future real scraping integration)
        # Set FIRECRAWL_API_KEY env var to enable real store scraping
        self.FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
        self.FIRECRAWL_ENABLED = (
            os.getenv("FIRECRAWL_ENABLED", "false").lower() == "true"
        )

        # Debug: Show scraping errors directly in API response for all stores
        # if enabled. Helpful for debugging environment issues or selector drift
        self.DEBUG_SCRAPER_ERRORS = (
            os.getenv("DEBUG_SCRAPER_ERRORS", "false").lower() == "true"
        )

        # Fallback: When all Playwright scrapers return zero results (e.g. in
        # a sandboxed environment without internet access), serve mock catalog
        # data so the UI remains functional.
        # Set USE_MOCK_FALLBACK=true in .env to enable.
        self.USE_MOCK_FALLBACK = (
            os.getenv("USE_MOCK_FALLBACK", "false").lower() == "true"
        )

        # Ollama LLM service settings for intelligent HTML extraction.
        # OLLAMA_BASE_URL: Base URL of the Ollama REST API
        #   (e.g. http://localhost:11434/)
        # OLLAMA_MODEL: Model name to use for extraction (e.g. llama3.2)
        # OLLAMA_ENABLED: Master switch - set to "true" to enable LLM
        #   extraction fallback
        # OLLAMA_TIMEOUT: Request timeout in seconds for Ollama API calls
        self.OLLAMA_BASE_URL = os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434/"
        ).rstrip("/")
        self.OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
        self.OLLAMA_ENABLED = (
            os.getenv("OLLAMA_ENABLED", "false").lower() == "true"
        )
        self.OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))


# PUBLIC_INTERFACE
def get_settings() -> Settings:
    """
    Get application settings instance.

    Returns:
        Settings object with configuration loaded from environment
    """
    return Settings()
