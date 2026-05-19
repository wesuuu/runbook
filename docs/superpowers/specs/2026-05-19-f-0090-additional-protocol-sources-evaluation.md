# F-0090 — Additional Protocol Sources: Comparative Evaluation + protocols.io Adapter

**Status:** approved-design · **Priority:** P2 · **Scope:** Backend (subagent + connector); Frontend unaffected · **Effort:** M (spike) + L (protocols.io adapter)

## 1. Summary

F-0084 added the `protocol_knowledgebase` chat subagent, which searches OpenWetWare
for public protocols and routes conversion through a human-in-the-loop (HITL)
approval gate. OpenWetWare alone is too narrow. This task does two things:

1. **The spike (Part A).** Evaluate five candidate sources, eliminate the
   non-viable ones (Sci-Hub on legal grounds), and produce a ranked
   recommendation with effort estimates and a feature-flag decision.
2. **The build (Part B).** Implement the #1-ranked adapter — **protocols.io** —
   including a shared **license-compatibility gate** so the product only ever
   auto-imports protocols whose authors permitted commercial reuse and
   derivatives.

Adapters for the lower-ranked sources are explicit follow-up tasks, not part of
F-0090.

---

## Part A — Comparative evaluation

### A.1 Comparison matrix

| Dimension | **protocols.io** | **PMC OA Subset** | **bioRxiv / medRxiv** | **JoVE** | **Sci-Hub** |
|---|---|---|---|---|---|
| **API / access** | Public REST API (v4), JSON. Search + per-protocol retrieve. | NCBI E-utilities (`esearch`/`efetch`) + PMC OA service; full-text JATS XML. | `api.biorxiv.org` — **metadata only** (DOI, title, abstract, license). Full text only via a bulk Amazon S3 TDM bucket. | **No public developer API.** Access via institutional subscription + SSO; third-party integrations exist for subscribers. | No legitimate API. Rotating TLDs (`.st`/`.ru`/`.se`/…). |
| **Auth** | OAuth2 — a client access token (from `client_id`/`client_secret` registered on the developers page) reads all public data. | None required. A free NCBI API key only raises the rate limit. | None. | Institutional subscription credentials. | — |
| **Licensing** | Per-protocol Creative Commons, author-selected. Public default ≈ CC-BY; CC-BY-NC and CC-BY-NC-ND also present. License exposed as a structured field. | OA subset is CC-licensed — mix of CC-BY, CC-BY-NC, CC-BY-NC-ND, CC0. Per-article; a "commercial-use" sub-filter exists. | Author-selected per preprint; many CC variants but also CC-BY-NC-ND and "no reuse without permission". | Proprietary, paywalled — not openly licensed. | None — hosts paywalled content without authorization. |
| **Content quality** | **Excellent** — purpose-built protocol repository; protocols are natively structured (titled steps, materials, durations). Cleanest normalization of any candidate. | **Fair** — research articles, not protocols; procedure content is buried in Methods sections and must be extracted from JATS XML. Noisier, lower fidelity. | **Poor** — preprints are papers; methods buried; and the API cannot return full text at query time at all. | High (purpose-built video + text protocols) — but inaccessible without a subscription. | N/A. |
| **Rate limits** | No hard published public limit; reasonable-use expected. Self-throttled via the existing token bucket. | 3 req/s without a key, 10 req/s with a free key. | Not strictly published; bulk S3 for heavy use. | N/A. | N/A. |
| **Cost** | Free public API tier. | Free. | Free. | Paid institutional subscription. | N/A. |
| **Legal status** | **Viable** with (a) a per-protocol license gate that blocks NC/ND, and (b) a legal review of the protocols.io API Terms of Service before launch — the API ToS is a layer separate from the per-protocol CC license and can independently constrain redistribution. | **Viable** — fully legal and public. Still needs the license gate (the OA subset includes NC/ND articles). | **Metadata viable only.** Useful full text requires bulk S3 ingestion — a different architecture (background ingestion) that does not fit an interactive query-time adapter. | **Not viable now.** Requires a JoVE partnership or customer-supplied institutional credentials *and* a contract permitting reuse inside Batchrite. | **Excluded — see A.2.** |

### A.2 Sci-Hub — exclusion rationale (recorded; no adapter, ever)

Sci-Hub is **out of scope and must never be integrated.** The reasoning, recorded
here so the decision is not re-litigated:

- Sci-Hub redistributes copyrighted, paywalled articles **without
  authorization** from the rights holders. There is no license under which we
  could lawfully ingest its content.
- It is under **active injunctions** from major publishers (Elsevier, ACS, and
  others) in US and EU courts. Its **rotating TLDs are themselves a signal** of
  ongoing legal enforcement against it.
- Integrating it would create **direct DMCA / copyright liability** for
  Batchrite.
- It would be an **automatic adverse finding** in any GLP/GxP customer audit —
  a non-starter for the regulated customers Batchrite targets.

No adapter, no feature flag, no follow-up task. The candidate is closed.

### A.3 Ranked recommendation

| Rank | Source | Decision | Effort | Notes |
|---|---|---|---|---|
| **1** | **protocols.io** | **Build now (this task, Part B).** | **L** | Best content fit, cleanest JSON→payload normalization, explicit per-protocol license field the gate keys on. Conditional on the license gate + API-ToS legal review. |
| **2** | **PMC OA Subset** | **Build next — separate follow-up task.** | **L+** | Zero credentials, unambiguously legal. The added cost over an L adapter is JATS Methods-section extraction and handling the article-vs-protocol content mismatch. |
| **3** | **bioRxiv / medRxiv** | **Do not build.** | — | The query-time API is metadata-only; usable full text exists only via bulk S3 ingestion, which is a different architecture (background library ingestion) explicitly out of scope for the interactive subagent. Revisit only if bulk ingestion becomes a product direction. |
| — | **JoVE** | **Defer indefinitely.** | Not estimable | Blocked on a commercial partnership or customer-supplied institutional credentials. Cannot be scoped until API access exists. |
| — | **Sci-Hub** | **Excluded permanently.** | — | See A.2. |

### A.4 Feature-flag decision

**Per-source flags nested under the existing `external_protocols` namespace, with
the master switch retained.** Detailed config shape in B.1.

Rationale:

- A single misbehaving or legally-flagged source can be disabled independently,
  without taking down the whole capability.
- The master switch (`external_protocols.enabled`) still disables everything at
  once.
- New sources are **opt-in** — adding one cannot change the behavior of an
  existing deployment that only set the master flag.

Rejected alternative — a flat sibling flag per source
(`features.external_protocols_protocols_io`): loses the master switch and the
namespacing, and scatters related config.

---

## Part B — protocols.io adapter design

### B.1 Feature-flag model

Restructure `ExternalProtocolsFeatureConfig` in `backend/app/core/config.py`:

```python
class ProtocolSourceConfig(BaseModel):
    """Per-source toggle within the external-protocols capability."""
    enabled: bool = True

class ProtocolsIoSourceConfig(ProtocolSourceConfig):
    enabled: bool = False                 # new source — opt-in
    access_token: str | None = None       # OAuth2 client access token

class ExternalProtocolsFeatureConfig(BaseModel):
    enabled: bool = False                 # master capability switch (unchanged)
    request_timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 10
    openwetware: ProtocolSourceConfig = ProtocolSourceConfig()
    protocols_io: ProtocolsIoSourceConfig = ProtocolsIoSourceConfig()
```

**Gating rule:** a source is live **iff** `external_protocols.enabled` (master)
**AND** `external_protocols.<source>.enabled`. OpenWetWare's per-source flag
defaults `True`, so a deployment that today sets only the master flag keeps
working unchanged. protocols.io defaults `False`.

Env shape:
`BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ENABLED=true`,
`BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN=…`.
The access token is a **secret** — set via env var only, never committed to
`settings.yaml`, treated like the AI provider keys.

### B.2 Code structure — a `sources/` sub-package

F-0084's `tools.py` is ~280 lines; adding protocols.io would push it past 500.
Extract a sub-package so each source is isolated and independently testable:

```
subagents/protocol_knowledgebase/
├── config.py           # register the protocols.io tool pair
├── prompt.md           # + protocols.io guidance, + license-restricted handling
├── tools.py            # thinned: subagent tool fns, TOOL_LABELS, shared rate limit, flag helpers
└── sources/
    ├── __init__.py
    ├── licenses.py     # shared license-compatibility gate (B.4)
    ├── openwetware.py  # MOVED from tools.py: parse_openwetware_wikitext + search/fetch helpers
    └── protocols_io.py # NEW: protocols.io search/fetch + parse_protocols_io_json
```

Moving the OpenWetWare connector is the one refactor beyond pure addition. It
updates the import paths in F-0084's existing parser/tools tests (~2 lines
each). The alternative — OpenWetWare in `tools.py`, protocols.io in `sources/` —
is asymmetric and confusing.

`tools.py` keeps the `TOOL_LABELS` dict covering every tool the subagent
registers (importing nothing new into `tool_labels.py`).

### B.3 protocols.io connector — `sources/protocols_io.py`

- `search_protocols_io(ctx, query, limit=5) -> ProtocolsIoSearchResult`
  Calls the protocols.io public search endpoint with an
  `Authorization: Bearer <access_token>` header. Returns hits
  (`id`, `title`, `url`, `snippet`).
- `fetch_protocols_io(ctx, url) -> ExternalProtocolPayload`
  Validates the URL host is `protocols.io` / `www.protocols.io` (literal check,
  mirroring `_require_oww_url`); extracts the protocol id; GETs the protocol
  detail JSON; runs the license gate (B.4); builds the payload.
- `parse_protocols_io_json(detail_json, source_url) -> ExternalProtocolPayload`
  Pure parser (fixture-driven tests, no HTTP). Maps the protocol JSON to the
  **existing `ExternalProtocolPayload`** — no change to the payload's core
  fields. `license` ← the protocol's license object; `attribution` ←
  `"protocols.io — <authors>, <title>"`; `source_url` ← the protocol URL.

The exact protocols.io v4 endpoint paths and JSON field names are pinned against
the live API docs at implementation time; the fixture JSON drives the parser
tests, so any schema drift surfaces as a test failure.

### B.4 License-compatibility gate — `sources/licenses.py`

A pure classifier, shared across sources (protocols.io now; PMC/OpenWetWare
later):

```python
@dataclass(frozen=True)
class LicenseVerdict:
    normalized: str         # canonical form, e.g. "CC-BY", "CC-BY-NC", "UNKNOWN"
    import_allowed: bool
    reason: str             # human-readable, used for license_note

# Commercial use AND derivative works both permitted.
_IMPORT_SAFE = {"CC0", "CC-BY", "CC-BY-SA", "PUBLIC-DOMAIN"}

def classify_license(raw: str | None) -> LicenseVerdict: ...
```

Normalization uppercases, strips version numbers, collapses separators. If the
normalized form contains an **NC** (NonCommercial) or **ND** (NoDerivatives)
token → `import_allowed=False`. Empty or unrecognized → `import_allowed=False`,
`normalized="UNKNOWN"` (**fail-closed**).

Why NC and ND both block: Batchrite is a commercial SaaS, so importing an NC
protocol is commercial use the license forbids; and converting a protocol into a
Batchrite protocol graph is a derivative work, which ND forbids.

**Behavior split** (validation tier **T1 — backend-only**; feedback is an
in-chat message, no frontend preflight):

- **Import-safe license** → normal convert/HITL path; full payload with `steps`
  and `materials`.
- **Restricted / unknown license** → `fetch_protocols_io` returns a
  **metadata-only** `ExternalProtocolPayload`: `title`, `source_url`, `license`,
  a short `summary` — **`steps` and `materials` are NOT copied into our
  system** — flagged `import_allowed=False`. The subagent presents it in the
  candidate list as a link with: *"This protocol is under a
  non-commercial/no-derivatives license, so I can't import it automatically.
  You can review it at \<link\> and add it to your library manually if it's
  appropriate for your use."*
- The product never offers a one-click "add restricted protocol to library":
  our tooling fetching and populating NC/ND content into a commercial product
  is itself the redistribution NC forbids, regardless of who clicks. If the user
  wants a restricted protocol, they bring it in through the **existing manual
  library-upload path**, where the user is the party doing the copying.

This requires a small addition to `ExternalProtocolPayload`:
`import_allowed: bool = True` and `license_note: str | None = None`. The `True`
default leaves the OpenWetWare path (CC-BY-SA 3.0 — import-safe) unchanged.

### B.5 Multi-source dispatch pattern

**Per-source tool pairs.** The subagent exposes `search_<source>` /
`fetch_<source>` for each source. All tools are registered **unconditionally**
on the subagent — the parent agent is cached per model tuple, not per org, so
conditional registration would break the cache invariant (F-0084 §3.6). Each
tool body checks the master flag + its source flag (+ the access token for
protocols.io) and raises `ValueError` if unsatisfied; the subagent reports that
message verbatim.

Connector code is one module per source under `sources/`, each exposing the
search / fetch / parse trio that normalizes to the shared
`ExternalProtocolPayload`. **Adding a future source** = add `sources/<x>.py` +
a tool pair in `tools.py`/`config.py` + a config sub-block in B.1 — the dispatch
core does not change.

The in-process rate-limit bucket is re-keyed from `org_id` to
`(org_id, source)` so the two sources do not share one budget.

### B.6 Subagent tools & prompt

- `tools.py` — add `search_protocols_io` / `fetch_protocols_io` tool functions
  (thin wrappers over `sources/protocols_io.py`), plus two `TOOL_LABELS`
  entries (`"Searching protocols.io…"`, `"Reading protocols.io protocol…"`).
  The existing `test_tool_labels.py` coverage test validates them
  automatically.
- `config.py` — register the new tool pair on the subagent.
- `prompt.md` — add protocols.io guidance: honor a source if the user names
  one; otherwise prefer protocols.io for "find a protocol for technique X"
  (it is purpose-built); when a fetch returns a license error or a
  license-restricted candidate, present it as a link with the manual-import
  note and continue with the other candidates. Subagent description updated to
  `(OpenWetWare, protocols.io)`.

### B.7 HITL approval flow

Unchanged from F-0084 — `create_protocol_from_external_source`,
`external_protocol_cache`, and `POST /sessions/{id}/messages/approve` are all
source-agnostic. **One addition:** the approval tool re-checks `import_allowed`
(re-classifying the license from the payload) before drafting — belt-and-
suspenders so a stale cached payload cannot slip a restricted protocol through.
If restricted, it raises `ValueError` and no protocol is created.

### B.8 Frontend

**Untouched.** A protocols.io candidate flows through the identical
`EXTERNAL_PROTOCOL_SOURCE` → `ApprovalCard` → approve path; the card and the
candidate list already render `title` / `source_url` / `license` generically. A
license-restricted (link-only) candidate is just a markdown list item — no new
component, no `chat-store` change.

---

## C. Data flow (protocols.io happy path)

```
turn 1 (search):   user "find a protocols.io protocol for plasmid miniprep"
                   → parent dispatches protocol_knowledgebase
                   → search_protocols_io + fetch_protocols_io ×N
                   → license gate: import-safe → full payload;
                                   restricted   → metadata-only, link-only note
                   → subagent returns markdown candidate list + JSON → done

turn 2 (convert):  user "use the second one" → parent calls
                   create_protocol_from_external_source (requires_approval=True)
                   → import_allowed re-check → DeferredToolRequests
                   → approval_required SSE event, stream ends

turn 2b (approve): user clicks Approve → POST /messages/approve
                   → tool body runs, dispatches protocol_creator
                   → new Protocol row; description cites source_url + license
                   → done
```

## D. Tests (TDD — red/green/refactor)

### D.1 Backend unit

- `test_license_gate.py` — `classify_license` over CC0 / CC-BY / CC-BY-SA
  (allowed), CC-BY-NC / CC-BY-ND / CC-BY-NC-ND (blocked), and empty / unknown
  (blocked, fail-closed). Asserts `normalized` canonicalization.
- `test_protocols_io_parser.py` — `parse_protocols_io_json` against
  `fixtures/protocols_io/protocol_detail.json`: asserts title, ≥3 materials,
  ≥5 steps, non-empty summary, license, attribution, `source_url`,
  `import_allowed=True`. A second case against `protocol_detail_nc.json`
  asserts `import_allowed=False`, empty `steps`/`materials`, populated
  `license_note`.
- `test_protocols_io_tools.py` — `httpx.AsyncClient.get` monkey-patched:
  (a) master flag off → `ValueError`; (b) source flag off → `ValueError`;
  (c) missing access token → `ValueError`; (d) host not `protocols.io` →
  `ValueError`; (e) rate-limit hit after `rate_limit_per_minute + 1` calls in
  the simulated minute; (f) successful search/fetch append `tool_calls` audit
  rows; (g) fetch of an NC-licensed protocol → metadata-only payload, no step
  text retained.
- `test_openwetware_parser.py`, `test_openwetware_tools.py` — update import
  paths for the `sources/openwetware.py` move; assertions unchanged.
- Config test (`test_protocol_knowledgebase_config.py` or the core config
  test) — new per-source flag structure; defaults `openwetware.enabled=True`,
  `protocols_io.enabled=False`; env-var override resolves.

### D.2 Backend integration

`test_protocol_knowledgebase_handoff.py` — extended:

- protocols.io path: mock protocols.io HTTP for one search + one fetch.
  `POST /messages/stream` → assert `tool_start` for `search_protocols_io` /
  `fetch_protocols_io`, then a candidate title in the assistant message.
  `POST /messages/stream` "use that one" → `approval_required`.
  `POST /messages/approve` `approved=true` → a new `Protocol` row whose
  description contains the protocols.io source URL and license.
- License-restricted path: mock an NC-licensed protocols.io protocol. Assert the
  subagent reply presents it as a link with the manual-import note, and that
  `create_protocol_from_external_source` refuses it (no `Protocol` row).

No new frontend tests — the frontend is unchanged.

## E. Files touched

```
backend/app/core/config.py                                                       # per-source flag model
backend/app/services/ai/subagents/protocol_knowledgebase/sources/__init__.py      # new
backend/app/services/ai/subagents/protocol_knowledgebase/sources/licenses.py      # new — classify_license
backend/app/services/ai/subagents/protocol_knowledgebase/sources/openwetware.py   # new — moved from tools.py
backend/app/services/ai/subagents/protocol_knowledgebase/sources/protocols_io.py  # new — protocols.io connector
backend/app/services/ai/subagents/protocol_knowledgebase/tools.py                 # thinned + protocols.io tool fns + TOOL_LABELS
backend/app/services/ai/subagents/protocol_knowledgebase/config.py                # register protocols.io tool pair
backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md                # protocols.io + license-restricted guidance
backend/app/services/ai/tools/external_protocols.py                               # approval tool: import_allowed re-check
backend/tests/fixtures/protocols_io/search_response.json                          # new fixture
backend/tests/fixtures/protocols_io/protocol_detail.json                          # new fixture (import-safe)
backend/tests/fixtures/protocols_io/protocol_detail_nc.json                       # new fixture (NC-licensed)
backend/tests/unit/test_license_gate.py                                           # new
backend/tests/unit/test_protocols_io_parser.py                                    # new
backend/tests/unit/test_protocols_io_tools.py                                     # new
backend/tests/unit/test_openwetware_parser.py                                     # import-path update
backend/tests/unit/test_openwetware_tools.py                                      # import-path update
backend/tests/unit/test_protocol_knowledgebase_config.py                          # per-source flag assertions
backend/tests/integration/test_protocol_knowledgebase_handoff.py                  # + protocols.io + NC paths
docs/superpowers/specs/2026-05-19-f-0090-additional-protocol-sources-evaluation.md # this doc
docs/superpowers/specs/2026-05-12-f-0084-protocol-knowledgebase-subagent-design.md # forward-pointer (stale non-goal)
CONTEXT.md                                                                        # Protocol Source + license gate glossary
CLAUDE.md                                                                         # external_protocols flag row: per-source sub-flags
.claude/rules/backend-ai.md                                                       # multi-source sources/ pattern + license gate
```

## F. Risks and pre-launch checklist

- **protocols.io API ToS legal review — hard gate.** `protocols_io.enabled`
  must NOT be flipped on in any environment until the protocols.io API Terms of
  Service have been reviewed. The per-protocol CC license governs the *content*;
  the API ToS governs *API use* and can independently restrict redistribution.
  This task ships the adapter flag-disabled; enabling it is a separate decision.
- **Access token is a secret.** Env var only, never `settings.yaml`.
- **API v4 schema drift.** Exact field paths are pinned at implementation
  against the live docs; the fixture-driven parser tests catch drift.
- **License classifier failure mode is safe.** Fail-closed on unknown licenses;
  a safe license misclassified as unknown costs only a link-only downgrade —
  never a wrongful import.
- **Single-process rate limit.** Inherited F-0084 limitation, now keyed
  `(org, source)`. Same multi-worker caveat.
- **Mock-tested adapter.** No live protocols.io call in the automated suite
  (consistent with OpenWetWare). A manual smoke test against the live API with a
  real token is recommended before production enablement but is not part of CI.

## G. Non-goals

- No PMC OA / bioRxiv / JoVE adapters — follow-up tasks or declined (Part A).
- No Sci-Hub integration — ever (A.2).
- No background ingestion or bulk-S3 import — interactive query-time only.
- No one-click "add a license-restricted protocol to the library."
- No frontend changes.
- No change to the HITL approval mechanics beyond the `import_allowed` re-check.
