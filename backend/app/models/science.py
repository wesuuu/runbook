"""Transitional shim (TD-0083) — re-exports the split `science` models.

Deleted once all imports migrate to the domain modules. Import from
`app.models.protocols` / `.runs` / `.projects` / `.equipment` / `.sites` /
`.signoffs` instead.
"""

from app.models.equipment import Equipment, EquipmentAttachment, EquipmentStatus
from app.models.projects import Project
from app.models.protocols import (
    Protocol,
    ProtocolRole,
    ProtocolVersion,
    UnitOpDefinition,
    UnitOpLibrarySubscription,
)
from app.models.runs import (
    Experiment,
    ExperimentStatus,
    Run,
    RunOutcome,
    RunRoleAssignment,
    RunStatus,
)
from app.models.signoffs import (
    GlpRole,
    GlpSignoff,
    GlpSignoffAction,
    GlpSignoffRequest,
    GlpSignoffRequestStatus,
)
from app.models.sites import Site, SiteManagerGrant

__all__ = [
    "Equipment",
    "EquipmentAttachment",
    "EquipmentStatus",
    "Project",
    "Protocol",
    "ProtocolRole",
    "ProtocolVersion",
    "UnitOpDefinition",
    "UnitOpLibrarySubscription",
    "Experiment",
    "ExperimentStatus",
    "Run",
    "RunOutcome",
    "RunRoleAssignment",
    "RunStatus",
    "GlpRole",
    "GlpSignoff",
    "GlpSignoffAction",
    "GlpSignoffRequest",
    "GlpSignoffRequestStatus",
    "Site",
    "SiteManagerGrant",
]
