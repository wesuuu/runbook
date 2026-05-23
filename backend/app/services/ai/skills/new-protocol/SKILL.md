---
name: new-protocol
description: Create a new protocol grounded in a source you pick — your library, external repositories (OpenWetWare, protocols.io), scratch, or all of the above.
icon: file-plus
---

# Create a new protocol

When invoked, you orchestrate a new-protocol creation flow.

## Step 1 — Detect an implicit source choice, otherwise ask

Before asking the picker question, scan the user's most recent message for an unambiguous source hint and route directly. **Direct-routing signals are HIGHEST PRIORITY — showing the picker after the user has named a source is a workflow violation.** Apply this routing table in order:

- Mentions "OpenWetWare", "OWW", "protocols.io", "protocols io", "the web", "external sources", "online protocols", "public protocols", "from the internet" → **External repositories** route. You MUST dispatch `task("protocol_knowledgebase", "<topic>")` immediately. The subagent picks the best source (OpenWetWare or protocols.io) for the query. Do NOT show the picker. Do NOT ask which source they want — they already told you.
- Mentions "my library", "our library", "the library", "indexed documents", a specific library doc title, or asks you to "use my docs" / "use our SOPs" → **Library** route. You MUST dispatch `task("research_library", "<topic>")` immediately. Do NOT show the picker.
- Mentions "from scratch", "no documents", "without any source", "draft one yourself", or "don't use the library" → **From scratch** route. You MUST dispatch `task("protocol_creator", "<topic>")` immediately. Do NOT show the picker.
- Mentions "search all", "try everything", "look everywhere", "any source" → **Search all** route. Skip the picker.
- Otherwise the intent is ambiguous. Reply with exactly these four options as a numbered list, then stop and wait for their reply:

1. **Library** — ground the protocol on the org's indexed research library.
2. **External repositories** — search OpenWetWare and protocols.io (requires approval before any external content is used).
3. **From scratch** — draft without any source.
4. **Search all** — try the library first, fall back to OpenWetWare if nothing relevant is found.

## Step 2 — Route based on the user's reply

The three explicit options are hard-scoped. Library does not silently escalate to OpenWetWare or scratch.

### Library

1. Dispatch `task("research_library", "<the topic the user wants to create a protocol for>")`. Use `search_documents` semantics.
2. If `research_library` returns **zero relevant chunks**, do NOT fall through. Reply: *"No matching library documents. Want me to run Search all instead?"* and stop. Wait for the user. Empty means the retrieval tool returned no results — never discard hits because they look uninteresting.
3. If results came back, **you MUST immediately dispatch `task("protocol_creator", "<brief>")` as your very next action**. Do not ask the user any clarifying question between research_library and protocol_creator — gaps (vacuum pressure, container type, fill volume, sample identity, etc.) are protocol_creator's responsibility to raise, not the parent's. Skipping the protocol_creator dispatch is a workflow violation, even if you think you have enough context. The brief includes a `grounding:` section listing the document titles and chunk text returned by research_library. **When you surface protocol_creator's output back to the user — whether it's a finished protocol, a clarifying question, or anything else — the first sentence of your reply MUST name the library document(s) that grounded the work** (e.g. *"Based on **[QA F-0089] Lyophilization SOP v2** from your library — …"*). This is non-negotiable: the user needs to see what document drove the draft, even when the subagent has follow-up questions. The brief format:

   ```
   <user's original topic>

   grounding:
   - title: <doc_title_1>
     chunks:
       - <chunk_text_1>
       - <chunk_text_2>
   - title: <doc_title_2>
     chunks:
       - <chunk_text_3>
   ```

### OpenWetWare

Existing F-0084/F-0090 flow. Dispatch `task("protocol_knowledgebase", "<topic>")`. The subagent searches OpenWetWare and protocols.io and surfaces an approval card; on approval, the parent calls `create_protocol_from_external_source`. Empty external result → reply: *"No matching external protocols. Want me to run Search all instead?"* and stop.

### From scratch

Dispatch `task("protocol_creator", "<the user's topic, no grounding section>")` directly. Do not invoke research_library or protocol_knowledgebase.

### Search all (the heuristic home)

1. Dispatch `task("research_library", "<topic>")`.
2. If zero results, dispatch `task("protocol_knowledgebase", "<topic>")` (F-0084 HITL).
3. If both empty, dispatch `task("protocol_creator", "<topic>")` from scratch.
4. Otherwise dispatch `task("protocol_creator", "<brief with grounding section>")` using whichever source returned content.

Future heuristics (topic-routing, multi-source merging) live here. The three explicit options stay predictable.

## Citation contract

When `protocol_creator` returns a created protocol, the protocol's description already contains the citation footer (it appends it itself). Do not add a second citation block. Just present the protocol to the user.
