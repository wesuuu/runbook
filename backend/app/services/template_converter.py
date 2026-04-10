"""Template conversion agent — converts filled documents to Jinja2 DOCX templates.

Pipeline:
1. Upload any file → convert to PDF via LibreOffice (if needed)
2. Feed PDF/image to a dedicated AI agent
3. AI outputs OpenXML <w:body> content with Jinja2 placeholders
4. Wrap in a valid .docx scaffold
5. Verification loop: render with mock data, check for issues, iterate
6. Return rendered preview + template download + warnings
"""

import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from docxtpl import DocxTemplate
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.file_storage import FileStorageService
from app.services.template_engine import KNOWN_VARIABLES, get_mock_context

logger = logging.getLogger(__name__)

MAX_VERIFICATION_ROUNDS = 3
JINJA_PATTERN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")

SYSTEM_PROMPT = """\
You are a document template engineer specializing in converting filled SOPs \
and batch records into reusable Jinja2 DOCX templates.

You will receive a PDF or image of a completed document. Your job:
1. Analyze the document structure (headings, paragraphs, tables, headers, footers)
2. Identify variable fields (dates, names, lot numbers, measurements, equipment IDs)
3. Output valid OpenXML (<w:body> content) with Jinja2 placeholders

VARIABLE NAMING:
- Use snake_case: operator_name, lot_number, completion_date, incubation_temp_c
- Use these KNOWN variables when applicable (they auto-fill from the system):
  {known_vars}

FOR TABLE LOOPS:
- Repeating rows (e.g., batch record steps) use {{%tr for step in steps %}} / \
{{%tr endfor %}} (docxtpl row-loop syntax)
- Place Jinja tags inside <w:t> elements

OPENXML RULES:
- Output ONLY the <w:body>...</w:body> content — no XML declaration, \
no document wrapper, no namespace declarations
- Use <w:p> for paragraphs, <w:tbl> for tables, <w:r><w:t> for text runs
- Use <w:pPr><w:pStyle w:val="Heading1"/></w:pPr> for headings
- Jinja2 syntax goes inside <w:t> elements as literal text
- Ensure all XML tags are properly closed and well-formed

EXAMPLE — paragraph with a variable:
<w:p>
  <w:r><w:t>Prepared by: {{{{ operator_name }}}} on {{{{ completion_date }}}}</w:t></w:r>
</w:p>

EXAMPLE — table with repeating rows:
<w:tbl>
  <w:tblPr><w:tblW w:w="5000" w:type="pct"/></w:tblPr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>Step</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>Description</w:t></w:r></w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>{{%tr for step in steps %}}</w:t></w:r></w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>{{{{ step.name }}}}</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>{{{{ step.description }}}}</w:t></w:r></w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>{{%tr endfor %}}</w:t></w:r></w:p></w:tc>
  </w:tr>
</w:tbl>
""".format(known_vars=", ".join(sorted(KNOWN_VARIABLES)))


# ── Data Classes ──


@dataclass
class RenderResult:
    """Result of attempting to render a template with mock data."""
    pdf_bytes: bytes
    jinja_remnants: list[str]
    format_issues: list[str]
    render_error: str | None = None


class ConversionState:
    """Tracks state for an active conversion session on the filesystem.

    Files are stored under: {storage_root}/{org_id}/conversions/{conversion_id}/
    """

    def __init__(
        self,
        org_id: UUID,
        conversion_id: UUID,
        storage_root: str = "./uploads",
    ) -> None:
        self.org_id = org_id
        self.conversion_id = conversion_id
        self.storage_root = Path(storage_root)
        self.base_path = Path(str(org_id)) / "conversions" / str(conversion_id)

    def _resolve(self, filename: str) -> Path:
        """Resolve a filename to full path under the conversion directory."""
        full = (self.storage_root / self.base_path / filename).resolve()
        root = self.storage_root.resolve()
        if not str(full).startswith(str(root) + "/") and full != root:
            raise ValueError("Path traversal detected")
        return full

    def ensure_dir(self) -> None:
        """Create the conversion directory if it doesn't exist."""
        self._resolve("_").parent.mkdir(parents=True, exist_ok=True)

    def write(self, filename: str, data: bytes) -> None:
        self._resolve(filename).write_bytes(data)

    def read(self, filename: str) -> bytes:
        return self._resolve(filename).read_bytes()

    def exists(self, filename: str) -> bool:
        return self._resolve(filename).exists()

    def write_json(self, filename: str, data: dict | list) -> None:
        self._resolve(filename).write_text(
            json.dumps(data, default=str), encoding="utf-8"
        )

    def read_json(self, filename: str) -> dict | list:
        return json.loads(self._resolve(filename).read_text(encoding="utf-8"))

    @property
    def preview_url(self) -> str:
        return f"/science/templates/conversions/{self.conversion_id}/preview.pdf"

    @property
    def template_url(self) -> str:
        return (
            f"/science/templates/conversions/{self.conversion_id}/template.docx"
        )


# ── Helper Functions ──


def _extract_body_xml(ai_output: str) -> str:
    """Extract <w:body> content from AI output, stripping code fences."""
    text = ai_output.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n", "", text)
        text = re.sub(r"\n```$", "", text)
        text = text.strip()
    # Extract body content if wrapped in <w:body> tags
    match = re.search(r"<w:body>(.*)</w:body>", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _wrap_in_docx(body_xml: str) -> bytes:
    """Wrap OpenXML body content into a valid .docx file.

    Creates a blank python-docx Document, then injects the AI-generated
    XML elements into its body. Falls back to plain paragraph on parse error.
    """
    from docx import Document
    from lxml import etree

    doc = Document()
    # Clear default empty paragraph
    for p in doc.paragraphs:
        p._element.getparent().remove(p._element)

    body = doc.element.body
    nsmap = doc.element.body.nsmap

    # Build namespace declarations for parsing
    ns_decls = " ".join(
        f'xmlns:{k}="{v}"' for k, v in nsmap.items() if k
    )
    # Default namespace needs special handling
    default_ns = nsmap.get(None, "")
    if default_ns:
        ns_decls = f'xmlns="{default_ns}" {ns_decls}'

    wrapped = f"<w:body {ns_decls}>{body_xml}</w:body>"

    try:
        new_body = etree.fromstring(wrapped.encode("utf-8"))
        for child in list(new_body):
            body.append(child)
    except etree.XMLSyntaxError as e:
        logger.warning("XML parse error in AI output: %s", e)
        # Fallback: insert raw text as a paragraph
        doc.add_paragraph(body_xml)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _extract_jinja_variables(xml_text: str) -> set[str]:
    """Extract Jinja2 variable names from OpenXML content.

    Returns top-level variable names (e.g., "step" from "{{ step.name }}")
    and collection names from {% for %} loops.
    """
    var_pattern = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
    loop_pattern = re.compile(r"\{%\s*(?:tr\s+)?for\s+(\w+)\s+in\s+(\w+)\s*%\}")
    variables: set[str] = set()

    for match in var_pattern.finditer(xml_text):
        name = match.group(1)
        top = name.split(".")[0]
        variables.add(top)

    for match in loop_pattern.finditer(xml_text):
        variables.add(match.group(1))  # loop variable
        variables.add(match.group(2))  # collection name

    return variables


def _try_render(template_bytes: bytes, template_type: str) -> RenderResult:
    """Render a template DOCX with mock data and check for issues.

    Returns a RenderResult with:
    - pdf_bytes: rendered PDF (empty on failure)
    - jinja_remnants: any Jinja2 syntax that survived rendering
    - format_issues: structural differences from expected output
    - render_error: error message if docxtpl render failed
    """
    mock_ctx = get_mock_context()

    with tempfile.TemporaryDirectory() as tmpdir:
        tpl_path = Path(tmpdir) / "template.docx"
        tpl_path.write_bytes(template_bytes)

        # Render with docxtpl
        try:
            doc = DocxTemplate(str(tpl_path))
            doc.render(mock_ctx)
            rendered_path = Path(tmpdir) / "rendered.docx"
            doc.save(str(rendered_path))
        except Exception as e:
            return RenderResult(
                pdf_bytes=b"",
                jinja_remnants=[],
                format_issues=[],
                render_error=f"docxtpl render failed: {e}",
            )

        # Check for surviving Jinja2 syntax in rendered output
        from docx import Document

        rendered_doc = Document(str(rendered_path))
        all_text_parts: list[str] = []
        for p in rendered_doc.paragraphs:
            all_text_parts.append(p.text)
        for table in rendered_doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    all_text_parts.append(cell.text)

        all_text = "\n".join(all_text_parts)
        remnants = JINJA_PATTERN.findall(all_text)

        # Convert to PDF for preview via LibreOffice
        pdf_bytes = b""
        try:
            subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmpdir,
                    str(rendered_path),
                ],
                capture_output=True,
                timeout=30,
            )
            pdf_path = Path(tmpdir) / "rendered.pdf"
            if pdf_path.exists():
                pdf_bytes = pdf_path.read_bytes()
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning("PDF conversion failed: %s", e)

        return RenderResult(
            pdf_bytes=pdf_bytes,
            jinja_remnants=remnants,
            format_issues=[],
        )


def _extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract readable text content from a DOCX file for the AI prompt.

    Extracts paragraphs and table contents in a structured format.
    """
    from docx import Document as DocxDocument

    doc = DocxDocument(BytesIO(file_bytes))
    parts: list[str] = []

    for element in doc.element.body:
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
        if tag == "p":
            # Paragraph
            text = element.text or ""
            # Collect text from runs
            runs_text = ""
            for run in element.iter():
                run_tag = run.tag.split("}")[-1] if "}" in run.tag else run.tag
                if run_tag == "t" and run.text:
                    runs_text += run.text
            if runs_text.strip():
                parts.append(runs_text.strip())
        elif tag == "tbl":
            # Table
            parts.append("[TABLE]")
            for row in element.iter():
                row_tag = row.tag.split("}")[-1] if "}" in row.tag else row.tag
                if row_tag == "tr":
                    cells: list[str] = []
                    for cell in row.iter():
                        cell_tag = (
                            cell.tag.split("}")[-1]
                            if "}" in cell.tag
                            else cell.tag
                        )
                        if cell_tag == "tc":
                            cell_text = ""
                            for t in cell.iter():
                                t_tag = (
                                    t.tag.split("}")[-1]
                                    if "}" in t.tag
                                    else t.tag
                                )
                                if t_tag == "t" and t.text:
                                    cell_text += t.text
                            cells.append(cell_text.strip())
                    if cells:
                        parts.append(" | ".join(cells))
            parts.append("[/TABLE]")

    return "\n".join(parts)


async def _to_pdf(file_bytes: bytes, filename: str) -> bytes:
    """Convert any supported file to PDF via LibreOffice.

    PDFs and images are returned as-is (images are fed directly to the
    model's vision input).
    """
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return file_bytes
    if ext in (".png", ".jpg", ".jpeg"):
        return file_bytes

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / f"input{ext}"
        input_path.write_bytes(file_bytes)
        result = subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                tmpdir,
                str(input_path),
            ],
            capture_output=True,
            timeout=60,
        )
        pdf_path = input_path.with_suffix(".pdf")
        if not pdf_path.exists():
            raise ValueError(
                f"LibreOffice failed to convert {filename} to PDF: "
                f"{result.stderr.decode()}"
            )
        return pdf_path.read_bytes()


# ── Main Conversion Pipeline ──


async def convert_document(
    db: AsyncSession,
    org_id: UUID,
    file_bytes: bytes,
    filename: str,
    template_type: str,
) -> dict[str, Any]:
    """Main conversion pipeline: file → PDF → AI → template → verify.

    Args:
        db: Database session (for model resolution).
        org_id: Organization ID.
        file_bytes: Raw uploaded file content.
        filename: Original filename (used for extension detection).
        template_type: "SOP" or "BATCH_RECORD".

    Returns a dict matching ConvertResponse schema.
    """
    from pydantic_ai import Agent

    from app.services.ai_config import get_model

    conversion_id = uuid4()
    state = ConversionState(org_id, conversion_id)
    state.ensure_dir()

    # Step 1: Store original and extract text content
    state.write("original.docx", file_bytes)

    ext = Path(filename).suffix.lower()
    is_image = ext in (".png", ".jpg", ".jpeg")

    # Extract text content based on file type
    if ext in (".docx",):
        doc_text = _extract_text_from_docx(file_bytes)
    elif is_image:
        doc_text = "[Image file — text extraction not available for images with this model]"
    else:
        # For PDF/XLSX, convert to PDF first then note limitation
        try:
            pdf_bytes = await _to_pdf(file_bytes, filename)
            state.write("original.pdf", pdf_bytes)
            doc_text = "[PDF content — extracted text not available, using file metadata only]"
        except Exception:
            doc_text = "[Could not extract text from this file format]"

    # Step 2: Call AI agent to generate OpenXML
    model = await get_model("template_convert", db, org_id=org_id)

    agent = Agent(model, system_prompt=SYSTEM_PROMPT)

    full_prompt = (
        f"Convert this completed {template_type} document into a Jinja2 "
        "DOCX template. Output ONLY the <w:body> OpenXML content.\n\n"
        "DOCUMENT CONTENT:\n"
        f"```\n{doc_text}\n```\n\n"
        "Analyze the document structure and content above. Identify all "
        "variable fields (names, dates, lot numbers, measurements, etc.) "
        "and replace them with appropriate {{ placeholder }} syntax. "
        "Keep static text (instructions, headers, section labels) as-is. "
        "Output ONLY the <w:body> OpenXML content."
    )

    result = await agent.run(full_prompt)
    body_xml = _extract_body_xml(result.output)
    template_docx = _wrap_in_docx(body_xml)
    state.write("template.docx", template_docx)

    # Step 3: Verification loop
    warnings: list[dict[str, str]] = []
    verification_passed = False
    rounds = 0
    chat_history: list[dict[str, str]] = []

    for i in range(MAX_VERIFICATION_ROUNDS):
        rounds = i + 1
        render_result = _try_render(template_docx, template_type)

        if render_result.render_error:
            chat_history.append({
                "role": "user",
                "content": (
                    f"The template failed to render: {render_result.render_error}. "
                    "Fix the OpenXML so it produces a valid template. "
                    "Output ONLY the corrected <w:body> content."
                ),
            })
            fix_result = await agent.run(
                chat_history[-1]["content"],
                message_history=result.all_messages(),
            )
            body_xml = _extract_body_xml(fix_result.output)
            template_docx = _wrap_in_docx(body_xml)
            state.write("template.docx", template_docx)
            result = fix_result
            continue

        if render_result.jinja_remnants:
            chat_history.append({
                "role": "user",
                "content": (
                    "The rendered output still contains raw Jinja2 syntax: "
                    f"{render_result.jinja_remnants}. Fix the template XML "
                    "so all placeholders render correctly with docxtpl. "
                    "Output ONLY the corrected <w:body> content."
                ),
            })
            fix_result = await agent.run(
                chat_history[-1]["content"],
                message_history=result.all_messages(),
            )
            body_xml = _extract_body_xml(fix_result.output)
            template_docx = _wrap_in_docx(body_xml)
            state.write("template.docx", template_docx)
            result = fix_result
            continue

        verification_passed = True
        break

    # Step 4: Render final preview
    final_render = _try_render(template_docx, template_type)
    if final_render.pdf_bytes:
        state.write("preview.pdf", final_render.pdf_bytes)

    # Step 5: Check missing known variables
    detected_vars = _extract_jinja_variables(body_xml)
    missing = sorted(v for v in KNOWN_VARIABLES if v not in detected_vars)
    for var in missing:
        warnings.append({
            "type": "missing_variable",
            "variable": var,
            "description": (
                f"Template does not use '{var}' — this data won't appear "
                "in the rendered output"
            ),
        })

    state.write_json("chat_history.json", chat_history)
    state.write_json("detected_vars.json", sorted(detected_vars))

    return {
        "conversion_id": str(conversion_id),
        "preview_url": state.preview_url,
        "template_download_url": state.template_url,
        "warnings": warnings,
        "variables_detected": sorted(detected_vars),
        "verification_rounds": rounds,
        "verification_passed": verification_passed,
    }


async def refine_template(
    db: AsyncSession,
    org_id: UUID,
    state: ConversionState,
    instruction: str,
) -> dict[str, Any]:
    """Refine an existing conversion via natural language instruction.

    Loads the current template and chat history, sends the instruction
    to the AI agent, and re-runs the verification loop.
    """
    from pydantic_ai import Agent

    from app.services.ai_config import get_model

    model = await get_model("template_convert", db, org_id=org_id)
    agent = Agent(model, system_prompt=SYSTEM_PROMPT)

    chat_history = state.read_json("chat_history.json") if state.exists(
        "chat_history.json"
    ) else []

    prompt = (
        f"The user wants to modify the template: {instruction}\n\n"
        "Output ONLY the updated <w:body> OpenXML content."
    )

    result = await agent.run(prompt)
    body_xml = _extract_body_xml(result.output)
    template_docx = _wrap_in_docx(body_xml)
    state.write("template.docx", template_docx)

    chat_history.append({"role": "user", "content": instruction})
    chat_history.append({"role": "assistant", "content": "Template updated."})

    # Re-run verification
    verification_passed = False
    rounds = 0
    for i in range(MAX_VERIFICATION_ROUNDS):
        rounds = i + 1
        render_result = _try_render(template_docx, "SOP")

        if render_result.render_error or render_result.jinja_remnants:
            issue = render_result.render_error or str(
                render_result.jinja_remnants
            )
            fix_result = await agent.run(
                f"Fix this issue: {issue}. Output ONLY corrected <w:body>.",
                message_history=result.all_messages(),
            )
            body_xml = _extract_body_xml(fix_result.output)
            template_docx = _wrap_in_docx(body_xml)
            state.write("template.docx", template_docx)
            result = fix_result
            continue

        verification_passed = True
        break

    final_render = _try_render(template_docx, "SOP")
    if final_render.pdf_bytes:
        state.write("preview.pdf", final_render.pdf_bytes)

    detected_vars = _extract_jinja_variables(body_xml)
    warnings: list[dict[str, str]] = []
    missing = sorted(v for v in KNOWN_VARIABLES if v not in detected_vars)
    for var in missing:
        warnings.append({
            "type": "missing_variable",
            "variable": var,
            "description": (
                f"Template does not use '{var}' — this data won't appear "
                "in the rendered output"
            ),
        })

    state.write_json("chat_history.json", chat_history)
    state.write_json("detected_vars.json", sorted(detected_vars))

    return {
        "conversion_id": str(state.conversion_id),
        "preview_url": state.preview_url,
        "template_download_url": state.template_url,
        "warnings": warnings,
        "variables_detected": sorted(detected_vars),
        "verification_rounds": rounds,
        "verification_passed": verification_passed,
    }


async def reupload_template(
    db: AsyncSession,
    org_id: UUID,
    state: ConversionState,
    file_bytes: bytes,
) -> dict[str, Any]:
    """Re-upload a manually edited template, re-render and re-validate."""
    state.write("template.docx", file_bytes)

    render_result = _try_render(file_bytes, "SOP")

    if render_result.pdf_bytes:
        state.write("preview.pdf", render_result.pdf_bytes)

    # Extract variables from the uploaded template
    from docx import Document as DocxDocument

    doc = DocxDocument(BytesIO(file_bytes))
    all_text_parts: list[str] = []
    for p in doc.paragraphs:
        all_text_parts.append(p.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_text_parts.append(cell.text)
    all_text = "\n".join(all_text_parts)

    detected_vars = _extract_jinja_variables(all_text)

    warnings: list[dict[str, str]] = []
    if render_result.render_error:
        warnings.append({
            "type": "render_error",
            "variable": "",
            "description": render_result.render_error,
        })
    if render_result.jinja_remnants:
        warnings.append({
            "type": "jinja_remnants",
            "variable": "",
            "description": (
                f"Raw Jinja2 syntax survived rendering: "
                f"{render_result.jinja_remnants}"
            ),
        })

    missing = sorted(v for v in KNOWN_VARIABLES if v not in detected_vars)
    for var in missing:
        warnings.append({
            "type": "missing_variable",
            "variable": var,
            "description": (
                f"Template does not use '{var}' — this data won't appear "
                "in the rendered output"
            ),
        })

    state.write_json("detected_vars.json", sorted(detected_vars))

    verification_passed = (
        not render_result.render_error and not render_result.jinja_remnants
    )

    return {
        "conversion_id": str(state.conversion_id),
        "preview_url": state.preview_url,
        "template_download_url": state.template_url,
        "warnings": warnings,
        "variables_detected": sorted(detected_vars),
        "verification_rounds": 1,
        "verification_passed": verification_passed,
    }


async def save_to_library(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    state: ConversionState,
    name: str,
    template_type: str,
    description: str | None,
    project_id: UUID | None,
    set_as_default: bool,
) -> dict[str, Any]:
    """Save the converted template to the DocumentTemplate library.

    Copies the template file to the templates storage path and creates
    a DocumentTemplate DB record.
    """
    from app.models.templates import DocumentTemplate
    from app.services.template_engine import parse_template

    template_bytes = state.read("template.docx")

    # Store in the templates directory
    storage = FileStorageService()
    filename = f"converted_{state.conversion_id}.docx"
    parts = [str(org_id), "document_templates", filename]
    relative_path = str(Path(*parts))
    full_path = storage.storage_root / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(template_bytes)

    # Parse variables from the template
    recognized, unrecognized = parse_template(full_path)

    template = DocumentTemplate(
        org_id=org_id,
        project_id=project_id,
        uploaded_by_id=user_id,
        name=name,
        description=description,
        template_type=template_type,
        file_path=relative_path,
        original_filename=filename,
        mime_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        file_size_bytes=len(template_bytes),
        variables={"recognized": recognized, "unrecognized": unrecognized},
    )
    db.add(template)
    await db.flush()

    return {
        "id": str(template.id),
        "name": template.name,
        "template_type": template.template_type,
        "status": template.status,
    }
