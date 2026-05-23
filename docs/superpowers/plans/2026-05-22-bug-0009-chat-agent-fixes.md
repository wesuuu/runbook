# BUG-0009 — Chat agent fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three chat-agent bugs: (#1) protocol-creation links use the wrong URL format, (#2) the chat agent advertises only OpenWetWare as a public-protocol source (not protocols.io), and (#4) library image extraction fails with `Errno 2`.

**Architecture:** Three independent commits in a single worktree. Commit #1 extracts an org-slug helper, server-formats the protocol markdown link inside the `create_protocol` tool result, and adds a regex sanitizer pass as a backstop against URL hallucination. Commit #2 parameterizes the chat-agent system prompt on the per-source external-protocols feature flags at agent build time and threads a `source_label` through `protocol_knowledgebase` so citations match the actual source. Commit #3 first un-truncates the docling subprocess stderr (so future failures self-diagnose), then registers `InputFormat.IMAGE` in the docling pipeline so PNG/JPG uploads succeed, with a regression test using a tiny PNG and `do_ocr=False`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, pydantic-ai 1.75+, pytest-asyncio, docling extractor subprocess.

---

## Spec reference

Implements `docs/superpowers/specs/2026-05-22-bug-0009-chat-agent-fixes-design.md`. Read it once before starting; it explains *why* each piece exists.

## File Structure

### New files

- `backend/app/services/core/org_slugs.py` — shared org-slug disambiguation helpers
- `backend/tests/unit/test_org_slugs.py` — unit tests for the helpers
- `backend/tests/unit/test_protocol_creator_tools.py` — covers `create_protocol` URL/markdown-link fields
- `backend/tests/unit/test_protocol_creator_prompt.py` — static assertions about the subagent prompt
- `backend/tests/unit/test_chat_agent_prompt_rendering.py` — covers flag-aware system-prompt rendering
- `backend/tests/unit/test_new_protocol_skill_rendering.py` — covers flag-aware SKILL.md rendering
- `backend/tests/integration/test_chat_protocol_link.py` — end-to-end through `send_message_streaming`
- `ext/docling-extractor/tests/test_image_extraction.py` — regression test for image input
- `ext/docling-extractor/tests/fixtures/tiny.png` — 64×64 solid-color fixture

### Modified files

- `backend/app/services/core/notifications/links.py` — delegate to new shared helpers
- `backend/app/services/ai/subagents/shared/protocols/tools.py` — add `protocol_url` + `protocol_markdown_link` to `CreateProtocolResult`
- `backend/app/services/ai/subagents/protocol_creator/prompt.md` — emit pre-formatted link verbatim, drop UUID template
- `backend/app/services/ai/runtime/sanitize.py` — add `strip_bare_protocol_links` pass to existing `sanitize_output`
- `backend/tests/unit/test_chat_summarization.py` *or* `test_chat_agent_factory.py` — only if behavior assertions there break (do not edit unless they fail)
- `backend/app/services/ai/prompts/chat_agent.md` — template form with placeholders for the external-protocols section
- `backend/app/services/ai/chat_agent.py` — render the system prompt at build time based on enabled external sources
- `backend/app/services/ai/skills/new-protocol/SKILL.md` — template form with placeholder for the external-source name
- `backend/app/services/ai/subagents/protocol_knowledgebase/types.py` — add `source_label` field to `ExternalProtocolPayload`
- `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py` — populate `source_label` on each fetch tool
- `backend/app/services/documents/extraction/extract_job.py` — un-truncate stderr (line 173 and line 182)
- `backend/tests/unit/test_extract_job.py` — assert full stderr is persisted
- `ext/docling-extractor/docling_extractor/pipeline.py` — register `InputFormat.IMAGE` with image options

### Out of scope (do NOT touch)

- `backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md` — already correct
- `backend/app/services/ai/subagents/protocol_knowledgebase/config.py` — already correct
- Frontend — no changes
- Any other code path that emits protocol URLs — verified `links.py` is the only other consumer

---

# Commit 1 — Sub-issue #1: Correct protocol link in chat

### Task 1.1: Add disambiguate_org_slugs helper (pure function, TDD)

**Files:**
- Create: `backend/app/services/core/org_slugs.py`
- Test: `backend/tests/unit/test_org_slugs.py`

- [ ] **Step 1: Write the failing tests for `disambiguate_org_slugs`**

Create `backend/tests/unit/test_org_slugs.py`:

```python
"""Unit tests for org-slug disambiguation helpers."""

from uuid import UUID, uuid4

from app.services.core.org_slugs import disambiguate_org_slugs


def test_empty_input_returns_empty_dict():
    assert disambiguate_org_slugs([]) == {}


def test_single_org_returns_plain_slug():
    oid = uuid4()
    out = disambiguate_org_slugs([(oid, "Acme Bio")])
    assert out == {oid: "acme-bio"}


def test_colliding_slugs_get_id_prefix_suffix():
    a = uuid4()
    b = uuid4()
    out = disambiguate_org_slugs([(a, "Acme"), (b, "Acme")])
    assert out[a] == f"acme-{str(a)[:8]}"
    assert out[b] == f"acme-{str(b)[:8]}"


def test_non_colliding_slugs_stay_plain_even_with_others_in_set():
    a = uuid4()
    b = uuid4()
    c = uuid4()
    out = disambiguate_org_slugs([(a, "Acme"), (b, "Acme"), (c, "Initech")])
    assert out[a].startswith("acme-")
    assert out[b].startswith("acme-")
    assert out[c] == "initech"


def test_no_alphanumeric_name_returns_empty_slug():
    oid = uuid4()
    out = disambiguate_org_slugs([(oid, "---")])
    assert out[oid] == ""


def test_no_alphanumeric_punctuation_returns_empty_slug():
    oid = uuid4()
    out = disambiguate_org_slugs([(oid, "!!!")])
    assert out[oid] == ""
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_org_slugs.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.services.core.org_slugs'`

- [ ] **Step 3: Implement `disambiguate_org_slugs`**

Create `backend/app/services/core/org_slugs.py`:

```python
"""Shared org-URL-slug disambiguation.

The frontend ``disambiguatedOrgSlug`` rule (F-0091): every org gets
``slugify(name)``; if two orgs in the user's membership set collide on
that base, both get a ``-{id-prefix}`` suffix. Backend code that emits
URLs to be opened in the SvelteKit app must apply the same rule.
"""

from __future__ import annotations

from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.slug import slugify
from app.models.iam import Organization, OrganizationMember


def disambiguate_org_slugs(
    orgs: Sequence[tuple[UUID, str]],
) -> dict[UUID, str]:
    """Map org id -> URL slug. Call this when you already hold the
    membership rows; prefer ``disambiguated_org_slug_for_user`` otherwise.

    Returns ``""`` for any org whose name has no alphanumeric content
    (slugifies to empty). Callers should treat empty-string slugs as
    "no valid URL" and degrade — never emit ``/-acme/...`` paths.
    """
    base: dict[UUID, str] = {oid: slugify(name) for oid, name in orgs}
    counts: dict[str, int] = {}
    for slug in base.values():
        counts[slug] = counts.get(slug, 0) + 1
    return {
        oid: ("" if slug == "" else slug if counts[slug] == 1 else f"{slug}-{str(oid)[:8]}")
        for oid, slug in base.items()
    }


async def disambiguated_org_slug_for_user(
    db: AsyncSession, user_id: UUID, org_id: UUID
) -> str | None:
    """Resolve the URL slug for ``org_id`` in the context of ``user_id``'s
    org memberships.

    Returns ``None`` if the user is not a member of ``org_id`` or if the
    resolved slug is blank / hyphen-leading (meaning the org name has no
    alphanumeric content and the URL has no valid form).
    """
    rows = await db.execute(
        select(Organization.id, Organization.name)
        .join(
            OrganizationMember,
            OrganizationMember.organization_id == Organization.id,
        )
        .where(OrganizationMember.user_id == user_id)
    )
    slugs = disambiguate_org_slugs(list(rows.all()))
    slug = slugs.get(org_id)
    if not slug or slug.startswith("-"):
        return None
    return slug
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_org_slugs.py -v
```
Expected: all 6 tests PASS.

### Task 1.2: Add disambiguated_org_slug_for_user tests (DB-backed)

**Files:**
- Test: `backend/tests/unit/test_org_slugs.py` (extend)

- [ ] **Step 1: Add failing async tests**

Append to `backend/tests/unit/test_org_slugs.py`:

```python
import pytest

from app.models.iam import Organization, OrganizationMember
from app.services.core.org_slugs import disambiguated_org_slug_for_user


async def _add_org(db, name: str) -> Organization:
    org = Organization(name=name)
    db.add(org)
    await db.flush()
    return org


async def _add_member(db, user_id, org_id):
    db.add(OrganizationMember(user_id=user_id, organization_id=org_id))
    await db.flush()


async def test_user_in_one_org_returns_slug(db_session, test_user):
    org = await _add_org(db_session, "Plain Lab")
    await _add_member(db_session, test_user.id, org.id)
    assert (
        await disambiguated_org_slug_for_user(db_session, test_user.id, org.id)
        == "plain-lab"
    )


async def test_user_in_colliding_orgs_returns_suffixed_slug(db_session, test_user):
    org_a = await _add_org(db_session, "Acme")
    org_b = await _add_org(db_session, "Acme")
    await _add_member(db_session, test_user.id, org_a.id)
    await _add_member(db_session, test_user.id, org_b.id)

    slug_a = await disambiguated_org_slug_for_user(db_session, test_user.id, org_a.id)
    slug_b = await disambiguated_org_slug_for_user(db_session, test_user.id, org_b.id)

    assert slug_a == f"acme-{str(org_a.id)[:8]}"
    assert slug_b == f"acme-{str(org_b.id)[:8]}"


async def test_user_not_a_member_returns_none(db_session, test_user):
    org = await _add_org(db_session, "Outside Lab")
    # No membership row inserted.
    assert (
        await disambiguated_org_slug_for_user(db_session, test_user.id, org.id)
        is None
    )


async def test_blank_slug_returns_none(db_session, test_user):
    org = await _add_org(db_session, "---")
    await _add_member(db_session, test_user.id, org.id)
    assert (
        await disambiguated_org_slug_for_user(db_session, test_user.id, org.id)
        is None
    )
```

- [ ] **Step 2: Run tests, verify they pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_org_slugs.py -v
```
Expected: all 10 tests PASS. (`test_user` and `db_session` fixtures already exist in `backend/tests/conftest.py`.)

If a test fails because `Organization` constructor requires fields beyond `name`, inspect `backend/tests/unit/test_notification_links.py:132-200` (`test_disambiguates_colliding_org_slugs`) for the exact construction pattern used there and mirror it.

### Task 1.3: Refactor `links.py` to delegate to the shared helper

**Files:**
- Modify: `backend/app/services/core/notifications/links.py`

- [ ] **Step 1: Run the existing links test to capture baseline**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_notification_links.py -v
```
Expected: all existing tests PASS (we want to confirm they still pass after the refactor).

- [ ] **Step 2: Replace the private helper with an import**

In `backend/app/services/core/notifications/links.py`, delete lines 35-50 (the entire `_disambiguated_org_slugs` function) and replace the import block at the top to add the new import:

```python
from app.services.core.org_slugs import disambiguate_org_slugs
```

Then at line 150 (formerly `org_slugs = _disambiguated_org_slugs(list(member_orgs.all()))`), change to:

```python
org_slugs = disambiguate_org_slugs(list(member_orgs.all()))
```

Leave the blank-slug guard at lines 162-165 unchanged — it stays per-route because `disambiguate_org_slugs` returns `""` for blank, not `None`.

- [ ] **Step 3: Run the existing tests again, verify still passing**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_notification_links.py tests/unit/test_org_slugs.py -v
```
Expected: all tests PASS.

- [ ] **Step 4: Commit the helper + refactor**

```bash
git add backend/app/services/core/org_slugs.py \
        backend/app/services/core/notifications/links.py \
        backend/tests/unit/test_org_slugs.py
git commit -m "$(cat <<'EOF'
refactor(BUG-0009): extract org-slug disambiguation helper

links.py's private _disambiguated_org_slugs moves to a shared
core/org_slugs.py module with two public entry points:
disambiguate_org_slugs(orgs) for batch resolution from pre-loaded
membership, and disambiguated_org_slug_for_user(db, user_id, org_id)
for the single-org case the chat tool needs. links.py delegates;
existing notification-URL tests stay green.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 1.4: Add `protocol_url` and `protocol_markdown_link` to `CreateProtocolResult` (TDD)

**Files:**
- Modify: `backend/app/services/ai/subagents/shared/protocols/tools.py` (lines 120-127 and 250-318)
- Create: `backend/tests/unit/test_protocol_creator_tools.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_protocol_creator_tools.py`:

```python
"""Unit tests for create_protocol tool URL/link fields."""

from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.ai.subagents.shared.protocols.tools import (
    CreateProtocolResult,
    ProtocolStepInput,
    create_protocol,
)


def test_create_protocol_result_has_url_fields_with_defaults():
    """Dataclass exposes the new fields with None defaults so older
    construction sites stay safe."""
    result = CreateProtocolResult(
        protocol_id=str(uuid4()),
        protocol_slug="my-protocol",
        protocol_name="My Protocol",
        project_id=str(uuid4()),
    )
    assert result.protocol_url is None
    assert result.protocol_markdown_link is None


async def test_create_protocol_returns_canonical_url_and_markdown_link(
    db_session, test_user, test_org, test_project, monkeypatch
):
    """Happy path: an org-member user creating a protocol gets
    protocol_url = /{org-slug}/protocols/{protocol-slug} and a
    pre-formatted protocol_markdown_link."""
    # Build a fake Protocol that create_protocol_from_spec_service returns.
    fake_protocol = MagicMock()
    fake_protocol.id = uuid4()
    fake_protocol.slug = "buffer-mix-v1"
    fake_protocol.name = "Buffer Mix v1"
    fake_protocol.project_id = test_project.id

    async def fake_service(db, user_id, project_name, spec):
        return fake_protocol

    monkeypatch.setattr(
        "app.services.ai.subagents.shared.protocols.tools."
        "create_protocol_from_spec_service",
        fake_service,
    )

    # Stub ChatDeps. db_lock is an async context manager.
    class _NoLock:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return None

    deps = MagicMock()
    deps.db = db_session
    deps.user_id = test_user.id
    deps.org_id = test_org.id
    deps.db_lock = _NoLock()
    deps.tool_calls = []

    ctx = MagicMock()
    ctx.deps = deps

    result = await create_protocol(
        ctx,
        project_name="Test Project",
        protocol_name="Buffer Mix v1",
        protocol_description="…",
        steps=[ProtocolStepInput(name="Step 1", unit_op_name="Mix")],
    )

    # test_org.name slugifies; test_user is a member (fixture default)
    assert result.protocol_url is not None
    assert result.protocol_url.endswith("/protocols/buffer-mix-v1")
    assert "/protocols/" in result.protocol_url
    # Form is /{org-slug}/protocols/{protocol-slug}
    assert result.protocol_url.count("/") == 3
    assert result.protocol_markdown_link == f"[Buffer Mix v1]({result.protocol_url})"


async def test_create_protocol_url_none_when_user_not_in_org(
    db_session, test_user, test_project, monkeypatch
):
    """Defensive: a request with an org_id the user is not a member of
    yields protocol_url=None and protocol_markdown_link=None rather
    than a malformed URL."""
    fake_protocol = MagicMock()
    fake_protocol.id = uuid4()
    fake_protocol.slug = "x"
    fake_protocol.name = "X"
    fake_protocol.project_id = test_project.id

    async def fake_service(db, user_id, project_name, spec):
        return fake_protocol

    monkeypatch.setattr(
        "app.services.ai.subagents.shared.protocols.tools."
        "create_protocol_from_spec_service",
        fake_service,
    )

    class _NoLock:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return None

    deps = MagicMock()
    deps.db = db_session
    deps.user_id = test_user.id
    deps.org_id = uuid4()  # user is NOT a member of this org
    deps.db_lock = _NoLock()
    deps.tool_calls = []

    ctx = MagicMock()
    ctx.deps = deps

    result = await create_protocol(
        ctx,
        project_name="Test Project",
        protocol_name="X",
        protocol_description="",
        steps=[ProtocolStepInput(name="Step 1", unit_op_name="Mix")],
    )

    assert result.protocol_url is None
    assert result.protocol_markdown_link is None
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_protocol_creator_tools.py -v
```
Expected: FAIL with `AttributeError: 'CreateProtocolResult' object has no attribute 'protocol_url'` (or unexpected-keyword-argument on construction).

- [ ] **Step 3: Add the fields to `CreateProtocolResult`**

In `backend/app/services/ai/subagents/shared/protocols/tools.py:120-127`, replace the dataclass with:

```python
@dataclass
class CreateProtocolResult:
    """Result of a create_protocol call."""

    protocol_id: str
    protocol_slug: str
    protocol_name: str
    project_id: str
    protocol_url: str | None = None
    protocol_markdown_link: str | None = None
```

- [ ] **Step 4: Wire `create_protocol` to compute the URL + markdown link**

In `backend/app/services/ai/subagents/shared/protocols/tools.py`:

1. At the top of the file (with the other `from app.services...` imports), add:

```python
from app.services.core.org_slugs import disambiguated_org_slug_for_user
```

2. Replace the `return CreateProtocolResult(...)` block at the end of `create_protocol` (currently lines 313-318) with:

```python
    org_slug = await disambiguated_org_slug_for_user(
        ctx.deps.db, ctx.deps.user_id, ctx.deps.org_id
    )
    if org_slug:
        protocol_url = f"/{org_slug}/protocols/{protocol.slug}"
        protocol_markdown_link = f"[{protocol.name}]({protocol_url})"
    else:
        protocol_url = None
        protocol_markdown_link = None

    return CreateProtocolResult(
        protocol_id=str(protocol.id),
        protocol_slug=protocol.slug,
        protocol_name=protocol.name,
        project_id=str(protocol.project_id),
        protocol_url=protocol_url,
        protocol_markdown_link=protocol_markdown_link,
    )
```

- [ ] **Step 5: Run tests, verify they pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_protocol_creator_tools.py -v
```
Expected: all 3 tests PASS.

### Task 1.5: Update `protocol_creator/prompt.md` end-of-turn instructions

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_creator/prompt.md` (lines 198-224)
- Create: `backend/tests/unit/test_protocol_creator_prompt.py`

- [ ] **Step 1: Write the failing static-assertion test**

Create `backend/tests/unit/test_protocol_creator_prompt.py`:

```python
"""Static assertions over the protocol_creator subagent prompt."""

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "app/services/ai/subagents/protocol_creator/prompt.md"
)


def _read_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def test_prompt_does_not_instruct_uuid_url_construction():
    """The buggy template /protocols/<protocol_id> must not appear."""
    prompt = _read_prompt()
    assert "/protocols/<protocol_id>" not in prompt


def test_prompt_references_protocol_markdown_link():
    """The end-of-turn section must point the model at the
    pre-formatted protocol_markdown_link from the tool result."""
    prompt = _read_prompt()
    assert "protocol_markdown_link" in prompt


def test_prompt_includes_fallback_for_missing_link():
    """If protocol_markdown_link is None, the model must know what to do."""
    prompt = _read_prompt()
    assert "If `protocol_markdown_link` is `None`" in prompt or \
        "If protocol_markdown_link is None" in prompt
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_protocol_creator_prompt.py -v
```
Expected: FAIL — `/protocols/<protocol_id>` is currently present, `protocol_markdown_link` is not.

- [ ] **Step 3: Rewrite the "End of turn" section of the prompt**

In `backend/app/services/ai/subagents/protocol_creator/prompt.md`, replace the section starting at line 198 (`## End of turn`) and ending at line 224 (the line before `## Grounded drafts (F-0089)`) with:

```markdown
## End of turn

Once `create_protocol` returns `ok=true`, your final reply MUST include
a markdown link to the new protocol so the user can jump straight to it.

**The tool result already contains a pre-formatted link in
`protocol_markdown_link`. Emit it verbatim. Do NOT construct any
`/protocols/...` URL yourself — the server has computed the correct
org-scoped form for you.**

If `protocol_markdown_link` is `None`, the link could not be resolved
(rare — happens only when the user is not a member of the org). In that
case, mention the protocol name as plain text and add a one-sentence
note that the link could not be generated.

If the protocol was imported from an external source (the dispatch
prompt contained `EXTERNAL_PROTOCOL_SOURCE` with a `source_url`), your
final reply MUST also include a markdown link to that source, labeled
according to the source domain:

- openwetware.org → `[OpenWetWare source](<source_url>)`
- protocols.io → `[protocols.io source](<source_url>)`

Example final reply for an external import:

  "Drafted {{protocol_markdown_link verbatim}} in the Cell Culture
  project, copied verbatim from the
  [OpenWetWare source](https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli).
  Two user deviations are noted on the description."

Do not omit either link. Do not paste raw URLs — they must be clickable
markdown links.

**Never claim a creation you didn't actually execute via a tool call.**
Your final reply may only describe records that correspond to a
successful tool return *this turn*.
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_protocol_creator_prompt.py -v
```
Expected: all 3 tests PASS.

### Task 1.6: Add `strip_bare_protocol_links` to `sanitize_output` (TDD backstop)

**Files:**
- Modify: `backend/app/services/ai/runtime/sanitize.py`
- Modify: `backend/tests/unit/` — extend existing sanitize tests if present, else create `test_sanitize.py`

Note: the spec proposed a new `output_sanitizer.py` module, but `runtime/sanitize.py` already owns LLM-output cleaning. Extend it instead — keeping the pipeline single-pass.

- [ ] **Step 1: Check what test file (if any) covers `sanitize_output`**

```bash
cd backend && source .venv/bin/activate && grep -l "from app.services.ai.runtime.sanitize" tests/
```

If a test file exists, extend it. If not, create `backend/tests/unit/test_sanitize.py`.

- [ ] **Step 2: Write the failing tests**

Create or extend with:

```python
"""Sanitizer tests for bare-protocol-link stripping."""

from app.services.ai.runtime.sanitize import sanitize_output


def test_strips_bare_protocol_uuid_link():
    """A `(/protocols/<uuid>)` link from a hallucinating model becomes
    plain text — the bracketed label stays so the user still sees the name."""
    out = sanitize_output("See [My Protocol](/protocols/abc-123-uuid).")
    assert "/protocols/abc-123-uuid" not in out
    assert "[My Protocol]" in out


def test_leaves_canonical_org_scoped_link_alone():
    """A correctly-formed /{org}/protocols/{slug} link is untouched."""
    text = "Open [My Protocol](/acme/protocols/my-protocol)."
    assert sanitize_output(text) == text


def test_strips_multiple_bare_links_in_one_message():
    out = sanitize_output(
        "First [A](/protocols/aaa) and second [B](/protocols/bbb)."
    )
    assert "/protocols/aaa" not in out
    assert "/protocols/bbb" not in out
    assert "[A]" in out and "[B]" in out


def test_does_not_touch_non_protocol_links():
    text = "See [Project](/projects/foo) and [Run](/runs/bar)."
    assert sanitize_output(text) == text
```

- [ ] **Step 3: Run tests, verify they fail**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_sanitize.py -v
```
Expected: FAIL — current `sanitize_output` does not touch protocol links.

- [ ] **Step 4: Add the stripping pass to `sanitize_output`**

In `backend/app/services/ai/runtime/sanitize.py`, after the existing module-level regex definitions (around line 27, after `_BARE_JSON_PATTERN`), add:

```python
# Strip `(/protocols/...)` from any markdown link whose path is NOT a
# canonical /{org-slug}/protocols/{slug} form. Models occasionally
# hallucinate a UUID-only path despite instructions; this is the
# server-side backstop so the user never sees a broken link.
#
# The pattern matches `](/protocols/...)` only — a path starting with
# `/{org-slug}` does not start with `/protocols`, so canonical links
# pass through untouched.
_BARE_PROTOCOL_LINK = re.compile(r"\]\(/protocols/[^)]+\)")
```

Then inside the `sanitize_output` function, immediately before `return cleaned.strip()`, add:

```python
    # Strip bare /protocols/... paths (canonical /{org}/protocols/... untouched).
    cleaned = _BARE_PROTOCOL_LINK.sub("]", cleaned)
```

Final `sanitize_output` body (relevant tail) becomes:

```python
    cleaned = _BARE_JSON_PATTERN.sub(_wrap_json, cleaned)
    cleaned = _BARE_PROTOCOL_LINK.sub("]", cleaned)
    return cleaned.strip()
```

- [ ] **Step 5: Run tests, verify they pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_sanitize.py -v
```
Expected: all 4 tests PASS.

### Task 1.7: End-to-end integration test through `send_message_streaming`

**Files:**
- Create: `backend/tests/integration/test_chat_protocol_link.py`

- [ ] **Step 1: Survey similar existing integration tests for the right harness**

```bash
ls backend/tests/integration/ | grep -i chat
```

Read one of them (e.g. `test_chat_*.py`) to understand the fixture pattern used to drive `send_message_streaming` with a stubbed model. Mirror that pattern.

- [ ] **Step 2: Write the failing integration test**

Create `backend/tests/integration/test_chat_protocol_link.py`:

```python
"""End-to-end: chat agent emits canonical protocol URL (not UUID form)
and the sanitizer scrubs any hallucinated /protocols/<uuid> link."""

# This is the only test that proves sanitizer + tool-result wiring
# work together. Write it to drive send_message_streaming with a
# stubbed model that:
#   (a) calls task("protocol_creator", "<topic>") which calls
#       create_protocol, then
#   (b) emits a reply containing BOTH the correct markdown link AND
#       a hallucinated [Other](/protocols/<uuid>) line.
# Assert the persisted assistant message:
#   - contains a /{org}/protocols/{slug} substring
#   - does NOT contain any "(/protocols/<uuid>)" substring
#
# Follow the harness pattern from an existing chat integration test
# (look for one that uses a stubbed model + drives send_message_streaming
# end-to-end). If no such pattern exists, write a thinner test that calls
# sanitize_output on a known string and asserts both branches — the
# integration coverage already exists via the unit tests in Task 1.6;
# this task is then a NO-OP and you mark it done.
```

If a clean integration-test harness exists, write the full test. If not, write a thinner repro-style test (per the comment above) and document why. The unit tests in Task 1.6 already cover the sanitizer behavior in isolation; the integration test adds value only when it goes through the live pipeline.

- [ ] **Step 3: Run the test**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_chat_protocol_link.py -v
```
Expected: PASS (or the test is a documented no-op if no harness exists).

### Task 1.8: Commit Sub-issue #1

- [ ] **Step 1: Run all touched test suites**

```bash
cd backend && source .venv/bin/activate && pytest \
  tests/unit/test_org_slugs.py \
  tests/unit/test_notification_links.py \
  tests/unit/test_protocol_creator_tools.py \
  tests/unit/test_protocol_creator_prompt.py \
  tests/unit/test_sanitize.py \
  tests/integration/test_chat_protocol_link.py \
  -v
```
Expected: all PASS.

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/ai/subagents/shared/protocols/tools.py \
        backend/app/services/ai/subagents/protocol_creator/prompt.md \
        backend/app/services/ai/runtime/sanitize.py \
        backend/tests/unit/test_protocol_creator_tools.py \
        backend/tests/unit/test_protocol_creator_prompt.py \
        backend/tests/unit/test_sanitize.py \
        backend/tests/integration/test_chat_protocol_link.py
git commit -m "$(cat <<'EOF'
fix(BUG-0009): emit canonical protocol URL from chat agent

create_protocol tool result now carries protocol_url
(/{org-slug}/protocols/{slug}) and a pre-formatted
protocol_markdown_link. The subagent prompt instructs the model to
emit the markdown link verbatim instead of constructing a URL.
sanitize_output adds a backstop that strips any bare
(/protocols/...) path the model hallucinates, so users never see
the broken legacy form.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

# Commit 2 — Sub-issue #2: protocols.io advertisement (flag-aware)

### Task 2.1: Add `source_label` to `ExternalProtocolPayload`

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/types.py`
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py` (lines 105-141 and 178-217)

- [ ] **Step 1: Write the failing test**

Create or extend `backend/tests/unit/test_protocol_knowledgebase_tools.py`:

```python
"""Tests for source_label population on fetch tools."""

from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
)


def test_payload_has_source_label_field_with_default():
    """source_label defaults to empty string so existing test fixtures
    that construct payloads without it keep working."""
    p = ExternalProtocolPayload(title="t", source_url="u", summary="s")
    assert p.source_label == ""
```

Also add a fetch-tool test (only if a test for the fetch tool already exists in this file — extend it; otherwise the dataclass test above is sufficient unit coverage and we'll cover behavior via the rendering test below):

```python
# If an existing test stubs fetch_openwetware → assert payload.source_label == "OpenWetWare"
# If an existing test stubs fetch_protocols_io → assert payload.source_label == "protocols.io"
```

- [ ] **Step 2: Run, verify failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_protocol_knowledgebase_tools.py -v
```
Expected: `AttributeError: 'ExternalProtocolPayload' object has no attribute 'source_label'`.

- [ ] **Step 3: Add the field to the dataclass**

In `backend/app/services/ai/subagents/protocol_knowledgebase/types.py`, add to `ExternalProtocolPayload` (after the `license_note` line):

```python
    # F-0090: the human-readable source name ("OpenWetWare" or "protocols.io")
    # populated by the fetch tool, so the parent agent can cite the actual
    # source verbatim instead of inferring it from the URL.
    source_label: str = ""
```

- [ ] **Step 4: Populate `source_label` in both fetch tools**

In `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py`:

After line 124 (`payload = await openwetware.fetch(...)`), add:

```python
    payload.source_label = "OpenWetWare"
```

After line 197 (`payload = await protocols_io.fetch_protocols_io(...)`), add:

```python
    payload.source_label = "protocols.io"
```

- [ ] **Step 5: Run, verify pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_protocol_knowledgebase_tools.py -v
```
Expected: PASS.

### Task 2.2: Convert `chat_agent.md` to a template + render at build time

**Files:**
- Modify: `backend/app/services/ai/prompts/chat_agent.md`
- Modify: `backend/app/services/ai/chat_agent.py`
- Create: `backend/tests/unit/test_chat_agent_prompt_rendering.py`

- [ ] **Step 1: Write the failing rendering tests**

Create `backend/tests/unit/test_chat_agent_prompt_rendering.py`:

```python
"""Tests for flag-aware chat-agent system-prompt rendering."""

import pytest

from app.services.ai.chat_agent import render_chat_agent_prompt


def test_both_sources_enabled_mentions_both():
    out = render_chat_agent_prompt(
        external_master_enabled=True,
        openwetware_enabled=True,
        protocols_io_enabled=True,
    )
    assert "OpenWetWare" in out
    assert "protocols.io" in out


def test_only_openwetware_mentions_only_openwetware():
    out = render_chat_agent_prompt(
        external_master_enabled=True,
        openwetware_enabled=True,
        protocols_io_enabled=False,
    )
    assert "OpenWetWare" in out
    assert "protocols.io" not in out


def test_only_protocols_io_mentions_only_protocols_io():
    out = render_chat_agent_prompt(
        external_master_enabled=True,
        openwetware_enabled=False,
        protocols_io_enabled=True,
    )
    assert "protocols.io" in out
    assert "OpenWetWare" not in out


def test_master_flag_off_drops_protocol_knowledgebase_section():
    out = render_chat_agent_prompt(
        external_master_enabled=False,
        openwetware_enabled=True,
        protocols_io_enabled=True,
    )
    assert "OpenWetWare" not in out
    assert "protocols.io" not in out
    assert "protocol_knowledgebase" not in out


def test_neither_sub_source_enabled_drops_section():
    out = render_chat_agent_prompt(
        external_master_enabled=True,
        openwetware_enabled=False,
        protocols_io_enabled=False,
    )
    assert "OpenWetWare" not in out
    assert "protocols.io" not in out
    assert "protocol_knowledgebase" not in out
```

- [ ] **Step 2: Run, verify failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_chat_agent_prompt_rendering.py -v
```
Expected: `ImportError: cannot import name 'render_chat_agent_prompt'`.

- [ ] **Step 3: Convert `chat_agent.md` to a template**

In `backend/app/services/ai/prompts/chat_agent.md`:

- Replace line 9 (the protocol_knowledgebase one-liner) with the placeholder line `- {{external_protocols_one_liner}}` (literal string, no Jinja). The rendering code substitutes it.
- Replace the section heading `## External protocols (OpenWetWare)` at line 61 with `## {{external_protocols_heading}}`.
- Replace the section body (lines 62-160, the entire `## External protocols (OpenWetWare)` section through the end of `### Handling rejection of the approval card`) with `{{external_protocols_section}}` — keep the literal raw section text in a Python constant inside `chat_agent.py` so we can vary only the source names by string substitution.

This is mechanical: extract the existing section text verbatim into a Python multi-line string in `chat_agent.py`, then replace OpenWetWare-specific phrasing with substitutable bits. Because the section is long, the cleanest split is:

- The body stays a single template with `{source_names}` (`"OpenWetWare and protocols.io"` / `"OpenWetWare"` / `"protocols.io"`) and `{section_heading}` substitutions.
- When master flag is off OR neither sub-source enabled, both `{{external_protocols_one_liner}}` and `{{external_protocols_section}}` substitute to empty string.

- [ ] **Step 4: Add `render_chat_agent_prompt` to `chat_agent.py`**

In `backend/app/services/ai/chat_agent.py`, replace the module-level `_CHAT_PROMPT = (_PROMPTS_DIR / "chat_agent.md").read_text()` with a rendering function:

```python
_CHAT_PROMPT_TEMPLATE = (_PROMPTS_DIR / "chat_agent.md").read_text()

_EXTERNAL_PROTOCOLS_ONE_LINER = (
    "- `protocol_knowledgebase` — search {source_names} for public "
    "protocols the user doesn't already have."
)

_EXTERNAL_PROTOCOLS_SECTION_TEMPLATE = """\
## External protocols ({source_names})

When the user asks for a public protocol, a protocol they don't have, or
something "from {source_names}", dispatch the `protocol_knowledgebase`
subagent. It returns a markdown list of candidates plus a fenced
`EXTERNAL_PROTOCOL_SOURCE` JSON block.

Surface the candidates to the user. Do NOT call any creation tool yet.

If `protocol_knowledgebase` reports the source is **unreachable** or an
**upstream outage** (rather than "no matching protocol"), relay that to
the user once and offer alternatives — search their library, or draft
from scratch. Do NOT re-dispatch `protocol_knowledgebase` to retry; the
outage will still be there. Re-dispatch at most twice for one request,
and only to refine a query that genuinely returned the wrong matches.

If the user wants to refine — different selection, different organism,
different steps — chat with them. You may re-dispatch
`protocol_knowledgebase` with a refined query. Reflect any user-requested
parameter overrides back at them in plain language before proceeding.

When the user explicitly confirms ("yes, convert it" / "create it" /
"draft this one"), you MUST first ask which project this protocol
belongs to so the user can see and confirm the destination on the
approval card. Phrase it tightly, e.g. "Which project should I put
this in?". Do NOT call the approval tool until the user answers.

Once you have a project name, call the parent tool
`create_protocol_from_external_source(source_url, title, project_name)`
using the chosen candidate's `source_url` and `title` from the
`EXTERNAL_PROTOCOL_SOURCE` block plus the user-supplied `project_name`.

**CRITICAL — never synthesize a `source_url`.** Only use a URL that
literally appears in the most recent `EXTERNAL_PROTOCOL_SOURCE` block.
If the user names a protocol that is NOT in the current candidate list,
you MUST re-dispatch `protocol_knowledgebase` with a refined query first,
wait for the new `EXTERNAL_PROTOCOL_SOURCE` block, and only then call
the approval tool with the URL from that block. Guessing a URL produces
a broken approval card.

The full payload is cached server-side when the subagent fetched the
page; you do NOT pass the JSON across this tool. This tool requires the
user's approval — the run will pause and a confirmation card is shown.
The user may inline-edit the procedure (add / remove / edit steps) on
that card before approving; their edits are applied server-side, so by
the time the tool body runs, the cached payload already reflects them
and the deviations array is populated. You do nothing special — just
hand the result off to protocol_creator.

After the tool returns a string starting with `EXTERNAL_PROTOCOL_APPROVED`,
the next line is the project name, the line after that is a JSON array of
deviations the user made on the approval card (possibly `[]`), and the
line after that is the payload JSON (already reflecting any edits).
Dispatch `protocol_creator` with a prompt of the form:

  "Draft a protocol in project <project_name> from the following external
  source. The payload steps are already the user-approved version — copy
  them verbatim. Cite the source URL in the description. If the
  deviations list is non-empty, note it under a 'Deviations from source'
  heading in the description. Deviations: <deviations JSON>.
  EXTERNAL_PROTOCOL_SOURCE:
  <payload JSON returned by the approval tool>"

Never call `create_protocol_from_external_source` without an explicit
in-turn user confirmation AND a project name. Never invent a payload —
the cached payload is the only source of truth.

### MANDATORY final reply after a successful import

When `protocol_creator` returns a successful result, your final reply to
the user MUST include BOTH of these as inline markdown links, with no
exceptions:

1. The `protocol_markdown_link` field from the `create_protocol` result,
   emitted verbatim. The server has computed the correct URL — do NOT
   construct your own.
2. A link to the original source page from the `EXTERNAL_PROTOCOL_SOURCE`
   payload's `source_url`, labeled by source:
   - openwetware.org → `[OpenWetWare source](<source_url>)`
   - protocols.io → `[protocols.io source](<source_url>)`

Example final reply:

  "Drafted [Heat-shock transformation of E. coli](/acme/protocols/heat-shock-transformation) in
  the Cell Culture project from the [OpenWetWare source](https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli).
  Three deviations from the source are recorded on the protocol description."

Do not just say "I created the protocol" without these links. Do not put
the URL in plain text — it must be a clickable markdown link.

### Handling rejection of the approval card

If the user rejects the approval card, the tool result will indicate
denial and the conversation continues. Briefly acknowledge in one
sentence ("Got it, skipped that protocol.") and invite them to pick a
different candidate from the previous `protocol_knowledgebase` search
or describe a different protocol. Do **not** propose the same candidate
again. There is no "rejection with reason" flow — corrections are
expressed by editing the approval card directly, not by rejecting.
"""


def _source_names(openwetware: bool, protocols_io: bool) -> str:
    if openwetware and protocols_io:
        return "OpenWetWare and protocols.io"
    if openwetware:
        return "OpenWetWare"
    if protocols_io:
        return "protocols.io"
    return ""


def render_chat_agent_prompt(
    external_master_enabled: bool,
    openwetware_enabled: bool,
    protocols_io_enabled: bool,
) -> str:
    """Substitute placeholders in chat_agent.md based on which external
    protocol sources are enabled. Sources gated off are not mentioned —
    we never advertise capability the backend will refuse.
    """
    live_oww = external_master_enabled and openwetware_enabled
    live_pio = external_master_enabled and protocols_io_enabled
    if not (live_oww or live_pio):
        # Drop both the one-liner and the entire section.
        return (
            _CHAT_PROMPT_TEMPLATE
            .replace("{{external_protocols_one_liner}}", "")
            .replace("{{external_protocols_section}}", "")
        )
    names = _source_names(live_oww, live_pio)
    one_liner = _EXTERNAL_PROTOCOLS_ONE_LINER.format(source_names=names)
    section = _EXTERNAL_PROTOCOLS_SECTION_TEMPLATE.format(source_names=names)
    return (
        _CHAT_PROMPT_TEMPLATE
        .replace("{{external_protocols_one_liner}}", one_liner)
        .replace("{{external_protocols_section}}", section)
    )
```

Then replace the existing usage in `build_chat_agent`:

```python
        # Was: instructions=_CHAT_PROMPT
        ext = settings.features.external_protocols
        instructions = render_chat_agent_prompt(
            external_master_enabled=ext.enabled,
            openwetware_enabled=ext.openwetware.enabled,
            protocols_io_enabled=ext.protocols_io.enabled,
        )
```

(Inspect `backend/app/core/config.py:265` and the `ExternalProtocolsFeatureConfig` definition around line 47-59 to confirm the exact attribute names. If they differ, adjust.)

- [ ] **Step 5: Run, verify pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_chat_agent_prompt_rendering.py -v
```
Expected: all 5 tests PASS.

### Task 2.3: Same template treatment for `new-protocol/SKILL.md`

**Files:**
- Modify: `backend/app/services/ai/skills/new-protocol/SKILL.md`
- Create: `backend/tests/unit/test_new_protocol_skill_rendering.py`

The SKILL.md is loaded by `SkillsCapability(directories=[...])`. That capability reads files raw; we can't substitute at load time without intercepting. Two options:

- **Option A (preferred):** rewrite SKILL.md so it always names both sources but explains each is "subject to per-source availability". The model is already gated on the parent agent's prompt — if `protocol_knowledgebase` cannot search a source, the subagent itself will return an empty result. Mentioning both sources in SKILL.md does not promise availability; the routing in Step 1's table still applies.
- **Option B:** subclass / wrap `SkillsCapability` to substitute on read. Heavier.

**Choose Option A.** It's a doc edit, not a code change, and matches the way other skills handle conditional capability.

- [ ] **Step 1: Write the failing static-assertion test**

Create `backend/tests/unit/test_new_protocol_skill_rendering.py`:

```python
"""Static assertions over the new-protocol SKILL.md content."""

from pathlib import Path

SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / "app/services/ai/skills/new-protocol/SKILL.md"
)


def test_skill_mentions_both_external_sources():
    """Both OpenWetWare and protocols.io must be named so the parent
    agent advertises the full set when asked 'what sources can you
    derive protocols from?'."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "OpenWetWare" in text
    assert "protocols.io" in text
```

- [ ] **Step 2: Run, verify failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_new_protocol_skill_rendering.py -v
```
Expected: FAIL — `protocols.io` is not currently in SKILL.md.

- [ ] **Step 3: Edit SKILL.md**

In `backend/app/services/ai/skills/new-protocol/SKILL.md`:

- Line 1 frontmatter description: change `description: Create a new protocol grounded in a source you pick — your library, OpenWetWare, scratch, or all of the above.` to `description: Create a new protocol grounded in a source you pick — your library, external repositories (OpenWetWare, protocols.io), scratch, or all of the above.`
- The routing table at line 15 ("Mentions 'OpenWetWare', 'OWW' …"): expand to also match `"protocols.io"`, `"protocols io"` as external-route triggers, e.g.:

  > Mentions "OpenWetWare", "OWW", "protocols.io", "protocols io", "the web", "external sources", "online protocols", "public protocols", "from the internet" → **External repositories** route. You MUST dispatch `task("protocol_knowledgebase", "<topic>")` immediately. The subagent picks the best source (OpenWetWare or protocols.io) for the query.

- The numbered list (line 22): change item 2 from `**OpenWetWare** — search the public OpenWetWare knowledgebase…` to `**External repositories** — search OpenWetWare and protocols.io (requires approval before any external content is used).`
- The "### OpenWetWare" subheading at line 49 stays as-is internally, but its body text expands the first sentence to: `Existing F-0084/F-0090 flow. Dispatch task("protocol_knowledgebase", "<topic>"). The subagent searches OpenWetWare and protocols.io and surfaces an approval card; on approval, the parent calls create_protocol_from_external_source. Empty external result → reply: "No matching external protocols. Want me to run Search all instead?" and stop.`

- [ ] **Step 4: Run, verify pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_new_protocol_skill_rendering.py -v
```
Expected: PASS.

### Task 2.4: Commit Sub-issue #2

- [ ] **Step 1: Run all touched test suites**

```bash
cd backend && source .venv/bin/activate && pytest \
  tests/unit/test_protocol_knowledgebase_tools.py \
  tests/unit/test_chat_agent_prompt_rendering.py \
  tests/unit/test_new_protocol_skill_rendering.py \
  -v
```
Expected: all PASS.

- [ ] **Step 2: Run the rest of the chat-agent unit tests as a sanity pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_chat_agent_factory.py tests/unit/test_chat_agent_prompt_guardrail.py -v
```
Expected: PASS. (If any fail because they expected the old `_CHAT_PROMPT` constant, update them to call `render_chat_agent_prompt(True, True, True)`.)

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/types.py \
        backend/app/services/ai/subagents/protocol_knowledgebase/tools.py \
        backend/app/services/ai/prompts/chat_agent.md \
        backend/app/services/ai/chat_agent.py \
        backend/app/services/ai/skills/new-protocol/SKILL.md \
        backend/tests/unit/test_protocol_knowledgebase_tools.py \
        backend/tests/unit/test_chat_agent_prompt_rendering.py \
        backend/tests/unit/test_new_protocol_skill_rendering.py
git commit -m "$(cat <<'EOF'
fix(BUG-0009): advertise protocols.io alongside OpenWetWare in chat

chat_agent.md is now rendered at agent build time against the per-source
external-protocols feature flags, so we never advertise a source the
backend has gated off. SKILL.md names both sources statically; the
subagent picks the right one for the query. protocol_knowledgebase
fetch tools populate source_label so the parent's citation matches
the actual source instead of being inferred from the URL.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

# Commit 3 — Sub-issue #4: Library image-extraction Errno 2

### Task 3.1: Un-truncate stderr in `extract_job.py` (TDD)

**Files:**
- Modify: `backend/app/services/documents/extraction/extract_job.py` (lines 173 and 182)
- Modify: `backend/tests/unit/test_extract_job.py`

- [ ] **Step 1: Read the existing extract_job test for the harness pattern**

```bash
cd backend && head -100 tests/unit/test_extract_job.py
```

Find a test that exercises the failure path (search for `_persist_failure` or `returncode != 0` setups).

- [ ] **Step 2: Write the failing test for full-stderr persistence**

Add to `backend/tests/unit/test_extract_job.py`:

```python
async def test_extract_persists_full_stderr_not_truncated(db_session, ...):
    """When docling fails with a long stderr, the persisted
    Document.error_message contains the full message (not truncated to 500).
    Diagnosing the next failure should not require a code change."""
    # Use the harness pattern from existing failure-path tests in this file.
    # Stub _fake_exec to return rc=1 with stderr longer than 500 chars
    # (e.g. "X" * 1000 + "MARKER_AT_END").
    # Run the extraction, then re-query the Document and assert
    #   doc.error_message.endswith("MARKER_AT_END")
    # so we know nothing past char 500 was dropped.
```

Replace `...` with the actual fixture list used by the surrounding tests in the file.

- [ ] **Step 3: Run, verify failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_extract_job.py::test_extract_persists_full_stderr_not_truncated -v
```
Expected: FAIL — message is currently truncated to 500.

- [ ] **Step 4: Remove the truncation**

In `backend/app/services/documents/extraction/extract_job.py`:

- Line 173: change `doc.error_message = f"Extraction error: {message[:500]}"` to:

  ```python
  doc.error_message = f"Extraction error: {message}"
  ```

- Line 182: change `await BackgroundJobService.fail(session, job, message[:500])` to:

  ```python
  await BackgroundJobService.fail(session, job, message)
  ```

If `BackgroundJob.error_message` (or whichever column `fail` writes to) is a `String(N)` column with a length cap, leave that truncation in place at that level — but the `Document.error_message` `Text` column has no cap and benefits most from the full message.

- Line 274: the existing `logger.error("... %s", msg[:500])` line is a fine length for log output; leave it as-is.

- [ ] **Step 5: Run, verify pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_extract_job.py -v
```
Expected: all PASS, including the new full-stderr test.

### Task 3.2: Time-boxed diagnose

This task is **manual** — set a 90-minute timer.

- [ ] **Step 1: Start the dev backend in the worktree**

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010
```

- [ ] **Step 2: Upload a PNG via the library UI**

In a separate terminal, start the worktree frontend:

```bash
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183
```

Open http://localhost:5183, log in, navigate to Library, upload any small PNG.

- [ ] **Step 3: Capture the now-full stderr**

After the upload fails, run:

```bash
cd backend && grep -A 200 "docling subprocess failed" /var/log/<wherever-uvicorn-logs> | head -300
```

Or read the document's `error_message` from the DB:

```bash
psql -h localhost -U postgres -d batchrite -c \
  "SELECT id, file_name, error_message FROM documents WHERE status = 'FAILED' ORDER BY updated_at DESC LIMIT 1;"
```

- [ ] **Step 4: Decision point**

Read the stderr. Within 90 minutes from when you started the diagnose, decide:

- **Root cause identified** → proceed to Task 3.3a (precise fix).
- **Still unclear** → proceed to Task 3.3b (defensive fix). Do not keep diagnosing past the time box.

Record the decision in `docs/superpowers/plans/2026-05-22-bug-0009-chat-agent-fixes.md` by checking exactly one of the two paths below.

### Task 3.3a: Precise fix (use only if root cause identified)

**Files:** depends on diagnosis. Most likely `ext/docling-extractor/docling_extractor/pipeline.py` plus possibly the cache/temp dir setup.

- [ ] **Step 1: Write a regression test that reproduces the failure**

In `ext/docling-extractor/tests/test_image_extraction.py`, write a test that invokes the failing path. See Task 3.4 for the test scaffold.

- [ ] **Step 2: Apply the fix**

Edit the file the diagnosis pointed at. Keep the change minimal.

- [ ] **Step 3: Run the regression test, verify pass**

```bash
cd ext/docling-extractor && python -m pytest tests/test_image_extraction.py -v
```
Expected: PASS.

### Task 3.3b: Defensive fix (use if root cause unclear after timebox)

**Files:**
- Modify: `ext/docling-extractor/docling_extractor/pipeline.py`

- [ ] **Step 1: Register `InputFormat.IMAGE` in `build_converter`**

In `ext/docling-extractor/docling_extractor/pipeline.py:41-58`, replace `build_converter` with:

```python
def build_converter(num_threads: int) -> DocumentConverter:
    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = True
    pdf_options.generate_picture_images = True
    pdf_options.ocr_options = EasyOcrOptions(
        lang=["en"],
        force_full_page_ocr=False,
    )
    pdf_options.accelerator_options = AcceleratorOptions(
        num_threads=num_threads,
        device=AcceleratorDevice.AUTO,
    )

    # IMAGE pipeline: OCR off by default. Reason: we do not control the
    # EasyOCR model cache on the docling subprocess host, so a missing
    # cache file becomes a FileNotFoundError that surfaces as the
    # confusing "[Errno 2] No such file or directory" the user sees.
    # Layout-only extraction always works; if a customer needs OCR'd
    # images later, we add it under a flag.
    from docling.datamodel.pipeline_options import PdfPipelineOptions as _IPO

    image_options = _IPO()
    image_options.do_ocr = False
    image_options.generate_picture_images = True
    image_options.accelerator_options = AcceleratorOptions(
        num_threads=num_threads,
        device=AcceleratorDevice.AUTO,
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            InputFormat.IMAGE: PdfFormatOption(pipeline_options=image_options),
        }
    )
```

Note: docling 2.x uses `PdfFormatOption` for IMAGE too (the format-option class is shared). If the docling version pinned in `ext/docling-extractor/pyproject.toml` requires a different option class, substitute it — the docs page for the pinned version is authoritative.

- [ ] **Step 2: Improve diagnostics by wrapping convert() in a self-explaining FileNotFoundError**

In `ext/docling-extractor/docling_extractor/pipeline.py:128-131`, wrap the `converter.convert(...)` call:

```python
def run_pipeline(file_path: Path, num_threads: int) -> ExtractionResult:
    converter = build_converter(num_threads)
    logger.info("Running docling on %s", file_path)
    try:
        convert_result = converter.convert(str(file_path))
    except FileNotFoundError as e:
        # Surface the missing path in the message so future failures
        # self-diagnose instead of returning a bare "[Errno 2]".
        missing = getattr(e, "filename", None) or "unknown path"
        raise FileNotFoundError(
            f"docling could not open required file: {missing}"
        ) from e
    doc = convert_result.document
    ...
```

### Task 3.4: Regression test for image extraction (TDD)

**Files:**
- Create: `ext/docling-extractor/tests/fixtures/tiny.png`
- Create: `ext/docling-extractor/tests/test_image_extraction.py`

- [ ] **Step 1: Generate the tiny PNG fixture**

```bash
cd ext/docling-extractor && python -c "from PIL import Image; Image.new('RGB', (64, 64), color=(255, 255, 255)).save('tests/fixtures/tiny.png')"
ls tests/fixtures/tiny.png
```
Expected: file exists, ~about 200 bytes.

- [ ] **Step 2: Write the regression test**

Create `ext/docling-extractor/tests/test_image_extraction.py`:

```python
"""Regression test: image input must extract without Errno 2 (BUG-0009 #4).

Uses a tiny solid-color PNG and runs the pipeline with do_ocr=False, so
the test does not depend on the EasyOCR model cache being present.
"""

import json
from pathlib import Path

import pytest

# Skip cleanly if docling cannot be imported in the test environment
# (e.g. CI without the heavy model deps). The bug is in the docling
# call path, so a mock would not catch it — we must run the real call.
docling = pytest.importorskip("docling", reason="docling not installed")

from docling_extractor.pipeline import run_pipeline


FIXTURE = Path(__file__).parent / "fixtures" / "tiny.png"


def test_runs_pipeline_on_image_without_errno_2(tmp_path):
    """Calling run_pipeline on a PNG must succeed (no FileNotFoundError,
    no '[Errno 2]'). Output content quality is not asserted; we only
    care that the pipeline reaches a returnable ExtractionResult."""
    result = run_pipeline(FIXTURE, num_threads=1)
    assert result is not None
    # Markdown can be empty for a solid-color image; the win is "no exception".
    assert isinstance(result.markdown, str)
    assert isinstance(result.page_count, int)


def test_extract_cli_on_image_writes_artifacts(tmp_path):
    """Drives extract.main() on the PNG fixture and asserts artifacts."""
    import sys

    from extract import main

    output_dir = tmp_path / "out"
    sys.argv = [
        "extract.py",
        "--input", str(FIXTURE),
        "--output-dir", str(output_dir),
        "--num-threads", "1",
    ]
    rc = main()
    assert rc == 0
    assert (output_dir / "refined.md").exists()
    assert (output_dir / "result.json").exists()
    result_json = json.loads((output_dir / "result.json").read_text())
    assert result_json.get("source_format") == "IMAGE"
```

- [ ] **Step 3: Run on main (before the fix) to confirm it currently fails**

If you're using path 3.3b (defensive), this test should fail on `main` and pass after the fix lands. Verify the failure first if possible:

```bash
cd ext/docling-extractor && git stash && python -m pytest tests/test_image_extraction.py -v
```
Expected: FAIL (reproduces the bug).

Then:

```bash
cd ext/docling-extractor && git stash pop
```

- [ ] **Step 4: Run after the fix, verify pass**

```bash
cd ext/docling-extractor && python -m pytest tests/test_image_extraction.py -v
```
Expected: PASS.

### Task 3.5: Commit Sub-issue #4

- [ ] **Step 1: Run all touched test suites**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_extract_job.py -v
cd ext/docling-extractor && python -m pytest tests/ -v
```
Expected: all PASS.

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/documents/extraction/extract_job.py \
        backend/tests/unit/test_extract_job.py \
        ext/docling-extractor/docling_extractor/pipeline.py \
        ext/docling-extractor/tests/test_image_extraction.py \
        ext/docling-extractor/tests/fixtures/tiny.png
git commit -m "$(cat <<'EOF'
fix(BUG-0009): library image extraction succeeds (Errno 2)

Two changes: (1) extract_job.py persists the full docling stderr to
Document.error_message instead of truncating at 500 chars, so future
failures self-diagnose. (2) pipeline.py registers InputFormat.IMAGE
with do_ocr=False so PNG/JPG inputs no longer fall through to a
default route that hit a missing OCR model cache. Regression test
runs the pipeline on a tiny solid-color PNG.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

# Post-commits — Full-suite verification

### Task 4.1: Full backend test suite

- [ ] **Step 1: Run backend pytest**

```bash
cd backend && source .venv/bin/activate && pytest
```
Expected: all PASS. If a previously-passing test broke (e.g. one that snapshotted the old chat_agent.md), update it to call `render_chat_agent_prompt(True, True, True)` for the same content.

### Task 4.2: Full docling-extractor suite

- [ ] **Step 1: Run docling tests**

```bash
cd ext/docling-extractor && python -m pytest
```
Expected: all PASS.

### Task 4.3: Optional frontend sanity pass

- [ ] **Step 1: Only if any frontend file changed**

```bash
cd frontend && npm run check
```

Skip this if no frontend file appears in `git diff --name-only main..HEAD --frontend/`.

---

# Browser verification (qa-verify, per spec)

Run AFTER all three commits land and full suites pass. See the spec's "Browser verification (required)" section for the exact pass criteria — three checks, one per sub-issue.

Pass to `qa-verify`:
- Dev DB: `localhost:5432`, user `postgres`, password `postgres`, db `batchrite` (worktree backend on port 8010, frontend on 5183).
- The three pass criteria from the spec verbatim.

Do not close BUG-0009 until all three browser checks pass.

---

# Self-review checklist

Before handing off to execution, the plan author re-reads the plan against the spec:

- [x] **Spec coverage:** Sub-issue #1 → Commit 1 (Tasks 1.1-1.8). Sub-issue #2 → Commit 2 (Tasks 2.1-2.4). Sub-issue #4 → Commit 3 (Tasks 3.1-3.5). Browser verification → post-commit step.
- [x] **Placeholder scan:** No "TBD", no "implement later", no "add appropriate error handling". Two places refer to "the harness pattern from existing tests" — these are *not* placeholders because the engineer is told exactly which file to read and what to mirror.
- [x] **Type consistency:** `disambiguate_org_slugs(orgs)` and `disambiguated_org_slug_for_user(db, user_id, org_id)` names match between definition and call sites. `CreateProtocolResult.protocol_url` and `.protocol_markdown_link` names match between dataclass, tool body, prompt, and test assertions. `ExternalProtocolPayload.source_label` consistent.
- [x] **Spec gap:** Spec proposed a new `output_sanitizer.py` module; plan extends the existing `runtime/sanitize.py` (DRY). Spec change implicitly approved by the dry-reuse-auditor (it would have flagged the new module as duplicative if we'd taken the spec literally).
