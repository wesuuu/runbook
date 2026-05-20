# F-0084 — External Protocol Knowledgebase Subagent (OpenWetWare v1)

**Status:** approved-design · **Priority:** P1 · **Scope:** Backend + Frontend (chat HITL plumbing) · **Effort:** XL (≈12–16h)

## 1. Summary

Add a chat subagent `protocol_knowledgebase` that searches OpenWetWare for public protocols, presents structured candidates in the chat, lets the user refine them in natural language, and — only after an explicit human-in-the-loop approval — hands the chosen payload to `protocol_creator` to draft a Batchrite protocol. The HITL gate uses pydantic-ai's native `requires_approval` / `DeferredToolRequests` primitive; this is the same shape pydantic-deepagents wraps, adapted to our existing à-la-carte capabilities stack.

Out of scope (explicitly deferred per the task): protocols.io, auto-mapping external steps onto Batchrite unit-op categories, background ingestion into the org library, silent RAG-style augmentation. (Superseded by F-0090, which adds protocols.io as a second source — see docs/superpowers/specs/2026-05-19-f-0090-additional-protocol-sources-evaluation.md.)

## 2. User flow

1. User in chat: "find an OpenWetWare protocol for heat-shock transformation of competent E. coli."
2. Parent agent dispatches `protocol_knowledgebase`. Subagent calls `search_openwetware` then `fetch_openwetware_protocol` for the top hits and replies to the parent with a structured payload + a markdown candidate list.
3. Assistant message renders the markdown list (one card per candidate) with clickable `openwetware.org` source links. The reply ends with "Tell me which one to draft from, or ask me to refine — I won't create anything until you give the go-ahead."
4. User can refine in free chat ("the second one, but bump ampicillin to 100 µg/mL"). The parent answers in chat, optionally re-dispatching the subagent. It does **not** auto-call any creation tool.
5. When the user explicitly confirms ("yes, convert it"), the parent calls `create_protocol_from_external_source(payload_json, title, source_url)`. The tool is registered with `requires_approval=True`, so `agent.run()` terminates with `DeferredToolRequests`.
6. Backend yields an `approval_required` SSE event and persists `result.all_messages()` (which contains the deferred call) to `session.ai_message_history`. The stream ends without a `done` event.
7. Frontend renders an inline `ApprovalCard` inside the assistant bubble with the structured payload preview and Approve / Reject buttons. The chat input is disabled while the gate is open.
8. On click, frontend POSTs to `/sessions/{id}/messages/approve`. Backend reconstructs `DeferredToolResults(approvals={tool_call_id: approved})`, resumes via `agent.run(deferred_tool_results=..., message_history=session.ai_message_history)`, and streams the rest through the existing SSE pipeline.
9. The approval is persisted as a user `ChatMessage` ("Approved external protocol conversion." or "Rejected …") so the transcript reads naturally. The resumed agent dispatches `protocol_creator` with the payload inlined into the dispatch prompt, and the final assistant message links to the new protocol with the existing `create_protocol` CTA pill.

## 3. Architecture

### 3.1 New subagent: `protocol_knowledgebase`

Mirrors `research_library` layout exactly.

```
backend/app/services/ai/subagents/protocol_knowledgebase/
├── __init__.py        # re-exports build
├── config.py          # build(model) -> SubAgentConfig
├── prompt.md          # focused instructions
└── tools.py           # search + fetch + parser + TOOL_LABELS
```

Subagent description (read by the parent for dispatch decisions): *"Searches public protocol repositories (OpenWetWare) and returns candidate protocols with structured summaries. Dispatch when the user asks for an external/public protocol, or to find a protocol for technique X from open repositories."*

Tools:

- `search_openwetware(ctx, query: str, limit: int = 5) -> OpenWetWareSearchResult`
  - Hits `https://openwetware.org/wiki/api.php?action=opensearch&search=<q>&limit=<n>&format=json` via `httpx.AsyncClient`.
  - Returns `OpenWetWareSearchResult(total, hits: list[OpenWetWareHit(title, url, snippet)])`.

- `fetch_openwetware_protocol(ctx, url: str) -> ExternalProtocolPayload`
  - Validates `url` host equals `openwetware.org` (literal string check); raises `ValueError("URL must be on openwetware.org")` otherwise.
  - Hits `api.php?action=parse&page=<title>&prop=wikitext|sections|displaytitle&format=json`.
  - Parses the wiki-text with a pure `parse_openwetware_wikitext(text, displaytitle, source_url) -> ExternalProtocolPayload` function (covered by fixture tests).

The result dataclass is loose semi-structured:

```python
@dataclass
class ExternalProtocolStep:
    text: str
    duration_min: int | None  # parsed via /(\d+(?:\.\d+)?)\s*(min|h|hour|s|sec)/i

@dataclass
class ExternalProtocolPayload:
    title: str
    source_url: str
    summary: str            # first paragraph of body or "Description"/"Background" section
    materials: list[str]    # bulleted lines under Materials / Reagents
    steps: list[ExternalProtocolStep]
    notes: str | None       # Notes / Tips section if present
    license: str            # "CC BY-SA 3.0" (OpenWetWare site-wide default)
    attribution: str        # "OpenWetWare contributors, <displaytitle>"
```

Tool labels in the same file:

```python
TOOL_LABELS = {
    "search_openwetware":         "Searching OpenWetWare…",
    "fetch_openwetware_protocol": "Reading external protocol…",
}
```

`backend/app/services/ai/tool_labels.py` imports this `TOOL_LABELS` dict and merges it into `_ALL_LABELS`. The existing coverage test in `tests/unit/test_tool_labels.py` validates both names automatically.

### 3.2 Parent-agent tool: `create_protocol_from_external_source`

Lives at `backend/app/services/ai/tools/external_protocols.py` (the rules file reserves `services/ai/tools/` for tools wired directly onto the parent chat Agent — this is the first occupant).

```python
async def create_protocol_from_external_source(
    ctx: RunContext[ChatDeps],
    payload_json: str,   # the ExternalProtocolPayload, JSON-stringified by the parent
    title: str,
    source_url: str,
) -> str: ...
```

Tool body (runs **only after the user approves**, via pydantic-ai's deferred-tool machinery):
- Appends `{"tool": "create_protocol_from_external_source", "title": title, "source_url": source_url, "approved": True}` to `ctx.deps.tool_calls`.
- Returns a literal string of the form `"EXTERNAL_PROTOCOL_APPROVED\n<JSON payload>"` so the parent agent can recognise the marker and dispatch `protocol_creator`.

Registered on the cached parent agent in `chat_agent.py` via:

```python
tools=[Tool(create_protocol_from_external_source, requires_approval=True)]
```

`TOOL_LABELS` entry in the same file → merged into the aggregator. Label: `"Awaiting approval…"` (so the in-flight thinking indicator reads sensibly if a deferred call leaks into the parent-agent event stream).

### 3.3 Prompt updates

- `backend/app/services/ai/prompts/chat_agent.md` — add a section: when a `protocol_knowledgebase` reply contains a structured payload and the user later asks to convert/create/use it, call `create_protocol_from_external_source` with the chosen payload JSON. After that tool returns `EXTERNAL_PROTOCOL_APPROVED\n<json>`, dispatch `protocol_creator` with the JSON payload embedded in the dispatch prompt. Never call `create_protocol_from_external_source` without the user explicitly confirming in this turn.
- `backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md` — focused subagent prompt: always call `search_openwetware` first, fetch ≤3 of the top hits, return a numbered markdown list (bold title, source URL, one-line summary) plus a fenced JSON block containing all `ExternalProtocolPayload` objects for the parent to pick from. Never invent steps not on the source page. Always cite `source_url`. Always include the CC BY-SA license notice.
- `backend/app/services/ai/subagents/protocol_creator/prompt.md` — add a short new section: if the dispatch brief contains an `EXTERNAL_PROTOCOL_SOURCE` JSON block, treat it as the seed. Copy `steps[].text` verbatim into the corresponding step `description`s. Cite `source_url` and `attribution` in the protocol description. Do not invent steps not present in the source.

### 3.4 HITL plumbing in `send_message_streaming`

Three changes:

1. **Detect deferred tool requests.** After `await run_task`, inspect `result.output`. If it's a `DeferredToolRequests` with `approvals` non-empty:
   - Persist `result.all_messages()` to `session.ai_message_history` (writer session, same pattern as today).
   - Persist a placeholder assistant `ChatMessage` row with `role=ASSISTANT`, `content="Awaiting your approval to draft the selected protocol."` (a meaningful string in case the column is NOT NULL), and `metadata_={"pending_approval": {"tool_call_id": ..., "tool_name": ..., "title": ..., "source_url": ..., "payload_preview": {…}}}` so the chat history endpoint can rebuild the card after a refresh. On resume, this placeholder row is `UPDATE`d (not duplicated) with the final assistant content and the `pending_approval` key removed.
   - Yield `{"type": "approval_required", "tool_call_id", "tool_name", "title", "source_url", "payload_preview", "assistant_message_id"}` and return — **no `done` event**.

2. **New entry point `resume_message_streaming`** in `send_message.py` for the approve endpoint. Takes the same session + a `DeferredToolResults` object. Reuses everything from step 4 onward of `send_message_streaming` (build agent, run with `deferred_tool_results=...` and `message_history=session.ai_message_history`, drain queue, sanitize, persist).

3. **Approval is its own user turn.** Before resuming, append a user `ChatMessage` ("Approved external protocol conversion." or "Rejected the external protocol conversion.") and commit. This lands in the chat transcript even if the resumed agent run fails.

### 3.5 New API endpoint

`backend/app/api/endpoints/chat.py`:

```python
@router.post("/sessions/{session_id}/messages/approve")
async def approve_message(
    session_id: UUID,
    body: ApprovalRequest,
    db = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Resume a chat turn that paused on a DeferredToolRequests approval gate."""
```

Schema in `backend/app/schemas/chat.py`:

```python
class ApprovalRequest(BaseModel):
    tool_call_id: str
    approved: bool

class ApprovalRequiredEvent(BaseModel):
    type: Literal["approval_required"]
    tool_call_id: str
    tool_name: str
    title: str
    source_url: str
    payload_preview: dict
    assistant_message_id: UUID
```

The endpoint returns `text/event-stream`, identical to `/sessions/{id}/messages/stream`. Auth, org-scoping, and 404 patterns mirror the streaming endpoint.

If the session has no pending deferred tool call with that `tool_call_id`, return `409 Conflict` with `{"error": "no_pending_approval"}`. If the request arrives after the agent state has already resumed (race between two approve clicks), the second returns `409`.

### 3.6 Settings / feature flag

Extend `FeaturesConfig` in `backend/app/core/config.py`:

```python
class ExternalProtocolsFeatureConfig(BaseModel):
    enabled: bool = False
    request_timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 10

class FeaturesConfig(BaseModel):
    offline_mode: OfflineModeFeatureConfig = OfflineModeFeatureConfig()
    external_protocols: ExternalProtocolsFeatureConfig = ExternalProtocolsFeatureConfig()
```

Env shape: `BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED=true`, etc.

When `settings.features.external_protocols.enabled` is `False`:
- `search_openwetware` and `fetch_openwetware_protocol` raise `ValueError("External protocols feature is disabled.")`. The subagent reports this back to the parent verbatim.
- The `create_protocol_from_external_source` tool is still registered (otherwise the agent cache would diverge between orgs), but it raises a `ValueError` immediately in its body if the flag is off.
- The subagent is registered unconditionally; gating happens at the tool layer so the agent cache stays uniform.

### 3.7 Rate limit (in-process token bucket)

In `tools.py`, module-level:

```python
_now: Callable[[], float] = time.monotonic           # patchable for tests
_RECENT_REQUESTS: dict[UUID, deque[float]] = {}      # org_id -> request timestamps
_LIMIT_LOCK = asyncio.Lock()

async def _check_rate_limit(org_id: UUID) -> None:
    limit = settings.features.external_protocols.rate_limit_per_minute
    async with _LIMIT_LOCK:
        now = _now()
        bucket = _RECENT_REQUESTS.setdefault(org_id, deque())
        cutoff = now - 60.0
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            raise ValueError(
                f"OpenWetWare rate limit hit "
                f"({limit}/min). Try again in a minute."
            )
        bucket.append(now)
```

Both `search_openwetware` and `fetch_openwetware_protocol` call `_check_rate_limit(ctx.deps.org_id)` before any network I/O. The bucket is module-scoped; we'll revisit when we run multi-worker.

### 3.8 Frontend

- **New component:** `frontend/src/lib/components/ai/ApprovalCard.svelte`. Props:
  ```ts
  interface Props {
    toolCallId: string;
    toolName: string;
    title: string;
    sourceUrl: string;
    payloadPreview: ExternalProtocolPayloadPreview;
    onApprove: (toolCallId: string) => void;
    onReject:  (toolCallId: string) => void;
  }
  ```
  Renders inline inside the assistant bubble. Layout matches the mockup at `/tmp/f0084-flow-mockup.html`: header strip with "Confirm protocol creation" + HITL chip, body with title/source/steps/duration/deviations grid, action strip with Reject (ghost) + Approve & draft (primary) buttons.

- **Chat stream client** (`frontend/src/lib/chat-store.svelte` — the existing SSE consumer):
  - Add a handler for `approval_required` events. Store the payload on the in-flight assistant message's `metadata_.pending_approval` and surface `ApprovalCard` from `ChatPanel.svelte` for any message with that metadata field.
  - On Approve / Reject, POST to `/sessions/{id}/messages/approve` and open a new SSE stream for the resumed turn. Disable the chat input while a pending approval is unresolved.

- **API client** (`frontend/src/lib/api.ts`): add `approveMessage(sessionId, toolCallId, approved)` returning the SSE response object.

- **Zod schemas** (`frontend/src/lib/schemas/chat.ts`): add `ApprovalRequiredEventSchema`, `ExternalProtocolPayloadPreviewSchema`, `ApprovalRequestSchema`.

No new SSE plumbing or markdown extensions. The existing `ChatPanel.svelte` already renders messages with `metadata_` lookups; we extend that pattern.

## 4. Data flow

```
turn 1 (search):   user → POST /messages/stream → parent dispatches knowledgebase
                   → search_openwetware + fetch_openwetware_protocol ×N
                   → subagent returns markdown + JSON → parent renders → done

turn 2 (refine):   user → POST /messages/stream → parent answers freely, may re-dispatch
                   knowledgebase. Repeat as needed. No tool gate hit.

turn 3 (convert):  user "yes" → POST /messages/stream → parent calls
                   create_protocol_from_external_source(...) (requires_approval=True)
                   → agent.run terminates with DeferredToolRequests
                   → backend persists message_history + placeholder assistant row
                   → yields {"type":"approval_required", ...}, stream ends

turn 3b (approve): user clicks Approve → POST /messages/approve
                   → backend appends user "Approved external protocol conversion" row
                   → agent.run(deferred_tool_results=..., message_history=...) resumes
                   → tool body runs, returns "EXTERNAL_PROTOCOL_APPROVED\n<json>"
                   → parent dispatches protocol_creator with payload inlined
                   → final assistant message includes a [Protocol Name](/protocols/<id>) link
                   → done
```

## 5. Tests

### 5.1 Backend unit

`tests/unit/test_openwetware_parser.py`
- Reads `tests/fixtures/openwetware/transformation_of_ecoli.wikitext` and asserts the parsed `ExternalProtocolPayload` has the expected title, ≥3 materials, ≥5 steps, a non-empty summary, the CC BY-SA license, and that at least one step has a parsed `duration_min`. Pure function, no HTTP.

`tests/unit/test_openwetware_tools.py`
- `httpx.AsyncClient.get` is monkey-patched to return canned MediaWiki JSON.
- Cases: (a) feature flag off → `ValueError`. (b) host not `openwetware.org` → `ValueError`. (c) rate-limit hit after `rate_limit_per_minute + 1` calls in the same simulated minute (clock injected via `_now`). (d) successful search appends a `tool_calls` audit row. (e) successful fetch appends an audit row with `source_url`.

`tests/unit/test_approval_flow.py`
- A pydantic-ai `Agent` with a single test tool registered as `requires_approval=True`. `agent.run("call it")` is asserted to return a `DeferredToolRequests` with one approval pending. A second run with `deferred_tool_results=DeferredToolResults(approvals={call_id: True})` is asserted to execute the tool body and return its string result.
- A second case asserts `approvals={call_id: False}` does NOT execute the tool body and the agent surfaces a rejection message.

### 5.2 Backend integration

`tests/integration/test_protocol_knowledgebase_handoff.py`
- Uses the existing chat fixture + a real `ChatSession`.
- Mocks `httpx.AsyncClient.get` to return canned OpenWetWare JSON for one query + one fetch.
- Step 1: `POST /sessions/{id}/messages/stream` with `"find an OpenWetWare protocol for transformation of E. coli"`. Asserts SSE stream contains `tool_start` for `search_openwetware` and `fetch_openwetware_protocol`, then a `done` event whose assistant message contains the candidate title.
- Step 2: `POST /sessions/{id}/messages/stream` with `"use that one"`. Asserts the SSE stream ends with `{"type":"approval_required", "tool_name":"create_protocol_from_external_source", ...}` and **no** `done` event.
- Step 3: `POST /sessions/{id}/messages/approve` with the captured `tool_call_id` and `approved=true`. Asserts the SSE stream contains a `tool_start` for `task` (protocol_creator dispatch) followed by a `done` event, that a new `Protocol` row was created with the candidate title, and that the protocol's description contains the OpenWetWare source URL.
- Step 4 (rejection path): repeat steps 1–2 in a fresh session, then `POST /messages/approve` with `approved=false`. Asserts no `Protocol` row created and the assistant transcript contains a user "Rejected …" message.

### 5.3 Frontend

`frontend/src/lib/components/ai/ApprovalCard.test.ts` (Vitest, jsdom)
- Renders with mock props, asserts title + source URL + deviations are visible, and that clicking Approve / Reject fires the respective callback with the `toolCallId`. No DOM snapshot — assert by accessible text and role.

Existing Playwright suite is **not** extended for v1 (the integration test covers the round trip).

## 6. Files touched

```
backend/app/core/config.py                                              # +ExternalProtocolsFeatureConfig
backend/app/services/ai/subagents/protocol_knowledgebase/__init__.py    # new
backend/app/services/ai/subagents/protocol_knowledgebase/config.py      # new
backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md      # new
backend/app/services/ai/subagents/protocol_knowledgebase/tools.py       # new (~280 lines incl. parser + rate limit)
backend/app/services/ai/tools/__init__.py                               # new (package marker; "tools/" reserved by rules)
backend/app/services/ai/tools/external_protocols.py                     # new (parent-agent approval tool + TOOL_LABELS)
backend/app/services/ai/tool_labels.py                                  # +2 imports + dict merge
backend/app/services/ai/chat_agent.py                                   # register subagent + Tool(..., requires_approval=True)
backend/app/services/ai/send_message.py                                 # DeferredToolRequests detection + resume_message_streaming
backend/app/services/ai/prompts/chat_agent.md                           # HITL guidance
backend/app/services/ai/subagents/protocol_creator/prompt.md            # EXTERNAL_PROTOCOL_SOURCE handling
backend/app/api/endpoints/chat.py                                       # POST /messages/approve
backend/app/schemas/chat.py                                             # ApprovalRequest, ApprovalRequiredEvent, ExternalProtocolPayloadPreview
backend/tests/fixtures/openwetware/transformation_of_ecoli.wikitext     # new fixture
backend/tests/fixtures/openwetware/opensearch_response.json             # new fixture
backend/tests/unit/test_openwetware_parser.py                           # new
backend/tests/unit/test_openwetware_tools.py                            # new
backend/tests/unit/test_approval_flow.py                                # new
backend/tests/integration/test_protocol_knowledgebase_handoff.py        # new
frontend/src/lib/components/ai/ApprovalCard.svelte                      # new
frontend/src/lib/components/ai/ApprovalCard.test.ts                     # new
frontend/src/lib/components/ai/ChatPanel.svelte                         # render ApprovalCard when metadata_.pending_approval present
frontend/src/lib/chat-store.svelte.ts                                   # handle approval_required event + approve POST + disable input
frontend/src/lib/api.ts                                                 # approveMessage
frontend/src/lib/schemas/chat.ts                                        # ApprovalRequiredEvent, ExternalProtocolPayloadPreview, ApprovalRequest
CLAUDE.md                                                               # add external_protocols feature flag to the flags table
.claude/rules/backend-ai.md                                             # short note on HITL / requires_approval pattern + tools/ first occupant
```

## 7. Risks and trade-offs

- **MediaWiki structure drift.** OpenWetWare wiki-text is community-edited and inconsistent. Section names like "Materials" vs "Reagents" vs "What you need" are handled by a synonym list; pages that defy all synonyms will still parse a `summary`, `license`, and `attribution` but may return empty `materials`/`steps`. The subagent prompt instructs the agent to flag this back to the user rather than fabricate.
- **Single-process rate limit.** Module-level token bucket does not coordinate across workers. Acceptable for our current single-replica deploy; revisit if we go multi-worker. Documented in the code.
- **Agent cache uniformity.** The parent agent is cached per `(chat_model, …)` tuple, not per org. Registering the approval tool conditionally on the feature flag would break the cache invariant. Therefore the tool is always registered and the gate is enforced inside the tool body.
- **Approval-state durability.** The deferred call is persisted as part of `ai_message_history` (pydantic-ai includes the tool call in `all_messages()`). A user who reloads the page during the approval gate sees the `ApprovalCard` rebuilt from the placeholder assistant message's `metadata_.pending_approval`. The card is the source of truth; the SSE event is just the live notification.

## 8. Non-goals confirmed

- No protocols.io integration.
- No mapping of external steps onto Batchrite unit-op categories before handoff — `protocol_creator` already knows the catalog.
- No persistence of fetched external protocols into the org library.
- No new chat aesthetic, custom cursors, or page-level animation work — `ApprovalCard` reuses existing chat primitives.
