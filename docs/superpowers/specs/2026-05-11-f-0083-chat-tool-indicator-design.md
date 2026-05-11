# F-0083: Show Chat Agent Tool Calls in Thinking Indicator

## Problem

While the chat agent runs a multi-step turn (search documents, look up unit ops, validate a protocol, etc.), the UI shows only a static 3-dot wiggle. Users can't tell what the agent is doing and lose trust on long turns.

We need the indicator to name the active tool ("Searching protocols…", "Reading run data…") while it is in flight, swap labels as the agent moves between tools, and disappear when the final assistant message renders.

## Constraints

- **Ephemeral.** Tool labels are a live status. No transcript artifact remains after the assistant message lands.
- **Tool name only.** No arguments, no result snippets.
- **Centralized label map.** Adding a new tool must not require editing the indicator component.
- **Fallback.** Pure-LLM thinking (no tool in flight) still shows the dot wiggle.
- **Scope.** Tool events only this round — assistant response text continues to arrive in a single final chunk (token streaming is a follow-up).

## Approach

Convert the chat send-message endpoint to SSE. Hook pydantic-ai's `event_stream_handler` to emit `tool_start` / `tool_end` events as the agent runs, then a final `done` event carrying the same payload the POST returns today. The frontend chat store consumes the stream, tracks `currentTool`, and the indicator renders a label from a shared `toolLabels` map (falling back to dots when null).

Considered alternatives:

- **Side-channel poll** — keep POST, expose `GET /sessions/{id}/status`. Rejected: poll latency makes labels feel laggy, race conditions across overlapping requests, fights pydantic-ai's native event flow.
- **DB-persisted tool log + poll** — extra DB writes per tool, worst-of-both.
- **WebSocket** — heavier infra than needed for a one-way stream.

## Architecture

### Backend

**New endpoint** `POST /chat/sessions/{session_id}/messages/stream` returning `text/event-stream`. The existing `POST .../messages` endpoint is removed in the same change (single consumer, frontend updates atomically).

**Event protocol** (one JSON object per SSE `data:` line):

```
data: {"type": "tool_start", "tool": "search_documents"}
data: {"type": "tool_end",   "tool": "search_documents"}
data: {"type": "tool_start", "tool": "search_unit_ops"}
data: {"type": "tool_end",   "tool": "search_unit_ops"}
data: {"type": "done", "user_message": {...}, "assistant_message": {...}, "sources": [...]}
```

- Discriminator field: `type`.
- `tool` is the raw pydantic-ai tool name (e.g., `search_documents`, `task`, `search_unit_ops`). Label translation happens on the frontend.
- `done` payload schema matches `ChatCompletionResponse` exactly — same shape, same fields.
- If the agent run raises, emit `data: {"type": "error", "detail": "..."}` then close.

**send_message refactor.** `send_message()` becomes an `async def send_message_streaming(...) -> AsyncIterator[dict]`:

1. Persist user message (yields nothing).
2. Wire an `event_stream_handler` callback into `agent.run(..., event_stream_handler=handler)`.
   - On `FunctionToolCallEvent` → enqueue `{"type": "tool_start", "tool": event.part.tool_name}`.
   - On `FunctionToolResultEvent` → enqueue `{"type": "tool_end", "tool": <name from tool_call_id map>}`.
   - Other event kinds ignored.
3. Drain the handler queue concurrently with `agent.run` (asyncio.Queue + a task running the agent; the generator yields whatever the queue produces).
4. After run completes, do the existing finalization (SUMMARY row, persist `ai_message_history`, dedupe sources, sanitize output, persist assistant message). Yield the `done` payload.

The non-streaming `send_message` is removed; the streaming version is the only entry point. (One internal caller; no public consumers outside the chat endpoint.)

**Persistence semantics unchanged.** Tool calls still land in `assistant_msg.metadata_["tool_calls"]` from `ctx.deps.tool_calls`. The streaming events are a separate live channel; they don't replace the audit record. This means the post-hoc tool-call rendering in the message (currently `+page.svelte:301–313`) continues to work for historical messages.

### Frontend

**Store** (`frontend/src/lib/chat-store.svelte.ts`):

- New `currentTool = $state<string | null>(null)` on the store.
- `sendMessage` switches from `fetch().json()` to a streaming reader (`response.body.getReader()` + `TextDecoder`, line-buffered to handle SSE framing).
- Per line: parse JSON after `data: ` prefix; dispatch:
  - `tool_start` → `currentTool = tool`
  - `tool_end` → `currentTool = null` if same tool (avoid clobbering a newer start)
  - `done` → reset `currentTool = null`, run the existing finalization (push assistant message, sources, refresh)
  - `error` → reset `currentTool = null`, surface error
- On disconnect/abort: reset `currentTool = null`.

**Indicator** (`frontend/src/routes/chat/+page.svelte:349–359` — extract into a small `lib/components/ai/ThinkingIndicator.svelte`):

```svelte
{#if currentTool}
  <span class="thinking-label">{toolLabels[currentTool] ?? toolLabels._fallback} <DotWiggle /></span>
{:else}
  <DotWiggle />
{/if}
```

The dot animation stays alongside the label (so the indicator always feels alive); only the leading text appears/disappears.

**Label map** (`frontend/src/lib/ai/tool-labels.ts` — new file):

```ts
export const toolLabels: Record<string, string> = {
  // research_library
  search_documents: 'Searching documents…',
  read_document_section: 'Reading document section…',
  list_documents: 'Listing documents…',
  // protocol_builder
  search_unit_ops: 'Searching unit ops…',
  list_unit_ops: 'Listing unit ops…',
  create_unit_op: 'Creating a unit op…',
  update_unit_op: 'Updating a unit op…',
  delete_unit_op: 'Deleting a unit op…',
  create_protocol: 'Drafting a protocol…',
  validate_protocol: 'Validating the protocol…',
  // subagent dispatch
  task: 'Thinking…',
  _fallback: 'Working…',
};
```

The exact key set is locked at implementation time by grepping every `ctx.deps.tool_calls.append({"tool": "<name>", ...})` site so the map is exhaustive. The component reads only from this map — adding a tool means adding one key here, nothing else.

## Data Flow (single turn)

```
client POST /…/messages/stream  ──▶  send_message_streaming()
                                         │
                                         ├─ user msg persisted, flushed
                                         │
                                         ├─ agent.run(event_stream_handler=h)  ──▶  Anthropic / OpenAI
                                         │       │
                                         │       ├─ FunctionToolCallEvent  ──▶  queue {tool_start, search_documents}  ──▶ SSE
                                         │       │   (tool body runs, appends to ctx.deps.tool_calls)
                                         │       ├─ FunctionToolResultEvent ──▶ queue {tool_end, search_documents}    ──▶ SSE
                                         │       └─ (repeat for each tool)
                                         │
                                         ├─ finalize (SUMMARY row, persist history, dedupe, sanitize, persist assistant msg)
                                         │
                                         └─ queue {done, ...}  ──▶ SSE  ──▶ frontend renders message, clears indicator
```

## Error Handling

- **Tool raises inside the agent.** pydantic-ai still emits `FunctionToolResultEvent` (with a retry/error part). We emit `tool_end` so the indicator clears; the agent decides whether to retry or surface the error in the final answer. No special event needed.
- **agent.run raises.** Caught in the streaming generator; emit `{"type": "error", "detail": "..."}`, log via `logger.exception` (same as today), do not commit. Frontend shows the existing error toast and resets `currentTool`.
- **Client disconnects mid-turn.** The agent task is cancelled; nothing persisted. (Acceptable: matches today's behavior for an interrupted POST.)
- **Unknown tool name on the frontend.** Falls back to `toolLabels._fallback` = "Working…". Logged once per session to console for observability.

## Testing

**Backend unit tests** (`backend/tests/unit/`):

- `test_send_message_streaming.py`
  - Yields `tool_start`/`tool_end` events for each tool the agent calls (use a stubbed pydantic-ai model that scripts tool calls).
  - Yields `done` with the same shape as today's `ChatCompletionResponse`.
  - Persists user + assistant messages even when no tool is called.
  - Emits `error` and rolls back on agent exception.

**Backend integration test** (`backend/tests/integration/`):

- `test_chat_stream_endpoint.py` — hit `/chat/sessions/{id}/messages/stream` with the real router, parse the SSE response, assert `tool_start`/`tool_end`/`done` ordering against a stubbed agent.

**Frontend unit tests** (`frontend/src/lib/`):

- `chat-store.test.ts` — mock `fetch` with a `ReadableStream`, push canned SSE bytes, assert `currentTool` transitions and final message append.
- `tool-labels.test.ts` — every tool key in `toolLabels` (minus `_fallback`) matches a real backend tool name (cross-check via a fixture listing all `tool_calls.append` sites; ideally generated by a small script run in CI later, but for now a hardcoded fixture is fine).

**Browser verification** (qa-verify agent): kick off a chat turn that exercises multiple tools (e.g., "find the SOP for cell culture and create a protocol from it") and confirm:
- Indicator label changes as tools fire.
- Label is gone the instant the final message text appears.
- Plain "what's 2+2" still shows the 3-dot wiggle (no tool path).
- Network tab shows SSE frames in order.

## Rollout

Single deploy: backend endpoint swap + frontend client switch in one PR. No feature flag — the streaming endpoint is a strict superset of behavior, and the frontend always pairs with the matching backend.

## Out of Scope

- Streaming the assistant's response text token-by-token (separate follow-up; user opted out for this round).
- Cancellation UI ("stop generating" button) — would benefit from the streaming infra but is its own task.
- Tool labels in i18n. Plain English strings only; existing chat UI is English-only.
- Surfacing tool errors as visible labels (e.g., "Search failed, retrying…"). Indicator stays neutral; errors only appear in the final assistant message.
