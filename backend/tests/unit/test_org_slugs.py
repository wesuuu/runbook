"""Unit tests for org-slug disambiguation helpers."""

from uuid import UUID, uuid4

from app.services.core.org_slugs import disambiguate_org_slugs


def test_empty_input_returns_empty_dict():
    assert disambiguate_org_slugs([]) == {}


def test_single_org_returns_plain_slug():
    oid = uuid4()
    out = disambiguate_org_slugs([(oid, "Acme Bio")])
    assert out == {oid: "acme-bio"}


def test_colliding_slugs_get_id_prefix_suffix():
    a = uuid4()
    b = uuid4()
    out = disambiguate_org_slugs([(a, "Acme"), (b, "Acme")])
    assert out[a] == f"acme-{str(a)[:8]}"
    assert out[b] == f"acme-{str(b)[:8]}"


def test_non_colliding_slugs_stay_plain_even_with_others_in_set():
    a = uuid4()
    b = uuid4()
    c = uuid4()
    out = disambiguate_org_slugs([(a, "Acme"), (b, "Acme"), (c, "Initech")])
    assert out[a].startswith("acme-")
    assert out[b].startswith("acme-")
    assert out[c] == "initech"


def test_no_alphanumeric_name_returns_empty_slug():
    oid = uuid4()
    out = disambiguate_org_slugs([(oid, "---")])
    assert out[oid] == ""


def test_no_alphanumeric_punctuation_returns_empty_slug():
    oid = uuid4()
    out = disambiguate_org_slugs([(oid, "!!!")])
    assert out[oid] == ""


def test_two_blank_orgs_collide_to_blank_not_suffixed():
    """Both orgs slugify to '' — implementation must not produce
    f'-{prefix}' (hyphen-leading) for them. They stay blank and the
    URL caller degrades. Regression for an adversarial-review finding."""
    a = uuid4()
    b = uuid4()
    out = disambiguate_org_slugs([(a, "---"), (b, "---")])
    assert out[a] == ""
    assert out[b] == ""


# ---------------------------------------------------------------------------
# DB-backed async tests for disambiguated_org_slug_for_user
# ---------------------------------------------------------------------------

import pytest

from app.models.iam import Organization, OrganizationMember
from app.services.core.org_slugs import disambiguated_org_slug_for_user


async def _add_org(db, name: str) -> Organization:
    org = Organization(name=name)
    db.add(org)
    await db.flush()
    return org


async def _add_member(db, user_id, org_id):
    db.add(OrganizationMember(user_id=user_id, organization_id=org_id))
    await db.flush()


async def test_user_in_one_org_returns_slug(db_session, test_user):
    org = await _add_org(db_session, "Plain Lab")
    await _add_member(db_session, test_user.id, org.id)
    assert (
        await disambiguated_org_slug_for_user(db_session, test_user.id, org.id)
        == "plain-lab"
    )


async def test_user_in_colliding_orgs_returns_suffixed_slug(db_session, test_user):
    org_a = await _add_org(db_session, "Acme")
    org_b = await _add_org(db_session, "Acme")
    await _add_member(db_session, test_user.id, org_a.id)
    await _add_member(db_session, test_user.id, org_b.id)

    slug_a = await disambiguated_org_slug_for_user(db_session, test_user.id, org_a.id)
    slug_b = await disambiguated_org_slug_for_user(db_session, test_user.id, org_b.id)

    assert slug_a == f"acme-{str(org_a.id)[:8]}"
    assert slug_b == f"acme-{str(org_b.id)[:8]}"


async def test_user_not_a_member_returns_none(db_session, test_user):
    org = await _add_org(db_session, "Outside Lab")
    # No membership row inserted.
    assert (
        await disambiguated_org_slug_for_user(db_session, test_user.id, org.id)
        is None
    )


async def test_blank_slug_returns_none(db_session, test_user):
    org = await _add_org(db_session, "---")
    await _add_member(db_session, test_user.id, org.id)
    assert (
        await disambiguated_org_slug_for_user(db_session, test_user.id, org.id)
        is None
    )
