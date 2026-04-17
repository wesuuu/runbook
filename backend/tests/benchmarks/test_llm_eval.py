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
from tests.benchmarks.conftest import (
    all_benchmark_scores,
    build_seed_catalog,
    discover_fixtures,
    find_document,
    get_mime_type,
    load_expected,
)
from tests.benchmarks.scoring import (
    print_score_report,
    score_proposal,
)

# Collect all fixture dirs at module level for parametrize
_fixture_dirs = discover_fixtures()
_fixture_ids = [d.name for d in _fixture_dirs]


@pytest.mark.benchmark
class TestProtocolImportAccuracy:
    """Feed real documents through the LLM import pipeline and score results."""

    @pytest_asyncio.fixture
    async def pro_org(self, db_session) -> Organization:
        """Create a Pro-tier org so AI provider defaults resolve."""
        org = Organization(
            name="Benchmark Org",
            subscription_tier=SubscriptionTier.PRO.value,
        )
        db_session.add(org)
        await db_session.flush()
        return org

    @pytest.mark.parametrize("fixture_dir", _fixture_dirs, ids=_fixture_ids)
    async def test_import_accuracy(self, fixture_dir: Path, db_session, pro_org):
        """Run a single fixture through extract -> parse -> build_proposal."""
        from app.services.protocol_importer import (
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
