"""Public service API for legal document versions.

Used by:
  * `app.api.endpoints.legal` — to serve content over HTTP.
  * `app.schemas.auth.UserResponse` — to compute `tos_current`.
  * `app.api.endpoints.auth.accept_tos` — to pin acceptance to `get_current_version()`.

Document content is read from disk at module load time (cached in memory)
because it is bundled with the deploy and never changes at runtime.
"""

from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from app.legal.versions import ALL_VERSIONS, CURRENT_VERSION

ALLOWED_DOCS: tuple[str, ...] = ("terms", "privacy")


class LegalDocument(TypedDict):
    version: str
    effective_date: str
    markdown: str


def get_current_version() -> str:
    return CURRENT_VERSION


def list_versions() -> list[str]:
    return list(ALL_VERSIONS)


@lru_cache(maxsize=None)
def get_document(version: str, doc: str) -> LegalDocument:
    """Read a versioned legal document from disk and return its content.

    Raises:
        KeyError: when `version` is not in ALL_VERSIONS.
        ValueError: when `doc` is not in ALLOWED_DOCS.
        FileNotFoundError: when the expected markdown file is missing on disk.
    """
    if version not in ALL_VERSIONS:
        raise KeyError(version)
    if doc not in ALLOWED_DOCS:
        raise ValueError(f"unknown document type: {doc!r}")

    base = Path(__file__).parent / "versions" / version
    markdown = (base / f"{doc}.md").read_text(encoding="utf-8")

    return LegalDocument(
        version=version,
        effective_date=version,
        markdown=markdown,
    )
