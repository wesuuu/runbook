# Implementation Plans

This directory contains detailed implementation plans for upcoming features. Each plan is a standalone markdown file designed for collaborative review.

## Workflow

1. **I write a plan** — detailed markdown file with approach, file changes, and open questions
2. **You review & comment** — add inline comments, questions, or `<!-- COMMENT: ... -->` annotations directly in the file
3. **I review your feedback** — adjust the plan based on your comments
4. **We agree** — once the plan is solid, I implement it following the workflow in `workflow.md`

## Comment Format

Use HTML comments anywhere in a plan file to leave feedback:

```markdown
<!-- COMMENT: I'd prefer we use approach B here because... -->
<!-- QUESTION: Should this also handle the case where...? -->
<!-- APPROVED -->
<!-- REJECTED: Let's skip this for now -->
```

Or just edit the text directly — I'll diff it against my version.

## Plan Status

| Plan | Status | Description |
|------|--------|-------------|
| [001-unitop-seeder.md](001-unitop-seeder.md) | Draft | Seed default unit operation library |
| [002-e2e-protocol-experiment.md](002-e2e-protocol-experiment.md) | Draft | End-to-end test coverage |
| [003-run-sheet-view.md](003-run-sheet-view.md) | Draft | Run Sheet execution view |
| [004-voice-commands.md](004-voice-commands.md) | Draft | Voice command interface |
| [005-tablet-polish.md](005-tablet-polish.md) | Draft | Tablet-first UI polish |
