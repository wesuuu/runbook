"""Tests for services/documents/retrieval.py — RAG against pgvector + keyword fallback."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization
from app.services.documents.retrieval import (
    RAG_MAX_CONTEXT_CHARS,
    RAG_MIN_SCORE,
    RAG_TOP_K,
    retrieve_relevant_chunks,
)


def test_constants_exist():
    assert isinstance(RAG_TOP_K, int)
    assert isinstance(RAG_MAX_CONTEXT_CHARS, int)
    assert isinstance(RAG_MIN_SCORE, float)


@pytest.mark.asyncio
async def test_returns_empty_when_no_documents(
    db_session: AsyncSession, test_org: Organization,
):
    result = await retrieve_relevant_chunks(
        db_session, query="anything", org_id=test_org.id,
    )
    assert result == []
