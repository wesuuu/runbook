"""One-shot codemod (TD-0083): rewrite imports off the `science` umbrella.

Run from backend/:  python scripts/split_science_imports.py
Deleted once TD-0083 lands.
"""

from __future__ import annotations

import ast
from pathlib import Path

MODELS = {
    "Protocol": "protocols",
    "ProtocolRole": "protocols",
    "ProtocolVersion": "protocols",
    "UnitOpDefinition": "protocols",
    "UnitOpLibrarySubscription": "protocols",
    "Run": "runs",
    "RunStatus": "runs",
    "RunRoleAssignment": "runs",
    "RunOutcome": "runs",
    "Experiment": "runs",
    "ExperimentStatus": "runs",
    "Project": "projects",
    "Equipment": "equipment",
    "EquipmentAttachment": "equipment",
    "EquipmentStatus": "equipment",
    "Site": "sites",
    "SiteManagerGrant": "sites",
    "GlpSignoff": "signoffs",
    "GlpSignoffRequest": "signoffs",
    "GlpRole": "signoffs",
    "GlpSignoffAction": "signoffs",
    "GlpSignoffRequestStatus": "signoffs",
}
SCHEMAS = {
    **{
        n: "protocols"
        for n in (
            "UnitOpDefinitionBase",
            "UnitOpDefinitionCreate",
            "UnitOpDefinitionUpdate",
            "UnitOpDefinitionResponse",
            "ProtocolRoleBase",
            "ProtocolRoleCreate",
            "ProtocolRoleUpdate",
            "ProtocolRoleResponse",
            "ProtocolBase",
            "ProtocolCreate",
            "ProtocolUpdate",
            "ProtocolResponse",
            "ProtocolVersionListItem",
            "ProtocolVersionResponse",
            "PublishDraftRequest",
            "DesignateApprovalRequest",
            "SubmitForApprovalRequest",
            "ApproveProtocolRequest",
            "RejectProtocolRequest",
            "ApprovalActorRef",
            "AwaitingApprovalItem",
            "GraphPayload",
            "StepProposalSchema",
            "ProtocolImportProposalResponse",
            "ProtocolRefineRequest",
            "ProtocolImportFinalizeRequest",
        )
    },
    **{
        n: "runs"
        for n in (
            "ExperimentStatus",
            "ExperimentNote",
            "ExperimentNoteCreate",
            "ExperimentNoteListResponse",
            "ExperimentCreate",
            "ExperimentUpdate",
            "ExperimentResponse",
            "RunStatus",
            "RunNote",
            "RunNoteCreate",
            "RunNoteListResponse",
            "RunAttachment",
            "RunAttachmentListResponse",
            "RunBase",
            "RunCreate",
            "RunUpdate",
            "RunStateUpdate",
            "RunStepStateUpdate",
            "RunResponse",
            "NodeOverrides",
            "RunOverrides",
            "SuggestLotNumberRequest",
            "SuggestLotNumberResponse",
            "CheckLotNumberResponse",
            "RunRoleAssignmentBase",
            "RunRoleAssignmentCreate",
            "RunRoleAssignmentResponse",
            "RunRoleAssignmentListResponse",
            "RunCompleteRequest",
            "RunReopenRequest",
        )
    },
    **{n: "signoffs" for n in ("GlpSignoffCreate", "GlpSignoffResponse")},
}
MAPS = {
    "app.models.science": ("app.models", MODELS),
    "app.schemas.science": ("app.schemas", SCHEMAS),
}
ROOT = Path(__file__).resolve().parent.parent  # backend/


def rewrite(path: Path) -> bool:
    src = path.read_text()
    if "science" not in src:
        return False
    lines = src.splitlines(keepends=True)
    edits = []  # (start_idx, end_idx, replacement)
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        indent = " " * node.col_offset
        if node.module.startswith("app.services.science"):
            new_mod = node.module.replace(
                "app.services.science", "app.services.protocols", 1
            )
            names = ", ".join(
                a.name + (f" as {a.asname}" if a.asname else "") for a in node.names
            )
            edits.append(
                (
                    node.lineno - 1,
                    node.end_lineno,
                    f"{indent}from {new_mod} import {names}\n",
                )
            )
        elif node.module in MAPS:
            base, table = MAPS[node.module]
            groups: dict[str, list[str]] = {}
            for a in node.names:
                if a.name not in table:
                    raise SystemExit(
                        f"{path}:{node.lineno}: unmapped symbol "
                        f"{a.name!r} from {node.module}"
                    )
                spec = a.name + (f" as {a.asname}" if a.asname else "")
                groups.setdefault(table[a.name], []).append(spec)
            edits.append(
                (
                    node.lineno - 1,
                    node.end_lineno,
                    "".join(
                        f"{indent}from {base}.{mod} import {', '.join(sorted(s))}\n"
                        for mod, s in sorted(groups.items())
                    ),
                )
            )
    if not edits:
        return False
    for start, end, repl in sorted(edits, reverse=True):
        lines[start:end] = [repl]
    path.write_text("".join(lines))
    return True


def main() -> None:
    changed = 0
    for path in sorted(ROOT.rglob("*.py")):
        if any(p in path.parts for p in (".venv", "__pycache__")):
            continue
        if path.name == "split_science_imports.py":
            continue
        if rewrite(path):
            changed += 1
            print(f"rewrote {path.relative_to(ROOT)}")
    print(f"\n{changed} files changed")


if __name__ == "__main__":
    main()
