"""TD-0091c: invite_html escapes dynamic values and validates accept_url
host against settings.backend_url; INVITE_SENT returns html_body iff
accept_url is supplied."""

import pytest

from app.services.core.notifications.templates import (
    TEMPLATES,
    TemplateResult,
    invite_html,
)


def test_invite_html_escapes_org_name_and_inviter():
    """Admin-set org name and user-controlled inviter name must not leak
    raw HTML into the rendered body."""
    from app.core.config import settings

    accept_url = f"{settings.backend_url}/auth/accept-invite?token=abc"
    out = invite_html(
        org_name="<script>alert(1)</script>",
        invited_by='Eve "</a><img src=x>',
        accept_url=accept_url,
        expires_at="2026-06-01",
    )
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    assert "<img src=x>" not in out


def test_invite_html_rejects_foreign_host():
    """accept_url must point at settings.backend_url; phishing redirects fail."""
    with pytest.raises(ValueError, match="Invalid accept_url"):
        invite_html(
            org_name="Batchrite",
            invited_by="Admin",
            accept_url="https://evil.example.com/auth/accept-invite?token=x",
        )


def test_invite_html_allows_matching_host():
    from app.core.config import settings

    accept_url = f"{settings.backend_url}/auth/accept-invite?token=abc"
    out = invite_html(
        org_name="Batchrite",
        invited_by="Admin",
        accept_url=accept_url,
    )
    assert "Batchrite" in out
    assert accept_url in out or "&amp;" in out  # url is html-escaped


def test_invite_sent_returns_template_result_with_html_when_accept_url_present():
    from app.core.config import settings

    accept_url = f"{settings.backend_url}/auth/accept-invite?token=abc"
    result = TEMPLATES["INVITE_SENT"](
        {
            "org_name": "Batchrite",
            "invited_by": "Admin",
            "accept_url": accept_url,
            "expires_at": "2026-06-01",
        },
    )
    assert isinstance(result, TemplateResult)
    assert result.html_body is not None
    assert "Batchrite" in result.html_body
    assert "Batchrite" in result.title


def test_invite_sent_returns_2tuple_when_accept_url_absent():
    """In-app-only invites (no email link) keep the 2-tuple legacy shape."""
    result = TEMPLATES["INVITE_SENT"](
        {"org_name": "Batchrite", "invited_by": "Admin"},
    )
    # Either a 2-tuple or a TemplateResult with html_body=None is acceptable.
    if isinstance(result, TemplateResult):
        assert result.html_body is None
    else:
        title, body = result
        assert "Batchrite" in title
