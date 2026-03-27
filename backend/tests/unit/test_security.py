import uuid
from datetime import timedelta

import pytest

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_verification_jwt,
    decode_access_token,
    generate_verification_token,
    TokenPayload,
)


def test_hash_verify_roundtrip():
    hashed = hash_password("mysecret")
    assert verify_password("mysecret", hashed) is True


def test_verify_wrong_password():
    hashed = hash_password("mysecret")
    assert verify_password("wrongpass", hashed) is False


def test_create_decode_token_roundtrip():
    uid = uuid.uuid4()
    token = create_access_token(uid)
    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded.user_id == uid
    assert decoded.org_id is None
    assert decoded.subscription_tier == "essentials"


def test_create_decode_token_with_org_context():
    uid = uuid.uuid4()
    org_id = uuid.uuid4()
    token = create_access_token(uid, org_id=org_id, subscription_tier="pro")
    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded.user_id == uid
    assert decoded.org_id == org_id
    assert decoded.subscription_tier == "pro"


def test_decode_expired_token():
    from app.core import config
    original = config.settings.access_token_expire_minutes
    config.settings.access_token_expire_minutes = 0
    try:
        uid = uuid.uuid4()
        token = create_access_token(uid)
    finally:
        config.settings.access_token_expire_minutes = original

    # Create a truly expired token manually
    from jose import jwt
    from datetime import datetime, timezone
    payload = {
        "sub": str(uuid.uuid4()),
        "exp": datetime(2020, 1, 1, tzinfo=timezone.utc),
    }
    expired_token = jwt.encode(
        payload, config.settings.secret_key,
        algorithm=config.settings.jwt_algorithm,
    )
    assert decode_access_token(expired_token) is None


def test_decode_garbage_token():
    assert decode_access_token("not.a.real.token") is None
    assert decode_access_token("") is None
    assert decode_access_token("abc123") is None


# --- Email verification token tests ---


def test_generate_verification_token():
    """Token is URL-safe and long enough to be unguessable."""
    token = generate_verification_token()
    assert len(token) >= 43  # 32 bytes base64url = 43 chars
    assert isinstance(token, str)
    # URL-safe: no +, /, or = padding issues
    for ch in token:
        assert ch.isalnum() or ch in ("-", "_")


def test_generate_verification_token_uniqueness():
    """Two generated tokens should never be the same."""
    tokens = {generate_verification_token() for _ in range(100)}
    assert len(tokens) == 100


def test_verification_jwt_scope():
    """Verification JWT has scope=verification and no email_verified claim."""
    uid = uuid.uuid4()
    org_id = uuid.uuid4()
    token = create_verification_jwt(uid, org_id=org_id)
    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded.user_id == uid
    assert decoded.org_id == org_id
    assert decoded.scope == "verification"


def test_token_roundtrip_with_email_verified_true():
    """Access token with email_verified=True roundtrips correctly."""
    uid = uuid.uuid4()
    token = create_access_token(uid, email_verified=True)
    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded.email_verified is True
    assert decoded.scope is None


def test_token_roundtrip_with_email_verified_false():
    """Access token with email_verified=False roundtrips correctly."""
    uid = uuid.uuid4()
    token = create_access_token(uid, email_verified=False)
    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded.email_verified is False


def test_old_token_without_ev_defaults_to_verified():
    """Tokens created before email verification feature default to verified."""
    from jose import jwt as jose_jwt
    from datetime import datetime, timezone
    from app.core import config

    payload = {
        "sub": str(uuid.uuid4()),
        "exp": datetime(2030, 1, 1, tzinfo=timezone.utc),
    }
    old_token = jose_jwt.encode(
        payload, config.settings.secret_key,
        algorithm=config.settings.jwt_algorithm,
    )
    decoded = decode_access_token(old_token)
    assert decoded is not None
    assert decoded.email_verified is True
    assert decoded.scope is None
