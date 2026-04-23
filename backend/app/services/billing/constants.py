"""Constants for the billing subsystem."""

from uuid import UUID

# System actor UUID used as actor_id in log_audit calls for webhook-driven
# state changes (where there is no authenticated user). Must be a valid
# UUID literal; does NOT need to exist in the users table since audit_logs
# does not enforce an FK on actor_id. (If an FK is added later, seed this
# UUID as a system user row.)
STRIPE_SYSTEM_ACTOR_ID: UUID = UUID("00000000-0000-0000-0000-00005771419e")
