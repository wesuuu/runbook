"""PDF generation service — re-export wrapper.

This module re-exports the public API from the split submodules
for backward compatibility. All PDF generation logic lives in:
- pdf_base.py: shared constants, format helpers, table drawing
- sop_generator.py: SOP PDF generation
- batch_record_generator.py: batch record PDF generation
"""

from app.services.sop_generator import generate_sop_pdf
from app.services.batch_record_generator import generate_batch_record_pdf
from app.services.pdf_base import _get_initials

__all__ = [
    "generate_sop_pdf",
    "generate_batch_record_pdf",
    "_get_initials",
]
