---
name: chat_optimize
description: Manually test and iterate on the AI chat agent's behavior via API calls. Use when the user wants to optimize the chat agent, fix agent responses, improve prompt quality, tune RAG search, debug tool usage, or says "the agent is giving garbage responses".
---

# Chat Agent Optimization

Iteratively test the AI chat agent by sending messages via the API, diagnosing issues, fixing prompts/code, and retrying until the agent behaves correctly.

## Step 1 — Ask what to optimize

Ask the user which area to focus on:

1. **Protocol generation** — the generate-protocol skill wizard flow (drill-down, step proposals, create_protocol call)
2. **Library/RAG search** — document retrieval quality (search_documents returning relevant results)
3. **General conversation** — response quality, thought leakage, formatting, tool usage
4. **Specific skill** — a particular skill file's instructions aren't being followed

## Step 2 — Set up a test session

```bash
cd /home/wesuuu/Code/trellisbio/backend && source .venv/bin/activate
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@bioprocess.com","password":"x"}' | \
  python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
SESSION=$(curl -s -X POST http://localhost:8000/chat/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{}' | \
  python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
```

Send messages with this pattern (reuse TOKEN/SESSION across turns):

```bash
curl -s --max-time 600 -X POST "http://localhost:8000/chat/sessions/$SESSION/messages" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content":"YOUR MESSAGE HERE"}' | python3 -c "
import json,sys; d=json.loads(sys.stdin.read()); a=d.get('assistant_message',{})
tc=(a.get('metadata_') or {}).get('tool_calls',[])
print('TOOLS:', [t.get('tool') for t in tc])
print('SOURCES:', len(d.get('sources',[])))
print('---')
print(a.get('content','ERR:'+json.dumps(d)[:300])[:800])
"
```

To test button-triggered skills, add `"skill_id":"generate-protocol"` to the JSON body.

## Step 3 — Diagnose and fix

Run a multi-turn conversation manually. After each turn, check:

- Did the agent call the expected tools?
- Did it follow the skill instructions (one question at a time, no dumps)?
- Is there thought leakage (`<think>`, "Thought Process:", reasoning narration)?
- Did it show raw JSON, IDs, or tool schemas to the user?
- Did RAG search return relevant results?

### Common issues and fixes

**Agent dumps raw tool results instead of using them internally**
- Root cause: Tool returns too much data (e.g., full param_schema for every unit op)
- Fix: Trim tool return models to minimal fields. Add "Do NOT show this to the user" in tool docstring.
- Files: `backend/app/services/chat_service.py` — tool return models and tool functions

**Agent doesn't follow skill workflow (summarizes instead of proposing steps)**
- Root cause: Skill instructions too verbose for the model. Long prose confuses small models.
- Fix: Rewrite SKILL.md with ultra-short numbered steps. Use imperative commands, not paragraphs.
- Files: `backend/skills/*/SKILL.md`

**Thought leakage (`<think>` tags or "Thought Process:" headers)**
- Root cause: Reasoning models (Qwen 3, DeepSeek) output thinking blocks.
- Fix: `_sanitize_output()` in chat_service.py strips these patterns.
- Files: `backend/app/services/chat_service.py` — `_sanitize_output()`

**Agent asks user for JSON/IDs/structured data**
- Root cause: Tool signature requires complex types the model can't abstract away.
- Fix: Simplify tool args (e.g., `project_name: str` instead of `project_id: UUID`, `steps_text: str` instead of `steps: list[dict]`). Parse server-side.
- Files: `backend/app/services/chat_service.py` — tool function signatures

**RAG search returns 0 results for valid queries**
- Root cause: `RAG_MIN_SCORE` too high, or embedding model degrades on long queries.
- Fix: Lower min_score (currently 0.05). The search tool has a short-query fallback that retries with first 4 words.
- Debug: `python3 -c "... retrieve_relevant_chunks(db, query='X', org_id=..., min_score=0.0) ..."` to see actual scores.
- Files: `backend/app/services/chat_service.py` — `RAG_MIN_SCORE`, `search_documents_tool`

**Agent can't generate valid tool call arguments (500 errors)**
- Root cause: Model too small to produce complex nested JSON for tool calls.
- Fix: Simplify tool signatures. Use pipe-delimited text instead of JSON arrays. Use name lookups instead of UUIDs.
- Alternative: Upgrade to a larger model (qwen3.5:27b works well, qwen3:latest 4B does not).

**Model fails on later turns (context too long)**
- Root cause: Small model's context fills with system prompt + skill inject + tool results + conversation history.
- Fix: Keep system prompt short (<1000 chars). Keep SKILL.md short (<500 chars of instructions). Trim tool return data.

## Step 4 — Iterate

After each fix:
1. Delete the test session: `curl -s -X DELETE ".../chat/sessions/$SESSION" ...`
2. Create a new session
3. Re-run the conversation from turn 1
4. Check if the fix resolved the issue without introducing new problems
5. If the model still misbehaves after 5+ attempts with the same prompt change, the issue is likely the model's capability ceiling — consider upgrading to a larger model

## Step 5 — Verify and clean up

After converging on a working solution:
1. Run backend tests: `pytest tests/unit/test_chat_service.py tests/unit/test_skills_compat.py -x -q`
2. Delete any test sessions/protocols created during testing
3. If the model was changed, update `backend/app/models/ai.py` DEFAULT_CONFIGS

## Key files

| File | What it controls |
|------|-----------------|
| `backend/app/services/chat_service.py` | System prompt, tool functions, RAG config, output sanitization |
| `backend/skills/*/SKILL.md` | Skill-specific workflow instructions |
| `backend/app/models/ai.py` | Default model config (provider, model_name) |
| `backend/app/core/config.py` | `skills_dir` path, `LLM_MAX_TOKENS` |

## Model notes

- **qwen3:latest (4B)**: Too small for multi-tool agent workflows. Dumps tool results, can't generate complex tool args.
- **qwen3.5:27b**: Works well. Follows skill instructions, proposes steps one at a time, generates valid tool calls.
- Larger models (Claude, GPT-4o) would be even better but require API keys configured per-org.
