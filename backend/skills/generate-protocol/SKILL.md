---
name: generate-protocol
description: Generate a structured protocol step-by-step
icon: flask-conical
---

# Generate Protocol

Follow these steps IN ORDER. Ask ONE question per message.

STEP 1: Ask "What type of process?" Wait for answer.
STEP 2: Ask "What scale?" Wait for answer.
STEP 3: Ask "Base this on a library document?" If yes, search. If no, continue.
STEP 4: Call list_unit_ops(). DO NOT show the results. Use the names internally.
STEP 5: Propose step 1 of the protocol: "For step 1, I suggest [name] — [brief description]. Does that work?"
STEP 6: After confirmation, propose step 2. Repeat until done.
STEP 7: Show numbered summary of all steps. Ask "Which project should I create this in?"
STEP 8: Call create_protocol() with the confirmed steps.

CRITICAL: After calling tools, DO NOT dump or summarize the tool results. Use them silently to propose the next protocol step.
