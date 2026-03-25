---
name: bug_add
description: Log a bug to the ClickUp BUGS list. Use when the user wants to "report a bug", "log a bug", "file a bug", "add a bug", or runs /bug_add. Takes a bug description and creates a detailed bug report with reproduction steps and expected behavior.
---

# Add Bug Report

Create a new bug report task in the **ClickUp BUGS list** (list ID: `901712289456`).

## Process

1. **Fetch existing tasks from ClickUp** using `clickup_filter_tasks` on list `901712289456` to check for duplicates and determine the next bug number (BUG-XXXX).
2. **Gather details** from the user's description. If the description is vague, investigate the codebase to understand the issue — but keep the report grounded in what was described.
3. **Research the codebase** to identify the likely source of the bug. Use Grep/Glob to find relevant files, read the code, and understand the failure path. This helps you write accurate location and root cause notes.
4. **Create the task in ClickUp** using `clickup_create_task` on list `901712289456` with:
   - **Name**: `[BUG-XXXX] Short description of the bug`
   - **Priority**: Map severity — Critical → urgent, High → high, Medium → normal, Low → low
   - **Description**: Full bug report in markdown (see format below)
5. **Print a summary** of what was logged, including the ClickUp task URL.

## Bug Report Format

The task description (markdown) should follow this template:

```markdown
**Severity**: Critical | High | Medium | Low
**Scope**: Backend | Frontend | Full Stack
**Location**: `file/path.ts:line` or `file/path.py:line` (if known)

**Description**: What the bug is and what impact it has.

**Steps to Reproduce**:
1. Step one
2. Step two
3. Step three

**Expected Behavior**: What should happen.

**Actual Behavior**: What actually happens.

**Root Cause** (if identified): Brief explanation of why the bug occurs.

**Suggested Fix**: Brief description of how to resolve it.

**Effort**: S (< 1hr) | M (1-4hr) | L (4-8hr) | XL (> 1 day)
```

## Severity Guidelines

- **Critical**: App crash, data loss, security vulnerability, blocks core workflows (run execution, protocol editing)
- **High**: Feature broken for all users, incorrect data displayed, auth/permission bypass
- **Medium**: Feature partially broken, UI rendering issues, edge case failures
- **Low**: Cosmetic issues, minor UX annoyances, non-blocking inconsistencies

## Guidelines

- **Number sequentially**: BUG-0001, BUG-0002, etc. Check existing ClickUp tasks for the next number.
- **Don't duplicate**: If a similar bug already exists in ClickUp, update it with additional context instead of creating a new one.
- **Be specific**: Steps to reproduce should be concrete and repeatable.
- **Include context**: Note browser, viewport, user role, or data conditions that trigger the bug if relevant.
- **Default severity**: Use `normal` (Medium) unless the user specifies otherwise or the impact is clearly higher/lower.
