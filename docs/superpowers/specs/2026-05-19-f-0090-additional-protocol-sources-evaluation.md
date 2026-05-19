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
| **Auth** | A single long-lived access token (generated once from a registered developer app) reads all public data. No per-user OAuth flow — we only ever read public protocols. | None required. A free NCBI API key only raises the rate limit. | None. | Institutional subscription credentials. | — |
| **Licensing** | **All public protocols uniformly CC-BY** — platform-wide policy, not author-selected. The per-protocol `license` field is still read and verified on every payload (fail-closed). | OA subset is CC-licensed — mix of CC-BY, CC-BY-NC, CC-BY-NC-ND, CC0. Per-article; a "commercial-use" sub-filter exists. | Author-selected per preprint; many CC variants but also CC-BY-NC-ND and "no reuse without permission". | Proprietary, paywalled — not openly licensed. | None — hosts paywalled content without authorization. |
| **Content quality** | **Excellent** — purpose-built protocol repository; protocols are natively structured (titled steps, materials, durations). Cleanest normalization of any candidate. | **Fair** — research articles, not protocols; procedure content is buried in Methods sections and must be extracted from JATS XML. Noisier, lower fidelity. | **Poor** — preprints are papers; methods buried; and the API cannot return full text at query time at all. | High (purpose-built video + text protocols) — but inaccessible without a subscription. | N/A. |
| **Rate limits** | No hard published public limit; reasonable-use expected. Self-throttled via the existing token bucket. | 3 req/s without a key, 10 req/s with a free key. | Not strictly published; bulk S3 for heavy use. | N/A. | N/A. |
| **Cost** | Free public API tier. | Free. | Free. | Paid institutional subscription. | N/A. |
| **Legal status** | **Viable.** Public content is uniformly CC-BY → importable. The license gate is fail-closed *verification* of each payload's `license` field (defence-in-depth), not a per-protocol router. Still gated on a legal review of the protocols.io API Terms of Service before launch — the API ToS is a layer separate from the CC license and can independently constrain redistribution. | **Viable** — fully legal and public. Still needs the license gate (the OA subset includes NC/ND articles). | **Metadata viable only.** Useful full text requires bulk S3 ingestion — a different architecture (background ingestion) that does not fit an interactive query-time adapter. | **Not viable now.** Requires a JoVE partnership or customer-supplied institutional credentials *and* a contract permitting reuse inside Batchrite. | **Excluded — see A.2.** |

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
| **1** | **protocols.io** | **Build now (this task, Part B).** | **L** | Best content fit, cleanest JSON→payload normalization. Public content is uniformly CC-BY (importable); the gate verifies that fail-closed. Conditional on the API-ToS legal review. |
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

Restructure `ExternalProtocolsFeatureConfig` in `backend/app/core/config.py`
into per-source sub-blocks, each carrying its own throttle/timeout:

```python
class OpenWetWareSourceConfig(BaseModel):
    enabled: bool = True                  # default-on — preserves F-0084 behavior
    request_timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 10

class ProtocolsIoSourceConfig(BaseModel):
    enabled: bool = False                 # new source — opt-in
    access_token: str = ""                # long-lived API token (secret)
    request_timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 10

class ExternalProtocolsFeatureConfig(BaseModel):
    enabled: bool = False                 # master capability switch (unchanged)
    openwetware: OpenWetWareSourceConfig = OpenWetWareSourceConfig()
    protocols_io: ProtocolsIoSourceConfig = ProtocolsIoSourceConfig()
```

**Gating rule:** a source is live **iff** `external_protocols.enabled` (master)
**AND** `external_protocols.<source>.enabled`. OpenWetWare's per-source flag
defaults `True`, so a deployment that today sets only the master flag keeps
working unchanged. protocols.io defaults `False`; if its flag is on but
`access_token` is empty, the protocols.io tools raise `ValueError` (fail-closed,
same shape as the existing `_require_oww_url` guard) rather than calling the API
unauthenticated.

**Breaking config change.** The current flat
`external_protocols.request_timeout_seconds` / `rate_limit_per_minute` move
under `.openwetware`. Any deployment that set the old env vars
(`BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__REQUEST_TIMEOUT_SECONDS`, …) must
re-target them to `…__OPENWETWARE__…`. Acceptable because the capability ships
flag-disabled; the migration note belongs in the PR description.

Env shape:
`BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ENABLED=true`,
`BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN=…`.
The access token is a **secret** — set via env var only, never committed to
`settings.yaml`, treated like the AI provider keys.

### B.2 Code structure — flat sibling modules

F-0084's `tools.py` is **461 lines** doing five distinct jobs: result
dataclasses, the OpenWetWare wikitext parser, the in-process rate limiter, the
flag/URL guards, and the subagent tool functions. Adding protocols.io would
push it past 700. Split it into flat sibling modules inside the existing
subagent package — no sub-package — so the agent's logic stays next to the
agent and each concern is independently testable:

```
subagents/protocol_knowledgebase/
├── config.py        # register the protocols.io tool pair (unchanged shape)
├── prompt.md        # + protocols.io guidance, + license-restricted handling
├── types.py         # NEW — result dataclasses, MOVED from tools.py
│                    #   (ExternalProtocolStep/Payload, *Hit/*SearchResult,
│                    #    + ProtocolsIoHit/ProtocolsIoSearchResult)
├── licenses.py      # NEW — shared license-compatibility gate (B.4)
├── rate_limit.py    # NEW — in-process token bucket, MOVED from tools.py,
│                    #   re-keyed (org_id, source)
├── openwetware.py   # NEW — parse_openwetware_wikitext + search/fetch helpers,
│                    #   MOVED from tools.py
├── protocols_io.py  # NEW — protocols.io search/fetch + parse_protocols_io_json
└── tools.py         # THINNED to ~80 lines — RunContext wrappers that map args,
                     #   delegate to the connector modules, append tool_calls
                     #   audit rows; plus the TOOL_LABELS dict
```

This follows the placement rule the project actually wants: `services/` is for
genuinely shared, multi-consumer code; code owned by one package lives *in* that
package as sibling files. `.claude/rules/backend-ai.md` and `backend-services.md`
are corrected to state this explicitly (see §E) — the prior wording mandating
`services/<domain>/` for all pure transforms was inaccurate.

Moving the OpenWetWare connector, dataclasses, and rate limiter out of
`tools.py` is the one refactor beyond pure addition. It updates import paths in
F-0084's existing parser/tools tests; assertions are unchanged.

`tools.py` keeps the `TOOL_LABELS` dict covering every tool the subagent
registers (importing nothing new into `tool_labels.py`).

### B.3 protocols.io connector — `protocols_io.py`

Connector functions take **explicit primitives** (`db`, `org_id`, `query`,
`access_token`, timeout, …) — not a pydantic-ai `RunContext` — so they unit-test
without the chat harness. The `tools.py` wrappers (B.6) adapt `RunContext` to
these signatures.

- `search_protocols_io(...) -> ProtocolsIoSearchResult`
  Calls the protocols.io public search endpoint with an
  `Authorization: Bearer <access_token>` header. Returns hits
  (`id`, `title`, `url`, `snippet`).
- `fetch_protocols_io(...) -> ExternalProtocolPayload`
  Validates the URL host is `protocols.io` / `www.protocols.io` (literal check,
  mirroring `_require_oww_url`); extracts the protocol id; GETs the protocol
  detail JSON; delegates to the parser. Does **not** reuse OpenWetWare's generic
  `if not payload.steps` guard — it has its own terminal logic (B.4).
- `parse_protocols_io_json(detail_json, source_url) -> ExternalProtocolPayload`
  Pure parser (fixture-driven tests, no HTTP). Maps the protocol JSON to the
  `ExternalProtocolPayload` in `types.py` — no change to the payload's core
  fields. `license` ← the protocol's license object, classified via
  `licenses.classify_license`; `attribution` ←
  `"protocols.io — <authors>, <title>"`; `source_url` ← the protocol URL.

The exact protocols.io v4 endpoint paths and JSON field names are pinned against
the live API docs at implementation time; the fixture JSON drives the parser
tests, so any schema drift surfaces as a test failure.

### B.4 License-compatibility gate — `licenses.py`

protocols.io public content is **uniformly CC-BY** (platform-wide policy — not
author-selected), so for protocols.io the gate is not a router: every public
protocol is import-safe. The gate's job for this source is **fail-closed
verification** — read the `license` field on every payload and confirm it
really is CC-BY or CC0; if it ever comes back as anything else (a legacy
import, embedded third-party content, a policy change), downgrade to link-only
rather than wrongly import. The source that genuinely needs per-item license
*routing* is **PMC OA** (follow-up task) — its open-access subset mixes CC-BY,
CC-BY-NC, CC-BY-NC-ND and CC0. The classifier is built shared and pure now so
PMC OA inherits it.

A pure classifier, shared across sources:

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

**Which licenses import, and why — the three clauses bite at different times:**

- **NC (NonCommercial)** bites at *use* time. Batchrite is a commercial SaaS;
  using NC content in the product is commercial use the license forbids
  outright. → **blocked.**
- **ND (NoDerivatives)** bites at *derivative* time. Parsing a protocol into a
  Batchrite protocol graph and letting the user edit it *is* making a
  derivative, which ND forbids. → **blocked** — we simply don't import ND
  content; it isn't permissive enough for the product.
- **SA (ShareAlike — CC-BY-SA)** bites only at *external-distribution* time. It
  permits commercial use and derivatives; it only obligates that a derivative,
  *if redistributed outside the customer*, carry the same SA terms. An internal
  lab protocol is rarely redistributed. → **import-safe.** The SA notice is
  carried forward in `attribution` / `license_note`, and the customer Terms of
  Service allocate responsibility for any onward redistribution of an SA-derived
  protocol to the customer — the party actually doing the distributing. That
  TOS clause needs counsel review before launch (see Risks).

So `_IMPORT_SAFE` = CC0, CC-BY, CC-BY-SA (+ public domain). This keeps the
classifier consistent with the **existing OpenWetWare path**, whose content is
uniformly CC-BY-SA 3.0: because CC-BY-SA is import-safe, routing OpenWetWare
through the classifier would be a no-op — so F-0090 leaves the OpenWetWare
connector exactly as F-0084 shipped it. The gate is invoked only by the
protocols.io connector (and, later, PMC OA).

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

**Payload additions & the three terminal states.** `ExternalProtocolPayload`
(now in `types.py`) gains `import_allowed: bool = True` and
`license_note: str | None = None`. The `True` default leaves the OpenWetWare
path (CC-BY-SA 3.0 — import-safe) unchanged. Crucially, `import_allowed=False`
must **not** collapse into the existing `error` field — they mean opposite
things to the subagent:

| Terminal state | `steps` | Fields | Subagent behavior | Cached? |
|---|---|---|---|---|
| Genuine fetch failure | `[]` | `error` set | Skip silently, try another URL | No |
| License-restricted, real protocol | `[]` | `import_allowed=False`, `error=None`, `license_note` set | Present as a link, stop | **Yes** |
| Importable protocol | populated | `import_allowed=True`, `error=None` | Offer HITL import | Yes |

So `fetch_protocols_io` has its **own terminal logic**, not OpenWetWare's
generic `if not payload.steps → error` guard: a license-restricted protocol is
fully parsed, legitimately has `steps=[]` (we never copy the step text), and
must surface as a link — not be silently skipped as a "stub". The 0-steps guard
applies on the protocols.io path **only** to an *import-safe* protocol that
genuinely parsed no steps (a real stub → `error`).

This flips the caching rule. F-0084 caches a payload iff `payload.steps` is
non-empty; that would wrongly drop a license-restricted payload, which the
approval tool's re-check (B.7) needs to read back. The rule becomes **cache iff
`payload.error is None`** — failures aren't cached; restricted-but-valid
payloads are.

### B.5 Multi-source dispatch pattern

**Per-source tool pairs.** The subagent exposes `search_<source>` /
`fetch_<source>` for each source. All tools are registered **unconditionally**
on the subagent — the parent agent is cached per model tuple, not per org, so
conditional registration would break the cache invariant (F-0084 §3.6). Each
`tools.py` wrapper checks the master flag + its source flag (+ the access token
for protocols.io) and raises `ValueError` if unsatisfied; the subagent reports
that message verbatim.

Connector code is one sibling module per source (`openwetware.py`,
`protocols_io.py`), each exposing the search / fetch / parse trio that
normalizes to the `ExternalProtocolPayload` in `types.py`. **Adding a future
source** = add `<x>.py` + a tool pair in `tools.py`/`config.py` + a config
sub-block in B.1 — the dispatch core does not change.

The in-process rate-limit bucket (`rate_limit.py`) is re-keyed from `org_id` to
`(org_id, source)` so the two sources do not share one budget.

### B.6 Subagent tools & prompt

- `tools.py` — add `search_protocols_io` / `fetch_protocols_io` tool functions
  (thin `RunContext` wrappers over `protocols_io.py`), plus two `TOOL_LABELS`
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
source-agnostic. **One addition:** before drafting, the approval tool reads
`import_allowed` straight off the cached payload
(`json.loads(cached)["import_allowed"]`) — a plain boolean check, no
`classify_license` call — and raises `ValueError` if it is `False`, so a stale
cached payload cannot slip a restricted protocol through. Keeping it a boolean
read leaves `classify_license` single-consumer (the connector) and the approval
tool free of licensing logic.

### B.8 Frontend

**Untouched.** A protocols.io candidate flows through the identical
`EXTERNAL_PROTOCOL_SOURCE` → `ApprovalCard` → approve path; the card and the
candidate list already render `title` / `source_url` / `license` generically. A
license-restricted (link-only) candidate is just a markdown list item — no new
component, no `chat-store` change.

### B.9 Terms of Service — imported-content license clause

Importing an externally-sourced protocol places third-party–licensed content
(CC-BY from protocols.io, CC-BY-SA from OpenWetWare) into a customer's library.
The CC obligations travel with that content — attribution always, and for
ShareAlike the same-terms obligation if a derivative is redistributed outside
the customer's org. The party that can actually discharge those obligations is
the **customer** (they decide whether and how to use, modify, and redistribute
the protocol), not Batchrite (which only surfaces the source and its license).
The customer Terms of Service must say so. The licensing engineering above (the
`licenses.py` gate, the carried-forward `attribution` / `license_note`) gives
the customer the *information* to comply; this clause allocates the
*responsibility*. Without it, §7 ("you retain all right, title, and interest"
in Customer Data) reads as if the customer owns imported content outright,
which is false for licensed third-party material.

**Clause substance** (draft for counsel — exact wording and section placement
are counsel's call):

> **Externally-Sourced Protocol Content.** The Service may let you import
> protocol content that originates from third-party public repositories and is
> made available under an open-content license (for example, a Creative
> Commons license). Imported content remains subject to its original license,
> and the rights you have in it are only those that license grants. Batchrite
> surfaces the source and the license of imported content but does not grant
> you, and does not assume on your behalf, any rights or obligations in that
> content. You are responsible for complying with the original license —
> including its attribution requirements and, for "ShareAlike" licenses, the
> obligation to license a derivative under the same terms if you redistribute
> it outside your organization. The ownership representation in Section 7 does
> not extend to imported third-party content; that content is hosted as
> Customer Data but is not owned by you.

Recommended placement: a new section immediately after §7, since it qualifies
what §7 means for content the customer did not author. Adding a section
renumbers §§8–18 and the §12 survival list gains the new section number — all
contained inside the new version file; **the 2026-04-27 files are never
edited.**

**Mechanism — a new versioned legal document.** Legal docs are immutable
versioned directories under `backend/app/legal/versions/<date>/`, registered in
`versions/__init__.py`; `service.get_document` derives `effective_date` from the
directory name. F-0090:

1. Creates `backend/app/legal/versions/2026-05-19/terms.md` — the 2026-04-27
   `terms.md` with the new section added, the `**Version:**` / `**Effective
   Date:**` headers bumped to `2026-05-19`, §§8–18 renumbered, and the
   counsel-review TODO marker retained.
2. Copies `privacy.md` into the same directory **unchanged** — a version
   directory must hold the complete document set even though the privacy policy
   is unaffected.
3. Adds `"2026-05-19"` to `ALL_VERSIONS` **and** bumps `CURRENT_VERSION` to
   `"2026-05-19"` in `versions/__init__.py` — the activation step — committed
   with the grep-able convention `feat(legal): activate ToS/Privacy version
   2026-05-19`.

**Activation now — the app is pre-launch with no production users.** Bumping
`CURRENT_VERSION` is what makes the new version live and re-prompts users to
accept it via the legal gate (which pins `users.tos_version`). Batchrite has no
real users yet, so there is no re-acceptance churn to defer — F-0090 activates
2026-05-19 directly, in the same change that authors it. The clause is in force
from the moment the work lands; no separate activation step is owed to the
protocols.io flag-enablement change. (The clause governing a still-disabled
capability is harmless — it simply pre-states the rule.)

The new `terms.md` retains the existing "counsel review before first paid
contract" TODO marker. Activating a pre-counsel version is consistent with the
status quo: 2026-04-27 is itself a pre-counsel draft already serving as
`CURRENT_VERSION`. Counsel review of the externally-sourced-content clause folds
into that existing pre-paid-contract review (see Risks); it does not gate
F-0090. F-0090 updates `test_legal_content.py`: the `**Version:**` /
`**Effective Date:**` header assertions move from `2026-04-27` to `2026-05-19`
(they are pinned to `CURRENT_VERSION`, which now moves), and a new assertion
checks the current terms contain the "Externally-Sourced Protocol Content"
heading. The required-section and counsel-TODO assertions still pass — the new
`terms.md` is a superset of 2026-04-27.

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
  `import_allowed=True`, `error is None`. A second case against
  `protocol_detail_nc.json` asserts `import_allowed=False`, `error is None`
  (restricted ≠ failure), empty `steps`/`materials`, populated `license_note`.
- `test_protocols_io_tools.py` — `httpx.AsyncClient.get` monkey-patched:
  (a) master flag off → `ValueError`; (b) source flag off → `ValueError`;
  (c) flag on but `access_token` empty → `ValueError`; (d) host not
  `protocols.io` → `ValueError`; (e) rate-limit hit after
  `rate_limit_per_minute + 1` calls in the simulated minute; (f) successful
  search/fetch append `tool_calls` audit rows; (g) fetch of a license-restricted
  protocol → `import_allowed=False`, `error is None`, no step text retained,
  payload **is** cached; (h) genuine fetch failure → `error` set, payload **not**
  cached.
- `test_openwetware_parser.py`, `test_openwetware_tools.py` — update import
  paths for the `openwetware.py` / `rate_limit.py` / `types.py` moves;
  `test_openwetware_tools.py` also re-targets its rate-limit monkeypatch to
  `external_protocols.openwetware.rate_limit_per_minute`. Assertions unchanged.
- `test_settings_external_protocols.py` — `request_timeout_seconds` /
  `rate_limit_per_minute` assertions re-target under `.openwetware`; add
  `.protocols_io.*` defaults.
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
backend/app/core/config.py                                                       # per-source flag model (breaking restructure)
backend/app/services/ai/subagents/protocol_knowledgebase/types.py                 # new — result dataclasses, moved from tools.py
backend/app/services/ai/subagents/protocol_knowledgebase/licenses.py              # new — classify_license
backend/app/services/ai/subagents/protocol_knowledgebase/rate_limit.py            # new — token bucket, moved from tools.py
backend/app/services/ai/subagents/protocol_knowledgebase/openwetware.py           # new — connector, moved from tools.py
backend/app/services/ai/subagents/protocol_knowledgebase/protocols_io.py          # new — protocols.io connector
backend/app/services/ai/subagents/protocol_knowledgebase/tools.py                 # thinned to RunContext wrappers + TOOL_LABELS
backend/app/services/ai/subagents/protocol_knowledgebase/config.py                # register protocols.io tool pair
backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md                # protocols.io + license-restricted guidance
backend/app/services/ai/tools/external_protocols.py                               # approval tool: import_allowed re-check
backend/app/legal/versions/2026-05-19/terms.md                                    # new — ToS version + externally-sourced-content clause
backend/app/legal/versions/2026-05-19/privacy.md                                  # new — privacy.md copied unchanged (version-set completeness)
backend/app/legal/versions/__init__.py                                            # register + activate 2026-05-19 (ALL_VERSIONS + CURRENT_VERSION bump)
backend/tests/fixtures/protocols_io/search_response.json                          # new fixture
backend/tests/fixtures/protocols_io/protocol_detail.json                          # new fixture (import-safe)
backend/tests/fixtures/protocols_io/protocol_detail_nc.json                       # new fixture (license-restricted)
backend/tests/unit/test_license_gate.py                                           # new
backend/tests/unit/test_protocols_io_parser.py                                    # new
backend/tests/unit/test_protocols_io_tools.py                                     # new
backend/tests/unit/test_openwetware_parser.py                                     # import-path update
backend/tests/unit/test_openwetware_tools.py                                      # import-path + per-source flag update
backend/tests/unit/test_settings_external_protocols.py                            # per-source config shape
backend/tests/unit/test_protocol_knowledgebase_config.py                          # per-source flag assertions
backend/tests/integration/test_protocol_knowledgebase_handoff.py                  # + protocols.io + restricted paths
backend/tests/unit/test_legal_content.py                                          # version-header assertions → 2026-05-19; new section check
docs/superpowers/specs/2026-05-19-f-0090-additional-protocol-sources-evaluation.md # this doc
docs/superpowers/specs/2026-05-12-f-0084-protocol-knowledgebase-subagent-design.md # forward-pointer (stale non-goal)
CONTEXT.md                                                                        # Protocol Source + license gate glossary
CLAUDE.md                                                                         # external_protocols flag row: per-source sub-flags
.claude/rules/backend-ai.md                                                       # locality rule fix + multi-source sibling-module pattern
.claude/rules/backend-services.md                                                 # locality rule fix (services = shared code only)
```

## F. Risks and pre-launch checklist

- **protocols.io API ToS legal review — hard gate.** `protocols_io.enabled`
  must NOT be flipped on in any environment until the protocols.io API Terms of
  Service have been reviewed. The per-protocol CC license governs the *content*;
  the API ToS governs *API use* and can independently restrict redistribution.
  This task ships the adapter flag-disabled; enabling it is a separate decision.
- **Imported-content licensing — ToS clause authored and activated.**
  Imported content carries its original CC license (attribution always;
  ShareAlike on onward redistribution for CC-BY-SA). F-0090 authors the
  Externally-Sourced Protocol Content clause, registers the 2026-05-19 ToS
  version, and bumps `CURRENT_VERSION` to activate it (B.9) — safe to do now
  because Batchrite is pre-launch with no production users, so there is no
  re-acceptance churn. Counsel review of the clause folds into the existing
  pre-paid-contract legal review carried by the `terms.md` TODO marker; it is
  not a blocker for F-0090.
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
