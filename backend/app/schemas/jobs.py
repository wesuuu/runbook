"""Shared schemas for background job tracking and progress reporting."""

from typing import Optional

from pydantic import BaseModel


class ProcessingProgress(BaseModel):
    """Progress information for a running or recently completed background job.

    Used by any feature that runs async work via BackgroundJobService.
    """

    stage: str = ""
    stage_label: str = ""
    current: int = 0
    total: int = 0
    percent: int = 0
    status: str = ""
    error_message: Optional[str] = None
