"""Tests for the embedding service."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.ai.embedding import (
    embed_texts,
    embed_query,
    _embed_ollama,
    _embed_openai_compatible,
    EmbeddingError,
    BATCH_SIZE,
)
from app.services.document_processor import _pad_embedding
from app.models.library import EMBEDDING_DIMENSIONS


class TestPadEmbedding:
    def test_same_dimensions_unchanged(self):
        vec = [0.1] * EMBEDDING_DIMENSIONS
        assert _pad_embedding(vec) == vec

    def test_shorter_vector_zero_padded(self):
        vec = [0.5] * 768
        result = _pad_embedding(vec)
        assert len(result) == EMBEDDING_DIMENSIONS
        assert result[:768] == [0.5] * 768
        assert result[768:] == [0.0] * (EMBEDDING_DIMENSIONS - 768)

    def test_longer_vector_truncated(self):
        vec = [0.3] * 3072
        result = _pad_embedding(vec)
        assert len(result) == EMBEDDING_DIMENSIONS
        assert result == [0.3] * EMBEDDING_DIMENSIONS

    def test_empty_vector_padded(self):
        result = _pad_embedding([])
        assert len(result) == EMBEDDING_DIMENSIONS
        assert all(v == 0.0 for v in result)


class TestEmbedOllama:
    @pytest.mark.asyncio
    async def test_successful_embedding(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        }

        with patch("app.services.ai.embedding.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await _embed_ollama(
                ["hello", "world"], "nomic-embed-text", None
            )

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_ollama_error_raises(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("app.services.ai.embedding.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            with pytest.raises(EmbeddingError, match="Ollama embedding failed"):
                await _embed_ollama(["test"], "model", None)

    @pytest.mark.asyncio
    async def test_ollama_uses_custom_base_url(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embeddings": [[0.1]]}

        with patch("app.services.ai.embedding.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            await _embed_ollama(
                ["test"], "model", "http://custom:11434"
            )

            # Check the URL used
            call_args = mock_client.post.call_args
            assert "http://custom:11434/api/embed" in call_args[0]


class TestEmbedOpenAICompatible:
    @pytest.mark.asyncio
    async def test_successful_embedding(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        }

        with patch("app.services.ai.embedding.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await _embed_openai_compatible(
                ["hello", "world"],
                "text-embedding-3-small",
                "sk-test-key",
                None,
                "openai",
            )

        assert len(result) == 2
        assert result[0] == [0.1, 0.2]

    @pytest.mark.asyncio
    async def test_requires_api_key(self):
        with pytest.raises(EmbeddingError, match="API key required"):
            await _embed_openai_compatible(
                ["test"], "model", None, None, "openai"
            )

    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("app.services.ai.embedding.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            with pytest.raises(EmbeddingError, match="openai embedding failed"):
                await _embed_openai_compatible(
                    ["test"], "model", "sk-bad", None, "openai"
                )


class TestEmbedTexts:
    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        # embed_texts with empty list should return immediately
        db = AsyncMock()
        result = await embed_texts([], db)
        assert result == []

    @pytest.mark.asyncio
    async def test_uses_config_from_db(self):
        db = AsyncMock()

        with patch(
            "app.services.ai.embedding.get_full_config",
            return_value={
                "provider": "ollama",
                "model_name": "nomic-embed-text",
                "api_key": None,
                "base_url": None,
            },
        ):
            with patch(
                "app.services.ai.embedding._embed_ollama",
                return_value=[[0.1, 0.2]],
            ) as mock_ollama:
                result = await embed_texts(["hello"], db)

        assert result == [[0.1, 0.2]]
        mock_ollama.assert_called_once()


class TestEmbedQuery:
    @pytest.mark.asyncio
    async def test_returns_single_vector(self):
        db = AsyncMock()

        with patch(
            "app.services.ai.embedding.embed_texts",
            return_value=[[0.1, 0.2, 0.3]],
        ):
            result = await embed_query("test query", db)

        assert result == [0.1, 0.2, 0.3]


class TestBatchSize:
    def test_batch_size_is_reasonable(self):
        assert BATCH_SIZE == 50
