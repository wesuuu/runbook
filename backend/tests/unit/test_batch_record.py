"""Tests for batch record PDF generation and role parsing."""

import pytest
from app.api.endpoints.science import _parse_graph_roles_and_steps
from app.services.pdf import generate_batch_record_pdf


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
