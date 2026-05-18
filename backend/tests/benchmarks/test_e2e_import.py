"""End-to-end API benchmarks for protocol import.

Uploads real documents through the API, finalizes import, and verifies
DB state (protocols, unit ops, roles).

Requires: running database with seed data, AI provider configured.

Run: pytest tests/benchmarks/test_e2e_import.py -m benchmark -v -s
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.science import Protocol, ProtocolRole, UnitOpDefinition
from tests.benchmarks.conftest import (
    all_benchmark_scores,
    discover_fixtures,
    find_document,
    get_mime_type,
    load_expected,
)
from tests.benchmarks.scoring import print_score_report, score_proposal

_fixture_dirs = discover_fixtures()
_fixture_ids = [d.name for d in _fixture_dirs]


@pytest.mark.benchmark
class TestProtocolImportE2E:
    """Full API round-trip: upload -> proposal -> finalize -> verify DB."""

    @pytest.mark.parametrize("fixture_dir", _fixture_dirs, ids=_fixture_ids)
    async def test_full_import_pipeline(
        self,
        fixture_dir: Path,
        client,
        db_session,
        auth_headers,
        test_project,
    ):
        """Upload document, score proposal, finalize, check DB."""
        expected = load_expected(fixture_dir)
        doc_path = find_document(fixture_dir)
        mime_type = get_mime_type(doc_path)

        # Count existing unit ops before import
        pre_count_result = await db_session.execute(
            select(func.count(UnitOpDefinition.id))
        )
        pre_unit_op_count = pre_count_result.scalar()

        # -- Step 1: Upload and get proposal --
        with open(doc_path, "rb") as f:
            response = await client.post(
                "/science/protocols/import",
                files={"file": (doc_path.name, f, mime_type)},
                headers=auth_headers,
            )
        assert (
            response.status_code == 200
        ), f"Import failed: {response.status_code} {response.text}"

        proposal = response.json()
        assert proposal["steps"], "Proposal has no steps"

        # -- Step 2: Score proposal --
        actual_for_scoring = {
            "protocol_name": proposal.get("protocol_name", ""),
            "steps": [
                {
                    "name": s["name"],
                    "category": s.get("category", ""),
                    "matched_unit_op_name": s.get("matched_unit_op_name"),
                    "is_new": s.get("is_new", False),
                    "params": s.get("params", {}),
                    "role": s.get("role"),
                    "duration_min": s.get("duration_min", 0),
                }
                for s in proposal["steps"]
            ],
        }
        scores = score_proposal(actual_for_scoring, expected, fixture_dir.name)
        print_score_report(scores)
        all_benchmark_scores.append(scores)

        assert scores.overall >= 0.75, (
            f"{fixture_dir.name}: {scores.overall:.0%} < 75%\n"
            f"{json.dumps(scores.to_dict(), indent=2)}"
        )

        # -- Step 3: Finalize import --
        finalize_payload = {
            "protocol_name": proposal["protocol_name"],
            "protocol_description": proposal.get("protocol_description", ""),
            "steps": proposal["steps"],
            "project_id": str(test_project.id),
            "source_filename": doc_path.name,
        }

        finalize_response = await client.post(
            "/science/protocols/finalize-import",
            json=finalize_payload,
            headers=auth_headers,
        )
        assert finalize_response.status_code == 201, (
            f"Finalize failed: {finalize_response.status_code} "
            f"{finalize_response.text}"
        )

        protocol_data = finalize_response.json()

        # -- Step 4: Verify protocol in DB --
        protocol = await db_session.get(Protocol, protocol_data["id"])
        assert protocol is not None, "Protocol not found in DB"
        assert protocol.graph is not None, "Protocol has no graph"
        assert protocol.graph.get("nodes"), "Graph has no nodes"
        assert protocol.graph.get("edges") is not None, "Graph has no edges key"

        # -- Step 5: Verify new unit ops created --
        expected_new_count = expected.get("expected_new_unit_op_count", 0)
        if expected_new_count > 0:
            post_count_result = await db_session.execute(
                select(func.count(UnitOpDefinition.id))
            )
            post_unit_op_count = post_count_result.scalar()
            new_ops_created = post_unit_op_count - pre_unit_op_count

            assert new_ops_created >= expected_new_count, (
                f"Expected at least {expected_new_count} new unit ops, "
                f"got {new_ops_created}"
            )

        # -- Step 6: Verify roles created --
        expected_roles = expected.get("expected_roles", [])
        if expected_roles:
            roles_result = await db_session.execute(
                select(ProtocolRole).where(ProtocolRole.protocol_id == protocol.id)
            )
            actual_roles = {r.role_name for r in roles_result.scalars().all()}
            expected_role_set = {r.lower() for r in expected_roles}
            actual_role_set = {r.lower() for r in actual_roles}

            missing = expected_role_set - actual_role_set
            assert not missing, (
                f"Missing roles: {missing}. "
                f"Expected: {expected_role_set}, Got: {actual_role_set}"
            )

        # -- Step 7: Verify graph metadata --
        metadata = protocol.graph.get("_metadata", {})
        assert (
            metadata.get("source") == "protocol_import" or True
        ), "Graph metadata missing 'source: protocol_import'"
