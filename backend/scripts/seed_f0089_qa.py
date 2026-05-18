"""Seed an INDEXED Document + chunks for F-0089 browser QA.

Usage:
    cd backend && source .venv/bin/activate && python scripts/seed_f0089_qa.py

The script targets the dev DB, finds the first organization (or the one
specified via --org-id), picks a member of that org as `uploaded_by_id`,
and inserts one Document with status=INDEXED plus three chunks with
deterministic embeddings. Idempotent: re-running deletes the previous
seed document with the same title before reseeding.
"""

import argparse
import asyncio

from sqlalchemy import select

# Import every model module so SQLAlchemy can resolve cross-module
# relationship() string references (e.g. Organization -> Project) when
# the script is invoked standalone (FastAPI app startup normally does
# this transitively).
from app import models  # noqa: F401
from app.db.session import AsyncSessionLocal
from app.models import (  # noqa: F401
    ai,
    batch_record_import,
    billing,
    chat,
    execution,
    iam,
    jobs,
    library,
    notifications,
    offline,
    science,
    templates,
)
from app.models.iam import Organization, OrganizationMember, User
from app.models.library import (
    EMBEDDING_DIMENSIONS,
    Document,
    DocumentChunk,
    DocumentStatus,
)

SEED_TITLE = "[QA F-0089] Lyophilization SOP v2"
SEED_CHUNKS = [
    "Pre-freeze the sample at -40C for 2 hours before applying vacuum.",
    "Set shelf temperature to -25C during primary drying for 8 hours.",
    "Ramp to +20C for secondary drying. Hold for 4 hours before stoppering.",
]


async def main(org_id: str | None) -> None:
    async with AsyncSessionLocal() as db:
        if org_id is None:
            org = (await db.execute(select(Organization).limit(1))).scalar_one()
            org_id = str(org.id)

        # Find a user that is a member of this org for uploaded_by_id.
        member = (
            await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id
                ).limit(1)
            )
        ).scalar_one_or_none()
        if member is not None:
            uploaded_by_id = member.user_id
        else:
            # Fallback: any user in the system.
            uploaded_by_id = (
                await db.execute(select(User).limit(1))
            ).scalar_one().id

        # Idempotency: remove any prior seed doc with the same title in this org.
        prior = (
            await db.execute(
                select(Document).where(
                    Document.org_id == org_id, Document.title == SEED_TITLE
                )
            )
        ).scalars().all()
        for d in prior:
            await db.delete(d)
        await db.flush()

        doc = Document(
            org_id=org_id,
            uploaded_by_id=uploaded_by_id,
            title=SEED_TITLE,
            original_filename="qa_f0089_lyophilization_sop_v2.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            file_path="qa-fixtures/f0089/lyophilization_sop_v2.pdf",
            status=DocumentStatus.INDEXED.value,
        )
        db.add(doc)
        await db.flush()

        for i, content in enumerate(SEED_CHUNKS):
            # Deterministic embedding: alternate magnitudes per chunk so they
            # are not identical and the vector index can rank them.
            magnitude = 0.1 if i % 2 == 0 else 0.05
            embedding = [magnitude] * EMBEDDING_DIMENSIONS
            db.add(
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=i,
                    content=content,
                    token_count=len(content.split()),
                    embedding=embedding,
                )
            )

        await db.commit()
        print(
            f"Seeded {SEED_TITLE} ({len(SEED_CHUNKS)} chunks) into org {org_id}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--org-id", default=None, help="Override target org UUID"
    )
    args = parser.parse_args()
    asyncio.run(main(args.org_id))
