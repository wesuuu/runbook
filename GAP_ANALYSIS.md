# Gap Analysis — Runbook AI Co-Pilot

> Analysis date: 2026-03-09
> Codebase state: `5d1ccd1` (main)
> Context: Research-use MVP targeting **gene & cell therapy (GCT) PD teams**. Not targeting GMP/regulated use yet. See `BUSINESS_STRATEGY.md` for phased approach, pricing, and funding strategy.

## Executive Summary

The Runbook AI Co-Pilot has a **strong core foundation** — graph-based protocol design, role-based run execution, AI-powered image analysis, offline field mode with encrypted sessions, and a multi-channel notification system. These are differentiated capabilities that most competitors lack or gate behind premium tiers.

**Product focus**: A **protocol execution and data collection platform** for GCT PD teams. Scientists design manufacturing protocols as visual flowcharts, execute runs on tablets in the lab, capture data (manually, via AI image analysis, or CSV import), and export cleanly to analysis tools (GraphPad Prism, SAS, Excel).

**What's notably missing for the GCT research MVP** falls into four categories:

1. **GCT-specific content** — No pre-loaded unit operations for cell therapy workflows (transfection, expansion, viral vector production). The unit op library is generic. This is the single biggest gap for the target market.
2. **Core usability gaps** — No undo/redo in the protocol editor, no full-text search, no commenting system. Basic expectations that affect daily usage.
3. **Export pipeline gaps** — Export works but lacks presets, clipboard copy, and Prism-friendly formatting. Core value prop must be frictionless.
4. **Lab workflow gaps** — No barcode scanning, no CSV/instrument data import. Features that make a lab tool feel purpose-built.

**Top 6 MVP priorities:**
1. GCT unit ops library & sample protocol templates (High — "built for you" moment)
2. Undo/redo in protocol editor (High — basic usability)
3. Export pipeline improvements (High — core value proposition)
4. Full-text search (High — critical at scale)
5. Commenting system (High — team collaboration)
6. Barcode/QR code scanning (High — lab workflow efficiency)

**Deferred to Phase 2 (GMP, revenue-dependent):** Electronic signatures, 21 CFR Part 11, SSO/SAML, hash chaining, data retention policies. See `BUSINESS_STRATEGY.md`.

---

## Current Capabilities Inventory

### What's Built

**Protocol Management**
- Visual graph-based protocol editor (@xyflow/svelte) with drag-drop unit operations
- Swimlane-based role organization with custom colors
- Protocol versioning (draft/published) with version history browsing
- Protocol approval workflow (DRAFT → PENDING_APPROVAL → APPROVED)
- Protocol archiving and restoration
- PDF generation (SOP and batch record formats) with customizable formatting
- Horizontal/vertical layout switching, time axis overlay

**Run Execution**
- Run creation from protocol snapshots (copy-on-write)
- Role assignment (users mapped to swimlane roles)
- Step-by-step execution with parameter entry
- Per-step completion tracking with user attribution
- Run status machine (PLANNED → ACTIVE → COMPLETED → EDITED)
- GMP edit tracking (original_results preserved, edited_by/edited_at logged)
- Run locking to started_by user

**AI & Image Analysis**
- Multi-provider AI vision (Ollama, Anthropic, Google, OpenAI)
- Image upload for run steps (JPEG/PNG/WebP/HEIC/TIFF, 20MB max)
- AI-powered parameter extraction from instrument images
- Multi-turn conversational analysis (ask follow-ups)
- Parameter tagging on images
- Batch analysis of pending images
- Configurable AI provider settings with connection testing

**Offline / Field Mode**
- PWA with service worker (cache-first static, network-first API)
- Encrypted offline sessions (PBKDF2 + AES-256-GCM via Web Crypto)
- IndexedDB storage for session data and action queue
- Offline run execution with image capture and manual value entry
- Auto-lock on inactivity (1 hour) with session expiry warnings
- Background Sync API + fallback for queue drain
- Orphaned action recovery on reconnect
- Admin token revocation

**Identity & Access Management**
- JWT-based auth with registration/login
- Organizations → Teams → Users hierarchy
- Granular permissions (VIEW/EDIT/APPROVE/ADMIN) on Projects, Protocols, Runs
- User or Team as permission principals
- User profile with avatar, preferences (font size, density)

**Notifications**
- In-app notification bell with unread count
- External channels: Email, Slack, Teams, Discord, Webhook, Console
- Configurable subscriptions per event type (12 event types)
- User-level and org-level channel management
- Delivery tracking with retry/failure logging

**Data Export**
- Multi-run export with column selection
- Long (normalized) and wide (matrix) layouts
- CSV, Excel, JSON output formats
- Preview grid with pagination

**Dashboard**
- My work sections (active, planned, completed runs)
- Activity feed with pagination
- Counter cards (runs, projects, protocols, team members)
- 7-day completion trend chart
- Pending image analysis alerts

**Mobile & Responsive**
- Mobile hamburger navigation with drawer
- Card-based table layouts on small screens
- Touch-target optimization (44×44px minimums)
- Responsive breakpoints throughout

### What's Planned (FEATURES.md Backlog)

| ID | Feature | Priority | Status |
|----|---------|----------|--------|
| F-0003 | Batch Image Processing | P2 | Proposed |
| F-0004 | OCR Preprocessing (Tesseract) | P3 | Proposed |
| F-0005 | Image Annotations for AI Guidance | P2 | Proposed |
| F-0006 | result_schema Cleanup & Repurposing | P3 | Proposed |
| F-0007 | AI Embeddings & Protocol Generation | P2 | Proposed |

---

## Gap Analysis Matrix

### Category: Core ELN Features

| Feature | Status | Gap Severity | Priority | Notes |
|---------|--------|-------------|----------|-------|
| Protocol authoring & versioning | Yes | — | — | Graph editor with full versioning, draft/publish, approval workflow |
| Experiment/run execution & tracking | Yes | — | — | Step-by-step execution with role assignments, status tracking |
| Data capture (manual, instrument, image) | Yes | — | — | Manual entry, AI image extraction, parameter tagging |
| Audit trail | Yes | — | — | Audit log with actor, timestamps, and change tracking. Sufficient for research use |
| Electronic signatures | No | Low | Phase 2 | Deferred — not required for research use. Foundation exists in data model for future GMP phase |
| Witness countersigning | No | Low | Phase 2 | Deferred — GMP requirement only |
| PDF/report generation | Yes | — | — | SOP + batch record PDFs with customizable formatting |
| Search (full-text, metadata, semantic) | Partial | High | High | Basic filtering exists; no full-text search across protocols/runs. Critical as data grows |
| Templates & reusable components | Yes | — | — | UnitOpDefinition library, protocol-to-run templating, save-as-new-unitOp |

### Category: Collaboration & Workflow

| Feature | Status | Gap Severity | Priority | Notes |
|---------|--------|-------------|----------|-------|
| Role-based access control (RBAC) | Yes | — | — | VIEW/EDIT/APPROVE/ADMIN per object, user or team principals |
| Team/project-based permissions | Yes | — | — | Org → Team → Project hierarchy with permission inheritance |
| Review & approval workflows | Partial | Low | Low | Protocol approval exists; multi-step approval chains are a GMP concern |
| Commenting & annotations | No | High | High | No comments on protocols, runs, or steps. Researchers need this for daily collaboration |
| Real-time collaboration | No | Low | Deferred | Single-user editing. Not needed for small research teams; massive architectural cost |
| Task assignment & tracking | Partial | Low | Low | Role assignments exist; no generic task/to-do system |
| @mentions & notifications | Partial | Medium | Medium | Notifications exist; @mentions depend on commenting system (GAP-002) |
| Activity feeds | Yes | — | — | Per-project audit log with filtering, dashboard activity feed |

### Category: Data & Analytics

| Feature | Status | Gap Severity | Priority | Notes |
|---------|--------|-------------|----------|-------|
| Structured data export (CSV, Excel, JSON) | Yes | — | — | Multi-run, multi-format export with column selection |
| Export pipeline quality | Partial | High | High | Works but needs presets, clipboard copy, and Prism/SAS-friendly formatting. Core value prop |
| Custom dashboards & KPIs | Partial | Low | Low | Basic dashboard exists. Not our job — scientists use Prism/SAS for analysis |
| Trend analysis across runs | No | Low | Deferred | Scientists use Prism/SAS/JMP for this. Building it in-app would be a mediocre duplicate |
| SPC charts (Statistical Process Control) | No | Low | Deferred | Same rationale — dedicated tools do this better |
| Comparison views (run vs run) | No | Low | Deferred | Export and compare in analysis tools |
| Data visualization (charts, graphs) | Partial | Low | Low | Completion trend chart exists. Parameter-level charting deferred to analysis tools |
| Inventory/reagent tracking | No | Low | Deferred | LIMS territory; out of scope for MVP |
| Equipment/instrument management | Partial | Low | Low | Equipment CRUD exists; sufficient for research use |

### Category: Integration & Connectivity

| Feature | Status | Gap Severity | Priority | Notes |
|---------|--------|-------------|----------|-------|
| LIMS integration | No | Low | Deferred | Out of scope for research MVP |
| Instrument data import (CSV, formats) | No | Medium | High | No CSV import; scientists must manually transcribe from instrument exports. Quick win |
| REST API for third-party integration | Partial | Low | Low | Full internal API exists; public API docs can come later |
| Webhook support | Partial | Low | Low | Outbound webhook exists; sufficient for now |
| SSO / LDAP / Active Directory | No | Low | Phase 2 | Enterprise requirement; not needed for small research teams on trial/subscription |
| Cloud storage integration (S3, Azure) | No | Medium | Medium | Needed for SaaS deployment; images on local disk won't scale |
| Calendar/scheduling integration | No | Low | Low | Nice to have |

### Category: Regulatory & Compliance

> Note: All regulatory/compliance features are **Phase 2 (GMP)**. The current audit trail is sufficient for research use. The data model already has the right foundation (audit logs, permission levels, versioning, approval workflows) for adding compliance later.

| Feature | Status | Gap Severity | Priority | Notes |
|---------|--------|-------------|----------|-------|
| Audit trail | Yes | — | — | Audit log with actor, timestamps, changes JSONB. Sufficient for research |
| Tamper-evident logging (hash chaining) | No | Low | Phase 2 | Add when pursuing GMP customers |
| Electronic signatures (21 CFR Part 11) | No | Low | Phase 2 | Expensive to implement properly; defer until revenue justifies |
| Data integrity controls (ALCOA+) | Partial | Low | Phase 2 | Attributable + contemporaneous exist; full ALCOA+ is GMP scope |
| Version history with diff views | Partial | Medium | Medium | Useful for research too — helps reviewers see what changed |
| Access logs & permission audit | Partial | Low | Phase 2 | Audit log tracks entity changes; dedicated access logs are GMP scope |
| Data retention policies | No | Low | Phase 2 | Not needed for research; required for GMP |
| Validation documentation (IQ/OQ/PQ) | No | Low | Phase 2 | Requires QA consulting; defer entirely |

### Category: AI & Automation

| Feature | Status | Gap Severity | Priority | Notes |
|---------|--------|-------------|----------|-------|
| AI-assisted data extraction from images | Yes | — | — | Multi-provider vision AI with conversational analysis. **Paid tier feature gate** |
| Natural language protocol generation | No | Low | Low | Planned (F-0007); cool demo but not daily-use for research |
| Anomaly detection in run data | No | Low | Deferred | Scientists evaluate data in analysis tools post-export |
| Predictive analytics | No | Low | Deferred | Premature; requires data accumulation and data science expertise |
| Automated deviation flagging | Partial | Low | Low | Offline value discrepancy exists; real-time flagging is a nice-to-have |
| Smart suggestions | No | Low | Deferred | Not needed for MVP |
| Voice-to-text for hands-free entry | No | Medium | Medium | Core product vision; high value for gloved scientists in the lab |

### Category: Mobile & Offline

| Feature | Status | Gap Severity | Priority | Notes |
|---------|--------|-------------|----------|-------|
| Tablet-optimized interface | Yes | — | — | Responsive design implemented (F-0008) |
| Offline data capture | Yes | — | — | Full field mode with encrypted sessions (F-0002) |
| Camera integration for image capture | Yes | — | — | Image upload in run execution and field mode |
| Barcode/QR code scanning | No | High | High | No barcode scanning for equipment, reagents, or samples. Common lab workflow |
| Push notifications | Partial | Low | Low | PWA installable; no native push via Web Push API |
| Field mode for disconnected labs | Yes | — | — | Comprehensive offline execution with sync (F-0002) |

### Category: User Experience

| Feature | Status | Gap Severity | Priority | Notes |
|---------|--------|-------------|----------|-------|
| Onboarding / guided tours | No | Medium | Medium | No first-run tutorial, tooltips, or walkthrough |
| Keyboard shortcuts | Partial | Low | Low | Some exist in protocol editor (xyflow defaults); no documented shortcut system |
| Undo/redo support | No | Medium | High | No undo/redo in protocol editor or run execution. High-impact usability gap |
| Drag-and-drop interactions | Yes | — | — | Protocol editor drag-drop, unit op library drag |
| Dark mode | No | Low | Low | Blocked by hardcoded colors (TD-0055); nice-to-have |
| Accessibility (WCAG 2.1 AA) | Partial | Medium | Medium | Semantic HTML and ARIA in shadcn components; no formal audit or compliance testing |
| Localization / i18n | No | Low | Low | English only; relevant for global biotech orgs |
| Help system / contextual docs | No | Medium | Medium | No in-app help, tooltips on complex features, or documentation links |

---

## Top Priority Gaps (GCT Research MVP)

### [GAP-001] GCT-Specific Unit Operations Library & Protocol Templates
- **Category**: Product / Domain Fit
- **Current State**: The unit op library exists (`UnitOpDefinition` model, seed script, searchable/categorized sidebar) but contains generic operations. No cell therapy-specific unit ops, no pre-configured parameter schemas for GCT workflows, no sample protocols.
- **Gap**: A GCT PD scientist opening the app for the first time sees generic building blocks instead of their actual workflow. They have to manually create every unit op (transfection, cell expansion, viral vector production, etc.) from scratch. This makes the trial experience slow and unimpressive.
- **Why It Matters**: This is the #1 differentiator against generic ELNs. When a CAR-T scientist opens the app and sees "Lentiviral Transduction" with pre-configured params (MOI, transduction efficiency, cell density), they know this tool was built for them. Without it, we're just another ELN.
- **Suggested Approach**:
  1. Expand `scripts/seed_unit_ops.py` with GCT-specific operations organized by category:
     - Upstream: plasmid prep, cell thaw, seeding, expansion, transfection/transduction, media exchange, harvest
     - Downstream: clarification, chromatography, TFF, buffer exchange, sterile filtration
     - Formulation: excipient addition, fill/finish, cryopreservation, visual inspection
     - QC: cell count/viability, flow cytometry, pH/DO/metabolite, endotoxin, sterility, potency assay
  2. Each unit op includes a `param_schema` with GCT-standard parameters (cell density, viability, MOI, titer, recovery, purity, etc.) with appropriate types and units
  3. Create 2-3 complete sample protocol templates as seed data:
     - CAR-T manufacturing (isolation → activation → transduction → expansion → harvest → formulation → cryo)
     - Lentiviral vector production (seeding → transfection → harvest → clarification → chromatography → TFF → formulation)
     - AAV vector production
  4. Sample protocols load in the onboarding flow so new users can explore a populated editor immediately
- **Effort Estimate**: M (3-5 days for seed data + templates)
- **Recommended Priority**: High — Must ship. This is the "built for cell therapy" moment

### [GAP-002] Undo/Redo in Protocol Editor
- **Category**: User Experience
- **Current State**: No undo/redo capability. Accidental deletions require reloading last saved version, losing all unsaved work.
- **Gap**: No command history, no Ctrl+Z / Ctrl+Y support. The protocol editor is the core creative tool and this is a basic usability expectation.
- **Why It Matters**: Every design/editing tool has undo/redo. Scientists building complex protocols (20-50+ steps) will make mistakes and need to quickly revert. This is the #1 usability complaint for any editor without it.
- **Suggested Approach**:
  1. Implement a command stack pattern: before each mutation, push a snapshot (or command + inverse) onto an undo stack
  2. Track: node add/delete/move, edge add/delete, property changes, swimlane operations
  3. Wire Ctrl+Z (undo) and Ctrl+Shift+Z / Ctrl+Y (redo) keyboard shortcuts
  4. Add undo/redo buttons to the canvas toolbar
  5. Limit stack depth (e.g., 50 actions) to manage memory
- **Effort Estimate**: M (3-5 days)
- **Recommended Priority**: High — Must ship

### [GAP-003] Export Pipeline Improvements
- **Category**: Data & Analytics
- **Current State**: Export works — multi-run, multi-format (CSV/Excel/JSON), column selection, preview grid. But it's one-shot: scientists reconfigure every time, can't copy to clipboard, and output formatting may need cleanup before Prism/SAS can use it.
- **Gap**: No saved export presets (column selections + format + layout). No one-click clipboard copy for pasting into Prism/Excel. No Prism-friendly or SAS-friendly output templates. Since export-to-analysis-tools is the core value proposition, this pipeline must be frictionless.
- **Why It Matters**: If scientists spend 10 minutes reformatting every export before it works in Prism, the app feels like a burden rather than a time-saver. The entire value of the tool is: capture data cleanly, get it into analysis tools fast.
- **Suggested Approach**:
  1. Save export presets per-project (column selection, format, layout stored in project settings JSONB)
  2. "Copy to Clipboard" button on export preview — tab-separated for direct paste into Excel/Prism
  3. Prism template format: parameter-per-column with run labels as row headers (Prism's expected layout)
  4. Optional: "Export to Prism" preset that auto-selects the right columns and layout
  5. Remember last-used export settings per user
- **Effort Estimate**: S-M (2-4 days)
- **Recommended Priority**: High — Must ship

### [GAP-004] Full-Text Search Across Entities
- **Category**: Core ELN Features
- **Current State**: Basic filtering on list pages (name contains). No global search. No search across protocol content, run data, or audit entries.
- **Gap**: Cannot search for "which runs used pH above 7.0" or "find all protocols mentioning centrifugation." Scientists accumulate protocols and runs quickly and need to find things.
- **Why It Matters**: Discoverability becomes critical once users have 20+ protocols. Every ELN offers at least basic search. Without it, scientists resort to naming conventions and manual browsing.
- **Suggested Approach**:
  1. Add PostgreSQL full-text search (tsvector/tsquery) on Protocol.name, Protocol.description, Run.name, and JSONB graph content
  2. Global search bar in the app header with instant results
  3. Faceted results (protocols, runs, projects) with filtering
  4. Index JSONB fields: extract node labels and parameter values for indexing
- **Effort Estimate**: M (3-5 days)
- **Recommended Priority**: High — Must ship

### [GAP-005] Commenting & Annotation System
- **Category**: Collaboration & Workflow
- **Current State**: No commenting anywhere. Scientists cannot leave notes, ask questions, or flag issues on protocols or runs.
- **Gap**: No threaded comments on protocols, runs, steps, or images. No @mentions. All discussion happens outside the app (email, Slack), losing context.
- **Why It Matters**: Research is collaborative. PD teams discuss protocols, flag observations during runs, and document decisions. Comments are where institutional knowledge lives.
- **Suggested Approach**:
  1. Add `Comment` model (entity_type, entity_id, parent_id for threading, author_id, body, mentions JSONB)
  2. API endpoints for CRUD + listing (with pagination)
  3. Comment sidebar/panel on protocol editor, run detail, and step detail
  4. @mention autocomplete from project members
  5. Notification integration (COMMENT_ADDED, MENTION event types)
- **Effort Estimate**: M (3-5 days)
- **Recommended Priority**: High — Must ship

### [GAP-006] Barcode/QR Code Scanning
- **Category**: Mobile & Offline
- **Current State**: Equipment management exists (CRUD). No barcode or QR code capabilities.
- **Gap**: No scanning for equipment, reagent lots, or sample IDs. Scientists manually type identifiers, which is error-prone and slow with gloves.
- **Why It Matters**: Labs use barcodes extensively. Scanning is 5-10x faster than manual entry and eliminates transcription errors. This is what makes a lab tool feel like it was built for a lab.
- **Suggested Approach**:
  1. Integrate a browser-based barcode scanner (e.g., `html5-qrcode` or `zxing-js/browser`)
  2. Add scan button to equipment picker, parameter entry fields, and run step forms
  3. Support Code 128, Code 39, QR, DataMatrix (common lab barcodes)
  4. Optional: generate QR codes for internal entities (run ID, equipment ID)
- **Effort Estimate**: S-M (2-4 days)
- **Recommended Priority**: High — Should ship

### [GAP-007] Instrument Data Import (CSV/File)
- **Category**: Integration & Connectivity
- **Current State**: All parameter data enters via manual entry or AI image analysis. No file import.
- **Gap**: No CSV/Excel upload for instrument data. Plate readers, chromatography systems, and spectrophotometers all export CSV. Scientists must manually transcribe values.
- **Why It Matters**: Eliminates manual entry errors and saves significant time per run. This is a common ask from any scientist who works with instruments that export data.
- **Suggested Approach**:
  1. Add "Import Data" button to run step parameter forms
  2. Accept CSV/Excel uploads, parse with column mapping UI
  3. Backend: `POST /runs/{id}/steps/{step_id}/import` endpoint
  4. Support column-to-parameter mapping (user selects which CSV column maps to which param)
  5. Preview imported values before confirming
- **Effort Estimate**: M (3-5 days)
- **Recommended Priority**: High — Should ship

### [GAP-008] Onboarding / Guided Tour
- **Category**: User Experience
- **Current State**: No first-run experience. New users land on the dashboard with no guidance.
- **Gap**: No tutorial, no tooltips on complex features, no walkthrough for first protocol creation. Scientists need to figure out the graph editor on their own.
- **Why It Matters**: With a 30-day trial model, first impressions determine conversion. If a scientist can't figure out how to create their first protocol in 10 minutes, they'll close the tab and never return.
- **Suggested Approach**:
  1. First-login detection → guided tour overlay (protocol creation → run execution → export)
  2. Contextual tooltips on non-obvious features (drag unit ops, swimlane resize, handle orientation)
  3. "Sample protocol" pre-loaded so users can explore a populated editor immediately
  4. Help button linking to docs (can be a simple static page initially)
- **Effort Estimate**: M (3-5 days)
- **Recommended Priority**: High — Should ship (critical for trial conversion)

### [GAP-009] Voice-to-Text for Hands-Free Data Entry
- **Category**: AI & Automation
- **Current State**: No voice input. All data entry requires touch/keyboard.
- **Gap**: Scientists with gloved hands, handling hazardous materials, or monitoring equipment can't easily type on a tablet.
- **Why It Matters**: Core product vision mentions "voice-enabled." This is a real differentiator — no competitor does this well. High value for lab work with gloves.
- **Suggested Approach**:
  1. Use the Web Speech API (SpeechRecognition) for browser-native voice capture
  2. Add microphone button to parameter entry fields
  3. Optional: pipe audio to AI provider (audio capability already in config model) for higher accuracy
  4. Visual feedback: waveform indicator, transcription preview before confirming
- **Effort Estimate**: M (3-5 days)
- **Recommended Priority**: Medium — Nice to have for MVP, differentiator for marketing

### [GAP-010] Protocol Version Diff View
- **Category**: User Experience
- **Current State**: Version history with prev/next browsing exists. No visual diff.
- **Gap**: Users can browse versions but can't see what changed. Must visually compare two versions manually.
- **Why It Matters**: Useful even for research — when iterating on protocols, scientists want to see what they changed between versions.
- **Suggested Approach**:
  1. Compute graph diff: compare nodes (added/removed/modified), edges (added/removed), metadata
  2. Color-coded render (green=added, red=removed, yellow=modified)
  3. List of changes sidebar with click-to-navigate
- **Effort Estimate**: M (3-5 days)
- **Recommended Priority**: Medium — Nice to have

### [GAP-011] Cloud Storage for Images (S3/Azure)
- **Category**: Integration & Connectivity
- **Current State**: Images stored on local disk. Works for development but won't scale for SaaS deployment.
- **Gap**: Local file storage means data loss risk, no CDN, and complicated backups. For a SaaS product, images need to live in cloud storage.
- **Why It Matters**: Infrastructure requirement for going live as a SaaS product. Not user-facing but blocks production deployment.
- **Suggested Approach**:
  1. Abstract file storage behind an interface (local vs S3-compatible)
  2. Use `boto3` for S3 or compatible (Cloudflare R2 is cheap)
  3. Presigned URLs for direct browser upload/download
  4. Migrate existing local files on deployment
- **Effort Estimate**: M (3-5 days)
- **Recommended Priority**: Medium — Required before production SaaS launch

---

## Recommendations (Solo Dev, GCT-Focused)

### Must Ship for MVP (blocks trial conversion)
1. **GCT unit ops library & templates** (GAP-001) — 3-5 days. "Built for cell therapy" moment
2. **Undo/redo in protocol editor** (GAP-002) — 3-5 days. Basic usability expectation
3. **Export pipeline improvements** (GAP-003) — 2-4 days. Core value prop must be frictionless
4. **Full-text search** (GAP-004) — 3-5 days. Critical once teams have 20+ protocols
5. **Commenting system** (GAP-005) — 3-5 days. Research teams need to collaborate in-app

### Should Ship Before Launch
6. **Barcode/QR scanning** (GAP-006) — 2-4 days. Makes it feel like a lab tool
7. **Instrument data import** (GAP-007) — 3-5 days. Eliminates manual transcription
8. **Onboarding / guided tour** (GAP-008) — 3-5 days. CAR-T sample protocol walkthrough. Critical for trial conversion
9. **Cloud storage for images** (GAP-011) — 3-5 days. Required for SaaS deployment

### Nice to Have (Post-Launch)
10. **Voice-to-text** (GAP-009) — Differentiator, good for marketing
11. **Protocol version diff** (GAP-010) — Useful but not blocking anyone
12. **Dark mode** — Frequently requested, not a dealbreaker

### Phase 2: GMP Expansion (MRR > $10k + LOI)
- Electronic signatures / 21 CFR Part 11
- Witness countersigning
- Tamper-evident audit trail (hash chaining)
- SSO / SAML / OIDC
- Data retention policies
- Validation documentation (IQ/OQ/PQ)
- Self-hosted enterprise deployment

See `BUSINESS_STRATEGY.md` for full Phase 2 triggers, pricing, and funding strategy.

---

## Appendix: Competitor Reference

### Benchling
- **Strengths**: Full 21 CFR Part 11 compliance, electronic signatures, molecular biology tools (sequence editor, plasmid maps), LIMS integration, built-in inventory management, REST API with webhooks
- **Gap for us**: E-signatures, LIMS integration, inventory/reagent tracking, advanced search, SSO/SAML
- **Note**: Benchling is the market leader for biotech R&D; they focus on molecular biology and are weaker on process development workflows

### Dotmatics (formerly BIOVIA Notebook)
- **Strengths**: Enterprise-grade compliance (Part 11, GxP), chemical/biological data management, advanced search with structure queries, mature approval workflows, LDAP/SSO
- **Gap for us**: E-signatures, compliance certification, advanced search, LDAP auth
- **Note**: Enterprise-heavy; slower to innovate on UX. Our AI and offline capabilities are differentiators

### LabArchives
- **Strengths**: Simple notebook interface, version history with full diff, rich text entries, e-signatures with witness countersigning, cross-notebook search, affordable pricing
- **Gap for us**: E-signatures, witness countersigning, version diff views, cross-entity search
- **Note**: Simpler tool; lacks our graph-based protocol design and AI features

### Sapio Sciences
- **Strengths**: Configurable ELN + LIMS combo, built-in analytics dashboards, SPC charts, instrument integration, barcode scanning, workflow automation
- **Gap for us**: Analytics/SPC charts, instrument integration, barcode scanning, workflow automation
- **Note**: Strong on analytics and integration; our offline/field mode and AI vision are differentiators

### eLabFTW (Open Source)
- **Strengths**: Self-hosted, API-first, experiment templates, timestamping (RFC 3161), tagging system, team management, active community
- **Gap for us**: Timestamping/tamper-proof records, tagging system, self-hosted deployment option
- **Note**: Open source competitor; less polished UX but strong on data integrity and self-hosting

---

## Summary: Competitive Position

**Our differentiators** (features competitors lack or do poorly):
1. GCT-specific unit op library and protocol templates (no generic ELN does this)
2. Graph-based visual protocol design with swimlanes (unique among ELNs)
3. AI-powered image analysis with multi-turn conversation (paid tier gate)
4. Full offline field mode with encrypted sessions and background sync
5. Copy-on-write protocol → run with deviation tracking
6. Tablet-first design purpose-built for lab use with gloves
7. Team-based pricing ($299/month) — 4-6x cheaper than Benchling/LabArchives corporate

**MVP gaps to close** (for GCT PD team adoption):
1. GCT unit ops + sample protocol templates ("built for cell therapy" moment)
2. Undo/redo in protocol editor (basic usability)
3. Export pipeline (core value prop — capture data, export to Prism/SAS/Excel)
4. Full-text search (discoverability at scale)
5. Commenting (team collaboration)
6. Barcode scanning + instrument import (lab workflow efficiency)
7. Onboarding with CAR-T sample walkthrough (trial conversion)

**Deliberately deferred** (not needed for research MVP):
- In-app analytics (scientists use Prism/SAS/JMP — don't build a worse version)
- 21 CFR Part 11 / e-signatures (Phase 2 — triggers at $10k MRR + signed LOI)
- SSO/SAML (Phase 2, enterprise customers)
- Real-time collaboration (architectural overkill for small research teams)
- LIMS / inventory management (different product category)

**Sustainability path**: 50 paying GCT PD teams at $299/month = $15k MRR = full-time sustainability. 2,000+ GCT clinical programs exist — 50 teams is 2.5% penetration. Funded by SBIR Phase I ($275k non-dilutive) + strategic angels ($75-150k) to bridge the 18-24 month ramp.

Closing the MVP gaps positions the app as the purpose-built protocol execution tool for cell therapy PD — not another generic ELN, but the one that speaks their language on day one.
