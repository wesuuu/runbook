---
name: qa_add
description: Add a QA issue to the ClickUp QA list. Use when the user wants to "add a QA issue", "log a QA item", "report a QA problem", "add to QA", or runs /qa_add. Takes a QA issue description and creates a detailed report with reproduction steps.
---

# Add QA Issue

Create a new QA issue task in the **ClickUp QA list** (list ID: `901712290772`).

## Process

1. **Fetch existing tasks from ClickUp** using `clickup_filter_tasks` on list `901712290772` to check for duplicates and determine the next issue number (QA-XXXX).
2. **Gather details** from the user's description. If the description is vague, investigate the codebase to understand the issue — but keep the report grounded in what was described.
3. **Research the codebase** to identify the likely source of the issue. Use Grep/Glob to find relevant files, read the code, and understand the failure path. This helps you write accurate location and recommendation notes.
4. **Create the task in ClickUp** using `clickup_create_task` on list `901712290772` with:
   - **Name**: `[QA-XXXX] Short description of the issue`
   - **Priority**: Map severity — Critical → urgent, High → high, Medium → normal, Low → low
   - **Description**: Full QA issue report in markdown (see format below)
5. **Print a summary** of what was logged, including the ClickUp task URL.

## QA Issue Report Format

The task description (markdown) should follow this template:

```markdown
**Severity**: Critical | High | Medium | Low
**Category**: UI/UX | Functionality | Performance | Accessibility | Security | Data
**Page**: /path/to/page
**User**: (user role or email if relevant)

**Description**: What the issue is and what impact it has.

**Steps to Reproduce**:
1. Step one
2. Step two
3. Step three

**Expected**: What should happen.

**Actual**: What actually happens.

**Console Errors**: (any relevant errors, or "None observed")

**Recommendation**: How to fix it.

**Effort**: S (< 1hr) | M (1-4hr) | L (4-8hr) | XL (> 1 day)
```

## Severity Guidelines

- **Critical**: App crashes, data loss, security bypass, feature completely broken
- **High**: Feature partially broken, wrong data displayed, permission issue
- **Medium**: UI glitch, confusing UX, missing loading/error state, console errors
- **Low**: Minor styling, nice-to-have improvement, accessibility suggestion

## Guidelines

- **Number sequentially**: QA-0001, QA-0002, etc. Check existing ClickUp tasks for the next number.
- **Don't duplicate**: If a similar issue already exists in ClickUp, update it with additional context instead of creating a new one.
- **Be specific**: Steps to reproduce should be concrete and repeatable.
- **Include context**: Note browser, viewport, user role, or data conditions that trigger the issue if relevant.
- **Default severity**: Use `normal` (Medium) unless the user specifies otherwise or the impact is clearly higher/lower.
