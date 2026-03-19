import ipaddress
import logging
import re
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.library import (
    Document,
    DocumentStatus,
    MAX_URL_RESPONSE_BYTES,
)

logger = logging.getLogger(__name__)

USER_AGENT = "TrellisBot/1.0"

# Private/internal IP ranges to block (SSRF prevention)
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/internal IP."""
    try:
        addr = ipaddress.ip_address(hostname)
        return any(addr in network for network in _BLOCKED_NETWORKS)
    except ValueError:
        # Not an IP literal — could be a domain. We'll resolve it.
        import socket
        try:
            infos = socket.getaddrinfo(hostname, None)
            for info in infos:
                addr = ipaddress.ip_address(info[4][0])
                if any(addr in network for network in _BLOCKED_NETWORKS):
                    return True
        except socket.gaierror:
            # Can't resolve — let httpx handle the error
            pass
    return False


async def check_robots_txt(url: str) -> bool:
    """Check if robots.txt allows fetching the given URL.

    Returns True if fetching is allowed, False if disallowed.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                robots_url,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                # No robots.txt or error — assume allowed
                return True

            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp.can_fetch(USER_AGENT, url)
    except Exception:
        # Network error fetching robots.txt — assume allowed
        return True


async def import_from_url(
    url: str,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    title: Optional[str],
    project_id: Optional[uuid.UUID],
    db: AsyncSession,
) -> Document:
    """Fetch a URL, extract text, and create a Document record.

    Args:
        url: The URL to import.
        org_id: Organization ID.
        user_id: Uploading user ID.
        title: Optional title override.
        project_id: Optional project to associate with.
        db: Database session.

    Returns:
        The created Document.

    Raises:
        ValueError: If the URL is invalid, blocked, or disallowed.
    """
    parsed = urlparse(str(url))

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Only http and https URLs are supported, got: {parsed.scheme}"
        )

    # SSRF prevention
    if not parsed.hostname:
        raise ValueError("Invalid URL: no hostname")

    if is_private_ip(parsed.hostname):
        raise ValueError("URLs pointing to private/internal IPs are blocked")

    # Check robots.txt
    allowed = await check_robots_txt(str(url))
    if not allowed:
        raise ValueError(
            "This URL is disallowed by the site's robots.txt"
        )

    # Fetch the URL
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        max_redirects=5,
    ) as client:
        resp = await client.get(
            str(url),
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()

        if len(resp.content) > MAX_URL_RESPONSE_BYTES:
            raise ValueError(
                f"Response too large: {len(resp.content)} bytes "
                f"(max {MAX_URL_RESPONSE_BYTES})"
            )

    # Extract text using trafilatura
    extracted_text = _extract_text_from_html(resp.text)

    if not extracted_text or not extracted_text.strip():
        raise ValueError("Could not extract text content from URL")

    # Determine title
    if not title:
        title = _extract_title_from_html(resp.text) or parsed.path.split(
            "/"
        )[-1] or "Imported document"

    # Store extracted text as a .txt file
    file_id = str(uuid.uuid4())
    storage_dir = Path(settings.document_storage_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    file_path = storage_dir / f"{file_id}.txt"
    file_path.write_text(extracted_text, encoding="utf-8")

    # Sanitize filename from URL
    url_filename = parsed.path.split("/")[-1] or "imported.html"
    # Strip any dangerous characters
    url_filename = re.sub(r"[^\w.\-]", "_", url_filename)

    doc = Document(
        org_id=org_id,
        project_id=project_id,
        uploaded_by_id=user_id,
        title=title,
        original_filename=url_filename,
        mime_type="text/html",
        file_size_bytes=len(extracted_text.encode("utf-8")),
        file_path=str(file_path),
        status=DocumentStatus.UPLOADED.value,
        source_url=str(url),
    )
    db.add(doc)
    await db.flush()
    return doc


def _extract_text_from_html(html: str) -> str:
    """Extract clean text from HTML using trafilatura with fallback."""
    try:
        import trafilatura

        result = trafilatura.extract(html)
        if result:
            return result
    except Exception:
        logger.warning("trafilatura extraction failed, using fallback")

    # Fallback: basic HTML tag stripping
    clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _extract_title_from_html(html: str) -> Optional[str]:
    """Extract title from HTML <title> tag."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None
