# YAML Settings Override — Design

## Problem

`backend/app/core/config.py` currently loads configuration from defaults, a `.env` file, and `BATCHRITE_*` environment variables via `pydantic-settings`. There's no way to supply a structured, declarative config file per environment. Operators who want to pin a deployment's database URL, AI provider routing, SMTP host, etc. must either manage a large set of env vars or edit `.env`, which doesn't handle nested fields cleanly and isn't a natural fit for a committed-per-env base config.

## Goal

Add a YAML config file as an additional settings source so operators can declare a base configuration in a single file, while environment variables remain the deploy-time override path for secrets and per-host tweaks.

## Precedence

Pydantic-settings' default source order, with YAML inserted between dotenv and secrets:

```
init_settings  →  env_settings  →  dotenv_settings  →  yaml_settings  →  file_secret_settings  →  defaults
```

Env vars (including `.env`) override YAML. YAML overrides field defaults. This is the 12-factor pattern: YAML is the declarative base, env vars are the emergency/deploy-time override.

## File Discovery

1. If `BATCHRITE_SETTINGS_FILE` is set, load that path. Missing or unreadable file → raise `FileNotFoundError` at startup (explicit request must succeed).
2. Else, if `backend/settings.yaml` exists, load it.
3. Else, silently skip — no YAML source contributes.

The default path is resolved relative to the backend working directory (same directory uvicorn is launched from for the standard dev command).

## YAML Structure

Field names in the YAML map 1:1 to `Settings` field names (snake_case). Nested pydantic models (currently `ProviderConfig` on `openrouter` and `ollama`) are expressed as nested mappings. Only fields the operator wants to override need to appear; omitted fields fall through to env/default.

Example:

```yaml
database_url: postgresql+asyncpg://batchrite:secret@db.internal:5432/batchrite
auth_enabled: true
debug: false

frontend_url: https://app.batchrite.com
backend_url: https://api.batchrite.com

smtp_host: smtp.sendgrid.net
smtp_port: 587
smtp_from: noreply@batchrite.com
smtp_tls: true

# Provider credentials
openrouter:
  api_key: sk-or-...
  base_url: https://openrouter.ai/api/v1
ollama:
  base_url: http://localhost:11434

# AI capability routing — route all LLM/vision work through openrouter
# to benchmark frontier models. Embedding stays local on ollama.
ai_vision_provider: openrouter
ai_vision_model: anthropic/claude-opus-4

ai_text_provider: openrouter
ai_text_model: anthropic/claude-opus-4

ai_doc_structure_provider: openrouter
ai_doc_structure_model: anthropic/claude-opus-4

ai_chat_provider: openrouter
ai_chat_model: anthropic/claude-opus-4

ai_protocol_generation_provider: openrouter
ai_protocol_generation_model: anthropic/claude-opus-4

ai_template_convert_provider: openrouter
ai_template_convert_model: anthropic/claude-opus-4

ai_embedding_provider: ollama
ai_embedding_model: nomic-embed-text:latest

task_runner_pool_size: 8
```

Note: `ai_audio_*` fields exist on `Settings` as placeholders but no capability
consumes them yet (`"audio"` is not in `SUPPORTED_CAPABILITIES` in
`backend/app/models/ai.py`). Omitted from the example until the feature lands.

Unknown keys are ignored (matches the existing `"extra": "ignore"` model config) so operators can leave comments/placeholders without breaking startup.

## Implementation

### New: `backend/app/core/yaml_source.py`

A `PydanticBaseSettingsSource` subclass that:
- Resolves the path per the discovery rules above.
- Reads the file with `yaml.safe_load`.
- Returns `{}` when no file is used.
- Returns the parsed dict (or `{}` if the file is empty) as the settings source.
- Raises on malformed YAML (`yaml.YAMLError` propagates) and on explicit-but-missing path (`FileNotFoundError`).

### Modified: `backend/app/core/config.py`

Override `Settings.settings_customise_sources` to insert the YAML source between `dotenv_settings` and `file_secret_settings`.

No changes to existing field definitions. The new `ProviderConfig` nesting already works naturally with YAML mappings.

### Modified: `backend/pyproject.toml`

Add `pyyaml` to dependencies.

### New: `backend/settings.example.yaml`

Committed template documenting every available field with example values commented out. Serves as the reference for what keys the YAML accepts.

### Modified: `.gitignore`

Add `backend/settings.yaml` so real configs (which may hold secrets) aren't committed. The `.example.yaml` template stays tracked.

## Tests

`backend/tests/unit/test_yaml_config.py` — uses `tmp_path` and monkeypatches `BATCHRITE_SETTINGS_FILE` to isolate from the working tree:

- **YAML overrides defaults**: write a YAML file setting `database_url`, assert `Settings().database_url` matches.
- **Env overrides YAML**: YAML sets `auth_enabled: false`, env sets `BATCHRITE_AUTH_ENABLED=true`, env wins.
- **Default file silent skip**: no `settings.yaml` present, no env var set, `Settings()` loads normally from defaults.
- **Explicit missing file raises**: `BATCHRITE_SETTINGS_FILE` points at a non-existent path, `Settings()` raises `FileNotFoundError`.
- **Malformed YAML raises**: write `: : :` to the file, `Settings()` raises `yaml.YAMLError`.
- **Nested provider config**: YAML sets `openrouter.api_key`, assert `settings.openrouter.api_key` matches.
- **Empty YAML file**: file exists but is empty, treated as `{}`, defaults apply.
- **Unknown keys ignored**: YAML contains a `not_a_real_field` key, `Settings()` loads without error.

## Non-goals

- No hot-reload — YAML is read once at `Settings()` construction time, same as env vars today.
- No multi-file merging (e.g., `settings.base.yaml` + `settings.prod.yaml`). One file per deployment.
- No schema export / validation tooling beyond what pydantic already provides on model load.
- No migration of existing env-based config — both continue to work; YAML is additive.
