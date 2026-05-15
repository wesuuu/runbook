import io
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient

# Reuses the conftest fixtures used by test_library_api.py
pytestmark = pytest.mark.asyncio


_PDF_MAGIC = b"%PDF-1.4\n%minimal\n"


async def _upload(client: AsyncClient, headers, content=_PDF_MAGIC):
    files = {"file": ("test.pdf", io.BytesIO(content), "application/pdf")}
    data = {"title": "Test Doc"}
    return await client.post(
        "/library/documents", files=files, data=data, headers=headers
    )


async def test_upload_rejects_text_plain(client: AsyncClient, auth_headers):
    files = {"file": ("x.txt", io.BytesIO(b"hi"), "text/plain")}
    data = {"title": "T"}
    resp = await client.post(
        "/library/documents", files=files, data=data, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_upload_calls_background_handler(
    client: AsyncClient, auth_headers
):
    launched: list = []

    class _FakeHandler:
        async def launch(self, job, **kwargs):
            launched.append((job, kwargs))

    with patch(
        "app.api.endpoints.library.get_background_handler",
        return_value=_FakeHandler(),
    ):
        resp = await _upload(client, auth_headers)

    assert resp.status_code == 201
    assert len(launched) == 1
    job, kwargs = launched[0]
    assert job == "document_extract"
    assert isinstance(kwargs["document_id"], UUID)


async def test_get_markdown_404_until_extracted(
    client: AsyncClient, auth_headers, fresh_document
):
    # `fresh_document` fixture inserts a Document row with no
    # stored_markdown
    resp = await client.get(
        f"/library/documents/{fresh_document.id}/markdown",
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_put_markdown_saves_and_marks_in_progress(
    client: AsyncClient, auth_headers, extracted_document
):
    new_md = "# New title\n\nFresh body."
    resp = await client.put(
        f"/library/documents/{extracted_document.id}/markdown",
        json={"markdown": new_md},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["refinement_status"] == "IN_PROGRESS"


async def test_refine_complete_transitions_to_indexing(
    client: AsyncClient, auth_headers, extracted_document
):
    """POST /refine/complete returns INDEXING immediately and queues the
    document_index background job (TD-0085 Phase 3 — indexing is no
    longer inline)."""
    launched: list = []

    class _FakeHandler:
        async def launch(self, job, **kwargs):
            launched.append((job, kwargs))

    with patch(
        "app.api.endpoints.library.get_background_handler",
        return_value=_FakeHandler(),
    ):
        resp = await client.post(
            f"/library/documents/{extracted_document.id}/refine/complete",
            json={},
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "INDEXING"
    assert launched == [
        ("document_index", {"document_id": extracted_document.id})
    ]


async def test_refine_complete_twice_returns_409(
    client: AsyncClient, auth_headers, extracted_document
):
    """Second refine/complete on an already-completed doc must be
    rejected with 409 — not silently re-launch the index job."""
    launched: list = []

    class _FakeHandler:
        async def launch(self, job, **kwargs):
            launched.append((job, kwargs))

    with patch(
        "app.api.endpoints.library.get_background_handler",
        return_value=_FakeHandler(),
    ):
        first = await client.post(
            f"/library/documents/{extracted_document.id}/refine/complete",
            json={},
            headers=auth_headers,
        )
        assert first.status_code == 200

        second = await client.post(
            f"/library/documents/{extracted_document.id}/refine/complete",
            json={},
            headers=auth_headers,
        )

    assert second.status_code == 409
    # Only the first call should have queued a job.
    assert len(launched) == 1


async def test_refine_complete_reopen_resets_to_awaiting_refinement(
    client: AsyncClient, auth_headers, extracted_document
):
    """reopen=True on a COMPLETE doc flips it back to AWAITING_REFINEMENT
    without launching a new index job."""
    launched: list = []

    class _FakeHandler:
        async def launch(self, job, **kwargs):
            launched.append((job, kwargs))

    with patch(
        "app.api.endpoints.library.get_background_handler",
        return_value=_FakeHandler(),
    ):
        # First complete it
        complete_resp = await client.post(
            f"/library/documents/{extracted_document.id}/refine/complete",
            json={},
            headers=auth_headers,
        )
        assert complete_resp.status_code == 200
        assert complete_resp.json()["status"] == "INDEXING"

        # Now reopen
        reopen_resp = await client.post(
            f"/library/documents/{extracted_document.id}/refine/complete",
            json={"reopen": True},
            headers=auth_headers,
        )

    assert reopen_resp.status_code == 200, reopen_resp.text
    body = reopen_resp.json()
    assert body["status"] == "AWAITING_REFINEMENT"
    assert body["refinement_status"] == "IN_PROGRESS"
    # Reopen must NOT queue another index job.
    assert len(launched) == 1


async def test_refine_complete_reopen_on_non_complete_returns_409(
    client: AsyncClient, auth_headers, extracted_document
):
    """reopen=True on a doc that was never completed must 409."""
    class _FakeHandler:
        async def launch(self, job, **kwargs):
            pass

    with patch(
        "app.api.endpoints.library.get_background_handler",
        return_value=_FakeHandler(),
    ):
        resp = await client.post(
            f"/library/documents/{extracted_document.id}/refine/complete",
            json={"reopen": True},
            headers=auth_headers,
        )

    assert resp.status_code == 409


