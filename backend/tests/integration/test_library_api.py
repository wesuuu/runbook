import io
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.iam import Organization, OrganizationMember, User
from app.models.library import Document, DocumentStatus
from app.models.science import Project


# Mock the background processor to avoid async task issues in tests
@pytest.fixture(autouse=True)
def mock_processor():
    with patch(
        "app.api.endpoints.library.process_document",
        new_callable=AsyncMock,
    ):
        yield


def _make_upload(
    client: AsyncClient,
    auth_headers: dict,
    content: bytes = b"Hello, world!",
    filename: str = "test.txt",
    mime_type: str = "text/plain",
    title: str = "Test Document",
    project_id: str | None = None,
    tags: str | None = None,
):
    """Helper to build an upload request."""
    data = {"title": title}
    if project_id:
        data["project_id"] = project_id
    if tags:
        data["tags"] = tags

    return client.post(
        "/library/documents",
        files={"file": (filename, io.BytesIO(content), mime_type)},
        data=data,
        headers=auth_headers,
    )


# --- Upload Tests ---


@pytest.mark.asyncio
async def test_upload_txt_document_returns_201(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    resp = await _make_upload(client, auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Test Document"
    assert body["mime_type"] == "text/plain"
    assert body["status"] == "UPLOADED"


@pytest.mark.asyncio
async def test_upload_pdf_document_returns_201(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    # Minimal valid PDF content (starts with %PDF-)
    pdf_content = b"%PDF-1.4 fake pdf content for testing"
    resp = await _make_upload(
        client,
        auth_headers,
        content=pdf_content,
        filename="report.pdf",
        mime_type="application/pdf",
        title="PDF Report",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_upload_sets_correct_response_fields(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    resp = await _make_upload(client, auth_headers, title="My Doc")
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert body["title"] == "My Doc"
    assert body["original_filename"] == "test.txt"
    assert body["file_size_bytes"] == len(b"Hello, world!")
    assert body["status"] == "UPLOADED"
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_upload_writes_file_to_disk(
    client: AsyncClient, auth_headers: dict, test_org: Organization, tmp_path
):
    from app.services.core.file_storage import FileStorageService

    resp = await _make_upload(client, auth_headers, content=b"disk check")
    assert resp.status_code == 201
    body = resp.json()
    # The file_path is now a relative path resolved via FileStorageService
    file_path = body["file_path"]
    assert str(test_org.id) in file_path  # org-scoped
    assert "documents" in file_path
    storage = FileStorageService()
    full_path = storage.resolve_path(file_path)
    assert full_path.exists()


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_mime_type(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    resp = await _make_upload(
        client,
        auth_headers,
        filename="test.exe",
        mime_type="application/octet-stream",
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    # Create content just over 50MB
    from app.models.library import MAX_DOCUMENT_SIZE_BYTES

    big_content = b"x" * (MAX_DOCUMENT_SIZE_BYTES + 1)
    resp = await _make_upload(
        client, auth_headers, content=big_content
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_upload_requires_authentication(client: AsyncClient):
    resp = await client.post(
        "/library/documents",
        files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"title": "Test"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_title_from_form_field(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    resp = await _make_upload(
        client, auth_headers, title="Custom Title"
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "Custom Title"


@pytest.mark.asyncio
async def test_upload_with_project_id(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    test_project: Project,
):
    resp = await _make_upload(
        client,
        auth_headers,
        project_id=str(test_project.id),
    )
    assert resp.status_code == 201
    assert resp.json()["project_id"] == str(test_project.id)


@pytest.mark.asyncio
async def test_upload_with_tags_json(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    resp = await _make_upload(
        client,
        auth_headers,
        tags=json.dumps(["sop", "cell-culture"]),
    )
    assert resp.status_code == 201
    assert resp.json()["tags"] == ["sop", "cell-culture"]


# --- List Tests ---


@pytest.mark.asyncio
async def test_list_documents_empty_returns_empty_list(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    resp = await client.get("/library/documents", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_documents_returns_uploaded_docs(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    # Upload two documents
    await _make_upload(client, auth_headers, title="Doc 1")
    await _make_upload(client, auth_headers, title="Doc 2")

    resp = await client.get("/library/documents", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_list_documents_filters_by_project_id(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    test_project: Project,
):
    await _make_upload(
        client,
        auth_headers,
        title="With Project",
        project_id=str(test_project.id),
    )
    await _make_upload(client, auth_headers, title="No Project")

    resp = await client.get(
        f"/library/documents?project_id={test_project.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "With Project"


@pytest.mark.asyncio
async def test_list_documents_filters_by_status(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    await _make_upload(client, auth_headers, title="Doc 1")

    resp = await client.get(
        "/library/documents?status=UPLOADED", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert all(
        item["status"] == "UPLOADED" for item in body["items"]
    )


@pytest.mark.asyncio
async def test_list_documents_pagination(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    for i in range(5):
        await _make_upload(client, auth_headers, title=f"Doc {i}")

    resp = await client.get(
        "/library/documents?limit=2&offset=0", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2

    resp2 = await client.get(
        "/library/documents?limit=2&offset=2", headers=auth_headers
    )
    body2 = resp2.json()
    assert len(body2["items"]) == 2


@pytest.mark.asyncio
async def test_list_documents_scoped_to_org(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
    test_org: Organization,
    db_session,
):
    """Documents from one org should not be visible to another org's user."""
    # Upload a document as test_user (in test_org)
    await _make_upload(client, auth_headers, title="Org 1 Doc")

    # Create a second org and add second_user to it
    org2 = Organization(name="Other Org")
    db_session.add(org2)
    await db_session.flush()

    from app.models.iam import OrganizationMember

    db_session.add(
        OrganizationMember(
            user_id=(await db_session.execute(
                __import__("sqlalchemy").select(User).where(
                    User.email == "second@example.com"
                )
            )).scalar_one().id,
            organization_id=org2.id,
            role="ADMIN",
        )
    )
    await db_session.flush()

    # List as second_user — should not see test_org's docs
    resp = await client.get(
        "/library/documents", headers=second_auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# --- Get Document Detail Tests ---


@pytest.mark.asyncio
async def test_get_document_detail_success(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    upload_resp = await _make_upload(client, auth_headers)
    doc_id = upload_resp.json()["id"]

    resp = await client.get(
        f"/library/documents/{doc_id}", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == doc_id
    assert body["title"] == "Test Document"
    assert "chunk_count" in body
    assert "chunks_preview" in body


@pytest.mark.asyncio
async def test_get_document_not_found_returns_404(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    import uuid

    fake_id = str(uuid.uuid4())
    resp = await client.get(
        f"/library/documents/{fake_id}", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_document_includes_chunk_count(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    upload_resp = await _make_upload(client, auth_headers)
    doc_id = upload_resp.json()["id"]

    resp = await client.get(
        f"/library/documents/{doc_id}", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["chunk_count"] == 0  # No processing yet (mocked)


# --- Delete Tests ---


@pytest.mark.asyncio
async def test_delete_document_returns_204(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    upload_resp = await _make_upload(client, auth_headers)
    doc_id = upload_resp.json()["id"]

    resp = await client.delete(
        f"/library/documents/{doc_id}", headers=auth_headers
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_document_removes_file(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    import os

    upload_resp = await _make_upload(client, auth_headers)
    body = upload_resp.json()
    doc_id = body["id"]
    file_path = body["file_path"]

    assert os.path.exists(file_path)

    resp = await client.delete(
        f"/library/documents/{doc_id}", headers=auth_headers
    )
    assert resp.status_code == 204
    assert not os.path.exists(file_path)


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_404(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    import uuid

    fake_id = str(uuid.uuid4())
    resp = await client.delete(
        f"/library/documents/{fake_id}", headers=auth_headers
    )
    assert resp.status_code == 404


# --- Retry Tests ---


@pytest.mark.asyncio
async def test_retry_failed_document_resets_status(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session,
):
    upload_resp = await _make_upload(client, auth_headers)
    doc_id = upload_resp.json()["id"]

    # Manually set to FAILED
    from sqlalchemy import select, update

    await db_session.execute(
        update(Document)
        .where(Document.id == doc_id)
        .values(
            status=DocumentStatus.FAILED.value,
            error_message="test error",
        )
    )
    await db_session.flush()

    resp = await client.post(
        f"/library/documents/{doc_id}/retry", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UPLOADED"
    assert body["error_message"] is None


@pytest.mark.asyncio
async def test_retry_non_failed_document_returns_409(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    upload_resp = await _make_upload(client, auth_headers)
    doc_id = upload_resp.json()["id"]

    resp = await client.post(
        f"/library/documents/{doc_id}/retry", headers=auth_headers
    )
    assert resp.status_code == 409


# --- Security Tests ---


@pytest.mark.asyncio
async def test_upload_rejects_spoofed_mime_type(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    """Send .txt content with application/pdf header — should fail magic check."""
    resp = await _make_upload(
        client,
        auth_headers,
        content=b"This is plain text, not a PDF",
        filename="report.pdf",
        mime_type="application/pdf",
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_rejects_path_traversal_filename(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    """Path traversal in filename should be sanitized."""
    resp = await _make_upload(
        client,
        auth_headers,
        filename="../../../etc/passwd",
        mime_type="text/plain",
    )
    # Should succeed but the filename should be sanitized
    assert resp.status_code == 201
    body = resp.json()
    assert ".." not in body["original_filename"]
    assert "/" not in body["original_filename"]


# --- URL Import Tests ---


@pytest.mark.asyncio
async def test_import_from_url_success(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = "<html><title>Test Page</title><body><p>Hello world content</p></body></html>"
    mock_response.content = mock_response.text.encode()
    mock_response.raise_for_status = lambda: None

    with patch(
        "app.services.protocols.url_importer.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with patch(
            "app.services.protocols.url_importer.check_robots_txt",
            return_value=True,
        ):
            with patch(
                "app.services.protocols.url_importer.is_private_ip",
                return_value=False,
            ):
                resp = await client.post(
                    "/library/documents/from-url",
                    json={
                        "url": "https://example.com/article",
                        "title": "My Article",
                    },
                    headers=auth_headers,
                )

    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "My Article"
    assert body["source_url"] == "https://example.com/article"


@pytest.mark.asyncio
async def test_import_from_url_rejects_private_ip(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    with patch(
        "app.services.protocols.url_importer.is_private_ip", return_value=True
    ):
        resp = await client.post(
            "/library/documents/from-url",
            json={"url": "http://127.0.0.1/secret"},
            headers=auth_headers,
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_from_url_rejects_non_http_scheme(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    resp = await client.post(
        "/library/documents/from-url",
        json={"url": "file:///etc/passwd"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_from_url_respects_robots_txt(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    with patch(
        "app.services.protocols.url_importer.is_private_ip", return_value=False
    ):
        with patch(
            "app.services.protocols.url_importer.check_robots_txt",
            return_value=False,
        ):
            resp = await client.post(
                "/library/documents/from-url",
                json={"url": "https://example.com/blocked"},
                headers=auth_headers,
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_import_from_url_stores_source_url(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = "<html><title>Test</title><body><p>Content</p></body></html>"
    mock_response.content = mock_response.text.encode()
    mock_response.raise_for_status = lambda: None

    with patch(
        "app.services.protocols.url_importer.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with patch(
            "app.services.protocols.url_importer.check_robots_txt",
            return_value=True,
        ):
            with patch(
                "app.services.protocols.url_importer.is_private_ip",
                return_value=False,
            ):
                resp = await client.post(
                    "/library/documents/from-url",
                    json={"url": "https://example.com/page"},
                    headers=auth_headers,
                )

    assert resp.status_code == 201
    body = resp.json()
    assert body["source_url"] == "https://example.com/page"
