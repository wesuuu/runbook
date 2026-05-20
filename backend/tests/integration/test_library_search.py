"""Integration tests for hybrid document search (keyword + vector)."""

import io
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.iam import Organization
from app.models.library import Document, DocumentChunk, DocumentStatus


# Mock the background handler globally for this module
@pytest.fixture(autouse=True)
def mock_processor():
    class _FakeHandler:
        async def launch(self, job, **kwargs):
            pass

    with patch(
        "app.api.endpoints.library.get_background_handler",
        return_value=_FakeHandler(),
    ):
        yield


async def _upload_and_index(client, auth_headers, db_session, title, content_text):
    """Insert a document and indexed chunk directly (no HTTP upload).

    Previously used HTTP upload with text/plain; text/plain is no longer
    an allowed MIME type, so we insert rows directly via db_session.
    """
    from sqlalchemy import select as sa_select

    from app.models.iam import (
        ObjectPermission,
        ObjectType,
        OrganizationMember,
        PermissionLevel,
        PrincipalType,
    )

    # Resolve org_id from the existing session/member rows via test_user token
    # We read the Authorization header to get user_id then query org membership.
    # Simpler: use a fixed org from test_org — but we don't have it here.
    # Instead, pull org from existing OrganizationMember rows.
    result = await db_session.execute(sa_select(OrganizationMember).limit(1))
    member = result.scalar_one_or_none()
    org_id = member.organization_id
    user_id = member.user_id

    doc = Document(
        org_id=org_id,
        uploaded_by_id=user_id,
        title=title,
        slug=f"{title.lower().replace(' ', '-')[:32]}-{uuid.uuid4().hex[:6]}",
        original_filename="test.txt",
        mime_type="text/plain",
        file_size_bytes=len(content_text.encode()),
        file_path=f"uploads/{uuid.uuid4().hex}.txt",
        status=DocumentStatus.INDEXED.value,
    )
    db_session.add(doc)
    await db_session.flush()

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=content_text,
        token_count=len(content_text.split()),
    )
    db_session.add(chunk)
    await db_session.flush()

    return str(doc.id)


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
            "app.services.ai.embedding.embed_query",
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
        # F-0091: the search result group carries the document's slug so the
        # frontend can build /<org>/library/<slug> links.
        assert body["items"][0]["document_slug"].startswith("cell-culture-protocol")

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
            "app.services.ai.embedding.embed_query",
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
        await _upload_and_index(client, auth_headers, db_session, "Doc", "hello world")

        with patch(
            "app.services.ai.embedding.embed_query",
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
            "app.services.ai.embedding.embed_query",
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
        from sqlalchemy import select as sa_select

        from app.models.iam import OrganizationMember

        result = await db_session.execute(sa_select(OrganizationMember).limit(1))
        member = result.scalar_one_or_none()

        doc = Document(
            org_id=member.organization_id,
            uploaded_by_id=member.user_id,
            title="Multi-Chunk Doc",
            slug=f"multi-chunk-doc-{uuid.uuid4().hex[:8]}",
            original_filename="multi.txt",
            mime_type="text/plain",
            file_size_bytes=100,
            file_path=f"uploads/{uuid.uuid4().hex}.txt",
            status=DocumentStatus.INDEXED.value,
        )
        db_session.add(doc)
        await db_session.flush()
        doc_id = str(doc.id)

        # Add multiple chunks with the same keyword
        for i in range(3):
            db_session.add(
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=i,
                    content=f"The bioreactor temperature was measured at {20 + i} degrees",
                    token_count=10,
                )
            )
        await db_session.flush()

        with patch(
            "app.services.ai.embedding.embed_query",
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
        await _upload_and_index(client, auth_headers, db_session, "Doc", "test content")

        with patch(
            "app.services.ai.embedding.embed_query",
            side_effect=Exception("offline"),
        ):
            resp = await client.get("/library/search?q=test", headers=auth_headers)

        assert resp.json()["search_mode"] == "keyword"

    @pytest.mark.asyncio
    async def test_search_requires_authentication(self, client: AsyncClient):
        resp = await client.get("/library/search?q=test")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_search_requires_query(
        self, client: AsyncClient, auth_headers, test_org
    ):
        resp = await client.get("/library/search?q=", headers=auth_headers)
        assert resp.status_code == 422
