---
name: new-protocol
description: Create a new protocol grounded in a source you pick — your library, OpenWetWare, scratch, or all of the above.
icon: file-plus
---

# Create a new protocol

When invoked, you orchestrate a new-protocol creation flow. Do NOT dispatch any subagent until the user has explicitly chosen a source.

## Step 1 — Ask the user to pick a source

Reply with exactly these four options as a numbered list, then stop and wait for their reply:

1. **Library** — ground the protocol on the org's indexed research library.
2. **OpenWetWare** — search the public OpenWetWare knowledgebase (requires approval before any external content is used).
3. **From scratch** — draft without any source.
4. **Search all** — try the library first, fall back to OpenWetWare if nothing relevant is found.

## Step 2 — Route based on the user's reply

The three explicit options are hard-scoped. Library does not silently escalate to OpenWetWare or scratch.

### Library

1. Dispatch `task("research_library", "<the topic the user wants to create a protocol for>")`. Use `search_documents` semantics.
2. If `research_library` returns **zero relevant chunks**, do NOT fall through. Reply: *"No matching library documents. Want me to run Search all instead?"* and stop. Wait for the user. Empty means the retrieval tool returned no results — never discard hits because they look uninteresting.
3. If results came back, dispatch `task("protocol_creator", "<brief>")` with a brief that includes a `grounding:` section listing the document titles and chunk text returned by research_library. The brief format:

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

Existing F-0084 flow. Dispatch `task("protocol_knowledgebase", "<topic>")`. The subagent surfaces an approval card; on approval, the parent calls `create_protocol_from_external_source`. Empty external result → reply: *"No matching OpenWetWare protocols. Want me to run Search all instead?"* and stop.

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
