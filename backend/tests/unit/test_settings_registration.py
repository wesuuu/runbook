"""F-0091: registration feature flag defaults and env override."""

import pytest

from app.core.config import RegistrationFeatureConfig, Settings


def test_registration_flag_defaults_on():
    cfg = RegistrationFeatureConfig()
    assert cfg.enabled is True


def test_registration_flag_present_on_settings():
    s = Settings()
    assert s.features.registration.enabled is True


def test_registration_flag_env_override_off(monkeypatch):
    monkeypatch.setenv("BATCHRITE_FEATURES__REGISTRATION__ENABLED", "false")
    s = Settings()
    assert s.features.registration.enabled is False
