"""Unit tests for notification deep-link URL resolution."""

from uuid import uuid4

from app.models.notifications import Notification
from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.runs import Experiment, Run
from app.services.core.notifications.links import resolve_notification_urls


async def _notif(db, user_id, entity_type, entity_id):
    """Create + flush a Notification so it has a real id."""
    n = Notification(
        user_id=user_id,
        event_type="RUN_STARTED",
        entity_type=entity_type,
        entity_id=entity_id,
        title="t",
        message="m",
    )
    db.add(n)
    await db.flush()
    return n


async def test_empty_input_returns_empty_map(db_session, test_user):
    assert await resolve_notification_urls(db_session, [], test_user.id) == {}


async def test_resolves_run_url(db_session, test_user, test_org, test_project):
    run = Run(name="CHO 42", slug="cho-42", project_id=test_project.id)
    db_session.add(run)
    await db_session.flush()
    n = await _notif(db_session, test_user.id, "run", run.id)

    urls = await resolve_notification_urls(db_session, [n], test_user.id)

    assert urls[n.id] == "/test-org/projects/test-project/runs/cho-42"


async def test_resolves_experiment_url(
    db_session, test_user, test_org, test_project
):
    exp = Experiment(name="Exp 1", slug="exp-1", project_id=test_project.id)
    db_session.add(exp)
    await db_session.flush()
    n = await _notif(db_session, test_user.id, "experiment", exp.id)

    urls = await resolve_notification_urls(db_session, [n], test_user.id)

    assert urls[n.id] == "/test-org/projects/test-project/experiments/exp-1"


async def test_resolves_protocol_url(db_session, test_user, test_org):
    proto = Protocol(
        name="Buffer Prep",
        slug="buffer-prep",
        owner_org_id=test_org.id,
        organization_id=test_org.id,
    )
    db_session.add(proto)
    await db_session.flush()
    n = await _notif(db_session, test_user.id, "protocol", proto.id)

    urls = await resolve_notification_urls(db_session, [n], test_user.id)

    assert urls[n.id] == "/test-org/protocols/buffer-prep"


async def test_resolves_project_url(db_session, test_user, test_project):
    n = await _notif(db_session, test_user.id, "project", test_project.id)

    urls = await resolve_notification_urls(db_session, [n], test_user.id)

    assert urls[n.id] == "/test-org/projects/test-project"


async def test_entity_type_is_case_insensitive(
    db_session, test_user, test_project
):
    run = Run(name="R", slug="r-1", project_id=test_project.id)
    db_session.add(run)
    await db_session.flush()
    n = await _notif(db_session, test_user.id, "Run", run.id)  # capital R

    urls = await resolve_notification_urls(db_session, [n], test_user.id)

    assert urls[n.id] == "/test-org/projects/test-project/runs/r-1"


async def test_non_routable_entity_type_resolves_to_none(
    db_session, test_user
):
    n = await _notif(
        db_session, test_user.id, "RevokedOfflineToken", uuid4()
    )

    urls = await resolve_notification_urls(db_session, [n], test_user.id)

    assert urls[n.id] is None


async def test_deleted_target_resolves_to_none(db_session, test_user):
    # Routable type, but no row with this id exists.
    n = await _notif(db_session, test_user.id, "run", uuid4())

    urls = await resolve_notification_urls(db_session, [n], test_user.id)

    assert urls[n.id] is None


async def test_target_in_non_member_org_resolves_to_none(
    db_session, test_user, second_org
):
    # A run in an org test_user does not belong to: a link would 403.
    other = Project(
        name="Other", slug="other-proj", organization_id=second_org.id
    )
    db_session.add(other)
    await db_session.flush()
    run = Run(name="R", slug="r-9", project_id=other.id)
    db_session.add(run)
    await db_session.flush()
    n = await _notif(db_session, test_user.id, "run", run.id)

    urls = await resolve_notification_urls(db_session, [n], test_user.id)

    assert urls[n.id] is None


async def test_disambiguates_colliding_org_slugs(db_session):
    """Two member orgs whose names slugify identically get id-suffixed."""
    from app.core.security import hash_password
    from app.models.iam import Organization, OrganizationMember, User

    org_a = Organization(name="Acme Bio")
    org_b = Organization(name="ACME  bio!")  # also slugifies to "acme-bio"
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    user = User(
        email="collide@example.com",
        hashed_password=hash_password("x"),
        full_name="Collide",
        selected_org_id=org_a.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add_all([
        OrganizationMember(
            user_id=user.id, organization_id=org_a.id, roles=["MEMBER"]
        ),
        OrganizationMember(
            user_id=user.id, organization_id=org_b.id, roles=["MEMBER"]
        ),
    ])
    proj = Project(name="P", slug="p-1", organization_id=org_a.id)
    db_session.add(proj)
    await db_session.flush()
    run = Run(name="R", slug="r-1", project_id=proj.id)
    db_session.add(run)
    await db_session.flush()
    n = await _notif(db_session, user.id, "run", run.id)

    urls = await resolve_notification_urls(db_session, [n], user.id)

    expected_slug = f"acme-bio-{str(org_a.id)[:8]}"
    assert urls[n.id] == f"/{expected_slug}/projects/p-1/runs/r-1"


async def test_batches_mixed_types_in_one_call(
    db_session, test_user, test_org, test_project
):
    run = Run(name="R", slug="r-2", project_id=test_project.id)
    proto = Protocol(
        name="Pr",
        slug="pr-2",
        owner_org_id=test_org.id,
        organization_id=test_org.id,
    )
    db_session.add_all([run, proto])
    await db_session.flush()
    n_run = await _notif(db_session, test_user.id, "run", run.id)
    n_proto = await _notif(db_session, test_user.id, "protocol", proto.id)
    n_bad = await _notif(db_session, test_user.id, "widget", uuid4())

    urls = await resolve_notification_urls(
        db_session, [n_run, n_proto, n_bad], test_user.id
    )

    assert urls[n_run.id] == "/test-org/projects/test-project/runs/r-2"
    assert urls[n_proto.id] == "/test-org/protocols/pr-2"
    assert urls[n_bad.id] is None
