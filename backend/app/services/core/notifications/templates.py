"""Message templates for each notification event type.

Each function returns a TemplateResult (title, body, optional html_body)
given a context dict. Context keys are documented per function.
"""

import html as _html
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.config import settings


@dataclass(frozen=True)
class TemplateResult:
    title: str
    body: str
    html_body: str | None = None


def invite_html(
    org_name: str,
    invited_by: str,
    accept_url: str,
    expires_at: str | None = None,
) -> str:
    """Shared HTML body for INVITE_SENT. Used by both the channel pipeline
    and the direct send_invitation_email path so the recipient sees byte-
    identical markup. All dynamic values are HTML-escaped; accept_url must
    point at the configured backend host (no open-redirect / phishing)."""
    parsed = urlparse(accept_url)
    base = urlparse(settings.backend_url)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        raise ValueError(f"Invalid accept_url host: {parsed.netloc}")

    safe_org = _html.escape(org_name)
    safe_inviter = _html.escape(invited_by)
    safe_url = _html.escape(accept_url)
    expiry_line = (
        f'<p style="color: #999; font-size: 12px;">'
        f"This invitation expires on {_html.escape(expires_at)}."
        f"</p>"
        if expires_at
        else ""
    )
    return f"""<div style="font-family: sans-serif; max-width: 600px;">
  <h2 style="color: #1a1a1a;">You've been invited to join {safe_org}</h2>
  <p style="color: #333; line-height: 1.6;">
    {safe_inviter} has invited you to join <strong>{safe_org}</strong> on Batchrite.
  </p>
  <p style="margin: 24px 0;">
    <a href="{safe_url}"
       style="background: #2563eb; color: white; padding: 12px 24px;
              border-radius: 6px; text-decoration: none; font-weight: 500;">
      Accept Invitation
    </a>
  </p>
  <p style="color: #666; font-size: 13px;">
    Or copy this link: {safe_url}
  </p>
  {expiry_line}
</div>"""


def role_assigned(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, role_name, assigned_by"""
    if personal:
        title = f"You've been assigned to {ctx['run_name']}"
        body = (
            f"You've been assigned as {ctx['role_name']} "
            f"on run {ctx['run_name']} by {ctx['assigned_by']}."
        )
    else:
        title = f"Role assigned on {ctx['run_name']}"
        body = (
            f"{ctx.get('assignee_name', 'A user')} was assigned as "
            f"{ctx['role_name']} on run {ctx['run_name']}."
        )
    return title, body


def role_unassigned(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, role_name, removed_by"""
    if personal:
        title = f"Removed from {ctx['run_name']}"
        body = (
            f"You've been unassigned from {ctx['role_name']} "
            f"on run {ctx['run_name']} by {ctx['removed_by']}."
        )
    else:
        title = f"Role unassigned on {ctx['run_name']}"
        body = (
            f"{ctx.get('unassignee_name', 'A user')} was unassigned from "
            f"{ctx['role_name']} on run {ctx['run_name']}."
        )
    return title, body


def role_reassigned(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, role_name, old_user_name, new_user_name, reassigned_by"""
    if personal:
        title = f"Role change on {ctx['run_name']}"
        body = (
            f"You've been assigned as {ctx['role_name']} "
            f"on run {ctx['run_name']} (previously {ctx['old_user_name']})."
        )
    else:
        title = f"Role reassigned on {ctx['run_name']}"
        body = (
            f"{ctx['role_name']} on run {ctx['run_name']} was reassigned "
            f"from {ctx['old_user_name']} to {ctx['new_user_name']}."
        )
    return title, body


def run_started(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, started_by"""
    title = f"Run started: {ctx['run_name']}"
    if personal:
        body = (
            f"Run {ctx['run_name']} has been started by {ctx['started_by']}. "
            f"You are assigned to this run."
        )
    else:
        body = f"Run {ctx['run_name']} has been started by {ctx['started_by']}."
    return title, body


def run_completed(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, completed_by"""
    title = f"Run completed: {ctx['run_name']}"
    body = (
        f"Run {ctx['run_name']} has been marked as completed by {ctx['completed_by']}."
    )
    return title, body


def invite_sent(ctx: dict, personal: bool = True):
    """ctx: org_name, invited_by, accept_url (optional), expires_at (optional).

    Returns a TemplateResult with html_body when accept_url is supplied;
    otherwise a 2-tuple (legacy in-app-only callers)."""
    org_name = ctx["org_name"]
    invited_by = ctx["invited_by"]
    title = f"Invitation to {org_name}"
    body = f"You've been invited to join {org_name} by {invited_by}."
    accept_url = ctx.get("accept_url")
    if accept_url:
        html_body = invite_html(
            org_name, invited_by, accept_url, ctx.get("expires_at"),
        )
        return TemplateResult(title=title, body=body, html_body=html_body)
    return title, body


def invite_accepted(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: org_name, accepted_by"""
    title = f"Invite accepted: {ctx['org_name']}"
    body = f"{ctx['accepted_by']} has accepted the invitation to {ctx['org_name']}."
    return title, body


def protocol_approved(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: protocol_name, approved_by"""
    title = f"Protocol approved: {ctx['protocol_name']}"
    body = (
        f"Protocol {ctx['protocol_name']} has been approved "
        f"by {ctx['approved_by']}."
    )
    return title, body


def protocol_reverted(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: protocol_name, edited_by"""
    title = f"Protocol reverted to draft: {ctx['protocol_name']}"
    body = (
        f"Protocol {ctx['protocol_name']} was edited by {ctx['edited_by']} "
        f"and has been reverted from APPROVED to DRAFT."
    )
    return title, body


def protocol_approval_requested(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: protocol_name, requested_by, role (optional: 'STUDY_DIRECTOR' | 'QAU')"""
    role = ctx.get("role")
    role_label = {
        "STUDY_DIRECTOR": "Study Director",
        "QAU": "QAU (Quality Assurance)",
    }.get(role or "", "approver")
    title = f"Approval requested: {ctx['protocol_name']}"
    body = (
        f"{ctx['requested_by']} requested your approval on protocol "
        f"{ctx['protocol_name']} as {role_label}."
    )
    return title, body


def step_deviation(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, step_name, edited_by, additional_count (optional)"""
    title = f"Step deviation on {ctx['run_name']}"
    body = (
        f"Step \"{ctx['step_name']}\" on run {ctx['run_name']} was edited "
        f"post-completion by {ctx['edited_by']}."
    )
    extra = ctx.get("additional_count", 0)
    if extra:
        body += (
            f" ({extra} other step{'s' if extra != 1 else ''} also changed.)"
        )
    return title, body


def pending_image_analysis(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, unanalyzed_count, completed_by"""
    count = ctx["unanalyzed_count"]
    title = f"Pending image analysis on {ctx['run_name']}"
    body = (
        f"Run {ctx['run_name']} was completed by {ctx['completed_by']} "
        f"with {count} unanalyzed image{'s' if count != 1 else ''}. "
        f"Review and analyze them when ready."
    )
    return title, body


def offline_sync_pending(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, user_name"""
    title = f"Field session active: {ctx['run_name']}"
    if personal:
        body = (
            f"You have an active field session for run {ctx['run_name']}. "
            f"Remember to sync your data when you're back online."
        )
    else:
        body = (
            f"{ctx.get('user_name', 'A user')} has an active field session "
            f"for run {ctx['run_name']}."
        )
    return title, body


def offline_value_discrepancy(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, step_name, field_name, manual_value, ai_value"""
    title = f"Value discrepancy on {ctx['run_name']}"
    body = (
        f"Step \"{ctx['step_name']}\" field \"{ctx['field_name']}\" "
        f"has a discrepancy: manual value {ctx['manual_value']} "
        f"vs AI value {ctx['ai_value']}. Please review."
    )
    return title, body


def run_signoff_requested(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, role ('STUDY_DIRECTOR' | 'QAU')"""
    role_label = {
        "STUDY_DIRECTOR": "Study Director",
        "QAU": "QAU (Quality Assurance)",
    }.get(ctx.get("role") or "", "reviewer")
    title = f"Review requested: {ctx['run_name']}"
    body = (
        f"Run {ctx['run_name']} is awaiting your sign-off as {role_label}."
    )
    return title, body


def run_signoff_cancelled(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name"""
    title = f"Review cancelled: {ctx['run_name']}"
    body = (
        f"The sign-off request for run {ctx['run_name']} was cancelled "
        f"because the run was reopened."
    )
    return title, body


# Registry mapping event types to template functions
TEMPLATES = {
    "ROLE_ASSIGNED": role_assigned,
    "ROLE_UNASSIGNED": role_unassigned,
    "ROLE_REASSIGNED": role_reassigned,
    "RUN_STARTED": run_started,
    "RUN_COMPLETED": run_completed,
    "INVITE_SENT": invite_sent,
    "INVITE_ACCEPTED": invite_accepted,
    "PROTOCOL_APPROVED": protocol_approved,
    "PROTOCOL_REVERTED": protocol_reverted,
    "PROTOCOL_APPROVAL_REQUESTED": protocol_approval_requested,
    "STEP_DEVIATION": step_deviation,
    "PENDING_IMAGE_ANALYSIS": pending_image_analysis,
    "OFFLINE_SYNC_PENDING": offline_sync_pending,
    "OFFLINE_VALUE_DISCREPANCY": offline_value_discrepancy,
    "RUN_SIGNOFF_REQUESTED": run_signoff_requested,
    "RUN_SIGNOFF_CANCELLED": run_signoff_cancelled,
}
