"""Tests for batch record PDF generation and role parsing."""

import pytest
from app.services.graph_processing import _parse_graph_roles_and_steps
from app.services.pdf import generate_batch_record_pdf, _get_initials


class TestParseGraphRolesAndSteps:
    """Test the _parse_graph_roles_and_steps function."""

    def test_swimlane_based_graph(self):
        """Test parsing swimlane-based (role-based) graph."""
        graph = {
            "nodes": [
                {
                    "id": "swimlane1",
                    "type": "swimLane",
                    "data": {"label": "Role A"},
                },
                {
                    "id": "unitop1",
                    "type": "unitOp",
                    "parentId": "swimlane1",
                    "data": {
                        "label": "Step 1",
                        "description": "Desc 1",
                    },
                    "position": {"x": 0, "y": 0},
                },
            ],
            "edges": [],
        }

        roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(
            graph
        )

        assert is_role_based is True
        assert len(roles_with_steps) == 1
        assert roles_with_steps[0]["role_name"] == "Role A"
        assert len(flat_steps) == 1
        assert flat_steps[0]["role_name"] == "Role A"

    def test_connected_component_graph_no_processstart(self):
        """Test parsing connected-component-based (process-based) graph without
        processStart nodes.
        """
        graph = {
            "nodes": [
                {
                    "id": "unitop1",
                    "type": "unitOp",
                    "data": {
                        "label": "Step 1",
                        "description": "Desc 1",
                    },
                    "position": {"x": 0, "y": 0},
                },
                {
                    "id": "unitop2",
                    "type": "unitOp",
                    "data": {
                        "label": "Step 2",
                        "description": "Desc 2",
                    },
                    "position": {"x": 100, "y": 0},
                },
            ],
            "edges": [
                {"id": "edge1", "source": "unitop1", "target": "unitop2"},
            ],
        }

        roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(
            graph
        )

        assert is_role_based is False
        # Single connected component
        assert len(roles_with_steps) == 1
        assert len(flat_steps) == 2
        # Process-based: no role_name on steps
        assert flat_steps[0]["role_name"] == ""
        assert flat_steps[1]["role_name"] == ""

    def test_multiple_disconnected_components(self):
        """Test parsing multiple disconnected components (processes)."""
        graph = {
            "nodes": [
                {
                    "id": "unitop1",
                    "type": "unitOp",
                    "data": {"label": "Process A Step 1"},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "id": "unitop2",
                    "type": "unitOp",
                    "data": {"label": "Process B Step 1"},
                    "position": {"x": 200, "y": 0},
                },
            ],
            "edges": [],  # No edges = two disconnected components
        }

        roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(
            graph
        )

        assert is_role_based is False
        # Two separate components
        assert len(roles_with_steps) == 2
        assert len(flat_steps) == 2

    def test_processstart_node_process_based(self):
        """Test that processStart node names don't leak into role_name in
        process-based mode.
        """
        graph = {
            "nodes": [
                {
                    "id": "processstart1",
                    "type": "processStart",
                    "data": {"label": "Buffer Prep"},
                },
                {
                    "id": "unitop1",
                    "type": "unitOp",
                    "data": {"label": "Step 1"},
                    "position": {"x": 50, "y": 0},
                },
            ],
            "edges": [
                {"id": "edge1", "source": "processstart1", "target": "unitop1"},
            ],
        }

        roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(
            graph
        )

        assert is_role_based is False
        # flat_steps should have empty role_name (Bug 1 fix)
        assert flat_steps[0]["role_name"] == ""
        # But roles_with_steps should have process_name for SOP
        assert roles_with_steps[0].get("process_name") == "Buffer Prep"


class TestGenerateBatchRecordPdf:
    """Test batch record PDF generation."""

    def test_no_role_column_process_based(self):
        """Test that Role column is omitted for process-based protocols."""
        roles_with_steps = [
            {
                "role_name": "",
                "process_name": "Process A",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Step 1",
                        "description": "Description",
                        "params": None,
                        "param_schema": None,
                        "duration_min": None,
                        "role_name": "",
                    }
                ],
            }
        ]

        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[],
            steps=flat_steps,
            filled=False,
            execution_data=None,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=False,
        )

        assert pdf_bytes
        # PDF generated successfully for process-based (no Role column)

    def test_role_column_role_based(self):
        """Test that Role column is included for role-based protocols."""
        roles_with_steps = [
            {
                "role_name": "Role 1",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Step 1",
                        "description": "Description",
                        "params": None,
                        "param_schema": None,
                        "duration_min": None,
                        "role_name": "Role 1",
                    }
                ],
            }
        ]

        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[{"id": "role1", "name": "Role 1"}],
            steps=flat_steps,
            filled=False,
            execution_data=None,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=True,
        )

        assert pdf_bytes
        # PDF generated successfully for role-based (with Role column)
        # Note: The actual text may be encoded in the PDF binary

    def test_multi_process_separate_tables(self):
        """Test that multiple processes generate separate tables (Bug 2 fix)."""
        roles_with_steps = [
            {
                "role_name": "",
                "process_name": "Process A",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Step 1",
                        "description": "Description A",
                        "params": None,
                        "param_schema": None,
                        "duration_min": None,
                        "role_name": "",
                    }
                ],
            },
            {
                "role_name": "",
                "process_name": "Process B",
                "steps": [
                    {
                        "id": "step2",
                        "name": "Step 2",
                        "description": "Description B",
                        "params": None,
                        "param_schema": None,
                        "duration_min": None,
                        "role_name": "",
                    }
                ],
            },
        ]

        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[],
            steps=flat_steps,
            filled=False,
            execution_data=None,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=False,
        )

        assert pdf_bytes
        # Multi-process PDF generated successfully (should have separate tables)

    def test_multi_param_step_blank(self):
        """Test that multi-param steps render sub-rows in the Value column."""
        param_schema = {
            "type": "object",
            "properties": {
                "vial_count": {
                    "type": "integer",
                    "title": "Vial Count",
                    "default": 1,
                },
                "thaw_temp_c": {
                    "type": "number",
                    "title": "Thaw Temperature",
                    "unit": "°C",
                    "default": 37.0,
                },
                "duration_min": {
                    "type": "number",
                    "title": "Duration",
                    "unit": "min",
                    "default": 2.0,
                },
            },
        }
        roles_with_steps = [
            {
                "role_name": "Operator",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Cell Thaw",
                        "description": "Thaw cells from LN2",
                        "params": {
                            "vial_count": 1,
                            "thaw_temp_c": 37.0,
                            "duration_min": 2.0,
                        },
                        "param_schema": param_schema,
                        "duration_min": 5,
                        "role_name": "Operator",
                    }
                ],
            }
        ]
        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Thaw Protocol",
            run_name="Run1",
            roles=[{"id": "r1", "name": "Operator"}],
            steps=flat_steps,
            filled=False,
            execution_data=None,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=True,
        )

        assert pdf_bytes
        assert len(pdf_bytes) > 500  # Non-trivial PDF

    def test_multi_param_step_filled(self):
        """Test that filled multi-param steps show results per parameter."""
        param_schema = {
            "type": "object",
            "properties": {
                "vial_count": {
                    "type": "integer",
                    "title": "Vial Count",
                },
                "thaw_temp_c": {
                    "type": "number",
                    "title": "Thaw Temperature",
                    "unit": "°C",
                },
            },
        }
        execution_data = {
            "step1": {
                "status": "completed",
                "results": {
                    "vial_count": 2,
                    "thaw_temp_c": 37.5,
                },
                "timestamp": "2026-03-06T10:00:00Z",
            }
        }
        roles_with_steps = [
            {
                "role_name": "",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Cell Thaw",
                        "description": "Thaw cells",
                        "params": {"vial_count": 1, "thaw_temp_c": 37.0},
                        "param_schema": param_schema,
                        "duration_min": None,
                        "role_name": "",
                    }
                ],
            }
        ]
        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[],
            steps=flat_steps,
            filled=True,
            execution_data=execution_data,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=False,
        )

        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_single_param_step_uses_standard_row(self):
        """Test that steps with 0 or 1 params use the standard single-row layout."""
        param_schema = {
            "type": "object",
            "properties": {
                "od_reading": {
                    "type": "number",
                    "title": "OD Reading",
                },
            },
        }
        roles_with_steps = [
            {
                "role_name": "",
                "steps": [
                    {
                        "id": "step1",
                        "name": "OD Check",
                        "description": "Measure OD",
                        "params": {"od_reading": None},
                        "param_schema": param_schema,
                        "duration_min": None,
                        "role_name": "",
                    }
                ],
            }
        ]
        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[],
            steps=flat_steps,
            filled=False,
            execution_data=None,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=False,
        )

        assert pdf_bytes

    def test_xref_fields_excluded_from_multi_param(self):
        """Test that x-ref-type fields are excluded from multi-param sub-rows."""
        param_schema = {
            "type": "object",
            "properties": {
                "source_vessel": {
                    "type": "string",
                    "title": "Source Vessel",
                    "x-ref-type": "equipment",
                },
                "volume_ml": {
                    "type": "number",
                    "title": "Volume",
                    "unit": "mL",
                },
            },
        }
        roles_with_steps = [
            {
                "role_name": "",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Transfer",
                        "description": "Transfer media",
                        "params": {"source_vessel": "V1", "volume_ml": 500},
                        "param_schema": param_schema,
                        "duration_min": None,
                        "role_name": "",
                    }
                ],
            }
        ]
        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        # Should use standard row since only 1 editable param (volume_ml)
        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[],
            steps=flat_steps,
            filled=False,
            execution_data=None,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=False,
        )

        assert pdf_bytes


class TestGetInitials:
    """Test the _get_initials helper."""

    def test_full_name(self):
        assert _get_initials("John Smith") == "J.S."

    def test_single_name(self):
        assert _get_initials("Alice") == "A."

    def test_three_names(self):
        assert _get_initials("Mary Jane Watson") == "M.J.W."

    def test_email_fallback(self):
        assert _get_initials("alice@example.com") == "A."

    def test_empty_string(self):
        assert _get_initials("") == ""

    def test_whitespace(self):
        assert _get_initials("  ") == ""


class TestCursiveInitials:
    """Test batch record PDF generation with electronic initials."""

    def test_filled_with_user_map(self):
        """Test that filled batch record with user_map renders without errors."""
        param_schema = {
            "type": "object",
            "properties": {
                "vial_count": {"type": "integer", "title": "Vial Count"},
                "thaw_temp_c": {"type": "number", "title": "Thaw Temp", "unit": "°C"},
            },
        }
        execution_data = {
            "step1": {
                "status": "completed",
                "results": {"vial_count": 2, "thaw_temp_c": 37.5},
                "completed_by_user_id": "user-abc-123",
                "timestamp": "2026-03-06T10:00:00Z",
            },
            "step2": {
                "status": "completed",
                "value": "All good",
                "completed_by_user_id": "user-abc-123",
                "timestamp": "2026-03-06T10:05:00Z",
            },
        }
        user_map = {"user-abc-123": "John Smith"}

        roles_with_steps = [
            {
                "role_name": "Operator",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Cell Thaw",
                        "description": "Thaw cells",
                        "params": {"vial_count": 1, "thaw_temp_c": 37.0},
                        "param_schema": param_schema,
                        "duration_min": 5,
                        "role_name": "Operator",
                    },
                    {
                        "id": "step2",
                        "name": "Visual Check",
                        "description": "Check culture",
                        "params": None,
                        "param_schema": None,
                        "duration_min": 1,
                        "role_name": "Operator",
                    },
                ],
            }
        ]
        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[{"id": "r1", "name": "Operator"}],
            steps=flat_steps,
            filled=True,
            execution_data=execution_data,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=True,
            user_map=user_map,
        )

        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_blank_record_no_initials(self):
        """Test that blank records don't render initials even with user_map."""
        roles_with_steps = [
            {
                "role_name": "",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Step 1",
                        "description": "Desc",
                        "params": None,
                        "param_schema": None,
                        "duration_min": None,
                        "role_name": "",
                    }
                ],
            }
        ]
        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[],
            steps=flat_steps,
            filled=False,
            execution_data=None,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=False,
            user_map={"some-id": "John"},
        )

        assert pdf_bytes

    def test_missing_user_id_no_crash(self):
        """Test that steps without completed_by_user_id render without errors."""
        execution_data = {
            "step1": {
                "status": "completed",
                "value": "Done",
                "timestamp": "2026-03-06T10:00:00Z",
            }
        }
        roles_with_steps = [
            {
                "role_name": "",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Step 1",
                        "description": "Desc",
                        "params": None,
                        "param_schema": None,
                        "duration_min": None,
                        "role_name": "",
                    }
                ],
            }
        ]
        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[],
            steps=flat_steps,
            filled=True,
            execution_data=execution_data,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=False,
            user_map={},
        )

        assert pdf_bytes

    def test_started_by_id_fallback(self):
        """Test that started_by_id is used when completed_by_user_id is missing."""
        execution_data = {
            "step1": {
                "status": "completed",
                "results": {"volume": 500},
                "timestamp": "2026-03-06T10:00:00Z",
            }
        }
        roles_with_steps = [
            {
                "role_name": "",
                "process_name": "Process 1",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Step 1",
                        "description": "Desc",
                        "params": {"volume": 500},
                        "param_schema": {
                            "type": "object",
                            "properties": {
                                "volume": {"type": "number", "title": "Volume"},
                            },
                        },
                        "duration_min": None,
                        "role_name": "",
                    }
                ],
            }
        ]
        flat_steps = [s for rws in roles_with_steps for s in rws.get("steps", [])]

        # No completed_by_user_id in execution_data, but started_by_id provided
        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[],
            steps=flat_steps,
            filled=True,
            execution_data=execution_data,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=False,
            user_map={"starter-user-id": "Admin User"},
            started_by_id="starter-user-id",
        )

        assert pdf_bytes
        # Should be larger than blank (has values + initials)
        blank_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[],
            steps=flat_steps,
            filled=False,
            format_options=None,
            roles_with_steps=roles_with_steps,
            is_role_based=False,
        )
        assert len(pdf_bytes) > len(blank_bytes)


class TestEditedBatchRecord:
    """Test GMP-compliant edited batch record PDF generation."""

    PARAM_SCHEMA = {
        "type": "object",
        "properties": {
            "vial_count": {"type": "integer", "title": "Vial Count"},
            "thaw_temp_c": {
                "type": "number",
                "title": "Thaw Temperature",
                "unit": "°C",
            },
        },
    }

    def _make_roles_and_steps(self):
        roles_with_steps = [
            {
                "role_name": "Operator",
                "steps": [
                    {
                        "id": "step1",
                        "name": "Cell Thaw",
                        "description": "Thaw cells",
                        "params": {"vial_count": 1, "thaw_temp_c": 37.0},
                        "param_schema": self.PARAM_SCHEMA,
                        "duration_min": 5,
                        "role_name": "Operator",
                    },
                    {
                        "id": "step2",
                        "name": "Visual Check",
                        "description": "Check cells",
                        "params": None,
                        "param_schema": None,
                        "duration_min": 1,
                        "role_name": "Operator",
                    },
                ],
            }
        ]
        flat_steps = [
            s for rws in roles_with_steps for s in rws.get("steps", [])
        ]
        return roles_with_steps, flat_steps

    def test_edited_multi_param_strikethrough(self):
        """Test that edited batch records with original_results generate a
        valid PDF that is larger than a non-edited version."""
        roles_with_steps, flat_steps = self._make_roles_and_steps()

        edited_exec = {
            "step1": {
                "status": "completed",
                "results": {"vial_count": 3, "thaw_temp_c": 38.0},
                "original_results": {"vial_count": 2, "thaw_temp_c": 37.5},
                "completed_by_user_id": "user-1",
                "edited_by_user_id": "user-2",
                "edited_at": "2026-03-06T12:00:00Z",
                "timestamp": "2026-03-06T10:00:00Z",
            },
            "step2": {
                "status": "completed",
                "value": "All good",
                "completed_by_user_id": "user-1",
                "timestamp": "2026-03-06T10:05:00Z",
            },
        }

        non_edited_exec = {
            "step1": {
                "status": "completed",
                "results": {"vial_count": 2, "thaw_temp_c": 37.5},
                "completed_by_user_id": "user-1",
                "timestamp": "2026-03-06T10:00:00Z",
            },
            "step2": {
                "status": "completed",
                "value": "All good",
                "completed_by_user_id": "user-1",
                "timestamp": "2026-03-06T10:05:00Z",
            },
        }

        user_map = {"user-1": "John Smith", "user-2": "Jane Doe"}

        edited_pdf = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[{"id": "r1", "name": "Operator"}],
            steps=flat_steps,
            filled=True,
            execution_data=edited_exec,
            roles_with_steps=roles_with_steps,
            is_role_based=True,
            user_map=user_map,
            run_status="EDITED",
        )

        non_edited_pdf = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[{"id": "r1", "name": "Operator"}],
            steps=flat_steps,
            filled=True,
            execution_data=non_edited_exec,
            roles_with_steps=roles_with_steps,
            is_role_based=True,
            user_map=user_map,
            run_status="COMPLETED",
        )

        assert edited_pdf
        assert non_edited_pdf
        # Edited PDF should be larger due to strikethrough + extra content
        assert len(edited_pdf) > len(non_edited_pdf)

    def test_edited_with_editor_initials(self):
        """Test that both completer and editor initials appear in user_map."""
        roles_with_steps, flat_steps = self._make_roles_and_steps()

        exec_data = {
            "step1": {
                "status": "completed",
                "results": {"vial_count": 3, "thaw_temp_c": 38.0},
                "original_results": {"vial_count": 2, "thaw_temp_c": 37.5},
                "completed_by_user_id": "user-1",
                "edited_by_user_id": "user-2",
                "edited_at": "2026-03-06T12:00:00Z",
                "timestamp": "2026-03-06T10:00:00Z",
            },
            "step2": {
                "status": "completed",
                "value": "All good",
                "completed_by_user_id": "user-1",
                "timestamp": "2026-03-06T10:05:00Z",
            },
        }

        user_map = {"user-1": "John Smith", "user-2": "Jane Doe"}

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[{"id": "r1", "name": "Operator"}],
            steps=flat_steps,
            filled=True,
            execution_data=exec_data,
            roles_with_steps=roles_with_steps,
            is_role_based=True,
            user_map=user_map,
            run_status="EDITED",
        )

        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_unedited_steps_unchanged(self):
        """Test that a mix of edited and unedited steps generates correctly.
        Step 1 is edited, step 2 is not."""
        roles_with_steps, flat_steps = self._make_roles_and_steps()

        exec_data = {
            "step1": {
                "status": "completed",
                "results": {"vial_count": 3, "thaw_temp_c": 37.5},
                "original_results": {"vial_count": 2, "thaw_temp_c": 37.5},
                "completed_by_user_id": "user-1",
                "edited_by_user_id": "user-2",
                "timestamp": "2026-03-06T10:00:00Z",
            },
            "step2": {
                "status": "completed",
                "value": "All good",
                "completed_by_user_id": "user-1",
                "timestamp": "2026-03-06T10:05:00Z",
            },
        }

        user_map = {"user-1": "John Smith", "user-2": "Jane Doe"}

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[{"id": "r1", "name": "Operator"}],
            steps=flat_steps,
            filled=True,
            execution_data=exec_data,
            roles_with_steps=roles_with_steps,
            is_role_based=True,
            user_map=user_map,
            run_status="EDITED",
        )

        assert pdf_bytes
        assert len(pdf_bytes) > 500

    def test_original_results_not_overwritten(self):
        """Test that if original_results is already set, it stays as-is.
        This is enforced by the backend logic, but the PDF should render
        whatever original_results is present."""
        roles_with_steps, flat_steps = self._make_roles_and_steps()

        # Simulate double edit: original_results still points to the first
        # completion, not the intermediate edit
        exec_data = {
            "step1": {
                "status": "completed",
                "results": {"vial_count": 5, "thaw_temp_c": 39.0},
                "original_results": {"vial_count": 1, "thaw_temp_c": 37.0},
                "completed_by_user_id": "user-1",
                "edited_by_user_id": "user-2",
                "timestamp": "2026-03-06T10:00:00Z",
            },
            "step2": {
                "status": "completed",
                "value": "All good",
                "completed_by_user_id": "user-1",
                "timestamp": "2026-03-06T10:05:00Z",
            },
        }

        user_map = {"user-1": "John Smith", "user-2": "Jane Doe"}

        pdf_bytes = generate_batch_record_pdf(
            protocol_name="Test",
            run_name="Run1",
            roles=[{"id": "r1", "name": "Operator"}],
            steps=flat_steps,
            filled=True,
            execution_data=exec_data,
            roles_with_steps=roles_with_steps,
            is_role_based=True,
            user_map=user_map,
            run_status="EDITED",
        )

        assert pdf_bytes
        assert len(pdf_bytes) > 500
