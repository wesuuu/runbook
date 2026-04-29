# TD-0081 Regression Check — 2026-04-29

## Status: DEFERRED to user manual verification

This regression check requires:
- Running backend dev server on port 8010
- A Pro-tier org with `chat`, `chat_subagent`, `chat_summary` capabilities configured (DB rows or env-var fallback)
- Real LLM provider credentials (OpenAI / Anthropic / Ollama)
- Live document library content for queries 1 and 2

The 25-task migration plan's automated test suite verifies the engineering invariants (1054 tests passing, 6 pre-existing baseline failures). What the test suite cannot verify is whether the LLM-driven chat behavior subjectively works as expected — that requires running real queries.

The user manual verification clicklist in `backend/docs/chat-agent-migration-plan.md` (§ "User Manual Verification") covers all five regression-check queries and more.

## Setup (to run yourself)

```bash
cd /home/wesuuu/Code/trellisbio/.claude/worktrees/TD-0081-chat-agent-reorg/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8010

# In another terminal:
cd /home/wesuuu/Code/trellisbio/.claude/worktrees/TD-0081-chat-agent-reorg/frontend
VITE_API_PORT=8010 npm run dev -- --port 5183
```

Open `http://localhost:5183`, log in to a Pro-tier org, navigate to chat.

## Queries to run

Fill in results below as you run each query.

### 1. General fact lookup
**Query:** "What's the typical seed train scale for monoclonal antibody production?"
**Expected:** response with [1], [2] citations from research_library if docs exist; otherwise general AI knowledge with the disclaimer.
**Response:** _(fill in)_
**Tool calls:** _(fill in)_
**Sources:** _(fill in)_
**Latency:** _(fill in)_
**Verdict:** _(PASS / DEGRADE / IMPROVE)_

### 2. Library inventory
**Query:** "What documents do we have on cell culture?"
**Expected:** list_documents tool fires; concise list of document titles.
**Verdict:** _(fill in)_

### 3. Protocol creation
**Query:** "I want to make a protocol for a 50L mAb seed train"
**Expected:** dispatch to protocol_builder; one question at a time; ends with `create_protocol` tool call against a real project; new Protocol row visible in the project's protocol list.
**Verdict:** _(fill in)_

### 4. Greeting
**Query:** "Hi, what can you help with?"
**Expected:** brief direct answer, no subagent dispatch (no `task` tool call in metadata).
**Verdict:** _(fill in)_

### 5. Long-context / compaction
**Setup:** issue 30+ messages until token usage approaches 80% of context window, then ask a recall question about the first message's content.
**Expected:** compaction triggers; `ChatMessage(role=SUMMARY)` row appears in `chat_messages` for the session; assistant answers without forgetting earlier context.
**Verdict:** _(fill in)_

## Summary

- Overall verdict: _(fill in after running)_
- Quality changes vs. pre-TD-0081 baseline: _(fill in)_
- Latency changes: _(fill in)_
- Issues to address before merging: _(fill in)_
