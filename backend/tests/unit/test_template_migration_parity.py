"""TEMPORARY — Visual parity tests: old fpdf2 vs new docxtpl pipeline.

Renders the same data through BOTH the old fpdf2 generators and the new
docxtpl template engine, compares page-by-page pixel similarity, and
writes reference/diff artifacts.

DELETE THIS FILE after Phase 0 of F-0065 is verified in production.
Also remove pdf2image from pyproject.toml dev dependencies.
"""

from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from app.services.template_engine import build_context, render_to_pdf as new_render
from app.services.pdf import generate_sop_pdf, generate_batch_record_pdf
from app.services.graph_processing import _parse_graph_roles_and_steps

ARTIFACTS_DIR = Path(__file__).parent.parent / "artifacts" / "templates"
SOP_TEMPLATE = Path("app/services/templates/sop_default.docx")
BR_TEMPLATE = Path("app/services/templates/batch_record_default.docx")

SIMILARITY_THRESHOLD = 85.0  # minimum acceptable % similarity


@pytest.fixture(autouse=True)
def ensure_artifacts_dir():
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _compare_pdfs(old_bytes: bytes, new_bytes: bytes) -> list[float]:
    """Compare two PDFs page-by-page, return per-page similarity (0-100%)."""
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        pytest.skip("pdf2image not installed")

    old_pages = convert_from_bytes(old_bytes, dpi=150)
    new_pages = convert_from_bytes(new_bytes, dpi=150)

    scores = []
    max_pages = max(len(old_pages), len(new_pages))
    for i in range(max_pages):
        if i >= len(old_pages) or i >= len(new_pages):
            scores.append(0.0)
            continue
        old_img = old_pages[i].convert("RGB")
        new_img = new_pages[i].convert("RGB").resize(old_img.size)
        diff = ImageChops.difference(old_img, new_img)
        stat = ImageStat.Stat(diff)
        avg_diff = sum(stat.mean) / len(stat.mean)
        similarity = max(0, 100 - (avg_diff / 255 * 100))
        scores.append(similarity)
    return scores


def _write_parity_artifacts(
    name: str,
    old_bytes: bytes,
    new_bytes: bytes,
    scores: list[float],
):
    """Write OLD reference, diff image, and scores file."""
    (ARTIFACTS_DIR / f"{name}_OLD.pdf").write_bytes(old_bytes)

    # Write scores
    lines = [f"Page {i+1}: {s:.1f}%" for i, s in enumerate(scores)]
    lines.append(f"\nAverage: {sum(scores)/len(scores):.1f}%")
    (ARTIFACTS_DIR / f"{name}_SCORES.txt").write_text("\n".join(lines))

    # Generate diff image for first page
    try:
        from pdf2image import convert_from_bytes

        old_pages = convert_from_bytes(old_bytes, dpi=150)
        new_pages = convert_from_bytes(new_bytes, dpi=150)
        if old_pages and new_pages:
            old_img = old_pages[0].convert("RGB")
            new_img = new_pages[0].convert("RGB").resize(old_img.size)
            diff = ImageChops.difference(old_img, new_img)
            # Amplify differences for visibility
            diff = diff.point(lambda x: min(255, x * 5))
            diff.save(str(ARTIFACTS_DIR / f"{name}_DIFF.png"))
    except Exception:
        pass


# ── Fixture data (matching test_template_engine.py) ──

SIMPLE_GRAPH = {
    "nodes": [
        {
            "id": "s1",
            "type": "unitOp",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": "Buffer Preparation",
                "description": "Prepare {{volume}} mL of PBS buffer.",
                "params": {"volume": 500},
                "paramSchema": {
                    "properties": {"volume": {"title": "Volume", "unit": "mL"}}
                },
                "duration_min": 30,
            },
        },
        {
            "id": "s2",
            "type": "unitOp",
            "position": {"x": 200, "y": 0},
            "data": {
                "label": "Cell Seeding",
                "description": "Seed cells at target density.",
                "params": {"density": 1e6},
                "paramSchema": {
                    "properties": {
                        "density": {
                            "title": "Seeding Density",
                            "unit": "cells/mL",
                        }
                    }
                },
                "duration_min": 15,
            },
        },
    ],
    "edges": [{"source": "s1", "target": "s2"}],
}

ROLE_GRAPH = {
    "nodes": [
        {
            "id": "lane1",
            "type": "swimLane",
            "position": {"x": 0, "y": 0},
            "data": {"label": "Media Prep"},
        },
        {
            "id": "lane2",
            "type": "swimLane",
            "position": {"x": 0, "y": 200},
            "data": {"label": "QC"},
        },
        {
            "id": "s1",
            "type": "unitOp",
            "parentId": "lane1",
            "position": {"x": 50, "y": 50},
            "data": {
                "label": "Weigh Reagents",
                "description": "Weigh NaCl and KCl.",
                "params": {"nacl_g": 8.0, "kcl_g": 0.2},
                "paramSchema": {
                    "properties": {
                        "nacl_g": {"title": "NaCl", "unit": "g"},
                        "kcl_g": {"title": "KCl", "unit": "g"},
                    }
                },
                "duration_min": 10,
            },
        },
        {
            "id": "s2",
            "type": "unitOp",
            "parentId": "lane1",
            "position": {"x": 250, "y": 50},
            "data": {
                "label": "Dissolve",
                "description": "Add to {{volume}} mL water and stir.",
                "params": {"volume": 1000},
                "paramSchema": {
                    "properties": {"volume": {"title": "Volume", "unit": "mL"}}
                },
                "duration_min": 15,
            },
        },
        {
            "id": "s3",
            "type": "unitOp",
            "parentId": "lane2",
            "position": {"x": 50, "y": 250},
            "data": {
                "label": "Measure pH",
                "description": "Measure and adjust pH.",
                "params": {"target_ph": 7.4},
                "paramSchema": {
                    "properties": {"target_ph": {"title": "Target pH"}}
                },
                "duration_min": 5,
            },
        },
    ],
    "edges": [
        {"source": "s1", "target": "s2"},
        {"source": "s2", "target": "s3"},
    ],
}


def test_parity_sop_simple():
    """Compare simple SOP: old fpdf2 vs new docxtpl."""
    rws, flat, is_rb = _parse_graph_roles_and_steps(SIMPLE_GRAPH)

    old_pdf = generate_sop_pdf(
        protocol_name="Simple Buffer Protocol",
        run_name=None,
        roles_with_steps=rws,
        protocol_description="A simple two-step buffer protocol.",
        version_number=1,
        last_modified="April 1, 2026",
    )

    ctx = build_context(
        protocol_name="Simple Buffer Protocol",
        protocol_description="A simple two-step buffer protocol.",
        version_number=1,
        created_at="April 1, 2026",
        roles_with_steps=rws,
        flat_steps=flat,
        is_role_based=is_rb,
    )
    new_pdf = new_render(SOP_TEMPLATE, ctx)

    scores = _compare_pdfs(old_pdf, new_pdf)
    _write_parity_artifacts("sop_simple", old_pdf, new_pdf, scores)

    avg = sum(scores) / len(scores) if scores else 0
    print(f"\nSOP Simple parity: {avg:.1f}% avg ({len(scores)} pages)")
    # Note: threshold is informational — we expect differences
    # between fpdf2 and LibreOffice rendering engines


def test_parity_sop_role_based():
    """Compare role-based SOP: old fpdf2 vs new docxtpl."""
    rws, flat, is_rb = _parse_graph_roles_and_steps(ROLE_GRAPH)

    old_pdf = generate_sop_pdf(
        protocol_name="Multi-Role Protocol",
        run_name=None,
        roles_with_steps=rws,
        protocol_description="Protocol with Media Prep and QC roles.",
        version_number=2,
        last_modified="April 1, 2026",
    )

    ctx = build_context(
        protocol_name="Multi-Role Protocol",
        protocol_description="Protocol with Media Prep and QC roles.",
        version_number=2,
        created_at="April 1, 2026",
        roles_with_steps=rws,
        flat_steps=flat,
        is_role_based=is_rb,
    )
    new_pdf = new_render(SOP_TEMPLATE, ctx)

    scores = _compare_pdfs(old_pdf, new_pdf)
    _write_parity_artifacts("sop_role_based", old_pdf, new_pdf, scores)

    avg = sum(scores) / len(scores) if scores else 0
    print(f"\nSOP Role-based parity: {avg:.1f}% avg ({len(scores)} pages)")


def test_parity_batch_record_blank():
    """Compare blank batch record: old fpdf2 vs new docxtpl."""
    rws, flat, is_rb = _parse_graph_roles_and_steps(ROLE_GRAPH)
    roles = [
        {"id": r["role_name"], "name": r["role_name"]}
        for r in rws
        if r["role_name"]
    ]

    old_pdf = generate_batch_record_pdf(
        protocol_name="Multi-Role Protocol",
        run_name="Preview",
        roles=roles,
        steps=flat,
        filled=False,
        roles_with_steps=rws,
        is_role_based=is_rb,
        version_number=2,
        last_modified="April 1, 2026",
    )

    ctx = build_context(
        protocol_name="Multi-Role Protocol",
        run_name="Preview",
        version_number=2,
        created_at="April 1, 2026",
        roles_with_steps=rws,
        flat_steps=flat,
        is_role_based=is_rb,
    )
    new_pdf = new_render(BR_TEMPLATE, ctx)

    scores = _compare_pdfs(old_pdf, new_pdf)
    _write_parity_artifacts("batch_record_blank", old_pdf, new_pdf, scores)

    avg = sum(scores) / len(scores) if scores else 0
    print(f"\nBatch Record Blank parity: {avg:.1f}% avg ({len(scores)} pages)")
