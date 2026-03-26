---
name: task_update
description: Update an existing ClickUp task across any list (QA, BUGS, FEATURES, TECH_DEBT). Use when the user wants to "update a task", "change task status", "add a comment to a task", "update QA-XXXX", "close BUG-XXXX", "update F-XXXX", or runs /task_update. Supports status changes, priority changes, adding comments, and updating descriptions. Useful when plans change, work is completed, or new context emerges.
---

# Update ClickUp Task

Update an existing task in any **ClickUp list** — QA, BUGS, FEATURES, or TECH_DEBT.

## List Reference

| Prefix | List | List ID |
|--------|------|---------|
| QA-    | QA | `901712290772` |
| BUG-   | BUGS | `901712289456` |
| F-     | FEATURES | `901712289454` |
| TD-    | TECH_DEBT | `901712289455` |

## Process

1. **Identify the task**:
   - If the user provides a task ID (e.g., `QA-0003`, `BUG-0001`, `F-0008`, `TD-0012`), determine the list from the prefix and search that list using `clickup_filter_tasks`.
   - If the user provides a description but no ID, search across the relevant list(s) using `clickup_filter_tasks` and match by name/description.
   - If ambiguous, show the user matching tasks and ask which one to update.

2. **Fetch the current task** using `clickup_get_task` to see its current state (status, priority, description, comments).

3. **Determine what to update** based on the user's request. Supported updates:
   - **Status**: Use `clickup_update_task` to change status (e.g., `open` → `in progress` → `complete`)
   - **Priority**: Use `clickup_update_task` to change priority (urgent, high, normal, low)
   - **Description**: Use `clickup_update_task` to modify the task description
   - **Name**: Use `clickup_update_task` to rename the task
   - **Comment**: Use `clickup_create_task_comment` to add a comment with new context

4. **Apply the update(s)** — make all requested changes.

5. **Print a summary** of what was changed, including the task URL and before/after values.

## Common Use Cases

### Plan Changed
When a plan or approach for a task changes, add a comment documenting what changed and why:

```markdown
## Plan Update — YYYY-MM-DD

**Previous Plan**: [brief description of old approach]

**New Plan**: [brief description of new approach]

**Reason**: [why the plan changed]

**Impact**: [any effect on scope, effort, or timeline]
```

### Progress Update
When work has progressed but isn't complete, add a status comment:

```markdown
## Progress Update — YYYY-MM-DD

**Status**: In Progress

**Completed**:
- [what's been done]

**Remaining**:
- [what's left to do]

**Blockers**: [any blockers, or "None"]
```

### Closing a Task
When marking a task complete, add a resolution comment before changing status:

```markdown
## Resolution — YYYY-MM-DD

**Fix/Implementation**: [brief description of what was done]

**Files Changed**:
- `file/path.ts` — [what changed]

**Verified**: [how it was verified — tests, manual check, etc.]
```

Then set status to `complete`.

### Scope Change
When the scope of a feature or fix changes:

```markdown
## Scope Change — YYYY-MM-DD

**Added**: [new requirements]

**Removed**: [dropped requirements]

**Reason**: [why scope changed]
```

Update the task description if acceptance criteria or details need to change.

## Batch Updates

If the user asks to update multiple tasks (e.g., "close all QA issues we fixed today"), process them one at a time but report a combined summary at the end.

## Guidelines

- **Always fetch current state first** before making changes — avoid overwriting recent updates from other sources.
- **Add comments for context** — don't just change status silently. A comment explaining *why* creates an audit trail.
- **Preserve existing description content** — when updating a description, merge changes into the existing text rather than replacing it entirely, unless the user explicitly asks for a full rewrite.
- **Use today's date** in comment headers (format: YYYY-MM-DD).
- **Confirm destructive changes** — if the user asks to delete content from a description or downgrade priority, confirm before applying.
