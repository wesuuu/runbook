"""Service to import protocols from uploaded documents (PDF, DOCX, images).

Orchestrates: text extraction → LLM parsing → unit op matching →
graph building. Supports iterative refinement via a stateless
refine endpoint.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.protocols import Protocol, ProtocolRole, UnitOpDefinition
from app.services.ai.ai_config import get_model
from app.services.ai.workflows.protocol_generator import (
    GeneratedProtocol,
    GeneratedStep,
    build_graph,
    extract_params,
    match_unit_op,
)

logger = logging.getLogger(__name__)


# ── Role color palette (mirrors frontend protocolNodes.getNextRoleColor) ──

ROLE_COLORS = [
    "#6366f1",  # indigo
    "#f59e0b",  # amber
    "#10b981",  # emerald
    "#ef4444",  # red
    "#8b5cf6",  # violet
    "#06b6d4",  # cyan
    "#f97316",  # orange
]


# ── Pydantic models for LLM structured output ──────────────────────


class ImportedParam(BaseModel):
    """A parameter extracted from the protocol document."""

    name: str = Field(description="Parameter name (snake_case)")
    type: str = Field(
        default="string",
        description="Data type: number, string, or boolean",
    )
    unit: str | None = Field(default=None, description="Unit of measurement")
    default: Any = Field(default=None, description="Default value if mentioned")


class ImportedStep(BaseModel):
    """A single step parsed from the protocol document."""

    name: str = Field(description="Step name")
    description: str = Field(default="", description="Brief description")
    category: str = Field(default="General", description="Category")
    duration_min: int | None = Field(
        default=30, description="Estimated duration in minutes"
    )
    params: list[ImportedParam] = Field(
        default_factory=list,
        description="Parameters for this step",
    )
    role: str | None = Field(
        default=None,
        description="Role/responsibility if mentioned (e.g. Operator, QC Lead)",
    )
    matched_unit_op_name: str | None = Field(
        default=None,
        description="Exact name from the unit op catalog if a match was found, else null",
    )


class ParsedProtocol(BaseModel):
    """Complete protocol parsed from a document by the LLM."""

    protocol_name: str = Field(description="Protocol name")
    protocol_description: str = Field(default="", description="Protocol description")
    steps: list[ImportedStep] = Field(description="Ordered list of steps")


# ── Two-agent pipeline: structure first, params second ─────────────


class StepSkeleton(BaseModel):
    """Step without params — output of structure agent (agent 1)."""

    name: str = Field(description="Step name")
    description: str = Field(default="", description="Brief description")
    category: str = Field(default="General", description="Category")
    duration_min: int | None = Field(
        default=30, description="Estimated duration in minutes"
    )
    role: str | None = Field(
        default=None,
        description="Role/responsibility if mentioned",
    )
    matched_unit_op_name: str | None = Field(
        default=None,
        description="Exact name from the unit op catalog if a match was found",
    )


class ProtocolSkeleton(BaseModel):
    """Protocol structure without params — output of structure agent (agent 1)."""

    protocol_name: str = Field(description="Protocol name")
    protocol_description: str = Field(default="", description="Protocol description")
    steps: list[StepSkeleton] = Field(description="Ordered list of steps (no params)")


class StepParams(BaseModel):
    """Params for a single step — output of param agent (agent 2)."""

    step_index: int = Field(description="Zero-based index of the step in the skeleton")
    params: list[ImportedParam] = Field(
        default_factory=list,
        description="Parameters extracted for this step",
    )


class ProtocolParams(BaseModel):
    """All per-step params — output of param agent (agent 2)."""

    steps: list[StepParams] = Field(
        default_factory=list,
        description="Params for each step, keyed by step_index",
    )


# ── Proposal models (returned for frontend review) ─────────────────


class StepProposal(BaseModel):
    """One step in the proposed protocol with match info."""

    name: str
    description: str = ""
    category: str = "General"
    duration_min: int = 30
    params: dict[str, Any] = Field(default_factory=dict)
    param_schema: dict[str, Any] = Field(default_factory=dict)
    role: str | None = None
    matched_unit_op_id: str | None = None
    matched_unit_op_name: str | None = None
    is_new: bool = False


class ProtocolImportProposal(BaseModel):
    """Full proposal returned for user review."""

    protocol_name: str
    protocol_description: str = ""
    steps: list[StepProposal]
    matched_count: int
    unmatched_count: int
    source_filename: str
    source_text_preview: str = ""


# ── Helper: build param_schema from ImportedParam list ──────────────


def build_param_schema_from_params(params: list[ImportedParam]) -> dict[str, Any]:
    """Convert a list of ImportedParam into a JSON Schema dict."""
    properties: dict[str, Any] = {}
    for p in params:
        prop: dict[str, Any] = {"type": p.type}
        if p.unit:
            prop["unit"] = p.unit
        if p.default is not None:
            prop["default"] = p.default
        prop["title"] = p.name.replace("_", " ").title()
        properties[p.name] = prop
    return {"type": "object", "properties": properties}


# ── Text extraction ─────────────────────────────────────────────────


async def extract_text(
    file_path: Path,
    mime_type: str,
    db: AsyncSession,
    org_id: UUID | None = None,
) -> str:
    """Extract text from a document based on its MIME type.

    Routes to the appropriate extractor:
    - PDF: pymupdf page-by-page extraction
    - DOCX: python-docx paragraph extraction
    - Images: vision LLM OCR
    """
    if mime_type == "application/pdf":
        from app.services.documents.document_processor import extract_pdf_pages

        pages = await asyncio.to_thread(extract_pdf_pages, file_path, False)
        return "\n\n".join(p.text for p in pages if p.text)

    if mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        from app.services.documents.document_processor import extract_docx

        return await asyncio.to_thread(extract_docx, file_path)

    if mime_type.startswith("image/"):
        from app.services.ai.ai_vision import extract_document_text

        return await extract_document_text(str(file_path), db, org_id)

    raise ValueError(f"Unsupported file type: {mime_type}")


# ── LLM parsing ─────────────────────────────────────────────────────


def _build_catalog_string(unit_ops: list[UnitOpDefinition]) -> str:
    """Format the unit op catalog as a human-readable bullet list."""
    lines = []
    for op in unit_ops:
        schema_str = ""
        if op.param_schema and op.param_schema.get("properties"):
            props = list(op.param_schema["properties"].keys())
            schema_str = f" (params: {', '.join(props)})"
        lines.append(
            f"- {op.name} [{op.category}]{schema_str}: "
            f"{op.description or 'No description'}"
        )
    return "\n".join(lines) if lines else "(empty catalog)"


async def extract_protocol_skeleton(
    text: str,
    unit_ops: list[UnitOpDefinition],
    db: AsyncSession,
    org_id: UUID | None = None,
) -> ProtocolSkeleton:
    """Agent 1: extract protocol structure — steps, catalog matches, roles, durations."""
    from pydantic_ai import Agent

    catalog = _build_catalog_string(unit_ops)

    system_prompt = f"""You parse biotech protocol documents into a structured step list.

UNIT OPERATION CATALOG:
{catalog}

YOUR ONLY JOB: extract each procedure step and match it to the closest catalog entry.

For EVERY step, set matched_unit_op_name to the EXACT catalog name (copy-paste
including capitalization and spaces). Step names in documents rarely match
catalog names word-for-word — match on MEANING.

Matching examples:
- "Sterile Filtration" -> "Filtration"
- "Seed Cells" -> "Seeding"
- "Transfect Cells" -> "Transfection"
- "Incubate" -> "Incubation"
- "Pre-warm Media" / "Media Change" -> "Media Preparation"
- "Cell Count" / "Assess Transfection" -> "Cell Counting"
- "QC Sampling" -> "Sample Collection"
- "Vial Filling" -> "Fill"
- "Potency Assay" -> "Assay"
- "Column Equilibration" / "Load" / "Wash" / "Elution" -> "Chromatography"
- "Neutralize" / "Adjust pH" -> "pH Adjustment"
- "Lyophilization" -> "Lyophilization"
- "Visual Inspection" -> "Visual Inspection"

Use null ONLY when no catalog entry is semantically related.

ALSO capture per step:
- role: exact role name if mentioned (e.g. "Fill Operator", "QC Inspector"), else null
- duration_min: estimate from text or domain knowledge (integer)
- category: closest category

Do NOT extract parameters yet — that is a separate task. Keep output minimal."""

    model = await get_model("protocol_generation", db, org_id=org_id)
    agent = Agent(
        model,
        system_prompt=system_prompt,
        output_type=ProtocolSkeleton,
        output_retries=3,
    )
    result = await agent.run(
        f"Extract the step structure from this protocol document:\n\n{text}"
    )
    return result.output


async def extract_protocol_params(
    text: str,
    skeleton: ProtocolSkeleton,
    unit_ops: list[UnitOpDefinition],
    db: AsyncSession,
    org_id: UUID | None = None,
) -> ProtocolParams:
    """Agent 2: extract parameters for each step in the skeleton."""
    from pydantic_ai import Agent

    # Build per-step context: for matched steps, include the catalog param schema
    # so the LLM knows exactly which param names/types to extract.
    unit_ops_by_name = {op.name.lower(): op for op in unit_ops}

    step_lines = []
    for idx, step in enumerate(skeleton.steps):
        matched = (
            unit_ops_by_name.get(step.matched_unit_op_name.lower())
            if step.matched_unit_op_name
            else None
        )
        if matched and matched.param_schema and matched.param_schema.get("properties"):
            expected_params = ", ".join(matched.param_schema["properties"].keys())
            step_lines.append(
                f"Step {idx}: {step.name}\n"
                f"  Matched: {matched.name}\n"
                f"  Expected params: {expected_params}"
            )
        else:
            step_lines.append(
                f"Step {idx}: {step.name}\n"
                f"  Matched: none (extract any params you find in the text)"
            )
    step_list = "\n".join(step_lines)

    system_prompt = f"""You extract parameter values from biotech protocol documents.

You will receive a protocol document and a list of already-identified steps.
Your job: for each step, extract the specific parameter values mentioned in
the text (volumes, temperatures, pH, times, reagents, methods, etc.).

For matched steps, focus on extracting the expected param names listed.
For unmatched steps, extract any parameters you can identify.

For EACH parameter, provide:
- name: snake_case (e.g. "volume_L", "target_pH", "cell_density")
- type: "number", "string", or "boolean"
- unit: unit of measurement if applicable (e.g. "mL", "°C", "minutes"), else null
- default: the actual value from the document (number for numbers, string for strings)

Return ONLY the params for each step, keyed by step_index (0-based).
If a step has no extractable params, return an empty params list for it."""

    user_prompt = f"""STEPS:
{step_list}

PROTOCOL DOCUMENT TEXT:
{text}

Extract the parameter values for each step above."""

    model = await get_model("protocol_generation", db, org_id=org_id)
    agent = Agent(
        model,
        system_prompt=system_prompt,
        output_type=ProtocolParams,
        output_retries=3,
    )
    result = await agent.run(user_prompt)
    return result.output


async def parse_protocol_text(
    text: str,
    unit_ops: list[UnitOpDefinition],
    db: AsyncSession,
    org_id: UUID | None = None,
) -> ParsedProtocol:
    """Parse protocol text into structured steps using two sequential LLM agents.

    Agent 1 extracts the step structure (names, catalog matches, roles, durations).
    Agent 2 extracts parameter values for each step.

    Splitting reduces per-call output size and keeps each agent focused on one task.
    """
    # Agent 1: extract skeleton
    skeleton = await extract_protocol_skeleton(text, unit_ops, db, org_id)

    # Agent 2: extract params for each step
    params_result = await extract_protocol_params(text, skeleton, unit_ops, db, org_id)

    # Merge: attach params to each step by index
    params_by_index = {sp.step_index: sp.params for sp in params_result.steps}
    merged_steps = []
    for idx, sk in enumerate(skeleton.steps):
        merged_steps.append(
            ImportedStep(
                name=sk.name,
                description=sk.description,
                category=sk.category,
                duration_min=sk.duration_min,
                params=params_by_index.get(idx, []),
                role=sk.role,
                matched_unit_op_name=sk.matched_unit_op_name,
            )
        )

    return ParsedProtocol(
        protocol_name=skeleton.protocol_name,
        protocol_description=skeleton.protocol_description,
        steps=merged_steps,
    )


# ── Proposal building ───────────────────────────────────────────────


def build_proposal(
    parsed: ParsedProtocol,
    unit_ops: list[UnitOpDefinition],
    source_filename: str,
    source_text: str = "",
) -> ProtocolImportProposal:
    """Build a proposal from parsed protocol, matching against the catalog."""
    steps: list[StepProposal] = []
    matched_count = 0
    unmatched_count = 0

    for step in parsed.steps:
        # Try to match against catalog
        matched_op = None
        if step.matched_unit_op_name:
            matched_op = match_unit_op(step.matched_unit_op_name, unit_ops)

        if matched_op:
            # Use catalog's param_schema and merge params
            param_schema = matched_op.param_schema or {}
            params_dict = {
                p.name: p.default for p in step.params if p.default is not None
            }
            params = extract_params(params_dict, param_schema)
            matched_count += 1

            steps.append(
                StepProposal(
                    name=step.name,
                    description=step.description,
                    category=matched_op.category,
                    duration_min=step.duration_min or 30,
                    params=params,
                    param_schema=param_schema,
                    role=step.role,
                    matched_unit_op_id=str(matched_op.id),
                    matched_unit_op_name=matched_op.name,
                    is_new=False,
                )
            )
        else:
            # Build param_schema from extracted params
            param_schema = build_param_schema_from_params(step.params)
            params_dict = {
                p.name: p.default for p in step.params if p.default is not None
            }
            unmatched_count += 1

            steps.append(
                StepProposal(
                    name=step.name,
                    description=step.description,
                    category=step.category,
                    duration_min=step.duration_min or 30,
                    params=params_dict,
                    param_schema=param_schema,
                    role=step.role,
                    is_new=True,
                )
            )

    return ProtocolImportProposal(
        protocol_name=parsed.protocol_name,
        protocol_description=parsed.protocol_description,
        steps=steps,
        matched_count=matched_count,
        unmatched_count=unmatched_count,
        source_filename=source_filename,
        source_text_preview=source_text[:500] if source_text else "",
    )


# ── Graph building (with swim lanes) ───────────────────────────────


def build_import_graph(
    steps: list[StepProposal],
    user_id: UUID,
    source_filename: str,
) -> dict[str, Any]:
    """Build a protocol graph JSONB from step proposals.

    Creates swim lane nodes for roles and parents unit op nodes
    under their respective lanes.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Collect unique roles and create swim lanes
    role_names: list[str] = []
    for s in steps:
        if s.role and s.role not in role_names:
            role_names.append(s.role)

    lane_map: dict[str, str] = {}  # role_name -> lane node id
    for i, role_name in enumerate(role_names):
        lane_id = f"lane-{uuid4()}"
        lane_map[role_name] = lane_id
        nodes.append(
            {
                "id": lane_id,
                "type": "swimLane",
                "zIndex": -1,
                "position": {"x": 0, "y": i * 220},
                "data": {
                    "label": role_name,
                    "color": ROLE_COLORS[i % len(ROLE_COLORS)],
                    "roleId": lane_id,
                    "orientation": "horizontal",
                },
                "style": "width: 800px; height: 200px;",
            }
        )

    # Create process start nodes + unit op nodes
    x_start = 100
    x_increment = 300
    y_default = 200  # y position for nodes without a role

    # Track x position per lane for layout
    lane_x_counters: dict[str, int] = {name: 0 for name in role_names}
    no_role_counter = 0

    # Insert a processStart node at the root of each lane chain
    # and one for the ungrouped chain (if any steps have no role)
    process_start_nodes: dict[str | None, dict[str, Any]] = {}
    has_ungrouped = any(not s.role for s in steps)

    for role_name in role_names:
        ps_id = f"ps-{uuid4()}"
        lane_id = lane_map[role_name]
        idx = lane_x_counters[role_name]
        lane_x_counters[role_name] += 1
        ps_node: dict[str, Any] = {
            "id": ps_id,
            "type": "processStart",
            "zIndex": 1,
            "position": {"x": x_start + idx * x_increment, "y": 30},
            "parentId": lane_id,
            "width": 220,
            "data": {
                "label": role_name,
                "description": "",
            },
        }
        nodes.append(ps_node)
        process_start_nodes[role_name] = ps_node

    if has_ungrouped:
        ps_id = f"ps-{uuid4()}"
        ps_node = {
            "id": ps_id,
            "type": "processStart",
            "zIndex": 1,
            "position": {"x": x_start + no_role_counter * x_increment, "y": y_default},
            "width": 220,
            "data": {
                "label": "Process",
                "description": "",
            },
        }
        no_role_counter += 1
        nodes.append(ps_node)
        process_start_nodes[None] = ps_node

    # Track the last node per chain for edge creation
    last_node_per_chain: dict[str | None, str] = {
        k: v["id"] for k, v in process_start_nodes.items()
    }

    op_nodes: list[dict[str, Any]] = []
    for step in steps:
        node_id = f"node-{uuid4()}"
        chain_key: str | None = (
            step.role if (step.role and step.role in lane_map) else None
        )

        if step.role and step.role in lane_map:
            lane_id = lane_map[step.role]
            lane_idx = lane_x_counters[step.role]
            lane_x_counters[step.role] += 1
            position = {"x": x_start + lane_idx * x_increment, "y": 30}
            parent_id = lane_id
        else:
            position = {"x": x_start + no_role_counter * x_increment, "y": y_default}
            no_role_counter += 1
            parent_id = None

        node: dict[str, Any] = {
            "id": node_id,
            "type": "unitOp",
            "position": position,
            "data": {
                "label": step.name,
                "unitOpId": step.matched_unit_op_id,
                "category": step.category,
                "description": step.description,
                "duration_min": step.duration_min,
                "params": step.params,
                "paramSchema": step.param_schema,
            },
        }
        if parent_id:
            node["parentId"] = parent_id

        op_nodes.append(node)

        # Create edge from last node in this chain
        if chain_key in last_node_per_chain:
            edges.append(
                {
                    "id": f"edge-{uuid4()}",
                    "source": last_node_per_chain[chain_key],
                    "target": node_id,
                }
            )
        last_node_per_chain[chain_key] = node_id

    nodes.extend(op_nodes)

    return {
        "nodes": nodes,
        "edges": edges,
        "layout": "horizontal",
        "handleOrientation": "horizontal",
        "timeEnabled": False,
        "startTime": "08:00",
        "pixelsPerHour": 150,
        "_metadata": {
            "source": "protocol_import",
            "source_filename": source_filename,
            "generated_by": str(user_id),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ── Refinement (general-purpose) ────────────────────────────────────


async def refine_protocol(
    graph: dict[str, Any],
    instruction: str,
    unit_ops: list[UnitOpDefinition],
    db: AsyncSession,
    org_id: UUID | None = None,
) -> dict[str, Any]:
    """Refine a protocol graph based on a natural language instruction.

    General-purpose: works for imported protocols and existing ones.
    Stateless — the full graph is passed in and returned.
    """
    from pydantic_ai import Agent

    # Serialize current graph steps for the LLM
    step_lines = []
    op_nodes = [n for n in graph.get("nodes", []) if n.get("type") == "unitOp"]
    for i, node in enumerate(op_nodes, 1):
        data = node.get("data", {})
        role_info = ""
        if node.get("parentId"):
            # Find the swim lane to get role name
            for ln in graph.get("nodes", []):
                if ln["id"] == node["parentId"] and ln.get("type") == "swimLane":
                    role_info = f" [Role: {ln['data'].get('label', '?')}]"
                    break
        step_lines.append(
            f"{i}. {data.get('label', '?')} [{data.get('category', 'General')}] "
            f"— {data.get('duration_min', 30)}min{role_info}"
        )
    steps_text = "\n".join(step_lines) if step_lines else "(no steps)"

    # Build catalog
    catalog_lines = []
    for op in unit_ops:
        schema_str = ""
        if op.param_schema and op.param_schema.get("properties"):
            props = list(op.param_schema["properties"].keys())
            schema_str = f" (params: {', '.join(props)})"
        catalog_lines.append(
            f"- {op.name} [{op.category}]{schema_str}: "
            f"{op.description or 'No description'}"
        )
    catalog = "\n".join(catalog_lines) if catalog_lines else "(empty catalog)"

    system_prompt = f"""You are a protocol design assistant. You are helping a scientist
refine a protocol. Below is the current protocol structure. The user will give you an
instruction to modify it. Apply the change and return the updated protocol.

CURRENT PROTOCOL STEPS:
{steps_text}

UNIT OPERATION CATALOG:
{catalog}

RULES:
1. Apply the user's instruction precisely.
2. When adding or modifying steps, match against the catalog when possible.
3. Preserve all unaffected steps exactly as they are.
4. Return the complete updated protocol, not just the changed parts.
5. Set matched_unit_op_name to the exact catalog name when a step matches."""

    model = await get_model("protocol_generation", db, org_id=org_id)
    agent = Agent(model, system_prompt=system_prompt, output_type=ParsedProtocol)

    # Extract current name/description from metadata or graph
    current_name = graph.get("_metadata", {}).get("protocol_name", "Protocol")
    result = await agent.run(
        f"Current protocol: '{current_name}'\n\n" f"User instruction: {instruction}"
    )

    # Rebuild proposal then graph
    proposal = build_proposal(result.output, unit_ops, "")
    return build_import_graph(
        proposal.steps,
        UUID(graph.get("_metadata", {}).get("generated_by", str(uuid4()))),
        graph.get("_metadata", {}).get("source_filename", ""),
    )


# ── Finalization ────────────────────────────────────────────────────


async def finalize_import(
    steps: list[StepProposal],
    protocol_name: str,
    protocol_description: str,
    project_id: UUID | None,
    organization_id: UUID | None,
    user_id: UUID,
    source_filename: str,
    db: AsyncSession,
) -> Protocol:
    """Create unit ops, protocol roles, and the protocol record.

    Args:
        steps: The finalized step proposals.
        protocol_name: Name for the new protocol.
        protocol_description: Description.
        project_id: Target project (mutually exclusive with organization_id).
        organization_id: Target org for org-scoped protocols.
        user_id: User creating the protocol.
        source_filename: Original filename for metadata.
        db: Database session.

    Returns:
        The created Protocol record.
    """
    org_id = organization_id
    if project_id:
        from app.models.projects import Project

        result = await db.execute(
            select(Project.organization_id).where(Project.id == project_id)
        )
        org_id = result.scalar_one_or_none()

    # 1. Create new UnitOpDefinitions for is_new steps
    new_op_map: dict[str, UUID] = {}  # step name -> new unit op id
    for step in steps:
        if step.is_new and step.name not in new_op_map:
            new_op = UnitOpDefinition(
                name=step.name,
                category=step.category,
                description=step.description,
                param_schema=step.param_schema,
                result_schema={},
                organization_id=org_id,
            )
            db.add(new_op)
            await db.flush()
            new_op_map[step.name] = new_op.id

    # Update step proposals with new unit op IDs
    for step in steps:
        if step.is_new and step.name in new_op_map:
            step.matched_unit_op_id = str(new_op_map[step.name])

    # 2. Create ProtocolRoles for unique role names
    role_names = []
    for s in steps:
        if s.role and s.role not in role_names:
            role_names.append(s.role)

    # 3. Build graph
    graph = build_import_graph(steps, user_id, source_filename)

    # 4. Create Protocol record
    protocol = Protocol(
        name=protocol_name,
        description=protocol_description,
        project_id=project_id,
        organization_id=organization_id,
        status="DRAFT",
        graph=graph,
    )
    db.add(protocol)
    await db.flush()

    # 5. Create ProtocolRole DB records
    for i, role_name in enumerate(role_names):
        role = ProtocolRole(
            protocol_id=protocol.id,
            name=role_name,
            color=ROLE_COLORS[i % len(ROLE_COLORS)],
            sort_order=i,
        )
        db.add(role)

    await db.flush()
    return protocol
