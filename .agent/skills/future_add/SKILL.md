---
name: future_add
description: Add a task to the ClickUp FUTURE list. Use when the user wants to "add to the future list", "log a future idea", "park this for later", "add to future", or runs /future_add. For ideas, wishlist items, or tasks that aren't ready to be worked on yet but should be captured.
---

# Add Future Task

Add a new task to the **ClickUp FUTURE list** (list ID: `901712303159`).

The FUTURE list is for ideas, wishlist items, and tasks that aren't actionable yet but worth capturing. Unlike FEATURES (specced and ready to build), FUTURE items are loosely defined and may or may not become real work.

## Process

1. **Fetch existing tasks from ClickUp** using `clickup_filter_tasks` on list `901712303159` to check for duplicates and determine the next item number (FUT-XXXX).
2. **Gather details** from the user's description. Keep it lightweight — FUTURE items don't need full specs. Capture the core idea, motivation, and any rough context.
3. **Create the task in ClickUp** using `clickup_create_task` on list `901712303159` with:
   - **Name**: `[FUT-XXXX] Short title`
   - **Priority**: `low` by default (these are future ideas). Use `normal` if the user indicates it's somewhat important, `high` only if explicitly requested.
   - **Description**: Brief description in markdown (see format below)
4. **Print a summary** of what was added, including the ClickUp task URL.

## Description Format

The task description (markdown) should follow this template:

```markdown
**Category**: Product | Engineering | UX | Infrastructure | Research | Other
**Source**: User idea | Gap analysis | Customer feedback | Tech exploration | Competitor feature

**Idea**: Clear, concise description of the idea or future task.

**Motivation**: Why this might be worth doing. What problem does it solve or what opportunity does it create?

**Rough Scope**: Quick estimate of what's involved — one sentence is fine. e.g., "Backend + frontend, probably a few days" or "Research spike needed first".

**Related**: Links to existing features (F-XXXX), tech debt (TD-XXXX), or bugs (BUG-XXXX) if relevant, or "None".
```

## Guidelines

- **Number sequentially**: FUT-0001, FUT-0002, etc. Check existing ClickUp tasks for the next number.
- **Don't duplicate**: If a similar idea already exists in the FUTURE list, update it with the new context instead of creating a new one. Also check the FEATURES list — if it's already specced there, tell the user and skip.
- **Keep it lightweight**: FUTURE items are rough ideas, not specs. Don't over-engineer the description.
- **Default priority**: Use `low` unless the user says otherwise. These are parking-lot items.
- **Promote when ready**: If a FUTURE item gets enough context to be actionable, suggest the user run `/feature_add` to promote it to the FEATURES list with a full spec.
