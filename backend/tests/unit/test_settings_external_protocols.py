"""Settings exposure for the external_protocols feature flag."""

from app.core.config import Settings


def test_external_protocols_default_off_with_defaults():
    s = Settings()
    assert s.features.external_protocols.enabled is False
    assert s.features.external_protocols.request_timeout_seconds == 10.0
    assert s.features.external_protocols.rate_limit_per_minute == 10


def test_external_protocols_env_override(monkeypatch):
    monkeypatch.setenv("BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED", "true")
    monkeypatch.setenv(
        "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__RATE_LIMIT_PER_MINUTE", "3"
    )
    s = Settings()
    assert s.features.external_protocols.enabled is True
    assert s.features.external_protocols.rate_limit_per_minute == 3
    assert s.features.external_protocols.request_timeout_seconds == 10.0
