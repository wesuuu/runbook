"""Embedding service — generates vector embeddings via configurable providers.

Uses the same AiProviderConfig resolution chain as other AI capabilities:
DB config → env var fallback → hardcoded default (Ollama nomic-embed-text).

Supports Ollama (/api/embed) and OpenAI-compatible (/v1/embeddings) APIs.
"""

import logging
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import DEFAULT_CONFIGS
from app.services.ai.ai_config import get_credentials, get_full_config

logger = logging.getLogger(__name__)

# Max texts per API call to avoid rate limits / timeouts
BATCH_SIZE = 50


from typing import Awaitable, Callable

# Type for progress callbacks: async fn(current, total)
ProgressCallback = Callable[[int, int], Awaitable[None]]


async def embed_texts(
    texts: list[str],
    db: AsyncSession,
    on_progress: ProgressCallback | None = None,
    org_id: "UUID | None" = None,
) -> list[list[float]]:
    """Generate embeddings for a list of texts.

    Resolves the embedding provider from AiProviderConfig, batches
    the texts, and returns one embedding vector per input text.

    Args:
        texts: List of text strings to embed.
        db: Database session for config resolution.
        on_progress: Optional async callback(current, total) called
            after each batch completes.

    Returns:
        List of embedding vectors (list of floats), same length as texts.
        Returns empty list if texts is empty.

    Raises:
        EmbeddingError: If the embedding API call fails.
    """
    if not texts:
        return []

    config = await get_full_config("embedding", db, org_id=org_id)
    provider = config["provider"]
    model_name = config["model_name"]
    creds = config.get("credentials") or {}
    api_key = creds.get("api_key")
    base_url = creds.get("base_url")
    context_window = config.get("context_window") or 8192

    all_embeddings: list[list[float]] = []
    total = len(texts)

    for i in range(0, total, BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]

        if provider == "ollama":
            embeddings = await _embed_ollama(
                batch, model_name, base_url, context_window, api_key
            )
        elif provider in ("openai", "anthropic", "google"):
            embeddings = await _embed_openai_compatible(
                batch, model_name, api_key, base_url, provider
            )
        else:
            raise EmbeddingError(f"Unsupported embedding provider: {provider}")

        all_embeddings.extend(embeddings)

        if on_progress:
            await on_progress(min(i + BATCH_SIZE, total), total)

    return all_embeddings


async def embed_query(
    query: str,
    db: AsyncSession,
    org_id: "UUID | None" = None,
) -> list[float]:
    """Embed a single query string. Convenience wrapper around embed_texts."""
    results = await embed_texts([query], db, org_id=org_id)
    if not results:
        raise EmbeddingError("Failed to embed query")
    return results[0]


async def _embed_ollama(
    texts: list[str],
    model: str,
    base_url: Optional[str],
    num_ctx: int = 8192,
    api_key: Optional[str] = None,
) -> list[list[float]]:
    """Call Ollama's /api/embed endpoint.

    A local Ollama daemon needs no auth, but Ollama Cloud
    (``https://ollama.com``) requires a Bearer token — send one whenever
    an API key is configured so the same code path serves both.
    """
    url = (base_url or "http://localhost:11434").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async with httpx.AsyncClient(timeout=120) as client:
        # Ollama /api/embed supports batch input
        resp = await client.post(
            f"{url}/api/embed",
            json={
                "model": model,
                "input": texts,
                "options": {"num_ctx": num_ctx},
            },
            headers=headers,
        )
        if resp.status_code != 200:
            raise EmbeddingError(
                f"Ollama embedding failed ({resp.status_code}): " f"{resp.text[:200]}"
            )

        data = resp.json()
        embeddings = data.get("embeddings", [])
        if len(embeddings) != len(texts):
            raise EmbeddingError(
                f"Ollama returned {len(embeddings)} embeddings "
                f"for {len(texts)} texts"
            )
        return embeddings


async def _embed_openai_compatible(
    texts: list[str],
    model: str,
    api_key: Optional[str],
    base_url: Optional[str],
    provider: str,
) -> list[list[float]]:
    """Call an OpenAI-compatible /v1/embeddings endpoint."""
    if provider == "openai":
        url = (base_url or "https://api.openai.com").rstrip("/")
    elif provider == "google":
        url = (base_url or "https://generativelanguage.googleapis.com").rstrip("/")
    elif provider == "anthropic":
        # Anthropic doesn't have an embeddings endpoint yet,
        # but allow it for forward compatibility
        url = (base_url or "https://api.anthropic.com").rstrip("/")
    else:
        url = (base_url or "").rstrip("/")

    if not api_key:
        raise EmbeddingError(
            f"API key required for {provider} embedding provider. "
            f"Configure it in Settings > AI > Embedding."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{url}/v1/embeddings",
            json={"model": model, "input": texts},
            headers=headers,
        )
        if resp.status_code != 200:
            raise EmbeddingError(
                f"{provider} embedding failed ({resp.status_code}): "
                f"{resp.text[:200]}"
            )

        data = resp.json()
        items = data.get("data", [])
        # Sort by index to ensure order matches input
        items.sort(key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in items]


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""

    pass
