"""Thin REST wrapper around the Loops API (loops.so).

Three public functions:
  - contacts_create(email, properties)
  - contacts_update(email, properties)   # upsert
  - events_send(email, event_name, event_properties, contact_properties)

Design notes:
  - No-op when BATCHRITE_LOOPS_API_KEY is unset. Registration and webhook
    flows must keep working locally / in CI without a Loops account.
  - Errors (HTTP non-2xx or network failures) are logged and swallowed.
    Lifecycle messaging is fire-and-forget; a Loops outage must never
    break user-facing flows.
  - Test seam: set_fake_client(fake) routes every call to fake.<method>
    so integration tests can assert exact events emitted.
"""

import logging
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


_fake_client: Any = None


def _reset_cache() -> None:
    """Clear any injected fake. Test-only."""
    global _fake_client
    _fake_client = None


def set_fake_client(fake: Any) -> None:
    """Inject a fake recorder; all calls route to fake.<method>(...) until reset."""
    global _fake_client
    _fake_client = fake


def is_configured() -> bool:
    """True iff BATCHRITE_LOOPS_API_KEY is populated."""
    return bool(settings.loops_api_key)


def contacts_create(*, email: str, properties: dict[str, Any]) -> None:
    """Create a contact in Loops. No-op when unconfigured."""
    if _fake_client is not None:
        _fake_client.contacts_create(email=email, properties=properties)
        return
    if not is_configured():
        return
    _post("/contacts/create", {"email": email, **properties})


def contacts_update(*, email: str, properties: dict[str, Any]) -> None:
    """Upsert a contact in Loops (create if missing, update if present)."""
    if _fake_client is not None:
        _fake_client.contacts_update(email=email, properties=properties)
        return
    if not is_configured():
        return
    _post("/contacts/update", {"email": email, **properties})


def events_send(
    *,
    email: str,
    event_name: str,
    event_properties: Optional[dict[str, Any]] = None,
    contact_properties: Optional[dict[str, Any]] = None,
) -> None:
    """Send an event. Contact properties merge into the contact server-side."""
    if _fake_client is not None:
        _fake_client.events_send(
            email=email,
            event_name=event_name,
            event_properties=event_properties or {},
            contact_properties=contact_properties or {},
        )
        return
    if not is_configured():
        return

    body: dict[str, Any] = {
        "email": email,
        "eventName": event_name,
        "eventProperties": event_properties or {},
    }
    # Loops accepts contact properties at the top level of events/send;
    # they upsert onto the contact alongside the event.
    if contact_properties:
        body.update(contact_properties)
    _post("/events/send", body)


def _post(path: str, body: dict[str, Any]) -> None:
    url = f"{settings.loops_base_url.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {settings.loops_api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client() as client:
            resp = client.post(
                url,
                json=body,
                headers=headers,
                timeout=settings.loops_request_timeout_seconds,
            )
        if resp.status_code >= 400:
            logger.warning(
                "Loops API %s returned %s: %s",
                path,
                resp.status_code,
                resp.text[:500],
            )
    except httpx.HTTPError:
        logger.exception("Loops API %s request failed", path)
