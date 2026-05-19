# F-0089 — Library-Sourced Protocol Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `protocol_creator` ground new protocol drafts on the org's indexed library via a new `new-protocol` chat skill that forces an explicit source choice (Library / OpenWetWare / From scratch / Search all) before generation.

**Architecture:** Add a `SkillsCapability` (from `pydantic-ai-skills 0.6.0`) to the cached chat Agent. The skill's SKILL.md drives a sibling-orchestration recipe — chat_agent dispatches `research_library` → `protocol_creator` for the Library path, reusing the F-0084 HITL flow for OpenWetWare. Chip activation becomes sticky on the frontend; the server composes a `[skill:<id>]` prefix on the model-visible message so chip-clicks deterministically load the skill.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (async/asyncpg), pydantic-ai 1.75+, pydantic-ai-skills 0.6.0, subagents-pydantic-ai, Svelte 5 (runes), Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-05-18-f-0089-library-sourced-protocol-generation-design.md`

**Mockup:** `docs/superpowers/specs/mockups/f0089-library-sourced-protocol.html`

---

## File Map

**Backend (new):**
- `backend/app/services/ai/skills/new-protocol/SKILL.md` — skill instructions + frontmatter (skills are code; they live alongside subagents, prompts, workflows)
- `backend/scripts/seed_f0089_qa.py` — QA fixture: inserts an INDEXED `Document` + chunks for browser verification
- `backend/tests/unit/test_skills_capability_loads_new_protocol.py`
- `backend/tests/unit/test_chat_agent_prompt_guardrail.py`
- `backend/tests/unit/test_subagents_protocol_creator.py` (if absent — current file may already exist; check before creating)
- `backend/tests/integration/test_library_sourced_protocol_creation.py`

**Backend (modified):**
- `backend/app/core/config.py:164` — anchor `skills_dir` default to an absolute path via `Path(__file__)` so it works from any CWD
- `backend/app/services/ai/chat_agent.py` — add `SkillsCapability` to `capabilities=[...]`
- `backend/app/services/ai/prompts/chat_agent.md` — add `[skill:<id>]` dispatch rule + `## Skill: new-protocol` guardrail block
- `backend/app/services/ai/send_message.py` — accept `skill_id` arg, compose `[skill:<id>] ` prefix on model-visible content while persisting clean DB content
- `backend/app/api/endpoints/chat.py` — pass `body.skill_id` into `send_message_streaming`
- `backend/app/services/ai/subagents/protocol_creator/prompt.md` — grounding instruction + citation footer format
- `backend/app/services/ai/subagents/research_library/tools.py` — `VIEWABLE_STATUSES` filter on `list_documents`
- `backend/tests/unit/test_subagents_research_library.py` — extend with status-filter test

**Frontend (modified):**
- `frontend/src/lib/chat-store.svelte.ts` — sticky `activeSkill` state, rewrite `activateSkill`, attach `skill_id` from state in `sendMessage`, clear on `done`
- `frontend/src/lib/components/ai/ChatPanel.svelte` — skill badge above textarea, accent border/ring in skill mode
- `frontend/src/lib/chat-store.test.ts` — extend with skill-state tests

**Rules:**
- `.claude/rules/backend-ai.md` — document `SkillsCapability` as third capability

---

## Task 1: Backend — Create the `new-protocol` SKILL.md

**Files:**
- Create: `backend/app/services/ai/skills/new-protocol/SKILL.md`
- Create: `backend/tests/unit/test_skills_capability_loads_new_protocol.py`
- Modify: `backend/app/core/config.py:164` — anchor `skills_dir` default to absolute path

- [ ] **Step 1: Anchor `skills_dir` default in `config.py`**

`config.py` is at `backend/app/core/config.py`. `parent.parent` = `backend/app/`, so the default points to `backend/app/services/ai/skills/` regardless of CWD. Change line 164:

```python
skills_dir: str = str(
    Path(__file__).resolve().parent.parent / "services" / "ai" / "skills"
)
```

Make sure `from pathlib import Path` is already imported at the top of `config.py` (it almost certainly is — check). The env override `BATCHRITE_SKILLS_DIR` remains available.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_skills_capability_loads_new_protocol.py`:

```python
"""Tests that the new-protocol SKILL.md is well-formed and discoverable."""

from pathlib import Path

import pytest
import yaml

from pydantic_ai_skills import SkillsCapability

# backend/app/services/ai/skills/new-protocol/SKILL.md
SKILL_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "app"
    / "services"
    / "ai"
    / "skills"
    / "new-protocol"
    / "SKILL.md"
)


def test_skill_md_exists() -> None:
    assert SKILL_PATH.is_file(), f"SKILL.md missing at {SKILL_PATH}"


def test_skill_md_has_required_frontmatter() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must begin with YAML frontmatter"
    parts = text.split("---", 2)
    assert len(parts) >= 3, "Frontmatter is malformed"
    meta = yaml.safe_load(parts[1])
    assert meta["name"] == "new-protocol"
    assert isinstance(meta.get("description"), str) and meta["description"]
    assert isinstance(meta.get("icon"), str) and meta["icon"]


def test_skill_md_body_covers_four_sources() -> None:
    body = SKILL_PATH.read_text(encoding="utf-8").split("---", 2)[2]
    lower = body.lower()
    for keyword in ("library", "openwetware", "from scratch", "search all"):
        assert keyword in lower, f"SKILL.md body must mention '{keyword}'"


def test_skill_md_hard_fails_library_empty_with_redirect() -> None:
    """Library miss must offer a redirect to Search all, not silently fall through."""
    body = SKILL_PATH.read_text(encoding="utf-8").split("---", 2)[2].lower()
    assert "search all" in body
    assert "no matching library" in body or "no library matches" in body, (
        "Body must include the Library-empty redirect message"
    )


def test_skill_is_discovered_by_skills_capability() -> None:
    """pydantic_ai_skills must parse our SKILL.md.

    Discovery surface in pydantic-ai-skills 0.6.0 is `cap.toolset.skills`,
    a `dict[str, Skill]` keyed by skill name. The bare `cap.skills` attribute
    does not exist — see the grilling notes attached to F-0089.
    """
    cap = SkillsCapability(directories=[str(SKILL_PATH.parent.parent)])
    assert "new-protocol" in cap.toolset.skills
    skill = cap.toolset.skills["new-protocol"]
    assert skill.description
    assert skill.metadata.get("icon") == "file-plus"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_skills_capability_loads_new_protocol.py -v`

Expected: FAIL on `test_skill_md_exists` (file does not exist).

- [ ] **Step 4: Create the SKILL.md file**

Create `backend/app/services/ai/skills/new-protocol/SKILL.md`:

```markdown
---
name: new-protocol
description: Create a new protocol grounded in a source you pick — your library, OpenWetWare, scratch, or all of the above.
icon: file-plus
---

# Create a new protocol

When invoked, you orchestrate a new-protocol creation flow. Do NOT dispatch any subagent until the user has explicitly chosen a source.

## Step 1 — Ask the user to pick a source

Reply with exactly these four options as a numbered list, then stop and wait for their reply:

1. **Library** — ground the protocol on the org's indexed research library.
2. **OpenWetWare** — search the public OpenWetWare knowledgebase (requires approval before any external content is used).
3. **From scratch** — draft without any source.
4. **Search all** — try the library first, fall back to OpenWetWare if nothing relevant is found.

## Step 2 — Route based on the user's reply

The three explicit options are hard-scoped. Library does not silently escalate to OpenWetWare or scratch.

### Library

1. Dispatch `task("research_library", "<the topic the user wants to create a protocol for>")`. Use `search_documents` semantics.
2. If `research_library` returns **zero relevant chunks**, do NOT fall through. Reply: *"No matching library documents. Want me to run Search all instead?"* and stop. Wait for the user. Empty means the retrieval tool returned no results — never discard hits because they look uninteresting.
3. If results came back, dispatch `task("protocol_creator", "<brief>")` with a brief that includes a `grounding:` section listing the document titles and chunk text returned by research_library. The brief format:

   ```
   <user's original topic>

   grounding:
   - title: <doc_title_1>
     chunks:
       - <chunk_text_1>
       - <chunk_text_2>
   - title: <doc_title_2>
     chunks:
       - <chunk_text_3>
   ```

### OpenWetWare

Existing F-0084 flow. Dispatch `task("protocol_knowledgebase", "<topic>")`. The subagent surfaces an approval card; on approval, the parent calls `create_protocol_from_external_source`. Empty external result → reply: *"No matching OpenWetWare protocols. Want me to run Search all instead?"* and stop.

### From scratch

Dispatch `task("protocol_creator", "<the user's topic, no grounding section>")` directly. Do not invoke research_library or protocol_knowledgebase.

### Search all (the heuristic home)

1. Dispatch `task("research_library", "<topic>")`.
2. If zero results, dispatch `task("protocol_knowledgebase", "<topic>")` (F-0084 HITL).
3. If both empty, dispatch `task("protocol_creator", "<topic>")` from scratch.
4. Otherwise dispatch `task("protocol_creator", "<brief with grounding section>")` using whichever source returned content.

Future heuristics (topic-routing, multi-source merging) live here. The three explicit options stay predictable.

## Citation contract

When `protocol_creator` returns a created protocol, the protocol's description already contains the citation footer (it appends it itself). Do not add a second citation block. Just present the protocol to the user.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_skills_capability_loads_new_protocol.py -v`

Expected: 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/app/services/ai/skills/new-protocol/SKILL.md backend/tests/unit/test_skills_capability_loads_new_protocol.py
git commit -m "feat(F-0089): add new-protocol SKILL.md with source-picker recipe"
```

---

## Task 2: Backend — Filter `list_documents` to viewable statuses

**Files:**
- Modify: `backend/app/services/ai/subagents/research_library/tools.py:262-315`
- Modify or create: `backend/tests/unit/test_subagents_research_library.py`

- [ ] **Step 1: Find or create the test file**

Run: `ls backend/tests/unit/test_subagents_research_library.py`

If absent, create it with the standard async-pytest header. If present, append to it.

- [ ] **Step 2: Write the failing test**

Add to `backend/tests/unit/test_subagents_research_library.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic_ai import RunContext

from app.models.library import Document, DocumentStatus
from app.services.ai.deps import ChatDeps
from app.services.ai.subagents.research_library.tools import list_documents


@pytest.mark.asyncio
async def test_list_documents_filters_to_viewable_statuses(
    db_session: AsyncSession, test_org
) -> None:
    """list_documents must return only INDEXED/ENRICHED/READY documents."""
    statuses = [
        ("Uploaded doc", DocumentStatus.UPLOADED),
        ("Indexing doc", DocumentStatus.INDEXING),
        ("Indexed doc", DocumentStatus.INDEXED),
        ("Enriched doc", DocumentStatus.ENRICHED),
        ("Ready doc", DocumentStatus.READY),
        ("Failed doc", DocumentStatus.FAILED),
    ]
    for title, status in statuses:
        db_session.add(
            Document(
                org_id=test_org.id,
                title=title,
                status=status,
                source_filename=f"{title}.pdf",
                storage_path=f"/tmp/{title}.pdf",
                content_hash=title,
            )
        )
    await db_session.flush()

    deps = ChatDeps(
        db=db_session, org_id=test_org.id, user_id=test_org.id, is_org_admin=False
    )
    ctx = RunContext(deps=deps, model=None, usage=None, prompt=None)  # type: ignore[arg-type]

    result = await list_documents(ctx)
    titles = {d.title for d in (result.documents or [])}
    assert titles == {"Indexed doc", "Enriched doc", "Ready doc"}
```

Note: if `Document` has additional required columns in your repo, mirror the existing test fixtures' pattern (see other tests in `tests/unit/` for the exact Document constructor signature).

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_subagents_research_library.py::test_list_documents_filters_to_viewable_statuses -v`

Expected: FAIL — assertion fails because non-viewable docs come back.

- [ ] **Step 4: Implement the filter**

In `backend/app/services/ai/subagents/research_library/tools.py`, modify the `list_documents` SQL to add a status filter. Replace the SQL block in `list_documents` (lines ~273-288) with:

```python
    from app.models.library import VIEWABLE_STATUSES

    viewable = tuple(s.value for s in VIEWABLE_STATUSES)
    result = await ctx.deps.db.execute(
        sa_text(
            """
            SELECT
                d.id AS document_id,
                d.title,
                COUNT(dc.id) AS chunk_count
            FROM documents d
            LEFT JOIN document_chunks dc ON dc.document_id = d.id
            WHERE d.org_id = :org_id
              AND d.status = ANY(:viewable)
            GROUP BY d.id, d.title
            ORDER BY d.title
            """
        ),
        {"org_id": str(ctx.deps.org_id), "viewable": list(viewable)},
    )
```

The `VIEWABLE_STATUSES` import lives at the top of the file alongside other imports — move the import there rather than nesting it.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_subagents_research_library.py::test_list_documents_filters_to_viewable_statuses -v`

Expected: PASS.

- [ ] **Step 6: Run full research_library test file as regression**

Run: `pytest tests/unit/test_subagents_research_library.py -v`

Expected: All tests PASS. If any pre-existing test depended on non-viewable docs showing up, update it (its assumption was wrong).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai/subagents/research_library/tools.py backend/tests/unit/test_subagents_research_library.py
git commit -m "fix(F-0089): filter list_documents to VIEWABLE_STATUSES only"
```

---

## Task 3: Backend — Wire `SkillsCapability` into the cached chat Agent

**Files:**
- Modify: `backend/app/services/ai/chat_agent.py`
- Modify: `backend/tests/unit/test_skills_capability_loads_new_protocol.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_skills_capability_loads_new_protocol.py`:

```python
@pytest.mark.asyncio
async def test_chat_agent_includes_skills_capability(
    db_session, test_org, monkeypatch
) -> None:
    """build_chat_agent must register a SkillsCapability that discovers new-protocol.

    Verified in pydantic-ai 1.75 via REPL exploration:
      - Multiple capabilities compose into a `CombinedCapability` at
        `agent._root_capability` (private — see comment below).
      - That CombinedCapability exposes `.capabilities` (list of the
        per-capability instances we passed in).
      - SkillsCapability discovery lives at `cap.toolset.skills`
        (a `dict[str, Skill]`), NOT at `cap.skills` (which doesn't exist).
    """
    from app.services.ai.chat_agent import build_chat_agent
    from app.services.ai.runtime.compaction import CompactionState
    from pydantic_ai_skills import SkillsCapability

    state = CompactionState()
    agent = await build_chat_agent(db_session, test_org.id, state)

    # NOTE: _root_capability is a private API in pydantic-ai 1.75. If a
    # future minor bump renames it, this test fails loudly — update the
    # one access path and move on. The behavior-only alternative (asserting
    # `load_skill` is a callable tool) is more durable but more elaborate;
    # the brittleness here is bounded and acceptable.
    caps = agent._root_capability.capabilities
    skill_caps = [c for c in caps if isinstance(c, SkillsCapability)]
    assert len(skill_caps) == 1, "Exactly one SkillsCapability must be registered"
    assert "new-protocol" in skill_caps[0].toolset.skills
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_skills_capability_loads_new_protocol.py::test_chat_agent_includes_skills_capability -v`

Expected: FAIL — no SkillsCapability in the agent.

- [ ] **Step 3: Modify `chat_agent.py`**

In `backend/app/services/ai/chat_agent.py`:

Add at the top with other third-party imports (after the `subagents_pydantic_ai` import):

```python
from pydantic_ai_skills import SkillsCapability
```

In the `Agent(...)` construction (around line 206), add `SkillsCapability` to the `capabilities=` list:

```python
            capabilities=[
                SubAgentCapability(
                    subagents=subagents,
                    default_model=subagent_model,
                    include_general_purpose=False,
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
                SkillsCapability(
                    directories=[str(Path(settings.skills_dir))],
                ),
            ],
```

Skills load once per cached agent instance (cache is keyed on the model tuple). Adding or modifying a SKILL.md file requires a process restart to take effect — documented in Task 10's rules refresh.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_skills_capability_loads_new_protocol.py -v`

Expected: all 6 tests PASS.

- [ ] **Step 5: Run the full chat-agent test suite for regressions**

Run: `pytest tests/ -k "chat_agent or chat or subagent" -v`

Expected: PASS. If `_capabilities` is the wrong attribute, the test will error — switch to whatever the public API exposes.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/chat_agent.py backend/tests/unit/test_skills_capability_loads_new_protocol.py
git commit -m "feat(F-0089): register SkillsCapability on cached chat Agent"
```

---

## Task 4: Backend — Add `[skill:<id>]` dispatch rule + `new-protocol` guardrail to `chat_agent.md`

**Files:**
- Modify: `backend/app/services/ai/prompts/chat_agent.md`
- Create: `backend/tests/unit/test_chat_agent_prompt_guardrail.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_chat_agent_prompt_guardrail.py`:

```python
"""Tests that chat_agent.md contains the F-0089 skill activation rules.

These are content-level assertions on the prompt file. They guard against
silent drift — if someone removes the dispatch rule or the guardrail
block, the source-picker contract breaks without crashing anything.
"""

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).parent.parent.parent
    / "app"
    / "services"
    / "ai"
    / "prompts"
    / "chat_agent.md"
)


def test_chat_agent_prompt_includes_skill_prefix_dispatch_rule() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "[skill:" in text, (
        "chat_agent.md must reference the [skill:<id>] prefix dispatch rule"
    )
    assert "load_skill" in text or "load that skill" in text, (
        "chat_agent.md must instruct the model to load the prefixed skill"
    )


def test_chat_agent_prompt_includes_new_protocol_guardrail() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "## Skill: new-protocol" in text, (
        "chat_agent.md must contain the named guardrail section"
    )
    # Anti-patterns enumerated so the model knows when NOT to load
    lower = text.lower()
    for keyword in ("summarize", "edits to an open protocol", "library lookups"):
        assert keyword in lower, f"Guardrail must list anti-pattern: {keyword}"
    # Positive triggers
    for keyword in ("draft", "create"):
        assert keyword in lower, f"Guardrail must list trigger word: {keyword}"


def test_chat_agent_prompt_includes_mid_flow_continuation_rule() -> None:
    """Turn 2 of the source-picker flow must not re-load the skill."""
    text = PROMPT_PATH.read_text(encoding="utf-8").lower()
    assert "mid-flow" in text or "source picker" in text, (
        "Guardrail must instruct the model on multi-turn continuation"
    )
    assert "do not re-load" in text or "do not load it again" in text, (
        "Guardrail must explicitly forbid re-loading on the source-reply turn"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_chat_agent_prompt_guardrail.py -v`

Expected: FAIL — both tests fail (prompt has no skill content yet).

- [ ] **Step 3: Modify `chat_agent.md`**

Append to `backend/app/services/ai/prompts/chat_agent.md` (after the existing dispatch rules and before any closing remarks):

```markdown

## Skills

You have access to chat skills via the `load_skill(skill_name)` tool. Skills give you ready-made recipes for multi-step flows.

### Prefix-based activation

If a user message begins with `[skill:<skill_id>]`, that prefix is a directive from the UI: the user clicked a skill chip. You MUST call `load_skill("<skill_id>")` as your first tool call for this turn, before any other dispatch. After loading, follow the skill's instructions for that turn.

The `[skill:<skill_id>]` prefix is for your eyes only. Do not echo it back in replies, and do not reference the brackets when talking to the user.

## Skill: new-protocol

Load `new-protocol` only when the user is asking to *create* a new protocol, signaled by either:

- a `[skill:new-protocol]` prefix on their message, OR
- an unambiguous creation request — wording like "draft", "create", "make me a new protocol", "build a protocol for X".

Do NOT load `new-protocol` for:

- questions about existing protocols ("summarize", "explain", "what does step 3 do")
- edits to an open protocol ("add a wash step", "change the temperature")
- general library lookups ("what SOPs do we have for lyophilization")

### Mid-flow continuation

The skill is multi-turn: on turn 1 you load it and present the source picker; on turn 2 the user replies with their source choice. On turn 2 do NOT re-load the skill — the SKILL.md content is already in your tool-result history. If your most recent turn presented the source picker AND the user's reply is a source name (Library / OpenWetWare / From scratch / Search all) or a number 1-4, treat that as the source choice and follow Step 2 of the SKILL.md. Do not ask "what would you like in the protocol?" or otherwise restart the flow.

If a subsequent turn shifts to non-creation work (the user asks something unrelated), proceed without re-loading and without forcing the source-picker flow to complete.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_chat_agent_prompt_guardrail.py -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/prompts/chat_agent.md backend/tests/unit/test_chat_agent_prompt_guardrail.py
git commit -m "feat(F-0089): add [skill:<id>] dispatch + new-protocol guardrail to chat_agent prompt"
```

---

## Task 5: Backend — Server-side `[skill:<id>]` prefix composition

**Files:**
- Modify: `backend/app/services/ai/send_message.py`
- Modify: `backend/app/api/endpoints/chat.py:262-268`
- Modify: `backend/tests/integration/test_chat_streaming.py` (or create `test_library_sourced_protocol_creation.py` if integration tests for chat live elsewhere — check `tests/integration/` layout first)

- [ ] **Step 1: Locate the appropriate integration test home**

Run: `ls backend/tests/integration/ | grep -i chat`

The plan assumes you'll create `backend/tests/integration/test_library_sourced_protocol_creation.py` for all F-0089 integration tests. If an existing file already covers chat streaming, you can add this single prefix-composition test there instead and keep the file dedicated to broader flows for later tasks.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/integration/test_library_sourced_protocol_creation.py` (or append to existing chat-streaming file):

```python
"""Integration tests for F-0089 library-sourced protocol creation."""

import json
from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_skill_id_prefixes_model_visible_content_but_not_db(
    client: AsyncClient,
    auth_headers: dict,
    test_org,
    db_session,
) -> None:
    """skill_id on the request must prepend [skill:<id>] to the model-visible
    user_content but keep the DB-persisted content clean.
    """
    # Create a session
    sess_resp = await client.post("/chat/sessions", json={}, headers=auth_headers)
    assert sess_resp.status_code == 200
    session_id = sess_resp.json()["id"]

    captured: dict = {}

    async def fake_send_message_streaming(db, session, user_content, **kwargs):
        captured["user_content"] = user_content
        captured["skill_id"] = kwargs.get("skill_id")
        # Yield a minimal done event so the endpoint completes
        yield {
            "type": "done",
            "user_message": {
                "id": "u1",
                "session_id": str(session.id),
                "role": "user",
                "content": "draft a media prep protocol",
                "metadata_": None,
                "created_at": "2026-01-01",
            },
            "assistant_message": {
                "id": "a1",
                "session_id": str(session.id),
                "role": "assistant",
                "content": "ok",
                "metadata_": None,
                "created_at": "2026-01-01",
            },
            "sources": [],
        }

    with patch(
        "app.api.endpoints.chat.send_message_streaming",
        side_effect=fake_send_message_streaming,
    ):
        resp = await client.post(
            f"/chat/sessions/{session_id}/messages/stream",
            json={"content": "draft a media prep protocol", "skill_id": "new-protocol"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # Drain the SSE response
        async for _ in resp.aiter_text():
            pass

    assert captured["skill_id"] == "new-protocol", (
        "Endpoint must forward skill_id to send_message_streaming"
    )
    # The endpoint passes body.content as-is; send_message_streaming itself
    # composes the model-visible prefix. Assert captured arg is the clean
    # user-typed text.
    assert captured["user_content"] == "draft a media prep protocol"


@pytest.mark.asyncio
async def test_skill_prefix_lands_in_serialized_message_history(
    db_session, test_org, test_user
) -> None:
    """After turn 1, the `[skill:<id>]` prefix must be present in the
    user-request part of `session.ai_message_history`.

    This is the load-bearing assertion for the whole skill-activation
    contract: it proves the prefix reached agent.run (and therefore the
    model) AND that it survives serialization for turn 2 to see. Inspecting
    `ai_message_history` via `ModelMessagesTypeAdapter` uses pydantic-ai's
    stable public API — more durable than hooking TestModel's call surface.
    """
    from app.models.chat import ChatSession
    from app.services.ai.send_message import send_message_streaming
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    from pydantic_ai.models.test import TestModel
    from pydantic_ai import Agent
    from sqlalchemy import text as sa_text

    session = ChatSession(org_id=test_org.id, user_id=test_user.id, title="New Chat")
    db_session.add(session)
    await db_session.flush()

    # Patch the agent factory to return a bare Agent with TestModel.
    # TestModel produces a deterministic text response and serializes the
    # full request/response message history just like a real run.
    with patch("app.services.ai.send_message.build_chat_agent") as mock_build:

        async def _build(*_a, **_kw):
            from app.services.ai.deps import ChatDeps
            return Agent(TestModel(), deps_type=ChatDeps)

        mock_build.side_effect = _build

        async for _ in send_message_streaming(
            db_session,
            session,
            user_content="draft me a protocol",
            user_id=test_user.id,
            is_org_admin=False,
            skill_id="new-protocol",
        ):
            pass

    # Re-fetch the session to read the persisted message history
    await db_session.refresh(session)

    # 1) DB-persisted ChatMessage.content stays clean (no prefix)
    rows = (
        await db_session.execute(
            sa_text(
                "SELECT content FROM chat_messages "
                "WHERE session_id = :sid AND role = 'user'"
            ),
            {"sid": str(session.id)},
        )
    ).fetchall()
    assert any(r.content == "draft me a protocol" for r in rows), (
        "Persisted user message must be the clean text"
    )

    # 2) ai_message_history carries the prefix — this is what turn 2 sees
    assert session.ai_message_history, "ai_message_history must be populated"
    msgs = ModelMessagesTypeAdapter.validate_python(session.ai_message_history)
    user_prompts: list[str] = []
    for m in msgs:
        for part in getattr(m, "parts", []):
            if getattr(part, "part_kind", None) == "user-prompt":
                user_prompts.append(part.content)
    assert any("[skill:new-protocol]" in p for p in user_prompts), (
        f"Prefix not found in serialized history user-prompts: {user_prompts!r}"
    )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/integration/test_library_sourced_protocol_creation.py -v`

Expected: FAIL — `send_message_streaming` does not accept `skill_id` yet.

- [ ] **Step 4: Update the endpoint to pass `skill_id`**

In `backend/app/api/endpoints/chat.py`, modify the `send_message_streaming` call (currently at lines 262-268):

```python
            async for event in send_message_streaming(
                db,
                session,
                body.content,
                user_id=current_user.id,
                is_org_admin=is_org_admin,
                skill_id=body.skill_id,
            ):
```

- [ ] **Step 5: Update `send_message_streaming` to compose the prefix**

In `backend/app/services/ai/send_message.py`, update the function signature and the prompt composition:

```python
async def send_message_streaming(
    db: AsyncSession,
    session: ChatSession,
    user_content: str,
    user_id: UUID,
    is_org_admin: bool,
    skill_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a chat turn as SSE-shaped event dicts. See module docstring."""
    session_pk: UUID = session.id
    session_org_id: UUID = session.org_id
    existing_history = session.ai_message_history

    # Compose the model-visible prompt with the skill prefix when set.
    # The DB-persisted content stays clean (user-visible chat shows no prefix).
    model_visible_content = (
        f"[skill:{skill_id}] {user_content}" if skill_id else user_content
    )

    # ── 1. Persist user message (clean text only) ─────────────────────────────
    user_msg = ChatMessage(
        session_id=session_pk,
        role=ChatMessageRole.USER,
        content=user_content,  # clean — no prefix
    )
    db.add(user_msg)
    await db.flush()
    ...
```

Then find every place in `send_message_streaming` that passes the user prompt into `agent.run(...)` (search for `agent.run`) and replace `user_content` with `model_visible_content` at the prompt argument only.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/integration/test_library_sourced_protocol_creation.py -v`

Expected: both prefix-composition tests PASS.

- [ ] **Step 7: Run full chat-endpoint test suite for regressions**

Run: `pytest tests/integration/ -k chat -v`

Expected: PASS. The signature change is backward-compatible (default `skill_id=None`), so existing callers continue to work.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/ai/send_message.py backend/app/api/endpoints/chat.py backend/tests/integration/test_library_sourced_protocol_creation.py
git commit -m "feat(F-0089): server-side [skill:<id>] prefix on model-visible chat content"
```

---

## Task 6: Backend — `protocol_creator` grounding instruction + citation footer

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_creator/prompt.md`
- Create or extend: `backend/tests/unit/test_subagents_protocol_creator.py`

- [ ] **Step 1: Check whether the test file exists**

Run: `ls backend/tests/unit/test_subagents_protocol_creator.py`

Create it if absent.

- [ ] **Step 2: Write the failing test**

Create or extend `backend/tests/unit/test_subagents_protocol_creator.py`:

```python
"""Tests that protocol_creator's prompt encodes the F-0089 grounding contract."""

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).parent.parent.parent
    / "app"
    / "services"
    / "ai"
    / "subagents"
    / "protocol_creator"
    / "prompt.md"
)


def test_prompt_documents_grounding_section() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8").lower()
    assert "grounding:" in text, (
        "protocol_creator prompt must describe the brief's grounding: section"
    )


def test_prompt_documents_citation_footer_format() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "Grounded in:" in text, "Prompt must specify the citation footer literal"
    assert "library document" in text.lower(), (
        "Footer template must include 'library document(s)'"
    )


def test_prompt_disallows_retrieval_tool_calls() -> None:
    """protocol_creator must not call search_documents — chat_agent retrieves first."""
    text = PROMPT_PATH.read_text(encoding="utf-8").lower()
    assert "do not" in text and (
        "search_documents" in text or "retrieval" in text
    ), "Prompt must explicitly forbid retrieval calls"


def test_prompt_disallows_page_numbers_in_footer() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8").lower()
    assert "no page numbers" in text or "page number" in text, (
        "Prompt must call out that page numbers are unavailable"
    )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_subagents_protocol_creator.py -v`

Expected: FAIL on all four (prompt has no grounding instructions yet).

- [ ] **Step 4: Update `protocol_creator/prompt.md`**

Append a new section to `backend/app/services/ai/subagents/protocol_creator/prompt.md`:

```markdown

## Grounded drafts (F-0089)

When your brief from chat_agent contains a `grounding:` section listing one or more library documents and their chunks, you MUST:

1. Draft the protocol using the chunks as the primary source of facts. Quote temperatures, durations, reagent concentrations, and step ordering from the chunks rather than inventing them.
2. Do NOT call `search_documents`, `read_section`, or any retrieval tool. The chat agent already retrieved the chunks before dispatching you. Calling retrieval again is wasteful and produces duplicate citations.
3. After the protocol's main description text, append this exact citation footer:

   ```
   Grounded in: {n} library document(s):
   - {doc_title_1}
   - {doc_title_2}
   ```

   `{n}` is the count. Each bullet is a document title copied verbatim from the brief. No page numbers — the markdown chunker does not populate them. No quotes, no chunk indices, no URLs. One title per line.

When your brief has no `grounding:` section, draft from your training knowledge as before. Do not invent a "Grounded in: 0 library documents" footer in that case — omit the footer entirely.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_subagents_protocol_creator.py -v`

Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_creator/prompt.md backend/tests/unit/test_subagents_protocol_creator.py
git commit -m "feat(F-0089): protocol_creator grounding + citation footer prompt contract"
```

---

## Task 7: Backend — One end-to-end integration test for the Library happy path

**Scope decision:** Earlier multi-test plans (four-source matrix via FunctionModel scripting) were dropped because FunctionModel's scripted-response cursor advances on every model call — including subagent calls — which makes multi-turn parent-plus-subagent scripts brittle. The four source paths are validated through layered defenses instead:

- **Task 1** locks the SKILL.md routing content via keyword + redirect-message tests.
- **Task 4** locks the chat_agent.md guardrail + mid-flow continuation rule.
- **Task 6** locks the protocol_creator grounding/citation contract.
- **Task 10's qa-verify run** walks all four paths in the browser with real models.

This integration test owns the **most prompt-sensitive single path** — Library, which exercises retrieval → grounding-section assembly → protocol_creator → citation footer. If that works end-to-end, the other three (which are strict subsets or skip-the-retrieval variants) are covered by their content-level tests + manual QA.

**Files:**
- Modify: `backend/tests/integration/test_library_sourced_protocol_creation.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_library_sourced_protocol_creation.py`:

```python
"""End-to-end integration test for the Library happy path."""

import json
from unittest.mock import patch

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


def _scripted_model(script: list[ModelResponse]) -> FunctionModel:
    """FunctionModel that replays a fixed sequence of responses.

    Note: FunctionModel's cursor advances on EVERY model call, including
    subagent calls. The script must therefore include responses for the
    subagent runs we expect to be triggered, in order. Keep the script as
    short as possible and let the trailing default "done" cover overflow.
    """
    iteration = {"n": 0}

    async def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        n = iteration["n"]
        iteration["n"] = n + 1
        if n < len(script):
            return script[n]
        return ModelResponse(parts=[TextPart(content="done")])

    return FunctionModel(call)


@pytest.mark.asyncio
async def test_library_source_flow_dispatches_research_then_creator(
    client, auth_headers, test_org, db_session
) -> None:
    """Library happy path: user picks Library → research_library is dispatched →
    protocol_creator receives a brief with a `grounding:` section listing the
    retrieved document title and chunk text.

    This is the only integration test in the F-0089 source-path matrix. The
    other three source paths (OpenWetWare, From scratch, Search all) are
    covered by Task 1's SKILL.md routing tests, Task 4's chat_agent.md
    guardrail tests, Task 6's protocol_creator grounding tests, and Task 10's
    manual QA walk-through.
    """
    from app.models.library import Document, DocumentChunk, DocumentStatus

    doc = Document(
        org_id=test_org.id,
        title="Lyophilization SOP v2",
        status=DocumentStatus.INDEXED,
        source_filename="lyo.pdf",
        storage_path="/tmp/lyo.pdf",
        content_hash="lyo",
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            org_id=test_org.id,
            chunk_index=0,
            content="Pre-freeze to -40C for 2 hours before applying vacuum.",
            embedding=[0.1] * 1536,
        )
    )
    await db_session.flush()
    await db_session.commit()

    # Capture dispatches to subagents by patching the `task` tool at its
    # registration point. This is more robust than scripting the script-
    # cursor across parent+subagent turns.
    captured: list[dict] = []

    async def fake_task(ctx, *, subagent_name: str, task: str):
        captured.append({"name": subagent_name, "task": task})
        if subagent_name == "research_library":
            from app.services.ai.subagents.research_library.tools import SearchResult
            return SearchResult(
                results=[{
                    "document_id": str(doc.id),
                    "title": "Lyophilization SOP v2",
                    "content": "Pre-freeze to -40C for 2 hours.",
                    "score": 0.9,
                }]
            )
        if subagent_name == "protocol_creator":
            return {"protocol_id": "created", "description": "Lyo protocol\n\nGrounded in: 1 library document(s):\n- Lyophilization SOP v2"}
        return {}

    # Script: load_skill → picker → research_library dispatch → creator dispatch → done
    script = [
        ModelResponse(parts=[ToolCallPart(
            tool_name="load_skill",
            args={"skill_name": "new-protocol"},
        )]),
        ModelResponse(parts=[TextPart(
            content="Pick a source: 1) Library 2) OpenWetWare 3) From scratch 4) Search all"
        )]),
        ModelResponse(parts=[ToolCallPart(
            tool_name="task",
            args={"subagent_name": "research_library", "task": "lyophilization"},
        )]),
        ModelResponse(parts=[ToolCallPart(
            tool_name="task",
            args={
                "subagent_name": "protocol_creator",
                "task": (
                    "lyophilization protocol\n\n"
                    "grounding:\n- title: Lyophilization SOP v2\n"
                    "  chunks:\n    - Pre-freeze to -40C for 2 hours."
                ),
            },
        )]),
        ModelResponse(parts=[TextPart(content="Created protocol grounded in your library.")]),
    ]

    # Mount the scripted model + fake task tool. Exact patch targets may
    # need adjustment based on chat_agent.py's import surface — confirm with
    # `grep -n "build_chat_agent\|task" backend/app/services/ai/send_message.py`
    # before writing the patch context manager. The intent is unambiguous:
    # replace the parent model with `_scripted_model(script)` and intercept
    # `task(...)` dispatches into `captured`.
    with patch("app.services.ai.send_message.build_chat_agent") as mock_build:
        from pydantic_ai import Agent
        from app.services.ai.deps import ChatDeps

        async def _build(*_a, **_kw):
            agent = Agent(_scripted_model(script), deps_type=ChatDeps)
            agent.tool(fake_task, name="task")
            return agent

        mock_build.side_effect = _build

        # Create session
        sess_resp = await client.post("/chat/sessions", json={}, headers=auth_headers)
        session_id = sess_resp.json()["id"]

        # Turn 1: skill chip click — server prepends [skill:new-protocol]
        r1 = await client.post(
            f"/chat/sessions/{session_id}/messages/stream",
            json={"content": "draft a lyophilization protocol", "skill_id": "new-protocol"},
            headers=auth_headers,
        )
        assert r1.status_code == 200
        async for _ in r1.aiter_text():
            pass

        # Turn 2: user replies "Library"
        r2 = await client.post(
            f"/chat/sessions/{session_id}/messages/stream",
            json={"content": "Library"},
            headers=auth_headers,
        )
        assert r2.status_code == 200
        async for _ in r2.aiter_text():
            pass

    dispatched_names = [c["name"] for c in captured]
    assert "research_library" in dispatched_names, (
        f"Library path must dispatch research_library; got {dispatched_names}"
    )
    assert "protocol_creator" in dispatched_names, (
        f"Library path must dispatch protocol_creator; got {dispatched_names}"
    )
    # Order matters: research_library must come before protocol_creator
    assert dispatched_names.index("research_library") < dispatched_names.index(
        "protocol_creator"
    )
    # The protocol_creator brief must include the grounding section + doc title
    creator_call = next(c for c in captured if c["name"] == "protocol_creator")
    assert "grounding:" in creator_call["task"].lower()
    assert "Lyophilization SOP v2" in creator_call["task"]
```

The test is deliberately a single end-to-end happy path. If during implementation you discover the patch targets above don't match the actual call surface (e.g., `build_chat_agent` is imported under a different name inside `send_message.py`), grep before patching and adjust the targets. The contract being asserted — *Library reply → research_library dispatch → protocol_creator brief carries grounding* — does not change.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_library_sourced_protocol_creation.py::test_library_source_flow_dispatches_research_then_creator -v`

Expected: FAIL — the skill loading chain isn't wired yet OR the assertions fail because dispatches don't happen in order.

- [ ] **Step 3: Run test until it passes**

After Tasks 1, 3, 4, 5 are landed, run the test. Iterate on the SKILL.md or chat_agent.md guardrail if the model isn't dispatching in the expected order — tighten the prompt, not the test.

- [ ] **Step 4: Run full integration suite for regressions**

Run: `pytest tests/integration/ -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/integration/test_library_sourced_protocol_creation.py
git commit -m "test(F-0089): integration test for Library happy path"
```

---

## Task 8: Frontend — Sticky `activeSkill` state in `chat-store.svelte.ts`

**Files:**
- Modify: `frontend/src/lib/chat-store.svelte.ts:685-689`
- Modify: `frontend/src/lib/chat-store.test.ts` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/chat-store.test.ts`:

```typescript
describe('chat-store skill activation (F-0089)', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
        store.clearActiveSkill?.();
    });

    it('activateSkill sets state without sending', async () => {
        const apiPost = vi.mocked((await import('$lib/api')).api.post);
        apiPost.mockClear();

        store.activateSkill({
            name: 'new-protocol',
            description: 'Create a new protocol grounded in a source.',
            icon: 'file-plus',
        });

        expect(store.getActiveSkill()?.name).toBe('new-protocol');
        expect(apiPost).not.toHaveBeenCalled();
    });

    it('sendMessage attaches active skill_id then clears on done', async () => {
        store.__test_setActiveSession({
            id: 'S1',
            messages: [],
            title: 'New Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        } as never);

        store.activateSkill({
            name: 'new-protocol',
            description: 'd',
            icon: 'file-plus',
        });

        let capturedBody: Record<string, unknown> | null = null;
        vi.spyOn(sse, 'streamSse').mockImplementation(
            async (_ep, body, cb) => {
                capturedBody = body;
                cb({
                    type: 'done',
                    user_message: {
                        id: 'u1',
                        session_id: 'S1',
                        role: 'user',
                        content: 'draft me a protocol',
                        metadata_: null,
                        created_at: '2026-01-01',
                    },
                    assistant_message: {
                        id: 'a1',
                        session_id: 'S1',
                        role: 'assistant',
                        content: 'ok',
                        metadata_: null,
                        created_at: '2026-01-01',
                    },
                    sources: [],
                });
            },
        );

        store.setMessageInput('draft me a protocol');
        await store.sendMessage();

        expect(capturedBody).toEqual({
            content: 'draft me a protocol',
            skill_id: 'new-protocol',
        });
        expect(store.getActiveSkill()).toBeNull();
    });

    it('switching sessions clears the active skill', async () => {
        // Set an active skill on session S1
        store.__test_setActiveSession({
            id: 'S1',
            messages: [],
            title: 'New Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        } as never);
        store.activateSkill({
            name: 'new-protocol',
            description: 'd',
            icon: 'file-plus',
        });
        expect(store.getActiveSkill()?.name).toBe('new-protocol');

        // Switch to a different session (or load a fresh one); the badge
        // must not bleed across boundaries.
        store.__test_setActiveSession({
            id: 'S2',
            messages: [],
            title: 'Another Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        } as never);
        expect(store.getActiveSkill()).toBeNull();
    });

    it('clearActiveSkill resets state and next sendMessage has no skill_id', async () => {
        store.__test_setActiveSession({
            id: 'S1',
            messages: [],
            title: 'New Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        } as never);

        store.activateSkill({
            name: 'new-protocol',
            description: 'd',
            icon: 'file-plus',
        });
        store.clearActiveSkill();
        expect(store.getActiveSkill()).toBeNull();

        let capturedBody: Record<string, unknown> | null = null;
        vi.spyOn(sse, 'streamSse').mockImplementation(
            async (_ep, body, cb) => {
                capturedBody = body;
                cb({
                    type: 'done',
                    user_message: {
                        id: 'u1',
                        session_id: 'S1',
                        role: 'user',
                        content: 'x',
                        metadata_: null,
                        created_at: '2026-01-01',
                    },
                    assistant_message: {
                        id: 'a1',
                        session_id: 'S1',
                        role: 'assistant',
                        content: 'y',
                        metadata_: null,
                        created_at: '2026-01-01',
                    },
                    sources: [],
                });
            },
        );

        store.setMessageInput('hello');
        await store.sendMessage();
        expect(capturedBody).toEqual({ content: 'hello' });
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- chat-store.test.ts`

Expected: FAIL — `getActiveSkill`, `clearActiveSkill` don't exist.

- [ ] **Step 3: Implement sticky skill state**

In `frontend/src/lib/chat-store.svelte.ts`:

Add module-level state (near other `$state` declarations at the top of the file):

```typescript
let activeSkill = $state<ChatSkill | null>(null);
```

Add exported getters/actions:

```typescript
export function getActiveSkill(): ChatSkill | null {
    return activeSkill;
}

export function clearActiveSkill(): void {
    activeSkill = null;
}
```

Rewrite `activateSkill` (currently at line 685):

```typescript
export function activateSkill(skill: ChatSkill): void {
    activeSkill = skill;
    // Focus the textarea if the parent component provided a hook; otherwise
    // the UI will handle focus via $effect on getActiveSkill().
}
```

Update `sendMessage()` to read from sticky state instead of taking a skill arg. Change the signature:

```typescript
export async function sendMessage(): Promise<void> {
    const content = messageInput.trim();
    if (!content || sending) return;
    const skillId = activeSkill?.name ?? null;
    ...
```

Then where the body is built:

```typescript
        const body: Record<string, string> = { content };
        if (skillId) {
            body.skill_id = skillId;
        }
```

After the SSE `done` event resolves (in the `done` branch where `donePayload` is set), clear the active skill:

```typescript
                } else if (event.type === 'done') {
                    donePayload = event as DonePayload;
                    activeSkill = null;
                }
```

(Match the exact existing event-handler structure — the `done` branch already exists; this is one new assignment line inside it.)

Also clear `activeSkill` whenever the active session changes. Find the session-switch logic (likely `setActiveSession` or wherever `activeSession.id` is assigned) and add `activeSkill = null;` to it. This prevents the badge from bleeding across session boundaries.

Update any callers of `sendMessage(skill.name)` in ChatPanel to plain `sendMessage()` — there are two callsites at `ChatPanel.svelte:112` (Enter key) and `ChatPanel.svelte:509` (Send button). Both should remain `sendMessage()` (they were already arg-less since the skill was passed via `activateSkill`, which auto-sent).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- chat-store.test.ts`

Expected: PASS (3 new tests + existing ones).

- [ ] **Step 5: Run full frontend test suite for regressions**

Run: `npm run test`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/chat-store.svelte.ts frontend/src/lib/chat-store.test.ts
git commit -m "feat(F-0089): sticky activeSkill state in chat-store"
```

---

## Task 9: Frontend — ChatPanel skill badge + skill-mode styling

**Files:**
- Modify: `frontend/src/lib/components/ai/ChatPanel.svelte`

- [ ] **Step 1: Manual UX check before editing**

Read the mockup at `docs/superpowers/specs/mockups/f0089-library-sourced-protocol.html` to confirm the badge styling. Key elements:

- Badge above textarea: `bg-accent/10 text-accent border border-accent/40 rounded-md px-2 py-1 text-xs inline-flex items-center gap-1.5`
- Composer wrapper in skill mode: replace `border-border/60 focus:ring-primary/30 focus:border-primary/50` with `border-accent ring-1 ring-accent/30`
- ✕ button on the badge calls `clearActiveSkill()` and uses `lucide-svelte X` icon

- [ ] **Step 2: Modify `ChatPanel.svelte`**

Add imports at the top of the script block (near other lucide imports):

```typescript
import { X } from 'lucide-svelte';
import { getActiveSkill, clearActiveSkill } from '$lib/chat-store.svelte';
import { getIcon } from '$lib/lucide-icon-map'; // or whatever the existing icon-resolver is — see ChatSkillButtons.svelte line 48
```

Add a derived for the active skill:

```typescript
const activeSkill = $derived(getActiveSkill());
```

In the template, immediately above the `<div class="flex items-end gap-2">` at line 486, add the badge:

```svelte
{#if activeSkill}
    <div class="mb-2 flex items-center gap-2">
        <div class="inline-flex items-center gap-1.5 rounded-md border border-accent/40 bg-accent/10 px-2 py-1 text-xs text-accent">
            {#snippet icon()}
                {@const Icon = getIcon(activeSkill.icon)}
                <Icon class="h-3 w-3" />
            {/snippet}
            {@render icon()}
            <span class="font-medium">
                {activeSkill.name
                    .split('-')
                    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
                    .join(' ')}
            </span>
            <button
                type="button"
                class="ml-1 rounded hover:bg-accent/20 p-0.5 cursor-pointer transition-all duration-150"
                onclick={clearActiveSkill}
                aria-label="Clear active skill"
            >
                <X class="h-3 w-3" />
            </button>
        </div>
    </div>
{/if}
```

Update the textarea class to be skill-aware. Replace the `class=` value at line 500 with a conditional via `cn()`:

```svelte
<textarea
    bind:this={inputEl}
    value={messageInput}
    oninput={(e) => setMessageInput(e.currentTarget.value)}
    onkeydown={handleKeydown}
    placeholder={activeSkill
        ? `Ask "${activeSkill.name.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}"…`
        : 'Ask a question...'}
    class={cn(
        'flex-1 resize-none rounded-xl px-3 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none min-h-[40px] max-h-[120px]',
        activeSkill
            ? 'border border-accent ring-1 ring-accent/30 bg-background focus:ring-accent/40'
            : 'border border-border/60 bg-background focus:ring-2 focus:ring-primary/30 focus:border-primary/50',
    )}
    rows="1"
    disabled={sending}
></textarea>
```

(`cn` should already be imported in this file. If not, add `import { cn } from '$lib/utils';` per `.claude/rules/frontend-components.md`.)

The `onactivate={activateSkill}` wiring on both `ChatSkillButtons` instances stays — activateSkill now sets state instead of auto-sending, which is the new behavior we want.

- [ ] **Step 3: Manual browser check**

Run from `frontend/`: `npm run dev`

In a separate terminal from `backend/`: `source .venv/bin/activate && uvicorn app.main:app --reload`

Open the app, login, open the chat panel, click a skill chip. Verify:

1. Chip click does NOT auto-send. Composer enters skill mode (accent border + ring).
2. Badge appears above the textarea with the skill name.
3. ✕ on the badge clears the mode and returns the composer to default styling.
4. Typing a message and pressing Send POSTs with `skill_id` in the body (check Network tab — the `messages/stream` request body should be `{"content": "...", "skill_id": "new-protocol"}`).
5. After the assistant reply finishes streaming, the badge clears automatically (single-message scope).

- [ ] **Step 4: Run check + tests**

Run: `cd frontend && npm run check && npm run test`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/ai/ChatPanel.svelte
git commit -m "feat(F-0089): ChatPanel skill-mode badge and accent composer treatment"
```

---

## Task 10: Backend — Final regression sweep + browser QA + rules refresh

**Files:**
- Create: `backend/scripts/seed_f0089_qa.py`
- Modify: `.claude/rules/backend-ai.md`

- [ ] **Step 0: Create the QA fixture script**

The Library-happy-path QA scenario depends on the org having an INDEXED document. Uploading via the UI introduces async-processing dependencies (embedding API latency, status polling). Pre-seed via a script instead.

Create `backend/scripts/seed_f0089_qa.py`:

```python
"""Seed an INDEXED Document + chunks for F-0089 browser QA.

Usage:
    cd backend && source .venv/bin/activate && python scripts/seed_f0089_qa.py

The script targets the dev DB, finds the user-org membership for the email
provided via --email (defaults to the first org in the system), and inserts
one Document with status=INDEXED plus three chunks with deterministic
embeddings. Idempotent: re-running replaces the previous seed.
"""

import argparse
import asyncio
from sqlalchemy import select
from app.core.config import settings
from app.db import AsyncSessionLocal
from app.models.library import Document, DocumentChunk, DocumentStatus
from app.models.iam import Organization

SEED_TITLE = "[QA F-0089] Lyophilization SOP v2"
SEED_CHUNKS = [
    "Pre-freeze the sample at -40C for 2 hours before applying vacuum.",
    "Set shelf temperature to -25C during primary drying for 8 hours.",
    "Ramp to +20C for secondary drying. Hold for 4 hours before stoppering.",
]
EMBEDDING_DIM = 1536  # matches the existing embedder


async def main(org_id: str | None) -> None:
    async with AsyncSessionLocal() as db:
        if org_id is None:
            org = (await db.execute(select(Organization).limit(1))).scalar_one()
            org_id = str(org.id)
        # Idempotency: delete any prior seed under the same title
        prior = (
            await db.execute(
                select(Document).where(
                    Document.org_id == org_id, Document.title == SEED_TITLE
                )
            )
        ).scalars().all()
        for d in prior:
            await db.delete(d)
        await db.flush()
        doc = Document(
            org_id=org_id,
            title=SEED_TITLE,
            status=DocumentStatus.INDEXED,
            source_filename="qa-lyo.md",
            storage_path="/tmp/qa-lyo.md",
            content_hash="qa-f0089-lyo",
        )
        db.add(doc)
        await db.flush()
        for i, content in enumerate(SEED_CHUNKS):
            # Deterministic embedding: alternating 0.1 / 0.0 per chunk index.
            # No real similarity needed — the QA flow asserts the chunk text
            # appears in the protocol_creator brief, not that retrieval is
            # semantically correct.
            embedding = [(0.1 if i % 2 == 0 else 0.05)] * EMBEDDING_DIM
            db.add(
                DocumentChunk(
                    document_id=doc.id,
                    org_id=org_id,
                    chunk_index=i,
                    content=content,
                    embedding=embedding,
                )
            )
        await db.commit()
        print(f"Seeded {SEED_TITLE} ({len(SEED_CHUNKS)} chunks) into org {org_id}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--org-id", default=None, help="Override target org UUID")
    args = p.parse_args()
    asyncio.run(main(args.org_id))
```

Verify columns by reading the existing `Document` and `DocumentChunk` models — if the seed errors on a NOT NULL column the script missed, mirror what existing tests pass (e.g., `tests/integration/conftest.py` document fixtures are a good reference).

Commit the fixture before running QA so qa-verify can re-execute it on demand:

```bash
git add backend/scripts/seed_f0089_qa.py
git commit -m "chore(F-0089): QA fixture seeding INDEXED document for browser verification"
```

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && source .venv/bin/activate && pytest`

Expected: All tests PASS. Coverage target >80% per CLAUDE.md.

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd frontend && npm run check && npm run test`

Expected: PASS, no type errors.

- [ ] **Step 3: Launch qa-verify agent for browser verification**

Brief the qa-verify agent with:

- Login: any email registered locally; password `postgres` works in dev.
- Feature: F-0089 library-sourced protocol creation.
- Pages affected: chat panel (right sidebar across the app), specifically the composer area and skill chips.
- **Visual reference:** open `docs/superpowers/specs/mockups/f0089-library-sourced-protocol.html` in a second browser tab. The mockup is the visual contract: the skill badge above the composer, the accent ring/border on the textarea in skill mode, the X icon to clear, chip activation behavior. Compare the live UI against the mockup side-by-side. Flag visual drift as POLISH issues (not FAILs), but fix them before returning.
- **Fixture setup:** before running browser flows, execute `cd backend && source .venv/bin/activate && python scripts/seed_f0089_qa.py` to insert the QA-only INDEXED document. Re-run if a previous QA session left the DB in an unknown state.
- Verification flows:
  1. **Library happy path.** Run the seed script (above). Open chat, click the **New protocol** chip, verify the composer enters skill mode (accent border + badge matching the mockup). Type "draft a lyophilization protocol". Send. Confirm the assistant offers four sources, reply "Library", confirm research_library and protocol_creator are dispatched (visible via the tool indicator labels), confirm the final protocol description ends with `Grounded in: 1 library document(s):\n- [QA F-0089] Lyophilization SOP v2`.
  2. **Library miss redirect.** With no indexed documents (or a topic unrelated to seeded docs), repeat the flow. The assistant should reply "No matching library documents. Want me to run Search all instead?" and NOT dispatch protocol_creator.
  3. **Search all fallthrough.** Same empty state, pick "Search all". Verify research_library runs first, then protocol_knowledgebase HITL approval card appears.
  4. **OpenWetWare regression.** Pick OpenWetWare. Verify F-0084 approval flow still works — research_library must NOT be dispatched.
  5. **From scratch.** Pick From scratch. Verify protocol_creator is dispatched immediately with no `grounding:` section in the brief, and the resulting protocol has no `Grounded in:` footer.
  6. **Compaction survival.** Continue chatting on the same session until the tool-indicator suggests compaction has fired (or invoke a long message sequence to force it). Ask a follow-up creation question. Inspect the agent's logged context (search server logs for `<skill id="new-protocol">`). Report whether the skill block survived or was summarized. If summarized, file a follow-up task — do not fix in this plan.
  7. **Lower-tier model evaluation.** If the configured `creation_model` is Kimi K2 or another lower-tier model, repeat verification (1) and confirm protocol_creator did not hallucinate citations or drop chunks from the brief. Compare draft quality to a from-scratch baseline on the same topic.

- [ ] **Step 4: Refresh `.claude/rules/backend-ai.md`**

Add a section near the existing capability documentation (the file lists `SubAgentCapability` and `ContextManagerCapability` in `chat_agent.py`'s skeleton — extend the capabilities block):

```markdown

### SkillsCapability (F-0089)

The chat Agent registers a third capability — `SkillsCapability` from `pydantic-ai-skills 0.6.0`. It reads `backend/app/services/ai/skills/<skill-name>/SKILL.md` files (skills are code; they live alongside subagents, prompts, workflows under `services/ai/`) and exposes `load_skill`, `list_skills`, `read_skill_resource`, and `run_skill_script` tools to the model. Skills land in conversation history as tool results when loaded, so they persist across turns.

Two activation paths:

- **Server-prefix (deterministic).** When a chat message arrives with `skill_id` set, `send_message.py` prepends `[skill:<skill_id>] ` to the model-visible prompt only (DB content stays clean). `chat_agent.md` instructs the model to call `load_skill("<id>")` first when it sees that prefix.
- **Prompt-guarded (model judgment).** For typed requests without the prefix, `chat_agent.md`'s `## Skill: <name>` blocks list the do/don't triggers per skill.

When adding a new skill: create `backend/app/services/ai/skills/<name>/SKILL.md` with `name`, `description`, `icon` frontmatter and instructions in markdown. Add a `## Skill: <name>` guardrail block to `chat_agent.md` listing positive triggers and anti-patterns. The `GET /chat/skills` endpoint reads the same directory, so the UI picks up new skills on the next request — but the chat Agent is cached per `(chat_model, subagent_model, summary_model, context_window)` tuple, so process restart is required for skill changes to reach the model.

Also update the `Package Layout` tree in this file: `services/ai/skills/` sits next to `subagents/`, `prompts/`, `workflows/`, `runtime/`, `tools/`.
```

- [ ] **Step 5: Prune stale content from rules files**

Re-read `.claude/rules/backend-ai.md`, `.claude/rules/conventions.md`, and `CLAUDE.md`. Remove any lines made obsolete by this PR (e.g. references to chat-store `activateSkill` auto-send behavior, the old `sendMessage(skillId)` signature). The implement-task skill requires pruning, not just appending.

- [ ] **Step 6: Commit rules updates**

```bash
git add .claude/rules/backend-ai.md
git commit -m "docs(F-0089): document SkillsCapability and skill activation paths"
```

- [ ] **Step 7: Verify with the user**

Present the change summary, the QA agent's report, and any follow-up items (e.g. compaction-survival outcome). Wait for explicit "ship it" before closing the ClickUp task.

---

## Self-Review

Spec coverage check (each requirement → task that implements it):

- ✓ `SkillsCapability` registered on chat Agent → Task 3
- ✓ `backend/app/services/ai/skills/new-protocol/SKILL.md` with frontmatter + four-option routing → Task 1
- ✓ Library hard-fail + redirect prompt → Task 1 (in SKILL.md body, asserted by `test_skill_md_hard_fails_library_empty_with_redirect`) + Task 7 happy-path test
- ✓ OpenWetWare unchanged from F-0084 → SKILL.md routing test (Task 1) + manual QA (Task 10 step 3 item 4)
- ✓ From scratch direct dispatch → SKILL.md routing test (Task 1) + manual QA (Task 10 step 3 item 5)
- ✓ Search all heuristic (library → OpenWetWare → scratch) → Task 1 + manual QA (Task 10 step 3 item 3)
- ✓ `[skill:<id>]` server-side prefix → Task 5 (endpoint forwarding test + two-turn `ai_message_history` prefix assertion)
- ✓ Multi-turn continuation (turn 2 source-reply routes without re-loading) → Task 4 guardrail block + Task 4's `test_chat_agent_prompt_includes_mid_flow_continuation_rule`
- ✓ `chat_agent.md` prompt updates (Path B guardrail + Path C dispatch + mid-flow rule) → Task 4
- ✓ `protocol_creator` grounding instruction + citation footer → Task 6
- ✓ `protocol_editor` unchanged → confirmed by absence of any task touching it
- ✓ `list_documents` VIEWABLE_STATUSES filter → Task 2
- ✓ `skills_dir` config anchored to absolute path → Task 1 step 1 (`config.py:164`)
- ✓ Frontend sticky activeSkill state (with session-switch clear) → Task 8
- ✓ ChatPanel badge + skill-mode styling → Task 9
- ✓ Visual reference handed to qa-verify → Task 10 step 3 (mockup path)
- ✓ QA fixture (INDEXED document seed) → Task 10 step 0
- ✓ Compaction-survival checkpoint → Task 10 step 3 (item 6) — ship-as-checkpoint per grilling decision; no pre-engineering
- ✓ Lower-tier model performance evaluation → Task 10 step 3 (item 7)
- ✓ Rules refresh including `services/ai/skills/` in package layout → Task 10 step 4-6

Placeholder/ambiguity scan: clean. pydantic-ai 1.75 API verified via REPL during the grilling session — Tasks 1 and 3 use the confirmed surfaces (`cap.toolset.skills` dict; `agent._root_capability.capabilities` list). Task 5 uses public `ModelMessagesTypeAdapter` rather than private TestModel hooks. Task 7 has explicit guidance to grep before patching if call surfaces drift.

Type-consistency check: `ChatSkill` shape used in Task 8 matches the existing schema at `frontend/src/lib/schemas/chat.ts:58` (consumed at `ChatSkillButtons.svelte:14`). `getActiveSkill` / `clearActiveSkill` / `activateSkill` names are consistent across Tasks 8 and 9. `sendMessage()` is argless across all callsites after Task 8 (existing callers at `ChatPanel.svelte:112` and `:509` are already argless).

---
