---
paths:
  - "backend/app/services/ai_*"
  - "backend/app/services/chat_*"
  - "backend/app/services/protocol_generator*"
  - "backend/app/services/embedding*"
  - "backend/app/models/ai.py"
  - "backend/app/api/endpoints/ai.py"
  - "backend/app/api/endpoints/chat.py"
---

# AI Agent Configuration Patterns

All AI features use pydantic-ai and follow the same architecture. New AI capabilities must conform.

## Provider Resolution (ai_config.py)

Every AI capability resolves its provider/model through `get_model(capability, db, org_id)`:

1. **Org DB config** (highest priority) -- `AiProviderConfig` table row for org+capability
2. **Platform env vars** (Pro+ only) -- `BATCHRITE_AI_{CAPABILITY}_{PROVIDER,MODEL,API_KEY,BASE_URL}`
3. **Hardcoded defaults** (Pro+ only) -- `DEFAULT_CONFIGS` dict in `models/ai.py`

Non-Pro orgs without custom DB config get a `ValueError`. Never bypass this chain.

## Adding a New AI Capability

1. Add capability name to `SUPPORTED_CAPABILITIES` in `models/ai.py`
2. Add default config to `DEFAULT_CONFIGS` dict
3. Add env var fields to `Settings` in `config.py`: `ai_{capability}_provider`, `_model`, `_api_key`, `_base_url`
4. Use `get_model("capability", db, org_id)` in your service code

## Agent Creation Pattern

All agents use pydantic-ai's `Agent` class with structured outputs:

```python
from pydantic_ai import Agent

# 1. Define structured output
class GeneratedProtocol(BaseModel):
    name: str
    steps: list[GeneratedStep]

# 2. Resolve model via ai_config
model = await get_model("protocol_generation", db, org_id=org_id)

# 3. Create agent with structured output type
agent = Agent(model, system_prompt=system_prompt, output_type=GeneratedProtocol)

# 4. Run
result = await agent.run(prompt)
protocol = result.output  # typed as GeneratedProtocol
```

## Tool Functions for Chat Agents

Tools are async functions taking `ctx: RunContext[ChatDeps]` as first param:

```python
async def search_documents_tool(ctx: RunContext[ChatDeps], query: str) -> SearchResult:
    # Access deps: ctx.deps.db, ctx.deps.org_id, ctx.deps.user_id
    # Track tool usage: ctx.deps.tool_calls.append({...})
    ...
```

Register tools in Agent constructor: `Agent(model, tools=[tool1, tool2], deps_type=ChatDeps)`

## API Key Injection

Keys are injected into `os.environ` on-demand by `_build_model_string()`. The `_PROVIDER_ENV_KEYS` dict maps provider names to their expected env var names. Credentials stored in JSONB in DB are extracted and set before agent creation.

## Output Sanitization

Chat responses pass through sanitization (strips `<think>` blocks, bold "Thought Process" sections, wraps bare JSON in code fences). Apply `_sanitize_llm_output()` to any user-facing LLM text.

## Context Management

- Message history persisted as JSONB via pydantic-ai's `ModelMessagesTypeAdapter`
- Compaction: when history exceeds token budget, older messages are LLM-summarized into a `role="summary"` message
- Hard truncation fallback: if still over limit after compaction, truncate from front
- Context window sizes defined in `settings.context_window_defaults`
