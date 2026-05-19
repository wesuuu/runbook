"""Settings exposure for the external_protocols feature flag (F-0084, F-0090)."""

from app.core.config import Settings


def test_external_protocols_default_off_with_defaults():
    s = Settings()
    assert s.features.external_protocols.enabled is False
    # OpenWetWare sub-block — default-on so F-0084 deployments keep working.
    assert s.features.external_protocols.openwetware.enabled is True
    assert s.features.external_protocols.openwetware.request_timeout_seconds == 10.0
    assert s.features.external_protocols.openwetware.rate_limit_per_minute == 10
    # protocols.io sub-block — opt-in, no token by default.
    assert s.features.external_protocols.protocols_io.enabled is False
    assert s.features.external_protocols.protocols_io.access_token == ""
    assert s.features.external_protocols.protocols_io.request_timeout_seconds == 10.0
    assert s.features.external_protocols.protocols_io.rate_limit_per_minute == 10


def test_external_protocols_env_override(monkeypatch):
    monkeypatch.setenv("BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED", "true")
    monkeypatch.setenv(
        "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__OPENWETWARE__RATE_LIMIT_PER_MINUTE",
        "3",
    )
    monkeypatch.setenv(
        "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ENABLED", "true"
    )
    monkeypatch.setenv(
        "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN", "tok-123"
    )
    s = Settings()
    assert s.features.external_protocols.enabled is True
    assert s.features.external_protocols.openwetware.rate_limit_per_minute == 3
    assert s.features.external_protocols.protocols_io.enabled is True
    assert s.features.external_protocols.protocols_io.access_token == "tok-123"
