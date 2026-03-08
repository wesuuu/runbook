---
name: add_feature
description: Add a feature specification to the FEATURES.md backlog. Use when the user wants to "add a feature", "log a feature", "spec out a feature", "add to the backlog", or runs /add_feature. Takes a feature idea and writes a detailed specification with acceptance criteria.
---

# Add Feature Specification

Add a new feature specification to `FEATURES.md` in the project root.

## Process

1. **Read existing `FEATURES.md`** to determine the next feature number and avoid duplicates. If the file doesn't exist, create it with the header below.
2. **Gather details** from the user's description. If the description is vague, use your knowledge of the codebase to flesh out the spec — but keep it grounded in what was requested.
3. **Research the codebase** as needed to understand where the feature would be implemented. Use Explore agents or Grep to check relevant files. This helps you write accurate scope and implementation notes.
4. **Append** the new feature entry to `FEATURES.md`.
5. **Print a summary** of what was added.

## File Header (create if missing)

```markdown
# Feature Backlog

Planned features for the Runbook AI Co-Pilot. Each entry is a specification that can be picked up for implementation.

---
```

## Feature Entry Format

Each feature should follow this template:

```markdown
### [F-XXXX] Feature title
- **Status**: Proposed | Approved | In Progress | Done
- **Priority**: P0 (Critical) | P1 (High) | P2 (Medium) | P3 (Low)
- **Scope**: Backend | Frontend | Full Stack | Infrastructure
- **Description**: Clear explanation of what the feature does and why it's needed.
- **Acceptance Criteria**:
  - [ ] Criterion 1
  - [ ] Criterion 2
  - [ ] Criterion 3
- **Implementation Notes**: Brief notes on where/how to implement (key files, APIs, components affected).
- **Dependencies**: Any features or work that must be completed first (reference F-XXXX IDs), or "None".
```

## Guidelines

- **Number sequentially**: F-0001, F-0002, etc. Check existing entries for the next number.
- **Don't duplicate**: If a similar feature already exists, update it instead of creating a new one.
- **Be specific**: Acceptance criteria should be testable and concrete.
- **Keep implementation notes brief**: Just enough to point a developer in the right direction. Reference specific files/modules from the codebase.
- **Default status**: New features start as `Proposed`.
- **Default priority**: Use `P2 (Medium)` unless the user specifies otherwise.
