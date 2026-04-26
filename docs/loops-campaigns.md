# Loops Lifecycle Messaging

Batchrite delegates all lifecycle email (welcome, trial reminders, dunning,
upgrade thank-you) to [Loops](https://loops.so). Our app stays thin: we emit
events and contact properties; Loops owns timing, copy, templating, delivery.

## Configuration

Set `BATCHRITE_LOOPS_API_KEY` to a Loops API key (Settings -> API in the Loops
dashboard). When unset, every emission is a silent no-op -- local dev, CI, and
self-hosted deployments run without a Loops account.

Optional overrides (rarely needed):

- `BATCHRITE_LOOPS_BASE_URL` — defaults to `https://app.loops.so/api/v1`.
- `BATCHRITE_LOOPS_REQUEST_TIMEOUT_SECONDS` — defaults to `5.0`.

## Events the app emits

| Event name              | Fired from                                              | When                                                |
| ----------------------- | ------------------------------------------------------- | --------------------------------------------------- |
| `signed_up`             | `auth.register`                                         | User finishes registration                          |
| `trial_started`         | `auth.register` (right after Stripe trial subscription) | Trial subscription created                          |
| `subscription_changed`  | Stripe webhook `customer.subscription.(created/updated)`| Tier OR status changes                              |
| `trial_expired`         | Stripe webhook `customer.subscription.deleted`          | Trial ended without payment method                  |

Event properties sent with `subscription_changed`:
`previous_plan`, `new_plan`, `previous_status`, `new_status`.
Use these in Loops workflow branches (e.g. upgrade vs downgrade).

## Contact properties synced

Every call upserts these fields on the contact (keyed by email):

| Property        | Source                         | Notes                                    |
| --------------- | ------------------------------ | ---------------------------------------- |
| `email`         | `user.email`                   | Primary key                              |
| `firstName`     | `user.full_name` first token   | Only when set; never overwritten w/ null |
| `org_id`        | `organization.id`              | UUID string                              |
| `org_name`      | `organization.name`            |                                          |
| `plan`          | `organization.subscription_tier` | `essentials` / `pro` / `enterprise`    |
| `status`        | `organization.subscription_status` | `trialing` / `active` / `canceled` / `past_due` |
| `trial_end`     | `organization.trial_end`       | ISO date string (YYYY-MM-DD)             |
| `days_in_trial` | Derived at signup              | Integer; used only on the first event    |

`trial_end` drives the built-in Loops workflow condition "contact.trial_end is
N days away". Do not emit extra reminder events from the app — just keep
`trial_end` fresh on the contact.

## Privacy / data minimization

Batchrite syncs ONLY the fields above. Explicitly NOT sent to Loops:

- Password hashes or any credential material.
- Protocol, run, experiment, batch-record, or document content. Lab data
  stays in the app database.
- Internal identifiers other than `org_id` and the contact's email.
- IP addresses, audit logs, or device metadata.

If marketing needs a new property, add it in `services/lifecycle/events.py`
(`_contact_properties`) and document it here. Do not add call-site-specific
properties inline.

## Campaigns (dashboard work)

Built in the Loops UI, not version-controlled. Suggested minimum set:

- **Welcome sequence** — trigger: `signed_up`. Intro + a single "here's what
  to try first" email at +1 day.
- **Trial ending reminders** — triggers: `contact.trial_end is 14 / 7 / 3 / 1
  day(s) away` and `contact.trial_end is today`. Loops handles the schedule
  from the `trial_end` property; no event emission from the app.
- **Post-trial dunning** — trigger: `trial_expired`. One-email nudge, then
  stop. Do not spam.
- **Upgrade thank-you** — trigger: `subscription_changed` where
  `new_plan` rank > `previous_plan` rank.

Changes to event names or property keys must be coordinated between this doc,
`services/lifecycle/events.py`, and the Loops dashboard triggers.
