"""Unit tests for offline token creation/decoding and value comparison."""

from uuid import uuid4, UUID

from app.core.security import (
    create_offline_token,
    decode_offline_token,
    decode_access_token,
    create_access_token,
)
from app.api.endpoints.sync import values_match


class TestOfflineToken:
    def test_create_returns_token_jti_expiry(self):
        user_id = uuid4()
        run_id = uuid4()
        token, jti, expires = create_offline_token(user_id, run_id)
        assert isinstance(token, str)
        assert isinstance(jti, str)
        assert len(jti) == 36  # UUID format
        assert expires is not None

    def test_decode_offline_token_success(self):
        user_id = uuid4()
        run_id = uuid4()
        token, jti, _ = create_offline_token(user_id, run_id)
        payload = decode_offline_token(token)
        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["run_id"] == str(run_id)
        assert payload["scope"] == "offline"
        assert payload["jti"] == jti

    def test_decode_offline_token_rejects_normal_token(self):
        user_id = uuid4()
        token = create_access_token(user_id)
        # Normal tokens don't have scope=offline
        payload = decode_offline_token(token)
        assert payload is None

    def test_decode_access_token_ignores_offline_scope(self):
        user_id = uuid4()
        run_id = uuid4()
        token, _, _ = create_offline_token(user_id, run_id)
        # decode_access_token should still return the user_id
        result = decode_access_token(token)
        assert result == user_id

    def test_decode_offline_token_rejects_garbage(self):
        assert decode_offline_token("not-a-token") is None

    def test_custom_expiry_days(self):
        token, _, expires = create_offline_token(uuid4(), uuid4(), days=1)
        payload = decode_offline_token(token)
        assert payload is not None


class TestValuesMatch:
    def test_exact_numeric_match(self):
        assert values_match(100, 100) is True

    def test_numeric_within_tolerance(self):
        # 5% of 1000 = 50, so 1050 is exactly at boundary
        assert values_match(1050, 1000) is True

    def test_numeric_outside_tolerance(self):
        # 6% off
        assert values_match(1060, 1000) is False

    def test_string_match_case_insensitive(self):
        assert values_match("Shake Flask", "shake flask") is True

    def test_string_mismatch(self):
        assert values_match("Flask", "Bioreactor") is False

    def test_none_values(self):
        assert values_match(None, None) is True
        assert values_match(None, 100) is False
        assert values_match(100, None) is False

    def test_zero_ai_value(self):
        assert values_match(0, 0) is True
        assert values_match(1, 0) is False
