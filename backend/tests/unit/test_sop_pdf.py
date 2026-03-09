"""Tests for SOP PDF generation."""

import pytest
from app.services.pdf import generate_sop_pdf


class TestGenerateSopPdf:
    """Test generate_sop_pdf produces valid PDFs."""

    def _single_role_steps(self):
        return [
            {
                "role_name": "Operator",
                "steps": [
                    {
                        "name": "Step 1",
                        "description": "Do the thing",
                        "params": None,
                        "param_schema": None,
                        "duration_min": None,
                    },
                ],
            }
        ]

    def test_basic_sop(self):
        """Test that a basic SOP PDF is generated."""
        pdf_bytes = generate_sop_pdf(
            protocol_name="Test Protocol",
            run_name=None,
            roles_with_steps=self._single_role_steps(),
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500
        assert pdf_bytes[:5] == b"%PDF-"

    def test_with_run_name(self):
        """Test SOP with a run name included."""
        pdf_bytes = generate_sop_pdf(
            protocol_name="Test Protocol",
            run_name="Run-001",
            roles_with_steps=self._single_role_steps(),
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_with_description(self):
        """Test SOP with a protocol description."""
        pdf_bytes = generate_sop_pdf(
            protocol_name="Test Protocol",
            run_name=None,
            roles_with_steps=self._single_role_steps(),
            protocol_description="This is a detailed protocol description.",
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_with_version_and_date(self):
        """Test SOP with version number and last modified date."""
        pdf_bytes = generate_sop_pdf(
            protocol_name="Test Protocol",
            run_name=None,
            roles_with_steps=self._single_role_steps(),
            version_number=3,
            last_modified="March 08, 2026",
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_multi_role(self):
        """Test SOP with multiple named roles gets page breaks."""
        roles_with_steps = [
            {
                "role_name": "Upstream Operator",
                "steps": [
                    {
                        "name": "Seed Culture",
                        "description": "Seed the cells",
                        "params": None,
                        "param_schema": None,
                        "duration_min": 30,
                    },
                ],
            },
            {
                "role_name": "Downstream Operator",
                "steps": [
                    {
                        "name": "Harvest",
                        "description": "Harvest the culture",
                        "params": None,
                        "param_schema": None,
                        "duration_min": 60,
                    },
                ],
            },
        ]
        pdf_bytes = generate_sop_pdf(
            protocol_name="Multi-Role Protocol",
            run_name=None,
            roles_with_steps=roles_with_steps,
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_process_based(self):
        """Test SOP with process sections (no named roles)."""
        roles_with_steps = [
            {
                "role_name": "",
                "process_name": "Buffer Prep",
                "process_description": "Prepare all buffers",
                "steps": [
                    {
                        "name": "Mix Buffer A",
                        "description": "Combine reagents",
                        "params": {"volume": 500},
                        "param_schema": {
                            "properties": {
                                "volume": {"title": "Volume", "unit": "mL"},
                            }
                        },
                        "duration_min": 15,
                    },
                ],
            },
            {
                "role_name": "",
                "process_name": "Cell Culture",
                "steps": [
                    {
                        "name": "Seed Cells",
                        "description": "Transfer cells to flask",
                        "params": None,
                        "param_schema": None,
                        "duration_min": 10,
                    },
                ],
            },
        ]
        pdf_bytes = generate_sop_pdf(
            protocol_name="Process Protocol",
            run_name=None,
            roles_with_steps=roles_with_steps,
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_with_params(self):
        """Test SOP with step parameters generates param sentence."""
        roles_with_steps = [
            {
                "role_name": "",
                "steps": [
                    {
                        "name": "Mix Buffer",
                        "description": "Combine reagents",
                        "params": {"volume_ml": 500, "ph": 7.4},
                        "param_schema": {
                            "properties": {
                                "volume_ml": {"title": "Volume", "unit": "mL"},
                                "ph": {"title": "pH"},
                            }
                        },
                        "duration_min": None,
                    },
                ],
            }
        ]
        pdf_bytes = generate_sop_pdf(
            protocol_name="Param Protocol",
            run_name=None,
            roles_with_steps=roles_with_steps,
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_with_template_description(self):
        """Test SOP with template placeholders in description."""
        roles_with_steps = [
            {
                "role_name": "",
                "steps": [
                    {
                        "name": "Set Temperature",
                        "description": "Set incubator to {{temp}} degrees",
                        "params": {"temp": 37},
                        "param_schema": None,
                        "duration_min": None,
                    },
                ],
            }
        ]
        pdf_bytes = generate_sop_pdf(
            protocol_name="Template Protocol",
            run_name=None,
            roles_with_steps=roles_with_steps,
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_with_duration(self):
        """Test SOP with step duration renders duration text."""
        roles_with_steps = [
            {
                "role_name": "",
                "steps": [
                    {
                        "name": "Incubate",
                        "description": "Place in incubator",
                        "params": None,
                        "param_schema": None,
                        "duration_min": 45,
                    },
                ],
            }
        ]
        pdf_bytes = generate_sop_pdf(
            protocol_name="Duration Protocol",
            run_name=None,
            roles_with_steps=roles_with_steps,
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_format_options_small(self):
        """Test SOP with small font size format option."""
        pdf_bytes = generate_sop_pdf(
            protocol_name="Small Font Protocol",
            run_name=None,
            roles_with_steps=self._single_role_steps(),
            format_options={"font_size": "small"},
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_format_options_large(self):
        """Test SOP with large font and relaxed spacing."""
        pdf_bytes = generate_sop_pdf(
            protocol_name="Large Format Protocol",
            run_name=None,
            roles_with_steps=self._single_role_steps(),
            format_options={
                "font_size": "large",
                "row_spacing": "relaxed",
            },
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_empty_steps(self):
        """Test SOP with a role that has no steps."""
        roles_with_steps = [
            {
                "role_name": "Operator",
                "steps": [],
            }
        ]
        pdf_bytes = generate_sop_pdf(
            protocol_name="Empty Protocol",
            run_name=None,
            roles_with_steps=roles_with_steps,
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_many_steps(self):
        """Test SOP with many steps forces multiple pages."""
        steps = [
            {
                "name": f"Step {i}",
                "description": f"Detailed description for step {i} "
                               f"with enough text to take up space.",
                "params": None,
                "param_schema": None,
                "duration_min": 5,
            }
            for i in range(1, 31)
        ]
        roles_with_steps = [{"role_name": "", "steps": steps}]
        pdf_bytes = generate_sop_pdf(
            protocol_name="Long Protocol",
            run_name=None,
            roles_with_steps=roles_with_steps,
        )
        assert pdf_bytes
        assert len(pdf_bytes) > 2000  # multiple pages = larger file
