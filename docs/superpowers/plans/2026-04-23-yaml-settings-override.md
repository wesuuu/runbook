# YAML Settings Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a YAML config file as a pydantic-settings source so operators can declare base configuration declaratively while env vars remain the override path for secrets and deploy-time tweaks.

**Architecture:** A new `YamlConfigSettingsSource` (subclass of `PydanticBaseSettingsSource`) is inserted into `Settings.settings_customise_sources` between `dotenv_settings` and `file_secret_settings`, making YAML override defaults but lose to env vars. File discovery: `BATCHRITE_SETTINGS_FILE` env var if set (must exist), else `backend/settings.yaml` if it exists, else no YAML source contributes.

**Tech Stack:** Python 3.13, pydantic v2, pydantic-settings v2, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-04-23-yaml-settings-override-design.md`

---

## File Structure

Files created:
- `backend/app/core/yaml_source.py` — `YamlConfigSettingsSource` class + `_resolve_yaml_path()` helper
- `backend/settings.example.yaml` — committed template documenting all fields
- `backend/tests/unit/test_yaml_config.py` — full test coverage

Files modified:
- `backend/app/core/config.py` — override `settings_customise_sources` to include the YAML source
- `backend/pyproject.toml` — add `pyyaml` dependency
- `.gitignore` — add `backend/settings.yaml`

---

### Task 1: Add pyyaml dependency

**Files:**
- Modify: `backend/pyproject.toml:8-30`

- [ ] **Step 1: Add pyyaml to the dependencies block**

Open `backend/pyproject.toml` and add `pyyaml = "^6.0"` to the `[tool.poetry.dependencies]` section, alphabetically near the bottom. After the edit, that block should include this new line alongside the existing ones:

```toml
pyyaml = "^6.0"
```

- [ ] **Step 2: Install the dependency**

Run from `backend/`:

```bash
cd backend && source .venv/bin/activate && poetry install --no-root
```

Expected: poetry installs `pyyaml` and regenerates `poetry.lock`.

- [ ] **Step 3: Verify import works**

Run from `backend/` with the venv active:

```bash
python -c "import yaml; print(yaml.__version__)"
```

Expected: prints a version string like `6.0.1` with no error.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/poetry.lock
git commit -m "chore(deps): add pyyaml for settings.yaml override support"
```

---

### Task 2: Update .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add settings.yaml to .gitignore**

Append this block to `.gitignore` (keep `settings.example.yaml` tracked — only the real `settings.yaml` is ignored):

```gitignore

# Operator-local settings override (do NOT commit; contains secrets)
backend/settings.yaml
```

- [ ] **Step 2: Verify the ignore rule works**

Run:

```bash
touch backend/settings.yaml && git check-ignore -v backend/settings.yaml && rm backend/settings.yaml
```

Expected: output shows `.gitignore:<line>:backend/settings.yaml	backend/settings.yaml`, confirming the rule matches.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore(gitignore): ignore backend/settings.yaml"
```

---

### Task 3: Implement `YamlConfigSettingsSource` (TDD)

**Files:**
- Create: `backend/app/core/yaml_source.py`
- Create: `backend/tests/unit/test_yaml_config.py`

This task tests the source in isolation. Settings-integration tests come in Task 4.

- [ ] **Step 1: Write the failing unit tests**

Create `backend/tests/unit/test_yaml_config.py`:

```python
"""Unit tests for YamlConfigSettingsSource (isolated from Settings wiring)."""
from pathlib import Path

import pytest
import yaml

from app.core.yaml_source import (
    YamlConfigSettingsSource,
    _resolve_yaml_path,
)


class _Dummy:
    """Stand-in settings_cls. YamlConfigSettingsSource calls __call__ only."""
    model_fields: dict = {}


def test_returns_empty_dict_when_no_path_resolved(monkeypatch, tmp_path):
    monkeypatch.delenv("BATCHRITE_SETTINGS_FILE", raising=False)
    monkeypatch.setattr(
        "app.core.yaml_source._resolve_yaml_path", lambda: None
    )
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
    monkeypatch.setenv(
        "BATCHRITE_SETTINGS_FILE", str(tmp_path / "nope.yaml")
    )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `backend/` with venv active:

```bash
pytest tests/unit/test_yaml_config.py -v
```

Expected: all tests FAIL with `ModuleNotFoundError: No module named 'app.core.yaml_source'`.

- [ ] **Step 3: Implement `YamlConfigSettingsSource`**

Create `backend/app/core/yaml_source.py`:

```python
"""YAML-backed pydantic-settings source.

Provides `YamlConfigSettingsSource`, a `PydanticBaseSettingsSource` that loads
settings values from a YAML file. Discovery:

1. If `BATCHRITE_SETTINGS_FILE` is set, load that path (must exist).
2. Else, if `backend/settings.yaml` exists, load it.
3. Else, contribute nothing.

Precedence is controlled by `Settings.settings_customise_sources` — see
`app.core.config`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic.fields import FieldInfo
from pydantic_settings import PydanticBaseSettingsSource

_SETTINGS_FILE_ENV_VAR = "BATCHRITE_SETTINGS_FILE"

# Resolves to `backend/settings.yaml` — this file lives at
# `backend/app/core/yaml_source.py`, so three parents up is `backend/`.
_DEFAULT_YAML_PATH = Path(__file__).parent.parent.parent / "settings.yaml"


def _resolve_yaml_path() -> Path | None:
    """Return the YAML file path to load, or None if no YAML should be used.

    Raises FileNotFoundError if `BATCHRITE_SETTINGS_FILE` is set but the
    target file doesn't exist.
    """
    explicit = os.environ.get(_SETTINGS_FILE_ENV_VAR)
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(
                f"{_SETTINGS_FILE_ENV_VAR} points at {path}, "
                f"which does not exist."
            )
        return path
    if _DEFAULT_YAML_PATH.is_file():
        return _DEFAULT_YAML_PATH
    return None


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """Pydantic settings source backed by a YAML file."""

    def __init__(self, settings_cls: type) -> None:
        super().__init__(settings_cls)
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        path = _resolve_yaml_path()
        if path is None:
            return {}
        with path.open("r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise ValueError(
                f"YAML settings file {path} must contain a mapping at the "
                f"top level, got {type(parsed).__name__}."
            )
        return parsed

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        value = self._data.get(field_name)
        return value, field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._data
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_yaml_config.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Lint**

```bash
black app/core/yaml_source.py tests/unit/test_yaml_config.py
isort app/core/yaml_source.py tests/unit/test_yaml_config.py
mypy app/core/yaml_source.py
```

Expected: black/isort report no changes (or apply formatting cleanly), mypy reports `Success`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/yaml_source.py backend/tests/unit/test_yaml_config.py
git commit -m "feat(config): add YamlConfigSettingsSource for pydantic-settings"
```

---

### Task 4: Wire YAML source into `Settings` (TDD, integration)

**Files:**
- Modify: `backend/app/core/config.py:140-145`
- Modify: `backend/tests/unit/test_yaml_config.py` (append integration tests)

- [ ] **Step 1: Append integration tests that exercise `Settings()`**

Add to the bottom of `backend/tests/unit/test_yaml_config.py`:

```python
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
        "database_url: postgresql+asyncpg://u:p@host:5432/db\n"
        "auth_enabled: false\n"
    )
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    s = Settings()
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"
    assert s.auth_enabled is False


def test_env_vars_override_yaml(tmp_path, monkeypatch):
    _isolate_env(monkeypatch)
    f = tmp_path / "s.yaml"
    f.write_text("auth_enabled: false\n")
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    monkeypatch.setenv("BATCHRITE_AUTH_ENABLED", "true")
    s = Settings()
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
    s = Settings()
    assert s.openrouter.api_key == "sk-or-xyz"
    assert s.openrouter.base_url == "https://openrouter.ai/api/v1"


def test_no_yaml_falls_through_to_defaults(monkeypatch):
    _isolate_env(monkeypatch)
    monkeypatch.setattr(
        "app.core.yaml_source._DEFAULT_YAML_PATH",
        Path("/nonexistent/batchrite/settings.yaml"),
    )
    s = Settings()
    # Defaults from config.py still apply.
    assert s.jwt_algorithm == "HS256"
    assert s.auth_enabled is True


def test_unknown_yaml_keys_are_ignored(tmp_path, monkeypatch):
    _isolate_env(monkeypatch)
    f = tmp_path / "s.yaml"
    f.write_text("not_a_real_field: 42\nauth_enabled: false\n")
    monkeypatch.setenv("BATCHRITE_SETTINGS_FILE", str(f))
    s = Settings()
    assert s.auth_enabled is False  # valid field applied
    assert not hasattr(s, "not_a_real_field")  # unknown silently dropped
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
pytest tests/unit/test_yaml_config.py -v -k "yaml_overrides_defaults or env_vars_override_yaml or yaml_loads_nested or no_yaml_falls_through or unknown_yaml_keys"
```

Expected: the 5 new tests FAIL because `Settings()` does not yet consult the YAML source — `test_yaml_overrides_defaults` will assert the wrong `database_url`, etc.

- [ ] **Step 3: Wire the YAML source into `Settings`**

In `backend/app/core/config.py`, add the import at the top (after the existing imports):

```python
from app.core.yaml_source import YamlConfigSettingsSource
```

Also add `from pydantic_settings import BaseSettings, PydanticBaseSettingsSource` to the existing pydantic_settings import line, so it becomes:

```python
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
```

Then replace the `model_config` block at the end of the `Settings` class:

```python
    model_config = {
        "env_prefix": "BATCHRITE_",
        "env_file": ".env",
        "extra": "ignore",
        "env_nested_delimiter": "__",
    }
```

with this block (adds `settings_customise_sources` right below the existing `model_config`):

```python
    model_config = {
        "env_prefix": "BATCHRITE_",
        "env_file": ".env",
        "extra": "ignore",
        "env_nested_delimiter": "__",
    }

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )
```

- [ ] **Step 4: Run the full test file to verify everything passes**

```bash
pytest tests/unit/test_yaml_config.py -v
```

Expected: all 14 tests PASS (9 from Task 3, 5 new integration tests).

- [ ] **Step 5: Run the broader suite to confirm no regressions**

```bash
pytest tests/unit/ -v
```

Expected: all tests pass. If `test_ai_config.py` or any other unit test that constructs `Settings()` now fails, it's almost certainly leaking host env vars into the test — inspect the failure and add `_isolate_env(monkeypatch)` guard where appropriate (do NOT change production code to mask the failure).

- [ ] **Step 6: Lint**

```bash
black app/core/config.py tests/unit/test_yaml_config.py
isort app/core/config.py tests/unit/test_yaml_config.py
mypy app/core/config.py
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/tests/unit/test_yaml_config.py
git commit -m "feat(config): wire YAML settings source into Settings precedence chain"
```

---

### Task 5: Add `settings.example.yaml` template

**Files:**
- Create: `backend/settings.example.yaml`

- [ ] **Step 1: Write the template**

Create `backend/settings.example.yaml` with the full example from the spec. Every line after the header comment is commented out so copying the file to `settings.yaml` is an explicit opt-in per field:

```yaml
# Batchrite settings override.
#
# Copy this file to `backend/settings.yaml` and uncomment any fields you
# want to override. Env vars (BATCHRITE_*) still win over anything set here.
#
# Precedence (highest to lowest):
#   env vars > .env file > settings.yaml > field defaults in config.py
#
# You can also point at an alternate path:
#   BATCHRITE_SETTINGS_FILE=/etc/batchrite/settings.yaml

# --- Core ---
# database_url: postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite
# secret_key: change-me-in-production
# jwt_algorithm: HS256
# access_token_expire_minutes: 60
# auth_enabled: true
# debug: false

# --- URLs ---
# frontend_url: http://localhost:5173
# backend_url: http://localhost:8000

# --- OAuth ---
# oauth_google_client_id: ""
# oauth_google_client_secret: ""
# oauth_microsoft_client_id: ""
# oauth_microsoft_client_secret: ""
# oauth_microsoft_tenant: common
# oauth_callback_url: http://localhost:5173/auth/callback

# --- SMTP ---
# smtp_host: localhost
# smtp_port: 1025
# smtp_from: noreply@batchrite.local
# smtp_user: ""
# smtp_pass: ""
# smtp_tls: false

# --- Verification / invitations ---
# verification_token_ttl_days: 7
# verification_resend_limit: 3
# verification_resend_window_minutes: 10
# verification_temp_token_minutes: 60
# invitation_ttl_days: 7

# --- AI provider credentials ---
# openrouter:
#   api_key: sk-or-...
#   base_url: https://openrouter.ai/api/v1
# ollama:
#   base_url: http://localhost:11434

# --- AI capability routing ---
# Route all LLM/vision capabilities through openrouter to benchmark frontier
# models. Embedding stays on local ollama (openrouter doesn't serve embeddings
# well). `ai_audio_*` is omitted — audio transcription isn't implemented yet
# (see SUPPORTED_CAPABILITIES in backend/app/models/ai.py).
# ai_vision_provider: openrouter
# ai_vision_model: anthropic/claude-opus-4
# ai_text_provider: openrouter
# ai_text_model: anthropic/claude-opus-4
# ai_doc_structure_provider: openrouter
# ai_doc_structure_model: anthropic/claude-opus-4
# ai_chat_provider: openrouter
# ai_chat_model: anthropic/claude-opus-4
# ai_protocol_generation_provider: openrouter
# ai_protocol_generation_model: anthropic/claude-opus-4
# ai_template_convert_provider: openrouter
# ai_template_convert_model: anthropic/claude-opus-4
# ai_embedding_provider: ollama
# ai_embedding_model: nomic-embed-text:latest

# --- Task runner / misc ---
# task_runner_backend: thread
# task_runner_pool_size: 4
# skills_dir: skills
# max_message_length: 10000
# compaction_threshold: 0.6
# template_convert_max_tool_calls: 25
```

- [ ] **Step 2: Verify the template is valid YAML**

From `backend/` with venv active:

```bash
python -c "import yaml; yaml.safe_load(open('settings.example.yaml'))"
```

Expected: no output, exit code 0 (all content is comments so `safe_load` returns `None`, which is valid).

- [ ] **Step 3: Smoke-test the default-path discovery by copying the template**

```bash
cp backend/settings.example.yaml backend/settings.yaml
python -c "from app.core.config import Settings; s = Settings(); print('loaded', s.jwt_algorithm)" 
# Expected: prints "loaded HS256" — all fields still come from defaults because
# the example file only contains comments.
rm backend/settings.yaml
```

(Run the python command from `backend/` with the venv active.)

- [ ] **Step 4: Commit**

```bash
git add backend/settings.example.yaml
git commit -m "docs(config): add settings.example.yaml template with openrouter routing"
```

---

## Final verification

- [ ] **Run the full backend test suite**

From `backend/`:

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Start the dev server to confirm clean startup**

```bash
uvicorn app.main:app --reload
```

Expected: server starts without warnings about the YAML source (no `settings.yaml` present locally, so the source silently contributes nothing). Ctrl-C to stop.

- [ ] **Confirm the spec requirements are covered**

Manually skim the spec and confirm each section has a corresponding task:
- Precedence chain — Task 4 Step 3 (`settings_customise_sources`)
- File discovery (env var + default + silent skip) — Task 3 (`_resolve_yaml_path`)
- YAML structure (flat + nested + unknown ignored) — Task 3/4 tests
- `pyyaml` dependency — Task 1
- `settings.example.yaml` committed — Task 5
- `.gitignore` entry — Task 2
- Test matrix (all 8 cases from spec) — Tasks 3 & 4

If any gap found, add a follow-up task before declaring done.
