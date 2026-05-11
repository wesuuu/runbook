# TD-0084 — Multi-role org membership

**Status:** Approved
**Priority:** P1
**Scope:** Full Stack (small/surgical)

## Problem

`OrganizationMember.role` is a single string column, so a user cannot simultaneously be `ADMIN` and `BILLING` (or, soon, `PROTOCOL_APPROVER`). This refactor converts the column to a list so capabilities become additive instead of mutually exclusive. Required by F-0066 (Protocol Approval), which introduces `PROTOCOL_APPROVER` as a new additive role.

## Design

### Storage

Replace `role: Mapped[str]` with `roles: Mapped[list[str]]`, using `sqlalchemy.dialects.postgresql.ARRAY(String)`.

```python
roles: Mapped[list[str]] = mapped_column(
    ARRAY(String),
    nullable=False,
    server_default=text("ARRAY['MEMBER']::varchar[]"),
)
```

Add a CHECK constraint enforcing every element is in the allowed set:

```sql
CHECK (roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER']::varchar[])
```

Rationale: ARRAY gives clean containment operators (`@>`, `ANY`) for the WHERE-clause sites that filter "members where roles contains ADMIN", and a CHECK constraint catches drift. JSONB would force `jsonb_array_elements` gymnastics for the same queries.

### MEMBER is implicit

`MEMBER` is the baseline org-membership marker — it is always present, never removable. Adding `ADMIN` produces `['MEMBER','ADMIN']`. Removing all elevated roles leaves `['MEMBER']`. This matches the prior single-column behavior (everyone had a role; `MEMBER` was the default) and lets the resolver treat membership existence == having `MEMBER`.

Server enforces by always inserting `MEMBER` into the set on any write.

### Roles enum

Extend `OrgRole`:

```python
class OrgRole(str, Enum):
    ADMIN = "ADMIN"
    BILLING = "BILLING"
    MEMBER = "MEMBER"
    PROTOCOL_APPROVER = "PROTOCOL_APPROVER"  # defined only; F-0066 enforces
```

### Helpers

Module-level functions in `models/iam.py` (matching the codebase's stateless-helper convention):

```python
def has_org_role(membership: OrganizationMember, role: str) -> bool:
    return role in (membership.roles or [])

def has_any_org_role(membership: OrganizationMember, roles: Iterable[str]) -> bool:
    member_roles = set(membership.roles or [])
    return any(r in member_roles for r in roles)
```

Read sites swap `membership.role == "ADMIN"` for `has_org_role(membership, "ADMIN")`.

### SQL filter sites

Sites that filter the table by role (admin counts, "is admin" lookups) switch to ARRAY containment via SQLAlchemy:

```python
# old:  OrganizationMember.role == OrgRole.ADMIN
# new:  OrganizationMember.roles.contains([OrgRole.ADMIN.value])
```

### Endpoints

`POST /iam/organizations/{org_id}/members` and `PATCH /iam/organizations/{org_id}/members/{user_id}` accept:

```json
{ "roles": ["ADMIN", "BILLING"] }
```

Validation:
- All values must be in `OrgRole` enum → 400 with the offending value.
- Server always normalizes to include `MEMBER`, so an empty `roles: []` is accepted and stored as `['MEMBER']`.

**Back-compat shim** (one release): if `roles` is absent and `role` is present, wrap as `roles=[role]` and emit a `DeprecationWarning` log line. Drop the shim in the release after F-0066 ships.

### Invitations

Out of scope. `Invitation.role` stays a single string. When an invitation is accepted, the new membership gets `roles=['MEMBER', invitation.role]` (deduplicated). Future task can broaden `Invitation.role` if needed.

### Migration

Single Alembic revision:

1. `ADD COLUMN roles varchar[] NOT NULL DEFAULT ARRAY['MEMBER']`
2. `UPDATE organization_members SET roles = ARRAY(SELECT DISTINCT unnest(ARRAY[role, 'MEMBER']))`
3. `ADD CONSTRAINT ck_org_member_roles CHECK (roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER']::varchar[])`
4. `DROP COLUMN role`

Down migration is the inverse: add back `role`, set it to `'ADMIN' if 'ADMIN'=ANY(roles) else 'BILLING' if 'BILLING'=ANY(roles) else 'MEMBER'`, drop `roles`.

### Frontend

`OrgMemberSchema.role: string` → `roles: array<string>` (Zod). Settings page (`routes/settings/+page.svelte`):
- `isOrgAdmin` derives from `roles.includes('ADMIN')`.
- The Role table column replaces its `<select>` with a chip-trigger that opens a `Popover` containing `dropdown-menu-checkbox-item`s (one per non-MEMBER role). The trigger displays each currently-assigned role as a `Badge`, plus a chevron.
- `MEMBER` renders as a dimmed, non-clickable `Badge` (the server enforces it; UI shows it but does not allow toggling).
- Closing the popover with changes triggers a single `PATCH /iam/organizations/{org_id}/members/{user_id}` with the full new `roles` list. Optimistic update + toast on failure.
- Mobile card snippet keeps its single-line role display, just rendering the chips inline (badges already wrap).
- Invite-dialog initial role stays single-select (matches `Invitation.role` — out of scope).

Layout sketch:

```
│ User             │ Roles                          │ Status  │ ...
│ Jane Doe         │ [Member] [Admin]            ▾  │ Active  │ ...
│                                  ↑ click opens popover with checkbox list
```

### Tests

- `backend/tests/integration/test_org_membership.py` — extended with multi-role assignment, role removal, validation of unknown values, MEMBER cannot be removed (request without MEMBER still keeps it), back-compat shim accepts `{"role": "ADMIN"}` and emits the deprecation log.
- `backend/tests/unit/test_permissions.py` — existing tests keep passing; add a multi-role member with `['MEMBER','ADMIN']` and verify ADMIN privileges resolve.
- New: `backend/tests/integration/test_multi_role_migration.py` — applies migration on a seeded prior-state row and asserts backfill includes both the original role and `MEMBER`.

## Acceptance criteria → coverage map

| AC | Where verified |
|---|---|
| Member can hold N roles concurrently | integration test: assign `['ADMIN','BILLING']`, GET returns both |
| ADMIN behavior unchanged | resolver test: `['MEMBER','ADMIN']` member has full org access |
| Role values defined as constants | `OrgRole` enum extended with PROTOCOL_APPROVER |
| Resolver uses only `roles` | grep -- no `.role` on `OrganizationMember` instances anywhere |
| Add/remove via API works | integration test: PATCH adds, PATCH removes, resolver reflects |
| Back-compat shim accepts `{"role": "X"}` for one release | shim test + deprecation log assertion |
| Org-members admin UI is multi-select | settings page renders chip picker |
| Migration backfill correct | dedicated migration test |
| Validation rejects unknown roles | integration test: `roles: ['BOGUS']` → 400 |
| MEMBER cannot be removed | integration test: PATCH `roles: []` returns `['MEMBER']` |

## Out of scope

- Enforcement of `BILLING`/`PROTOCOL_APPROVER` (their own tasks)
- `TeamMember` multi-role
- `Invitation.role` plurality
- Per-project member multi-role (already handled by `ObjectPermission`)
