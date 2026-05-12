---
name: f0083-chat-tool-indicator
description: QA notes for F-0083 chat agent live tool-call label indicator
metadata:
  type: project
---

# F-0083 Chat Tool Indicator QA

## Architecture
- Chat messages now POST to `/sessions/{id}/messages/stream` (SSE), not old single POST.
- Backend emits `tool_start {tool, label}` and `tool_end {tool}` events, then `done {user_message, assistant_message, sources}`.
- Frontend: `streamSse()` in `lib/ai/sse-stream.ts`, state in `chat-store.svelte.ts` (`currentToolLabel`, `currentToolName`).
- `ThinkingIndicator.svelte` renders `{#if label}<span>{label}</span>{/if}` + 3 bouncing dots.

## What labels appear in practice
- `task` dispatch tool → "Thinking…" — this is the parent-agent dispatch event.
- Subagent tools (`list_protocols`, `search_documents`) fire inside the subagent and do NOT surface on the parent event stream. Only parent-level `FunctionToolCallEvent` objects yield SSE events.
- Simple messages ("hi") that invoke no tools show dots-only (no label) — correct behavior.

## CORS requirement
Worktree frontend on :5203 requires an entry in `backend/app/main.py` CORS origins list. Added `"http://localhost:5203"` during QA — this must be committed.

## AI provider setup for QA
Worktree backend needs `settings.yaml` and `.env` copied from the main workspace (`/home/wesuuu/Code/trellisbio/backend/`) to get Ollama/OpenRouter credentials. Without these, all SSE streams return `{"type":"error"}` immediately.

**Why:** Worktrees have no untracked files (`.env`, `settings.yaml`). Copy them manually before browser QA.

## Test results (all PASS)
- Dots appear when `sending=true` and `stalePending=false`
- "Thinking…" label visible inside bubble during tool dispatch
- Label clears after `tool_end` / `done`
- No lingering dots after completed turns
- No console errors
- Portrait 768×1024 layout correct
