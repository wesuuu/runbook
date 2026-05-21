"""F-0093 — org-wide GET /experiments index endpoint."""

import pytest

from app.models.projects import Project
from app.models.runs import Experiment, Run


async def _make_experiment(db, project_id, name, slug):
    exp = Experiment(name=name, slug=slug, project_id=project_id)
    db.add(exp)
    await db.flush()
    return exp


@pytest.mark.asyncio
async def test_lists_org_experiments_with_summary(
    client, auth_headers, db_session, test_project
):
    await _make_experiment(db_session, test_project.id, "Exp One", "exp-one")
    await db_session.commit()

    resp = await client.get("/experiments", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Exp One"
    assert row["project_name"] == test_project.name
    assert row["lifecycle_status"] == "DRAFT"
    assert row["run_count"] == 0
    assert row["run_summaries"] == []


@pytest.mark.asyncio
async def test_org_isolation(
    client, auth_headers, second_auth_headers, db_session,
    test_project, second_org,
):
    # An experiment in a different org must not appear for test_user.
    other_project = Project(
        name="Other", organization_id=second_org.id, slug="other-project",
        owner_type="USER",
    )
    db_session.add(other_project)
    await db_session.flush()
    await _make_experiment(db_session, other_project.id, "Hidden", "hidden")
    await _make_experiment(db_session, test_project.id, "Visible", "visible")
    await db_session.commit()

    rows = (await client.get("/experiments", headers=auth_headers)).json()
    names = {r["name"] for r in rows}
    assert "Visible" in names
    assert "Hidden" not in names


@pytest.mark.asyncio
async def test_lifecycle_status_correct_past_60_run_cap(
    client, auth_headers, db_session, test_project
):
    exp = await _make_experiment(db_session, test_project.id, "Big", "big")
    # 62 COMPLETED runs then 3 PLANNED runs — the open runs sit past the cap.
    for i in range(62):
        db_session.add(
            Run(
                name=f"r{i}", slug=f"big-r{i}", project_id=test_project.id,
                experiment_id=exp.id, status="COMPLETED",
            )
        )
    for i in range(3):
        db_session.add(
            Run(
                name=f"p{i}", slug=f"big-p{i}", project_id=test_project.id,
                experiment_id=exp.id, status="PLANNED",
            )
        )
    await db_session.commit()

    rows = (await client.get("/experiments", headers=auth_headers)).json()
    row = next(r for r in rows if r["name"] == "Big")
    assert row["run_count"] == 65
    assert len(row["run_summaries"]) == 60   # capped
    assert row["lifecycle_status"] == "IN_PROGRESS"  # derived from uncapped counts


@pytest.mark.asyncio
async def test_400_when_no_org_selected(client, db_session):
    from app.core.security import create_access_token
    from app.models.iam import User
    from app.core.security import hash_password

    orphan = User(
        email="orphan@example.com", hashed_password=hash_password("x"),
        full_name="Orphan", selected_org_id=None, email_verified=True,
    )
    db_session.add(orphan)
    await db_session.commit()
    token = create_access_token(
        orphan.id, org_id=None, subscription_tier="free", email_verified=True
    )
    resp = await client.get(
        "/experiments", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_permission_filters_restricted_projects(
    client, db_session, test_org,
):
    """A non-admin member sees only projects they can VIEW.

    Note: the `test_project` fixture is itself permissions-locked
    (`permissions_enabled=True` + an ADMIN grant for `test_user` only), so it
    is NOT a valid "visible" case for a plain member. This test creates its
    own genuinely-open project instead.
    """
    from app.core.security import create_access_token, hash_password
    from app.models.iam import OrganizationMember, User

    # An org-open project (permissions disabled) -> visible to every member.
    open_proj = Project(
        name="Open", organization_id=test_org.id, slug="open-proj",
        owner_type="USER", settings={"permissions_enabled": False},
    )
    # A permissions-locked project with no grant for the member -> hidden.
    locked = Project(
        name="Locked", organization_id=test_org.id, slug="locked",
        owner_type="USER", settings={"permissions_enabled": True},
    )
    db_session.add_all([open_proj, locked])
    await db_session.flush()
    await _make_experiment(db_session, open_proj.id, "Open Exp", "open-exp")
    await _make_experiment(db_session, locked.id, "Locked Exp", "locked-exp")

    member = User(
        email="member@example.com", hashed_password=hash_password("x"),
        full_name="Plain Member", selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(member)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=member.id, organization_id=test_org.id, roles=["MEMBER"]
        )
    )
    await db_session.commit()

    token = create_access_token(
        member.id, org_id=test_org.id, subscription_tier="free",
        email_verified=True,
    )
    rows = (
        await client.get(
            "/experiments", headers={"Authorization": f"Bearer {token}"}
        )
    ).json()
    names = {r["name"] for r in rows}
    assert "Open Exp" in names
    assert "Locked Exp" not in names
