---
name: td_add
description: Log a tech debt item to the ClickUp TECH_DEBT list. Use when the user wants to "log tech debt", "add a TD item", "track tech debt", or runs /td_add. Takes a description of a specific tech debt issue and creates a task in ClickUp.
---

# Add Tech Debt Item

Create a new tech debt task in the **ClickUp TECH_DEBT list** (list ID: `901712289455`).

## Process

1. **Fetch existing tasks from ClickUp** using `clickup_filter_tasks` on list `901712289455` to check for duplicates and determine the next item number (TD-XXXX).
2. **Gather details** from the user's description. If the description is vague, investigate the codebase to understand the issue — but keep the report grounded in what was described.
3. **Research the codebase** to identify the scope and location of the debt. Use Grep/Glob to find relevant files and understand the problem. This helps you write accurate location and fix notes.
4. **Create the task in ClickUp** using `clickup_create_task` on list `901712289455` with:
   - **Name**: `[TD-XXXX] Short description`
   - **Priority**: Map severity — Critical → urgent, High → high, Medium → normal, Low → low
   - **Description**: Full tech debt report in markdown (see format below)
5. **Print a summary** of what was logged, including the ClickUp task URL.

## Tech Debt Item Format

The task description (markdown) should follow this template:

```markdown
**Category**: Code Smells | Missing Implementation | Type Safety | Testing Gaps | Security | Architecture | Dependencies
**Severity**: Critical | High | Medium | Low
**Location**: `file/path.py:line` or `file/path.ts:line`

**Description**: What the issue is and why it matters.

**Suggested Fix**: Brief description of how to resolve it.

**Effort**: S (< 1hr) | M (1-4hr) | L (4-8hr) | XL (> 1 day)
```

## Severity Guidelines

- **Critical**: Security vulnerabilities, data loss risks, production blockers
- **High**: Missing tests for critical paths, broken patterns, significant code smells
- **Medium**: Inconsistencies, moderate code smells, missing validations
- **Low**: Style issues, minor TODOs, nice-to-have improvements

## Guidelines

- **Number sequentially**: TD-0001, TD-0002, etc. Check existing ClickUp tasks for the next number.
- **Don't duplicate**: If a similar item already exists in ClickUp, update it with additional context instead of creating a new one.
- **Be specific**: Location should point to exact files and line numbers where possible.
- **Keep fix notes brief**: Just enough to point a developer in the right direction.
- **Default severity**: Use `normal` (Medium) unless the user specifies otherwise or the impact is clearly higher/lower.
