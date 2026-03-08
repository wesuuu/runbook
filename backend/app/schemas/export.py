from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class ExportLayout(str, Enum):
    LONG = "long"
    WIDE = "wide"


class ExportFormat(str, Enum):
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"


class ColumnDef(BaseModel):
    key: str
    label: str
    group: str  # "metadata", "step", "data", "audit"


class ExportPreviewRequest(BaseModel):
    run_ids: list[UUID]
    layout: ExportLayout = ExportLayout.LONG


class ExportPreviewResponse(BaseModel):
    columns: list[ColumnDef]
    rows: list[dict[str, Any]]
    run_count: int


class ExportDownloadRequest(BaseModel):
    run_ids: list[UUID]
    format: ExportFormat
    layout: ExportLayout = ExportLayout.LONG
    columns: Optional[list[str]] = None
