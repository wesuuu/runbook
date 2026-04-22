"""LLM accuracy benchmarks for protocol import.

Runs against a real AI provider. Excluded from normal test suite via
the 'benchmark' marker.

Run: pytest tests/benchmarks/test_llm_eval.py -m benchmark -v -s
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from app.models.iam import Organization, SubscriptionTier
from app.services.batch.batch_record_extractor import (
    extract_batch_record_data,
    extract_batch_record_pages,
    map_steps_to_protocol,
    map_values_to_execution_data,
)
from tests.benchmarks.batch_record_scoring import (
    build_auto_finalized_mappings,
    print_run_report,
    score_run,
)
from tests.benchmarks.conftest import (
    all_batch_record_run_scores,
    all_benchmark_scores,
    build_seed_catalog,
    discover_fixtures,
    find_document,
    get_mime_type,
    load_expected,
    load_json,
)
from tests.benchmarks.scoring import (
    print_score_report,
    score_proposal,
)

# Collect all fixture dirs at module level for parametrize
_fixture_dirs = discover_fixtures()
_fixture_ids = [d.name for d in _fixture_dirs]

_br_fixture_dirs = discover_fixtures(
    subdir="document-to-run",
    marker_file="expected_run.json",
)
_br_fixture_ids = [d.name for d in _br_fixture_dirs]


@pytest.mark.benchmark
class TestProtocolImportAccuracy:
    """Feed real documents through the LLM import pipeline and score results."""

    @pytest.mark.parametrize("fixture_dir", _fixture_dirs, ids=_fixture_ids)
    async def test_import_accuracy(self, fixture_dir: Path, db_session, pro_org):
        """Run a single fixture through extract -> parse -> build_proposal."""
        from app.services.protocols.protocol_importer import (
            build_proposal,
            extract_text,
            parse_protocol_text,
        )

        # Load expected output
        expected = load_expected(fixture_dir)

        # Find document and determine MIME type
        doc_path = find_document(fixture_dir)
        mime_type = get_mime_type(doc_path)

        # Build catalog (mock objects matching seed data)
        catalog = build_seed_catalog()

        # Step 1: Extract text from document
        text = await extract_text(doc_path, mime_type, db_session, org_id=pro_org.id)
        assert text and text.strip(), f"No text extracted from {doc_path.name}"

        # Step 2: Parse with real LLM
        parsed = await parse_protocol_text(
            text, catalog, db_session, org_id=pro_org.id
        )
        assert parsed.steps, "LLM returned no steps"

        # Step 3: Build proposal (deterministic matching)
        proposal = build_proposal(
            parsed, catalog, doc_path.name, text
        )

        # Convert proposal to dict for scoring
        actual = {
            "protocol_name": proposal.protocol_name,
            "steps": [
                {
                    "name": s.name,
                    "category": s.category,
                    "matched_unit_op_name": s.matched_unit_op_name,
                    "is_new": s.is_new,
                    "params": s.params,
                    "role": s.role,
                    "duration_min": s.duration_min,
                }
                for s in proposal.steps
            ],
        }

        # Score
        scores = score_proposal(actual, expected, fixture_dir.name)
        print_score_report(scores)
        all_benchmark_scores.append(scores)

        # Assert with full breakdown on failure
        assert scores.overall >= 0.75, (
            f"{fixture_dir.name}: {scores.overall:.0%} < 75%\n"
            f"{json.dumps(scores.to_dict(), indent=2)}"
        )


@pytest.mark.benchmark
class TestBatchRecordAccuracy:
    """Run the full batch-record-import pipeline and score the output Run."""

    @pytest.mark.parametrize(
        "fixture_dir", _br_fixture_dirs, ids=_br_fixture_ids,
    )
    async def test_batch_record_to_run(
        self, fixture_dir: Path, db_session, pro_org,
    ):
        # 1. Extract
        doc = find_document(fixture_dir)
        mime = get_mime_type(doc)
        text, page_images = await extract_batch_record_pages(
            doc, mime, db_session, org_id=pro_org.id,
        )
        extraction = await extract_batch_record_data(
            text, page_images, db_session, org_id=pro_org.id,
        )

        # 2. Map against target protocol
        protocol = load_json(fixture_dir, "protocol.json")
        mappings = await map_steps_to_protocol(
            extraction, protocol, db_session, org_id=pro_org.id,
        )

        # 3. Simulate user-finalize: auto-accept all extracted values + pass through aux fields
        finalized = build_auto_finalized_mappings(extraction, mappings)
        execution_data = map_values_to_execution_data(
            finalized, protocol, user_id=pro_org.id,
        )

        # 4. Score against expected_run.json
        expected_run = load_json(fixture_dir, "expected_run.json")
        run_metadata = {
            "run_name": extraction.batch_id or extraction.document_title or "",
        }
        scores = score_run(
            execution_data, run_metadata, expected_run, protocol, fixture_dir.name,
        )
        print_run_report(scores)
        all_batch_record_run_scores.append(scores)

        assert scores.overall >= 0.75, (
            f"{fixture_dir.name}: {scores.overall:.0%} < 75%\n"
            f"{json.dumps(scores.to_dict(), indent=2, default=str)}"
        )
