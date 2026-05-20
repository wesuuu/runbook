# Import Base
from app.models.ai import AiProviderConfig, ImageConversation, RunImage
from app.models.base import Base
from app.models.batch_record_import import BatchRecordImport
from app.models.billing import StripeEvent  # noqa: F401
from app.models.chat import ChatMessage, ChatSession
from app.models.equipment import Equipment, EquipmentAttachment, EquipmentStatus
from app.models.execution import AuditLog

# Import all models for Side Effects (so they register with Base)
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    Organization,
    OrganizationMember,
    OrgRole,
    PermissionLevel,
    PrincipalType,
    Team,
    TeamMember,
    TeamRole,
    User,
)
from app.models.jobs import BackgroundJob
from app.models.library import Document, DocumentChunk
from app.models.notifications import (
    Notification,
    NotificationChannel,
    NotificationDelivery,
    NotificationSubscription,
)
from app.models.offline import RevokedOfflineToken
from app.models.projects import Project
from app.models.protocols import Protocol, ProtocolVersion, UnitOpDefinition
from app.models.runs import Experiment, ExperimentStatus, Run, RunStatus
from app.models.signoffs import (
    GlpRole,
    GlpSignoff,
    GlpSignoffAction,
    GlpSignoffRequest,
    GlpSignoffRequestStatus,
)
from app.models.sites import Site, SiteManagerGrant
from app.models.templates import DocumentTemplate
