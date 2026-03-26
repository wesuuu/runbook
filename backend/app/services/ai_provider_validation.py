"""Validate AI provider credentials by attempting to instantiate the provider."""

import logging

from fastapi import HTTPException

from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.providers.mistral import MistralProvider
from pydantic_ai.providers.cohere import CohereProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.providers.xai import XaiProvider
from pydantic_ai.providers.cerebras import CerebrasProvider
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.together import TogetherProvider
from pydantic_ai.providers.fireworks import FireworksProvider
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai.providers.google import GoogleProvider

logger = logging.getLogger(__name__)

PROVIDER_CLASSES: dict = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
    "groq": GroqProvider,
    "mistral": MistralProvider,
    "cohere": CohereProvider,
    "openrouter": OpenRouterProvider,
    "xai": XaiProvider,
    "cerebras": CerebrasProvider,
    "deepseek": DeepSeekProvider,
    "together": TogetherProvider,
    "fireworks": FireworksProvider,
    "bedrock": BedrockProvider,
    "google": GoogleProvider,
}


def validate_provider_credentials(
    provider: str, credentials: dict | None
) -> None:
    """Try to instantiate the pydantic-ai provider to validate credentials.

    Raises HTTPException(422) with a generic message on failure.
    Logs the full error for server-side debugging.
    """
    cls = PROVIDER_CLASSES.get(provider)
    if cls is None:
        return

    try:
        cls(**(credentials or {}))
    except Exception as e:
        logger.warning(
            "AI provider validation failed for %s: %s", provider, e
        )
        raise HTTPException(
            status_code=422,
            detail=f"Configuration error for {provider}. "
            "Please check your credentials.",
        )
