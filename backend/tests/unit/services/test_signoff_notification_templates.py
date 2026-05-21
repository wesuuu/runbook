"""Notification templates for run sign-off events (F-0080)."""

from app.services.core.notifications.templates import TEMPLATES


def test_run_signoff_requested_template_registered():
    assert "RUN_SIGNOFF_REQUESTED" in TEMPLATES
    title, body = TEMPLATES["RUN_SIGNOFF_REQUESTED"](
        {"run_name": "Run 7", "role": "QAU"}, personal=True
    )
    assert "Run 7" in title
    assert "QAU" in body or "Quality Assurance" in body


def test_run_signoff_cancelled_template_registered():
    assert "RUN_SIGNOFF_CANCELLED" in TEMPLATES
    title, body = TEMPLATES["RUN_SIGNOFF_CANCELLED"](
        {"run_name": "Run 7"}, personal=True
    )
    assert "Run 7" in title
