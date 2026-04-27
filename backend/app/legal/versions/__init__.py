"""Registered legal document versions.

CURRENT_VERSION is the single explicit constant that controls what version
the app considers "live in production." Bumping it is the activation step.

ALL_VERSIONS is the full chronological list. CURRENT_VERSION must be a member.
Old versions are never removed — they remain valid for historical lookups
and to preserve the meaning of `users.tos_version` values pinned to old
versions.

Activation commit message convention (grep-able):

    feat(legal): activate ToS/Privacy version <date>
"""

CURRENT_VERSION = "2026-04-27"

ALL_VERSIONS = [
    "2026-04-27",
]

assert CURRENT_VERSION in ALL_VERSIONS, (
    f"CURRENT_VERSION={CURRENT_VERSION!r} is not in ALL_VERSIONS"
)
