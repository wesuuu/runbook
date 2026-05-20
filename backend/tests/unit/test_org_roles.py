from app.models.iam import _ALLOWED_ORG_ROLES, OrgRole
from app.schemas.iam import _LEGACY_ROLE_RANK


def test_site_manager_in_enum():
    assert OrgRole.SITE_MANAGER.value == "SITE_MANAGER"


def test_site_manager_allowed():
    assert "SITE_MANAGER" in _ALLOWED_ORG_ROLES


def test_site_manager_legacy_rank():
    assert _LEGACY_ROLE_RANK["SITE_MANAGER"] == 2
    # Same rank as PROTOCOL_APPROVER; ADMIN still highest.
    assert _LEGACY_ROLE_RANK["ADMIN"] > _LEGACY_ROLE_RANK["SITE_MANAGER"]
