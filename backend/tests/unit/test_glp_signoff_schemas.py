from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.science import (GlpSignoffCreate, GlpSignoffResponse,
                                 RunCompleteRequest, RunReopenRequest)


def test_signoff_create_validates_role():
    payload = GlpSignoffCreate(
        role="QAU", action="APPROVED", attestation="x", signature_image_path="p.png"
    )
    assert payload.role == "QAU"
    with pytest.raises(ValueError):
        GlpSignoffCreate(role="ADMIN", action="APPROVED")


def test_signoff_create_validates_action():
    with pytest.raises(ValueError):
        GlpSignoffCreate(role="QAU", action="MAYBE")


def test_signoff_response_from_attributes():
    class FakeOrm:
        id = uuid4()
        protocol_id = None
        run_id = uuid4()
        role = "OPERATOR"
        action = "APPROVED"
        signer_id = uuid4()
        attestation = "x"
        signed_at = datetime.now(timezone.utc)
        signature_image_path = "p.png"
        signoff_request_id = None
        invalidated_at = None
        invalidated_reason = None
        invalidated_by_id = None
        created_at = datetime.now(timezone.utc)
        updated_at = datetime.now(timezone.utc)

    resp = GlpSignoffResponse.model_validate(FakeOrm())
    assert resp.role == "OPERATOR"


def test_run_complete_validates_outcome():
    req = RunCompleteRequest(outcome="COMPLETED_NORMAL")
    assert req.outcome == "COMPLETED_NORMAL"
    with pytest.raises(ValueError):
        RunCompleteRequest(outcome="DONE")


def test_run_reopen_requires_reason():
    with pytest.raises(ValueError):
        RunReopenRequest(reason="")
