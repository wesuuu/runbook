---
title: Organizations, roles, and permissions
summary: Organizations, member roles, and permission levels.
keywords: [organization, roles, permissions, members, invite]
---

# Organizations, roles, and permissions

Every Batchrite account belongs to an **organization**. All projects,
protocols, runs, and documents live inside that organization, and every
person who works on them must be a member of it. Only organization members
can log in and access the workspace.

## What you can do

- Invite colleagues to join your organization by email.
- Assign one or more roles to each member to control what they can manage.
- Control access to individual projects using permission grants (Viewer,
  Editor, Approver, or Admin).
- Remove members or revoke pending invitations.
- View the member list and filter by status (All, Active, Pending).

## The roles

Every member always has the **Member** role, which cannot be removed. On top
of that, admins can assign any combination of the following additive roles:

| Role | What it allows |
|---|---|
| **Admin** | Full access to everything in the organization — all projects, settings, member management, and AI configuration. |
| **Billing** | Access to billing and subscription settings. |
| **Protocol approver** | Can approve protocols in any project, without needing an explicit per-project permission grant. |
| **Site manager** | Manages one or more lab sites. When this role is assigned you must also select which sites the person manages. |

Org admins automatically have full access to every object in the organization
regardless of project-level permission settings.

## Permission levels

When a project has access control turned on, members (or teams) can be
granted one of four levels on that project:

| Level | What it allows |
|---|---|
| **Viewer** | Read-only access — can view protocols, runs, and documents. |
| **Editor** | Can create and edit protocols and runs inside the project. |
| **Approver** | Editor access plus the ability to approve protocols. |
| **Admin** | Full control over the project, including managing other members' access. |

When access control is turned off for a project, all organization members
automatically have Editor access to it.

## How to invite a member

You must have the **Admin** role to invite members.

1. Go to **Settings** (from the navigation menu).
2. The **Organization** tab opens by default. You will see the member list.
3. Click **Invite Member** (top-right of the member card).
4. Enter the colleague's email address in the field that appears.
5. Click **Send Invite**.

The recipient receives an email with a link to join. Until they accept, their
row in the member list shows a **Pending** status. If the link expires, click
**Resend** on their row to issue a fresh invitation. To cancel an outstanding
invitation before it is accepted, click **Revoke**.

After a member joins, click the role badge next to their name to open the
role picker and assign additional roles.
