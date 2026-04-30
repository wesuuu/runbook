---
name: QA test accounts for empty-state verification
description: Known DB accounts suitable for triggering empty states in Batchrite; includes credentials and data state
type: project
---

**qa-empty-1776464192@test.com / password123**
- org_id: `8bd5576b-d705-417b-a71a-51f8e8b632e8`
- State: 0 runs, 0 projects, 0 docs, 0 chat sessions, 0 activity
- Email verified: yes (manually set via DB)
- Use for: triggering all empty states simultaneously (dashboard, projects, library, chat)

**admin@bioprocess.com / password123**
- org_id: `10000000-0000-0000-0000-000000000002` (Acme Biologics)
- State: 0 runs but 10 activity items, 1 project, 4 docs, 2 chat sessions
- Use for: partial empty states (dashboard runs, not activity)

**Why:** Registration requires email verification; seed accounts may have wrong JWT org_id. The qa-empty account was manually email-verified in the DB and has a clean org.

**How to apply:** Use `qa-empty-1776464192@test.com` as the default empty-state test user in future QA scripts for this feature set.
