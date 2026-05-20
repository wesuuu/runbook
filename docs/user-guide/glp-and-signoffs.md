---
title: GLP sign-offs
summary: GLP mode, sign-offs, QAU independence, and approval gating.
keywords: [glp, signoff, qau, approval, compliance, audit]
---

# GLP sign-offs

Good Laboratory Practice (GLP) is a regulatory framework that requires formal, traceable sign-offs on studies and experiments. When GLP mode is enabled on a protocol, Batchrite enforces a structured sign-off chain — Operator, Study Director, and/or QAU (Quality Assurance Unit) — on both the protocol itself and on any runs executed from it. Sign-offs are time-stamped, locked to a signature image, and recorded in an immutable audit log.

## What you can do

- Enable or disable GLP sign-offs on individual protocols using the **GLP** button in the protocol editor toolbar.
- Require a **Study Director** sign-off (§58.33) and/or a **QAU** sign-off (§58.35) for a protocol.
- Designate a specific Study Director by name or allow any org member with the QAU role to fulfill QAU sign-off.
- Sign protocols and runs in your designated role using the **Sign as [ROLE]** button in the **GLP Sign-offs** section.
- See whether each required sign-off is **Signed** or still pending.
- View the full sign-off history — including invalidated sign-offs and the reason for invalidation — by expanding **Approval history** on the protocol page.
- View all runs or protocols awaiting your sign-off in the **Pending approvals** card on the dashboard.
- Set a saved signature image in **Settings → Appearance → Signature** so it is automatically embedded in sign-off records.

## How to enable GLP sign-offs on a protocol

1. Open a protocol in the editor.
2. In the toolbar at the top of the canvas, click the **GLP** button. The **GLP Settings** panel opens on the right side of the screen.
3. To require a Study Director sign-off, click the toggle next to **Require Study Director sign-off** so it reads **On**. Optionally choose a **Designated Study Director** from the member picker.
4. To require a QAU sign-off, click the toggle next to **Require QAU sign-off** so it reads **On**. Under **QAU assignment**, choose **Any org-level QAU** (any member with the QAU role can sign) or **Designate a person** (pin sign-off to one named individual).
5. Optionally edit the attestation text under **Attestation defaults** for each role.
6. Click **Apply** to save the settings to the protocol. The **GLP** button in the toolbar gains a pulsing indicator when sign-offs are required.
7. Save the protocol. When you next publish, the protocol will enter a **Submit for Approval** flow instead of publishing directly.

## How to sign off

Sign-off buttons appear in the **GLP Sign-offs** section on both protocol pages and run pages.

1. Go to the protocol or run that requires your sign-off.
2. In the **GLP Sign-offs** section, find the row for your role (for example, **OPERATOR**, **STUDY_DIRECTOR**, or **QAU**). If the row shows **Signed**, your sign-off is already recorded. If it shows **Sign as [ROLE]**, you have not yet signed.
3. Click **Sign as [ROLE]**. A dialog opens showing your role, the applicable CFR citation, and an **Attestation** field pre-filled with the default text for that role.
4. Review or edit the attestation text, then review the **Signature** preview. If you have a saved signature image, it appears here; otherwise your cursive name is used. To upload a signature, go to **Settings → Appearance**.
5. Click **Confirm sign-off**. Batchrite records your sign-off with a timestamp, locks in the signature image, and updates the row to show **Signed**.

## How approval gating works

When a protocol has Study Director or QAU sign-offs enabled, it cannot be started as a run until it passes an approval gate:

- When you click the publish button on a GLP-enabled protocol, Batchrite submits it for approval (**Submit for Approval**) rather than publishing it directly. The protocol status becomes **Pending Approval**.
- The designated approvers receive a notification and can see the protocol in their **Pending approvals** card. They approve or reject the protocol directly on the protocol page using the **Approve Protocol** or **Reject Protocol** actions.
- Runs cannot be created from a protocol that is still in **Pending Approval** status; only **Approved** protocols can be used to start runs.

**QAU independence** is enforced by the system automatically. The person who provides QAU sign-off must not have also acted as an operator, creator, lane assignee, or step actor on the same study. If you try to sign as QAU but you were involved in running the study, Batchrite shows an independence warning and blocks the sign-off. On protocols, QAU cannot be signed by the same person who holds an active Study Director sign-off.

Reopening a completed run (using **Reopen with reason**, then confirming **Reopen and invalidate sign-offs**) automatically invalidates all existing sign-offs for that run. The sign-off chain must be completed again before the run can be closed.
