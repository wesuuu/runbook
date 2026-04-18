---
name: add-task
description: Use when the user wants to create a ClickUp task -- feature request, bug report, QA issue, tech debt, or future idea. Also triggers on "add a task", "log a ticket", "create a ticket", "add to clickup", or /add_task.
---

# Add Task to ClickUp

Create a well-scoped task in the appropriate ClickUp list. Interview the caller until you understand the full picture before writing anything.

## 🚨 CRITICAL: Task Name Format

**Task names MUST follow: `[PREFIX-XXXX] Short title`**

Where `PREFIX-XXXX` is the **NEXT sequential ID** determined from existing tasks in that list.

❌ **Wrong:** "Chat disabled for non-Pro users without AI configured"
✅ **Right:** "BUG-0050 Chat disabled for non-Pro users without AI configured"

This is not optional. The sequential ID is how tasks are referenced and searched. Without it, the task is unfindable.

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

### 3. Research, deduplicate, and GET THE SEQUENTIAL ID

Grep/read relevant files to confirm scope. Use `clickup_filter_tasks` on the target list to check for duplicates -- offer to update if similar exists. 

**CRITICAL:** Before drafting, look at all existing tasks in the target list. Find the highest number. Increment it. This becomes your `XXXX` for the task name.

Example: If BUG-0049 is the highest, your next task is **BUG-0050**.

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

| Mistake | Fix | Severity |
|---------|-----|----------|
| Creating task name WITHOUT `[PREFIX-XXXX]` | You MUST look up the next sequential ID first. Non-negotiable. | 🔴 CRITICAL |
| Thinking "the user can add the number later" | No. The sequential ID belongs in the task name at creation. If you forget it, delete and recreate. | 🔴 CRITICAL |
| Not determining the next sequential ID before drafting | Look at all existing tasks in the list. Find the highest number. Increment it. Do this BEFORE you draft anything. | 🔴 CRITICAL |
| Skipping the interview | Creating a vague task from a one-liner. 2-4 questions prevent wasted implementation time later. | 🟡 HIGH |
| Not checking duplicates | Similar task already exists, now there are two competing tickets. | 🟡 HIGH |
| Over-interviewing | 6+ questions when the scope is already clear. Stop when you can write acceptance criteria. | 🟡 MEDIUM |
| Wrong list | Logging a broken feature as tech debt instead of a bug. If something worked and now doesn't, it's a bug. | 🟡 MEDIUM |

## Rules

- **Interview first.** Don't create a vague task.
- **One question at a time.** Don't overwhelm.
- **Look up sequential ID before drafting.** Find the highest number in the list, increment it.
- **Draft before creating.** User confirms before it hits ClickUp.
- **Task name MUST be `[PREFIX-XXXX] Short title`.** No exceptions. Ever.
- **Don't duplicate.** Check existing tasks first.
- **Default priority**: normal, unless user specifies otherwise.

## 🚨 Red Flags

These thoughts mean STOP — you're about to violate the sequential ID requirement:

- ❌ "I'll just create the task and they can add the number later"
- ❌ "The sequential ID isn't critical, the content is"
- ❌ "I can look up the number after drafting"
- ❌ "This is a simple task, I don't need to follow the full process"
- ❌ "The task name doesn't have the number yet, but I'll mention it to the user"

**All of these mean: STOP. Determine the sequential ID BEFORE you draft or create anything.**
