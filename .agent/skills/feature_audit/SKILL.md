---
name: feature_audit
description: Audit how a feature works end-to-end across DB, backend, and frontend. Use when the user asks "how does X work", "audit feature X", "trace the data flow for X", "explain feature X end-to-end", or runs /feature_audit. Shows DB schema, backend endpoints/logic, frontend components, and data flow with code examples. If the user follows up with suggestions or issues, offers to log them via /td_add, /qa_add, /feature_add, or /bug_add.
---

# Feature Audit

Trace how a feature works end-to-end across the database, backend, and frontend layers — with code examples showing the data flow.

## Inputs

The user provides a feature name or description (e.g., "run assignments", "protocol editor", "experiment execution", "audit logging"). If no feature is specified, ask the user what feature they want to audit.

## Process

### Phase 1: Deep Investigation

Use Explore agents and/or Grep/Glob/Read to investigate the feature across all layers. Run searches in parallel where possible.

1. **Database Layer**
   - Find the relevant SQLAlchemy models in `backend/app/models/`
   - Identify table names, columns, relationships, JSONB fields, and foreign keys
   - Check for Alembic migrations related to the feature in `backend/alembic/versions/`

2. **Backend Layer**
   - Find API endpoints in `backend/app/api/endpoints/` that serve this feature
   - Trace the request/response flow: router → service logic → DB queries
   - Find Pydantic schemas in `backend/app/schemas/` (request + response models)
   - Note any business logic, validations, or side effects (e.g., audit logging)

3. **Frontend Layer**
   - Find Svelte components/pages that consume the feature
   - Trace API calls in `frontend/src/lib/api.ts` or component-level fetches
   - Identify state management patterns (runes, context, stores)
   - Note UI components involved (forms, tables, modals, graph nodes)

4. **Data Flow**
   - Map the full journey: User action → Frontend call → API endpoint → DB operation → Response → UI update
   - Identify any intermediate transformations, caching, or side effects

### Phase 2: Present the Audit

Present findings in a structured format with actual code snippets from the codebase:

```
## Feature Audit: [Feature Name]

### 1. Database Schema
- **Table(s)**: table names and purpose
- **Key columns**: column definitions with types
- **Relationships**: foreign keys and joins
- **Code**: Actual model definition snippet

### 2. Backend API
- **Endpoints**: METHOD /path — what it does
- **Schemas**: Request/response Pydantic models
- **Business Logic**: Key operations and validations
- **Code**: Actual endpoint and schema snippets

### 3. Frontend
- **Components**: Which .svelte files render this feature
- **API Calls**: How the frontend fetches/sends data
- **State Management**: How data is stored and updated in the UI
- **Code**: Actual component/API call snippets

### 4. Data Flow
- Step-by-step trace from user action to DB and back
- Diagram or numbered list showing each hop

### 5. Observations
- Any inconsistencies, gaps, or noteworthy patterns found during the audit
```

Use real code snippets with file paths and line numbers (e.g., `backend/app/models/science.py:42`). Keep snippets focused — show the relevant parts, not entire files.

### Phase 3: Follow-Up (Conversational)

After presenting the audit, if the user responds with:
- Suggestions, improvements, or "it should work differently"
- "That's not right" or "there's a problem with..."
- Identifying gaps, bugs, or tech debt
- Requesting changes or enhancements

Then **ask the user** which list they'd like to add it to:

> "Would you like me to log this? I can add it to one of these lists:
> - `/feature_add` — if this is a new feature or enhancement
> - `/bug_add` — if this is a bug that needs fixing
> - `/qa_add` — if this is a QA issue to test/verify
> - `/td_add` — if this is tech debt to address
>
> Which one fits best, or should I skip it?"

If the user picks one, invoke the corresponding skill with the context from the audit and the user's feedback. Do NOT auto-log without asking.

## Guidelines

- **Be thorough**: Check all three layers. A feature might span multiple models, endpoints, and components.
- **Show real code**: Always include actual snippets from the codebase with file paths and line numbers.
- **Stay factual**: Report what the code actually does, not what documentation says it should do.
- **Note gaps**: If a layer is missing (e.g., no frontend for a backend-only feature), say so explicitly.
- **Keep it scannable**: Use headers, bullet points, and short code blocks. The user should be able to quickly find the layer they care about.
- **Multiple features**: If the user's query touches multiple features, audit each one or ask which to focus on.
