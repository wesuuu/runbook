"""Transitional shim (TD-0083) — re-exports the moved library_registry.

Deleted once all imports migrate to `app.services.protocols`.
"""

from app.services.protocols import library_registry  # noqa: F401
