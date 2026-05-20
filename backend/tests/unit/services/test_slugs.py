"""Tests for the assign_slug DB uniqueness helper."""

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.models.iam import Organization
from app.models.projects import Project
from app.services.slugs import assign_slug, assign_slug_or_422

# ---------------------------------------------------------------------------
# Local fixtures — inline org/project factories scoped to this test module.
# We don't use `test_org` / `test_project` from conftest because those are
# shared singletons; these tests need independent orgs to test cross-scope
# isolation.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def org_factory(db_session):
    """Return an async callable that creates a fresh Organization."""

    async def _make(**kwargs):
        org = Organization(name=kwargs.get("name", f"org-{uuid.uuid4().hex[:8]}"))
        db_session.add(org)
        await db_session.flush()
        return org

    return _make


@pytest_asyncio.fixture
async def project_factory(db_session):
    """Return an async callable that creates a minimal Project row."""

    async def _make(*, organization_id, name, slug, **kwargs):
        proj = Project(
            name=name,
            slug=slug,
            organization_id=organization_id,
            settings={},
        )
        for k, v in kwargs.items():
            setattr(proj, k, v)
        db_session.add(proj)
        await db_session.flush()
        return proj

    return _make


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_slug_returns_slugified_name(db_session, org_factory):
    org = await org_factory()
    slug = await assign_slug(
        db_session, Project, Project.organization_id, org.id, "Buffer Prep"
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_raises_on_collision(
    db_session, org_factory, project_factory
):
    org = await org_factory()
    await project_factory(
        organization_id=org.id, name="Buffer Prep", slug="buffer-prep"
    )
    with pytest.raises(ValueError, match="SLUG_CONFLICT"):
        await assign_slug(
            db_session, Project, Project.organization_id, org.id, "buffer prep"
        )


@pytest.mark.asyncio
async def test_assign_slug_allows_same_name_in_a_different_scope(
    db_session, org_factory, project_factory
):
    org_a = await org_factory()
    org_b = await org_factory()
    await project_factory(
        organization_id=org_a.id, name="Buffer Prep", slug="buffer-prep"
    )
    slug = await assign_slug(
        db_session, Project, Project.organization_id, org_b.id, "Buffer Prep"
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_excludes_self_on_rename(
    db_session, org_factory, project_factory
):
    org = await org_factory()
    proj = await project_factory(
        organization_id=org.id, name="Buffer Prep", slug="buffer-prep"
    )
    # Renaming to a slug it already owns must not raise.
    slug = await assign_slug(
        db_session,
        Project,
        Project.organization_id,
        org.id,
        "Buffer Prep",
        exclude_id=proj.id,
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_falls_back_for_degenerate_name(db_session, org_factory):
    org = await org_factory()
    slug = await assign_slug(
        db_session, Project, Project.organization_id, org.id, "🎉🎉"
    )
    assert slug.startswith("untitled-")


@pytest.mark.asyncio
async def test_assign_slug_or_422_returns_slug_on_success(db_session, org_factory):
    org = await org_factory()
    slug = await assign_slug_or_422(
        db_session,
        Project,
        Project.organization_id,
        org.id,
        "Buffer Prep",
        "project",
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_or_422_raises_http_422_on_collision(
    db_session, org_factory, project_factory
):
    org = await org_factory()
    await project_factory(
        organization_id=org.id, name="Buffer Prep", slug="buffer-prep"
    )
    with pytest.raises(HTTPException) as exc_info:
        await assign_slug_or_422(
            db_session,
            Project,
            Project.organization_id,
            org.id,
            "buffer prep",
            "project",
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "SLUG_CONFLICT"
