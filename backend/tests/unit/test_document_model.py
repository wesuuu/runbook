from app.models.library import (
    ALLOWED_DOCUMENT_TYPES,
    Document,
    DocumentSourceFormat,
    DocumentStatus,
    RefinementStatus,
)


def test_new_status_values_present():
    values = {s.value for s in DocumentStatus}
    assert "EXTRACTING" in values
    assert "AWAITING_REFINEMENT" in values
    assert "INDEXING" in values
    # Legacy values preserved for backwards compatibility
    assert "INDEXED" in values
    assert "ENRICHED" in values


def test_source_format_enum():
    assert DocumentSourceFormat.PDF.value == "PDF"
    assert DocumentSourceFormat.DOCX.value == "DOCX"
    assert DocumentSourceFormat.IMAGE.value == "IMAGE"


def test_refinement_status_enum():
    values = {s.value for s in RefinementStatus}
    assert values == {
        "NOT_REQUIRED",
        "PENDING",
        "IN_PROGRESS",
        "COMPLETE",
    }


def test_document_has_new_columns():
    cols = {c.name for c in Document.__table__.columns}
    for expected in [
        "source_format",
        "stored_markdown",
        "images_dir",
        "refinement_status",
        "refinement_flags",
        "ocr_engine",
        "refined_by_id",
        "refined_at",
    ]:
        assert expected in cols, f"missing column: {expected}"


def test_allowed_document_types_phase1():
    # Only PDF, DOCX, and image MIMEs. Text/markdown/html/rtf removed.
    assert "application/pdf" in ALLOWED_DOCUMENT_TYPES
    assert (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        in ALLOWED_DOCUMENT_TYPES
    )
    assert "image/png" in ALLOWED_DOCUMENT_TYPES
    assert "image/jpeg" in ALLOWED_DOCUMENT_TYPES
    assert "image/tiff" in ALLOWED_DOCUMENT_TYPES
    assert "image/webp" in ALLOWED_DOCUMENT_TYPES
    assert "text/plain" not in ALLOWED_DOCUMENT_TYPES
    assert "text/markdown" not in ALLOWED_DOCUMENT_TYPES
    assert "text/html" not in ALLOWED_DOCUMENT_TYPES
    assert "application/rtf" not in ALLOWED_DOCUMENT_TYPES
