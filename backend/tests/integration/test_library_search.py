"""Integration tests for hybrid document search (keyword + vector)."""

import io
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.iam import Organization
from app.models.library import Document, DocumentChunk, DocumentStatus


# Mock the background processor globally for this module
@pytest.fixture(autouse=True)
def mock_processor():
    with patch(
        "app.api.endpoints.library.process_document",
        new_callable=AsyncMock,
    ):
        yield


async def _upload_and_index(
    client, auth_headers, db_session, title, content_text
):
    """Upload a document and manually create indexed chunks for testing."""
    resp = await client.post(
        "/library/documents",
        files={
            "file": ("test.txt", io.BytesIO(content_text.encode()), "text/plain")
        },
        data={"title": title},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    # Manually update status and add chunks (bypassing background processor)
    from sqlalchemy import update

    await db_session.execute(
        update(Document)
        .where(Document.id == doc_id)
        .values(status=DocumentStatus.INDEXED.value)
    )

    # Add a chunk with the content
    chunk = DocumentChunk(
        document_id=doc_id,
        chunk_index=0,
        content=content_text,
        token_count=len(content_text.split()),
    )
    db_session.add(chunk)
    await db_session.flush()

    return doc_id


class TestKeywordSearch:
    """Search should work with keywords even without embeddings."""

    @pytest.mark.asyncio
    async def test_keyword_search_finds_matching_content(
        self, client: AsyncClient, auth_headers, test_org, db_session
    ):
        await _upload_and_index(
            client,
            auth_headers,
            db_session,
            "Cell Culture Protocol",
            "CHO-K1 cells were passaged at 80% confluence using TrypLE Express",
        )

        # Mock embedding to fail — forces keyword-only mode
        with patch(
            "app.services.embedding.embed_query",
            side_effect=Exception("no embeddings"),
        ):
            resp = await client.get(
                "/library/search?q=CHO-K1 confluence",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["search_mode"] == "keyword"
        assert body["total"] >= 1
        assert body["items"][0]["document_title"] == "Cell Culture Protocol"

    @pytest.mark.asyncio
    async def test_keyword_search_returns_highlights(
        self, client: AsyncClient, auth_headers, test_org, db_session
    ):
        await _upload_and_index(
            client,
            auth_headers,
            db_session,
            "Purification SOP",
            "The protein A chromatography column was equilibrated with phosphate buffer",
        )

        with patch(
            "app.services.embedding.embed_query",
            side_effect=Exception("no embeddings"),
        ):
            resp = await client.get(
                "/library/search?q=chromatography",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        highlighted = body["items"][0]["best_chunk"]["highlighted_content"]
        assert highlighted is not None
        assert "<mark>" in highlighted

    @pytest.mark.asyncio
    async def test_keyword_search_no_results(
        self, client: AsyncClient, auth_headers, test_org, db_session
    ):
        await _upload_and_index(
            client, auth_headers, db_session, "Doc", "hello world"
        )

        with patch(
            "app.services.embedding.embed_query",
            side_effect=Exception("no embeddings"),
        ):
            resp = await client.get(
                "/library/search?q=xyznonexistent",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_stemming_works(
        self, client: AsyncClient, auth_headers, test_org, db_session
    ):
        """Searching 'passage' should match content with 'passaged'."""
        await _upload_and_index(
            client,
            auth_headers,
            db_session,
            "Passage Doc",
            "The cells were passaged twice before seeding",
        )

        with patch(
            "app.services.embedding.embed_query",
            side_effect=Exception("no embeddings"),
        ):
            resp = await client.get(
                "/library/search?q=passage",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["total"] >= 1


class TestResultGrouping:
    """Results should be grouped by document."""

    @pytest.mark.asyncio
    async def test_multiple_chunks_grouped_into_one_result(
        self, client: AsyncClient, auth_headers, test_org, db_session
    ):
        # Upload a doc
        resp = await client.post(
            "/library/documents",
            files={
                "file": (
                    "test.txt",
                    io.BytesIO(b"placeholder"),
                    "text/plain",
                )
            },
            data={"title": "Multi-Chunk Doc"},
            headers=auth_headers,
        )
        doc_id = resp.json()["id"]

        from sqlalchemy import update

        await db_session.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(status=DocumentStatus.INDEXED.value)
        )

        # Add multiple chunks with the same keyword
        for i in range(3):
            db_session.add(
                DocumentChunk(
                    document_id=doc_id,
                    chunk_index=i,
                    content=f"The bioreactor temperature was measured at {20 + i} degrees",
                    token_count=10,
                )
            )
        await db_session.flush()

        with patch(
            "app.services.embedding.embed_query",
            side_effect=Exception("no embeddings"),
        ):
            resp = await client.get(
                "/library/search?q=bioreactor temperature",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        body = resp.json()
        # Should be grouped into 1 document result
        assert body["total"] == 1
        assert body["items"][0]["match_count"] == 3
        assert body["items"][0]["document_title"] == "Multi-Chunk Doc"


class TestSearchModes:
    """Verify the search_mode field is set correctly."""

    @pytest.mark.asyncio
    async def test_keyword_mode_when_embedding_unavailable(
        self, client: AsyncClient, auth_headers, test_org, db_session
    ):
        await _upload_and_index(
            client, auth_headers, db_session, "Doc", "test content"
        )

        with patch(
            "app.services.embedding.embed_query",
            side_effect=Exception("offline"),
        ):
            resp = await client.get(
                "/library/search?q=test", headers=auth_headers
            )

        assert resp.json()["search_mode"] == "keyword"

    @pytest.mark.asyncio
    async def test_search_requires_authentication(self, client: AsyncClient):
        resp = await client.get("/library/search?q=test")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_search_requires_query(
        self, client: AsyncClient, auth_headers, test_org
    ):
        resp = await client.get(
            "/library/search?q=", headers=auth_headers
        )
        assert resp.status_code == 422
