---
name: archive
description: Archive completed items from FEATURES.md, QA_SURVEY.md, and TECH_DEBT.md into respective archive files. Use when the user asks to "archive done items", "clean up the backlog", "archive finished features", "archive resolved tech debt", or runs /archive. Optionally pass a specific file scope (e.g., /archive features, /archive qa, /archive tech_debt, or /archive all).
---

# Archive Completed Items

Move finished/resolved/fixed items from the active tracking files into dedicated archive files, keeping the active files focused on open work.

## Source Files and Completion Markers

| Source File | Archive File | Completed When |
|-------------|-------------|----------------|
| `FEATURES.md` | `FEATURES_ARCHIVE.md` | `- **Status**: Done` |
| `QA_SURVEY.md` | `QA_SURVEY_ARCHIVE.md` | `**FIXED**` or `**DEFERRED**` in the severity line |
| `TECH_DEBT.md` | `TECH_DEBT_ARCHIVE.md` | `**RESOLVED**` or `**WONTFIX**` in the severity line |

## Process

1. **Determine scope** from the user's argument:
   - `features` or `f` → only FEATURES.md
   - `qa` or `q` → only QA_SURVEY.md
   - `tech_debt` or `td` → only TECH_DEBT.md
   - `all` or no argument → all three files

2. **For each in-scope file**, read it and identify completed items:
   - **FEATURES.md**: Items where `- **Status**: Done` appears in the item block
   - **QA_SURVEY.md**: Items where the severity line contains `**FIXED**` or `**DEFERRED**`
   - **TECH_DEBT.md**: Items where the severity line contains `**RESOLVED**` or `**WONTFIX**`

3. **Show the user what will be archived** before making changes:
   ```
   Items to archive:
     FEATURES.md (2 items):
       [F-0001] Protocol Delete & Archive with Admin Unarchive (Done)
       [F-0009] Global Toast Notification System (Done)
     QA_SURVEY.md (3 items):
       [QA-0001] Dashboard and Projects endpoints return 500/503 (FIXED)
       [QA-0002] Backend server degrades over time (DEFERRED)
       [QA-0003] Settings Organization tab shows "No members found" (FIXED)
     TECH_DEBT.md (0 items):
       (none)

   Proceed? (y/n)
   ```
   **Wait for user confirmation before proceeding.**

4. **Create or update the archive file** for each source:
   - If the archive file doesn't exist, create it with a header (see Archive File Format below)
   - Append each completed item's full markdown block (from `### [ID]` to the next `###` or end of section)
   - Add an `- **Archived**: YYYY-MM-DD` line to each archived item

5. **Remove archived items from the source file**:
   - Delete the entire item block from the source file
   - **Do NOT modify items that are still open** — only remove completed ones

6. **Update summary tables** in the source files:
   - **FEATURES.md**: No summary table to update (just remove the item blocks)
   - **QA_SURVEY.md**: Update the summary table counts to reflect removed items
   - **TECH_DEBT.md**: Update the summary table counts to reflect removed items

7. **Print a summary** of what was archived:
   ```
   Archived:
     FEATURES.md → FEATURES_ARCHIVE.md: 2 items (F-0001, F-0009)
     QA_SURVEY.md → QA_SURVEY_ARCHIVE.md: 3 items (QA-0001, QA-0002, QA-0003)
     TECH_DEBT.md → TECH_DEBT_ARCHIVE.md: 0 items (nothing to archive)
   ```

## Archive File Format

When creating a new archive file, use this header:

**FEATURES_ARCHIVE.md:**
```markdown
# Feature Archive

Completed features moved from `FEATURES.md`. These items are retained for reference.

---
```

**QA_SURVEY_ARCHIVE.md:**
```markdown
# QA Survey Archive

Resolved QA issues moved from `QA_SURVEY.md`. These items are retained for reference.

---
```

**TECH_DEBT_ARCHIVE.md:**
```markdown
# Tech Debt Archive

Resolved technical debt items moved from `TECH_DEBT.md`. These items are retained for reference.

---
```

Each archived item is appended below the `---` separator with its full original content plus the `- **Archived**: YYYY-MM-DD` line.

## Rules

- **Confirm before archiving.** Always show the list and wait for user approval.
- **Preserve item content exactly.** Copy the full item block verbatim — don't edit content, only add the `- **Archived**` line.
- **Don't touch open items.** Only move items that match the completion markers. If an item is `In Progress`, `Proposed`, or has no completion marker, leave it in the source file.
- **Update counts.** If the source file has a summary table, update it after removing items so the numbers stay accurate.
- **Idempotent.** If an item is already in the archive file, don't duplicate it. Skip and note it.
- **Keep the `---` separator** between the file header/intro section and the items section in the source files. Don't remove structural markdown.
- **Sort archive by ID.** When appending to an existing archive file, maintain ID order (F-0001 before F-0009, TD-0001 before TD-0047, etc.).
