"""Result dataclasses for the protocol_knowledgebase subagent connectors.

Shared by openwetware.py, protocols_io.py, the tools.py RunContext
wrappers, and the parent-agent approval tool (via the cached JSON payload).
These are @dataclass, not pydantic models — serialize with
``dataclasses.asdict`` + ``json.dumps``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ExternalProtocolStep:
    text: str
    duration_min: int | None  # parsed from step text where present


@dataclass
class ExternalProtocolPayload:
    title: str
    source_url: str
    summary: str
    materials: list[str] = field(default_factory=list)
    steps: list[ExternalProtocolStep] = field(default_factory=list)
    notes: str | None = None
    license: str = "CC BY-SA 3.0"
    attribution: str = ""
    error: str | None = None
    # F-0090: a license-restricted protocol is parsed to metadata only
    # (steps stay empty, no step text copied) and flagged import_allowed=False.
    # This is NOT an error — error means a genuine fetch/parse failure.
    import_allowed: bool = True
    license_note: str | None = None
    # F-0090: the human-readable source name. Typed Literal (not bare str)
    # so a future connector cannot smuggle markdown via a closing `)` —
    # the parent agent emits this value inside `[<source_label> source](<url>)`.
    source_label: Literal["", "OpenWetWare", "protocols.io"] = ""


@dataclass
class OpenWetWareHit:
    title: str
    url: str
    snippet: str


@dataclass
class OpenWetWareSearchResult:
    total: int
    hits: list[OpenWetWareHit] = field(default_factory=list)
    message: str = ""


@dataclass
class ProtocolsIoHit:
    id: str
    title: str
    url: str
    snippet: str


@dataclass
class ProtocolsIoSearchResult:
    total: int
    hits: list[ProtocolsIoHit] = field(default_factory=list)
    message: str = ""
