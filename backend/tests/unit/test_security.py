import uuid
from datetime import timedelta

import pytest

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
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
