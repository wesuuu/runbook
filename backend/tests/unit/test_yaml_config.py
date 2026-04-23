"""Unit tests for YamlConfigSettingsSource (isolated from Settings wiring)."""

import os
from pathlib import Path

import pytest
import yaml

from app.core.yaml_source import YamlConfigSettingsSource, _resolve_yaml_path


class _Dummy:
    """Stand-in settings_cls. YamlConfigSettingsSource calls __call__ only."""

    model_fields: dict = {}
    model_config: dict = {}


def test_returns_empty_dict_when_no_path_resolved(monkeypatch, tmp_path):
    monkeypatch.delenv("BATCHRITE_SETTINGS_FILE", raising=False)
    monkeypatch.setattr("app.core.yaml_source._resolve_yaml_path", lambda: None)
    source = YamlConfigSettingsSource(_Dummy)
    assert source() == {}


def test_returns_empty_dict_when_file_is_empty(tmp_path, monkeypatch):
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(empty))
    source = YamlConfigSettingsSource(_Dummy)
    assert source() == {}


def test_parses_flat_keys(tmp_path, monkeypatch):
    f = tmp_path / "s.yaml"
    f.write_text("auth_enabled: false\ndebug: true\n")
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    source = YamlConfigSettingsSource(_Dummy)
    assert source() == {"auth_enabled": False, "debug": True}


def test_parses_nested_provider_config(tmp_path, monkeypatch):
    f = tmp_path / "s.yaml"
    f.write_text(
        "openrouter:\n"
        "  api_key: sk-or-xyz\n"
        "  base_url: https://openrouter.ai/api/v1\n"
    )
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    source = YamlConfigSettingsSource(_Dummy)
    assert source() == {
        "openrouter": {
            "api_key": "sk-or-xyz",
            "base_url": "https://openrouter.ai/api/v1",
        }
    }


def test_explicit_missing_file_raises(tmp_path, monkeypatch):
    missing = tmp_path / "does-not-exist.yaml"
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(missing))
    with pytest.raises(FileNotFoundError):
        YamlConfigSettingsSource(_Dummy)


def test_malformed_yaml_raises(tmp_path, monkeypatch):
    f = tmp_path / "bad.yaml"
    f.write_text(": : :\n")
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    with pytest.raises(yaml.YAMLError):
        YamlConfigSettingsSource(_Dummy)


def test_resolve_path_prefers_env_var(tmp_path, monkeypatch):
    f = tmp_path / "s.yaml"
    f.write_text("auth_enabled: true\n")
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    assert _resolve_yaml_path() == f


def test_resolve_path_raises_for_explicit_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(tmp_path / "nope.yaml"))
    with pytest.raises(FileNotFoundError):
        _resolve_yaml_path()


def test_resolve_path_returns_none_when_default_missing(monkeypatch):
    monkeypatch.delenv("BATCHRITE_SETTINGS_FILE", raising=False)
    # Point the default resolver at a definitely-missing location.
    monkeypatch.setattr(
        "app.core.yaml_source._DEFAULT_YAML_PATH",
        Path("/nonexistent/batchrite/settings.yaml"),
    )
    assert _resolve_yaml_path() is None


# --- Integration tests: Settings() with the YAML source wired in ---

from app.core.config import Settings


def _isolate_env(monkeypatch):
    """Clear BATCHRITE_* env vars that could leak in from the host."""
    for key in list(os.environ):
        if key.startswith("BATCHRITE_"):
            monkeypatch.delenv(key, raising=False)


def test_yaml_overrides_defaults(tmp_path, monkeypatch):
    _isolate_env(monkeypatch)
    f = tmp_path / "s.yaml"
    f.write_text(
        "database_url: postgresql+asyncpg://u:p@host:5432/db\n" "auth_enabled: false\n"
    )
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"
    assert s.auth_enabled is False


def test_env_vars_override_yaml(tmp_path, monkeypatch):
    _isolate_env(monkeypatch)
    f = tmp_path / "s.yaml"
    f.write_text("auth_enabled: false\n")
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    monkeypatch.setenv("BATCHRITE_AUTH_ENABLED", "true")
    s = Settings(_env_file=None)
    assert s.auth_enabled is True


def test_yaml_loads_nested_provider_config(tmp_path, monkeypatch):
    _isolate_env(monkeypatch)
    f = tmp_path / "s.yaml"
    f.write_text(
        "openrouter:\n"
        "  api_key: sk-or-xyz\n"
        "  base_url: https://openrouter.ai/api/v1\n"
    )
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    s = Settings(_env_file=None)
    assert s.openrouter.api_key == "sk-or-xyz"
    assert s.openrouter.base_url == "https://openrouter.ai/api/v1"


def test_no_yaml_falls_through_to_defaults(monkeypatch):
    _isolate_env(monkeypatch)
    monkeypatch.setattr(
        "app.core.yaml_source._DEFAULT_YAML_PATH",
        Path("/nonexistent/batchrite/settings.yaml"),
    )
    s = Settings(_env_file=None)
    assert s.jwt_algorithm == "HS256"
    assert s.auth_enabled is True


def test_unknown_yaml_keys_are_ignored(tmp_path, monkeypatch):
    _isolate_env(monkeypatch)
    f = tmp_path / "s.yaml"
    f.write_text("not_a_real_field: 42\nauth_enabled: false\n")
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    s = Settings(_env_file=None)
    assert s.auth_enabled is False
    assert not hasattr(s, "not_a_real_field")
