"""Message templates for each notification event type.

Each function returns (title, body) given a context dict.
Context keys are documented per function.
"""


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
    body = f"Run {ctx['run_name']} has been marked as completed by {ctx['completed_by']}."
    return title, body


def invite_sent(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: org_name, invited_by"""
    title = f"Invitation to {ctx['org_name']}"
    body = (
        f"You've been invited to join {ctx['org_name']} "
        f"by {ctx['invited_by']}."
    )
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


def step_deviation(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, step_name, edited_by"""
    title = f"Step deviation on {ctx['run_name']}"
    body = (
        f"Step \"{ctx['step_name']}\" on run {ctx['run_name']} was edited "
        f"post-completion by {ctx['edited_by']}."
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
    "STEP_DEVIATION": step_deviation,
    "PENDING_IMAGE_ANALYSIS": pending_image_analysis,
    "OFFLINE_SYNC_PENDING": offline_sync_pending,
    "OFFLINE_VALUE_DISCREPANCY": offline_value_discrepancy,
}
