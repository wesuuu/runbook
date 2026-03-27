"""Interactive test script for the chat agent protocol generation flow.

Tests the full multi-turn conversation:
1. Search library for buffer formulations
2. Ask agent to find a specific formulation
3. Tell it to create a protocol based on it
4. Verify it outlines steps and asks about parameters one at a time
5. Verify it actually creates the protocol after confirmation

Usage:
    cd backend && source .venv/bin/activate
    python scripts/test_chat_agent.py
"""

import asyncio
import json
import sys
import re
from uuid import UUID

# Add parent dir to path
sys.path.insert(0, ".")

from app.db.session import AsyncSessionLocal
from app.services.chat_service import (
    create_session,
    send_message,
    get_session,
)

ORG_ID = UUID("10000000-0000-0000-0000-000000000001")
USER_ID = UUID("20000000-0000-0000-0000-000000000001")

# Test conversation steps
CONVERSATION = [
    {
        "msg": "What documents do you have about buffer or media preparation?",
        "check": lambda resp, tc: (
            any(t.get("tool") in ("search_documents", "list_documents") for t in tc),
            "Should call search_documents or list_documents"
        ),
    },
    {
        "msg": "Can you look up how to prepare a PBS buffer? There should be something in the library about it.",
        "check": lambda resp, tc: (
            any(t.get("tool") == "search_documents" for t in tc),
            "Should call search_documents for PBS"
        ),
    },
    {
        "msg": "Let's create a protocol for preparing PBS buffer based on what you found.",
        "check": lambda resp, tc: (
            any(t.get("tool") == "load_skill" for t in tc)
            or "step" in resp.lower()
            or "scale" in resp.lower()
            or "what" in resp.lower(),
            "Should load generate-protocol skill OR start asking about the process"
        ),
    },
    {
        "msg": "Lab scale, about 1 liter.",
        "check": lambda resp, tc: (
            "?" in resp,
            "Should ask a follow-up question (one at a time)"
        ),
    },
    {
        "msg": "Yes, that looks right. Please create it in the Bioprocess Alpha project.",
        "check": lambda resp, tc: (
            any(t.get("tool") == "create_protocol" for t in tc)
            or "created" in resp.lower()
            or "draft" in resp.lower()
            or "confirm" in resp.lower()
            or "project" in resp.lower(),
            "Should create the protocol or ask for final confirmation"
        ),
    },
]

# Quality checks applied to ALL responses
QUALITY_CHECKS = [
    (
        lambda resp: "<think>" not in resp,
        "FAIL: Thought leakage — <think> tags in response"
    ),
    (
        lambda resp: not re.search(r'[\{\[]\s*"[a-z_]+"\s*:', resp),
        "WARN: Raw JSON in response (should be readable text)"
    ),
    (
        lambda resp: len(resp) < 5000,
        "WARN: Response too long (>5000 chars) — may be dumping"
    ),
]


def check_quality(resp: str, step: int) -> list[str]:
    issues = []
    for check_fn, msg in QUALITY_CHECKS:
        if not check_fn(resp):
            issues.append(f"  Step {step}: {msg}")
    return issues


async def run_test(attempt: int):
    print(f"\n{'='*60}")
    print(f"ATTEMPT {attempt}")
    print(f"{'='*60}")

    async with AsyncSessionLocal() as db:
        # Create session
        session = await create_session(db, USER_ID, ORG_ID, title="Protocol Test")
        await db.commit()
        session = await get_session(db, session.id)

        all_issues = []
        step_results = []

        for i, step in enumerate(CONVERSATION, 1):
            print(f"\n--- Step {i}: {step['msg'][:60]}... ---")

            try:
                user_msg, asst_msg, sources = await send_message(
                    db, session, step["msg"],
                    user_id=USER_ID,
                    is_org_admin=True,
                )
                await db.commit()
                session = await get_session(db, session.id)
            except Exception as e:
                print(f"  ERROR: {e}")
                step_results.append(("ERROR", str(e)))
                break

            resp = asst_msg.content
            tc = (asst_msg.metadata_ or {}).get("tool_calls", [])

            # Show response summary
            print(f"  Response ({len(resp)} chars): {resp[:200]}...")
            if tc:
                print(f"  Tool calls: {[t.get('tool') for t in tc]}")
            if sources:
                print(f"  Sources: {len(sources)}")

            # Step-specific check
            passed, reason = step["check"](resp, tc)
            status = "PASS" if passed else "FAIL"
            print(f"  Check: {status} — {reason}")
            step_results.append((status, reason))

            # Quality checks
            issues = check_quality(resp, i)
            all_issues.extend(issues)
            for issue in issues:
                print(issue)

        # Cleanup
        from app.services.chat_service import delete_session
        session = await get_session(db, session.id)
        if session:
            await delete_session(db, session)
            await db.commit()

        # Summary
        print(f"\n--- ATTEMPT {attempt} SUMMARY ---")
        for i, (status, reason) in enumerate(step_results, 1):
            print(f"  Step {i}: {status} — {reason}")
        if all_issues:
            print("  Quality issues:")
            for issue in all_issues:
                print(f"    {issue}")

        passed_count = sum(1 for s, _ in step_results if s == "PASS")
        total = len(step_results)
        print(f"  Score: {passed_count}/{total}")

        return passed_count, total, step_results, all_issues


async def main():
    max_attempts = 3  # Start with 3, increase if needed
    best_score = 0
    best_attempt = 0

    for attempt in range(1, max_attempts + 1):
        passed, total, results, issues = await run_test(attempt)
        score = passed / total if total > 0 else 0

        if score > best_score:
            best_score = score
            best_attempt = attempt

        if passed == total and not any("FAIL" in i for i in issues):
            print(f"\n*** ALL CHECKS PASSED on attempt {attempt}! ***")
            return

        print(f"\n  Best so far: attempt {best_attempt} ({best_score:.0%})")

    print(f"\n{'='*60}")
    print(f"FINAL: Best score {best_score:.0%} on attempt {best_attempt}")
    if best_score < 0.6:
        print("CONCLUSION: Model is not following instructions reliably.")
        print("Consider: stronger model, simplified prompt, or fewer tool choices.")
    elif best_score < 1.0:
        print("CONCLUSION: Partial success — prompt may need further tuning.")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
