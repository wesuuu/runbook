# Chat AI Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate chat access by subscription tier, hide FAB for non-Pro orgs, add rate-limited admin notification endpoint.

**Architecture:** Frontend checks org tier from auth context and conditionally renders FAB/empty state. Backend provides POST /chat/notify-admin with rate limiting abstracted via RateLimitService (DB-backed, swappable for Redis).

**Tech Stack:** FastAPI, SQLAlchemy, Svelte 5 runes, Alembic, Pytest

---

## Task 1: Backend - Rate Limiting Service (Unit Tests & Implementation)

**Files:**
- Create: `backend/app/services/rate_limit.py`
- Create: `backend/tests/unit/services/test_rate_limit.py`

**Context:** Build the RateLimitService abstraction so the notify endpoint can check per-user and per-org limits. DB-backed for now, but designed to swap for Redis later.

- [ ] **Step 1: Write failing unit test for `is_allowed()`**

Create `backend/tests/unit/services/test_rate_limit.py`:

```python
import pytest
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.rate_limit import RateLimitService


@pytest.mark.asyncio
async def test_is_allowed_first_request(db: AsyncSession):
    """First request should always be allowed."""
    service = RateLimitService(max_attempts=1, window_seconds=3600)
    result = await service.is_allowed("test-key", db)
    assert result is True


@pytest.mark.asyncio
async def test_is_allowed_under_limit(db: AsyncSession):
    """Requests under limit should be allowed."""
    service = RateLimitService(max_attempts=3, window_seconds=3600)
    # Record 2 attempts
    await service.record_attempt("test-key-2", db)
    await service.record_attempt("test-key-2", db)
    # Third should be allowed
    result = await service.is_allowed("test-key-2", db)
    assert result is True


@pytest.mark.asyncio
async def test_is_allowed_over_limit(db: AsyncSession):
    """Requests over limit should be denied."""
    service = RateLimitService(max_attempts=2, window_seconds=3600)
    # Record 2 attempts (at limit)
    await service.record_attempt("test-key-3", db)
    await service.record_attempt("test-key-3", db)
    # Third should be denied
    result = await service.is_allowed("test-key-3", db)
    assert result is False


@pytest.mark.asyncio
async def test_is_allowed_window_expiry(db: AsyncSession, freezer):
    """Requests outside window should be allowed again."""
    service = RateLimitService(max_attempts=1, window_seconds=3600)
    # Record first attempt at t=0
    await service.record_attempt("test-key-4", db)
    # Should be denied at t=1h
    assert await service.is_allowed("test-key-4", db) is False
    # Should be allowed at t=1h + 1s
    freezer.move_to(datetime.now() + timedelta(seconds=3601))
    assert await service.is_allowed("test-key-4", db) is True
```

Run: `pytest backend/tests/unit/services/test_rate_limit.py -v`
Expected: FAIL (module not found)

- [ ] **Step 2: Create RateLimitService with `is_allowed()` method**

Create `backend/app/services/rate_limit.py`:

```python
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatRateLimitAttempt


class RateLimitService:
    """Rate limit checker using database-backed storage.
    
    Can be swapped for Redis in the future without changing the interface.
    """

    def __init__(self, max_attempts: int, window_seconds: int):
        """Initialize with max attempts and time window (in seconds)."""
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

    async def is_allowed(self, key: str, db: AsyncSession) -> bool:
        """Check if key is under the rate limit.
        
        Args:
            key: Unique identifier for the rate limit bucket
            db: Database session
            
        Returns:
            True if under limit, False if at/over limit
        """
        # Calculate the cutoff time (oldest allowed attempt)
        cutoff = datetime.utcnow() - timedelta(seconds=self.window_seconds)
        
        # Count attempts within the window
        result = await db.execute(
            select(func.count()).select_from(ChatRateLimitAttempt)
            .where(
                ChatRateLimitAttempt.key == key,
                ChatRateLimitAttempt.attempted_at >= cutoff
            )
        )
        count = result.scalar() or 0
        
        return count < self.max_attempts

    async def record_attempt(self, key: str, db: AsyncSession) -> None:
        """Record a new attempt for this key.
        
        Args:
            key: Unique identifier for the rate limit bucket
            db: Database session
        """
        attempt = ChatRateLimitAttempt(key=key, attempted_at=datetime.utcnow())
        db.add(attempt)
        await db.commit()
```

Run: `pytest backend/tests/unit/services/test_rate_limit.py -v`
Expected: PASS (but will fail on models.chat import)

- [ ] **Step 3: Commit**

```bash
cd backend
git add app/services/rate_limit.py tests/unit/services/test_rate_limit.py
git commit -m "feat: add RateLimitService abstraction for rate limiting"
```

---

## Task 2: Backend - Database Models for Rate Limiting & Notifications

**Files:**
- Modify: `backend/app/models/chat.py` (add models)
- Create: `backend/alembic/versions/*_add_rate_limit_and_notification_tables.py` (migration)

**Context:** Add SQLAlchemy models and Alembic migration for the two new tables: `chat_rate_limit_attempts` and `chat_notifications`.

- [ ] **Step 1: Add models to `chat.py`**

Read the current `backend/app/models/chat.py` to understand the structure, then append these models:

```python
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

# (Add these to app/models/chat.py, after existing ChatSession model)

class ChatRateLimitAttempt(Base, TimestampMixin):
    """Track rate limit attempts for notifications."""
    
    __tablename__ = "chat_rate_limit_attempts"
    
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(String, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    
    __table_args__ = (
        Index("idx_key_attempted_at", "key", "attempted_at"),
    )


class ChatNotification(Base, UUIDMixin, TimestampMixin):
    """Track admin notifications from non-Pro users."""
    
    __tablename__ = "chat_notifications"
    
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    
    __table_args__ = (
        Index("idx_org_created_at", "org_id", "created_at"),
        Index("idx_user_created_at", "user_id", "created_at"),
    )
```

- [ ] **Step 2: Generate Alembic migration**

Run: `cd backend && alembic revision --autogenerate -m "add rate limit and notification tables"`

Check the generated file at `backend/alembic/versions/*_add_rate_limit_and_notification_tables.py` and verify:
- `chat_rate_limit_attempts` table with `id`, `key`, `attempted_at`, `idx_key_attempted_at` index
- `chat_notifications` table with `id`, `user_id`, `org_id`, `created_at`, `updated_at`, indices
- FK constraints for user_id and org_id

- [ ] **Step 3: Apply migration**

Run: `cd backend && alembic upgrade head`

Expected: Migration applies successfully. Check DB: `psql batchrite -c "\dt chat_*"`

- [ ] **Step 4: Commit**

```bash
cd backend
git add app/models/chat.py alembic/versions/*_add_rate_limit_and_notification_tables.py
git commit -m "feat: add ChatRateLimitAttempt and ChatNotification models"
```

---

## Task 3: Backend - POST /chat/notify-admin Endpoint (Integration Test & Implementation)

**Files:**
- Modify: `backend/app/api/endpoints/chat.py` (add endpoint)
- Modify: `backend/app/schemas/chat.py` (add response schemas)
- Create: `backend/tests/integration/endpoints/test_chat_notify.py` (integration test)

**Context:** Build the notify-admin endpoint with rate limiting, email sending, and proper error handling.

- [ ] **Step 1: Write integration test for happy path**

Create `backend/tests/integration/endpoints/test_chat_notify.py`:

```python
import pytest
from httpx import AsyncClient
from uuid import uuid4
from app.models.iam import User, Organization, OrganizationMember, OrgRole, SubscriptionTier


@pytest.mark.asyncio
async def test_notify_admin_success(client: AsyncClient, db, current_user_fixture):
    """POST /chat/notify-admin succeeds for non-Pro org."""
    # Setup: non-Pro org
    user = current_user_fixture
    org = Organization(
        id=uuid4(),
        name="Non-Pro Org",
        subscription_tier=SubscriptionTier.ESSENTIALS.value
    )
    db.add(org)
    
    membership = OrganizationMember(
        user_id=user.id,
        organization_id=org.id,
        role=OrgRole.MEMBER.value
    )
    db.add(membership)
    await db.commit()
    
    # Switch user to this org (auth token updated to include org context)
    # (Assuming test fixture handles this)
    
    # Make request
    response = await client.post("/chat/notify-admin")
    
    assert response.status_code == 200
    data = response.json()
    assert "success" in data or "message" in data


@pytest.mark.asyncio
async def test_notify_admin_rate_limit_per_user(client: AsyncClient, db, current_user_fixture):
    """Second request within 24h returns 429 (per-user limit)."""
    # Setup
    user = current_user_fixture
    org = Organization(
        id=uuid4(),
        name="Test Org",
        subscription_tier=SubscriptionTier.ESSENTIALS.value
    )
    db.add(org)
    membership = OrganizationMember(
        user_id=user.id,
        organization_id=org.id,
        role=OrgRole.MEMBER.value
    )
    db.add(membership)
    await db.commit()
    
    # First request
    response1 = await client.post("/chat/notify-admin")
    assert response1.status_code == 200
    
    # Second request (same user, same day)
    response2 = await client.post("/chat/notify-admin")
    assert response2.status_code == 429


@pytest.mark.asyncio
async def test_notify_admin_rate_limit_per_org(client: AsyncClient, db, org_with_3_users_fixture):
    """Fourth user request returns 429 (org limit hit)."""
    # Setup: 3 users in same org, 4th tries to notify
    org = org_with_3_users_fixture  # has 3 non-Pro users already notified
    user4 = User(id=uuid4(), email="user4@test.com", full_name="User 4")
    db.add(user4)
    
    membership = OrganizationMember(
        user_id=user4.id,
        organization_id=org.id,
        role=OrgRole.MEMBER.value
    )
    db.add(membership)
    await db.commit()
    
    # First 3 users already called notify-admin (fixture sets this up)
    # 4th user tries
    response = await client.post("/chat/notify-admin")
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_notify_admin_pro_org_forbidden(client: AsyncClient, db, current_user_fixture):
    """Pro org users get 403 (no need to notify)."""
    user = current_user_fixture
    org = Organization(
        id=uuid4(),
        name="Pro Org",
        subscription_tier=SubscriptionTier.PRO.value
    )
    db.add(org)
    membership = OrganizationMember(
        user_id=user.id,
        organization_id=org.id,
        role=OrgRole.MEMBER.value
    )
    db.add(membership)
    await db.commit()
    
    response = await client.post("/chat/notify-admin")
    assert response.status_code == 403
```

Run: `pytest backend/tests/integration/endpoints/test_chat_notify.py::test_notify_admin_success -v`
Expected: FAIL (endpoint not found)

- [ ] **Step 2: Add response schemas to `chat.py`**

Add to `backend/app/schemas/chat.py`:

```python
from pydantic import BaseModel


class NotifyAdminResponse(BaseModel):
    """Response from POST /chat/notify-admin."""
    message: str
    user_notified_at: str  # ISO timestamp
```

- [ ] **Step 3: Implement POST /chat/notify-admin endpoint**

Add to `backend/app/api/endpoints/chat.py` (after existing endpoints):

```python
from datetime import datetime
from sqlalchemy import select
from app.services.rate_limit import RateLimitService
from app.models.chat import ChatNotification
from app.schemas.chat import NotifyAdminResponse


@router.post("/notify-admin", response_model=NotifyAdminResponse)
async def notify_admin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Notify org admins that a non-Pro user needs AI configured.
    
    Rate limits:
    - 1 per user per 24h
    - 3 per org per 24h
    """
    # Get user's org
    org_id, _ = await _get_user_org(current_user, db)
    
    # Check if org is Pro (if so, they don't need to notify)
    result = await db.execute(
        select(Organization.subscription_tier).where(Organization.id == org_id)
    )
    tier = result.scalar_one_or_none()
    if tier and TIER_RANK.get(SubscriptionTier(tier), 0) >= TIER_RANK[SubscriptionTier.PRO]:
        raise HTTPException(
            status_code=403,
            detail="Your organization has Pro subscription. AI is available by default."
        )
    
    # Check per-user rate limit (1 per 24h)
    user_rate_limit = RateLimitService(max_attempts=1, window_seconds=86400)
    user_key = f"notify-admin:user:{current_user.id}"
    if not await user_rate_limit.is_allowed(user_key, db):
        raise HTTPException(
            status_code=429,
            detail="You've already notified admins recently. They'll get back to you soon."
        )
    
    # Check per-org rate limit (3 per 24h)
    org_rate_limit = RateLimitService(max_attempts=3, window_seconds=86400)
    org_key = f"notify-admin:org:{org_id}"
    if not await org_rate_limit.is_allowed(org_key, db):
        raise HTTPException(
            status_code=429,
            detail="Your organization has reached its notification limit. Please try again later."
        )
    
    # Record rate limit attempts (both per-user and per-org)
    await user_rate_limit.record_attempt(user_key, db)
    await org_rate_limit.record_attempt(org_key, db)
    
    # Record notification
    notification = ChatNotification(
        user_id=current_user.id,
        organization_id=org_id
    )
    db.add(notification)
    await db.commit()
    
    # Send email to org admins (non-blocking; errors logged but don't fail the request)
    try:
        admin_emails = await _get_org_admin_emails(org_id, db)
        # (Assuming email service exists; see implementation detail below)
        await send_admin_notification_email(
            org_id=org_id,
            user_name=current_user.full_name or current_user.email,
            admin_emails=admin_emails
        )
    except Exception as e:
        logger.error(f"Failed to send notification email: {e}", exc_info=True)
        # Don't fail the request — notification was recorded
    
    return NotifyAdminResponse(
        message="Admin notified! They'll get back to you soon.",
        user_notified_at=datetime.utcnow().isoformat()
    )


async def _get_org_admin_emails(org_id: uuid.UUID, db: AsyncSession) -> list[str]:
    """Get all admin emails for an org."""
    result = await db.execute(
        select(User.email)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.role == OrgRole.ADMIN.value
        )
    )
    return result.scalars().all()


async def send_admin_notification_email(
    org_id: uuid.UUID,
    user_name: str,
    admin_emails: list[str]
):
    """Send notification email to org admins (async, fire-and-forget)."""
    # (Assuming app has an email service; adjust to match your infrastructure)
    from app.services.email import send_email  # or however email is handled
    
    for admin_email in admin_emails:
        await send_email(
            to=admin_email,
            subject=f"Chat AI Configuration Requested - {user_name}",
            template="admin_notification_chat_ai",
            context={
                "user_name": user_name,
                "org_id": str(org_id),
                "settings_url": f"{settings.frontend_base_url}/settings/ai",
            }
        )
```

- [ ] **Step 4: Add required imports to `chat.py`**

Add to the imports section of `backend/app/api/endpoints/chat.py`:

```python
from app.models.chat import ChatNotification
from app.models.iam import Organization, OrgRole, SubscriptionTier, TIER_RANK
from app.services.rate_limit import RateLimitService
from app.schemas.chat import NotifyAdminResponse
```

- [ ] **Step 5: Run integration tests**

Run: `pytest backend/tests/integration/endpoints/test_chat_notify.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/api/endpoints/chat.py app/schemas/chat.py tests/integration/endpoints/test_chat_notify.py
git commit -m "feat: add POST /chat/notify-admin endpoint with rate limiting"
```

---

## Task 4: Frontend - Update Auth Interface with Subscription Tier

**Files:**
- Modify: `frontend/src/lib/auth.svelte.ts`

**Context:** Add `subscription_tier` field to the `Org` interface so components can check org tier.

- [ ] **Step 1: Update Org interface**

In `frontend/src/lib/auth.svelte.ts`, modify the `Org` interface:

```typescript
interface Org {
    id: string;
    name: string;
    subscription_tier: string;  // "essentials", "pro", etc.
    created_at: string;
    updated_at: string;
}
```

- [ ] **Step 2: Verify endpoint returns tier**

The `/iam/organizations` endpoint already returns `subscription_tier` in the backend schema, so no backend changes needed. Confirm by checking `backend/app/schemas/iam.py` — it should have `subscription_tier: str` in `OrganizationResponse`.

- [ ] **Step 3: Commit**

```bash
cd frontend
git add src/lib/auth.svelte.ts
git commit -m "feat: add subscription_tier to Org interface"
```

---

## Task 5: Frontend - FAB Visibility Gating by Subscription Tier

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`

**Context:** Hide the chat FAB for non-Pro organizations.

- [ ] **Step 1: Locate FAB rendering in layout**

In `frontend/src/routes/+layout.svelte`, find where `ChatPanel` is rendered (around line 200-250). Look for:

```svelte
<ChatPanel ... />
```

and the `shouldShowChat` derived variable.

- [ ] **Step 2: Add helper function to check if org is Pro**

Add this function to the `<script>` block of `+layout.svelte`:

```typescript
function isOrgPro(org: Org | null): boolean {
    return org?.subscription_tier === "pro";
}
```

- [ ] **Step 3: Modify ChatPanel rendering**

Change the ChatPanel render condition from:

```svelte
<ChatPanel {showFab} ... />
```

to:

```svelte
{#if isOrgPro(currentOrg)}
    <ChatPanel showFab={shouldShowChat} ... />
{/if}
```

This completely hides ChatPanel (and FAB) for non-Pro orgs.

- [ ] **Step 4: Test in browser**

Start the dev server and navigate as a non-Pro user:
- FAB should be completely hidden (no button visible anywhere)
- As a Pro user, FAB should be visible

- [ ] **Step 5: Commit**

```bash
cd frontend
git add src/routes/+layout.svelte
git commit -m "feat: hide chat FAB for non-Pro organizations"
```

---

## Task 6: Frontend - /chat Empty State for Non-Pro Orgs

**Files:**
- Modify: `frontend/src/routes/chat/+page.svelte`
- Create: `frontend/src/lib/schemas/chat.ts` additions (if needed for NotifyAdminResponse)

**Context:** Show a full-page empty state for non-Pro orgs with a "Contact Administrator" button.

- [ ] **Step 1: Add NotifyAdminResponse schema (if not already present)**

In `frontend/src/lib/schemas/chat.ts`, add:

```typescript
import { z } from 'zod';

export const NotifyAdminResponseSchema = z.object({
    message: z.string(),
    user_notified_at: z.string(),
});

export type NotifyAdminResponse = z.infer<typeof NotifyAdminResponseSchema>;
```

- [ ] **Step 2: Add isOrgPro helper to chat page**

In `frontend/src/routes/chat/+page.svelte`, add to the `<script>` block:

```typescript
import { getCurrentOrg } from '$lib/auth.svelte';

const currentOrg = $derived(getCurrentOrg());

function isOrgPro(org: Org | null): boolean {
    return org?.subscription_tier === "pro";
}
```

- [ ] **Step 3: Add notify-admin button logic**

Add to the `<script>` block:

```typescript
let notifyLoading = $state(false);
let notifyMessage = $state<string | null>(null);
let notifyError = $state<string | null>(null);

async function handleNotifyAdmin(): Promise<void> {
    notifyLoading = true;
    notifyMessage = null;
    notifyError = null;

    try {
        const response = await api.post('/chat/notify-admin', {}, {
            schema: NotifyAdminResponseSchema,
        });
        notifyMessage = response.message;
        // Disable button for 24h (could also store in localStorage if desired)
    } catch (error) {
        const errMsg = error instanceof Error ? error.message : String(error);
        
        // Handle rate limit errors
        if (errMsg.includes("429") || errMsg.includes("rate limit") || errMsg.includes("already notified")) {
            notifyError = "You've already notified admins recently. They'll get back to you soon.";
        } else if (errMsg.includes("organization has reached")) {
            notifyError = "Your organization has reached its notification limit. Please try again later.";
        } else {
            notifyError = "Failed to notify admin. Please try again.";
        }
        toast.error(notifyError);
    } finally {
        notifyLoading = false;
    }
}
```

- [ ] **Step 4: Add empty state UI for non-Pro orgs**

In the markup of `+page.svelte`, wrap the existing content with a check:

```svelte
{#if !isOrgPro(currentOrg)}
    <!-- Empty state for non-Pro orgs -->
    <div class="flex h-[calc(100vh-57px)] items-center justify-center">
        <div class="text-center max-w-md px-6">
            <div class="w-14 h-14 rounded-2xl bg-amber-500/10 flex items-center justify-center mx-auto mb-4">
                <svg class="w-7 h-7 text-amber-600" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                    <path d="M12 9v3.75m-9.303 3.376c.865 1.728 2.883 2.875 5.303 2.875 2.42 0 4.438-1.147 5.303-2.875M3 20.25h18A2.25 2.25 0 0 0 21 18V6A2.25 2.25 0 0 0 18.75 3.75H5.25A2.25 2.25 0 0 0 3 6v12a2.25 2.25 0 0 0 1.5 2.102" />
                </svg>
            </div>
            <h2 class="text-lg font-semibold text-foreground mb-2">AI Chat Not Available</h2>
            <p class="text-sm text-muted-foreground mb-6">
                Your organization doesn't have AI configured. Contact an admin to set it up.
            </p>
            {#if notifyMessage}
                <div class="mb-4 p-3 rounded-lg bg-green-500/10 border border-green-500/30 text-green-700 dark:text-green-400 text-sm">
                    {notifyMessage}
                </div>
            {/if}
            <Button
                onclick={handleNotifyAdmin}
                disabled={notifyLoading || !!notifyMessage}
                class="w-full"
            >
                {notifyLoading ? 'Notifying...' : 'Contact Administrator'}
            </Button>
            {#if notifyError}
                <p class="text-xs text-red-500 mt-2">{notifyError}</p>
            {/if}
        </div>
    </div>
{:else}
    <!-- Normal chat interface for Pro orgs -->
    <div class="flex h-[calc(100vh-57px)] overflow-hidden">
        <!-- (existing chat markup here) -->
    </div>
{/if}
```

- [ ] **Step 5: Test in browser**

- [ ] **Step 5.1: Test as non-Pro user**
  - Navigate to `/chat`
  - Should see empty state with "Contact Administrator" button
  - Click button → should show success message "Admin notified! They'll get back to you soon."
  - Click again → should show "You've already notified admins recently..."

- [ ] **Step 5.2: Test as Pro user**
  - Navigate to `/chat`
  - Should see normal chat interface (sidebar, messages, input)

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/routes/chat/+page.svelte src/lib/schemas/chat.ts
git commit -m "feat: add empty state for non-Pro orgs on /chat"
```

---

## Task 7: E2E Testing

**Files:**
- Create or modify: E2E test file (depends on your E2E setup — Playwright, Cypress, etc.)

**Context:** Test the complete user flows: FAB visibility, empty state, notification button.

- [ ] **Step 1: Write E2E test for non-Pro user**

(Assuming Playwright in `frontend/tests/e2e/`):

```typescript
import { test, expect } from '@playwright/test';

test('non-pro user sees empty state and can contact admin', async ({ page, context }) => {
    // Login as non-Pro user (fixture handles this)
    const { user, org } = await loginNonProUser(context);
    
    // Navigate to /chat
    await page.goto('/chat');
    
    // Verify empty state is visible
    await expect(page.getByText('AI Chat Not Available')).toBeVisible();
    await expect(page.getByText("Your organization doesn't have AI configured")).toBeVisible();
    
    // Verify "Contact Administrator" button is visible
    const notifyBtn = page.getByRole('button', { name: /Contact Administrator/ });
    await expect(notifyBtn).toBeVisible();
    await expect(notifyBtn).toBeEnabled();
    
    // Click button
    await notifyBtn.click();
    
    // Verify success message
    await expect(page.getByText(/Admin notified/)).toBeVisible();
    
    // Button should now be disabled
    await expect(notifyBtn).toBeDisabled();
});

test('pro user sees normal chat interface', async ({ page, context }) => {
    // Login as Pro user
    const { user, org } = await loginProUser(context);
    
    // Navigate to /chat
    await page.goto('/chat');
    
    // Should NOT see empty state
    await expect(page.getByText('AI Chat Not Available')).not.toBeVisible();
    
    // Should see chat UI (sidebar, input area, etc.)
    await expect(page.getByText('Chats')).toBeVisible();  // sidebar heading
    await expect(page.getByPlaceholder(/Ask about/)).toBeVisible();  // input
});

test('non-pro user sees no FAB on dashboard', async ({ page, context }) => {
    const { user, org } = await loginNonProUser(context);
    
    // Navigate to dashboard
    await page.goto('/');
    
    // FAB should not be visible anywhere
    const fabButton = page.getByRole('button', { name: /chat/i });
    await expect(fabButton).not.toBeVisible();
});

test('pro user sees FAB on dashboard', async ({ page, context }) => {
    const { user, org } = await loginProUser(context);
    
    // Navigate to dashboard
    await page.goto('/');
    
    // FAB should be visible
    const fabButton = page.getByRole('button', { name: /chat/i });
    await expect(fabButton).toBeVisible();
    
    // Click FAB → should open chat panel (or navigate to /chat)
    await fabButton.click();
    await expect(page.getByText(/Batchrite AI/)).toBeVisible();
});
```

Run: `npm run test:e2e` (adjust command to match your setup)
Expected: PASS

- [ ] **Step 2: Commit**

```bash
cd frontend
git add tests/e2e/*.ts  # or wherever E2E tests live
git commit -m "test: add E2E tests for chat AI gating"
```

---

## Task 8: Final Testing & Verification

**Context:** Run full test suite, verify all acceptance criteria met.

- [ ] **Step 1: Run all backend tests**

```bash
cd backend
pytest tests/ -v --cov=app
```

Expected: All tests PASS, coverage >80%

- [ ] **Step 2: Run all frontend tests**

```bash
cd frontend
npm run test
npm run test:e2e
```

Expected: All tests PASS

- [ ] **Step 3: Manual smoke test**

1. **Non-Pro org:**
   - FAB not visible on dashboard ✓
   - `/chat` shows empty state ✓
   - "Contact Administrator" button works ✓
   - Second click blocked by rate limit ✓

2. **Pro org:**
   - FAB visible on dashboard ✓
   - `/chat` shows normal interface ✓
   - Can send messages normally ✓

- [ ] **Step 4: Verify acceptance criteria**

From the design spec:
- ✅ FAB visibility respects org subscription tier (hidden for non-Pro)
- ✅ `/chat` page shows full-page empty state for non-Pro orgs
- ✅ "Contact Administrator" button present and functional
- ✅ Rate limiting: per-user (1 per 24h) and per-org (3 per 24h)
- ✅ Toast/feedback messages are clear and actionable
- ✅ Pro orgs always have full chat access (system AI guaranteed)
- ✅ Rate limiting abstracted as `RateLimitService` (swappable for Redis)
- ✅ All tests passing (unit, integration, E2E)

- [ ] **Step 5: Final commit (if any cleanup needed)**

```bash
git add .
git commit -m "test: verify all acceptance criteria met"
```

---

## Task 9: QA Verification (Browser Testing)

**Context:** Launch qa-verify agent to perform comprehensive browser-based testing of the UI/UX changes.

- [ ] **Step 1: Start dev servers**

Ensure both backend and frontend dev servers are running:

```bash
# Terminal 1: Backend
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev  # runs on :5173
```

- [ ] **Step 2: Launch qa-verify agent**

Dispatch the qa-verify agent with:

```
Prompt: "Verify BUG-0050 Chat AI Gating implementation"

Context:
- Feature: Gate chat access by org subscription tier
- Non-Pro orgs: FAB hidden, /chat shows empty state with "Contact Administrator" button
- Pro orgs: FAB visible, /chat works normally
- Rate limiting: admin notifications limited (1/user/24h, 3/org/24h)

Test as:
1. Non-Pro user (e.g., create one via /register or use test fixture)
   - Verify FAB not visible on dashboard
   - Navigate to /chat → verify empty state displays
   - Verify "Contact Administrator" button is present and styled correctly
   - Click button → verify success message shows
   - Click again → verify rate limit message shows
   - Check browser console for errors
   
2. Pro user (create Pro org in DB or use test fixture)
   - Verify FAB visible on dashboard
   - Click FAB → verify chat panel opens
   - Navigate to /chat → verify full chat UI (sidebar, messages, input)
   - Send a test message → verify it works (or appropriate error if AI not available)
   - Check for layout issues, overflow, responsive design on mobile

Verify:
- Empty state styling is professional and on-brand
- Buttons are appropriately sized and clickable
- Toast/success messages are clear
- No broken links (especially admin settings link if shown)
- Mobile responsiveness
- Accessibility (keyboard navigation, ARIA labels)
- No console errors or warnings
```

Agent will test the implementation in the browser, verify UI/UX quality, and report any issues.

Expected: Agent reports PASS, no layout/styling issues, all functionality working.

- [ ] **Step 3: Review qa-verify report**

The agent will provide a detailed report. Check for:
- Functional correctness (gating logic works)
- UI/UX quality (empty state looks good, buttons styled correctly)
- Mobile responsiveness (works on tablet/mobile)
- Accessibility (keyboard navigation, proper semantics)
- Performance (no lag, smooth interactions)

If agent finds issues, fix them inline and re-run verification.

- [ ] **Step 4: Commit verification results (if any fixes)**

```bash
git add .
git commit -m "fix: resolve QA verification issues"
```

---

## Task 10: User Verification & Task Closure

**Context:** Get explicit user sign-off that the feature meets acceptance criteria and is ready to ship.

- [ ] **Step 1: Summarize changes to user**

Present a summary of what was implemented:

**Backend:**
- ✅ RateLimitService abstraction (in-memory DB, swappable for Redis)
- ✅ POST /chat/notify-admin endpoint with dual rate limiting
- ✅ ChatNotification + ChatRateLimitAttempt models + migration

**Frontend:**
- ✅ Subscription tier gating (FAB hidden for non-Pro)
- ✅ Full-page empty state on /chat for non-Pro orgs
- ✅ "Contact Administrator" button with success/error messaging
- ✅ Rate limit feedback (429 errors handled gracefully)

**Testing:**
- ✅ Unit tests: RateLimitService logic
- ✅ Integration tests: POST /chat/notify-admin endpoint
- ✅ E2E tests: FAB visibility, empty state, notification flow
- ✅ Manual verification: dashboard & /chat for both Pro and non-Pro users
- ✅ QA browser verification: UI/UX quality, accessibility, mobile responsiveness

**Files Changed:** 7 modified, 8 created
**Test Coverage:** >80% on backend
**All Acceptance Criteria Met:** ✓

- [ ] **Step 2: Ask user for explicit verification**

Present the following to the user:

---

**Feature Verification Checklist**

Please confirm the following before we close the task:

- [ ] **FAB Visibility:** Non-Pro users don't see chat FAB on dashboard; Pro users do
- [ ] **Empty State:** Non-Pro users see full-page empty state on /chat (not partial UI)
- [ ] **Notify Button:** "Contact Administrator" button is visible and clickable
- [ ] **Success Path:** Clicking notify button shows "Admin notified!" message
- [ ] **Rate Limiting:** Second click shows rate limit message (24h)
- [ ] **Pro User Access:** Pro users can access /chat and chat works normally
- [ ] **UI/UX Quality:** Empty state looks professional, buttons are properly sized
- [ ] **Mobile Responsive:** Works on mobile devices without overflow/layout issues
- [ ] **No Errors:** Browser console has no errors or warnings
- [ ] **Tests Pass:** All unit, integration, E2E tests passing

Once you've verified the above, please confirm: "✓ Feature complete and ready to ship"

---

- [ ] **Step 3: Wait for user confirmation**

Do not proceed to close the task until user explicitly confirms.

- [ ] **Step 4: Close task in ClickUp**

Once user confirms, run:

```bash
git log --oneline -10  # Show recent commits for reference
```

Then exit the worktree and close the task via ClickUp.

---

## Summary

**What was built:**
- Backend: RateLimitService abstraction, ChatNotification + ChatRateLimitAttempt models, POST /chat/notify-admin endpoint
- Frontend: Subscription tier gating for FAB, empty state with notify button for non-Pro orgs
- Testing: Unit, integration, E2E tests covering all flows

**Files created:** 8
**Files modified:** 7
**Tests added:** 3+ test files with comprehensive coverage
**Commits:** 8 atomic commits, each passing tests

---
