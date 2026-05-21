---
name: project_bug005_chat_heartbeat
description: QA verified BUG-005 chat turn heartbeat fix — spurious "interrupted" banner replaced with server-side turn_in_progress boolean
metadata:
  type: project
---

BUG-005 fix verified in browser. The false "interrupted" banner (previously fired by a blind 90-second client `STALE_POLL_MS` timer) is now driven by the server's `turn_in_progress` boolean on the chat session detail response.

**Why:** Old timer fired even when the backend turn was healthy. New logic: poll only while `turn_in_progress=true`; surface the amber banner only when the server says the turn is orphaned (heartbeat gone, turn_in_progress=false, trailing user message with no reply).

**How to apply:** If future chat QA involves staleness/heartbeat logic, the key field is `active_turn_heartbeat_at` (nullable timestamp) and `turn_in_progress` (computed boolean) on `GET /chat/sessions/{id}`. The frontend store function `maybeStartAwaitingPoll` is the entry point.

## Test setup notes

- Worktree DB is `batchrite_wt4` (set in `backend/.env`). The seed does NOT set BioProcess Inc to `pro` tier — you must run `UPDATE organizations SET subscription_tier = 'pro' WHERE id = '10000000-0000-0000-0000-000000000001';` against `batchrite_wt4` before testing.
- Pre-seeded interrupted session ID: `cccccccc-0000-0000-0000-000000000005` ("BUG-005 interrupted turn"), trailing user message with no reply and `active_turn_heartbeat_at=null`, `turn_in_progress=false`.
- Login as `admin@bioprocess.com` / `password123`, then `POST /auth/switch-org` with `org_id=10000000-0000-0000-0000-000000000001` to get a Pro-scoped token.

## What was verified

1. **Normal chat — no spurious banner**: Sent a message, observed NO amber banner during or after a healthy response. Confirmed `stalePending` is never set while `turn_in_progress=true`.
2. **Interrupted-turn banner**: Opened the pre-seeded session. Banner appeared immediately with exact copy: "This request was interrupted and did not complete." Buttons: "Resend" (underlined, amber text) and "Dismiss" (muted amber text). No "Keep waiting" button (old copy).
3. **Dismiss**: Clicking Dismiss clears the banner. It does not reappear after 3 seconds (no poll loop firing).

## Console errors during QA run

Zero feature-related console errors. Two `404/Not found: /dashboard` errors were test-script artifacts from navigating before auth token was seated.

## UI/UX assessment

Banner passes visual check:
- `bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 max-w-[85%]` — clean amber styling, left-aligned like assistant messages
- Minor inconsistency: banner `max-w-[85%]` vs message bubble `max-w-[80%]` — not worth fixing, deliberate for slightly wider callout
- Bare `<button>` elements used (not shadcn `Button`) — acceptable because amber color isn't a Button variant; all required states (cursor-pointer, hover, transition) are present
