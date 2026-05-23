"""TD-0091c: ensure the backfill migration's event list matches DEFAULT_POLICY.

The literal event list in the migration must equal the set of policy entries
with email=True at the time the migration was written. If you change
DEFAULT_POLICY's email defaults, write a new migration rather than mutating
this one — old migrations are immutable history.
"""

import re
from pathlib import Path

from app.models.notifications import NotificationEventType
from app.services.core.notifications.policy import DEFAULT_POLICY

MIGRATION_PATH = (
    Path(__file__).parent.parent.parent
    / "alembic"
    / "versions"
    / "td0091c_c_backfill_default_channels.py"
)


def test_migration_event_list_matches_policy_email_set():
    expected = {ev for ev, p in DEFAULT_POLICY.items() if p.email}
    source = MIGRATION_PATH.read_text()
    match = re.search(r"CROSS JOIN \(VALUES(.+?)\) AS e", source, re.S)
    assert match is not None, "Could not locate VALUES tuple in migration"
    event_names = {e.value for e in NotificationEventType}
    found = set(re.findall(r"'([A-Z_]+)'", match.group(1))) & event_names
    assert found == expected, f"Migration drift: {found ^ expected}"
