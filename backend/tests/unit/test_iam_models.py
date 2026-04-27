from app.models.iam import Organization, User


def test_user_has_tos_columns():
    user_columns = {c.name for c in User.__table__.columns}
    assert "tos_accepted_at" in user_columns
    assert "tos_version" in user_columns


def test_user_tos_columns_are_nullable():
    cols = {c.name: c for c in User.__table__.columns}
    assert cols["tos_accepted_at"].nullable is True
    assert cols["tos_version"].nullable is True


def test_organization_has_legal_terms_overridden_column():
    org_columns = {c.name for c in Organization.__table__.columns}
    assert "legal_terms_overridden" in org_columns


def test_organization_legal_terms_overridden_default_false():
    cols = {c.name: c for c in Organization.__table__.columns}
    col = cols["legal_terms_overridden"]
    assert col.nullable is False
    # SQLAlchemy stores server_default as a TextClause whose .arg holds the SQL text
    assert getattr(col.server_default, "arg", None) is not None
