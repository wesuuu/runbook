"""Template conversion agent — converts filled documents to Jinja2 DOCX templates.

Uses a tool-use agent loop where the AI model drives the conversion by calling
tools to write, validate, and compare templates iteratively. Progress is
streamed to the frontend via Server-Sent Events (SSE).
"""

import asyncio
import json
import logging
import re
import subprocess
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from docxtpl import DocxTemplate
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import BinaryContent
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.file_storage import FileStorageService
from app.services.template_engine import KNOWN_VARIABLES, get_mock_context

logger = logging.getLogger(__name__)

JINJA_PATTERN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")

TOOL_LIMIT_MSG = (
    "Tool call limit ({limit}) reached. Conversion cannot continue — "
    "the document may be too complex for the current model. "
    "Please simplify the document or configure a more capable AI model."
)


# ── SSE Event Stream ──


class EventStream:
    """Buffered async event stream for SSE.

    The background conversion task pushes events via push().
    The SSE endpoint reads events via the async iterator protocol.
    Supports late-joining clients by replaying from buffer index 0.
    """

    def __init__(self) -> None:
        self._events: list[tuple[str, str]] = []
        self._waiters: list[asyncio.Event] = []
        self._closed = False

    def push(self, event_type: str, data: dict) -> None:
        """Push an event. Called from the background task."""
        self._events.append((event_type, json.dumps(data, default=str)))
        for w in self._waiters:
            w.set()

    def close(self) -> None:
        """Signal no more events will come."""
        self._closed = True
        for w in self._waiters:
            w.set()

    async def iter_events(self) -> AsyncIterator[tuple[str, str]]:
        """Async iterator yielding (event_type, data_json) tuples."""
        idx = 0
        while True:
            while idx < len(self._events):
                yield self._events[idx]
                idx += 1
            if self._closed:
                return
            waiter = asyncio.Event()
            self._waiters.append(waiter)
            await waiter.wait()
            self._waiters.remove(waiter)


# Module-level registry: conversion_id -> EventStream
_active_streams: dict[str, EventStream] = {}


# ── Data Classes ──


@dataclass
class RenderResult:
    """Result of attempting to render a template with mock data."""

    pdf_bytes: bytes
    jinja_remnants: list[str]
    format_issues: list[str]
    render_error: str | None = None


@dataclass
class ConversionDeps:
    """Dependencies injected into pydantic-ai tools via RunContext."""

    state: "ConversionState"
    event_stream: EventStream
    org_id: UUID
    template_type: str
    original_pdf_bytes: bytes
    model: Any
    tool_call_count: int = field(default=0, init=False)
    max_tool_calls: int = field(
        default_factory=lambda: settings.template_convert_max_tool_calls
    )


class ConversionState:
    """Tracks state for an active conversion session on the filesystem.

    Files are stored under:
        {storage_root}/{org_id}/tmp/conversions/{conversion_id}/
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
        self.base_path = (
            Path(str(org_id)) / "tmp" / "conversions" / str(conversion_id)
        )

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
        return (
            f"/science/templates/conversions/"
            f"{self.conversion_id}/preview.pdf"
        )

    @property
    def template_url(self) -> str:
        return (
            f"/science/templates/conversions/"
            f"{self.conversion_id}/template.docx"
        )


# ── Helper Functions ──


def _extract_body_xml(ai_output: str) -> str:
    """Extract <w:body> content from AI output, stripping code fences."""
    text = ai_output.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n", "", text)
        text = re.sub(r"\n```$", "", text)
        text = text.strip()
    match = re.search(r"<w:body>(.*)</w:body>", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _wrap_in_docx(body_xml: str) -> bytes:
    """Wrap OpenXML body content into a valid .docx file."""
    from docx import Document
    from lxml import etree

    doc = Document()
    for p in doc.paragraphs:
        p._element.getparent().remove(p._element)

    body = doc.element.body
    nsmap = doc.element.body.nsmap

    ns_decls = " ".join(
        f'xmlns:{k}="{v}"' for k, v in nsmap.items() if k
    )
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
        doc.add_paragraph(body_xml)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _extract_jinja_variables(xml_text: str) -> set[str]:
    """Extract Jinja2 variable names from template text."""
    var_pattern = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
    loop_pattern = re.compile(
        r"\{%\s*(?:tr\s+)?for\s+(\w+)\s+in\s+(\w+)\s*%\}"
    )
    variables: set[str] = set()

    for match in var_pattern.finditer(xml_text):
        name = match.group(1)
        top = name.split(".")[0]
        variables.add(top)

    for match in loop_pattern.finditer(xml_text):
        variables.add(match.group(1))
        variables.add(match.group(2))

    return variables


def _try_render(template_bytes: bytes, template_type: str) -> RenderResult:
    """Render a template DOCX with mock data and check for issues."""
    mock_ctx = get_mock_context()

    with tempfile.TemporaryDirectory() as tmpdir:
        tpl_path = Path(tmpdir) / "template.docx"
        tpl_path.write_bytes(template_bytes)

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
    """Extract readable text content from a DOCX file."""
    from docx import Document as DocxDocument

    doc = DocxDocument(BytesIO(file_bytes))
    parts: list[str] = []

    for element in doc.element.body:
        tag = (
            element.tag.split("}")[-1]
            if "}" in element.tag
            else element.tag
        )
        if tag == "p":
            runs_text = ""
            for run in element.iter():
                run_tag = (
                    run.tag.split("}")[-1]
                    if "}" in run.tag
                    else run.tag
                )
                if run_tag == "t" and run.text:
                    runs_text += run.text
            if runs_text.strip():
                parts.append(runs_text.strip())
        elif tag == "tbl":
            parts.append("[TABLE]")
            for row in element.iter():
                row_tag = (
                    row.tag.split("}")[-1]
                    if "}" in row.tag
                    else row.tag
                )
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
    """Convert any supported file to PDF via LibreOffice."""
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


def _extract_docx_text(template_bytes: bytes) -> str:
    """Extract all text from a DOCX file (paragraphs + tables)."""
    from docx import Document as DocxDocument

    doc = DocxDocument(BytesIO(template_bytes))
    parts: list[str] = []
    for p in doc.paragraphs:
        parts.append(p.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


# ── Tool Functions ──


def _check_tool_limit(deps: ConversionDeps, tool_name: str) -> str | None:
    """Increment counter and return error string if over limit."""
    deps.tool_call_count += 1
    if deps.tool_call_count > deps.max_tool_calls:
        msg = TOOL_LIMIT_MSG.format(limit=deps.max_tool_calls)
        deps.event_stream.push("error", {"message": msg})
        return msg
    return None


async def write_template_tool(
    ctx: RunContext[ConversionDeps], body_xml: str
) -> str:
    """Write OpenXML body content as a DOCX template file.

    Takes the <w:body> inner XML content, wraps it into a valid .docx,
    and stores it. Returns a file_id for use with validate() and
    compare_to_original().
    """
    deps = ctx.deps
    seq = deps.tool_call_count + 1

    err = _check_tool_limit(deps, "write_template")
    if err:
        return err

    deps.event_stream.push(
        "tool_call",
        {"tool": "write_template", "status": "running", "sequence": seq},
    )

    try:
        cleaned_xml = _extract_body_xml(body_xml)
        docx_bytes = _wrap_in_docx(cleaned_xml)
        deps.state.write("template.docx", docx_bytes)

        deps.event_stream.push(
            "tool_result",
            {
                "tool": "write_template",
                "status": "success",
                "sequence": seq,
                "summary": f"Template created ({len(docx_bytes)} bytes)",
            },
        )
        return f"Success. file_id=template.docx"
    except Exception as e:
        deps.event_stream.push(
            "tool_result",
            {
                "tool": "write_template",
                "status": "error",
                "sequence": seq,
                "summary": str(e)[:200],
            },
        )
        return f"Error writing template: {e}"


async def validate_tool(
    ctx: RunContext[ConversionDeps], file_id: str
) -> str:
    """Validate the template DOCX and check Jinja2 syntax.

    Renders the template with mock data, checks for render errors and
    surviving Jinja2 syntax, and extracts detected variables.
    """
    deps = ctx.deps
    seq = deps.tool_call_count + 1

    err = _check_tool_limit(deps, "validate")
    if err:
        return err

    deps.event_stream.push(
        "tool_call",
        {"tool": "validate", "status": "running", "sequence": seq},
    )

    try:
        template_bytes = deps.state.read(file_id)
        render_result = _try_render(template_bytes, deps.template_type)

        all_text = _extract_docx_text(template_bytes)
        detected_vars = _extract_jinja_variables(all_text)

        issues = []
        if render_result.render_error:
            issues.append(f"Render error: {render_result.render_error}")
        if render_result.jinja_remnants:
            issues.append(
                f"Jinja remnants after render: "
                f"{render_result.jinja_remnants}"
            )

        status_str = "error" if issues else "success"
        summary = (
            "; ".join(issues)
            if issues
            else f"Valid. {len(detected_vars)} variables found."
        )

        deps.event_stream.push(
            "tool_result",
            {
                "tool": "validate",
                "status": status_str,
                "sequence": seq,
                "summary": summary[:200],
            },
        )

        result_parts = [f"Variables found: {sorted(detected_vars)}"]
        if issues:
            result_parts.append(f"Issues: {'; '.join(issues)}")
        else:
            result_parts.append(
                "No issues found. Template renders cleanly."
            )
        return "\n".join(result_parts)
    except Exception as e:
        deps.event_stream.push(
            "tool_result",
            {
                "tool": "validate",
                "status": "error",
                "sequence": seq,
                "summary": str(e)[:200],
            },
        )
        return f"Error validating: {e}"


async def compare_to_original_tool(
    ctx: RunContext[ConversionDeps], file_id: str
) -> str:
    """Render the template with mock data and compare to the original.

    Renders the template to PDF, then spawns a vision subagent to
    compare the rendered output against the original document.
    Returns a text assessment of visual fidelity.
    """
    deps = ctx.deps
    seq = deps.tool_call_count + 1

    err = _check_tool_limit(deps, "compare_to_original")
    if err:
        return err

    deps.event_stream.push(
        "tool_call",
        {
            "tool": "compare_to_original",
            "status": "running",
            "sequence": seq,
        },
    )

    try:
        template_bytes = deps.state.read(file_id)
        render_result = _try_render(template_bytes, deps.template_type)

        if not render_result.pdf_bytes:
            deps.event_stream.push(
                "tool_result",
                {
                    "tool": "compare_to_original",
                    "status": "error",
                    "sequence": seq,
                    "summary": (
                        "Could not render PDF for comparison"
                        f" ({render_result.render_error})"
                    ),
                },
            )
            return (
                f"Cannot compare: render failed "
                f"({render_result.render_error})"
            )

        deps.state.write("preview.pdf", render_result.pdf_bytes)

        comparison_prompt = (
            "Compare these two documents. The first is the ORIGINAL "
            "filled document. The second is a RENDERED TEMPLATE with "
            "mock data filled in.\n\n"
            "Assess:\n"
            "1. Structural match — sections, tables, headings in same "
            "order?\n"
            "2. Formatting similarity — fonts, spacing, layout\n"
            "3. Missing or extra content\n\n"
            "Be specific about differences. If they match well, say so "
            "briefly."
        )

        original_bytes = deps.original_pdf_bytes
        original_mime = "application/pdf"
        if original_bytes[:4] == b"\x89PNG":
            original_mime = "image/png"
        elif original_bytes[:2] == b"\xff\xd8":
            original_mime = "image/jpeg"

        vision_agent: Agent[None, str] = Agent(
            deps.model,
            system_prompt="You are a document comparison assistant.",
            output_type=str,
        )

        user_content: list[Any] = [
            BinaryContent(
                data=original_bytes, media_type=original_mime
            ),
            BinaryContent(
                data=render_result.pdf_bytes,
                media_type="application/pdf",
            ),
            comparison_prompt,
        ]

        vision_result = await asyncio.wait_for(
            vision_agent.run(user_content),
            timeout=120,
        )

        assessment = vision_result.output
        deps.event_stream.push(
            "tool_result",
            {
                "tool": "compare_to_original",
                "status": "success",
                "sequence": seq,
                "summary": assessment[:200],
            },
        )
        return assessment
    except Exception as e:
        deps.event_stream.push(
            "tool_result",
            {
                "tool": "compare_to_original",
                "status": "error",
                "sequence": seq,
                "summary": str(e)[:200],
            },
        )
        return f"Comparison failed: {e}"


# ── System Prompt ──


SYSTEM_PROMPT = """\
You are a document template engineer specializing in converting filled SOPs \
and batch records into reusable Jinja2 DOCX templates.

You have 3 tools:
1. write_template(body_xml) — Write OpenXML <w:body> content as a DOCX file
2. validate(file_id) — Validate the template renders with mock data
3. compare_to_original(file_id) — Visually compare rendered output to original

YOUR WORKFLOW:
1. Analyze the document, identify variable fields, generate OpenXML
2. Call write_template() with your XML
3. Call validate("template.docx") to check for errors
4. If errors: fix the XML, call write_template() again, then validate() again
5. Once validation passes, call compare_to_original("template.docx")
6. If the comparison reveals issues, fix and repeat from step 2

You have a limited number of tool calls. If a tool tells you the limit is \
reached, stop immediately and report what you have so far.

VARIABLE NAMING:
- Use snake_case: operator_name, lot_number, completion_date, incubation_temp_c
- Use these KNOWN variables when applicable (they auto-fill from the system):
  {known_vars}

FOR TABLE LOOPS:
- Repeating rows use {{%tr for step in steps %}} / {{%tr endfor %}} \
(docxtpl row-loop syntax)
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
  <w:r><w:t>Prepared by: {{{{ operator_name }}}} on \
{{{{ completion_date }}}}</w:t></w:r>
</w:p>

EXAMPLE — table with repeating rows:
<w:tbl>
  <w:tblPr><w:tblW w:w="5000" w:type="pct"/></w:tblPr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>Step</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>Description</w:t></w:r></w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>{{%tr for step in steps %}}</w:t></w:r>\
</w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>{{{{ step.name }}}}</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>{{{{ step.description }}}}</w:t></w:r>\
</w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>{{%tr endfor %}}</w:t></w:r></w:p></w:tc>
  </w:tr>
</w:tbl>
""".format(known_vars=", ".join(sorted(KNOWN_VARIABLES)))


# ── Main Conversion Pipeline ──


async def convert_document(
    db: AsyncSession,
    org_id: UUID,
    file_bytes: bytes,
    filename: str,
    template_type: str,
    conversion_id: UUID | None = None,
) -> dict[str, Any]:
    """Main conversion: file -> agent loop with tools -> template.

    The AI model drives the conversion by calling write_template,
    validate, and compare_to_original tools in whatever order it
    chooses, up to a configurable max tool calls limit.
    """
    from app.services.ai_config import get_model

    if conversion_id is None:
        conversion_id = uuid4()

    state = ConversionState(org_id, conversion_id)
    state.ensure_dir()

    event_stream = EventStream()
    _active_streams[str(conversion_id)] = event_stream

    try:
        # Store original and prepare input
        state.write("original", file_bytes)

        ext = Path(filename).suffix.lower()
        if ext in (".docx",):
            doc_text = _extract_text_from_docx(file_bytes)
            original_pdf = await _to_pdf(file_bytes, filename)
        elif ext in (".png", ".jpg", ".jpeg"):
            doc_text = "[Image file]"
            original_pdf = file_bytes
        else:
            original_pdf = await _to_pdf(file_bytes, filename)
            doc_text = "[PDF/other content]"

        state.write("original.pdf", original_pdf)

        # Resolve model
        model = await get_model("template_convert", db, org_id=org_id)

        # Build deps and agent
        deps = ConversionDeps(
            state=state,
            event_stream=event_stream,
            org_id=org_id,
            template_type=template_type,
            original_pdf_bytes=original_pdf,
            model=model,
        )

        agent: Agent[ConversionDeps, str] = Agent(
            model,
            system_prompt=SYSTEM_PROMPT,
            tools=[
                write_template_tool,
                validate_tool,
                compare_to_original_tool,
            ],
            deps_type=ConversionDeps,
        )

        user_prompt = (
            f"Convert this completed {template_type} document into a "
            "Jinja2 DOCX template.\n\n"
            "DOCUMENT CONTENT:\n"
            f"```\n{doc_text}\n```\n\n"
            "Analyze the document structure and content above. Identify "
            "all variable fields (names, dates, lot numbers, "
            "measurements, etc.) and replace them with appropriate "
            "{{ placeholder }} syntax. Keep static text (instructions, "
            "headers, section labels) as-is.\n\n"
            "Use your tools to write the template, validate it, and "
            "compare the rendered output to the original document."
        )

        await asyncio.wait_for(
            agent.run(user_prompt, deps=deps),
            timeout=600,
        )

        # Build final result from state
        detected_vars: set[str] = set()
        if state.exists("template.docx"):
            template_bytes = state.read("template.docx")
            all_text = _extract_docx_text(template_bytes)
            detected_vars = _extract_jinja_variables(all_text)

        warnings: list[dict[str, str]] = []
        missing = sorted(
            v for v in KNOWN_VARIABLES if v not in detected_vars
        )
        for var in missing:
            warnings.append({
                "type": "missing_variable",
                "variable": var,
                "description": (
                    f"Template does not use '{var}' — this data "
                    "won't appear in the rendered output"
                ),
            })

        result_data = {
            "conversion_id": str(conversion_id),
            "preview_url": state.preview_url,
            "template_download_url": state.template_url,
            "warnings": warnings,
            "variables_detected": sorted(detected_vars),
        }

        state.write_json("result.json", result_data)

        event_stream.push("complete", {
            "template_url": state.template_url,
            "preview_url": (
                state.preview_url
                if state.exists("preview.pdf")
                else None
            ),
            "variables": sorted(detected_vars),
            "warnings": warnings,
        })

        return result_data

    except Exception as e:
        logger.exception("Template conversion failed")
        event_stream.push("error", {"message": str(e)})
        raise
    finally:
        event_stream.close()


async def refine_template(
    db: AsyncSession,
    org_id: UUID,
    state: ConversionState,
    instruction: str,
) -> dict[str, Any]:
    """Refine an existing conversion via natural language instruction.

    Uses the same tool-based agent loop as convert_document.
    """
    from app.services.ai_config import get_model

    cid = str(state.conversion_id)
    event_stream = EventStream()
    _active_streams[cid] = event_stream

    try:
        model = await get_model("template_convert", db, org_id=org_id)

        original_pdf = (
            state.read("original.pdf")
            if state.exists("original.pdf")
            else b""
        )

        deps = ConversionDeps(
            state=state,
            event_stream=event_stream,
            org_id=org_id,
            template_type="SOP",
            original_pdf_bytes=original_pdf,
            model=model,
        )

        agent: Agent[ConversionDeps, str] = Agent(
            model,
            system_prompt=SYSTEM_PROMPT,
            tools=[
                write_template_tool,
                validate_tool,
                compare_to_original_tool,
            ],
            deps_type=ConversionDeps,
        )

        # Load current template text for context
        current_text = ""
        if state.exists("template.docx"):
            current_text = _extract_docx_text(
                state.read("template.docx")
            )

        prompt = (
            f"The user wants to modify the existing template.\n"
            f"Current template content:\n{current_text[:3000]}\n\n"
            f"User instruction: {instruction}\n\n"
            "Apply the changes, write the updated template, validate "
            "it, and compare to the original document."
        )

        await asyncio.wait_for(
            agent.run(prompt, deps=deps),
            timeout=300,
        )

        # Build result
        detected_vars: set[str] = set()
        if state.exists("template.docx"):
            all_text = _extract_docx_text(state.read("template.docx"))
            detected_vars = _extract_jinja_variables(all_text)

        warnings: list[dict[str, str]] = []
        missing = sorted(
            v for v in KNOWN_VARIABLES if v not in detected_vars
        )
        for var in missing:
            warnings.append({
                "type": "missing_variable",
                "variable": var,
                "description": (
                    f"Template does not use '{var}' — this data "
                    "won't appear in the rendered output"
                ),
            })

        result_data = {
            "conversion_id": str(state.conversion_id),
            "preview_url": state.preview_url,
            "template_download_url": state.template_url,
            "warnings": warnings,
            "variables_detected": sorted(detected_vars),
        }

        event_stream.push("complete", {
            "template_url": state.template_url,
            "preview_url": (
                state.preview_url
                if state.exists("preview.pdf")
                else None
            ),
            "variables": sorted(detected_vars),
            "warnings": warnings,
        })

        return result_data

    except Exception as e:
        logger.exception("Template refinement failed")
        event_stream.push("error", {"message": str(e)})
        raise
    finally:
        event_stream.close()


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

    all_text = _extract_docx_text(file_bytes)
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

    return {
        "conversion_id": str(state.conversion_id),
        "preview_url": state.preview_url,
        "template_download_url": state.template_url,
        "warnings": warnings,
        "variables_detected": sorted(detected_vars),
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
    """Save the converted template to the DocumentTemplate library."""
    from app.models.templates import DocumentTemplate
    from app.services.template_engine import parse_template

    template_bytes = state.read("template.docx")

    storage = FileStorageService()
    filename = f"converted_{state.conversion_id}.docx"
    parts = [str(org_id), "document_templates", filename]
    relative_path = str(Path(*parts))
    full_path = storage.storage_root / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(template_bytes)

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
        variables={
            "recognized": recognized,
            "unrecognized": unrecognized,
        },
    )
    db.add(template)
    await db.flush()

    return {
        "id": str(template.id),
        "name": template.name,
        "template_type": template.template_type,
        "status": template.status,
    }
