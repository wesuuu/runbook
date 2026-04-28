import pytest

from app.legal import service as legal_service
from app.legal.versions import ALL_VERSIONS, CURRENT_VERSION


def test_current_version_is_in_all_versions():
    assert CURRENT_VERSION in ALL_VERSIONS


def test_get_current_version_returns_constant():
    assert legal_service.get_current_version() == CURRENT_VERSION


def test_list_versions_returns_all_versions():
    assert legal_service.list_versions() == list(ALL_VERSIONS)


def test_get_document_returns_terms_for_current_version():
    doc = legal_service.get_document(CURRENT_VERSION, "terms")
    assert doc["version"] == CURRENT_VERSION
    assert doc["effective_date"] == CURRENT_VERSION
    assert isinstance(doc["markdown"], str)
    assert len(doc["markdown"]) > 0


def test_get_document_returns_privacy_for_current_version():
    doc = legal_service.get_document(CURRENT_VERSION, "privacy")
    assert doc["version"] == CURRENT_VERSION
    assert doc["effective_date"] == CURRENT_VERSION
    assert isinstance(doc["markdown"], str)
    assert len(doc["markdown"]) > 0


def test_get_document_unknown_version_raises_key_error():
    with pytest.raises(KeyError):
        legal_service.get_document("does-not-exist", "terms")


def test_get_document_unknown_doc_type_raises_value_error():
    with pytest.raises(ValueError):
        legal_service.get_document(CURRENT_VERSION, "bogus-doc")
