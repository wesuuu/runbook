---
name: gap_analysis
description: Analyze the app against industry standards and competitor features to identify missing capabilities. Use when the user asks to "find missing features", "do a gap analysis", "what are we missing", "competitive analysis", or runs /gap_analysis. Produces a prioritized GAP_ANALYSIS.md document.
---

# Gap Analysis Skill

Perform a comprehensive gap analysis of the Runbook AI Co-Pilot app by comparing its current capabilities against (1) what's built in the codebase, (2) industry-standard features for digital lab notebooks / ELN platforms, and (3) common expectations for biotech PD workflow tools. Output a prioritized document of missing features and capability gaps.

## Process

### Phase 1 — Inventory Current Capabilities

Scan the codebase to build a complete picture of what exists today. Use Explore agents in parallel:

**Backend scan** (run in parallel):
1. Read all API endpoint files in `backend/app/api/endpoints/` — list every route and its purpose
2. Read all models in `backend/app/models/` — understand the data model
3. Read all services in `backend/app/services/` — understand business logic capabilities
4. Check for any AI/ML integrations, export formats, notification types

**Frontend scan** (run in parallel):
1. Read all route pages in `frontend/src/routes/` — list every user-facing page
2. Read key components in `frontend/src/lib/components/` — identify UI capabilities
3. Check `frontend/src/lib/api.ts` for all API calls being made
4. Look for any analytics, reporting, or visualization components

**Existing documentation**:
1. Read `FEATURES.md` to see planned/done features
2. Read `TECH_DEBT.md` for known limitations
3. Read `QA_SURVEY.md` for known UX issues
4. Read `CLAUDE.md` for architectural context

Compile into a "Current State" inventory organized by domain.

### Phase 2 — Industry Benchmark

Compare the current capabilities against these standard feature categories for digital lab notebooks and biotech PD tools. For each category, assess: **Has it?** (Yes/Partial/No) and **Gap severity** (Critical/High/Medium/Low/Nice-to-have).

#### Core ELN Features
- Protocol authoring and versioning
- Experiment execution and tracking
- Data capture (manual entry, instrument, image)
- Audit trail / 21 CFR Part 11 compliance readiness
- Electronic signatures and witness countersigning
- PDF/report generation
- Search (full-text, metadata, semantic)
- Templates and reusable components

#### Collaboration & Workflow
- Role-based access control (RBAC)
- Team/project-based permissions
- Review and approval workflows
- Commenting and annotations on protocols/runs
- Real-time collaboration / concurrent editing
- Task assignment and tracking
- @mentions and notifications
- Activity feeds

#### Data & Analytics
- Structured data export (CSV, Excel, JSON)
- Custom dashboards and KPIs
- Trend analysis across runs
- Statistical process control (SPC) charts
- Comparison views (run vs run, batch vs batch)
- Data visualization (charts, graphs)
- Inventory/reagent tracking
- Equipment/instrument management

#### Integration & Connectivity
- LIMS integration
- Instrument data import (CSV, instrument-specific formats)
- REST API for third-party integration
- Webhook support for event-driven automation
- SSO / LDAP / Active Directory authentication
- Cloud storage integration (S3, Azure Blob)
- Calendar/scheduling integration

#### Regulatory & Compliance
- Full audit trail with tamper-evident logging
- Electronic signatures (21 CFR Part 11)
- Data integrity controls (ALCOA+ principles)
- Version history with diff views
- Access logs and permission audit
- Data retention policies
- Validation documentation (IQ/OQ/PQ support)

#### AI & Automation
- AI-assisted data extraction from images
- Natural language protocol generation
- Anomaly detection in run data
- Predictive analytics for process optimization
- Automated deviation flagging
- Smart suggestions (next steps, parameter recommendations)
- Voice-to-text for hands-free data entry

#### Mobile & Offline
- Tablet-optimized interface
- Offline data capture
- Camera integration for image capture
- Barcode/QR code scanning
- Push notifications
- Field mode for disconnected labs

#### User Experience
- Onboarding / guided tours
- Keyboard shortcuts
- Undo/redo support
- Drag-and-drop interactions
- Dark mode / theme customization
- Accessibility (WCAG 2.1 AA)
- Localization / i18n
- Help system / contextual documentation

### Phase 3 — Prioritize Gaps

Score each identified gap using this framework:

| Factor | Weight | Scale |
|--------|--------|-------|
| **User Impact** | 40% | How much does this affect daily scientist workflows? |
| **Competitive Pressure** | 25% | Do all competitors have this? Is it a table-stakes feature? |
| **Implementation Effort** | 20% | How hard is it to build? (inverse — easier = higher score) |
| **Regulatory Risk** | 15% | Does lacking this create compliance issues? |

Assign each gap a **composite priority**: Critical, High, Medium, Low, or Nice-to-have.

### Phase 4 — Write the Document

Write findings to `GAP_ANALYSIS.md` in the project root using this format:

```markdown
# Gap Analysis — Runbook AI Co-Pilot

> Analysis date: YYYY-MM-DD
> Codebase state: (git commit hash)

## Executive Summary

Brief overview: what the app does well, what's notably missing, and top 3-5 priorities.

## Current Capabilities Inventory

### What's Built
(Organized list of existing features by domain)

### What's Planned
(Summary of FEATURES.md backlog items)

## Gap Analysis Matrix

### Category: (e.g., Core ELN Features)

| Feature | Status | Gap Severity | Priority | Notes |
|---------|--------|-------------|----------|-------|
| Feature name | Yes / Partial / No | Critical-Low | Composite score | Brief note |

(Repeat for each category from Phase 2)

## Top Priority Gaps

### [GAP-001] Short description
- **Category**: Which domain
- **Current State**: What exists today (if anything)
- **Gap**: What's missing
- **Why It Matters**: User impact + competitive/regulatory context
- **Suggested Approach**: High-level implementation direction
- **Effort Estimate**: T-shirt size (S/M/L/XL)
- **Recommended Priority**: Critical / High / Medium / Low

(Repeat for each significant gap, ordered by priority)

## Recommendations

### Quick Wins (< 1 week each)
- Bulleted list of low-effort, high-impact items

### Strategic Investments (1-4 weeks each)
- Medium-effort items that significantly close competitive gaps

### Long-term Roadmap (1+ month each)
- Large initiatives that require architectural work

## Appendix: Competitor Reference

Brief notes on what leading ELN/lab notebook platforms offer that informed this analysis:
- Benchling
- Dotmatics (formerly BIOVIA Notebook)
- LabArchives
- Sapio Sciences
- eLabFTW (open source)
```

## Guidelines

- **Be specific**: Reference actual files, endpoints, and components when describing current state.
- **Be honest**: If something is partially implemented or fragile, say so — don't mark it as "Yes".
- **Be practical**: Prioritize gaps that matter for a biotech PD scientist's daily workflow, not theoretical completeness.
- **Don't duplicate**: Cross-reference with `FEATURES.md` — if a gap is already a planned feature, note it but still assess priority.
- **Focus on the delta**: The value is in finding what's NOT in the backlog yet, not re-listing known items.
- **Include quick wins**: Identify small gaps that could be closed in a few hours — these are high-ROI.
