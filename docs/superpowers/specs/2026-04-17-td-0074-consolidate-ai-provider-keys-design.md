# TD-0074 — Consolidate AI Provider API Keys

## Problem

Platform-level AI credentials are duplicated per capability. `Settings` in
`backend/app/core/config.py` exposes 8 capability quartets, one per capability
(vision, audio, text, embedding, doc_structure, chat, protocol_generation,
template_convert):

```
BATCHRITE_AI_{CAP}_PROVIDER
BATCHRITE_AI_{CAP}_MODEL
BATCHRITE_AI_{CAP}_API_KEY
BATCHRITE_AI_{CAP}_BASE_URL
```

API keys belong to the *provider*, not the capability. When two capabilities
use OpenRouter, operators must copy the same key into two env vars. A
deployment using OpenRouter for all 8 capabilities sets the same key 8 times.

## Goals

- One API key env var per supported provider, not per capability.
- Capability config reduces to provider + model. Credentials resolve from the
  provider-level setting based on the capability's chosen provider.
- `Settings` surface area shrinks: 32 capability fields (8×4) become 16 (8×2)
  + 2 nested provider configs (openrouter + ollama, the providers currently in
  use). Other providers in `SUPPORTED_PROVIDERS` can be added as a one-line
  field when they're actually needed (YAGNI).
- Env var namespace stays under `BATCHRITE_` but uses pydantic-settings nested
  delimiter so code and env vars share structure.

## Non-Goals

- Per-org `AiProviderConfig` DB rows are untouched. They continue to carry
  their own `credentials` JSONB. Scope is **platform env var fallback only**.
- No new capabilities, no provider additions, no DB migration.
- The `audio` capability stays present in `Settings` (provider + model fields
  remain) even though it isn't in `SUPPORTED_CAPABILITIES` yet — the ticket
  lists it as an existing capability that must resolve correctly.

## Design

### Nested provider config

Define a shared nested model:

```python
class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str = ""
```

Add 2 provider-level fields to `Settings` for the providers currently in use:

```python
openrouter: ProviderConfig = ProviderConfig()
ollama: ProviderConfig = ProviderConfig()
```

Other providers (`anthropic`, `openai`, `google`, `groq`, `mistral`, `cohere`,
`xai`, `cerebras`, `deepseek`, `together`, `fireworks`) will be added one at a
time when a capability is actually configured to use them. `bedrock` uses AWS
SDK env vars and does not need a `ProviderConfig` field.

### Env var pattern

Use pydantic-settings `env_nested_delimiter="__"`. Env vars become:

```
BATCHRITE_OPENROUTER__API_KEY
BATCHRITE_ANTHROPIC__API_KEY
BATCHRITE_OLLAMA__BASE_URL
...
```

This is the standard pydantic-settings convention for nested models. Code
access: `settings.openrouter.api_key`, `settings.ollama.base_url`.

### Capability fields (unchanged except for removals)

Keep for all 8 capabilities:

```python
ai_vision_provider: str = ""
ai_vision_model: str = ""
# ... for audio, text, embedding, doc_structure, chat,
#     protocol_generation, template_convert
```

Remove `ai_{cap}_api_key` and `ai_{cap}_base_url` — 16 fields deleted.

### `_get_env_fallback()` logic

Replace the per-capability key/base_url reads with provider-level lookup.

```python
_PROVIDER_SETTINGS_ATTRS = {
    "openrouter": "openrouter",
    "ollama":     "ollama",
}

def _get_env_fallback(capability: str) -> dict | None:
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

The dict is effectively identity-mapped today, but keeping it makes the
"provider name → settings attr" indirection explicit and localizes any future
naming drift. A capability whose `ai_{cap}_provider` is not in this dict
(e.g., `anthropic` before its field is added) returns with `credentials=None`;
`_build_model_string` then relies on whatever is already in `os.environ`,
matching today's behavior for unconfigured providers.

### `backend/.env` update

Drop the duplicated per-cap keys and rely on the single OpenRouter key:

```
BATCHRITE_OPENROUTER__API_KEY=sk-or-...

BATCHRITE_AI_TEMPLATE_CONVERT_PROVIDER=openrouter
BATCHRITE_AI_TEMPLATE_CONVERT_MODEL=anthropic/claude-sonnet-4

BATCHRITE_AI_PROTOCOL_GENERATION_PROVIDER=openrouter
BATCHRITE_AI_PROTOCOL_GENERATION_MODEL=anthropic/claude-sonnet-4

BATCHRITE_AI_VISION_PROVIDER=openrouter
BATCHRITE_AI_VISION_MODEL=anthropic/claude-sonnet-4
```

### Rules doc update

`.claude/rules/backend-ai.md` step 3 of "Adding a New AI Capability":

> 3. Add env var fields to `Settings` in `config.py`: `ai_{capability}_provider`
>    and `ai_{capability}_model`. **Do not add `_api_key` or `_base_url`** —
>    credentials resolve from the provider-level `settings.<provider>.api_key`
>    (and `base_url` where applicable).

And update the "Provider Resolution" bullet 2 to reflect the new env var
pattern.

## Testing

Add tests to `backend/tests/unit/test_ai_config.py` covering:

1. `_get_env_fallback` returns `None` when provider or model is unset.
2. `_get_env_fallback` resolves `credentials.api_key` from the provider-level
   setting when `ai_{cap}_provider` matches a configured provider.
3. `_get_env_fallback` resolves `credentials.base_url` for Ollama.
4. `_get_env_fallback` returns `provider + model_name` with `credentials=None`
   when the provider has no configured key (e.g., an ollama capability with
   no base_url set — it falls through to pydantic-ai defaults downstream).

Monkeypatch `settings` attributes to simulate env var state. Do not require
real env var loading.

## Breaking Change

Operators upgrading must rename env vars:

| Old                                              | New                               |
|--------------------------------------------------|-----------------------------------|
| `BATCHRITE_AI_VISION_API_KEY=...`                | `BATCHRITE_OPENROUTER__API_KEY=…` |
| `BATCHRITE_AI_CHAT_API_KEY=...`                  | (same key reused across caps)     |
| `BATCHRITE_AI_{CAP}_BASE_URL=...` (for Ollama)   | `BATCHRITE_OLLAMA__BASE_URL=…`    |

Note the **double underscore** in the new env var names — pydantic-settings
treats `__` as the nested-field delimiter. A single underscore will not be
picked up.

Call this out in release notes.

## Out of Scope

- Migrating existing deployments' env files (operators handle this).
- Changing `AiProviderConfig` DB rows or schemas.
- Adding bedrock env var support.
- UI changes to the per-org AI configuration page.

## Risks

- **Silent misconfiguration**: if an operator renames `BATCHRITE_AI_VISION_API_KEY`
  to `BATCHRITE_OPENROUTER_API_KEY` (single underscore) instead of
  `BATCHRITE_OPENROUTER__API_KEY`, it won't be picked up. Mitigation: call out
  the double-underscore explicitly in release notes.
- **Pro tier calls fail at runtime**: if a capability points at a provider
  whose key isn't set, the current `_build_model_string` will fail only when
  the agent tries to call out. Same behavior as today — no regression.
