"""URL-slug generation. Pure functions only — safe to import from Alembic."""

import re
import secrets
import unicodedata

SLUG_MAX_LENGTH = 64

# Slugs that would shadow a static segment of the GitHub-style URL scheme
# (/:org/:object/:slug and its nested project forms). A routed object may
# never take one of these as its slug, or the router could not tell a record
# apart from a route. Enforced on the live path by `assign_slug`; the
# migration backfill disambiguates them via `dedupe_slugs`.
RESERVED_SLUGS: frozenset[str] = frozenset(
    {
        "new",
        "projects",
        "runs",
        "experiments",
        "protocols",
        "library",
        "documents",
    }
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_EDGE_HYPHENS = re.compile(r"^-+|-+$")


def slugify(name: str) -> str:
    """Convert a display name to a URL-safe slug.

    Lowercase -> strip accents -> drop non-alphanumerics -> collapse
    separator runs to a single '-' -> trim -> cap at 64 chars. Returns
    "" when the input has no alphanumeric content; the caller supplies a
    fallback (see `dedupe_slugs` / `assign_slug`).
    """
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    collapsed = _NON_ALNUM.sub("-", ascii_only.lower())
    trimmed = _EDGE_HYPHENS.sub("", collapsed)
    return trimmed[:SLUG_MAX_LENGTH].rstrip("-")


def _fallback_slug() -> str:
    """Slug for a name with no alphanumeric content. Effectively unique."""
    return f"untitled-{secrets.token_hex(3)}"


def dedupe_slugs(items: list[tuple[object, str]]) -> dict[object, str]:
    """Assign collision-free slugs to a batch of rows sharing one scope.

    `items` is (row_id, base_slug) ordered oldest-first. The first row to
    claim a base keeps it; later rows get '-2', '-3', ... A base that is
    empty gets an 'untitled-<hex>' fallback. A base equal to a reserved
    word is disambiguated the same way (no row keeps the bare slug). Used
    only by the migration backfill — the live path rejects collisions and
    reserved words instead.
    """
    result: dict[object, str] = {}
    # Seed `used` with the reserved words so no row claims a bare reserved
    # slug; such a base falls through to the '-2' suffix path below.
    used: set[str] = set(RESERVED_SLUGS)
    for row_id, base in items:
        base = base or _fallback_slug()
        candidate = base
        n = 1
        while candidate in used:
            n += 1
            suffix = f"-{n}"
            candidate = base[: SLUG_MAX_LENGTH - len(suffix)].rstrip("-") + suffix
        used.add(candidate)
        result[row_id] = candidate
    return result
