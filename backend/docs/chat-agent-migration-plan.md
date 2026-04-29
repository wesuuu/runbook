# Chat Agent Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `backend/app/services/ai/` from a monolithic `chat_service.py` into a harness-shaped layout (chat agent + 3 subagents + thin tools + runtime + workflows), adopting the official pydantic-ai Capabilities API à la carte.

**Architecture:** The chat agent becomes a pure orchestrator with zero direct tools, dispatching to three specialist subagents (`research_library`, `protocol_builder`, `run_planner`) via `SubAgentCapability`. Compaction moves from in-house code to `ContextManagerCapability` with audit-write callbacks. Per-request agent construction in this plan; globalization for TD-0063 lands in Task 23.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, pytest-asyncio, pydantic-ai 1.x with new deps `subagents-pydantic-ai` (provides `SubAgentCapability`) + `summarization-pydantic-ai` (provides `ContextManagerCapability`, imports as `pydantic_ai_summarization`) + `tiktoken` (accurate token counter).

**Spec:** `backend/docs/chat-agent-target-structure.md`
**Inventory:** `backend/docs/chat-agent-inventory.md`
**Eval:** `backend/docs/chat-agent-harness-eval.md`

---

## Pre-flight

Before starting, ensure the worktree is set up:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install poetry
poetry install --no-root
```

Verify the test database is reachable: `psql postgresql://postgres:postgres@localhost:5432/batchrite_test -c "SELECT 1"`. If missing, create it: `createdb -h localhost -U postgres batchrite_test`.

Confirm baseline tests pass before any change:

```bash
cd backend && source .venv/bin/activate
pytest tests/unit/test_chat_service.py tests/integration/test_chat_api.py -v
```

If any baseline test fails, stop and investigate before continuing.

---

## File Structure

### Files created (alphabetical)

| Path | Responsibility |
|---|---|
| `backend/app/services/ai/__init__.py` | Public API: re-exports `send_message`, `create_session`, `get_session`, `list_sessions`, `delete_session` |
| `backend/app/services/ai/chat_agent.py` | `build_chat_agent(db, org_id, compaction_state)` — Agent factory with capabilities |
| `backend/app/services/ai/deps.py` | `RetrievedChunk`, `ChatDeps` (with `subagents` field + `clone_for_subagent`) |
| `backend/app/services/ai/send_message.py` | `send_message(...)` — orchestration: build → run → persist |
| `backend/app/services/ai/sessions.py` | Session CRUD: `create_session`, `get_session`, `list_sessions`, `delete_session` |
| `backend/app/services/ai/prompts/chat_agent.md` | Main chat agent system prompt |
| `backend/app/services/ai/prompts/summarization.md` | `ContextManagerCapability` summary prompt |
| `backend/app/services/ai/runtime/__init__.py` | empty |
| `backend/app/services/ai/runtime/compaction.py` | `CompactionState`, `make_compaction_hooks(state)` |
| `backend/app/services/documents/retrieval.py` | `retrieve_relevant_chunks` + `_keyword_search_chunks` (RAG SQL) |
| `backend/app/services/ai/runtime/sanitize.py` | `sanitize_output` + regex constants |
| `backend/app/services/ai/runtime/token_counting.py` | `tiktoken_counter` |
| `backend/app/services/ai/subagents/__init__.py` | Re-exports research_library, protocol_builder, run_planner modules |
| `backend/app/services/ai/subagents/research_library/__init__.py` | Re-exports `build` |
| `backend/app/services/ai/subagents/research_library/config.py` | `build(model) -> SubAgentConfig` |
| `backend/app/services/ai/subagents/research_library/prompt.md` | Librarian persona |
| `backend/app/services/ai/subagents/research_library/tools.py` | `search_documents`, `read_section`, `list_documents` |
| `backend/app/services/ai/subagents/protocol_builder/__init__.py` | Re-exports `build` |
| `backend/app/services/ai/subagents/protocol_builder/config.py` | `build(model) -> SubAgentConfig` |
| `backend/app/services/ai/subagents/protocol_builder/prompt.md` | Protocol builder persona |
| `backend/app/services/ai/subagents/protocol_builder/tools.py` | `list_unit_ops`, `create_unit_op`, `create_protocol_from_spec` |
| `backend/app/services/ai/subagents/run_planner/__init__.py` | Re-exports `build` (placeholder) |
| `backend/app/services/ai/subagents/run_planner/config.py` | Placeholder `build(model)` |
| `backend/app/services/ai/subagents/run_planner/prompt.md` | "(placeholder)" |
| `backend/app/services/ai/subagents/run_planner/tools.py` | empty (placeholder) |
| `backend/app/services/ai/tools/__init__.py` | empty |
| `backend/app/services/ai/tools/projects.py` | `list_projects`, `get_project_by_name` (shared by protocol_builder/run_planner) |
| `backend/app/services/ai/workflows/__init__.py` | empty |
| `backend/app/services/ai/workflows/protocol_generator.py` | (moved from `services/ai/protocol_generator.py`) — disposition header marks dormant |
| `backend/app/services/ai/workflows/sop_generator.py` | (moved from `services/ai/sop_generator.py`) |
| `backend/app/services/protocols/creation.py` | `create_protocol_from_spec(db, user_id, project_name, spec)` — owns project lookup, permission check, parse, graph build, persist. New chat-specific operation (different from the existing `POST /protocols` endpoint, which has different inputs and a template-resolution step). |
| `backend/app/services/protocols/unit_ops.py` | `create_unit_op_definition(db, user_id, org_id, is_org_admin, scope, project_id, name, ...)` — single canonical implementation. The existing `api/endpoints/unit_ops.py::create_unit_op` is refactored to call this same service. |
| `backend/tests/unit/test_runtime_sanitize.py` | tests for `sanitize_output` |
| `backend/tests/unit/test_documents_retrieval.py` | tests for `retrieve_relevant_chunks` (after extraction) |
| `backend/tests/unit/test_runtime_compaction.py` | tests for `CompactionState` + `make_compaction_hooks` |
| `backend/tests/unit/test_runtime_token_counting.py` | tests for `tiktoken_counter` |
| `backend/tests/unit/test_deps.py` | tests for `ChatDeps.clone_for_subagent` |
| `backend/tests/unit/test_protocols_creation.py` | tests for `services/protocols/creation.py` |
| `backend/tests/unit/test_protocols_unit_ops.py` | tests for `services/protocols/unit_ops.py` (and the refactored endpoint) |
| `backend/tests/unit/test_subagents_research_library.py` | tests for research subagent tools |
| `backend/tests/unit/test_subagents_protocol_builder.py` | tests for protocol_builder subagent tools |
| `backend/tests/unit/test_chat_agent_factory.py` | tests for `build_chat_agent` (no LLM call — agent construction only) |
| `backend/tests/unit/test_sessions.py` | tests for sessions module (after extraction) |
| `backend/tests/unit/test_send_message.py` | tests for send_message orchestration |
| `backend/tests/integration/test_chat_concurrency.py` | tests for state-leak across concurrent requests (Task 23) |

### Files modified

| Path | What changes |
|---|---|
| `backend/pyproject.toml` | Add `subagents-pydantic-ai`, `summarization-pydantic-ai`, `tiktoken`. Remove `pydantic-ai-skills`. |
| `backend/app/models/ai.py` | Add `chat_subagent`, `chat_summary` to `SUPPORTED_CAPABILITIES` and `DEFAULT_CONFIGS` |
| `backend/app/core/config.py` | Add `ai_chat_subagent_provider`, `ai_chat_subagent_model`, `ai_chat_summary_provider`, `ai_chat_summary_model` to `Settings` |
| `backend/app/services/ai/chat_service.py` | Progressively shrunk via Tasks 5-7, deleted in Task 20 |
| `backend/app/api/endpoints/chat.py` | Update imports in Task 19 |
| `backend/app/services/documents/pdf.py` | Update import path for `generate_sop_pdf` (Task 21) |

### Files deleted

| Path | When |
|---|---|
| `backend/app/services/ai/chat_service.py` | Task 20 |
| `backend/app/services/ai/protocol_generator.py` | Task 21 (moved to workflows/) |
| `backend/app/services/ai/sop_generator.py` | Task 21 (moved to workflows/) |
| `backend/skills/generate-protocol/SKILL.md` | Task 22 |
| `backend/skills/generate-protocol/` (folder if empty) | Task 22 |

---

## Task 1: Add new dependencies

**Goal:** Install `subagents-pydantic-ai`, `summarization-pydantic-ai`, `tiktoken` for the new capability stack.

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add to `[tool.poetry.dependencies]`**

Open `backend/pyproject.toml` and locate the `[tool.poetry.dependencies]` section (it currently has `pydantic-ai = "^1.66.0"`). Add three entries:

```toml
subagents-pydantic-ai = "^0.2.2"
summarization-pydantic-ai = "^0.1.4"
tiktoken = "^0.7.0"
```

- [ ] **Step 2: Install**

```bash
cd backend
source .venv/bin/activate
poetry lock --no-update
poetry install --no-root
```

Expected: install succeeds, no resolution errors.

- [ ] **Step 3: Verify imports work**

```bash
python -c "from subagents_pydantic_ai import SubAgentCapability, SubAgentConfig, SubAgentDepsProtocol; print('subagents OK')"
python -c "from pydantic_ai_summarization import ContextManagerCapability; print('summarization OK')"
python -c "import tiktoken; print('tiktoken OK')"
```

Expected: three "OK" lines.

- [ ] **Step 4: Run baseline tests to confirm no regression**

```bash
pytest tests/unit/test_chat_service.py tests/integration/test_chat_api.py -v
```

Expected: same passing test count as pre-flight.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/poetry.lock
git commit -m "chore(ai): add subagents-pydantic-ai, summarization-pydantic-ai, tiktoken"
```

**Rollback:** `git revert HEAD` then `poetry install --no-root`.

---

## Task 2: Add AI capability keys for chat subagent and summarizer

**Goal:** Register `chat_subagent` and `chat_summary` in the existing capability resolution chain so per-org provider/model config works for them.

**Files:**
- Modify: `backend/app/models/ai.py`
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Write failing test for `chat_subagent` and `chat_summary` resolution**

Create `backend/tests/unit/test_ai_config_new_capabilities.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import DEFAULT_CONFIGS, SUPPORTED_CAPABILITIES


def test_chat_subagent_in_supported_capabilities():
    assert "chat_subagent" in SUPPORTED_CAPABILITIES


def test_chat_summary_in_supported_capabilities():
    assert "chat_summary" in SUPPORTED_CAPABILITIES


def test_chat_subagent_default_config():
    assert "chat_subagent" in DEFAULT_CONFIGS
    cfg = DEFAULT_CONFIGS["chat_subagent"]
    assert "provider" in cfg
    assert "model_name" in cfg


def test_chat_summary_default_config():
    assert "chat_summary" in DEFAULT_CONFIGS
    cfg = DEFAULT_CONFIGS["chat_summary"]
    assert "provider" in cfg
    assert "model_name" in cfg
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_ai_config_new_capabilities.py -v
```

Expected: FAIL — `"chat_subagent" not in SUPPORTED_CAPABILITIES`.

- [ ] **Step 3: Add the capabilities to `models/ai.py`**

In `backend/app/models/ai.py`, replace:

```python
SUPPORTED_CAPABILITIES = ("vision", "text", "embedding", "doc_structure", "chat", "protocol_generation", "template_convert")
```

with:

```python
SUPPORTED_CAPABILITIES = (
    "vision", "text", "embedding", "doc_structure",
    "chat", "chat_subagent", "chat_summary",
    "protocol_generation", "template_convert",
)
```

In the same file, in `DEFAULT_CONFIGS`, after the `"chat": {...}` entry add:

```python
"chat_subagent": {
    "provider": "ollama",
    "model_name": "qwen3.5:27b",
},
"chat_summary": {
    "provider": "ollama",
    "model_name": "qwen3.5:27b",
},
```

- [ ] **Step 4: Add Settings env var fields**

In `backend/app/core/config.py`, locate the existing `ai_chat_provider` / `ai_chat_model` lines (around line 80) and add four new fields below them:

```python
ai_chat_subagent_provider: str = ""
ai_chat_subagent_model: str = ""
ai_chat_summary_provider: str = ""
ai_chat_summary_model: str = ""
```

- [ ] **Step 5: Run the new test**

```bash
pytest tests/unit/test_ai_config_new_capabilities.py -v
```

Expected: PASS.

- [ ] **Step 6: Run full ai_config test suite to confirm no regression**

```bash
pytest tests/unit/test_ai_config.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/ai.py backend/app/core/config.py backend/tests/unit/test_ai_config_new_capabilities.py
git commit -m "feat(ai): add chat_subagent and chat_summary AI capabilities"
```

**Rollback:** `git revert HEAD`.

---

## Task 3: Verify frontend AI settings page picks up new capabilities

**Goal:** Confirm whether the AI settings UI dynamically renders capabilities or hardcodes the list. No code changes unless hardcoded.

**Files:**
- Read-only inspection: `frontend/src/lib/components/settings/`, `frontend/src/lib/api.ts`

- [ ] **Step 1: Find the AI settings page component**

```bash
grep -rln "ai_provider_config\|AiProviderConfig\|ai/configs" frontend/src --include="*.svelte" --include="*.ts"
```

Note the matching files.

- [ ] **Step 2: Inspect how capabilities are listed**

Open the matched files. Look for either:
- (Dynamic) A loop over capability keys returned by an API call to `/ai/capabilities` or similar.
- (Hardcoded) A literal array like `['chat', 'protocol_generation', ...]`.

- [ ] **Step 3: If dynamic, no change needed**

Document in a one-line file (`backend/docs/chat-agent-migration-plan-frontend-note.md`):
```markdown
Verified at <date>: AI settings page reads capabilities dynamically. New keys chat_subagent and chat_summary will render automatically.
```

- [ ] **Step 4: If hardcoded, add the new keys**

Edit the array(s) found in step 2 to include `'chat_subagent'` and `'chat_summary'`. Run frontend type-check:

```bash
cd frontend && npm run check
```

- [ ] **Step 5: Manually verify in browser (optional smoke test)**

If you have the dev server running: navigate to AI settings page, confirm the two new rows appear. (Otherwise defer until Task 24.)

- [ ] **Step 6: Commit**

```bash
git add backend/docs/chat-agent-migration-plan-frontend-note.md frontend/  # only frontend if modified
git commit -m "chore(ai-settings): surface chat_subagent and chat_summary capabilities"
```

**Rollback:** `git revert HEAD`.

---

## Task 4: Create empty new directory skeleton

**Goal:** Lay down the new structure with empty `__init__.py` files so subsequent tasks can import. No behavior change.

**Files:**
- Create: 14 new `__init__.py` files and the `prompts/`, `runtime/`, `subagents/`, `tools/`, `workflows/` directories

- [ ] **Step 1: Create directories and empty `__init__.py` files**

```bash
cd backend/app/services/ai
mkdir -p prompts runtime tools workflows
mkdir -p subagents/research_library subagents/protocol_builder subagents/run_planner
touch prompts/chat_agent.md prompts/summarization.md
touch runtime/__init__.py
touch subagents/__init__.py
touch subagents/research_library/__init__.py subagents/research_library/prompt.md
touch subagents/protocol_builder/__init__.py subagents/protocol_builder/prompt.md
touch subagents/run_planner/__init__.py subagents/run_planner/prompt.md
touch tools/__init__.py
touch workflows/__init__.py
```

- [ ] **Step 2: Verify Python recognizes the packages**

```bash
cd backend
source .venv/bin/activate
python -c "import app.services.ai.runtime, app.services.ai.subagents, app.services.ai.tools, app.services.ai.workflows; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Run baseline tests**

```bash
pytest tests/unit/ -q
```

Expected: same passing count as pre-flight.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/ai/
git commit -m "chore(ai): scaffold subagents/tools/runtime/workflows/prompts directories"
```

**Rollback:** `git revert HEAD`.

---

## Task 5: Extract output sanitization to `runtime/sanitize.py`

**Goal:** Move `_sanitize_output` and its regex constants out of `chat_service.py` into the new runtime module. Existing callers continue to work via re-export.

**Files:**
- Create: `backend/app/services/ai/runtime/sanitize.py`
- Create: `backend/tests/unit/test_runtime_sanitize.py`
- Modify: `backend/app/services/ai/chat_service.py` (remove the moved code, add a re-export shim)

- [ ] **Step 1: Write failing test for `sanitize_output`**

Create `backend/tests/unit/test_runtime_sanitize.py`:

```python
"""Tests for the extracted output sanitization utility."""
from app.services.ai.runtime.sanitize import sanitize_output


def test_strips_think_blocks():
    text = "Hello <think>internal</think> world"
    assert sanitize_output(text) == "Hello  world"


def test_strips_thought_process_section():
    text = "**Thought Process:**\nlots of reasoning\n---\nThe answer is 42"
    out = sanitize_output(text)
    assert "Thought Process" not in out
    assert "42" in out


def test_wraps_bare_json_in_code_fence():
    text = 'Here is the data: {"key": "longer than twenty chars value here"}'
    out = sanitize_output(text)
    assert "```json" in out


def test_preserves_already_fenced_json():
    text = 'Here:\n```json\n{"key": "longer than twenty chars value here"}\n```'
    out = sanitize_output(text)
    # Should not double-wrap
    assert out.count("```json") == 1


def test_returns_original_when_sanitization_empties_text():
    text = "<think>only thinking</think>"
    out = sanitize_output(text)
    # All-thinking text returns original to avoid blank responses
    assert out == text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_runtime_sanitize.py -v
```

Expected: FAIL — `ModuleNotFoundError: app.services.ai.runtime.sanitize`.

- [ ] **Step 3: Create the sanitize module**

Create `backend/app/services/ai/runtime/sanitize.py`:

```python
"""LLM output sanitization: strip <think> blocks, wrap bare JSON, etc."""
import re

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_THOUGHT_HEADER_PATTERN = re.compile(
    r"\*{0,2}(?:Thought Process|Internal Reasoning|My Reasoning|Analysis|Planning)"
    r"[:\*]*\s*\n.*?(?=\n---|\n\*{0,2}(?:Answer|Response)[:\*]|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_BARE_JSON_PATTERN = re.compile(
    r"(?<!\`\`\`)([\{\[]\s*\".{20,}?[\}\]])", re.DOTALL
)


def sanitize_output(text: str) -> str:
    """Clean up LLM output: strip reasoning tags, wrap bare JSON in fences.

    Returns original `text` if sanitization would empty it (avoids blank
    responses on all-thinking outputs).
    """
    cleaned = _THINK_PATTERN.sub("", text).strip()
    cleaned = _THOUGHT_HEADER_PATTERN.sub("", cleaned).strip()
    cleaned = re.sub(r"^---\s*\n", "", cleaned)
    cleaned = re.sub(r"^\*{0,2}Answer\*{0,2}[:\s]*\n?", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        return text

    def _wrap_json(m: re.Match) -> str:
        json_str = m.group(1)
        prefix = cleaned[:m.start()]
        if prefix.count("```") % 2 == 1:
            return m.group(0)
        return f"\n```json\n{json_str}\n```\n"

    cleaned = _BARE_JSON_PATTERN.sub(_wrap_json, cleaned)
    return cleaned.strip()
```

- [ ] **Step 4: Run new test to verify it passes**

```bash
pytest tests/unit/test_runtime_sanitize.py -v
```

Expected: PASS.

- [ ] **Step 5: Add re-export shim in `chat_service.py`**

In `backend/app/services/ai/chat_service.py`, find the existing `_sanitize_output`, `_THINK_PATTERN`, `_THOUGHT_HEADER_PATTERN`, `_BARE_JSON_PATTERN` definitions (near line 858-893) and replace them with:

```python
# Sanitization moved to runtime/sanitize.py during TD-0081 migration.
# Shim kept here until chat_service.py is deleted (Task 20).
from app.services.ai.runtime.sanitize import sanitize_output as _sanitize_output  # noqa: F401
```

- [ ] **Step 6: Run all chat_service tests**

```bash
pytest tests/unit/test_chat_service.py -v
```

Expected: PASS — `_sanitize_output` callers now use the new module.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai/runtime/sanitize.py backend/tests/unit/test_runtime_sanitize.py backend/app/services/ai/chat_service.py
git commit -m "refactor(ai): extract output sanitization to runtime/sanitize.py"
```

**Rollback:** `git revert HEAD`.

---

## Task 6: Extract RAG retrieval to `services/documents/retrieval.py`

**Goal:** Move `retrieve_relevant_chunks`, `_keyword_search_chunks`, and the RAG constants out of `chat_service.py` into `services/documents/retrieval.py`. Consolidate the retry-with-shorter-query heuristic from `search_documents_tool` into the retrieval function.

**Why `services/documents/` and not `services/ai/runtime/`:** retrieval is a documents-domain query function — it queries `document_chunks` via pgvector + tsvector hybrid scoring. It hooks into nothing in the agent loop (no capability, no callback, no message lifecycle). Bundling it under `runtime/` would suggest it's part of the agent machinery, which it isn't. Co-located with `services/documents/document_processor.py` it's reusable beyond chat (e.g., a future `POST /documents/search` endpoint can call the same function).

**Files:**
- Create: `backend/app/services/documents/retrieval.py`
- Create: `backend/tests/unit/test_documents_retrieval.py`
- Modify: `backend/app/services/ai/chat_service.py` (re-export shim)

- [ ] **Step 1: Write failing test for `retrieve_relevant_chunks` shape**

Create `backend/tests/unit/test_documents_retrieval.py`:

```python
"""Tests for services/documents/retrieval.py — RAG against pgvector + keyword fallback."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization
from app.services.documents.retrieval import (RAG_MAX_CONTEXT_CHARS,
                                                RAG_MIN_SCORE, RAG_TOP_K,
                                                retrieve_relevant_chunks)


def test_constants_exist():
    assert isinstance(RAG_TOP_K, int)
    assert isinstance(RAG_MAX_CONTEXT_CHARS, int)
    assert isinstance(RAG_MIN_SCORE, float)


@pytest.mark.asyncio
async def test_returns_empty_when_no_documents(
    db_session: AsyncSession, test_org: Organization,
):
    result = await retrieve_relevant_chunks(
        db_session, query="anything", org_id=test_org.id,
    )
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_documents_retrieval.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create the retrieval module**

Create `backend/app/services/documents/retrieval.py`. Copy the bodies of `retrieve_relevant_chunks`, `_keyword_search_chunks`, and the constants `RAG_TOP_K`, `RAG_MAX_CONTEXT_CHARS`, `RAG_MIN_SCORE` from `chat_service.py`. Move the retry-with-shorter-query heuristic from `search_documents_tool` (lines 156-160) into the body of `retrieve_relevant_chunks`. The `_pad_embedding` import is now intra-package (`document_processor` is a sibling); `embed_query` still comes from `services/ai/embedding.py`:

```python
"""RAG retrieval: hybrid semantic + keyword search over document chunks."""
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.deps import RetrievedChunk

logger = logging.getLogger(__name__)

RAG_TOP_K = 8
RAG_MAX_CONTEXT_CHARS = 12000
RAG_MIN_SCORE = 0.05


async def retrieve_relevant_chunks(
    db: AsyncSession,
    query: str,
    org_id: UUID,
    document_ids: list[UUID] | None = None,
    top_k: int = RAG_TOP_K,
    max_chars: int = RAG_MAX_CONTEXT_CHARS,
    min_score: float = RAG_MIN_SCORE,
) -> list[RetrievedChunk]:
    """Hybrid semantic + keyword search over document chunks.

    Returns top-K chunks sorted by relevance, capped at max_chars total.
    Falls back to keyword-only if embedding service is unavailable.
    Retries with a shortened query if the initial search returns nothing.
    """
    chunks = await _retrieve_once(
        db, query=query, org_id=org_id, document_ids=document_ids,
        top_k=top_k, max_chars=max_chars, min_score=min_score,
    )
    if not chunks and len(query.split()) > 3:
        # Embeddings degrade on long queries; retry with first 4 words.
        short_query = " ".join(query.split()[:4])
        chunks = await _retrieve_once(
            db, query=short_query, org_id=org_id, document_ids=document_ids,
            top_k=top_k, max_chars=max_chars, min_score=min_score,
        )
    return chunks


async def _retrieve_once(
    db: AsyncSession,
    query: str,
    org_id: UUID,
    document_ids: list[UUID] | None,
    top_k: int,
    max_chars: int,
    min_score: float,
) -> list[RetrievedChunk]:
    """Single retrieval pass — exposed only so retry logic can wrap it."""
    query_embedding = None
    try:
        from app.services.ai.embedding import embed_query
        from app.services.documents.document_processor import _pad_embedding

        raw = await embed_query(query, db)
        query_embedding = _pad_embedding(raw)
    except Exception:
        logger.debug("Embedding unavailable for RAG, using keyword-only")

    fetch_limit = top_k * 3

    if query_embedding is not None:
        has_embeddings = await db.execute(
            sa_text("""
                SELECT 1 FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE d.org_id = :org_id AND dc.embedding IS NOT NULL
                LIMIT 1
            """),
            {"org_id": str(org_id)},
        )

        if has_embeddings.fetchone() is not None:
            doc_filter = ""
            params: dict[str, Any] = {
                "query_vec": str(query_embedding),
                "query": query,
                "org_id": str(org_id),
                "limit": fetch_limit,
            }
            if document_ids:
                doc_filter = "AND dc.document_id = ANY(:doc_ids)"
                params["doc_ids"] = [str(d) for d in document_ids]

            result = await db.execute(
                sa_text(f"""
                    SELECT
                        dc.id AS chunk_id, dc.document_id, dc.chunk_index,
                        dc.content, dc.page_number, d.title AS document_title,
                        CASE WHEN dc.embedding IS NOT NULL
                            THEN (1.0 - (dc.embedding <=> :query_vec))
                            ELSE 0.0
                        END AS vector_score,
                        CASE WHEN dc.search_vector @@ plainto_tsquery('english', :query)
                            THEN ts_rank(dc.search_vector, plainto_tsquery('english', :query))
                            ELSE 0.0
                        END AS keyword_score
                    FROM document_chunks dc
                    JOIN documents d ON d.id = dc.document_id
                    WHERE d.org_id = :org_id
                      {doc_filter}
                      AND (
                          dc.embedding IS NOT NULL
                          OR dc.search_vector @@ plainto_tsquery('english', :query)
                      )
                    ORDER BY (
                        0.7 * CASE WHEN dc.embedding IS NOT NULL
                            THEN (1.0 - (dc.embedding <=> :query_vec))
                            ELSE 0.0
                        END
                        + 0.3 * CASE WHEN dc.search_vector @@ plainto_tsquery('english', :query)
                            THEN ts_rank(dc.search_vector, plainto_tsquery('english', :query))
                            ELSE 0.0
                        END
                    ) DESC
                    LIMIT :limit
                """),
                params,
            )
        else:
            result = await _keyword_search_chunks(
                db, query, org_id, document_ids, fetch_limit
            )
    else:
        result = await _keyword_search_chunks(
            db, query, org_id, document_ids, fetch_limit
        )

    rows = result.fetchall()
    chunks: list[RetrievedChunk] = []
    total_chars = 0

    for row in rows:
        if hasattr(row, "vector_score"):
            score = round(0.7 * row.vector_score + 0.3 * row.keyword_score, 4)
        else:
            score = round(float(row.keyword_score), 4)
        if score < min_score:
            continue
        content = row.content
        if total_chars + len(content) > max_chars:
            break
        chunks.append(RetrievedChunk(
            document_id=row.document_id,
            document_title=row.document_title,
            chunk_id=row.chunk_id,
            chunk_index=row.chunk_index,
            page_number=row.page_number,
            content=content,
            score=score,
        ))
        total_chars += len(content)
        if len(chunks) >= top_k:
            break
    return chunks


async def _keyword_search_chunks(db, query, org_id, document_ids, limit):
    doc_filter = ""
    params: dict[str, Any] = {
        "query": query, "org_id": str(org_id), "limit": limit,
    }
    if document_ids:
        doc_filter = "AND dc.document_id = ANY(:doc_ids)"
        params["doc_ids"] = [str(d) for d in document_ids]
    return await db.execute(
        sa_text(f"""
            SELECT
                dc.id AS chunk_id, dc.document_id, dc.chunk_index,
                dc.content, dc.page_number, d.title AS document_title,
                ts_rank(dc.search_vector, plainto_tsquery('english', :query)) AS keyword_score
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE d.org_id = :org_id
              {doc_filter}
              AND dc.search_vector @@ plainto_tsquery('english', :query)
            ORDER BY ts_rank(dc.search_vector, plainto_tsquery('english', :query)) DESC
            LIMIT :limit
        """),
        params,
    )
```

NOTE: this file imports `RetrievedChunk` from `app.services.ai.deps`, which is created in Task 7. Until Task 7, leave a placeholder import:

```python
# Temporary placeholder — replaced in Task 7
from app.services.ai.chat_service import RetrievedChunk
```

After Task 7 completes, change this back to `from app.services.ai.deps import RetrievedChunk`.

- [ ] **Step 4: Update `chat_service.py` to re-export from new location**

In `backend/app/services/ai/chat_service.py`, replace the bodies of `retrieve_relevant_chunks`, `_keyword_search_chunks`, and the RAG constants with:

```python
# RAG retrieval moved to services/documents/retrieval.py during TD-0081 migration.
from app.services.documents.retrieval import (
    RAG_MAX_CONTEXT_CHARS, RAG_MIN_SCORE, RAG_TOP_K,
    retrieve_relevant_chunks,
)
```

In `search_documents_tool`, remove the now-redundant retry block (lines that paraphrase the query when no chunks return) — the retry now lives inside `retrieve_relevant_chunks`.

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_documents_retrieval.py tests/unit/test_chat_service.py tests/integration/test_chat_api.py -v
```

Expected: PASS — retrieval-using callers continue to work; new test passes.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/documents/retrieval.py backend/tests/unit/test_documents_retrieval.py backend/app/services/ai/chat_service.py
git commit -m "refactor(documents): extract RAG retrieval to services/documents/retrieval.py with retry"
```

**Rollback:** `git revert HEAD`.

---

## Task 7: Move `RetrievedChunk` and `ChatDeps` to `deps.py` with new fields

**Goal:** Create `app/services/ai/deps.py` containing `RetrievedChunk` and `ChatDeps` with the new `subagents` field and `clone_for_subagent` method (satisfies `SubAgentDepsProtocol`).

**Files:**
- Create: `backend/app/services/ai/deps.py`
- Create: `backend/tests/unit/test_deps.py`
- Modify: `backend/app/services/ai/chat_service.py` (re-export)
- Modify: `backend/app/services/documents/retrieval.py` (fix the temporary `RetrievedChunk` placeholder import)

- [ ] **Step 1: Write failing test for `ChatDeps.clone_for_subagent`**

Create `backend/tests/unit/test_deps.py`:

```python
"""Tests for ChatDeps shape and clone_for_subagent semantics."""
import uuid
from unittest.mock import MagicMock

from subagents_pydantic_ai import SubAgentDepsProtocol

from app.services.ai.deps import ChatDeps, RetrievedChunk


def make_deps(**overrides) -> ChatDeps:
    base = dict(
        db=MagicMock(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        is_org_admin=False,
    )
    base.update(overrides)
    return ChatDeps(**base)


def test_chat_deps_satisfies_subagent_protocol():
    deps = make_deps()
    assert isinstance(deps, SubAgentDepsProtocol)


def test_clone_at_max_depth_zero_wipes_subagents():
    deps = make_deps()
    deps.subagents = {"foo": "bar"}
    cloned = deps.clone_for_subagent(max_depth=0)
    assert cloned.subagents == {}


def test_clone_at_max_depth_one_preserves_subagents():
    deps = make_deps()
    deps.subagents = {"foo": "bar"}
    cloned = deps.clone_for_subagent(max_depth=1)
    assert cloned.subagents == {"foo": "bar"}


def test_clone_shares_sources_list_for_aggregation():
    deps = make_deps()
    cloned = deps.clone_for_subagent(max_depth=0)
    cloned.sources.append(RetrievedChunk(
        document_id=uuid.uuid4(),
        document_title="t",
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        page_number=None,
        content="c",
        score=1.0,
    ))
    # Mutation in the clone shows up in the parent — that's the design
    assert len(deps.sources) == 1


def test_clone_shares_tool_calls_list():
    deps = make_deps()
    cloned = deps.clone_for_subagent(max_depth=0)
    cloned.tool_calls.append({"tool": "search_documents"})
    assert len(deps.tool_calls) == 1


def test_clone_preserves_db_and_identity_fields():
    deps = make_deps()
    cloned = deps.clone_for_subagent()
    assert cloned.db is deps.db
    assert cloned.org_id == deps.org_id
    assert cloned.user_id == deps.user_id
    assert cloned.is_org_admin == deps.is_org_admin
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_deps.py -v
```

Expected: FAIL — `ModuleNotFoundError: app.services.ai.deps`.

- [ ] **Step 3: Create `deps.py`**

Create `backend/app/services/ai/deps.py`:

```python
"""Per-request dependencies injected into pydantic-ai tools and subagents.

ChatDeps satisfies SubAgentDepsProtocol from subagents-pydantic-ai (structural
typing — no inheritance).
"""
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class RetrievedChunk:
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_index: int
    page_number: int | None
    content: str
    score: float


@dataclass
class ChatDeps:
    """Dependencies injected into pydantic-ai tools via RunContext."""
    db: AsyncSession
    org_id: UUID
    user_id: UUID
    is_org_admin: bool
    sources: list[RetrievedChunk] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    subagents: dict[str, Any] = field(default_factory=dict)

    def clone_for_subagent(self, max_depth: int = 0) -> "ChatDeps":
        """Create deps for a subagent run.

        - db / org_id / user_id / is_org_admin: shared (request scope)
        - sources / tool_calls: shared so subagent citations and tool-call
          audit rows bubble up to the parent (mutated in place)
        - subagents: preserved when max_depth > 0 (nested dispatch allowed),
          wiped at max_depth == 0 (leaf subagent)
        """
        return ChatDeps(
            db=self.db,
            org_id=self.org_id,
            user_id=self.user_id,
            is_org_admin=self.is_org_admin,
            sources=self.sources,
            tool_calls=self.tool_calls,
            subagents={} if max_depth <= 0 else self.subagents,
        )
```

- [ ] **Step 4: Update `services/documents/retrieval.py` to import from `deps`**

In `backend/app/services/documents/retrieval.py`, change:

```python
from app.services.ai.chat_service import RetrievedChunk
```

to:

```python
from app.services.ai.deps import RetrievedChunk
```

- [ ] **Step 5: Update `chat_service.py` to re-export from new location**

In `backend/app/services/ai/chat_service.py`, replace the existing `RetrievedChunk` and `ChatDeps` dataclass definitions (lines ~58-77) with:

```python
# Deps moved to deps.py during TD-0081 migration.
from app.services.ai.deps import ChatDeps, RetrievedChunk  # noqa: F401
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/unit/test_deps.py tests/unit/test_chat_service.py tests/unit/test_documents_retrieval.py tests/integration/test_chat_api.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai/deps.py backend/app/services/documents/retrieval.py backend/app/services/ai/chat_service.py backend/tests/unit/test_deps.py
git commit -m "refactor(ai): move ChatDeps and RetrievedChunk to deps.py with subagent support"
```

**Rollback:** `git revert HEAD`.

---

## Task 8: Create `services/protocols/creation.py`

**Goal:** Extract the protocol-creation business logic out of the future `create_protocol_from_spec` tool body into a reusable service. The tool will become a thin wrapper.

**Why a new service rather than reusing `api/endpoints/protocols.py::create_protocol`:** the existing endpoint takes `project_id` directly, supports both project- and org-scoped protocols, and resolves default SOP/BatchRecord templates. The chat tool's path is narrower: look up project **by name**, parse a step-text format, build the graph from a step list, persist as DRAFT. Same model, different operation. A premature unification would force one of the two callers into shapes that don't fit. If a future task reveals shared lower-level helpers worth extracting (e.g., a graph-persist helper), do that then — not preemptively.

**Files:**
- Create: `backend/app/services/protocols/__init__.py` (if it doesn't exist)
- Create: `backend/app/services/protocols/creation.py`
- Create: `backend/tests/unit/test_protocols_creation.py`

- [ ] **Step 1: Write failing test for `create_protocol_from_spec`**

Create `backend/tests/unit/test_protocols_creation.py`:

```python
"""Tests for services/protocols/creation.py — thin protocol creation service."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (ObjectPermission, ObjectType, Organization,
                            PermissionLevel, PrincipalType, User)
from app.models.science import Project
from app.services.protocols.creation import (ProtocolSpec, ProtocolStep,
                                              create_protocol_from_spec)


@pytest_asyncio.fixture
async def project(
    db_session: AsyncSession, test_org: Organization, test_user: User,
) -> Project:
    p = Project(name="test-proj", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(p)
    await db_session.flush()
    # Grant edit permission
    perm = ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=test_user.id,
        object_type=ObjectType.PROJECT,
        object_id=p.id,
        level=PermissionLevel.EDIT,
        granted_by_id=test_user.id,
    )
    db_session.add(perm)
    await db_session.flush()
    return p


@pytest.mark.asyncio
async def test_creates_protocol_from_spec(
    db_session: AsyncSession, test_user: User, project: Project,
):
    spec = ProtocolSpec(
        name="My Protocol",
        description="Bench-scale mAb",
        steps=[
            ProtocolStep(name="Buffer Mix", unit_op_name="Buffer Preparation", duration_min=15),
            ProtocolStep(name="Inoculate", unit_op_name="Cell Seeding", duration_min=30),
        ],
    )
    proto = await create_protocol_from_spec(
        db_session, user_id=test_user.id, project_name=project.name, spec=spec,
    )
    assert proto.name == "My Protocol"
    assert proto.project_id == project.id
    assert proto.status == "DRAFT"
    assert len(proto.graph["nodes"]) == 2
    assert len(proto.graph["edges"]) == 1


@pytest.mark.asyncio
async def test_raises_when_project_not_found(
    db_session: AsyncSession, test_user: User,
):
    spec = ProtocolSpec(name="X", description="", steps=[
        ProtocolStep(name="s", unit_op_name="s", duration_min=10),
    ])
    with pytest.raises(ValueError, match="not found"):
        await create_protocol_from_spec(
            db_session, user_id=test_user.id,
            project_name="nonexistent", spec=spec,
        )


@pytest.mark.asyncio
async def test_raises_without_edit_permission(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    p = Project(name="other-proj", organization_id=test_org.id, owner_id=uuid.uuid4())
    db_session.add(p)
    await db_session.flush()
    spec = ProtocolSpec(name="X", description="", steps=[
        ProtocolStep(name="s", unit_op_name="s", duration_min=10),
    ])
    with pytest.raises(ValueError, match="permission"):
        await create_protocol_from_spec(
            db_session, user_id=test_user.id,
            project_name="other-proj", spec=spec,
        )


@pytest.mark.asyncio
async def test_raises_when_spec_has_no_steps(
    db_session: AsyncSession, test_user: User, project: Project,
):
    spec = ProtocolSpec(name="X", description="", steps=[])
    with pytest.raises(ValueError, match="step"):
        await create_protocol_from_spec(
            db_session, user_id=test_user.id,
            project_name=project.name, spec=spec,
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_protocols_creation.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create the service**

Confirm `backend/app/services/protocols/__init__.py` exists; if not, `touch` it.

Create `backend/app/services/protocols/creation.py`:

```python
"""Service: create a Protocol in a project from a structured spec.

Owns project lookup, EDIT permission check, graph construction, persistence.
Used by both the chat agent's protocol_builder subagent (via a thin tool
wrapper) and any future direct REST endpoint or batch job.
"""
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import ObjectType, PermissionLevel
from app.models.science import Project, Protocol, UnitOpDefinition
from app.services.core.permissions import check_permission


class ProtocolStep(BaseModel):
    name: str
    unit_op_name: str
    category: str = "General"
    description: str = ""
    duration_min: int = 30
    params: dict[str, Any] = Field(default_factory=dict)


class ProtocolSpec(BaseModel):
    name: str
    description: str = ""
    steps: list[ProtocolStep]


async def create_protocol_from_spec(
    db: AsyncSession,
    user_id: UUID,
    project_name: str,
    spec: ProtocolSpec,
) -> Protocol:
    """Create a DRAFT Protocol in the named project from a structured spec.

    Raises ValueError if:
      - project not found
      - user lacks EDIT permission
      - spec has no steps
    """
    if not spec.steps:
        raise ValueError("spec must include at least one step")

    result = await db.execute(
        select(Project).where(Project.name.ilike(f"%{project_name}%"))
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise ValueError(f"Project '{project_name}' not found")

    allowed = await check_permission(
        db, user_id, ObjectType.PROJECT, project.id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise ValueError("You don't have edit permission on this project")

    result = await db.execute(select(UnitOpDefinition))
    unit_ops = list(result.scalars().all())

    # Reuse the existing graph-builder helpers (they will move to
    # workflows/protocol_generator.py in Task 21 — this import path
    # updates then).
    from app.services.ai.protocol_generator import (GeneratedProtocol,
                                                     GeneratedStep, build_graph)

    generated = GeneratedProtocol(
        name=spec.name,
        description=spec.description,
        steps=[
            GeneratedStep(
                name=s.name,
                unit_op_name=s.unit_op_name,
                category=s.category,
                description=s.description,
                duration_min=s.duration_min,
                params=s.params,
            )
            for s in spec.steps
        ],
    )
    graph = build_graph(generated, unit_ops, UUID(int=0), user_id)

    protocol = Protocol(
        name=spec.name,
        description=spec.description,
        project_id=project.id,
        status="DRAFT",
        graph=graph,
    )
    db.add(protocol)
    await db.flush()
    return protocol
```

- [ ] **Step 4: Run new test**

```bash
pytest tests/unit/test_protocols_creation.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/creation.py backend/tests/unit/test_protocols_creation.py backend/app/services/protocols/__init__.py
git commit -m "feat(protocols): add create_protocol_from_spec service"
```

**Rollback:** `git revert HEAD`.

---

## Task 9: Extract unit-op creation into `services/protocols/unit_ops.py` and refactor existing endpoint

**Goal:** Extract the unit-op creation logic that lives inline in `api/endpoints/unit_ops.py::create_unit_op` into a service. Refactor the endpoint to call the service. The chat tool (Task 14) will call the same service.

**Why `services/protocols/` and not `services/science/`:** unit ops are a protocols concept — every protocol step references one — and they're created/edited via the protocol editor UI. The existing `services/science/` directory holds `library_registry.py` (subscription/library management), which is a different concern. Co-locate unit-op creation with `services/protocols/creation.py`.

**Why refactor the endpoint now:** otherwise we end up with two copies of the same logic — one in the endpoint, one called from the chat tool. The thin-tool rule (§5 of the spec) only works if both callers go through the same service. The endpoint is small (`api/endpoints/unit_ops.py:138-198`); refactoring is bounded.

**Files:**
- Create: `backend/app/services/protocols/unit_ops.py`
- Create: `backend/tests/unit/test_protocols_unit_ops.py`
- Modify: `backend/app/api/endpoints/unit_ops.py` (refactor `create_unit_op` to call service)

- [ ] **Step 1: Write failing service test**

Create `backend/tests/unit/test_protocols_unit_ops.py`:

```python
"""Tests for services/protocols/unit_ops.py — unit op creation service."""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.services.protocols.unit_ops import create_unit_op_definition


@pytest.mark.asyncio
async def test_creates_org_scoped_unit_op_for_admin(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    op = await create_unit_op_definition(
        db_session,
        user_id=test_user.id,
        org_id=test_org.id,
        is_org_admin=True,
        scope="org",
        name="Custom Mix",
        category="Buffer Prep",
        description="Mix Tris/HCl",
        param_schema={"properties": {}},
    )
    assert op.name == "Custom Mix"
    assert op.organization_id == test_org.id
    assert op.project_id is None


@pytest.mark.asyncio
async def test_rejects_org_scope_for_non_admin(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    with pytest.raises(ValueError, match="admin"):
        await create_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=False,
            scope="org",
            name="X", category="X", description="X", param_schema={},
        )


@pytest.mark.asyncio
async def test_project_scope_requires_project_id(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    with pytest.raises(ValueError, match="project_id"):
        await create_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=False,
            scope="project",
            project_id=None,
            name="X", category="X", description="X", param_schema={},
        )


@pytest.mark.asyncio
async def test_rejects_invalid_scope(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    with pytest.raises(ValueError, match="scope"):
        await create_unit_op_definition(
            db_session,
            user_id=test_user.id,
            org_id=test_org.id,
            is_org_admin=True,
            scope="bogus",
            name="X", category="X", description="X", param_schema={},
        )


@pytest.mark.asyncio
async def test_rejects_duplicate_name(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    await create_unit_op_definition(
        db_session, user_id=test_user.id, org_id=test_org.id, is_org_admin=True,
        scope="org", name="Dup", category="C", description="D", param_schema={},
    )
    with pytest.raises(ValueError, match="exists"):
        await create_unit_op_definition(
            db_session, user_id=test_user.id, org_id=test_org.id, is_org_admin=True,
            scope="org", name="Dup", category="C", description="D", param_schema={},
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_protocols_unit_ops.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create the service**

Create `backend/app/services/protocols/unit_ops.py`:

```python
"""Service: create a UnitOpDefinition (org- or project-scoped).

Single canonical implementation called by:
  - api/endpoints/unit_ops.py::create_unit_op (HTTP — protocol editor button)
  - subagents/protocol_builder/tools.py::create_unit_op (chat tool)
"""
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import UnitOpDefinition


async def create_unit_op_definition(
    db: AsyncSession,
    *,
    user_id: UUID,
    org_id: UUID,
    is_org_admin: bool,
    scope: str,
    name: str,
    category: str,
    description: str,
    param_schema: dict[str, Any],
    project_id: UUID | None = None,
    result_schema: dict[str, Any] | None = None,
) -> UnitOpDefinition:
    """Create a unit op definition.

    Raises ValueError on validation errors. The caller is responsible for
    upstream concerns:
      - resolving `is_org_admin` from JWT/membership (HTTP) or from
        ChatDeps.is_org_admin (chat)
      - validating that `project_id`, if given, belongs to `org_id`
        (HTTP endpoint only — chat tool doesn't accept arbitrary project IDs)
    """
    if scope == "org":
        if not is_org_admin:
            raise ValueError(
                "Only organization admins can create org-wide unit "
                "operations. Use scope='project' instead."
            )
        target_org: UUID | None = org_id
        target_proj: UUID | None = None
    elif scope == "project":
        if project_id is None:
            raise ValueError("project_id is required for project-scoped unit ops")
        target_org = org_id
        target_proj = project_id
    else:
        raise ValueError("scope must be 'org' or 'project'")

    existing = await db.execute(
        select(UnitOpDefinition).where(
            UnitOpDefinition.name == name,
            (UnitOpDefinition.organization_id == org_id)
            | (UnitOpDefinition.organization_id.is_(None)),
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Unit op '{name}' already exists")

    op = UnitOpDefinition(
        name=name,
        category=category,
        description=description,
        param_schema=param_schema,
        result_schema=result_schema,
        organization_id=target_org,
        project_id=target_proj,
    )
    db.add(op)
    await db.flush()
    return op
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_protocols_unit_ops.py -v
```

Expected: PASS.

- [ ] **Step 5: Identify any existing endpoint test file**

```bash
ls backend/tests/integration/test_unit_ops*.py 2>/dev/null
ls backend/tests/integration/ | grep -i unit_op
```

If a file exists, note its path — we'll re-run it after refactoring the endpoint to confirm behavior is preserved. If none exists, the integration coverage relies on whatever calls `POST /unit-ops` — the protocol editor flow — which is exercised by frontend e2e tests, not backend unit tests. We'll add a minimal endpoint test as part of this task.

- [ ] **Step 6: Add an endpoint integration test if none exists**

Append to `backend/tests/integration/test_unit_ops_api.py` (creating it if missing):

```python
"""Integration tests for POST /unit-ops endpoint (must stay green across the
service-extraction refactor)."""
import pytest
from httpx import AsyncClient

from app.models.iam import Organization, User


@pytest.mark.asyncio
async def test_org_admin_creates_org_scoped_unit_op(
    client: AsyncClient, auth_headers: dict, test_org: Organization,
):
    body = {
        "name": "Endpoint Test Op",
        "category": "Buffer Prep",
        "description": "via endpoint",
        "param_schema": {"properties": {}},
    }
    resp = await client.post("/unit-ops", json=body, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Endpoint Test Op"
    assert data["organization_id"] == str(test_org.id)
    assert data["project_id"] is None


@pytest.mark.asyncio
async def test_non_admin_rejected_for_org_scope(
    client: AsyncClient, member_auth_headers: dict,
):
    """A non-admin org member cannot create org-scoped unit ops."""
    body = {
        "name": "Should Fail",
        "category": "X",
        "description": "X",
        "param_schema": {},
    }
    resp = await client.post("/unit-ops", json=body, headers=member_auth_headers)
    assert resp.status_code == 403
```

NOTE: this test references `member_auth_headers` — a non-admin authenticated client. If your `conftest.py` doesn't have this fixture, either skip the second test or add the fixture (look at how `auth_headers` is built and create a parallel one for a non-admin user). Don't block on this; the first test is the load-bearing one.

- [ ] **Step 7: Run the endpoint test against the unrefactored endpoint to confirm baseline**

```bash
pytest tests/integration/test_unit_ops_api.py -v
```

Expected: PASS.

- [ ] **Step 8: Refactor `api/endpoints/unit_ops.py::create_unit_op` to call the service**

In `backend/app/api/endpoints/unit_ops.py`, replace the body of the `create_unit_op` function (currently lines 143-198) with:

```python
@router.post(
    "/unit-ops",
    response_model=UnitOpDefinitionResponse,
    status_code=201,
)
async def create_unit_op(
    unit_op: UnitOpDefinitionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    org_id = user.selected_org_id
    if org_id is None:
        raise HTTPException(
            status_code=400,
            detail="No organization selected",
        )

    # Per-endpoint guard: project (if any) must belong to user's org
    # (this is an HTTP-layer concern because the body accepts arbitrary
    # project_ids; the chat tool path doesn't have this risk).
    if unit_op.project_id is not None:
        result = await db.execute(
            select(Project).where(
                Project.id == unit_op.project_id,
                Project.organization_id == org_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=404,
                detail="Project not found in your organization",
            )

        allowed = await check_permission(
            db, user.id, ObjectType.PROJECT,
            unit_op.project_id, PermissionLevel.EDIT,
        )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail="Project edit permission required",
            )
        is_org_admin = False  # not relevant for project scope
        scope = "project"
    else:
        # Org-scoped — resolve admin role from membership
        admin_q = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.organization_id == org_id,
                OrganizationMember.role == OrgRole.ADMIN,
            )
        )
        is_org_admin = admin_q.scalar_one_or_none() is not None
        if not is_org_admin:
            raise HTTPException(
                status_code=403,
                detail="Org admin role required for org-scoped unit ops",
            )
        scope = "org"

    # Delegate to the canonical service
    from app.services.protocols.unit_ops import create_unit_op_definition
    try:
        new_op = await create_unit_op_definition(
            db,
            user_id=user.id,
            org_id=org_id,
            is_org_admin=is_org_admin,
            scope=scope,
            project_id=unit_op.project_id,
            name=unit_op.name,
            category=unit_op.category,
            description=unit_op.description,
            param_schema=unit_op.param_schema,
            result_schema=unit_op.result_schema,
        )
    except ValueError as e:
        # Service-layer validation errors map to 400/422 at the HTTP boundary
        raise HTTPException(status_code=422, detail=str(e))

    await db.commit()
    await db.refresh(new_op)
    return new_op
```

The helper `_require_org_admin` becomes redundant for the create path (still used by `update_unit_op`); leave it in place — it's used elsewhere in the file.

- [ ] **Step 9: Run both the service test and the endpoint test**

```bash
pytest tests/unit/test_protocols_unit_ops.py tests/integration/test_unit_ops_api.py -v
```

Expected: BOTH pass.

- [ ] **Step 10: Run full test suite to confirm no regression**

```bash
pytest -q
```

Expected: same passing count as pre-flight (or higher).

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/protocols/unit_ops.py backend/tests/unit/test_protocols_unit_ops.py backend/app/api/endpoints/unit_ops.py backend/tests/integration/test_unit_ops_api.py
git commit -m "refactor(unit_ops): extract create logic into services/protocols/unit_ops.py and have endpoint call it"
```

**Rollback:** `git revert HEAD`.

---

## Task 10: Create `runtime/token_counting.py`

**Goal:** Tiktoken-backed token counter for `ContextManagerCapability`.

**Files:**
- Create: `backend/app/services/ai/runtime/token_counting.py`
- Create: `backend/tests/unit/test_runtime_token_counting.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/test_runtime_token_counting.py`:

```python
"""Tests for runtime/token_counting.py — tiktoken-backed counter."""
from app.services.ai.runtime.token_counting import tiktoken_counter


def test_returns_int_for_simple_string_message():
    msgs = ["hello world"]
    assert isinstance(tiktoken_counter(msgs), int)
    assert tiktoken_counter(msgs) > 0


def test_handles_empty_list():
    assert tiktoken_counter([]) == 0


def test_grows_monotonically_with_text_length():
    short = tiktoken_counter(["one two"])
    long = tiktoken_counter(["one two three four five six seven eight"])
    assert long > short


def test_handles_dict_messages_via_str():
    # ContextManagerCapability passes pydantic-ai message objects; counter
    # should at minimum not crash on dict-shaped inputs.
    msgs = [{"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "hi"}]}]
    assert tiktoken_counter(msgs) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_runtime_token_counting.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create the counter**

Create `backend/app/services/ai/runtime/token_counting.py`:

```python
"""Token counter for ContextManagerCapability.

Uses tiktoken's cl100k_base encoding (OpenAI/Anthropic-equivalent for
counting purposes). Falls back to a 4-chars/token heuristic if tiktoken
is unavailable or fails on a message shape.
"""
import json
from typing import Any

import tiktoken

_ENCODER = tiktoken.get_encoding("cl100k_base")


def tiktoken_counter(messages: list[Any]) -> int:
    """Estimate total tokens across a list of pydantic-ai messages.

    Each message may be a string, dict, or pydantic-ai ModelMessage object.
    Serializes each message and counts tokens in the resulting string.
    """
    total = 0
    for msg in messages:
        if isinstance(msg, str):
            text = msg
        elif isinstance(msg, dict):
            text = json.dumps(msg, default=str)
        else:
            # pydantic-ai message object: try .model_dump first, fall back to str
            try:
                text = json.dumps(msg.model_dump(mode="json"), default=str)
            except Exception:
                text = str(msg)
        try:
            total += len(_ENCODER.encode(text))
        except Exception:
            total += len(text) // 4
    return total
```

- [ ] **Step 4: Run test**

```bash
pytest tests/unit/test_runtime_token_counting.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/runtime/token_counting.py backend/tests/unit/test_runtime_token_counting.py
git commit -m "feat(ai): add tiktoken_counter for ContextManagerCapability"
```

**Rollback:** `git revert HEAD`.

---

## Task 11: Create `runtime/compaction.py` — CompactionState + hooks

**Goal:** Implement `CompactionState` (per-request capture object) and `make_compaction_hooks(state)` factory that returns the closures we'll wire into `ContextManagerCapability.on_before_compress` / `on_after_compress`. Audit data flows back via `state` to the orchestrator, which writes the `ChatMessage(role=SUMMARY)` row.

**Files:**
- Create: `backend/app/services/ai/runtime/compaction.py`
- Create: `backend/tests/unit/test_runtime_compaction.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/test_runtime_compaction.py`:

```python
"""Tests for runtime/compaction.py — CompactionState + capability hooks."""
from pydantic_ai.messages import ModelRequest, SystemPromptPart

from app.services.ai.runtime.compaction import (CompactionState,
                                                  make_compaction_hooks)


def test_initial_state_is_untriggered():
    s = CompactionState()
    assert s.triggered is False
    assert s.summary_text is None
    assert s.summarized_message_count == 0


def test_audit_metadata_when_untriggered_returns_empty_dict():
    s = CompactionState()
    assert s.audit_metadata() == {}


def test_on_before_marks_triggered_and_records_cutoff():
    s = CompactionState()
    on_before, _ = make_compaction_hooks(s)
    on_before(["msg1", "msg2", "msg3"], cutoff_index=2)
    assert s.triggered is True
    assert s.summarized_message_count == 2


def test_on_after_extracts_summary_from_first_message():
    s = CompactionState()
    _, on_after = make_compaction_hooks(s)
    summary_msg = ModelRequest(parts=[SystemPromptPart(content="conversation summary text")])
    result = on_after([summary_msg, "next-real-message"])
    assert s.summary_text == "conversation summary text"
    assert result is None  # we don't modify the summary


def test_on_after_handles_no_system_prompt_part_gracefully():
    s = CompactionState()
    _, on_after = make_compaction_hooks(s)
    on_after(["plain-string-no-parts"])
    # No exception, summary stays None
    assert s.summary_text is None


def test_audit_metadata_when_triggered():
    s = CompactionState()
    on_before, on_after = make_compaction_hooks(s)
    on_before(["a", "b", "c"], cutoff_index=2)
    summary_msg = ModelRequest(parts=[SystemPromptPart(content="sum")])
    on_after([summary_msg])
    meta = s.audit_metadata()
    assert meta["type"] == "summary"
    assert meta["summarized_message_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_runtime_compaction.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create the module**

Create `backend/app/services/ai/runtime/compaction.py`:

```python
"""Compaction state + hooks for ContextManagerCapability.

The capability's on_before_compress / on_after_compress callbacks are sync.
We capture state via closures into a CompactionState, then the orchestrator
inspects state after agent.run() returns and writes the audit
ChatMessage(role=SUMMARY) row. Avoids scheduling coroutines from sync hooks.
"""
from dataclasses import dataclass
from typing import Any, Callable

from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart


@dataclass
class CompactionState:
    """Per-request capture of compaction events."""
    summary_text: str | None = None
    summarized_message_count: int = 0
    triggered: bool = False

    def audit_metadata(self) -> dict[str, Any]:
        if not self.triggered:
            return {}
        return {
            "type": "summary",
            "summarized_message_count": self.summarized_message_count,
        }


def make_compaction_hooks(
    state: CompactionState,
) -> tuple[Callable[[list[ModelMessage], int], None], Callable[[list[ModelMessage]], str | None]]:
    """Return (on_before, on_after) closures for ContextManagerCapability."""

    def on_before(messages: list[ModelMessage], cutoff_index: int) -> None:
        state.triggered = True
        state.summarized_message_count = cutoff_index

    def on_after(messages: list[ModelMessage]) -> str | None:
        if messages:
            first = messages[0]
            if isinstance(first, ModelRequest):
                for part in first.parts:
                    if isinstance(part, SystemPromptPart):
                        state.summary_text = part.content
                        break
        return None  # don't modify the summary

    return on_before, on_after
```

- [ ] **Step 4: Run test**

```bash
pytest tests/unit/test_runtime_compaction.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/runtime/compaction.py backend/tests/unit/test_runtime_compaction.py
git commit -m "feat(ai): add runtime/compaction.py — CompactionState and hooks"
```

**Rollback:** `git revert HEAD`.

---

## Task 12: Write the prompt files

**Goal:** Lay down the markdown prompt files that the chat agent and subagents will load from disk.

**Files:**
- Modify: `backend/app/services/ai/prompts/chat_agent.md`
- Modify: `backend/app/services/ai/prompts/summarization.md`
- Modify: `backend/app/services/ai/subagents/research_library/prompt.md`
- Modify: `backend/app/services/ai/subagents/protocol_builder/prompt.md`
- Modify: `backend/app/services/ai/subagents/run_planner/prompt.md`

- [ ] **Step 1: Write the chat agent system prompt**

Replace the empty `backend/app/services/ai/prompts/chat_agent.md` contents with:

```markdown
You are Batchrite AI, a concise assistant for biotech Process Development scientists.

You orchestrate three specialists via the `task` tool:
- **research_library** — answers factual questions from the org's document library, returns synthesized answers with [1], [2] citations
- **protocol_builder** — multi-turn collaboration that ends in a draft Protocol artifact
- **run_planner** — gathers requirements for an upcoming run

RULES:
- Never show your reasoning, thought process, or `<think>` tags. Respond directly.
- Never show JSON, IDs, or tool schemas. Speak in plain language.
- Be concise. Use markdown for formatting.
- Cite sources with [1], [2] when using content from research_library.
- If research_library finds nothing, answer from general AI knowledge with this disclaimer:
  > ⚠️ This is from general AI knowledge, not your organization's documents. Verify independently.
- Never fabricate document titles or pretend info came from the library.

ROUTING:
- Factual question about something the org has documented? → `task("research_library", ...)`
- User wants to create a protocol? → `task("protocol_builder", ...)`
- User wants to plan a run? → `task("run_planner", ...)`
- General greeting / clarification / no domain action? → answer directly without dispatching

When invoking a subagent that previously asked the user a question, restate all
relevant prior context in your new `task()` prompt — the subagent has no memory
of earlier turns.
```

- [ ] **Step 2: Write the summarization prompt**

Replace `backend/app/services/ai/prompts/summarization.md`:

```markdown
Summarize the following conversation between a user and an AI assistant.

Preserve:
- Key decisions
- User preferences
- Protocols/experiments discussed
- Specific values and parameters mentioned
- Any unresolved questions

Be concise (2-3 paragraphs). Write in third person ("The user discussed...").
Do NOT include greetings, pleasantries, or meta-commentary about the summary itself.
```

- [ ] **Step 3: Write the research_library prompt**

Replace `backend/app/services/ai/subagents/research_library/prompt.md`:

```markdown
You are a research specialist for an organization's document library.

Your job:
- Use `search_documents` to find relevant content. If a query returns nothing,
  try paraphrasing or shortening it once before giving up.
- Use `read_section` when you need more context around a promising chunk.
- Use `list_documents` only when the user asks what's in the library.
- Synthesize a concise answer with [1], [2] citation markers referencing the
  chunks you used.
- Never fabricate sources. If nothing matches, say so plainly:
  "I couldn't find anything about this in the library."

Do not engage in conversation. Return a single synthesized answer to the
caller and stop.
```

- [ ] **Step 4: Write the protocol_builder prompt**

Replace `backend/app/services/ai/subagents/protocol_builder/prompt.md`:

```markdown
You are a protocol design specialist for biotech Process Development.

Goal: collaborate with the user to produce a draft Protocol record.

Steps:
1. Gather requirements: process type, scale, base document if any.
2. Use `list_unit_ops` to see the catalog. Do NOT show this list to the user
   verbatim — use it internally to pick step names.
3. Propose protocol steps one at a time. After each, wait for user confirmation
   in the parent conversation.
4. Once steps are confirmed, ask which project the protocol belongs in.
5. Use `list_projects` to confirm the project name resolves.
6. Call `create_protocol_from_spec` with the confirmed spec.
7. Confirm to the user that the draft protocol was created.

Behaviors:
- Ask ONE question per turn. Wait for the answer before continuing.
- Do not propose steps without confirming the prior step is correct.
- If you need facts from the org library mid-flow, dispatch to research_library
  via `task("research_library", "...")` rather than searching directly.
- Do not invent unit_op_names. Only use names that appear in `list_unit_ops`.
```

- [ ] **Step 5: Write the run_planner prompt (placeholder)**

Replace `backend/app/services/ai/subagents/run_planner/prompt.md`:

```markdown
(placeholder)

You are a run planning specialist. This subagent is a stub for now — the full
implementation will be defined in a follow-up task. Return a polite message
indicating the feature is not yet available.
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/prompts/ backend/app/services/ai/subagents/
git commit -m "feat(ai): add prompts for chat agent, summarizer, and three subagents"
```

**Rollback:** `git revert HEAD`.

---

## Task 13: Build `research_library` subagent

**Goal:** Move the three document tools out of `chat_service.py` into `subagents/research_library/tools.py`, and create the subagent's `build(model)` config function.

**Files:**
- Modify: `backend/app/services/ai/subagents/research_library/tools.py` (currently empty)
- Modify: `backend/app/services/ai/subagents/research_library/config.py` (currently empty)
- Modify: `backend/app/services/ai/subagents/research_library/__init__.py`
- Create: `backend/tests/unit/test_subagents_research_library.py`

- [ ] **Step 1: Write failing test for the tool functions**

Create `backend/tests/unit/test_subagents_research_library.py`:

```python
"""Tests for research_library subagent tools and config."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext

from app.services.ai.deps import ChatDeps, RetrievedChunk
from app.services.ai.subagents.research_library import build
from app.services.ai.subagents.research_library.tools import (list_documents,
                                                                read_section,
                                                                search_documents)


def make_ctx() -> RunContext[ChatDeps]:
    deps = ChatDeps(
        db=AsyncMock(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        is_org_admin=False,
    )
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps
    return ctx


def test_build_returns_subagent_config_with_required_fields():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "research_library"
    assert "description" in cfg
    assert "instructions" in cfg
    assert cfg["model"] == "openai:gpt-4.1-mini"
    tools = cfg["agent_kwargs"]["tools"]
    assert search_documents in tools
    assert read_section in tools
    assert list_documents in tools


@pytest.mark.asyncio
async def test_search_documents_appends_to_sources(monkeypatch):
    ctx = make_ctx()
    fake_chunks = [
        RetrievedChunk(
            document_id=uuid.uuid4(), document_title="t",
            chunk_id=uuid.uuid4(), chunk_index=0,
            page_number=None, content="c", score=0.5,
        ),
    ]

    async def fake_retrieve(*args, **kwargs):
        return fake_chunks

    monkeypatch.setattr(
        "app.services.ai.subagents.research_library.tools.retrieve_relevant_chunks",
        fake_retrieve,
    )
    result = await search_documents(ctx, query="hello")
    assert result.total == 1
    assert ctx.deps.sources == fake_chunks
    assert ctx.deps.tool_calls[-1]["tool"] == "search_documents"
    assert ctx.deps.tool_calls[-1]["subagent"] == "research_library"


@pytest.mark.asyncio
async def test_search_documents_returns_no_results_message_when_empty(monkeypatch):
    ctx = make_ctx()

    async def fake_retrieve(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "app.services.ai.subagents.research_library.tools.retrieve_relevant_chunks",
        fake_retrieve,
    )
    result = await search_documents(ctx, query="hello")
    assert result.total == 0
    assert "No matching" in result.message
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_subagents_research_library.py -v
```

Expected: FAIL — module/function not defined.

- [ ] **Step 3: Implement `tools.py`**

Replace `backend/app/services/ai/subagents/research_library/tools.py` with:

```python
"""Document research tools — used only by the research_library subagent."""
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy import text as sa_text

from app.services.ai.deps import ChatDeps, RetrievedChunk
from app.services.documents.retrieval import retrieve_relevant_chunks


# ─── Result models ───

class DocumentChunkResult(BaseModel):
    document_id: str
    document_title: str
    chunk_index: int
    page_number: int | None
    relevance: float
    content: str


class SearchDocumentsResult(BaseModel):
    results: list[DocumentChunkResult]
    total: int
    message: str


class SectionChunk(BaseModel):
    chunk_index: int
    page_number: int | None
    content: str
    is_target: bool


class DocumentSectionResult(BaseModel):
    document_id: str
    document_title: str
    chunks: list[SectionChunk]


class DocumentListItem(BaseModel):
    document_id: str
    title: str
    status: str
    page_count: int | None


class ListDocumentsResult(BaseModel):
    documents: list[DocumentListItem]
    total: int
    message: str


# ─── Tool functions (thin) ───

async def search_documents(
    ctx: RunContext[ChatDeps], query: str, max_results: int = 5,
) -> SearchDocumentsResult:
    """Search the organization's document library for relevant content."""
    chunks = await retrieve_relevant_chunks(
        ctx.deps.db, query=query, org_id=ctx.deps.org_id, top_k=max_results,
    )
    ctx.deps.sources.extend(chunks)
    ctx.deps.tool_calls.append({
        "tool": "search_documents",
        "subagent": "research_library",
        "query": query,
        "results": len(chunks),
    })
    return SearchDocumentsResult(
        results=[
            DocumentChunkResult(
                document_id=str(c.document_id), document_title=c.document_title,
                chunk_index=c.chunk_index, page_number=c.page_number,
                relevance=c.score, content=c.content,
            )
            for c in chunks
        ],
        total=len(chunks),
        message=f"Found {len(chunks)} results" if chunks
        else "No matching documents found in the library",
    )


async def read_section(
    ctx: RunContext[ChatDeps],
    document_id: str,
    chunk_index: int,
    window: int = 2,
) -> DocumentSectionResult:
    """Read a section of a document by fetching chunks around a given index.

    Use after search_documents finds a chunk and you need more context.
    """
    result = await ctx.deps.db.execute(
        sa_text("""
            SELECT dc.id AS chunk_id, dc.document_id, dc.chunk_index,
                   dc.content, dc.page_number, d.title AS document_title
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.document_id = :doc_id
              AND d.org_id = :org_id
              AND dc.chunk_index BETWEEN :start AND :end
            ORDER BY dc.chunk_index
        """),
        {
            "doc_id": document_id,
            "org_id": str(ctx.deps.org_id),
            "start": max(0, chunk_index - window),
            "end": chunk_index + window,
        },
    )
    rows = result.fetchall()
    if not rows:
        return DocumentSectionResult(
            document_id=document_id, document_title="Unknown", chunks=[],
        )
    for row in rows:
        ctx.deps.sources.append(RetrievedChunk(
            document_id=row.document_id, document_title=row.document_title,
            chunk_id=row.chunk_id, chunk_index=row.chunk_index,
            page_number=row.page_number, content=row.content, score=1.0,
        ))
    ctx.deps.tool_calls.append({
        "tool": "read_section",
        "subagent": "research_library",
        "document_id": document_id,
        "chunk_index": chunk_index,
        "window": window,
        "results": len(rows),
    })
    return DocumentSectionResult(
        document_id=document_id,
        document_title=rows[0].document_title,
        chunks=[
            SectionChunk(
                chunk_index=row.chunk_index, page_number=row.page_number,
                content=row.content, is_target=row.chunk_index == chunk_index,
            )
            for row in rows
        ],
    )


async def list_documents(ctx: RunContext[ChatDeps]) -> ListDocumentsResult:
    """List documents in the organization's library."""
    result = await ctx.deps.db.execute(
        sa_text("""
            SELECT id, title, status, page_count
            FROM documents
            WHERE org_id = :org_id
            ORDER BY created_at DESC
            LIMIT 50
        """),
        {"org_id": str(ctx.deps.org_id)},
    )
    rows = result.fetchall()
    ctx.deps.tool_calls.append({
        "tool": "list_documents",
        "subagent": "research_library",
        "results": len(rows),
    })
    return ListDocumentsResult(
        documents=[
            DocumentListItem(
                document_id=str(row.id), title=row.title,
                status=row.status, page_count=row.page_count,
            )
            for row in rows
        ],
        total=len(rows),
        message=f"{len(rows)} documents in the library" if rows
        else "No documents have been uploaded to the library yet",
    )
```

- [ ] **Step 4: Implement `config.py`**

Replace `backend/app/services/ai/subagents/research_library/config.py` with:

```python
"""research_library SubAgentConfig builder.

Built per-request so the model resolves per-org via ai_config.
"""
from pathlib import Path
from typing import Any

from subagents_pydantic_ai import SubAgentConfig

from .tools import list_documents, read_section, search_documents

_PROMPT = (Path(__file__).parent / "prompt.md").read_text()


def build(model: Any) -> SubAgentConfig:
    return {
        "name": "research_library",
        "description": (
            "Use when the user asks a factual question that the organization's "
            "documents could answer. Returns a synthesized answer with [1], [2] "
            "citations referencing chunks. Do not use for general knowledge."
        ),
        "instructions": _PROMPT,
        "model": model,
        "agent_kwargs": {
            "tools": [search_documents, read_section, list_documents],
        },
        "typically_needs_context": True,
    }
```

- [ ] **Step 5: Update `__init__.py`**

Replace `backend/app/services/ai/subagents/research_library/__init__.py`:

```python
from .config import build

__all__ = ["build"]
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/unit/test_subagents_research_library.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai/subagents/research_library/ backend/tests/unit/test_subagents_research_library.py
git commit -m "feat(ai): add research_library subagent (config, tools)"
```

**Rollback:** `git revert HEAD`.

---

## Task 14: Build `protocol_builder` subagent

**Goal:** Move the three protocol/unit-op tools out of `chat_service.py` into `subagents/protocol_builder/tools.py` as **thin wrappers** over the new services. Add the subagent config.

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_builder/tools.py`
- Modify: `backend/app/services/ai/subagents/protocol_builder/config.py`
- Modify: `backend/app/services/ai/subagents/protocol_builder/__init__.py`
- Create: `backend/tests/unit/test_subagents_protocol_builder.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/test_subagents_protocol_builder.py`:

```python
"""Tests for protocol_builder subagent tools and config."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext

from app.services.ai.deps import ChatDeps
from app.services.ai.subagents.protocol_builder import build
from app.services.ai.subagents.protocol_builder.tools import (
    create_protocol, create_unit_op, list_unit_ops,
)


def make_ctx() -> RunContext[ChatDeps]:
    deps = ChatDeps(
        db=AsyncMock(), org_id=uuid.uuid4(),
        user_id=uuid.uuid4(), is_org_admin=False,
    )
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps
    return ctx


def test_build_returns_subagent_config():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "protocol_builder"
    assert cfg["model"] == "openai:gpt-4.1-mini"
    tools = cfg["agent_kwargs"]["tools"]
    assert list_unit_ops in tools
    assert create_unit_op in tools
    assert create_protocol in tools


@pytest.mark.asyncio
async def test_create_unit_op_delegates_to_service(monkeypatch):
    ctx = make_ctx()
    called = {}

    async def fake_service(*args, **kwargs):
        called.update(kwargs)
        op = MagicMock()
        op.id = uuid.uuid4()
        op.name = kwargs["name"]
        op.category = kwargs["category"]
        return op

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.create_unit_op_definition",
        fake_service,
    )
    result = await create_unit_op(
        ctx, name="X", category="C", description="D",
        param_schema={}, scope="org",
    )
    assert called["name"] == "X"
    assert called["scope"] == "org"
    assert result.name == "X"
    assert ctx.deps.tool_calls[-1]["tool"] == "create_unit_op"


@pytest.mark.asyncio
async def test_create_protocol_delegates_to_service(monkeypatch):
    ctx = make_ctx()
    fake_protocol = MagicMock()
    fake_protocol.id = uuid.uuid4()
    fake_protocol.name = "P"
    fake_protocol.project_id = uuid.uuid4()

    async def fake_service(*args, **kwargs):
        return fake_protocol

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.create_protocol_from_spec_service",
        fake_service,
    )
    result = await create_protocol(
        ctx, project_name="proj", protocol_name="P",
        protocol_description="D",
        steps_text="Step1 | Op1 | 10",
    )
    assert result.protocol_id == str(fake_protocol.id)
    assert ctx.deps.tool_calls[-1]["tool"] == "create_protocol"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_subagents_protocol_builder.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `tools.py`**

Replace `backend/app/services/ai/subagents/protocol_builder/tools.py` with:

```python
"""Protocol building tools — used only by the protocol_builder subagent.

These are THIN wrappers over services. No business logic in tool bodies.
"""
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy import select

from app.models.science import UnitOpDefinition
from app.services.ai.deps import ChatDeps
from app.services.protocols.creation import (ProtocolSpec, ProtocolStep,
                                              create_protocol_from_spec as
                                              create_protocol_from_spec_service)
from app.services.protocols.unit_ops import (create_unit_op_definition as
                                              create_unit_op_definition_service)


# ─── Result models ───

class UnitOpInfo(BaseModel):
    name: str
    category: str


class ListUnitOpsResult(BaseModel):
    unit_ops: list[UnitOpInfo]
    total: int
    message: str


class CreateUnitOpResult(BaseModel):
    id: str
    name: str
    category: str


class CreateProtocolResult(BaseModel):
    protocol_id: str
    protocol_name: str
    project_id: str


# ─── Tool functions (thin) ───

async def list_unit_ops(ctx: RunContext[ChatDeps]) -> ListUnitOpsResult:
    """List available unit operation names and categories.

    Returns a SHORT list of names only. Use to pick the right unit op for
    each protocol step. Do NOT show this list to the user verbatim.
    """
    result = await ctx.deps.db.execute(
        select(UnitOpDefinition)
        .where(
            (UnitOpDefinition.organization_id == ctx.deps.org_id)
            | (UnitOpDefinition.organization_id.is_(None))
        )
        .order_by(UnitOpDefinition.category)
    )
    ops = result.scalars().all()
    ctx.deps.tool_calls.append({
        "tool": "list_unit_ops", "subagent": "protocol_builder",
        "results": len(ops),
    })
    return ListUnitOpsResult(
        unit_ops=[UnitOpInfo(name=op.name, category=op.category) for op in ops],
        total=len(ops),
        message="Use these names when proposing protocol steps. "
                "Do not show this list to the user.",
    )


async def create_unit_op(
    ctx: RunContext[ChatDeps],
    name: str,
    category: str,
    description: str,
    param_schema: dict,
    scope: str = "project",
    project_id: str | None = None,
) -> CreateUnitOpResult:
    """Create a custom unit operation definition. Only after user approval."""
    op = await create_unit_op_definition_service(
        ctx.deps.db,
        user_id=ctx.deps.user_id,
        org_id=ctx.deps.org_id,
        is_org_admin=ctx.deps.is_org_admin,
        scope=scope,
        project_id=UUID(project_id) if project_id else None,
        name=name, category=category, description=description,
        param_schema=param_schema,
    )
    ctx.deps.tool_calls.append({
        "tool": "create_unit_op", "subagent": "protocol_builder",
        "unit_op_id": str(op.id), "name": name,
    })
    return CreateUnitOpResult(id=str(op.id), name=op.name, category=op.category)


async def create_protocol(
    ctx: RunContext[ChatDeps],
    project_name: str,
    protocol_name: str,
    protocol_description: str,
    steps_text: str,
) -> CreateProtocolResult:
    """Create a protocol in a project from a confirmed step list.

    steps_text format: one step per line: "step_name | unit_op_name | duration_min"
    Example: "Dissolve Tris | Buffer Preparation | 15"
    """
    parsed: list[ProtocolStep] = []
    for line in steps_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        step_name = parts[0] if len(parts) > 0 else "Step"
        unit_op_name = parts[1] if len(parts) > 1 else parts[0]
        duration = 30
        if len(parts) > 2:
            try:
                duration = int(parts[2])
            except ValueError:
                pass
        parsed.append(ProtocolStep(
            name=step_name, unit_op_name=unit_op_name, duration_min=duration,
        ))

    spec = ProtocolSpec(
        name=protocol_name, description=protocol_description, steps=parsed,
    )
    protocol = await create_protocol_from_spec_service(
        ctx.deps.db, user_id=ctx.deps.user_id,
        project_name=project_name, spec=spec,
    )
    ctx.deps.tool_calls.append({
        "tool": "create_protocol", "subagent": "protocol_builder",
        "protocol_id": str(protocol.id),
        "project_id": str(protocol.project_id),
    })
    return CreateProtocolResult(
        protocol_id=str(protocol.id),
        protocol_name=protocol.name,
        project_id=str(protocol.project_id),
    )
```

- [ ] **Step 4: Implement `config.py`**

Replace `backend/app/services/ai/subagents/protocol_builder/config.py` with:

```python
"""protocol_builder SubAgentConfig builder."""
from pathlib import Path
from typing import Any

from subagents_pydantic_ai import SubAgentConfig

from .tools import create_protocol, create_unit_op, list_unit_ops

_PROMPT = (Path(__file__).parent / "prompt.md").read_text()


def build(model: Any) -> SubAgentConfig:
    return {
        "name": "protocol_builder",
        "description": (
            "Use when the user wants to create a protocol. Multi-turn flow "
            "that ends with a draft Protocol record. Asks one question at a "
            "time. Does not search documents — dispatches to research_library "
            "if facts are needed."
        ),
        "instructions": _PROMPT,
        "model": model,
        "agent_kwargs": {
            "tools": [list_unit_ops, create_unit_op, create_protocol],
        },
        "typically_needs_context": True,
    }
```

- [ ] **Step 5: Update `__init__.py`**

Replace `backend/app/services/ai/subagents/protocol_builder/__init__.py`:

```python
from .config import build

__all__ = ["build"]
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/unit/test_subagents_protocol_builder.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_builder/ backend/tests/unit/test_subagents_protocol_builder.py
git commit -m "feat(ai): add protocol_builder subagent (thin tools over services)"
```

**Rollback:** `git revert HEAD`.

---

## Task 15: Stub `run_planner` subagent

**Goal:** Placeholder so the architecture is whole. Return a polite "not yet available" message.

**Files:**
- Modify: `backend/app/services/ai/subagents/run_planner/tools.py`
- Modify: `backend/app/services/ai/subagents/run_planner/config.py`
- Modify: `backend/app/services/ai/subagents/run_planner/__init__.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/unit/test_subagents_research_library.py` or create `backend/tests/unit/test_subagents_run_planner.py`:

```python
"""Tests for run_planner stub."""
from app.services.ai.subagents.run_planner import build


def test_build_returns_placeholder_subagent_config():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "run_planner"
    assert "(placeholder)" in cfg["instructions"].lower() or \
           "not yet" in cfg["instructions"].lower()
    # Stub has no domain tools yet
    assert cfg["agent_kwargs"].get("tools", []) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_subagents_run_planner.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement stub `tools.py`**

Replace `backend/app/services/ai/subagents/run_planner/tools.py` with:

```python
"""Placeholder — run_planner subagent has no tools yet."""
```

- [ ] **Step 4: Implement `config.py`**

Replace `backend/app/services/ai/subagents/run_planner/config.py` with:

```python
"""run_planner SubAgentConfig builder (placeholder)."""
from pathlib import Path
from typing import Any

from subagents_pydantic_ai import SubAgentConfig

_PROMPT = (Path(__file__).parent / "prompt.md").read_text()


def build(model: Any) -> SubAgentConfig:
    return {
        "name": "run_planner",
        "description": (
            "(Placeholder) Use when the user wants to plan a run. "
            "Currently returns a not-yet-available message."
        ),
        "instructions": _PROMPT,
        "model": model,
        "agent_kwargs": {
            "tools": [],
        },
    }
```

- [ ] **Step 5: Update `__init__.py`**

Replace `backend/app/services/ai/subagents/run_planner/__init__.py`:

```python
from .config import build

__all__ = ["build"]
```

- [ ] **Step 6: Update `subagents/__init__.py`**

Replace `backend/app/services/ai/subagents/__init__.py`:

```python
"""Chat agent subagent registry."""
from . import protocol_builder, research_library, run_planner

__all__ = ["protocol_builder", "research_library", "run_planner"]
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/unit/test_subagents_run_planner.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/ai/subagents/run_planner/ backend/app/services/ai/subagents/__init__.py backend/tests/unit/test_subagents_run_planner.py
git commit -m "feat(ai): stub run_planner subagent (placeholder)"
```

**Rollback:** `git revert HEAD`.

---

## Task 16: Build `chat_agent.py` factory

**Goal:** The Agent factory that composes capabilities + subagents. Returns a fresh `Agent` per request scope (globalization is Task 23).

**Files:**
- Modify: `backend/app/services/ai/chat_agent.py` (currently empty or absent)
- Create: `backend/tests/unit/test_chat_agent_factory.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/test_chat_agent_factory.py`:

```python
"""Tests for chat_agent.build_chat_agent — construction without LLM call."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.chat_agent import build_chat_agent
from app.services.ai.runtime.compaction import CompactionState


@pytest.mark.asyncio
async def test_build_chat_agent_returns_agent_with_capabilities():
    db = MagicMock()
    org_id = MagicMock()
    state = CompactionState()

    fake_chat_model = "openai:gpt-4.1-mini"
    fake_subagent_model = "openai:gpt-4.1-mini"
    fake_summary_model = "openai:gpt-4.1-mini"

    async def fake_get_model(cap, db_, org_id_=None):
        return {
            "chat": fake_chat_model,
            "chat_subagent": fake_subagent_model,
            "chat_summary": fake_summary_model,
        }[cap]

    async def fake_get_context_window(cap, db_, org_id_=None):
        return 100_000

    with patch("app.services.ai.chat_agent.get_model", fake_get_model), \
         patch("app.services.ai.chat_agent.get_context_window", fake_get_context_window):
        agent = await build_chat_agent(db, org_id, state)
    # Agent constructed without raising; that's the contract for this unit test.
    assert agent is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_chat_agent_factory.py -v
```

Expected: FAIL — `chat_agent.build_chat_agent` not defined or signature mismatch.

- [ ] **Step 3: Implement `chat_agent.py`**

Create/replace `backend/app/services/ai/chat_agent.py`:

```python
"""Chat agent factory — composes capabilities + subagents.

Returns a fresh Agent per request scope. Globalization is in Task 23.
"""
from pathlib import Path
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai_summarization import ContextManagerCapability
from sqlalchemy.ext.asyncio import AsyncSession
from subagents_pydantic_ai import SubAgentCapability

from app.core.config import settings
from app.services.ai.ai_config import get_context_window, get_model
from app.services.ai.deps import ChatDeps
from app.services.ai.runtime.compaction import (CompactionState,
                                                  make_compaction_hooks)
from app.services.ai.runtime.token_counting import tiktoken_counter
from app.services.ai.subagents import (protocol_builder, research_library,
                                         run_planner)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_CHAT_PROMPT = (_PROMPTS_DIR / "chat_agent.md").read_text()
_SUMMARY_PROMPT = (_PROMPTS_DIR / "summarization.md").read_text()


async def build_chat_agent(
    db: AsyncSession,
    org_id: UUID,
    compaction_state: CompactionState,
) -> Agent[ChatDeps, str]:
    """Build the chat agent for a given org's request scope."""
    chat_model     = await get_model("chat",          db, org_id=org_id)
    subagent_model = await get_model("chat_subagent", db, org_id=org_id)
    summary_model  = await get_model("chat_summary",  db, org_id=org_id)
    context_window = await get_context_window("chat", db, org_id=org_id)

    subagents = [
        research_library.build(subagent_model),
        protocol_builder.build(subagent_model),
        run_planner.build(subagent_model),
    ]

    on_before, on_after = make_compaction_hooks(compaction_state)

    return Agent(
        chat_model,
        instructions=_CHAT_PROMPT,
        deps_type=ChatDeps,
        capabilities=[
            SubAgentCapability(
                subagents=subagents,
                max_nesting_depth=1,
            ),
            ContextManagerCapability(
                max_tokens=context_window,
                compress_threshold=settings.compaction_threshold,
                summarization_model=summary_model,
                summary_prompt=_SUMMARY_PROMPT,
                max_tool_output_tokens=2000,
                token_counter=tiktoken_counter,
                on_before_compress=on_before,
                on_after_compress=on_after,
            ),
        ],
        tools=[],
    )
```

- [ ] **Step 4: Run test**

```bash
pytest tests/unit/test_chat_agent_factory.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/chat_agent.py backend/tests/unit/test_chat_agent_factory.py
git commit -m "feat(ai): add chat_agent factory composing capabilities and subagents"
```

**Rollback:** `git revert HEAD`.

---

## Task 17: Build `sessions.py`

**Goal:** Extract session CRUD out of `chat_service.py` into `sessions.py`. Existing callers continue to work via `chat_service` re-exports.

**Files:**
- Modify: `backend/app/services/ai/sessions.py` (currently empty/absent)
- Create: `backend/tests/unit/test_sessions.py`
- Modify: `backend/app/services/ai/chat_service.py` (re-export shim)

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/test_sessions.py`:

```python
"""Tests for the extracted sessions module."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.services.ai.sessions import (create_session, delete_session,
                                       get_session, list_sessions)


@pytest.mark.asyncio
async def test_creates_session_with_default_title(
    db_session: AsyncSession, test_user: User, test_org: Organization,
):
    session = await create_session(
        db_session, user_id=test_user.id, org_id=test_org.id,
    )
    assert session.title == "New Chat"
    assert session.user_id == test_user.id


@pytest.mark.asyncio
async def test_get_session_returns_none_for_missing(
    db_session: AsyncSession,
):
    result = await get_session(db_session, uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_list_sessions_returns_user_sessions(
    db_session: AsyncSession, test_user: User, test_org: Organization,
):
    await create_session(db_session, user_id=test_user.id, org_id=test_org.id)
    await create_session(db_session, user_id=test_user.id, org_id=test_org.id)
    sessions, total = await list_sessions(
        db_session, user_id=test_user.id, org_id=test_org.id,
    )
    assert total >= 2
    assert all(s.user_id == test_user.id for s in sessions)


@pytest.mark.asyncio
async def test_delete_removes_session(
    db_session: AsyncSession, test_user: User, test_org: Organization,
):
    session = await create_session(db_session, user_id=test_user.id, org_id=test_org.id)
    await delete_session(db_session, session)
    refetched = await get_session(db_session, session.id)
    assert refetched is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_sessions.py -v
```

Expected: FAIL — module/functions not defined.

- [ ] **Step 3: Implement `sessions.py`**

Create/replace `backend/app/services/ai/sessions.py`:

```python
"""ChatSession CRUD — pure DB operations, no LLM."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat import ChatSession, ChatSessionStatus


async def create_session(
    db: AsyncSession,
    user_id: UUID,
    org_id: UUID,
    title: Optional[str] = None,
    context_document_ids: Optional[list[UUID]] = None,
) -> ChatSession:
    session = ChatSession(
        user_id=user_id,
        org_id=org_id,
        title=title or "New Chat",
        context_document_ids=[str(did) for did in context_document_ids]
        if context_document_ids
        else None,
    )
    db.add(session)
    await db.flush()
    return session


async def get_session(
    db: AsyncSession, session_id: UUID,
) -> Optional[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    )
    return result.scalar_one_or_none()


async def list_sessions(
    db: AsyncSession,
    user_id: UUID,
    org_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ChatSession], int]:
    base_query = select(ChatSession).where(
        ChatSession.user_id == user_id,
        ChatSession.org_id == org_id,
        ChatSession.status == ChatSessionStatus.ACTIVE,
    )
    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar_one()
    result = await db.execute(
        base_query.order_by(ChatSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def delete_session(db: AsyncSession, session: ChatSession) -> None:
    await db.delete(session)
    await db.flush()
```

- [ ] **Step 4: Update `chat_service.py` to re-export**

In `backend/app/services/ai/chat_service.py`, replace the existing `create_session`, `get_session`, `list_sessions`, `delete_session` definitions with:

```python
# Sessions moved to sessions.py during TD-0081 migration.
from app.services.ai.sessions import (  # noqa: F401
    create_session, delete_session, get_session, list_sessions,
)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_sessions.py tests/unit/test_chat_service.py tests/integration/test_chat_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/sessions.py backend/tests/unit/test_sessions.py backend/app/services/ai/chat_service.py
git commit -m "refactor(ai): extract session CRUD to sessions.py"
```

**Rollback:** `git revert HEAD`.

---

## Task 18: Build `send_message.py` orchestration

**Goal:** Replace the `send_message` + `_call_llm` orchestration with the new flow that uses the harness-shaped agent and writes audit summary rows from `CompactionState`.

**Files:**
- Modify: `backend/app/services/ai/send_message.py`
- Create: `backend/tests/unit/test_send_message.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/test_send_message.py`:

```python
"""Tests for send_message.send_message — orchestration without LLM call."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessageRole, ChatSessionStatus
from app.models.iam import Organization, User
from app.services.ai.send_message import send_message
from app.services.ai.sessions import create_session


@pytest_asyncio.fixture
async def session(db_session, test_user, test_org):
    s = await create_session(
        db_session, user_id=test_user.id, org_id=test_org.id,
    )
    return s


@pytest.mark.asyncio
async def test_persists_user_and_assistant_messages(
    db_session: AsyncSession, test_user: User, test_org: Organization, session,
):
    fake_run_result = MagicMock()
    fake_run_result.output = "Hello back"
    fake_run_result.all_messages = MagicMock(return_value=[])

    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(return_value=fake_run_result)

    async def fake_build(*args, **kwargs):
        return fake_agent

    with patch("app.services.ai.send_message.build_chat_agent", fake_build):
        user_msg, assistant_msg, sources = await send_message(
            db_session, session, "Hello",
            user_id=test_user.id, is_org_admin=False,
        )
    assert user_msg.role == ChatMessageRole.USER
    assert user_msg.content == "Hello"
    assert assistant_msg.role == ChatMessageRole.ASSISTANT
    assert assistant_msg.content == "Hello back"
    assert sources == []


@pytest.mark.asyncio
async def test_writes_summary_row_when_compaction_triggered(
    db_session: AsyncSession, test_user: User, test_org: Organization, session,
):
    fake_run_result = MagicMock()
    fake_run_result.output = "ok"
    fake_run_result.all_messages = MagicMock(return_value=[])

    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(return_value=fake_run_result)

    captured_state = {}

    async def fake_build(db, org_id, compaction_state):
        # Simulate compaction firing during the run
        compaction_state.triggered = True
        compaction_state.summary_text = "summarized text"
        compaction_state.summarized_message_count = 5
        captured_state["state"] = compaction_state
        return fake_agent

    from sqlalchemy import select

    from app.models.chat import ChatMessage
    with patch("app.services.ai.send_message.build_chat_agent", fake_build):
        await send_message(
            db_session, session, "Hello",
            user_id=test_user.id, is_org_admin=False,
        )

    res = await db_session.execute(
        select(ChatMessage).where(
            ChatMessage.session_id == session.id,
            ChatMessage.role == ChatMessageRole.SUMMARY,
        )
    )
    summaries = list(res.scalars().all())
    assert len(summaries) == 1
    assert summaries[0].content == "summarized text"
    assert summaries[0].metadata_["summarized_message_count"] == 5


@pytest.mark.asyncio
async def test_auto_titles_on_first_message(
    db_session: AsyncSession, test_user: User, test_org: Organization, session,
):
    assert session.title == "New Chat"

    fake_run_result = MagicMock()
    fake_run_result.output = "ok"
    fake_run_result.all_messages = MagicMock(return_value=[])

    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(return_value=fake_run_result)

    async def fake_build(*args, **kwargs):
        return fake_agent

    with patch("app.services.ai.send_message.build_chat_agent", fake_build):
        await send_message(
            db_session, session, "First user message",
            user_id=test_user.id, is_org_admin=False,
        )
    await db_session.refresh(session)
    assert session.title == "First user message"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_send_message.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `send_message.py`**

Create/replace `backend/app/services/ai/send_message.py`:

```python
"""Send-message orchestration: build agent → run → persist."""
import logging
from typing import Any
from uuid import UUID

from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import (ChatMessage, ChatMessageRole, ChatSession)
from app.services.ai.chat_agent import build_chat_agent
from app.services.ai.deps import ChatDeps, RetrievedChunk
from app.services.ai.runtime.compaction import CompactionState
from app.services.ai.runtime.sanitize import sanitize_output

logger = logging.getLogger(__name__)


async def send_message(
    db: AsyncSession,
    session: ChatSession,
    user_content: str,
    user_id: UUID,
    is_org_admin: bool,
) -> tuple[ChatMessage, ChatMessage, list[RetrievedChunk]]:
    """Send a user message and return (user_msg, assistant_msg, sources)."""
    # 1. Persist user message
    user_msg = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.USER,
        content=user_content,
    )
    db.add(user_msg)
    await db.flush()
    if session.title == "New Chat":
        session.title = user_content[:100].strip()
        await db.flush()

    # 2. Build deps + compaction state
    state = CompactionState()
    deps = ChatDeps(
        db=db, org_id=session.org_id,
        user_id=user_id, is_org_admin=is_org_admin,
    )

    # 3. Build agent and run
    agent = await build_chat_agent(db, session.org_id, state)
    message_history = None
    if session.ai_message_history:
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(
                session.ai_message_history,
            )
        except Exception:
            logger.warning(
                "Failed to deserialize ai_message_history; starting fresh",
            )

    result = await agent.run(
        user_content,
        deps=deps,
        message_history=message_history,
    )

    # 4. Write audit summary row if compaction triggered
    if state.triggered and state.summary_text:
        summary_msg = ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.SUMMARY,
            content=state.summary_text,
            metadata_=state.audit_metadata(),
        )
        db.add(summary_msg)
        await db.flush()

    # 5. Persist new history + assistant message
    session.ai_message_history = ModelMessagesTypeAdapter.dump_python(
        result.all_messages(), mode="json",
    )

    seen_ids: set = set()
    unique_sources: list[RetrievedChunk] = []
    for s in deps.sources:
        if s.chunk_id not in seen_ids:
            seen_ids.add(s.chunk_id)
            unique_sources.append(s)

    metadata: dict[str, Any] = {}
    if unique_sources:
        metadata["sources"] = [
            {
                "document_id": str(s.document_id),
                "document_title": s.document_title,
                "chunk_id": str(s.chunk_id),
                "chunk_index": s.chunk_index,
                "page_number": s.page_number,
                "score": s.score,
                "snippet": s.content[:200],
            }
            for s in unique_sources
        ]
    if deps.tool_calls:
        metadata["tool_calls"] = deps.tool_calls

    assistant_msg = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.ASSISTANT,
        content=sanitize_output(result.output),
        metadata_=metadata or None,
    )
    db.add(assistant_msg)
    await db.flush()
    return user_msg, assistant_msg, unique_sources
```

- [ ] **Step 4: Run test**

```bash
pytest tests/unit/test_send_message.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/send_message.py backend/tests/unit/test_send_message.py
git commit -m "feat(ai): add send_message orchestration with audit-row writing"
```

**Rollback:** `git revert HEAD`.

---

## Task 19: Cutover `api/endpoints/chat.py` to new modules

**Goal:** Switch the HTTP layer from `chat_service.send_message` to the new `send_message.send_message`. Update `services/ai/__init__.py` to export the new public API.

**Files:**
- Modify: `backend/app/services/ai/__init__.py`
- Modify: `backend/app/api/endpoints/chat.py`

- [ ] **Step 1: Update `services/ai/__init__.py`**

Replace `backend/app/services/ai/__init__.py`:

```python
"""Public API for the chat agent.

Endpoints import these names — keep them stable across refactors.
"""
from app.services.ai.send_message import send_message
from app.services.ai.sessions import (create_session, delete_session,
                                       get_session, list_sessions)

__all__ = [
    "send_message",
    "create_session", "get_session", "list_sessions", "delete_session",
]
```

- [ ] **Step 2: Update `api/endpoints/chat.py` imports**

In `backend/app/api/endpoints/chat.py`, replace:

```python
from app.services.ai import chat_service
```

with:

```python
from app.services.ai import (create_session, delete_session, get_session,
                              list_sessions, send_message)
```

Then replace each `chat_service.<func>(...)` call with `<func>(...)`. Specifically:

- `chat_service.create_session(...)` → `create_session(...)`
- `chat_service.get_session(...)` → `get_session(...)`
- `chat_service.list_sessions(...)` → `list_sessions(...)`
- `chat_service.delete_session(...)` → `delete_session(...)`
- `chat_service.send_message(...)` → `send_message(...)`

Also: the new `send_message` does **not** accept `skill_inject`. Find the lines that compute `skill_inject` in the endpoint and remove them. The `body.skill_id` on `ChatMessageCreate` becomes unused but stays on the schema — frontend still sends it. Future task can remove from the schema if desired.

- [ ] **Step 3: Run integration tests**

```bash
pytest tests/integration/test_chat_api.py -v
```

Expected: PASS — endpoint behavior preserved.

- [ ] **Step 4: Run full test suite to confirm no regression**

```bash
pytest -q
```

Expected: same passing count as pre-flight (or higher, due to new tests added in Tasks 5-18).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/__init__.py backend/app/api/endpoints/chat.py
git commit -m "refactor(ai): cutover chat endpoint to new send_message + sessions modules"
```

**Rollback:** `git revert HEAD`.

---

## Task 20: Delete `chat_service.py`

**Goal:** With all callers migrated, the monolithic `chat_service.py` (now mostly re-export shims) can be deleted.

**Files:**
- Delete: `backend/app/services/ai/chat_service.py`
- Delete: `backend/tests/unit/test_chat_service.py` (the tests covered code that has moved; coverage now lives in test_sessions, test_runtime_*, test_subagents_*, test_send_message)
- Modify: any other importers (verify none)

- [ ] **Step 1: Confirm no imports remain**

```bash
grep -rln "from app.services.ai.chat_service\|from app.services.ai import chat_service" backend/app backend/tests backend/scripts
```

Expected: no output (empty result). If any results appear, update those callers to use the new modules from `app.services.ai`.

- [ ] **Step 2: Delete the files**

```bash
git rm backend/app/services/ai/chat_service.py
git rm backend/tests/unit/test_chat_service.py
```

- [ ] **Step 3: Run full test suite**

```bash
pytest -q
```

Expected: PASS — no test failures.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(ai): delete monolithic chat_service.py — fully migrated to new structure"
```

**Rollback:** `git revert HEAD` (restores both files).

---

## Task 21: Move `sop_generator.py` and `protocol_generator.py` to `workflows/`

**Goal:** Both files relocate under `services/ai/workflows/`. Add the disposition header to `protocol_generator.py`. Update import paths in callers.

**Files:**
- Move: `backend/app/services/ai/sop_generator.py` → `backend/app/services/ai/workflows/sop_generator.py`
- Move: `backend/app/services/ai/protocol_generator.py` → `backend/app/services/ai/workflows/protocol_generator.py`
- Modify: `backend/app/services/documents/pdf.py` (import path)
- Modify: `backend/app/services/protocols/creation.py` (import path)

- [ ] **Step 1: Move with git**

```bash
cd backend
git mv app/services/ai/sop_generator.py app/services/ai/workflows/sop_generator.py
git mv app/services/ai/protocol_generator.py app/services/ai/workflows/protocol_generator.py
```

- [ ] **Step 2: Add disposition header to `protocol_generator.py`**

Open `backend/app/services/ai/workflows/protocol_generator.py` and replace the file's existing top docstring (`"""Service to generate a Protocol graph from a chat conversation via LLM."""`) with:

```python
"""One-shot protocol generation from a chat conversation.

DORMANT SINCE TD-0081 (Apr 2026).

This workflow is not currently invoked by any endpoint or background job.
It is preserved because:
  - The code is written and tested.
  - It represents a legitimate alternate UX path ("explore in chat, then
    formalize") that we may productize later.
  - Deleting and rebuilding later is more work than keeping it dormant.

Status: kept until we confirm the conversational `protocol_builder` subagent
performs well in production. Once validated, this file may be deleted along
with its unit test (tests/unit/test_protocol_generator.py).

DO NOT add new callers without first promoting this to a real product
feature with its own task and acceptance criteria.

The graph-building helpers (build_graph, match_unit_op, extract_params) in
this module ARE used by services/protocols/creation.py and must not be
removed without replacing them.
"""
```

- [ ] **Step 3: Update import in `services/documents/pdf.py`**

In `backend/app/services/documents/pdf.py`, change:

```python
from app.services.ai.sop_generator import generate_sop_pdf
```

to:

```python
from app.services.ai.workflows.sop_generator import generate_sop_pdf
```

- [ ] **Step 4: Update import in `services/protocols/creation.py`**

In `backend/app/services/protocols/creation.py`, change:

```python
from app.services.ai.protocol_generator import (GeneratedProtocol,
                                                 GeneratedStep, build_graph)
```

to:

```python
from app.services.ai.workflows.protocol_generator import (GeneratedProtocol,
                                                            GeneratedStep,
                                                            build_graph)
```

- [ ] **Step 5: Search for any other importers**

```bash
grep -rln "from app.services.ai.sop_generator\|from app.services.ai.protocol_generator" backend/
```

Expected: no remaining matches. If any appear, update them similarly.

- [ ] **Step 6: Run full test suite**

```bash
pytest -q
```

Expected: PASS — both modules accessible at new paths; tests for `protocol_generator` (tests/unit/test_protocol_generator.py) continue to pass.

- [ ] **Step 7: Commit**

```bash
git add -A backend/app/services/ai/workflows/ backend/app/services/documents/pdf.py backend/app/services/protocols/creation.py
git commit -m "refactor(ai): relocate sop_generator and protocol_generator to workflows/"
```

**Rollback:** `git revert HEAD`.

---

## Task 22: Delete `generate-protocol` skill and `pydantic-ai-skills` dep

**Goal:** Remove the legacy skill file and the `pydantic-ai-skills` dependency. The `protocol_builder` subagent now handles this flow.

**Files:**
- Delete: `backend/skills/generate-protocol/SKILL.md`
- Delete: `backend/skills/generate-protocol/` (folder, if empty)
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Remove the skill file**

```bash
cd backend
git rm -r skills/generate-protocol
```

- [ ] **Step 2: Confirm `pydantic-ai-skills` is no longer imported**

```bash
grep -rln "pydantic_ai_skills\|pydantic-ai-skills" backend/app backend/tests backend/scripts
```

Expected: no matches (we removed `_get_skills_toolset` and the SkillsToolset import as part of Task 20).

- [ ] **Step 3: Remove the dependency from `pyproject.toml`**

In `backend/pyproject.toml`, find the `pydantic-ai-skills = "..."` line in `[tool.poetry.dependencies]` and delete it. Then:

```bash
poetry lock --no-update
poetry install --no-root
```

- [ ] **Step 4: Run full test suite**

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/poetry.lock backend/skills/
git commit -m "chore(ai): remove generate-protocol skill and pydantic-ai-skills dep"
```

**Rollback:** `git revert HEAD` then `poetry install --no-root`.

---

## Task 23: Globalize chat agent (TD-0063 absorption)

**Goal:** The chat agent is currently constructed once per request inside `build_chat_agent`. Pydantic-ai agents are designed to be stateless globals — re-instantiating per turn is wasteful and is exactly what TD-0063 calls out. Promote to a process-level singleton, passing per-request `deps` and `compaction_state` through `agent.run(...)`.

**Risk:** State leak if anything in the agent or capabilities holds per-request references. Add a concurrency test that hits the agent with two different orgs simultaneously and verifies `deps.sources` doesn't bleed across requests.

**Files:**
- Modify: `backend/app/services/ai/chat_agent.py`
- Modify: `backend/app/services/ai/send_message.py`
- Create: `backend/tests/integration/test_chat_concurrency.py`

- [ ] **Step 1: Write failing concurrency test**

Create `backend/tests/integration/test_chat_concurrency.py`:

```python
"""Verify chat agent globalization doesn't leak state across requests."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.services.ai.deps import ChatDeps, RetrievedChunk
from app.services.ai.send_message import send_message
from app.services.ai.sessions import create_session


@pytest.mark.asyncio
async def test_concurrent_runs_do_not_share_sources(
    db_session: AsyncSession, test_user: User, test_org: Organization,
    second_user: User, second_org: Organization,
):
    """Two requests against different orgs must end with isolated deps.sources."""
    sess1 = await create_session(db_session, user_id=test_user.id, org_id=test_org.id)
    sess2 = await create_session(db_session, user_id=second_user.id, org_id=second_org.id)

    fake_chunk_a = RetrievedChunk(
        document_id=uuid4(), document_title="A",
        chunk_id=uuid4(), chunk_index=0,
        page_number=None, content="A-content", score=0.9,
    )
    fake_chunk_b = RetrievedChunk(
        document_id=uuid4(), document_title="B",
        chunk_id=uuid4(), chunk_index=0,
        page_number=None, content="B-content", score=0.9,
    )

    call_count = {"n": 0}

    async def fake_run(prompt, deps, message_history=None):
        # Each "run" injects a different chunk into its OWN deps
        call_count["n"] += 1
        if call_count["n"] == 1:
            deps.sources.append(fake_chunk_a)
        else:
            deps.sources.append(fake_chunk_b)
        result = MagicMock()
        result.output = "ok"
        result.all_messages = MagicMock(return_value=[])
        return result

    fake_agent = MagicMock()
    fake_agent.run = fake_run

    async def fake_build(*args, **kwargs):
        return fake_agent

    with patch("app.services.ai.send_message.build_chat_agent", fake_build):
        await asyncio.gather(
            send_message(db_session, sess1, "q1",
                         user_id=test_user.id, is_org_admin=False),
            send_message(db_session, sess2, "q2",
                         user_id=second_user.id, is_org_admin=False),
        )

    # Each session's metadata should reference its own chunk only.
    from sqlalchemy import select

    from app.models.chat import ChatMessage, ChatMessageRole
    res1 = await db_session.execute(
        select(ChatMessage).where(
            ChatMessage.session_id == sess1.id,
            ChatMessage.role == ChatMessageRole.ASSISTANT,
        )
    )
    res2 = await db_session.execute(
        select(ChatMessage).where(
            ChatMessage.session_id == sess2.id,
            ChatMessage.role == ChatMessageRole.ASSISTANT,
        )
    )
    msg1 = res1.scalar_one()
    msg2 = res2.scalar_one()
    sources1 = (msg1.metadata_ or {}).get("sources", [])
    sources2 = (msg2.metadata_ or {}).get("sources", [])
    titles1 = {s["document_title"] for s in sources1}
    titles2 = {s["document_title"] for s in sources2}
    assert "A" in titles1 and "B" not in titles1
    assert "B" in titles2 and "A" not in titles2
```

NOTE: this test relies on `second_user` and `second_org` fixtures from conftest.py (they exist for cross-org isolation tests).

- [ ] **Step 2: Run the test against current per-request build**

```bash
pytest tests/integration/test_chat_concurrency.py -v
```

Expected: PASS (the per-request build is already isolated). This establishes the baseline before globalization.

- [ ] **Step 3: Globalize the agent**

In `backend/app/services/ai/chat_agent.py`, refactor `build_chat_agent` to cache by `(org_id, model_keys)`. The simplest approach: a module-level `_AGENT_CACHE: dict[tuple, Agent]` keyed by the model identifiers. Replace the existing `build_chat_agent` body with:

```python
"""Chat agent factory — composes capabilities + subagents.

Agents are cached per (org_id, model-set) tuple so they are not rebuilt every
turn (TD-0063). Per-request state (deps, compaction_state) is passed to
agent.run() at call time, never closed over the global Agent.
"""
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai_summarization import ContextManagerCapability
from sqlalchemy.ext.asyncio import AsyncSession
from subagents_pydantic_ai import SubAgentCapability

from app.core.config import settings
from app.services.ai.ai_config import get_context_window, get_model
from app.services.ai.deps import ChatDeps
from app.services.ai.runtime.compaction import (CompactionState,
                                                  make_compaction_hooks)
from app.services.ai.runtime.token_counting import tiktoken_counter
from app.services.ai.subagents import (protocol_builder, research_library,
                                         run_planner)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_CHAT_PROMPT = (_PROMPTS_DIR / "chat_agent.md").read_text()
_SUMMARY_PROMPT = (_PROMPTS_DIR / "summarization.md").read_text()

_AGENT_CACHE: dict[tuple[str, ...], "Agent[ChatDeps, str]"] = {}


def _cache_key(chat_model: Any, subagent_model: Any, summary_model: Any,
                context_window: int) -> tuple[str, ...]:
    return (str(chat_model), str(subagent_model), str(summary_model), str(context_window))


async def build_chat_agent(
    db: AsyncSession,
    org_id: UUID,
    compaction_state: CompactionState,
) -> "Agent[ChatDeps, str]":
    """Return a cached Agent for the resolved (model, ctx-window) tuple.

    Compaction callbacks reference compaction_state via closures captured at
    cache time. Because these closures see the FIRST CompactionState passed
    in for this cache key, we instead bind the latest state via a thin
    indirection: the cache stores a mutable "dispatch" object that the hooks
    consult at run time (see _LiveState). Per-request state is set via
    set_compaction_state below before agent.run().
    """
    chat_model     = await get_model("chat",          db, org_id=org_id)
    subagent_model = await get_model("chat_subagent", db, org_id=org_id)
    summary_model  = await get_model("chat_summary",  db, org_id=org_id)
    context_window = await get_context_window("chat", db, org_id=org_id)

    key = _cache_key(chat_model, subagent_model, summary_model, context_window)

    if key not in _AGENT_CACHE:
        live = _LiveState()  # mutable holder; hooks read state from this
        on_before, on_after = _make_live_hooks(live)

        subagents = [
            research_library.build(subagent_model),
            protocol_builder.build(subagent_model),
            run_planner.build(subagent_model),
        ]
        _AGENT_CACHE[key] = (Agent(
            chat_model,
            instructions=_CHAT_PROMPT,
            deps_type=ChatDeps,
            capabilities=[
                SubAgentCapability(subagents=subagents, max_nesting_depth=1),
                ContextManagerCapability(
                    max_tokens=context_window,
                    compress_threshold=settings.compaction_threshold,
                    summarization_model=summary_model,
                    summary_prompt=_SUMMARY_PROMPT,
                    max_tool_output_tokens=2000,
                    token_counter=tiktoken_counter,
                    on_before_compress=on_before,
                    on_after_compress=on_after,
                ),
            ],
            tools=[],
        ), live)

    agent, live = _AGENT_CACHE[key]
    live.set(compaction_state)
    return agent


class _LiveState:
    """Mutable holder so cached compaction hooks can find the per-request state."""
    def __init__(self) -> None:
        self._state: CompactionState | None = None

    def set(self, state: CompactionState) -> None:
        self._state = state

    @property
    def state(self) -> CompactionState | None:
        return self._state


def _make_live_hooks(live: _LiveState):
    def on_before(messages, cutoff_index):
        if live.state is None:
            return
        live.state.triggered = True
        live.state.summarized_message_count = cutoff_index

    def on_after(messages):
        if live.state is None:
            return None
        from pydantic_ai.messages import ModelRequest, SystemPromptPart
        if messages:
            first = messages[0]
            if isinstance(first, ModelRequest):
                for part in first.parts:
                    if isinstance(part, SystemPromptPart):
                        live.state.summary_text = part.content
                        break
        return None
    return on_before, on_after


def _reset_cache_for_tests() -> None:
    """Test helper: clear the cache between tests."""
    _AGENT_CACHE.clear()
```

NOTE the trade-off: caching means the compaction hook closures must look up the *current* request's `CompactionState` via a mutable indirection (`_LiveState`). This works because pydantic-ai serializes runs (one `agent.run()` at a time per Agent — confirm with the upstream docs if streaming/concurrency on the same Agent ever becomes a concern).

If concurrent runs on the *same cached agent* turn out to share `_LiveState` unsafely, fall back to per-request agents (revert this commit). The concurrency test in Step 5 will catch it.

- [ ] **Step 4: Reset the cache between tests**

In `backend/tests/conftest.py`, add an autouse fixture (after the existing fixtures):

```python
@pytest.fixture(autouse=True)
def _reset_chat_agent_cache():
    from app.services.ai.chat_agent import _reset_cache_for_tests
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()
```

- [ ] **Step 5: Run the concurrency test**

```bash
pytest tests/integration/test_chat_concurrency.py -v
```

Expected: PASS — sources don't bleed across orgs.

- [ ] **Step 6: Run full suite**

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 7: If concurrency test fails, revert**

```bash
git restore backend/app/services/ai/chat_agent.py backend/tests/conftest.py
```

Then file a follow-up note: globalization needs a different design (e.g., agent-per-event-loop or a request-context var). Continue to Task 24 with per-request build still in place.

- [ ] **Step 8: Commit (only if Step 5 passed)**

```bash
git add backend/app/services/ai/chat_agent.py backend/tests/conftest.py backend/tests/integration/test_chat_concurrency.py
git commit -m "perf(ai): cache chat Agent per (org-model) tuple — absorbs TD-0063"
```

**Rollback:** `git revert HEAD`.

---

## Task 24: Run 5-query regression check + document quality changes

**Goal:** Manually verify chat behavior against five representative queries before merging. Document any quality changes (good or bad) in a regression note.

**Files:**
- Create: `backend/docs/chat-agent-regression-2026-XX-XX.md` (use today's date)
- Create: `backend/scripts/test_chat_agent.py` content (or use existing if present)

- [ ] **Step 1: Confirm dev backend can start**

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8010 &  # alternate port for worktree
```

Wait for "Application startup complete" then `curl http://localhost:8010/health` returns 200.

- [ ] **Step 2: Confirm a Pro org with chat config exists**

Run via the Python REPL or a script: ensure at least one org has `chat`, `chat_subagent`, `chat_summary` configured (DB rows or env-var fallback). Otherwise `get_model("chat_subagent", ...)` will raise.

- [ ] **Step 3: Run the 5 queries**

Use the existing `backend/scripts/test_chat_agent.py` as a harness, or via `httpx` from a notebook:

1. **General fact lookup:** "What's the typical seed train scale for monoclonal antibody production?"
   Expected: response with [1], [2] citations from research_library if docs exist; otherwise general AI knowledge with the disclaimer.
2. **Library inventory:** "What documents do we have on cell culture?"
   Expected: list_documents tool fires; concise list of document titles.
3. **Protocol creation:** "I want to make a protocol for a 50L mAb seed train"
   Expected: dispatch to protocol_builder; one question at a time; ends with `create_protocol` tool call against a real project.
4. **Greeting:** "Hi, what can you help with?"
   Expected: brief direct answer, no subagent dispatch.
5. **Long-context query:** issue messages until > 80% of context window, then ask a fact-recall question.
   Expected: compaction triggers; `ChatMessage(role=SUMMARY)` row appears in the session; assistant answers without forgetting earlier context.

For each query, capture: response text, tool calls, sources, latency, any errors.

- [ ] **Step 4: Write the regression note**

Create `backend/docs/chat-agent-regression-<YYYY-MM-DD>.md`:

```markdown
# TD-0081 Regression Check — <date>

## Setup
- Backend at commit <SHA>
- Org config: <provider/model for chat, chat_subagent, chat_summary>

## Queries

### 1. General fact lookup
**Query:** "What's the typical seed train scale for mAb production?"
**Response:** <paste>
**Tool calls:** <paste>
**Sources:** <paste>
**Latency:** <ms>
**Verdict:** <PASS / DEGRADE / IMPROVE> — <one sentence>

### 2. Library inventory
... (same template)

### 3. Protocol creation
... (same template; verify Protocol record was created in DB)

### 4. Greeting
... (same template; verify NO subagent dispatch occurred)

### 5. Long-context / compaction
... (same template; verify ChatMessage(role=SUMMARY) row was inserted)

## Summary

- Overall verdict: <PASS / NEEDS WORK>
- Quality changes vs. pre-TD-0081 baseline: <if any>
- Latency changes: <if any>
- Issues to address before merging: <list or "none">
```

- [ ] **Step 5: Commit the regression note**

```bash
git add backend/docs/chat-agent-regression-*.md
git commit -m "docs(ai): TD-0081 regression check results"
```

**Rollback:** `git revert HEAD`.

---

## Task 25: Final cleanup — branch is ready

**Goal:** Verify the worktree branch is clean, all tests pass, and the migration is complete.

- [ ] **Step 1: Confirm no orphan files**

```bash
git status
```

Expected: clean working tree on the worktree branch.

- [ ] **Step 2: Run full backend test suite**

```bash
cd backend && source .venv/bin/activate && pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run linters**

```bash
black app tests --check
isort app tests --check
mypy app
```

Expected: no errors.

- [ ] **Step 4: Confirm acceptance criteria**

Tick off each item from the spec's §14 acceptance criteria:

- [ ] Inventory document committed
- [ ] Harness evaluation document committed
- [ ] Target structure design document committed
- [ ] New dependencies added (subagents-pydantic-ai, summarization-pydantic-ai, tiktoken)
- [ ] pydantic-ai-skills dependency removed
- [ ] app/services/ai/ follows the structure in design doc §3
- [ ] Tools are thin wrappers (≤30 lines, no permission/persist logic in tool bodies)
- [ ] Chat agent has zero direct tools; all capabilities are subagents
- [ ] Audit-visible compaction preserved (ChatMessage(role=SUMMARY) rows still written)
- [ ] All existing chat tests pass after the migration
- [ ] TD-0063 absorbed (Task 23, if concurrency test passed)
- [ ] 5-query regression check run; quality changes documented
- [ ] protocol_generator.py carries the disposition header
- [ ] generate-protocol skill file deleted from backend/skills/

If any are unchecked, address them before declaring complete.

- [ ] **Step 5: Final commit if needed**

If any small fixes were needed in Step 4, commit them:

```bash
git add -A
git commit -m "chore(ai): final cleanup for TD-0081"
```

---

## Self-Review Checklist (run after writing this plan)

Before handing this plan to an executor, the author runs through:

1. **Spec coverage:** Every section of `chat-agent-target-structure.md` is implemented by some task above. Specifically: §3 (directory layout) → Task 4 + Tasks 13-18; §4 (tool placement) → enforced in Tasks 13-15; §5 (thin tools) → Tasks 8-9 + 14; §6 (ChatDeps) → Task 7; §7 (chat_agent factory) → Task 16; §7.1 (per-subagent config) → Tasks 13-15 use `build(model)`; §7.2 (nested dispatch) → Task 16 sets `max_nesting_depth=1`; §8 (send_message) → Task 18; §9 (research_library detail) → Task 13; §10 (compaction) → Task 11; §10.5 (conversation persistence) → behavior emerges from architecture, no specific task; §11 (migration map) → Tasks 5-21 implement the moves; §12 (disposition) → Task 21 step 2; §13 (endpoint contract) → Task 19 preserves it; §15 (sequencing) → tasks ordered to match.
2. **Placeholder scan:** No TBDs, no "implement later", no abstract steps without code.
3. **Type consistency:** `ChatDeps`, `RetrievedChunk`, `CompactionState`, `ProtocolSpec`, `SubAgentConfig` referenced consistently across tasks. Tool function names (`search_documents`, `read_section`, `list_documents`, `list_unit_ops`, `create_unit_op`, `create_protocol`) match between subagent tools.py, config.py, and tests.

---

## User Manual Verification (after engineer self-review passes)

Once the engineer signals "Self-Review passed; tests green," the user (Wesley) runs through this clicklist in the browser to confirm the migration is correct from a product perspective. Don't skip — these catch behavior changes that unit/integration tests can miss.

**Setup:**
1. Branch is at the tip of the worktree branch with all 25 tasks committed.
2. Backend running on the worktree port (e.g., `:8010`):
   ```bash
   cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010
   ```
3. Frontend running on the worktree port (e.g., `:5183`) with `VITE_API_PORT=8010`:
   ```bash
   cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183
   ```
4. Log in as a Pro-tier org admin user. Confirm at least one project exists.

### Group A — Chat behavior

- [ ] **A1. Basic chat works.**
  - Click the chat icon → "New chat"
  - Type "Hello" → send
  - **Expected:** A short, friendly response appears within ~3s. No `<think>` tags, no raw JSON, no "I'll now..." preamble.

- [ ] **A2. Library research returns citations.**
  - In a chat, type a question your library has documents about (e.g., "What buffers do we use for the seed train?")
  - **Expected:**
    - Response includes `[1]`, `[2]`-style citation markers.
    - The "Sources" panel under the assistant message shows document titles + page numbers.
    - Clicking a source opens the document at the cited section.
  - **Failure modes to watch:** no citations shown despite library having matching docs; or citations shown but no Sources panel.

- [ ] **A3. No-match library fallback message.**
  - In a chat, ask a question with no matching docs (e.g., "What's the airspeed of an unladen swallow?")
  - **Expected:** Response includes the disclaimer:
    > ⚠️ This is from general AI knowledge, not your organization's documents. Verify independently.

- [ ] **A4. Protocol creation flow end-to-end.**
  - In a chat: "I want to make a protocol for a 50L mAb seed train"
  - **Expected:** The agent asks clarifying questions one at a time (process type → scale → base document?). Confirms each step before proposing the next.
  - Confirm steps as the agent proposes them. When asked which project, name an existing project.
  - **Expected:** "Created protocol 'X' as draft in project Y" appears.
  - Open the project → Protocols tab → confirm a new DRAFT protocol exists with the steps you confirmed.

- [ ] **A5. Greetings don't dispatch a subagent.**
  - In a fresh chat: "Hi, what can you help with?"
  - **Expected:** Direct text answer. No "Searching..." or tool-call indicator. (You can verify in the chat metadata panel that `tool_calls` is empty.)

### Group B — Compaction and audit

- [ ] **B1. Compaction triggers on long conversation.**
  - In one chat session, ask 20+ questions until the chat metadata panel shows token count > 80% of the configured context window.
  - On the next message, watch for the "Conversation Summary" indicator.
  - **Expected:** A summary message appears in the chat history (rendered with a distinct style), and subsequent messages still reference earlier facts (e.g., "as you mentioned about the buffer composition...").

- [ ] **B2. Summary is persisted in DB.**
  - With B1 still in scope, in a separate terminal:
    ```bash
    psql postgresql://postgres:postgres@localhost:5432/batchrite -c \
      "SELECT id, role, LEFT(content, 80) FROM chat_messages WHERE role = 'SUMMARY' ORDER BY created_at DESC LIMIT 3"
    ```
  - **Expected:** At least one row with role `SUMMARY` and a sensible content preview.

- [ ] **B3. Context-warning surfaces if compaction can't recover.**
  - Stress-test by pasting very long content into the chat repeatedly.
  - **Expected:** Eventually a "This conversation's history has been heavily compacted. Response quality may degrade — consider starting a new chat session." banner appears in the message metadata.

### Group C — AI settings and provider resolution

- [ ] **C1. New capability rows appear in AI Settings.**
  - Navigate to Settings → AI.
  - **Expected:** Three new rows compared to before TD-0081: `chat`, `chat_subagent`, `chat_summary` (the latter two are new).

- [ ] **C2. Custom provider config for `chat_subagent` is honored.**
  - Set `chat_subagent` to a model different from `chat` (e.g., `chat` = a fast Haiku, `chat_subagent` = Sonnet).
  - In a chat, ask a research question (which dispatches to `research_library`).
  - **Expected:** Watching the request log on the backend, the subagent run uses the Sonnet model; the orchestrator uses Haiku.
  - **How to confirm:** `tail -f` the backend log and look for two distinct model identifiers per turn.

- [ ] **C3. `chat_summary` model resolves separately.**
  - Set `chat_summary` to a different (cheap) model.
  - Trigger compaction (per B1).
  - **Expected:** The compaction LLM call goes to the `chat_summary` model, not `chat` or `chat_subagent`.

- [ ] **C4. Pro-tier defaults still apply.**
  - As an admin of a Pro-tier org with no `chat_subagent` config, send a chat message.
  - **Expected:** No `ValueError`. Subagent runs use the platform default model. (If Pro-tier orgs without config get errors, the `DEFAULT_CONFIGS` rollout is incomplete.)

### Group D — Protocol editor (was endpoint logic, now via service)

- [ ] **D1. Create custom unit op via the protocol editor.**
  - Open the protocol editor for any protocol → "Add Custom Unit Op" button.
  - Enter a unique name, category, description; submit.
  - **Expected:** New unit op appears in the unit op list and is usable in the canvas.
  - **What this verifies:** the refactored `POST /unit-ops` endpoint (now calling `services/protocols/unit_ops.py::create_unit_op_definition`) still works for the protocol editor flow.

- [ ] **D2. Org-admin-only org-scoped unit op enforcement.**
  - As a non-admin org member, try to create an org-scoped unit op (or watch the API fail with 403).
  - **Expected:** 403 with the message "Org admin role required for org-scoped unit ops".

- [ ] **D3. Duplicate unit op name rejected.**
  - In the protocol editor, try to create a unit op with a name that already exists.
  - **Expected:** 422 with "Unit op '<name>' already exists" (now sourced from the service's `ValueError` raised through the endpoint).

### Group E — Documents domain (post-`retrieval.py` move)

- [ ] **E1. Library list still loads.**
  - Navigate to Library.
  - **Expected:** Existing documents render with titles, status, page counts. (Verifies `services/documents/retrieval.py` move didn't break anything.)

- [ ] **E2. Document upload still works.**
  - Upload a PDF.
  - **Expected:** Upload completes, document is processed (chunks + embeddings created), and is searchable from chat (verify via A2).

### Group F — Regressions and cross-cutting

- [ ] **F1. Existing chat sessions still load.**
  - Open a chat session created **before** the TD-0081 migration.
  - **Expected:** Messages render correctly (including any old `role=SUMMARY` rows). Sending a new message in this session works (i.e., the new `send_message.py` correctly deserializes legacy `ai_message_history`).

- [ ] **F2. SOP PDF generation still works.**
  - Trigger an SOP PDF download (wherever it's exposed in the UI — typically Run page → Print SOP).
  - **Expected:** A valid PDF downloads. (Verifies the `sop_generator.py` move from `services/ai/` to `services/ai/workflows/` and the import-path update in `services/documents/pdf.py`.)

- [ ] **F3. Cross-org isolation.**
  - Log in as a user in Org A. Note a citation [1] document title.
  - Log in as a user in Org B (different org). Ask the same research question.
  - **Expected:** Org B's response cites Org B's documents. Org A's titles do NOT appear. This catches state-leak from the agent caching introduced in Task 23.

### Decision

After running the clicklist:

- [ ] **All boxes checked, no surprises** → migration is verified. Engineer can proceed to merge / close TD-0081.
- [ ] **Some boxes failed or behaved unexpectedly** → file findings inline next to the relevant item with reproduction steps. Engineer addresses, re-runs the regression suite, and asks the user to re-verify those items only.

---

*End of plan. Total: 25 tasks. Estimated effort: 3-5 sessions of 2-3 hours each.*
