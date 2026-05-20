"""License-compatibility gate for imported external protocols (F-0090).

Pure and shared. A protocol is import-safe only if its license permits BOTH
commercial use AND derivative works — Batchrite is a commercial product and
importing a protocol into an editable graph is a derivative work. Fails
closed: an empty or unrecognized license is treated as not import-safe.

protocols.io public content is uniformly CC-BY, so for that source this is
fail-closed *verification*, not a router. PMC OA (a future source) mixes
CC-BY / CC-BY-NC / CC-BY-NC-ND / CC0 and needs the routing — hence shared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Commercial use AND derivatives both permitted. ShareAlike (SA) is included:
# it only obligates same-terms on *external redistribution*, which the
# customer Terms of Service allocate to the customer (F-0090 §B.9).
_IMPORT_SAFE = {"CC0", "CC-BY", "CC-BY-SA", "PUBLIC-DOMAIN"}


@dataclass(frozen=True)
class LicenseVerdict:
    normalized: str  # canonical form, e.g. "CC-BY", "CC-BY-NC", "UNKNOWN"
    import_allowed: bool
    reason: str  # human-readable; surfaced as license_note


def _normalize(raw: str) -> str:
    """Uppercase, drop version numbers, collapse separators to ``-``."""
    # Strip version numbers — a number preceded by whitespace (" 3.0",
    # " 4.0"). The leading-whitespace anchor protects the "0" in "CC0".
    s = re.sub(r"\s+\d+(?:\.\d+)?", "", raw.upper())
    s = re.sub(r"[\s_/]+", "-", s.strip())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def classify_license(raw: str | None) -> LicenseVerdict:
    """Classify a raw license string into an import verdict."""
    if not raw or not raw.strip():
        return LicenseVerdict(
            "UNKNOWN", False, "No license specified; cannot verify reuse rights."
        )
    normalized = _normalize(raw)
    tokens = normalized.split("-")
    if "NC" in tokens:
        return LicenseVerdict(
            normalized,
            False,
            "NonCommercial license — Batchrite is a commercial product.",
        )
    if "ND" in tokens:
        return LicenseVerdict(
            normalized,
            False,
            "NoDerivatives license — importing a protocol builds a derivative.",
        )
    if normalized in _IMPORT_SAFE:
        return LicenseVerdict(
            normalized,
            True,
            f"{normalized} permits commercial use and derivative works.",
        )
    return LicenseVerdict(
        "UNKNOWN",
        False,
        f"Unrecognized license {raw!r}; cannot verify reuse rights.",
    )
