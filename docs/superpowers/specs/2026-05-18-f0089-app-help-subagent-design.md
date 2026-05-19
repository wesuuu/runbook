# F-0089 App Help Subagent — Design

**Status:** Design approved 2026-05-18, awaiting implementation plan.
**ClickUp:** [F-0089] App Help Subagent — In-App Product Q&A from Curated User Guide (`86e1ef8k3`).
**Effort:** XL (~2 days with corpus authoring and page-context awareness).

## Goal

Give the global chat agent grounded knowledge of Batchrite itself — how features work, where pages live, what concepts mean, how to troubleshoot common settings. Today the chat agent can search org documents (`research_library`), search OpenWetWare (`protocol_knowledgebase`), and edit protocols (`protocol_editor`/`protocol_creator`), but it has no grounded knowledge of the product, so users asking "how do I create a protocol?" or "what's the difference between an Experiment and a Run?" get hallucinated or generic answers.

The fix is a new `app_help` subagent grounded in a curated in-repo Markdown corpus under `docs/user-guide/`, plus page-context awareness so the chat agent knows which route the user is currently viewing.

## Non-goals

- In-product UI changes beyond passing the current route (no "ask about this page" button — the chat FAB already exists).
- Screenshots in the corpus.
- Multi-language support.
- Indexing user-uploaded org documents (that's `research_library`'s job).
- Retrieval engine (BM25 / embeddings) — see "Approach" for why the LLM does retrieval directly via filesystem tools.

## Approach

**Subagent + filesystem tools, no retrieval engine, no embeddings.**

The corpus is small (~15-25 curated pages), authored by us, and lives in the repo as Markdown. The subagent gets two tools:

- `list_user_guide_pages()` returns each page's frontmatter (filename, title, summary, keywords) — a cheap index the model uses to pick what to read.
- `read_user_guide_page(filename)` reads one file.

The model picks the relevant page from the index, reads it, answers with a citation. No DB, no embedding spend, no chunking, no migration. Adding a page is dropping a file in `docs/user-guide/` — discoverable on the next tool call (the agent is cached, the tool reads disk on each call).

**Why not stuff the full corpus into the system prompt?** Considered. It works for v1 (~10-15K tokens) but adds latency and cost on every help question and hits a ceiling around 50-100 pages. Filesystem tools cost one extra round-trip and scale.

**Why not BM25 / embeddings?** Considered. Both are YAGNI at this corpus size — the LLM is smart enough to pick from a structured index of 25 pages. Swap in retrieval *behind the same subagent boundary* if the corpus or latency demands it.

**Why a separate subagent rather than tools on the parent?** Matches the existing pattern (`protocol_knowledgebase`, `research_library`). Keeps the parent's tool surface small. Lets `description` drive routing automatically.

## Components

### 1. Corpus — `docs/user-guide/`

```
docs/user-guide/
├── README.md                    # human-facing index, explains the help subagent
├── getting-started.md
├── protocols-and-editor.md
├── experiments-and-runs.md
├── library-and-documents.md
├── chat-agent.md
├── glp-and-signoffs.md
├── ai-configuration.md
├── org-roles-permissions.md
├── sites-and-equipment.md
└── … (one .md per verified-shipped feature surface; see Phase 1)
```

Each page begins with YAML frontmatter:

```yaml
---
title: Protocols and the protocol editor
summary: How to create, edit, and validate protocols using the visual editor.
keywords: [protocol, editor, swimlane, unit op, graph]
---
```

End-user voice — second person ("You can…"), no developer jargon, no internal file paths in user-facing prose. This corpus is distinct from `.claude/rules/` and `CLAUDE.md` (developer-facing) and from user-uploaded library documents (org-scoped data).

Pages are ~150-400 words. Markdown headings are fine; the model reads the whole body.

### 2. Subagent package — `backend/app/services/ai/subagents/app_help/`

```
app_help/
├── __init__.py
├── config.py        # build(model) -> SubAgentConfig
├── prompt.md        # ~30 lines, end-user-tone instructions
└── tools.py         # list_user_guide_pages, read_user_guide_page, TOOL_LABELS
```

**`config.py`** mirrors `protocol_knowledgebase/config.py`:

```python
SubAgentConfig(
    name="app_help",
    description=(
        "Answers questions about Batchrite itself — how features work, "
        "where to find things, what terms mean, troubleshooting. "
        "Dispatch when the user asks 'how do I…', 'what is…', 'where is…', "
        "'why can't I…' about the product. Does NOT answer questions about "
        "the user's data (uploaded docs, protocols, runs) — those route to "
        "research_library or the protocol/run tools."
    ),
    instructions=_PROMPT_PATH.read_text(),
    model=model,
    typically_needs_context=False,
    agent_kwargs={
        "model_settings": CHAT_AGENT_MODEL_SETTINGS,
        "tools": [list_user_guide_pages, read_user_guide_page],
    },
)
```

`typically_needs_context=False` because help questions are usually self-contained ("how do I create a protocol?") and don't need the conversation history. The framework can opt in per-call when context matters.

**`tools.py`** — dataclass results, recoverable errors (no raises), path-traversal guards:

```python
@dataclass
class UserGuidePageMeta:
    filename: str
    title: str
    summary: str
    keywords: list[str]

@dataclass
class ListUserGuidePagesResult:
    total: int
    pages: list[UserGuidePageMeta]

@dataclass
class ReadUserGuidePageResult:
    filename: str
    title: str
    content: str             # body, frontmatter stripped
    error: str | None = None

async def list_user_guide_pages(ctx: RunContext[ChatDeps]) -> ListUserGuidePagesResult: ...
async def read_user_guide_page(ctx: RunContext[ChatDeps], filename: str) -> ReadUserGuidePageResult: ...

TOOL_LABELS = {
    "list_user_guide_pages": "Looking up help topics…",
    "read_user_guide_page": "Reading help page…",
}
```

**Path safety in `read_user_guide_page`:**

- Accept bare filename only — reject inputs containing `/`, `\`, `..`, or null bytes.
- Require `.md` extension.
- Resolve under `Path(settings.user_guide_dir).resolve()`; verify the resolved path is a child of that root.
- On any violation, return an `error` field rather than raising — same recovery shape as `fetch_openwetware_protocol` so the model can try a different filename instead of killing the run.

**Module-level cache for `list_user_guide_pages`:** parse each file's frontmatter once, cache keyed by mtime, invalidate when mtime changes. ~25 small files = sub-millisecond scan even uncached, so the cache is comfort more than necessity.

**`prompt.md`** (sketch):

```
You answer questions about Batchrite, a Laboratory Execution System for
biotech process development.

To answer:
1. Call list_user_guide_pages to see what topics exist.
2. Read the page(s) most relevant to the question.
3. Answer concisely in end-user voice — no code, no jargon unless the
   page uses it.
4. Cite each page you read at the end:

     Sources:
     - [Protocols and the protocol editor](docs/user-guide/protocols-and-editor.md)

If list_user_guide_pages returns nothing relevant, or you read a page
and it doesn't answer the question, say so:
"I don't have documentation on that yet — try asking your admin or
filing a request." Do NOT fall back to general knowledge about lab
software, FastAPI, or PostgreSQL.

If the dispatched task mentions the user's current route (e.g.
"/protocols/abc/edit"), use it to pick the page that covers that surface.
```

### 3. Configuration

New setting on `Settings` in `backend/app/core/config.py`:

```python
user_guide_dir: str = "docs/user-guide"
```

Resolved at config-load time the same way `skills_dir` is. Tests override via `monkeypatch` to point at a fixture corpus.

### 4. Feature flag

New entry on `FeaturesConfig`:

```python
class AppHelpFeatureConfig(BaseModel):
    enabled: bool = False

class FeaturesConfig(BaseModel):
    offline_mode: OfflineModeFeatureConfig = OfflineModeFeatureConfig()
    external_protocols: ExternalProtocolsFeatureConfig = ExternalProtocolsFeatureConfig()
    app_help: AppHelpFeatureConfig = AppHelpFeatureConfig()
```

Env var: `BATCHRITE_FEATURES__APP_HELP__ENABLED`.

Gating in `backend/app/services/ai/chat_agent.py`:

```python
subagents = [...existing...]
if settings.features.app_help.enabled:
    subagents.append(app_help.build(subagent_model))
```

No frontend flag. The chat UI surfaces the capability when the agent dispatches it, hides it otherwise — same pattern as F-0084's external protocols.

`CLAUDE.md` feature-flags table gets a row:

| Flag | Backend | Frontend | Default | Notes |
| --- | --- | --- | --- | --- |
| App help | `features.app_help.enabled` (yaml) or `BATCHRITE_FEATURES__APP_HELP__ENABLED` (env) | n/a — server-gated | `false` | `app_help` chat subagent answers product Q&A from `docs/user-guide/`. (F-0089) |

### 5. Chat-agent registration

Three coordinated edits:

- `subagents/__init__.py`: import `app_help`, add to `__all__`.
- `chat_agent.py`: register conditionally on the flag (see §4).
- `prompts/chat_agent.md`: add a `## Subagent: app_help` block listing do/don't triggers:

  > **Subagent: app_help** — Dispatch for questions about Batchrite the product: how features work, where pages live, what terms mean, troubleshooting. Examples: "how do I publish a protocol?", "what's the difference between an experiment and a run?", "why is the chat sidebar empty?". Do NOT dispatch for questions about the user's own data — route those to `research_library` or use the protocol/run tools.

### 6. Page-context awareness

The chat FAB sends the user's current route so the help subagent can disambiguate vague questions ("how does this work?").

**Frontend** (chat FAB component, send path in `lib/api.ts` or chat store):

- Read `window.location.pathname` at send time.
- Pass it as `current_route` on the message-send / streaming-send request body.

**Backend** — additive changes only:

- Add `current_route: str | None = None` to the chat-message create request schema (and its streaming equivalent).
- In `send_message.py`, when `current_route` is present, prepend `[page:<route>] ` to the **model-visible** prompt only. The persisted `ChatMessage.content` stays the user's raw text. This mirrors the existing `[skill:<id>] ` prefix mechanism used by `SkillsCapability` — same plumbing, no new `ChatDeps` field, no prop threading into subagents.

**Prompt edits:**

- `chat_agent.md` gets one paragraph: "When the user's message begins with `[page:<route>]`, the user is currently viewing that page in the app. Use this to disambiguate vague questions like 'how does this work?' — when dispatching to `app_help`, include the route in the task description so the subagent knows the current page."
- `app_help/prompt.md` notes that the dispatched task may mention a current route; use `list_user_guide_pages` + title/summary/keywords to pick the matching page.

**Route format:** raw `window.location.pathname` with UUIDs intact (e.g. `/protocols/abc-123-…/edit`). The model handles them; pattern-stripping IDs is more code for no benefit.

**Not now:** declaring `routes: ["/protocols/*"]` in frontmatter to make route-to-page matching mechanical. Add later if we see wrong-page citations in practice.

## Testing

### Unit — `tests/unit/services/ai/subagents/test_app_help_tools.py`

- `list_user_guide_pages` parses frontmatter from each fixture page and returns metadata.
- `list_user_guide_pages` handles a file with no frontmatter by skipping it and logging a warning — the corpus author must add frontmatter for the page to be discoverable.
- `read_user_guide_page("protocols.md")` returns body with frontmatter stripped.
- `read_user_guide_page("../../etc/passwd")` returns a populated `error`, does NOT raise.
- `read_user_guide_page("nonexistent.md")` returns a populated `error`.
- `read_user_guide_page("not-markdown.txt")` returns a populated `error`.

### Unit — `tests/unit/services/ai/subagents/test_app_help_config.py`

- `build(model)` returns a `SubAgentConfig` with both tools and the expected name/description.

### Unit — `tests/unit/test_tool_labels.py` (existing)

- Both new tools have entries in `TOOL_LABELS`. (The existing test already asserts every tool function has a label — add the entries and the test passes.)

### Unit — page-context prefix

- Extend the existing `send_message` unit tests: when the request includes `current_route`, the model-visible prompt begins with `[page:<route>] `; the persisted user-message `content` does not. When `current_route` is absent or empty, no prefix is added.

### Integration — `tests/integration/services/ai/test_app_help_integration.py`

Seed a small fixture corpus under `tests/fixtures/user_guide/`, point `settings.user_guide_dir` at it via `monkeypatch`:

- With `features.app_help.enabled=True`, sending "how do I create a protocol?" through the chat agent results in (a) `app_help` being dispatched (assert via `tool_calls`), (b) the response body containing a citation link to a `docs/user-guide/*.md` page from the fixture.
- With the flag disabled, the same question does not dispatch `app_help` (the subagent isn't registered).
- A query the fixture doesn't cover ("how do I integrate with Salesforce?") returns the "I don't have documentation on that yet" phrasing and no fabricated citation.
- A chat message with `current_route="/protocols/abc/edit"` and user text "how do I publish this?" dispatches `app_help` and the response cites the protocols page from the fixture.

### Frontend — Vitest

- The chat FAB store / send action attaches `current_route` to the outgoing message request.

## Work breakdown (input to writing-plans)

**Phase 1 — Feature audit.** Verify which surfaces from the task description are actually shipped vs aspirational. Output: the concrete list of pages to write. The user-guide must not document features that don't exist (e.g. voice/dictation, if it isn't built).

**Phase 2 — Subagent infrastructure.** Package skeleton (`config.py`, `prompt.md`, `tools.py`), feature flag, `user_guide_dir` setting, registration in `chat_agent.py`, `subagents/__init__.py` import, prompt block in `chat_agent.md`, `TOOL_LABELS` entries. TDD: write the failing unit tests first.

**Phase 3 — Page-context awareness.** Backend request schema field, `[page:<route>]` prefix in `send_message.py`, frontend chat FAB wiring, prompt edits, unit + integration tests.

**Phase 4 — Corpus authoring.** One `.md` per audited surface (Phase 1 output), frontmatter, end-user voice, ~150-400 words per page.

**Phase 5 — Integration tests + docs sync.** Wire up the fixture corpus, end-to-end routing tests. Update `CLAUDE.md` feature-flags table; add a one-line note about `app_help` in `.claude/rules/backend-ai.md`'s subagents directory tree.

## Out of scope

- In-product UI changes beyond `current_route` (no per-page help button, no inline tooltips).
- Screenshots, animated GIFs, video.
- Multi-language corpus.
- Indexing user-uploaded org docs.
- Retrieval engine (BM25 / embeddings).
- Declarative `routes:` frontmatter mapping (deferred until empirically needed).

## Dependencies

- F-0040: existing chat tool-based RAG infra (subagent framework, `ChatDeps`, `tool_calls` audit).
- F-0066: embedding search infra. Not used — left in the dependency list because if we later swap retrieval in, this is what we'd reuse.
- F-0083: tool labels live next to tool definitions (`TOOL_LABELS` per module + aggregator).
- F-0089 (other): server-prefix activation pattern (`SkillsCapability`'s `[skill:<id>]` prefix) — the page-context `[page:<route>]` prefix copies this mechanism.
