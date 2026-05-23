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
