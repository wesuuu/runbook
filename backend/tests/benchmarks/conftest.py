"""Shared fixtures for protocol import benchmarks."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.iam import Organization, SubscriptionTier

BENCHMARKS_DIR = Path(__file__).parent
INPUT_TO_PROTOCOL_DIR = BENCHMARKS_DIR / "input-to-protocol"


def discover_fixtures(
    subdir: str = "input-to-protocol",
    marker_file: str = "expected.json",
) -> list[Path]:
    """Find all fixture directories under `subdir` that contain `marker_file`.

    Defaults preserve the F-0058 call site: `discover_fixtures()` with no
    args returns input-to-protocol dirs with `expected.json`.
    """
    root = BENCHMARKS_DIR / subdir
    if not root.exists():
        return []
    return sorted(
        d for d in root.iterdir() if d.is_dir() and (d / marker_file).exists()
    )


def load_json(fixture_dir: Path, filename: str) -> dict:
    """Load a JSON file from a fixture directory."""
    with open(fixture_dir / filename) as f:
        return json.load(f)


def load_expected(fixture_dir: Path) -> dict:
    """Backwards-compatible wrapper: load expected.json (F-0058 convention)."""
    return load_json(fixture_dir, "expected.json")


def find_document(fixture_dir: Path) -> Path:
    """Find the document file (PDF or PNG) in a fixture directory."""
    for ext in ("pdf", "png", "jpg", "jpeg", "tiff", "docx"):
        candidate = fixture_dir / f"document.{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No document file found in {fixture_dir}")


def get_mime_type(doc_path: Path) -> str:
    """Get MIME type from file extension."""
    mime, _ = mimetypes.guess_type(str(doc_path))
    if mime:
        return mime
    ext_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return ext_map.get(doc_path.suffix.lower(), "application/octet-stream")


def make_mock_unit_op(
    name: str,
    category: str = "General",
    param_schema: dict | None = None,
    description: str = "",
) -> MagicMock:
    """Create a mock UnitOpDefinition matching the DB model interface."""
    op = MagicMock()
    op.id = uuid4()
    op.name = name
    op.category = category
    op.description = description or f"Description for {name}"
    op.param_schema = param_schema or {}
    return op


def build_seed_catalog() -> list[MagicMock]:
    """Build mock UnitOpDefinition list matching the seed data catalog.

    This mirrors backend/app/db/seed.py so the benchmark uses the same
    catalog the LLM will see in production.
    """
    return [
        make_mock_unit_op(
            "Buffer Preparation",
            "Media Prep",
            {
                "type": "object",
                "properties": {
                    "buffer_name": {"type": "string"},
                    "volume_L": {"type": "number"},
                    "pH_target": {"type": "number"},
                    "pH_tolerance": {"type": "number"},
                    "pH_agent": {"type": "string"},
                },
            },
            "Prepare buffer solution",
        ),
        make_mock_unit_op(
            "Media Preparation",
            "Media Prep",
            {
                "type": "object",
                "properties": {
                    "media_name": {"type": "string"},
                    "volume_L": {"type": "number"},
                    "basal_medium": {"type": "string"},
                    "supplements": {"type": "string"},
                },
            },
            "Prepare cell culture media",
        ),
        make_mock_unit_op(
            "Seeding",
            "Cell Culture",
            {
                "type": "object",
                "properties": {
                    "cell_density": {"type": "number"},
                    "vessel_type": {"type": "string"},
                    "volume_mL": {"type": "number"},
                },
            },
            "Seed cells into vessel",
        ),
        make_mock_unit_op(
            "Incubation",
            "Cell Culture",
            {
                "type": "object",
                "properties": {
                    "temperature_C": {"type": "number"},
                    "CO2_percent": {"type": "number"},
                    "duration_hours": {"type": "number"},
                    "rpm": {"type": "number"},
                },
            },
            "Incubate cells",
        ),
        make_mock_unit_op(
            "Cell Counting",
            "Cell Culture",
            {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "dilution_factor": {"type": "number"},
                },
            },
            "Count cells",
        ),
        make_mock_unit_op(
            "Transfection",
            "Cell Culture",
            {
                "type": "object",
                "properties": {
                    "reagent": {"type": "string"},
                    "dna_amount_ug": {"type": "number"},
                    "method": {"type": "string"},
                },
            },
            "Transfect cells",
        ),
        make_mock_unit_op(
            "Harvest",
            "Cell Culture",
            {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "centrifuge_rcf": {"type": "number"},
                },
            },
            "Harvest cells",
        ),
        make_mock_unit_op(
            "Centrifugation",
            "Purification",
            {
                "type": "object",
                "properties": {
                    "rcf_g": {"type": "number"},
                    "duration_min": {"type": "number"},
                    "temperature_C": {"type": "number"},
                },
            },
            "Centrifuge sample",
        ),
        make_mock_unit_op(
            "Filtration",
            "Purification",
            {
                "type": "object",
                "properties": {
                    "filter_size_um": {"type": "number"},
                    "filter_type": {"type": "string"},
                    "volume_L": {"type": "number"},
                },
            },
            "Filter solution",
        ),
        make_mock_unit_op(
            "Chromatography",
            "Purification",
            {
                "type": "object",
                "properties": {
                    "column_type": {"type": "string"},
                    "resin": {"type": "string"},
                    "flow_rate_mL_min": {"type": "number"},
                },
            },
            "Chromatographic purification",
        ),
        make_mock_unit_op(
            "pH Adjustment",
            "Reaction",
            {
                "type": "object",
                "properties": {
                    "target_pH": {"type": "number"},
                    "acid_or_base": {"type": "string"},
                },
            },
            "Adjust solution pH",
        ),
        make_mock_unit_op(
            "Mixing",
            "Reaction",
            {
                "type": "object",
                "properties": {
                    "speed_rpm": {"type": "number"},
                    "duration_min": {"type": "number"},
                    "temperature_C": {"type": "number"},
                },
            },
            "Mix solution",
        ),
        make_mock_unit_op(
            "Sample Collection",
            "Analytics",
            {
                "type": "object",
                "properties": {
                    "volume_mL": {"type": "number"},
                    "container_type": {"type": "string"},
                    "storage_temp_C": {"type": "number"},
                },
            },
            "Collect sample",
        ),
        make_mock_unit_op(
            "Assay",
            "Analytics",
            {
                "type": "object",
                "properties": {
                    "assay_type": {"type": "string"},
                    "method": {"type": "string"},
                },
            },
            "Run assay",
        ),
        make_mock_unit_op(
            "Fill",
            "Fill/Finish",
            {
                "type": "object",
                "properties": {
                    "fill_volume_mL": {"type": "number"},
                    "container_type": {"type": "string"},
                    "fill_speed": {"type": "string"},
                },
            },
            "Fill containers",
        ),
        make_mock_unit_op(
            "Lyophilization",
            "Fill/Finish",
            {
                "type": "object",
                "properties": {
                    "shelf_temp_C": {"type": "number"},
                    "chamber_pressure_mTorr": {"type": "number"},
                    "duration_hours": {"type": "number"},
                },
            },
            "Lyophilize product",
        ),
        make_mock_unit_op(
            "Visual Inspection",
            "Quality Control",
            {
                "type": "object",
                "properties": {
                    "inspection_type": {"type": "string"},
                    "acceptance_criteria": {"type": "string"},
                },
            },
            "Visual inspection",
        ),
    ]


@pytest.fixture
def unit_ops_catalog() -> list[MagicMock]:
    """Provide the seed unit op catalog as mock objects."""
    return build_seed_catalog()


@pytest_asyncio.fixture
async def pro_org(db_session) -> Organization:
    """Pro-tier org for benchmarks so AI provider defaults resolve."""
    org = Organization(
        name="Benchmark Org",
        subscription_tier=SubscriptionTier.PRO.value,
    )
    db_session.add(org)
    await db_session.flush()
    return org


# -- Shared score accumulators + pytest summary hook --

all_benchmark_scores: list = []
"""Shared list that test files append BenchmarkScores to.
The pytest_terminal_summary hook prints aggregate results."""

all_batch_record_run_scores: list = []
"""Shared list that batch record run benchmarks append scores to."""


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print aggregate benchmark summary at end of run."""
    from tests.benchmarks.batch_record_scoring import print_run_summary
    from tests.benchmarks.scoring import print_summary_table

    if all_benchmark_scores:
        print_summary_table(all_benchmark_scores)
    if all_batch_record_run_scores:
        print_run_summary(all_batch_record_run_scores)
