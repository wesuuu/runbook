"""list_awaiting_for_user must ignore run-scoped GlpSignoffRequest rows (F-0080)."""

import pytest

from app.models.runs import Run
from app.models.signoffs import GlpSignoffRequest
from app.services.approvals.awaiting import list_awaiting_for_user


@pytest.mark.asyncio
async def test_awaiting_ignores_run_request(db_session, test_project, test_user):
    """A run-scoped request assigned to the user must not surface as a
    protocol approval item.

    test_user has no submitted protocols awaiting approval, so the only way
    `items` becomes non-empty is if the run request leaks — which the
    `protocol_id IS NOT NULL` scoping (explicit after Step 3, implicit
    before) must prevent. `assert items == []` fails loudly on a leak.
    """
    run = Run(name="R", project_id=test_project.id, graph={}, execution_data={})
    db_session.add(run)
    await db_session.flush()
    db_session.add(
        GlpSignoffRequest(
            run_id=run.id, role="QAU", status="OPEN",
            requested_user_id=test_user.id,
        )
    )
    await db_session.flush()

    items = await list_awaiting_for_user(db_session, test_user.id)
    assert items == []
    # Belt-and-suspenders: no item may carry a NULL protocol_id.
    assert all(item["protocol_id"] is not None for item in items)
