#!/usr/bin/env python3
"""Generate benchmark fixture documents (PDFs and PNGs).

Run from backend/: python tests/benchmarks/input-to-protocol/generate_fixtures.py

Idempotent — regenerates all documents from scratch.
To add a new fixture: add a generate_NN_*() function and call it from main().
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

FIXTURES_DIR = Path(__file__).parent


def _sop_header_style() -> ParagraphStyle:
    styles = getSampleStyleSheet()
    return ParagraphStyle(
        "SOPHeader",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=12,
    )


def _sop_body_style() -> ParagraphStyle:
    styles = getSampleStyleSheet()
    return ParagraphStyle(
        "SOPBody",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        spaceAfter=6,
    )


def _sop_section_style() -> ParagraphStyle:
    styles = getSampleStyleSheet()
    return ParagraphStyle(
        "SOPSection",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=12,
        spaceAfter=6,
    )


def _build_pdf(output_path: Path, title: str, doc_number: str, elements_fn):
    """Build a PDF with standard SOP header and custom body elements."""
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    header = _sop_header_style()
    body = _sop_body_style()
    section = _sop_section_style()

    elements = []

    # Standard SOP header table
    header_data = [
        ["STANDARD OPERATING PROCEDURE", ""],
        [f"Title: {title}", f"Doc #: {doc_number}"],
        ["Effective: 2026-01-15", "Rev: 1.0"],
    ]
    header_table = Table(header_data, colWidths=[4 * inch, 3 * inch])
    header_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.95)),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("SPAN", (0, 0), (1, 0)),
                ("ALIGN", (0, 0), (1, 0), "CENTER"),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Add custom body elements
    elements_fn(elements, header, body, section)

    doc.build(elements)


def _build_png(output_path: Path, lines: list[str], degrade: bool = False):
    """Render text lines to a PNG image.

    Args:
        output_path: Where to save.
        lines: Text lines to render.
        degrade: If True, simulate low-quality scan (noise, rotation).
    """
    width, height = 850, max(1100, len(lines) * 28 + 200)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_bold = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16
        )
    except OSError:
        font = ImageFont.load_default()
        font_bold = font

    y = 40
    for line in lines:
        if line.startswith("# "):
            draw.text((40, y), line[2:], fill="black", font=font_bold)
            y += 30
        elif line.startswith("---"):
            draw.line([(40, y + 5), (width - 40, y + 5)], fill="grey", width=1)
            y += 15
        else:
            draw.text((40, y), line, fill="black", font=font)
            y += 22

    if degrade:
        import random

        # Add noise
        pixels = img.load()
        for _ in range(width * height // 20):
            x = random.randint(0, width - 1)
            y_pos = random.randint(0, height - 1)
            gray = random.randint(180, 230)
            pixels[x, y_pos] = (gray, gray, gray)

        # Slight rotation
        img = img.rotate(1.5, fillcolor="white", expand=False)

        # Reduce resolution then scale back up (blur effect)
        small = img.resize((width // 3, height // 3), Image.BILINEAR)
        img = small.resize((width, height), Image.BILINEAR)

    img.save(output_path)


# ── Fixture generators ────────────────────────────────────────────


def generate_01_buffer_prep():
    """PDF: Simple buffer prep, 4 steps, all catalog matches."""
    out_dir = FIXTURES_DIR / "01-buffer-prep"
    out_dir.mkdir(exist_ok=True)

    def body(elements, header, body, section):
        elements.append(Paragraph("1. Purpose", section))
        elements.append(
            Paragraph(
                "This SOP describes the preparation of 10L Tris-HCl buffer (50mM, pH 7.4) "
                "for use in downstream purification processes.",
                body,
            )
        )
        elements.append(Paragraph("2. Responsible Personnel", section))
        elements.append(Paragraph("Role: Operator", body))
        elements.append(Paragraph("3. Procedure", section))
        elements.append(
            Paragraph(
                "<b>Step 1: Buffer Preparation</b><br/>"
                "Weigh 60.57g Tris base and dissolve in 8L purified water in a 10L carboy. "
                "Stir at 200 RPM until fully dissolved (approximately 15 minutes). "
                "Target volume: 10L. Target concentration: 50mM.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 2: pH Adjustment</b><br/>"
                "Using a calibrated pH meter, adjust pH to 7.4 (&plusmn; 0.05) by slow addition "
                "of concentrated HCl (6N). Mix thoroughly between additions. "
                "Record final pH reading.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 3: Sterile Filtration</b><br/>"
                "Filter the entire 10L volume through a 0.22&mu;m PES membrane filter "
                "into a sterile carboy. Use a peristaltic pump at 500 mL/min flow rate. "
                "Perform bubble-point integrity test post-filtration.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 4: QC Sampling</b><br/>"
                "Collect a 50mL sample into a sterile polypropylene tube. "
                "Label with buffer name, lot number, and date. "
                "Store at 2-8&deg;C. Submit for pH verification and bioburden testing.",
                body,
            )
        )

    _build_pdf(
        out_dir / "document.pdf", "Tris-HCl Buffer Preparation", "SOP-BUF-001", body
    )


def generate_02_cell_culture_passage():
    """PDF: Cell passage, 7 steps, 2 new unit ops."""
    out_dir = FIXTURES_DIR / "02-cell-culture-passage"
    out_dir.mkdir(exist_ok=True)

    def body(elements, header, body, section):
        elements.append(Paragraph("1. Purpose", section))
        elements.append(
            Paragraph(
                "Routine passage of adherent CHO-K1 cells for seed train maintenance. "
                "Cells are split 1:4 every 3-4 days when reaching 80-90% confluence.",
                body,
            )
        )
        elements.append(Paragraph("2. Responsible Personnel", section))
        elements.append(Paragraph("Role: Operator", body))
        elements.append(Paragraph("3. Materials", section))

        materials = [
            ["Item", "Specification"],
            ["Complete Growth Medium", "DMEM/F12 + 10% FBS + 1% Pen/Strep"],
            ["PBS", "Dulbecco's PBS without Ca/Mg"],
            ["Trypsin-EDTA", "0.25% Trypsin, 1mM EDTA"],
            ["T-175 Flasks", "Corning, tissue-culture treated"],
        ]
        mat_table = Table(materials, colWidths=[2.5 * inch, 4 * inch])
        mat_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.95)),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                ]
            )
        )
        elements.append(mat_table)
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph("4. Procedure", section))
        elements.append(
            Paragraph(
                "<b>Step 1: Pre-warm Media</b><br/>"
                "Remove complete growth medium from 4&deg;C storage. "
                "Place in 37&deg;C water bath for 20 minutes. "
                "Volume required: 35mL per T-175 flask.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 2: Aspirate Spent Media</b><br/>"
                "Remove flask from incubator. Using a vacuum aspirator, "
                "carefully remove all spent media from the flask. "
                "Tilt flask to collect residual media at the corner.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 3: PBS Wash</b><br/>"
                "Add 10mL PBS to the flask. Gently rock the flask to wash the cell monolayer. "
                "Aspirate the PBS wash. Repeat once for a total of 2 washes.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 4: Trypsinization</b><br/>"
                "Add 5mL 0.25% Trypsin-EDTA to the flask. "
                "Incubate at 37&deg;C for 5 minutes. "
                "Check cell detachment under microscope.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 5: Neutralize and Harvest</b><br/>"
                "Add 10mL complete medium to neutralize trypsin. "
                "Pipette up and down to create single-cell suspension. "
                "Transfer to a 50mL conical tube.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 6: Cell Count</b><br/>"
                "Take 100&mu;L sample. Mix with 100&mu;L Trypan Blue (1:2 dilution). "
                "Load hemocytometer and count using Trypan Blue exclusion method. "
                "Record viable cell density and viability percentage.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 7: Seed New Flasks</b><br/>"
                "Seed new T-175 flasks at 0.5 &times; 10<super>6</super> cells/mL "
                "in 35mL complete medium. "
                "Place in incubator at 37&deg;C, 5% CO2, humidified atmosphere.",
                body,
            )
        )

    _build_pdf(out_dir / "document.pdf", "CHO-K1 Cell Passage", "SOP-CC-012", body)


def generate_03_protein_a_purification():
    """PNG: Protein A purification, 10 steps, 3 new unit ops (scan-style)."""
    out_dir = FIXTURES_DIR / "03-protein-a-purification"
    out_dir.mkdir(exist_ok=True)

    lines = [
        "# Protein A Purification Protocol",
        "# Doc: SOP-PUR-007  Rev 2.1  Effective: 2025-11-01",
        "---",
        "",
        "Responsible: Purification Scientist (steps 1-9), QC Analyst (step 10)",
        "",
        "PROCEDURE:",
        "",
        "1. Column Equilibration",
        "   Equilibrate the MabSelect SuRe Protein A column (CV = 5mL)",
        "   with 5 column volumes of binding buffer (20mM sodium phosphate,",
        "   150mM NaCl, pH 7.2) at 1.0 mL/min flow rate.",
        "   Duration: 25 minutes.",
        "",
        "2. Load Clarified Harvest",
        "   Load the clarified cell culture harvest onto the column at",
        "   0.5 mL/min. Load volume: 50mL (10 CV). Monitor A280 for",
        "   breakthrough. Column type: Protein A.",
        "   Duration: 100 minutes.",
        "",
        "3. Wash",
        "   Wash with 10 CV binding buffer at 1.0 mL/min to remove",
        "   unbound material. Monitor A280 until baseline is reached.",
        "   Duration: 50 minutes.",
        "",
        "4. Elution",
        "   Elute bound protein with 5 CV of elution buffer (100mM",
        "   glycine-HCl, pH 3.0) at 0.5 mL/min. Collect 1mL fractions.",
        "   Pool fractions with A280 > 0.1 AU. Column type: Protein A.",
        "   Duration: 50 minutes.",
        "",
        "5. Neutralize Eluate",
        "   Immediately neutralize pooled eluate to pH 7.0 (+/- 0.2)",
        "   using 1M Tris-HCl pH 9.0. Mix gently by inversion.",
        "   Record final pH. Duration: 10 minutes.",
        "",
        "6. Low pH Viral Inactivation",
        "   Adjust eluate to pH 3.5 using 1M HCl. Hold for 60 minutes",
        "   at room temperature (20-25C). This is a critical process step",
        "   for viral safety. Record pH and hold start/end times.",
        "   Duration: 60 minutes.",
        "",
        "7. Re-neutralize and Filter",
        "   Adjust pH back to 7.0 using 1M Tris base.",
        "   Filter through 0.22um PES membrane. Volume: approx 10mL.",
        "   Duration: 15 minutes.",
        "",
        "8. Diafiltration",
        "   Using a 30kDa TFF cassette, diafilter into formulation buffer",
        "   (10mM histidine, 150mM NaCl, pH 6.0). Perform 5 diavolumes.",
        "   Transmembrane pressure: 15 psi. Flow rate: 5 mL/min.",
        "   Duration: 90 minutes.",
        "",
        "9. Concentration",
        "   Concentrate the diafiltrated pool to target 10 mg/mL using",
        "   the same TFF cassette. Centrifuge any precipitate at 3000xg",
        "   for 10 minutes at 4C. Duration: 30 minutes.",
        "",
        "10. Final QC Sample Collection",
        "    Collect 2mL sample into sterile polypropylene cryovial.",
        "    Store at -80C. Submit for: A280 concentration, SEC-HPLC",
        "    purity, endotoxin (LAL), and sterility.",
        "    Duration: 10 minutes.",
    ]

    _build_png(out_dir / "document.png", lines, degrade=False)


def generate_04_transfection():
    """PDF: Transfection protocol, 6 steps, 1 new unit op."""
    out_dir = FIXTURES_DIR / "04-transfection"
    out_dir.mkdir(exist_ok=True)

    def body(elements, header, body, section):
        elements.append(Paragraph("1. Purpose", section))
        elements.append(
            Paragraph(
                "Transient transfection of HEK293 cells for recombinant protein expression "
                "using Lipofectamine 3000. Target: 6-well plate scale.",
                body,
            )
        )
        elements.append(Paragraph("2. Responsible Personnel", section))
        elements.append(Paragraph("Role: Scientist", body))
        elements.append(Paragraph("3. Procedure", section))
        elements.append(
            Paragraph(
                "<b>Step 1: Seed Cells (Day -1)</b><br/>"
                "Seed HEK293 cells at 0.5 &times; 10<super>6</super> cells/well "
                "in 2mL complete DMEM per well of a 6-well plate. "
                "Incubate overnight at 37&deg;C, 5% CO2. "
                "Cells should be 70-80% confluent at transfection.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 2: Prepare DNA-Lipid Complexes (Day 0)</b><br/>"
                "Per well: dilute 2.5&mu;g plasmid DNA in 125&mu;L Opti-MEM. "
                "In a separate tube, dilute 3.75&mu;L Lipofectamine 3000 in 125&mu;L Opti-MEM. "
                "Add 5&mu;L P3000 reagent to the DNA tube. "
                "Combine DNA and lipid tubes, mix gently. Incubate 15 minutes at room temperature. "
                "DNA:lipid ratio is 1:1.5.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 3: Transfect Cells</b><br/>"
                "Add 250&mu;L DNA-lipid complex dropwise to each well. "
                "Gently rock plate to distribute. "
                "Method: lipofection. Reagent: Lipofectamine 3000. DNA amount: 2.5&mu;g/well.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 4: Incubate</b><br/>"
                "Return plate to incubator. Incubate for 4-6 hours at 37&deg;C, 5% CO2. "
                "Do not disturb the plate during incubation.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 5: Media Change</b><br/>"
                "After 4-6 hours, aspirate transfection media. "
                "Replace with 2mL fresh complete DMEM per well. "
                "Return to incubator.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 6: Assess Transfection (Day 2)</b><br/>"
                "At 48 hours post-transfection, count cells and assess viability. "
                "Take 100&mu;L sample, mix with Trypan Blue (1:2 dilution). "
                "Method: Trypan Blue exclusion. Expected viability: &gt;85%.",
                body,
            )
        )

    _build_pdf(
        out_dir / "document.pdf", "HEK293 Transient Transfection", "SOP-CC-023", body
    )


def generate_05_fill_finish_qc():
    """PDF: Fill/Finish with QC, 8 steps, 2 new unit ops, 2 roles."""
    out_dir = FIXTURES_DIR / "05-fill-finish-qc"
    out_dir.mkdir(exist_ok=True)

    def body(elements, header, body, section):
        elements.append(Paragraph("1. Purpose", section))
        elements.append(
            Paragraph(
                "Aseptic fill of drug product into 2mL glass vials, followed by "
                "lyophilization and QC release testing. Batch size: 500 vials.",
                body,
            )
        )
        elements.append(Paragraph("2. Responsible Personnel", section))

        roles = [
            ["Role", "Responsibility"],
            [
                "Fill Operator",
                "Steps 1-4, 6: Buffer prep, filtration, fill, sealing, lyo",
            ],
            [
                "QC Inspector",
                "Steps 5, 7, 8: Visual inspection, particulate testing, assay",
            ],
        ]
        role_table = Table(roles, colWidths=[2 * inch, 4.5 * inch])
        role_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.95)),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                ]
            )
        )
        elements.append(role_table)
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph("3. Procedure", section))
        elements.append(
            Paragraph(
                "<b>Step 1: Prepare Formulation Buffer</b> (Fill Operator)<br/>"
                "Prepare 5L of histidine formulation buffer (10mM L-histidine, 150mM NaCl, "
                "pH 6.0). Dissolve components in WFI, adjust pH with HCl. "
                "Volume: 5L. pH target: 6.0.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 2: Sterile Filtration</b> (Fill Operator)<br/>"
                "Filter drug substance through 0.22&mu;m PES membrane into sterile vessel. "
                "Filter type: PES membrane. Pore size: 0.22&mu;m. Volume: 1.2L. "
                "Perform integrity test post-filtration.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 3: Vial Filling</b> (Fill Operator)<br/>"
                "Fill each vial with 1.2mL drug product using peristaltic pump. "
                "Fill speed: medium (2 mL/sec). Container type: 2mL Type I glass vial. "
                "Check fill weight every 50 vials (&plusmn; 3% target).",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 4: Stoppering and Crimping</b> (Fill Operator)<br/>"
                "Insert rubber stopper into each vial under laminar flow. "
                "Apply aluminum crimp cap using manual crimping tool. "
                "Verify each seal visually. Duration: 120 minutes for 500 vials.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 5: 100% Visual Inspection</b> (QC Inspector)<br/>"
                "Inspect every vial against black and white backgrounds. "
                "Inspection type: 100% manual. Reject criteria: visible particles, "
                "cracks, seal defects, fill volume anomalies. "
                "Acceptance criteria: no visible particles, intact seal.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 6: Lyophilization</b> (Fill Operator)<br/>"
                "Load vials into lyophilizer. Cycle parameters: "
                "shelf temperature -40&deg;C, chamber pressure 100 mTorr, "
                "primary drying 24 hours, secondary drying 6 hours at 25&deg;C. "
                "Total cycle: 30 hours.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 7: Particulate Testing</b> (QC Inspector)<br/>"
                "Test per USP &lt;788&gt;. Use HIAC liquid particle counter. "
                "Acceptance: &le; 6000 particles &ge; 10&mu;m, &le; 600 particles &ge; 25&mu;m per container. "
                "Test 10 vials from the batch. Method: light obscuration.",
                body,
            )
        )
        elements.append(
            Paragraph(
                "<b>Step 8: Potency Assay</b> (QC Inspector)<br/>"
                "Run ELISA potency assay on 3 vials. "
                "Assay type: ELISA. Method: sandwich ELISA. "
                "Acceptance: 80-120% of nominal potency. "
                "Report mean, SD, and %CV.",
                body,
            )
        )

    _build_pdf(out_dir / "document.pdf", "Drug Product Fill/Finish", "SOP-FF-004", body)


def generate_06_messy_scan():
    """PNG: Low-quality scan simulating photographed laminated card."""
    out_dir = FIXTURES_DIR / "06-messy-scan"
    out_dir.mkdir(exist_ok=True)

    lines = [
        "# Cell Thaw Quick Reference",
        "---",
        "",
        "1. Thaw cryovial from LN2 storage",
        "   Place vial in 37C water bath",
        "   Swirl gently for 2-3 min until just thawed",
        "   Vial count: 1, Duration: 3 min",
        "",
        "2. Add thawed cells to pre-warmed media",
        "   Transfer vial contents to 15mL tube",
        "   Add 9mL pre-warmed complete DMEM",
        "   Media name: complete DMEM, Volume: 10mL",
        "",
        "3. Centrifuge to remove DMSO",
        "   Spin at 300xg for 5 min at RT",
        "   Discard supernatant carefully",
        "   RCF: 300g, Duration: 5 min, Temp: 22C",
        "",
        "4. Resuspend and seed",
        "   Resuspend pellet in 10mL fresh media",
        "   Seed into T-75 flask",
        "   Cell density: 0.3e6 cells/mL",
        "   Vessel: T-75 flask, Volume: 10mL",
    ]

    _build_png(out_dir / "document.png", lines, degrade=True)


def main():
    print("Generating benchmark fixtures...")
    generate_01_buffer_prep()
    print("  01-buffer-prep/document.pdf")
    generate_02_cell_culture_passage()
    print("  02-cell-culture-passage/document.pdf")
    generate_03_protein_a_purification()
    print("  03-protein-a-purification/document.png")
    generate_04_transfection()
    print("  04-transfection/document.pdf")
    generate_05_fill_finish_qc()
    print("  05-fill-finish-qc/document.pdf")
    generate_06_messy_scan()
    print("  06-messy-scan/document.png")
    print("Done.")


if __name__ == "__main__":
    main()
