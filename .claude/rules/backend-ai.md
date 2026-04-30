---
paths:
  - "backend/app/services/ai/**"
  - "backend/app/services/protocols/validation.py"
  - "backend/app/models/ai.py"
  - "backend/app/api/endpoints/ai.py"
  - "backend/app/api/endpoints/chat.py"
---

# AI Agent Configuration Patterns

All AI features use **pydantic-ai 1.75+** and follow a single architecture. New AI capabilities must conform.

The chat agent is built as a **harness** — pydantic-ai `Agent` composed with à la carte capabilities (subagent dispatch, context management). One-shot generators (workflows) use plain `Agent` directly.

## Package Layout (`backend/app/services/ai/`)

```
services/ai/
├── ai_config.py         # Provider/model/credential resolution (get_model, get_context_window)
├── ai_provider_validation.py
├── ai_vision.py
├── chat_agent.py        # Builds the cached chat Agent + capabilities (entry point)
├── send_message.py      # Per-request orchestration: load history → run agent → persist
├── sessions.py          # ChatSession CRUD + message history persistence
├── deps.py              # ChatDeps dataclass (RunContext.deps for tools/subagents)
├── embedding.py
├── prompts/             # System prompts (chat_agent.md, summarization.md)
├── runtime/             # Cross-cutting helpers used inside the harness
│   ├── compaction.py    #   CompactionState (per-request mutable state for hooks)
│   ├── token_counting.py#   tiktoken_counter
│   └── sanitize.py      #   _sanitize_llm_output
├── subagents/           # Each subagent is its own package
│   ├── protocol_builder/
│   │   ├── config.py    #   build(model) -> SubAgentConfig
│   │   ├── prompt.md    #   System prompt (read at build time)
│   │   └── tools.py     #   Tool functions for this subagent
│   ├── research_library/
│   └── run_planner/
├── tools/               # Reserved for tools wired directly onto the parent chat Agent
└── workflows/           # One-shot Agents (not subagents): protocol_generator.py, sop_generator.py
```

**Where things go:**
- New **subagent**: new package under `subagents/<name>/` with `config.py` exposing `build(model)`, `prompt.md`, `tools.py`. Register in `chat_agent.py` `subagents = [...]`.
- New **tool on an existing subagent**: add to that subagent's `tools.py` and append to its `agent_kwargs["tools"]` in `config.py`.
- New **one-shot Agent** (called from a service, not via chat): add under `services/ai/workflows/` and call from the relevant domain service.
- **Pure validators / business rules** the agent uses (e.g. graph validation): live in the domain service, not here. Example: `services/protocols/validation.py`. Tools wrap them.

## Provider Resolution (`ai_config.py`)

Every AI capability resolves its provider/model through `get_model(capability, db, org_id)`:

1. **Org DB config** (highest priority) — `AiProviderConfig` row for org+capability
2. **Platform env vars** (Pro+ only):
   - Capability provider + model: `BATCHRITE_AI_{CAPABILITY}_{PROVIDER,MODEL}`
   - Provider-level credentials: `BATCHRITE_{PROVIDER}__API_KEY` (and `BATCHRITE_OLLAMA__BASE_URL` where applicable)
3. **Hardcoded defaults** (Pro+ only) — `DEFAULT_CONFIGS` in `models/ai.py`

Non-Pro orgs without custom DB config get a `ValueError`. Never bypass this chain.

## Adding a New AI Capability

1. Add capability name to `SUPPORTED_CAPABILITIES` in `models/ai.py`
2. Add default config to `DEFAULT_CONFIGS`
3. Add env var fields to `Settings` in `config.py`: `ai_{capability}_provider` and `ai_{capability}_model`. **Do not add `_api_key` or `_base_url`** — credentials resolve from `settings.<provider>.api_key` (and `base_url` for Ollama). New providers need a `ProviderConfig` field on `Settings` and an entry in `_PROVIDER_SETTINGS_ATTRS` in `ai_config.py`.
4. If the model isn't already listed in `settings.context_window_defaults`, add it (look up provider/model — wrong size silently triggers context compaction every turn).
5. Use `get_model("capability", db, org_id)` in your service code.

## Chat Agent Harness Pattern

The chat agent is built once per `(chat_model, subagent_model, summary_model, context_window)` tuple and cached. Per-request state is wired in via `_LiveState` indirection so cached compaction hooks read the current request's `CompactionState`.

```python
# chat_agent.py (skeleton)
agent = Agent(
    chat_model,
    instructions=_CHAT_PROMPT,
    deps_type=ChatDeps,
    capabilities=[
        SubAgentCapability(
            subagents=[research_library.build(m), protocol_builder.build(m), ...],
            default_model=subagent_model,
            include_general_purpose=False,   # disable; otherwise it pulls openai:gpt-4.1 + OPENAI_API_KEY
            max_nesting_depth=1,
        ),
        ContextManagerCapability(
            max_tokens=context_window,
            compress_threshold=settings.compaction_threshold,
            summarization_model=summary_model,
            summary_prompt=_SUMMARY_PROMPT,
            max_tool_output_tokens=2000,
            token_counter=tiktoken_counter,
            on_before_compress=on_before,    # closures over _LiveState
            on_after_compress=on_after,
        ),
    ],
    tools=[],
)
```

**Never** call `Agent(...)` directly inside a request handler — go through `build_chat_agent()`. Callers do `live.set(state)` immediately before `agent.run()`.

## Subagent Pattern (`subagents-pydantic-ai`)

A subagent is a `SubAgentConfig` exposed by a `build(model)` function:

```python
# subagents/<name>/config.py
def build(model: str) -> SubAgentConfig:
    return SubAgentConfig(
        name="my_subagent",
        description="When to dispatch this subagent (read by parent agent)",
        instructions=_PROMPT_PATH.read_text(),
        model=model,
        typically_needs_context=True,
        agent_kwargs={"tools": [tool_a, tool_b]},
    )
```

The framework auto-injects a `task` tool on the parent for dispatch. Subagents share `ChatDeps` via `ctx.deps.clone_for_subagent(max_depth=...)` — `sources` and `tool_calls` are shared so citations and audit rows bubble up.

## One-Shot Workflows (`workflows/`)

For non-conversational generation (single prompt → structured output), use a plain `Agent` with `output_type=`:

```python
# workflows/protocol_generator.py
model = await get_model("protocol_generation", db, org_id=org_id)
agent = Agent(model, system_prompt=system_prompt, output_type=GeneratedProtocol)
result = await agent.run(prompt)
```

These don't need capabilities. Don't co-locate them with chat subagents — they're called from domain services, not by the chat agent.

## Tool Functions

Tools take `RunContext[ChatDeps]` as first param:

```python
async def my_tool(ctx: RunContext[ChatDeps], arg: str) -> MyResult:
    # ctx.deps.db, ctx.deps.org_id, ctx.deps.user_id, ctx.deps.is_org_admin
    ctx.deps.tool_calls.append({"tool": "my_tool", "arg": arg, ...})
    ...
```

Keep tools **thin**: argument mapping + service delegation + `tool_calls` audit. No business logic. If logic is non-trivial, put it in `services/<domain>/` and have the tool call it. Use `@dataclass` (or pydantic) result types — pydantic-ai serializes them.

## API Key Injection

`_build_model_string()` injects keys into `os.environ` on demand. The `_PROVIDER_ENV_KEYS` dict maps provider → env var name. Resolution order: `credentials` kwarg from DB → `settings.<provider>.api_key`. Both paths must be covered for new providers.

## Output Sanitization

Chat responses pass through `_sanitize_llm_output()` (strips `<think>` blocks, bold "Thought Process" sections, wraps bare JSON in code fences). Apply to any user-facing LLM text — workflow outputs included.

## Context Management

- Message history persisted as JSONB via pydantic-ai's `ModelMessagesTypeAdapter`
- Compaction is owned by `ContextManagerCapability` from `pydantic-ai-summarization`. It tracks tokens with `tiktoken_counter` (cl100k_base) and summarizes older turns when `compress_threshold` (default 0.6) of `max_tokens` is reached
- Per-request signals (was compaction triggered? what was the summary?) are surfaced through `CompactionState` via the `_LiveState` indirection — see `chat_agent.py` for the wiring
- Context window sizes live in `settings.context_window_defaults` — entries are matched against the model name suffix; missing models silently fall back to 8192 and trigger compaction every turn
