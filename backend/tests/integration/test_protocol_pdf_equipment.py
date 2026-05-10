"""Integration test: equipment interpolation + X-Unresolved-Placeholders header."""

from unittest.mock import patch

import pytest

from app.models.science import Equipment, Protocol
from app.models.templates import DocumentTemplate


@pytest.fixture
def fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4 fake"


async def _make_template(db_session, org_id) -> DocumentTemplate:
    tpl = DocumentTemplate(
        name="SOP Test",
        template_type="SOP",
        file_path="fake/path.docx",
        original_filename="path.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size_bytes=0,
        org_id=org_id,
        is_system=False,
        is_default=False,
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def _make_protocol(db_session, project_id, sop_tpl_id, graph) -> Protocol:
    proto = Protocol(
        name="Test Protocol",
        description="desc",
        project_id=project_id,
        version_number=1,
        graph=graph,
        sop_template_id=sop_tpl_id,
    )
    db_session.add(proto)
    await db_session.flush()
    return proto


async def test_pdf_endpoint_attaches_unresolved_header(
    client, db_session, test_user, test_org, test_project, auth_headers, fake_pdf_bytes
):
    """Endpoint surfaces unresolved {{<id>_name}} via X-Unresolved-Placeholders."""
    tpl = await _make_template(db_session, test_org.id)
    eq = Equipment(
        organization_id=test_org.id,
        name="Bioreactor A",
        description="5L stirred tank",
    )
    db_session.add(eq)
    await db_session.flush()

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "label": "Step One",
                    "description": "Use {{E-001_name}} and {{E-999_name}}",
                    "equipment": [{"local_id": "E-001", "equipment_id": str(eq.id)}],
                },
            },
        ],
        "edges": [],
    }
    proto = await _make_protocol(db_session, test_project.id, tpl.id, graph)

    with patch(
        "app.api.endpoints.protocol_pdfs._resolve_template_path",
        return_value="/tmp/fake.docx",
    ), patch(
        "app.api.endpoints.protocol_pdfs.render_to_pdf",
        return_value=fake_pdf_bytes,
    ):
        resp = await client.get(
            f"/science/protocols/{proto.id}/pdf/sop", headers=auth_headers
        )

    assert resp.status_code == 200
    assert "X-Unresolved-Placeholders" in resp.headers
    assert "E-999_name" in resp.headers["X-Unresolved-Placeholders"]
    assert "E-001_name" not in resp.headers["X-Unresolved-Placeholders"]


async def test_pdf_endpoint_no_header_when_all_resolved(
    client, db_session, test_user, test_org, test_project, auth_headers, fake_pdf_bytes
):
    """No X-Unresolved-Placeholders header when every token resolves."""
    tpl = await _make_template(db_session, test_org.id)
    eq = Equipment(
        organization_id=test_org.id,
        name="Bioreactor A",
        description="5L",
    )
    db_session.add(eq)
    await db_session.flush()

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "label": "Step One",
                    "description": "Use {{E-001_name}}",
                    "equipment": [{"local_id": "E-001", "equipment_id": str(eq.id)}],
                },
            },
        ],
        "edges": [],
    }
    proto = await _make_protocol(db_session, test_project.id, tpl.id, graph)

    with patch(
        "app.api.endpoints.protocol_pdfs._resolve_template_path",
        return_value="/tmp/fake.docx",
    ), patch(
        "app.api.endpoints.protocol_pdfs.render_to_pdf",
        return_value=fake_pdf_bytes,
    ):
        resp = await client.get(
            f"/science/protocols/{proto.id}/pdf/sop", headers=auth_headers
        )

    assert resp.status_code == 200
    assert "X-Unresolved-Placeholders" not in resp.headers
