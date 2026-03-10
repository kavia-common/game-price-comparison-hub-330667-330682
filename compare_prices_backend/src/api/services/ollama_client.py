"""
Ollama LLM client for the PriceHunt backend.

Provides an async interface to the Ollama REST API for text generation.
Used by the LLM extractor service to parse HTML into structured game
price data when the Ollama service is available and enabled.

Contract:
    Input:  prompt (str), optional model override, optional timeout
    Output: Generated text (str) on success, None on failure
    Errors: Never raises; logs warnings and returns None on any failure
    Side effects: HTTP POST to Ollama /api/generate endpoint

Environment:
    OLLAMA_BASE_URL — Base URL of the Ollama API (e.g. http://localhost:11434)
    OLLAMA_MODEL    — Default model name (e.g. llama3.2)
    OLLAMA_TIMEOUT  — Request timeout in seconds (default: 60)
"""

import logging
from typing import Optional

import httpx

from src.api.config import get_settings

logger = logging.getLogger(__name__)


# PUBLIC_INTERFACE
async def generate_text(
    prompt: str,
    model: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Optional[str]:
    """
    Send a prompt to the Ollama /api/generate endpoint and return the response text.

    Uses the OLLAMA_BASE_URL and OLLAMA_MODEL from application settings unless
    overridden by the caller. Streams are disabled for simplicity — the full
    response is returned once generation completes.

    Args:
        prompt: The full prompt string to send to the model.
        model: Optional model name override (defaults to OLLAMA_MODEL setting).
        timeout: Optional timeout in seconds (defaults to OLLAMA_TIMEOUT setting).

    Returns:
        The generated text string, or None if the request failed.
    """
    settings = get_settings()
    base_url = settings.OLLAMA_BASE_URL
    model_name = model or settings.OLLAMA_MODEL
    request_timeout = timeout or settings.OLLAMA_TIMEOUT

    url = f"{base_url}/api/generate"

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
    }

    logger.info(
        "ollama_client: generate_text START | model=%s | url=%s | prompt_len=%d",
        model_name, url, len(prompt),
    )

    try:
        async with httpx.AsyncClient(timeout=request_timeout) as client:
            response = await client.post(url, json=payload)

            if response.status_code != 200:
                logger.warning(
                    "ollama_client: generate_text NON_200 | status=%d | body=%s",
                    response.status_code, response.text[:500],
                )
                return None

            data = response.json()
            generated = data.get("response", "")

            logger.info(
                "ollama_client: generate_text SUCCESS | model=%s | response_len=%d",
                model_name, len(generated),
            )
            return generated

    except httpx.TimeoutException:
        logger.warning(
            "ollama_client: generate_text TIMEOUT | model=%s | timeout=%ds",
            model_name, request_timeout,
        )
        return None
    except httpx.ConnectError:
        logger.warning(
            "ollama_client: generate_text CONNECT_ERROR | url=%s — is the Ollama service running?",
            url,
        )
        return None
    except Exception as exc:
        logger.error(
            "ollama_client: generate_text UNEXPECTED_ERROR | error=%s",
            str(exc), exc_info=True,
        )
        return None


# PUBLIC_INTERFACE
async def check_ollama_health() -> bool:
    """
    Check whether the Ollama service is reachable and responding.

    Sends a lightweight GET request to the Ollama base URL. A 200 response
    indicates the service is up.

    Returns:
        True if the Ollama service responds, False otherwise.
    """
    settings = get_settings()
    base_url = settings.OLLAMA_BASE_URL

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(base_url)
            is_healthy = response.status_code == 200
            logger.info(
                "ollama_client: health_check | url=%s | healthy=%s",
                base_url, is_healthy,
            )
            return is_healthy
    except Exception as exc:
        logger.warning(
            "ollama_client: health_check FAILED | url=%s | error=%s",
            base_url, str(exc),
        )
        return False
