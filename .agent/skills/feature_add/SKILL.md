---
name: feature_add
description: Add a feature specification to the ClickUp FEATURES list. Use when the user wants to "add a feature", "log a feature", "spec out a feature", "add to the backlog", or runs /feature_add. Takes a feature idea and writes a detailed specification with acceptance criteria.
---

# Add Feature Specification

Add a new feature task to the **ClickUp FEATURES list** (list ID: `901712289454`).

## Process

1. **Fetch existing tasks from ClickUp** using `clickup_filter_tasks` on list `901712289454` to check for duplicates and determine the next feature number (F-XXXX).
2. **Gather details** from the user's description. If the description is vague, use your knowledge of the codebase to flesh out the spec — but keep it grounded in what was requested.
3. **Research the codebase** as needed to understand where the feature would be implemented. Use Explore agents or Grep to check relevant files. This helps you write accurate scope and implementation notes.
4. **Create the task in ClickUp** using `clickup_create_task` on list `901712289454` with:
   - **Name**: `[F-XXXX] Feature title`
   - **Priority**: Map P0 → urgent, P1 → high, P2 → normal, P3 → low
   - **Description**: Full feature specification in markdown (see format below)
5. **Print a summary** of what was added, including the ClickUp task URL.

## Feature Description Format

The task description (markdown) should follow this template:

```markdown
**Status**: Proposed
**Priority**: P0 (Critical) | P1 (High) | P2 (Medium) | P3 (Low)
**Scope**: Backend | Frontend | Full Stack | Infrastructure

**Description**: Clear explanation of what the feature does and why it's needed.

**Acceptance Criteria**:
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

**Implementation Notes**: Brief notes on where/how to implement (key files, APIs, components affected).

**Dependencies**: Any features or work that must be completed first (reference F-XXXX IDs), or "None".
```

## Guidelines

- **Number sequentially**: F-0001, F-0002, etc. Check existing ClickUp tasks for the next number.
- **Don't duplicate**: If a similar feature already exists in ClickUp, update it instead of creating a new one.
- **Be specific**: Acceptance criteria should be testable and concrete.
- **Keep implementation notes brief**: Just enough to point a developer in the right direction. Reference specific files/modules from the codebase.
- **Default priority**: Use `normal` (P2 Medium) unless the user specifies otherwise.
