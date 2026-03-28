---
name: ship
description: Review, test, commit, and push code to a branch. Use when the user wants to "ship it", "commit and push", "push to main", "send it", or runs /ship. Optionally pass a target branch (e.g., /ship develop). Defaults to main. Runs /simplify, all test suites, writes a descriptive commit message, and pushes.
---

# Ship

Review code quality, run all tests, commit, and push to a target branch.

**Default branch**: `main`
**Usage**: `/ship [branch]` — e.g., `/ship`, `/ship develop`, `/ship feature/new-auth`

## Process

### 1. Run /simplify

Before anything else, invoke the `/simplify` skill to review all changed code for reuse, quality, and efficiency issues. Fix any issues it identifies before proceeding.

### 2. Run all test suites

Run all three tiers of tests **sequentially**. If any tier fails, diagnose and fix the issue before moving to the next tier. Do NOT skip ahead.

**Tier 1 — Backend unit & integration tests:**
```bash
cd /home/wesuuu/Code/trellisbio/backend && source .venv/bin/activate && pytest tests/ -x -q
```

**Tier 2 — Frontend type checking & unit tests:**
```bash
cd /home/wesuuu/Code/trellisbio/frontend && npm run check && npx vitest run
```

**Tier 3 — E2E tests (requires dev servers running):**
```bash
cd /home/wesuuu/Code/trellisbio/frontend && npx playwright test
```

#### Handling test failures

- Read the failure output carefully and trace it to the root cause.
- Fix the code (not the test) unless the test itself is wrong.
- Re-run the **entire tier** after each fix to confirm no regressions.
- If a test failure is unrelated to your changes (pre-existing flake), note it in the commit message body but do not block the ship.
- **Maximum 3 fix attempts per tier.** If still failing after 3 rounds, stop and present the failures to the user for guidance. Do NOT force push broken code.

### 3. Stage and commit

1. **Review what's changed** — run `git status` and `git diff` to see all modifications.
2. **Stage relevant files** — use `git add <specific files>` for files related to the current work. Never blindly `git add -A`. Exclude:
   - `.env` files or anything with secrets/credentials
   - Large binaries or generated files
   - Unrelated changes the user didn't intend to ship
3. **If there are unrelated changes**, ask the user whether to include them or leave them unstaged.
4. **Write a descriptive commit message** following the project's conventional commit format:
   ```
   <type>(<scope>): <short summary>

   <body — explain what changed and why, not how>

   Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
   ```
   - **type**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
   - **scope**: affected area (e.g., `protocol-editor`, `auth`, `api`, `runner`)
   - **body**: 2-5 lines covering the motivation and key changes. Mention test results.
   - If multiple types of changes are present, use the most significant type and note others in the body.
5. **Create the commit** using a HEREDOC for proper formatting:
   ```bash
   git commit -m "$(cat <<'EOF'
   <type>(<scope>): <summary>

   <body>

   Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
   EOF
   )"
   ```

### 4. Push to target branch

1. **Determine the target branch** — use the argument passed to `/ship`, or default to `main`.
2. **Check current branch** — run `git branch --show-current`.
   - If already on the target branch, push directly.
   - If on a different branch and the target is `main`, **ask the user** whether they want to:
     - Push the current branch and create a PR to main
     - Merge into main locally and push
     - Push to the current branch instead
3. **Push**:
   ```bash
   git push origin <branch>
   ```
   - If the remote branch doesn't exist yet, use `git push -u origin <branch>`.
   - **Never force push.** If the push is rejected, pull first and resolve conflicts.
4. **Report success** — print the branch name, commit SHA, and a link to the remote if available.

## Rules

- **Never push failing tests.** All three tiers must pass (or failures must be confirmed pre-existing) before pushing.
- **Never force push.** If rejected, pull and resolve.
- **Never push secrets.** Check staged files for `.env`, credentials, API keys, tokens.
- **Never skip /simplify.** Code quality review is mandatory before shipping.
- **Ask before ambiguous actions.** If you're unsure which files to stage, which branch to target, or whether to include unrelated changes — ask the user.
- **One logical commit.** Bundle related changes into a single well-described commit. If the changes are truly independent, ask the user if they want separate commits.
- **Commit message quality matters.** The message should make sense to a reviewer reading `git log` months later. Lead with *why*, not *what*.
