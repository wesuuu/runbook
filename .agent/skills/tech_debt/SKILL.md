---
name: tech_debt
description: Analyze the codebase for technical debt and append findings to TECH_DEBT.md. Use when the user asks to "find tech debt", "audit code quality", "log technical debt", "what needs refactoring", or runs /tech_debt. Scans backend and frontend code for common debt patterns and documents them for future development.
---

# Technical Debt Analysis

Perform a structured technical debt analysis of the trellisbio codebase and append findings to `TECH_DEBT.md` in the project root.

## Analysis Categories

Scan for the following categories of technical debt:

### 1. Code Smells
- Functions/methods over 50 lines
- Files over 500 lines
- Deeply nested logic (3+ levels)
- Duplicated code patterns across files
- Unused imports, variables, or dead code paths

### 2. Missing or Incomplete Implementation
- TODO/FIXME/HACK/XXX comments in source code
- Stubbed or placeholder functions
- Empty catch/except blocks
- Features marked incomplete in `plan.md`

### 3. Type Safety & Validation
- Uses of `any` in TypeScript or missing type annotations in Python public APIs
- Missing Zod/Pydantic validation at API boundaries
- Untyped API responses in the frontend

### 4. Testing Gaps
- Files with no corresponding test coverage
- Test files with skipped or commented-out tests
- Missing integration tests for API endpoints
- Missing edge case coverage (error paths, empty states)

### 5. Security & Configuration
- Hardcoded secrets, API keys, or credentials
- Missing input sanitization
- Plaintext storage of sensitive data (noted TODOs)
- Missing CORS, rate limiting, or auth checks

### 6. Architecture & Design
- Tight coupling between modules
- Missing error handling or inconsistent error patterns
- Direct DB queries outside service/repository layers
- Frontend components with mixed concerns (data fetching + rendering)

### 7. Dependencies & Tooling
- Outdated or pinned dependencies
- Missing linting/formatting enforcement
- No CI/CD pipeline defined
- Missing pre-commit hooks

## Output Format

For each finding, append an entry to `TECH_DEBT.md` using this format:

```markdown
### [TD-XXXX] Short description
- **Category**: (one of the categories above)
- **Severity**: Critical | High | Medium | Low
- **Location**: `file/path.py:line` or `file/path.ts:line`
- **Description**: What the issue is and why it matters
- **Suggested Fix**: Brief description of how to resolve it
- **Effort**: S (< 1hr) | M (1-4hr) | L (4-8hr) | XL (> 1 day)
```

## Severity Guidelines

- **Critical**: Security vulnerabilities, data loss risks, production blockers
- **High**: Missing tests for critical paths, broken patterns, significant code smells
- **Medium**: Inconsistencies, moderate code smells, missing validations
- **Low**: Style issues, minor TODOs, nice-to-have improvements

## Process

1. Read the existing `TECH_DEBT.md` to understand what's already documented and determine the next TD number
2. Use Explore agents to scan `backend/app/` and `frontend/src/` in parallel
3. Cross-reference with `plan.md` for known incomplete features
4. Grep for TODO/FIXME/HACK/XXX comments across the codebase
5. Deduplicate against existing entries — do NOT add duplicates
6. Append only NEW findings to `TECH_DEBT.md`, preserving existing entries
7. Print a summary: count of new items by category and severity
