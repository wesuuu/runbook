# TD-0074 — Consolidate AI Provider Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 16 per-capability API key/base_url `Settings` fields with 2 nested provider-level `ProviderConfig` models (openrouter, ollama — the providers currently in use); resolve credentials through the provider named in each capability's provider field.

**Architecture:** Nested pydantic-settings model with `env_nested_delimiter="__"`. `Settings` gains 2 `ProviderConfig` fields; capabilities keep only `provider` + `model`. `_get_env_fallback` looks up credentials from the provider-level setting via a small identity-map dict. Additional providers get added one line at a time when needed.

**Tech Stack:** Python 3, pydantic v2 / pydantic-settings, pytest-asyncio, pydantic-ai.

**Spec:** [docs/superpowers/specs/2026-04-17-td-0074-consolidate-ai-provider-keys-design.md](../specs/2026-04-17-td-0074-consolidate-ai-provider-keys-design.md)

---

## File Structure

**Modify:**
- `backend/app/core/config.py` — add `ProviderConfig` model, 2 provider-level fields (openrouter, ollama); remove 16 per-cap api_key/base_url fields; add `env_nested_delimiter="__"` to `model_config`.
- `backend/app/services/ai_config.py` — replace capability-specific key/base_url reads in `_get_env_fallback` with provider-level lookup via new `_PROVIDER_SETTINGS_ATTRS` dict.
- `backend/tests/unit/test_ai_config.py` — add `TestGetEnvFallback` class covering the new resolution path.
- `backend/.env` — rename obsolete `BATCHRITE_AI_*_API_KEY` lines to a single `BATCHRITE_OPENROUTER__API_KEY`.
- `.claude/rules/backend-ai.md` — rewrite step 3 of "Adding a New AI Capability" and the "Provider Resolution" bullet 2.

---

## Task 1: Add `ProviderConfig` model and provider-level fields to `Settings`

**Files:**
- Modify: `backend/app/core/config.py`

Pydantic-settings populates nested models from env vars when `env_nested_delimiter` is set on `model_config`. After this task, `settings.openrouter.api_key` reads `BATCHRITE_OPENROUTER__API_KEY` from the environment.

- [ ] **Step 1: Add the `ProviderConfig` nested model import and class**

In `backend/app/core/config.py`, add `BaseModel` to the pydantic import and define `ProviderConfig` above `Settings`:

```python
import warnings

from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str = ""


class Settings(BaseSettings):
    ...
```

- [ ] **Step 2: Add the 2 provider-level fields on `Settings`**

Insert a new block after the `ai_*` capability fields (after the `ai_template_convert_model: str = ""` line), before the "Template conversion settings" block:

```python
    # Provider-level credentials (env vars like BATCHRITE_OPENROUTER__API_KEY,
    # BATCHRITE_OLLAMA__BASE_URL). Only providers currently in use are listed;
    # add others (anthropic, openai, etc.) one line at a time when needed.
    openrouter: ProviderConfig = ProviderConfig()
    ollama: ProviderConfig = ProviderConfig()
```

- [ ] **Step 3: Add `env_nested_delimiter` to `model_config`**

Change the `model_config` line at the bottom of `Settings`:

```python
    model_config = {
        "env_prefix": "BATCHRITE_",
        "env_file": ".env",
        "extra": "ignore",
        "env_nested_delimiter": "__",
    }
```

- [ ] **Step 4: Verify Settings imports without error**

Run:
```bash
cd backend && source .venv/bin/activate && python -c "from app.core.config import settings; print(settings.openrouter.api_key, settings.ollama.base_url)"
```
Expected: prints two empty strings, no traceback.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py
git commit -m "feat(config): add provider-level ProviderConfig nested settings [TD-0074]"
```

---

## Task 2: Remove per-capability `api_key` and `base_url` from `Settings`

**Files:**
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Delete the 16 capability-specific credential fields**

In `backend/app/core/config.py`, remove the following lines (keep `*_provider` and `*_model` for every capability — only the 16 api_key/base_url lines are deleted):

```python
    ai_vision_api_key: str = ""
    ai_vision_base_url: str = ""
    ai_audio_api_key: str = ""
    ai_audio_base_url: str = ""
    ai_text_api_key: str = ""
    ai_text_base_url: str = ""
    ai_embedding_api_key: str = ""
    ai_embedding_base_url: str = ""
    ai_doc_structure_api_key: str = ""
    ai_doc_structure_base_url: str = ""
    ai_chat_api_key: str = ""
    ai_chat_base_url: str = ""
    ai_protocol_generation_api_key: str = ""
    ai_protocol_generation_base_url: str = ""
    ai_template_convert_api_key: str = ""
    ai_template_convert_base_url: str = ""
```

After removal the `ai_*` block contains only the 8 `*_provider` and 8 `*_model` fields.

- [ ] **Step 2: Verify Settings still imports**

Run:
```bash
cd backend && source .venv/bin/activate && python -c "from app.core.config import settings; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 3: Verify ai_config.py still imports (it will now fail at call-time, but import is fine)**

Run:
```bash
cd backend && source .venv/bin/activate && python -c "from app.services.ai_config import _get_env_fallback; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/config.py
git commit -m "refactor(config): remove per-capability api_key/base_url fields [TD-0074]"
```

---

## Task 3: Write failing tests for new `_get_env_fallback` behavior

**Files:**
- Test: `backend/tests/unit/test_ai_config.py`

These tests describe the target contract: `_get_env_fallback` reads `ai_{cap}_provider` + `ai_{cap}_model` from settings, then resolves credentials by consulting the provider-level `ProviderConfig`. Tests must fail before Task 4 — the current implementation reads `ai_{cap}_api_key` which no longer exists.

- [ ] **Step 1: Add the `TestGetEnvFallback` class**

Append to `backend/tests/unit/test_ai_config.py`:

```python
from app.core.config import ProviderConfig, settings
from app.services.ai_config import _get_env_fallback


class TestGetEnvFallback:
    """_get_env_fallback resolves credentials from provider-level Settings."""

    def test_returns_none_when_provider_unset(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_vision_provider", "")
        monkeypatch.setattr(settings, "ai_vision_model", "some-model")
        assert _get_env_fallback("vision") is None

    def test_returns_none_when_model_unset(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_vision_provider", "openrouter")
        monkeypatch.setattr(settings, "ai_vision_model", "")
        assert _get_env_fallback("vision") is None

    def test_resolves_api_key_from_provider_level(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_vision_provider", "openrouter")
        monkeypatch.setattr(settings, "ai_vision_model", "anthropic/claude-sonnet-4")
        monkeypatch.setattr(
            settings,
            "openrouter",
            ProviderConfig(api_key="sk-or-test"),
        )
        result = _get_env_fallback("vision")
        assert result == {
            "provider": "openrouter",
            "model_name": "anthropic/claude-sonnet-4",
            "credentials": {"api_key": "sk-or-test"},
        }

    def test_resolves_base_url_for_ollama(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_chat_provider", "ollama")
        monkeypatch.setattr(settings, "ai_chat_model", "qwen3.5:27b")
        monkeypatch.setattr(
            settings,
            "ollama",
            ProviderConfig(base_url="http://lab-box:11434"),
        )
        result = _get_env_fallback("chat")
        assert result == {
            "provider": "ollama",
            "model_name": "qwen3.5:27b",
            "credentials": {"base_url": "http://lab-box:11434"},
        }

    def test_returns_none_credentials_when_provider_has_no_key(self, monkeypatch):
        """Ollama with no base_url is valid; credentials should be None."""
        monkeypatch.setattr(settings, "ai_text_provider", "ollama")
        monkeypatch.setattr(settings, "ai_text_model", "gemma3:latest")
        monkeypatch.setattr(settings, "ollama", ProviderConfig())
        result = _get_env_fallback("text")
        assert result == {
            "provider": "ollama",
            "model_name": "gemma3:latest",
            "credentials": None,
        }

    def test_unknown_provider_returns_none_credentials(self, monkeypatch):
        """A provider name not in the mapping still returns provider+model."""
        monkeypatch.setattr(settings, "ai_text_provider", "bedrock")
        monkeypatch.setattr(settings, "ai_text_model", "anthropic.claude")
        result = _get_env_fallback("text")
        assert result == {
            "provider": "bedrock",
            "model_name": "anthropic.claude",
            "credentials": None,
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_ai_config.py::TestGetEnvFallback -v
```
Expected: all 6 tests FAIL. The current `_get_env_fallback` calls `getattr(settings, "ai_vision_api_key", None)` which returns `None` (attribute removed), so the result shape won't match assertions (e.g. `credentials` may be `None` when test expects a dict, or vice versa).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_ai_config.py
git commit -m "test(ai_config): cover provider-level env fallback [TD-0074]"
```

---

## Task 4: Rewrite `_get_env_fallback` to use provider-level settings

**Files:**
- Modify: `backend/app/services/ai_config.py`

- [ ] **Step 1: Add the `_PROVIDER_SETTINGS_ATTRS` mapping**

In `backend/app/services/ai_config.py`, add a new constant directly below the existing `_PROVIDER_ENV_KEYS` dict (around line 34):

```python
# Map provider name → attribute name on Settings holding its ProviderConfig.
# Only providers whose ProviderConfig field exists on Settings belong here;
# add a new entry whenever a new provider field is added to Settings.
_PROVIDER_SETTINGS_ATTRS: dict[str, str] = {
    "openrouter": "openrouter",
    "ollama": "ollama",
}
```

- [ ] **Step 2: Replace `_get_env_fallback`**

Replace the existing `_get_env_fallback` (around lines 89-110) with:

```python
def _get_env_fallback(capability: str) -> dict | None:
    """Check env vars for a capability config.

    Reads ``ai_{capability}_provider`` + ``ai_{capability}_model`` from settings,
    then looks up credentials on the provider-level ProviderConfig
    (``settings.<provider>.api_key`` / ``.base_url``).

    Returns a config dict or None.
    """
    provider = getattr(settings, f"ai_{capability}_provider", "")
    model_name = getattr(settings, f"ai_{capability}_model", "")
    if not (provider and model_name):
        return None

    creds: dict = {}
    attr = _PROVIDER_SETTINGS_ATTRS.get(provider)
    if attr is not None:
        pc = getattr(settings, attr)
        if pc.api_key:
            creds["api_key"] = pc.api_key
        if pc.base_url:
            creds["base_url"] = pc.base_url

    return {
        "provider": provider,
        "model_name": model_name,
        "credentials": creds or None,
    }
```

- [ ] **Step 3: Update the stale comment about env var naming**

In `_build_model_string` (around line 49), update the docstring line:

```python
    under the standard env var name that pydantic-ai expects (e.g.,
    OPENROUTER_API_KEY). This bridges the gap between Batchrite's
    config system (BATCHRITE_<PROVIDER>__API_KEY) and pydantic-ai.
```

And the inline comment at line 64:

```python
    # Inject API key into os.environ if provided via credentials
    # (from DB config or BATCHRITE_<PROVIDER>__API_KEY env vars)
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run:
```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_ai_config.py::TestGetEnvFallback -v
```
Expected: all 6 tests PASS.

- [ ] **Step 5: Run the full ai_config test file**

Run:
```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_ai_config.py -v
```
Expected: all tests PASS (previously existing `TestBuildModelString`, `TestGetModelOrgScoped`, `TestGetFullConfigOrgScoped`, plus new `TestGetEnvFallback`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai_config.py
git commit -m "refactor(ai_config): resolve creds from provider-level settings [TD-0074]"
```

---

## Task 5: Update `backend/.env` to the new env var pattern

**Files:**
- Modify: `backend/.env`

The user's existing `.env` already has `BATCHRITE_OPENROUTER_API_KEY` (single underscore, unused by code) and three duplicate `BATCHRITE_AI_*_API_KEY` lines. Collapse those into the new nested form and keep the capability provider/model lines.

- [ ] **Step 1: Rewrite `backend/.env`**

Replace lines 5-20 (the current `BATCHRITE_OPENROUTER_API_KEY` line and the three `AI_*` blocks) with:

```
BATCHRITE_OPENROUTER__API_KEY=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

# Template conversion AI (system-wide default)
BATCHRITE_AI_TEMPLATE_CONVERT_PROVIDER=openrouter
BATCHRITE_AI_TEMPLATE_CONVERT_MODEL=anthropic/claude-sonnet-4

# Protocol generation AI (system-wide default)
BATCHRITE_AI_PROTOCOL_GENERATION_PROVIDER=openrouter
BATCHRITE_AI_PROTOCOL_GENERATION_MODEL=anthropic/claude-sonnet-4

# Vision AI (system-wide default)
BATCHRITE_AI_VISION_PROVIDER=openrouter
BATCHRITE_AI_VISION_MODEL=anthropic/claude-sonnet-4
```

- [ ] **Step 2: Verify settings loads the new env var**

Run:
```bash
cd backend && source .venv/bin/activate && python -c "from app.core.config import settings; assert settings.openrouter.api_key.startswith('sk-or-'), settings.openrouter.api_key; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 3: Verify template_convert capability resolves correctly end-to-end**

Run:
```bash
cd backend && source .venv/bin/activate && python -c "
from app.services.ai_config import _get_env_fallback
r = _get_env_fallback('template_convert')
assert r['provider'] == 'openrouter', r
assert r['model_name'] == 'anthropic/claude-sonnet-4', r
assert r['credentials']['api_key'].startswith('sk-or-'), r
print('ok')
"
```
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/.env
git commit -m "chore(env): migrate to provider-level BATCHRITE_OPENROUTER__API_KEY [TD-0074]"
```

---

## Task 6: Update `.claude/rules/backend-ai.md`

**Files:**
- Modify: `.claude/rules/backend-ai.md`

- [ ] **Step 1: Rewrite the "Provider Resolution" bullet 2**

In `.claude/rules/backend-ai.md`, change the Provider Resolution numbered list (around lines 17-22) to:

```markdown
Every AI capability resolves its provider/model through `get_model(capability, db, org_id)`:

1. **Org DB config** (highest priority) -- `AiProviderConfig` table row for org+capability
2. **Platform env vars** (Pro+ only):
   - Capability provider + model: `BATCHRITE_AI_{CAPABILITY}_{PROVIDER,MODEL}`
   - Provider-level credentials: `BATCHRITE_{PROVIDER}__API_KEY` (and `BATCHRITE_OLLAMA__BASE_URL` where applicable)
3. **Hardcoded defaults** (Pro+ only) -- `DEFAULT_CONFIGS` dict in `models/ai.py`
```

- [ ] **Step 2: Rewrite "Adding a New AI Capability" step 3**

Replace step 3 (around line 30) with:

```markdown
3. Add env var fields to `Settings` in `config.py`: `ai_{capability}_provider` and `ai_{capability}_model`. **Do not add `_api_key` or `_base_url`** — credentials resolve from the provider-level `settings.<provider>.api_key` (and `base_url` for Ollama).
```

- [ ] **Step 3: Update the "API Key Injection" section**

Replace the existing "API Key Injection" paragraph (around line 71) with:

```markdown
## API Key Injection

Keys are injected into `os.environ` on-demand by `_build_model_string()`. The `_PROVIDER_ENV_KEYS` dict maps provider names to their expected env var names. Credentials stored in JSONB in DB (or on `settings.<provider>.api_key` from env vars) are extracted and set before agent creation.
```

- [ ] **Step 4: Commit**

```bash
git add .claude/rules/backend-ai.md
git commit -m "docs(rules): update AI env var pattern to provider-level keys [TD-0074]"
```

---

## Task 7: Run full backend test suite

**Files:**
- (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run:
```bash
cd backend && source .venv/bin/activate && pytest -x --tb=short
```
Expected: all tests PASS.

- [ ] **Step 2: Run linters**

Run:
```bash
cd backend && source .venv/bin/activate && black app tests && isort app tests && mypy app
```
Expected: no errors. Any black/isort reformatting is acceptable; mypy must be clean.

- [ ] **Step 3: If linters reformatted anything, commit**

```bash
git add -A
git status
# Only commit if there are formatting-only changes
git diff --cached --stat
git commit -m "chore: format after TD-0074 changes" || true
```

Expected: either a clean working tree or a formatting-only commit.

---

## Self-Review

**Spec coverage:**
- ✅ Remove `ai_{cap}_api_key` / `ai_{cap}_base_url` — Task 2
- ✅ Add provider-level `ProviderConfig` fields (openrouter, ollama) — Task 1
- ✅ `env_nested_delimiter="__"` — Task 1 step 3
- ✅ `_get_env_fallback` reads provider+model, resolves creds from provider-level — Task 4
- ✅ Other providers (anthropic, openai, …) intentionally deferred; `_get_env_fallback` returns `credentials=None` for them, matching today's no-key behavior — Task 4 + Task 3's `test_unknown_provider_returns_none_credentials`
- ✅ Audio capability provider+model fields retained — Task 2 explicitly keeps them
- ✅ `.env` updated — Task 5
- ✅ `backend-ai.md` rules updated — Task 6
- ✅ Tests — Task 3 (6 tests covering None/empty cases, api_key resolution for openrouter, base_url for ollama, providers not yet in the mapping)
- ✅ Breaking change callout is in the spec and will surface in commit messages; release notes are produced by `/ship` at merge time.

**Placeholder scan:** No TBDs, no "handle edge cases", no "similar to Task N". Every code step shows the code.

**Type consistency:** `ProviderConfig` has `api_key: str` and `base_url: str` in Task 1, referenced the same way in Tasks 3 and 4. `_PROVIDER_SETTINGS_ATTRS` keys match the field names added in Task 1.
