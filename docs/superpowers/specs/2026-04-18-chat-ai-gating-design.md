# Chat AI Gating & Admin Notification Design

**Date:** 2026-04-18  
**Task:** BUG-0050  
**Scope:** Full-stack (frontend + backend)  
**Effort:** M (1-4 hours)

## Problem

Non-Pro users (and Pro users without custom AI configured) can see the chat FAB and navigate to `/chat`, but encounter a generic "failed to send message" error when trying to use it. This creates broken UX where users discover the limitation only after attempting to use the feature.

## Solution Overview

Gate chat access based on organization subscription tier and AI configuration:
- **Pro orgs:** Always have system AI configured by default → full chat access
- **Non-Pro orgs:** No default AI → hide FAB, show empty state with "Contact Administrator" button
- **Rate limiting:** Admin notifications are rate-limited (1 per user per 24h + 3 per org per 24h)

## Design

### Frontend Changes

#### 1. Update Auth Context (`auth.svelte.ts`)
- Add `subscription_tier: string` to the `Org` interface
- The field is already returned by `/iam/organizations` endpoint; frontend just needs to declare it

#### 2. Hide FAB in Layout (`src/routes/+layout.svelte`)
- Check `currentOrg?.subscription_tier` before rendering ChatPanel FAB
- Only show FAB if `subscription_tier === "pro"` (or derive from `_is_org_pro_or_above()` logic)

#### 3. Empty State in Chat Page (`src/routes/chat/+page.svelte`)
- If org is non-Pro, show empty state (full-page) instead of normal chat interface
- Message: "AI Chat Not Available"
- Description: "Your organization doesn't have AI configured. Contact an admin to set it up."
- Action button: "Contact Administrator" → calls `POST /chat/notify-admin`
- Handle 429 (rate limited): "You've already notified admins recently. Please try again later."
- Pro orgs always see normal chat interface (no gating needed)

---

### Backend Changes

#### 1. Rate Limiting Service (`app/services/rate_limit.py`)

```python
class RateLimitService:
    """Check and record rate-limited actions.
    
    Implementation uses DB (chat_rate_limit_attempts table).
    Can be swapped for Redis in the future.
    """
    
    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
    
    async def is_allowed(self, key: str, db: AsyncSession) -> bool:
        """Check if key is under limit. Does NOT record the attempt."""
        # Query: count attempts for this key in the last window_seconds
        # Return: count < max_attempts
    
    async def record_attempt(self, key: str, db: AsyncSession) -> None:
        """Record a new attempt for this key."""
        # Insert row into chat_rate_limit_attempts
```

#### 2. Database Schema

**New table: `chat_rate_limit_attempts`**
```sql
CREATE TABLE chat_rate_limit_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR NOT NULL,           -- e.g., "notify-admin:user:{user_id}"
    attempted_at TIMESTAMP NOT NULL DEFAULT NOW(),
    INDEX idx_key_attempted_at (key, attempted_at)
);
```

**New table: `chat_notifications`**
```sql
CREATE TABLE chat_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    INDEX idx_org_created_at (org_id, created_at),
    INDEX idx_user_created_at (user_id, created_at)
);
```

#### 3. New Endpoint: `POST /chat/notify-admin`

**Requirements:**
- Auth required (authenticated users only)
- Only callable by non-Pro orgs (Pro orgs have AI by default)
- Rate limiting: per-user (1 per 24h) + per-org (3 per 24h)
- Success: Send email to all org admins, insert notification record
- Returns:
  - 200: Success
  - 429: Rate limit exceeded (per-user or per-org)
  - 403: User's org is Pro (no need to notify)

**Implementation:**
1. Get user's org and check tier
2. If Pro tier → 403 (no need to notify)
3. Check per-user rate limit: `key = f"notify-admin:user:{user_id}"`, limit=1, window=86400
4. Check per-org rate limit: `key = f"notify-admin:org:{org_id}"`, limit=3, window=86400
5. If either check fails → 429
6. Send email to all org admins (use existing email service)
7. Record notification in `chat_notifications` table
8. Record rate limit attempt in both rate limit keys
9. Return 200 with success message

---

## Data Flow

### Non-Pro User Navigates to `/chat`

```
1. Frontend loads /chat route
2. Chat component checks: currentOrg.subscription_tier
3. If non-Pro:
   → Show empty state with "Contact Administrator" button
   → Do NOT load chat sessions/messages
4. User clicks "Contact Administrator"
5. Frontend calls POST /chat/notify-admin
6. Backend:
   → Checks rate limits (per-user, per-org)
   → If limited: return 429
   → If allowed: send email to admins, record attempt
   → Return 200
7. Frontend shows: "Admin notified! They'll get back to you soon."
8. Button is now disabled for next 24 hours (via rate limit response)
```

### Pro User Navigates to `/chat`

```
1. Frontend loads /chat route
2. Chat component checks: currentOrg.subscription_tier === "pro"
3. Is Pro → render full chat interface normally
4. AI is available (system default)
```

---

## Error Handling

- **Per-user rate limit exceeded:** 429 with message "You've already notified admins. They'll get back to you soon."
- **Per-org rate limit exceeded:** 429 with message "Your organization has reached its notification limit. Please try again later."
- **Email send fails:** Log error, still return 200 (notification record created), so user isn't penalized
- **Non-Pro org trying to access chat:** No backend enforcement needed (frontend gates), but `/chat/sessions` will fail if called directly

---

## Testing

### Unit Tests
- `test_rate_limit_service_allows_under_limit()`
- `test_rate_limit_service_denies_over_limit()`
- `test_rate_limit_service_window_expiry()`

### Integration Tests
- `test_notify_admin_success()` — valid request, returns 200
- `test_notify_admin_per_user_rate_limit()` — second request within 24h returns 429
- `test_notify_admin_per_org_rate_limit()` — third user triggers org limit, fourth request returns 429
- `test_notify_admin_after_window_expiry()` — request allowed after 24h window

### E2E Tests
- Non-Pro org user sees empty state on `/chat` (no FAB, no chat UI)
- "Contact Administrator" button works, shows success message
- Clicking again shows rate limit message
- Pro org user sees full chat interface and FAB

---

## Acceptance Criteria

- ✅ FAB visibility respects org subscription tier (hidden for non-Pro)
- ✅ `/chat` page shows full-page empty state for non-Pro orgs
- ✅ "Contact Administrator" button present and functional
- ✅ Rate limiting: per-user (1 per 24h) and per-org (3 per 24h)
- ✅ Toast/feedback messages are clear and actionable
- ✅ Pro orgs always have full chat access (system AI guaranteed)
- ✅ Rate limiting abstracted as `RateLimitService` (swappable for Redis)
- ✅ All tests passing (unit, integration, E2E)

---

## Future Considerations

- **Redis rate limiting:** Replace `RateLimitService` DB implementation with Redis for better performance at scale
- **Email template:** Customize notification email with org/user details
- **Admin dashboard:** Show notification history and user requests
- **Tier-based limits:** Adjust notification limits based on subscription tier
