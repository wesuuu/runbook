---
name: add-task
description: Use when the user wants to create a ClickUp task -- feature request, bug report, QA issue, tech debt, or future idea. Also triggers on "add a task", "log a ticket", "create a ticket", "add to clickup", or /add_task.
---

# Add Task to ClickUp

Create a well-scoped task in the appropriate ClickUp list. Interview the caller until you understand the full picture before writing anything.

## When to Use

- User describes something that should be tracked (bug, feature idea, debt, QA finding)
- User explicitly asks to create a ClickUp task
- You discover an issue during implementation that belongs in a different task

**Don't use when:** User wants to update an existing task (use `/task_update`) or implement a task (use `/implement_task`).

## ClickUp Lists

| List | ID | Prefix | Use for |
|---|---|---|---|
| FEATURES | `901712289454` | F-XXXX | New functionality |
| BUGS | `901712289456` | BUG-XXXX | Broken behavior |
| QA | `901712290772` | QA-XXXX | Testing issues found during QA |
| TECH_DEBT | `901712289455` | TD-XXXX | Refactors, code quality, missing tests |
| FUTURE | `901712303159` | FUT-XXXX | Ideas not ready for implementation |

## Process

### 1. Determine the list

If the user specified a type, use that list. Otherwise ask which of the five categories fits.

### 2. Interview for scope

Ask questions **one at a time**. Adapt to task type:

- **Features**: Problem being solved, expected behavior, edge cases, scope (backend/frontend/full-stack), dependencies
- **Bugs**: Expected vs actual, reproduction steps, severity, location in app
- **QA / tech debt / future**: What was observed, where, risk of inaction

**Stop when** you can write testable acceptance criteria (features) or clear reproduction steps (bugs). 2-4 questions is usually enough.

### 3. Research and deduplicate

Grep/read relevant files to confirm scope. `clickup_filter_tasks` on the target list to check for duplicates -- offer to update if similar exists. Determine next sequential ID from existing tasks.

### 4. Draft, confirm, create

Present the full description to the user before creating. After confirmation, `clickup_create_task` with:
- **Name**: `[PREFIX-XXXX] Short title`
- **Priority**: urgent / high / normal / low (default: normal)
- **Description**: Markdown body per format below

Print the task name and ClickUp URL when done.

## Description Format

All tasks use this structure. Include only the fields relevant to the task type.

```markdown
**Priority**: P0 (Critical) | P1 (High) | P2 (Medium) | P3 (Low)
**Severity**: Critical | High | Medium | Low          <!-- bugs only -->
**Scope**: Backend | Frontend | Full Stack
**Location**: `file/path:line`                         <!-- if known -->

**Description**: What and why.

**Acceptance Criteria**:                               <!-- features -->
- [ ] Criterion 1
- [ ] Criterion 2

**Steps to Reproduce**:                                <!-- bugs -->
1. Step one
2. Step two

**Expected**: What should happen.                      <!-- bugs -->
**Actual**: What happens instead.                      <!-- bugs -->

**Recommendation**: What should be done.               <!-- QA/TD/future -->
**Implementation Notes**: Key files/modules affected.
**Dependencies**: F-XXXX or None.
**Effort**: S (<1hr) | M (1-4hr) | L (4-8hr) | XL (>1 day)
```

## Common Mistakes

- **Skipping the interview**: Creating a vague task from a one-liner. 2-4 questions prevent wasted implementation time later.
- **Not checking duplicates**: Similar task already exists, now there are two competing tickets.
- **Over-interviewing**: 6+ questions when the scope is already clear. Stop when you can write acceptance criteria.
- **Wrong list**: Logging a broken feature as tech debt instead of a bug. If something worked and now doesn't, it's a bug.

## Rules

- **Interview first.** Don't create a vague task.
- **One question at a time.** Don't overwhelm.
- **Draft before creating.** User confirms before it hits ClickUp.
- **Don't duplicate.** Check existing tasks first.
- **Default priority**: normal, unless user specifies otherwise.
