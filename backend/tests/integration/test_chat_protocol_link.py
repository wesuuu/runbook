"""End-to-end: chat agent emits canonical protocol URL (not UUID form)
and the sanitizer scrubs any hallucinated /protocols/<uuid> link.

Mandatory regression for BUG-0009 #1. Proves that the sanitizer pass in
sanitize_output (Task 1.6) is wired correctly through send_message_streaming
— a fake agent returning raw text that contains BOTH a canonical org-scoped
link AND a bare /protocols/<uuid> link lands in the DB with the canonical
link intact and the bare one scrubbed.

Harness mirrors test_chat_concurrency.py: patch build_chat_agent, drive
send_message_streaming directly, read back the persisted ChatMessage row.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatMessageRole
from app.models.iam import Organization, User
from app.services.ai.send_message import send_message_streaming
from app.services.ai.sessions import create_session

# A model reply that contains:
#   - a CANONICAL org-scoped link  → must survive sanitization
#   - a BARE /protocols/<uuid> link → must be scrubbed by the sanitizer
_CANONICAL_HREF = "/test-org/protocols/buffer-mix-v1"
_BARE_HREF = "/protocols/abc-123-uuid"

_MODEL_REPLY = (
    f"I created [Buffer Mix v1]({_CANONICAL_HREF}) for you. "
    f"You can also see it at [Buffer Mix v1 (old)]({_BARE_HREF}) but "
    "that link format is deprecated."
)


async def _drain(session):
    """Exhaust send_message_streaming and return all yielded events."""
    events = []
    async for ev in send_message_streaming(
        session.db,
        session.chat_session,
        "Create buffer mix protocol",
        user_id=session.user_id,
        is_org_admin=False,
    ):
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_chat_emits_canonical_url_and_strips_hallucinated_uuid_link(
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
):
    """The model is stubbed to return a reply that contains BOTH a correct
    canonical /{org-slug}/protocols/{slug} link AND a hallucinated bare
    /protocols/<uuid> link. The persisted assistant message must:

      - preserve the canonical /{org}/protocols/{slug} href
      - NOT contain `(/protocols/abc-123-uuid)` anywhere (sanitizer scrubbed it)
      - still contain the label text `[Buffer Mix v1 (old)]` (label is kept)
    """
    chat_session = await create_session(
        db_session, user_id=test_user.id, org_id=test_org.id
    )

    async def fake_run(prompt, deps, message_history=None, **kwargs):
        result = MagicMock()
        result.output = _MODEL_REPLY
        result.all_messages = MagicMock(return_value=[])
        return result

    fake_agent = MagicMock()
    fake_agent.run = fake_run

    async def fake_build(*args, **kwargs):
        return fake_agent

    events = []
    with patch("app.services.ai.send_message.build_chat_agent", fake_build):
        async for ev in send_message_streaming(
            db_session,
            chat_session,
            "Create buffer mix protocol",
            user_id=test_user.id,
            is_org_admin=False,
        ):
            events.append(ev)

    # There should be a 'done' event
    done_events = [e for e in events if e.get("type") == "done"]
    assert done_events, f"Expected a 'done' event, got: {events}"
    done = done_events[0]

    # The done event itself carries the sanitized content
    assistant_content_in_event = done["assistant_message"]["content"]

    # ── Assertions against the stream event ─────────────────────────────────
    # Canonical href must survive
    assert _CANONICAL_HREF in assistant_content_in_event, (
        f"Canonical href {_CANONICAL_HREF!r} was stripped from the event "
        f"output; sanitizer over-fired.\nContent: {assistant_content_in_event!r}"
    )
    # Bare bare href must be scrubbed
    assert _BARE_HREF not in assistant_content_in_event, (
        f"Bare href {_BARE_HREF!r} survived in the event output; "
        f"sanitizer did not fire.\nContent: {assistant_content_in_event!r}"
    )
    # Label text must be kept (only the href is removed, not the label)
    assert "[Buffer Mix v1 (old)]" in assistant_content_in_event, (
        "Link label was stripped along with the href; sanitizer must keep "
        f"the label.\nContent: {assistant_content_in_event!r}"
    )

    # ── Assertions against the PERSISTED DB row ──────────────────────────────
    # send_message_streaming writes through AsyncSessionLocal (rebound to the
    # same connection by the db_session conftest fixture), so the row is
    # visible on db_session immediately after draining the stream.
    result = await db_session.execute(
        select(ChatMessage).where(
            ChatMessage.session_id == chat_session.id,
            ChatMessage.role == ChatMessageRole.ASSISTANT,
        )
    )
    persisted = result.scalar_one()

    # The persisted content must match the sanitized content in the event
    assert persisted.content == assistant_content_in_event, (
        "Persisted assistant message content differs from the streamed event "
        f"content.\nPersisted: {persisted.content!r}\nEvent: {assistant_content_in_event!r}"
    )

    # Canonical href must survive in the persisted row
    assert _CANONICAL_HREF in persisted.content, (
        f"Canonical href {_CANONICAL_HREF!r} missing from persisted row.\n"
        f"Content: {persisted.content!r}"
    )

    # Bare href must be absent from the persisted row
    assert _BARE_HREF not in persisted.content, (
        f"Bare href {_BARE_HREF!r} present in persisted row — sanitizer "
        f"did not scrub it.\nContent: {persisted.content!r}"
    )

    # Label must still be present in the persisted row
    assert "[Buffer Mix v1 (old)]" in persisted.content, (
        f"Link label missing from persisted row.\nContent: {persisted.content!r}"
    )
