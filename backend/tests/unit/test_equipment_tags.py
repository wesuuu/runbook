import pytest

from app.services.equipment.tags import normalize_tag, normalize_tags


def test_normalize_tag_basic():
    assert normalize_tag(" High-Speed ") == "high-speed"


def test_normalize_tag_collapse_whitespace():
    assert normalize_tag("cell culture") == "cell-culture"


def test_normalize_tag_strip_disallowed():
    assert normalize_tag("GLP/QC") == "glp-qc"


def test_normalize_tag_truncates_to_40():
    out = normalize_tag("a" * 80)
    assert len(out) == 40


def test_normalize_tags_dedupes_and_caps_at_20():
    raw = ["GLP", "glp", " glp "] + [f"t{i}" for i in range(25)]
    out = normalize_tags(raw)
    assert out.count("glp") == 1
    assert len(out) <= 20


@pytest.mark.asyncio
async def test_list_distinct_tags(db_session, test_org, test_user, make_equipment):
    from app.schemas.sites import SiteCreate
    from app.services.equipment.tags import list_distinct_tags
    from app.services.sites import crud as sites_crud

    site = await sites_crud.create_site(
        db_session,
        org_id=test_org.id,
        payload=SiteCreate(name="Lab"),
        actor_id=test_user.id,
    )
    e1 = await make_equipment(site_id=site.id, name="A")
    e1.tags = ["alpha", "beta"]
    e2 = await make_equipment(site_id=site.id, name="B")
    e2.tags = ["beta", "gamma"]
    await db_session.commit()

    out = await list_distinct_tags(db_session, test_org.id)
    assert "alpha" in out
    assert "beta" in out
    assert "gamma" in out
