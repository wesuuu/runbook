#!/usr/bin/env python3
"""Manual test script for context window compaction.

Builds a synthetic long conversation, runs compact_history() with the
real LLM, and prints the summary + token stats.

Usage:
    cd backend
    source .venv/bin/activate
    python scripts/test_compaction.py
"""
import asyncio
import json
import uuid

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.ai.ai_config import get_context_window, get_model
from app.services.ai.chat_service import (
    compact_history,
    estimate_messages_tokens,
    estimate_tokens,
)


def _build_synthetic_history(num_exchanges: int = 30) -> list:
    """Build a synthetic pydantic-ai style message history."""
    messages = []

    topics = [
        ("What media should I use for CHO cell culture?",
         "For CHO cell culture, I recommend CD CHO medium from Thermo Fisher. It's chemically defined and supports high cell density growth."),
        ("What's the optimal seeding density?",
         "Typical seeding density for CHO cells is 0.3-0.5 x 10^6 cells/mL. This allows for 3-4 day growth before passage."),
        ("How often should I passage?",
         "Passage every 3-4 days when cells reach 80-90% confluence, or 3-4 x 10^6 cells/mL in suspension."),
        ("What temperature and CO2 levels?",
         "Maintain at 37C with 5-8% CO2. Some protocols use temperature shift to 33C during production phase."),
        ("Tell me about fed-batch vs perfusion",
         "Fed-batch: simpler, add nutrients periodically, harvest at end. Perfusion: continuous feed/harvest, higher productivity but more complex equipment."),
        ("What supplements do I need?",
         "Key supplements: L-glutamine (or GlutaMAX), anti-clumping agent, and potentially insulin-like growth factor."),
        ("How do I measure viability?",
         "Use trypan blue exclusion with an automated cell counter. Target >90% viability for healthy cultures."),
        ("What about mycoplasma testing?",
         "Test every 2-4 weeks using PCR-based assays. Mycoplasma contamination is common and can severely affect results."),
        ("Can you help me design a scale-up protocol?",
         "For scale-up from flask to bioreactor: maintain same kLa, impeller tip speed, and nutrient feed ratios. Start at 2L working volume."),
        ("What analytics should I run during production?",
         "Key analytics: cell count/viability daily, glucose/lactate, pH, osmolality, and product titer via ELISA or Protein A HPLC."),
    ]

    for i in range(num_exchanges):
        topic = topics[i % len(topics)]
        user_content, assistant_content = topic

        # Add variation
        if i > len(topics):
            user_content = f"Follow-up #{i}: {user_content}"
            assistant_content = f"Building on our earlier discussion: {assistant_content} Additionally, consider parameter optimization for your specific cell line."

        messages.append({
            "kind": "request",
            "parts": [
                {
                    "part_kind": "user-prompt",
                    "content": user_content,
                    "timestamp": f"2026-03-27T{10 + i // 6:02d}:{(i * 10) % 60:02d}:00Z",
                }
            ],
            "timestamp": None,
            "instructions": None,
            "run_id": None,
            "metadata": None,
        })
        messages.append({
            "kind": "response",
            "parts": [
                {
                    "part_kind": "text",
                    "content": assistant_content,
                    "id": None,
                    "provider_name": None,
                    "provider_details": None,
                }
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_write_tokens": 0,
                "cache_read_tokens": 0,
            },
            "model_name": "test-model",
            "timestamp": f"2026-03-27T{10 + i // 6:02d}:{(i * 10) % 60 + 1:02d}:00Z",
            "provider_name": None,
            "provider_url": None,
            "provider_details": None,
            "provider_response_id": None,
            "finish_reason": None,
            "run_id": None,
            "metadata": None,
        })

    return messages


async def main():
    print("=" * 60)
    print("Context Window Compaction Test")
    print("=" * 60)

    async with AsyncSessionLocal() as db:
        # Get model config
        from sqlalchemy import select, text
        from app.models.iam import Organization

        from app.models.iam import User

        result = await db.execute(select(Organization).limit(1))
        org = result.scalar_one_or_none()
        if not org:
            print("ERROR: No organizations found in DB. Run seed script first.")
            return

        user_result = await db.execute(select(User).limit(1))
        user = user_result.scalar_one_or_none()
        if not user:
            print("ERROR: No users found in DB. Run seed script first.")
            return

        org_id = org.id
        context_window = await get_context_window("chat", db, org_id=org_id)
        model = await get_model("chat", db, org_id=org_id)
        budget = int(context_window * settings.compaction_threshold)

        print(f"\nModel: {model}")
        print(f"Context window: {context_window:,} tokens")
        print(f"Compaction threshold: {settings.compaction_threshold}")
        print(f"Token budget: {budget:,} tokens")

        # Build synthetic history (small for quick local testing)
        messages = _build_synthetic_history(num_exchanges=10)
        total_tokens_before = estimate_messages_tokens(messages)

        print(f"\n--- Before Compaction ---")
        print(f"Messages: {len(messages)}")
        print(f"Estimated tokens: {total_tokens_before:,}")
        print(f"Over budget: {total_tokens_before > budget}")

        # For testing, use a smaller budget to force compaction
        test_budget = min(budget, 1500)
        print(f"\nUsing test budget of {test_budget:,} tokens to force compaction")
        budget = test_budget

        # Create a temporary session for the test
        from app.models.chat import ChatSession, ChatSessionStatus
        session = ChatSession(
            user_id=user.id,
            org_id=org_id,
            title="Compaction Test",
            status=ChatSessionStatus.ACTIVE,
        )
        db.add(session)
        await db.flush()

        print(f"\n--- Running Compaction ---")
        try:
            compacted, summary_text = await compact_history(
                db=db,
                session_id=session.id,
                messages=messages,
                token_budget=budget,
                model=model,
                org_id=org_id,
            )

            total_tokens_after = estimate_messages_tokens(compacted)

            print(f"\n--- After Compaction ---")
            print(f"Messages: {len(compacted)}")
            print(f"Estimated tokens: {total_tokens_after:,}")
            print(f"Reduction: {total_tokens_before - total_tokens_after:,} tokens "
                  f"({(1 - total_tokens_after / total_tokens_before) * 100:.1f}%)")

            if summary_text:
                print(f"\n--- Summary ({estimate_tokens(summary_text):,} tokens) ---")
                print(summary_text)
            else:
                print("\nNo summary generated (history was under budget).")

        except Exception as e:
            print(f"\nERROR: Compaction failed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Clean up — rollback the temp session
            await db.rollback()

    print("\n" + "=" * 60)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
