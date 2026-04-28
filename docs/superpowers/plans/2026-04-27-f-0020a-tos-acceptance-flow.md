# F-0020a — Terms of Service & Legal Acceptance Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-04-27-f-0020a-tos-acceptance-flow-design.md`](../specs/2026-04-27-f-0020a-tos-acceptance-flow-design.md)

**Goal:** Add a clickwrap ToS/Privacy acceptance flow that gates app usage on first authenticated load and on subsequent ToS version changes, with versioned backend-served content and on-prem/enterprise bypass knobs.

**Architecture:** Backend stores versioned markdown under `backend/app/legal/versions/<date>/{terms,privacy}.md` with an explicit `CURRENT_VERSION` constant. Public GET endpoints serve the content. `POST /auth/accept-tos` records acceptance on the User row plus an AuditLog row. Frontend layout gates authenticated, email-verified users at `/legal/accept` until `tos_current` is `true`. Two bypass knobs (`BATCHRITE_LEGAL_GATE_ENABLED` env var, `Organization.legal_terms_overridden` flag) accommodate enterprise/on-prem.

**Tech Stack:** FastAPI (async), SQLAlchemy 2.0, Alembic, PostgreSQL JSONB, Pydantic v2, Svelte 5 (Runes), SvelteKit, Vitest, Playwright, marked + DOMPurify (existing).

---

## Task 1: Versioned content scaffold (backend)

**Files:**
- Create: `backend/app/legal/__init__.py`
- Create: `backend/app/legal/service.py`
- Create: `backend/app/legal/versions/__init__.py`
- Create: `backend/app/legal/versions/2026-04-27/__init__.py` (empty, makes directory importable)
- Create: `backend/app/legal/versions/2026-04-27/terms.md` (placeholder; real content in Task 2)
- Create: `backend/app/legal/versions/2026-04-27/privacy.md` (placeholder; real content in Task 2)
- Test: `backend/tests/unit/test_legal_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_legal_service.py
import pytest

from app.legal import service as legal_service
from app.legal.versions import ALL_VERSIONS, CURRENT_VERSION


def test_current_version_is_in_all_versions():
    assert CURRENT_VERSION in ALL_VERSIONS


def test_get_current_version_returns_constant():
    assert legal_service.get_current_version() == CURRENT_VERSION


def test_list_versions_returns_all_versions():
    assert legal_service.list_versions() == list(ALL_VERSIONS)


def test_get_document_returns_terms_for_current_version():
    doc = legal_service.get_document(CURRENT_VERSION, "terms")
    assert doc["version"] == CURRENT_VERSION
    assert doc["effective_date"] == CURRENT_VERSION
    assert isinstance(doc["markdown"], str)
    assert len(doc["markdown"]) > 0


def test_get_document_returns_privacy_for_current_version():
    doc = legal_service.get_document(CURRENT_VERSION, "privacy")
    assert doc["version"] == CURRENT_VERSION
    assert doc["effective_date"] == CURRENT_VERSION
    assert isinstance(doc["markdown"], str)
    assert len(doc["markdown"]) > 0


def test_get_document_unknown_version_raises_key_error():
    with pytest.raises(KeyError):
        legal_service.get_document("does-not-exist", "terms")


def test_get_document_unknown_doc_type_raises_value_error():
    with pytest.raises(ValueError):
        legal_service.get_document(CURRENT_VERSION, "bogus-doc")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_legal_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.legal'` (or similar import error).

- [ ] **Step 3: Create the directory structure and registry**

`backend/app/legal/__init__.py`:
```python
"""Legal documents (Terms of Service, Privacy Policy) — versioned content service.

The frontend fetches all legal content from this backend module via the
`/legal/...` endpoints. See `service.py` for the public API and
`versions/__init__.py` for the version registry.
"""
```

`backend/app/legal/versions/__init__.py`:
```python
"""Registered legal document versions.

CURRENT_VERSION is the single explicit constant that controls what version
the app considers "live in production." Bumping it is the activation step.

ALL_VERSIONS is the full chronological list. CURRENT_VERSION must be a member.
Old versions are never removed — they remain valid for historical lookups
and to preserve the meaning of `users.tos_version` values pinned to old
versions.

Activation commit message convention (grep-able):

    feat(legal): activate ToS/Privacy version <date>
"""

CURRENT_VERSION = "2026-04-27"

ALL_VERSIONS = [
    "2026-04-27",
]

assert CURRENT_VERSION in ALL_VERSIONS, (
    f"CURRENT_VERSION={CURRENT_VERSION!r} is not in ALL_VERSIONS"
)
```

`backend/app/legal/versions/2026-04-27/__init__.py`:
```python
```
(empty file — makes the dated directory importable; the markdown lives next to it.)

`backend/app/legal/versions/2026-04-27/terms.md`:
```markdown
<!-- TODO: Have counsel review before signing first paid contract or accepting any regulated data. Last drafted: 2026-04-27 by Wesley + Claude. -->
# Terms of Service

**Version:** 2026-04-27
**Effective Date:** 2026-04-27

(Placeholder — real content drafted in Task 2.)
```

`backend/app/legal/versions/2026-04-27/privacy.md`:
```markdown
<!-- TODO: Have counsel review before signing first paid contract or accepting any regulated data. Last drafted: 2026-04-27 by Wesley + Claude. -->
# Privacy Policy

**Version:** 2026-04-27
**Effective Date:** 2026-04-27

(Placeholder — real content drafted in Task 2.)
```

`backend/app/legal/service.py`:
```python
"""Public service API for legal document versions.

Used by:
  * `app.api.endpoints.legal` — to serve content over HTTP.
  * `app.schemas.auth.UserResponse` — to compute `tos_current`.
  * `app.api.endpoints.auth.accept_tos` — to pin acceptance to `get_current_version()`.

Document content is read from disk at module load time (cached in memory)
because it is bundled with the deploy and never changes at runtime.
"""

from functools import lru_cache
from importlib.resources import files
from typing import TypedDict

from app.legal.versions import ALL_VERSIONS, CURRENT_VERSION

ALLOWED_DOCS: tuple[str, ...] = ("terms", "privacy")


class LegalDocument(TypedDict):
    version: str
    effective_date: str
    markdown: str


def get_current_version() -> str:
    return CURRENT_VERSION


def list_versions() -> list[str]:
    return list(ALL_VERSIONS)


@lru_cache(maxsize=None)
def get_document(version: str, doc: str) -> LegalDocument:
    """Read a versioned legal document from disk and return its content.

    Raises:
        KeyError: when `version` is not in ALL_VERSIONS.
        ValueError: when `doc` is not in ALLOWED_DOCS.
        FileNotFoundError: when the expected markdown file is missing on disk.
    """
    if version not in ALL_VERSIONS:
        raise KeyError(version)
    if doc not in ALLOWED_DOCS:
        raise ValueError(f"unknown document type: {doc!r}")

    package = f"app.legal.versions.{version.replace('-', '_')}"
    # The dated directories include hyphens, but Python packages require
    # underscores. We use importlib.resources to read the file regardless.
    # Fall back to a literal path traversal if the dated package isn't
    # importable due to hyphens.
    try:
        resource = files(package).joinpath(f"{doc}.md")
        markdown = resource.read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError):
        # Hyphenated directory: read directly via filesystem path.
        from pathlib import Path

        base = Path(__file__).parent / "versions" / version
        markdown = (base / f"{doc}.md").read_text(encoding="utf-8")

    return LegalDocument(
        version=version,
        effective_date=version,
        markdown=markdown,
    )
```

(Note: the `2026-04-27` directory uses a hyphen, which isn't a valid Python identifier. The `importlib.resources` path will fall through to the filesystem read. The empty `__init__.py` is created defensively in case Python tooling tries to walk it; it's harmless either way.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_legal_service.py -v`
Expected: PASS — all 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/legal/ backend/tests/unit/test_legal_service.py
git commit -m "feat(legal): versioned content service with CURRENT_VERSION registry

Adds backend/app/legal/ scaffold: versions registry with
CURRENT_VERSION + ALL_VERSIONS constants, get_current_version()/
get_document() service API, and placeholder markdown for the
2026-04-27 version. Real content drafted in the next task."
```

---

## Task 2: Draft Terms of Service and Privacy Policy markdown

**Files:**
- Modify: `backend/app/legal/versions/2026-04-27/terms.md`
- Modify: `backend/app/legal/versions/2026-04-27/privacy.md`
- Test: `backend/tests/unit/test_legal_content.py`

This task replaces the placeholder markdown from Task 1 with the actual ToS and Privacy Policy content.

- [ ] **Step 1: Write the failing test (content sanity check)**

```python
# backend/tests/unit/test_legal_content.py
"""Sanity checks on the drafted legal content. These tests validate that
the documents include the load-bearing sections required by the spec —
not the prose itself, which is reviewed in PR diffs.
"""

from app.legal import service as legal_service
from app.legal.versions import CURRENT_VERSION


def test_terms_contains_required_sections():
    terms = legal_service.get_document(CURRENT_VERSION, "terms")["markdown"]
    required = [
        "Research Use Only",  # RUO designation
        "21 CFR 820",         # FDA medical device reference
        "Protected Health Information",  # HIPAA section
        "45 CFR 160.103",     # HIPAA citation
        "Business Associate", # BAA disclaimer
        "Limitation of Liability",
        "Governing Law",
        "California",         # governing law state
        "legal@batchrite.com",
    ]
    for needle in required:
        assert needle in terms, f"Terms missing required section/phrase: {needle!r}"


def test_privacy_contains_required_sections():
    privacy = legal_service.get_document(CURRENT_VERSION, "privacy")["markdown"]
    required = [
        "Information We Collect",
        "AI",                  # AI processing disclosure
        "Cookies",
        "Retention",
        "Your Rights",
        "do not use customer data to train",  # AI training commitment
        "privacy@batchrite.com",
    ]
    for needle in required:
        assert needle in privacy, f"Privacy missing required section/phrase: {needle!r}"


def test_terms_has_version_header():
    terms = legal_service.get_document(CURRENT_VERSION, "terms")["markdown"]
    assert "**Version:** 2026-04-27" in terms
    assert "**Effective Date:** 2026-04-27" in terms


def test_privacy_has_version_header():
    privacy = legal_service.get_document(CURRENT_VERSION, "privacy")["markdown"]
    assert "**Version:** 2026-04-27" in privacy
    assert "**Effective Date:** 2026-04-27" in privacy


def test_terms_includes_counsel_todo_marker():
    """Source-only marker so future-us remembers to involve counsel."""
    terms = legal_service.get_document(CURRENT_VERSION, "terms")["markdown"]
    assert "TODO: Have counsel review" in terms


def test_privacy_includes_counsel_todo_marker():
    privacy = legal_service.get_document(CURRENT_VERSION, "privacy")["markdown"]
    assert "TODO: Have counsel review" in privacy
```

- [ ] **Step 2: Run tests to verify they fail (placeholder content lacks the required sections)**

Run: `cd backend && pytest tests/unit/test_legal_content.py -v`
Expected: FAIL — most assertions fail because the placeholder markdown is empty of substance.

- [ ] **Step 3: Replace the placeholder ToS markdown**

Overwrite `backend/app/legal/versions/2026-04-27/terms.md` with:

```markdown
<!-- TODO: Have counsel review before signing first paid contract or accepting any regulated data. Last drafted: 2026-04-27 by Wesley + Claude. -->
# Terms of Service

**Version:** 2026-04-27
**Effective Date:** 2026-04-27

These Terms of Service ("Terms") govern your access to and use of Batchrite (the "Service"), provided by Batchrite, LLC, a California limited liability company ("Batchrite", "we", "us", or "our"). By creating an account, clicking "Accept", or otherwise using the Service, you agree to these Terms. If you do not agree, do not use the Service.

## 1. Acceptance

You accept these Terms by clicking "Accept" or by accessing the Service. If you are using the Service on behalf of an organization, you represent that you have authority to bind that organization and "you" refers to both you and that organization. These Terms become effective on the date you click "Accept".

## 2. Description of Service

Batchrite is a laboratory execution system that lets you author protocols, execute experiment runs, capture data, and use AI-assisted features for biotech research and development workflows. The Service is delivered as software-as-a-service over the Internet.

## 3. Research Use Only (RUO)

THE SERVICE IS PROVIDED FOR RESEARCH USE ONLY. The Service is **not** a medical device under 21 CFR 820, is **not** intended or validated for diagnostic use, and is **not** validated for cGMP, GLP, GCP, or other GxP-regulated workflows. We make no representations regarding compliance with any regulatory framework. If you choose to use the Service in any regulated context, you are solely responsible for any qualification, validation, change control, and oversight required.

## 4. Prohibition on Protected Health Information (HIPAA)

You represent and warrant that you will not upload, store, or transmit through the Service any "Protected Health Information" as defined in HIPAA at 45 CFR 160.103, or any other individually identifiable health information. We are **not** a Business Associate as defined under HIPAA, and no Business Associate Agreement ("BAA") is implied or in force unless separately executed in writing. If we discover or reasonably believe PHI has been uploaded to the Service, we may suspend or terminate the affected account without notice and require you to remediate.

## 5. Account & Eligibility

You must be at least 18 years old and use the Service for legitimate research, business, or professional purposes. You agree to provide accurate registration information, keep your credentials confidential, and notify us immediately of unauthorized access. You are responsible for activity under your account.

## 6. License Grant

Subject to these Terms and your payment of applicable fees, we grant you a limited, non-exclusive, non-transferable, non-sublicensable, revocable license to access and use the Service for your internal research and business purposes during your subscription term.

## 7. Customer Data; License to Us

You retain all right, title, and interest in the data, content, and materials you upload, create, or transmit through the Service ("Customer Data"). You grant us a limited, worldwide, royalty-free license to host, store, transmit, display, modify, and process Customer Data solely as necessary to deliver and improve the Service for you. **We do not use Customer Data to train AI models, and we will not share Customer Data with third-party AI providers in a manner that allows them to train on it.** Any other use of your data for training requires your separate written consent.

## 8. Acceptable Use

You agree not to: (a) use the Service for any unlawful purpose; (b) reverse engineer, decompile, or attempt to derive the source code of the Service except where applicable law expressly permits; (c) scrape, crawl, or use automated means to access the Service except via our supported APIs; (d) upload PHI in violation of Section 4; (e) resell, sublicense, or commercially exploit the Service without our written consent; (f) interfere with or disrupt the Service, its security, or other users' use; or (g) circumvent any usage limits, quotas, or access controls.

## 9. Intellectual Property

We retain all right, title, and interest in the Service, including all software, designs, trademarks, and improvements. Your feedback and suggestions become non-confidential, and you grant us a perpetual, irrevocable, royalty-free license to use them. Customer Data remains yours.

## 10. Confidentiality

Each party agrees to protect the other's Confidential Information using at least the same care it uses for its own (and no less than reasonable care). Customer Data is your Confidential Information. Each party may use Confidential Information only as necessary to perform under these Terms. These obligations survive termination.

## 11. Fees & Payment

Where the Service or particular features require payment, fees are billed via Stripe and are non-refundable for partial billing periods. We may change fees on reasonable notice; changes apply to renewals. Unpaid fees may result in suspension. You are responsible for taxes other than our income taxes.

## 12. Term & Termination

These Terms remain in effect while your account is active. Either party may terminate at any time, with paid plans terminating at the end of the then-current billing period. Upon termination we will make Customer Data available for export for thirty (30) days, after which we may delete it. Sections that by their nature should survive (e.g., 4, 7, 9, 10, 13, 14, 15, 16) will survive termination.

## 13. Warranty Disclaimer

THE SERVICE IS PROVIDED "AS IS" AND "AS AVAILABLE" WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING WITHOUT LIMITATION WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, OR FITNESS FOR ANY REGULATED USE (INCLUDING CLINICAL, DIAGNOSTIC, OR cGMP/GLP/GCP USE). WE DO NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED, ERROR-FREE, OR SECURE.

## 14. Limitation of Liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, OUR TOTAL LIABILITY ARISING OUT OF OR RELATING TO THESE TERMS WILL NOT EXCEED THE AMOUNTS YOU PAID US IN THE TWELVE (12) MONTHS PRECEDING THE EVENT GIVING RISE TO LIABILITY, OR ONE HUNDRED U.S. DOLLARS (US$100), WHICHEVER IS GREATER. NEITHER PARTY WILL BE LIABLE FOR INDIRECT, INCIDENTAL, CONSEQUENTIAL, SPECIAL, OR EXEMPLARY DAMAGES, INCLUDING LOST PROFITS, REVENUES, OR DATA, EVEN IF ADVISED OF THEIR POSSIBILITY.

## 15. Indemnification

You will indemnify and defend us against third-party claims arising from your breach of Sections 4 (PHI), 7 (Customer Data rights), or 8 (Acceptable Use). We will indemnify and defend you against third-party claims that the Service, as provided by us and used by you in accordance with these Terms, infringes that third party's U.S. intellectual property rights, subject to the limitations in Section 14.

## 16. Governing Law; Dispute Resolution

These Terms are governed by the laws of the State of California, without regard to conflict of laws rules. Before filing a formal proceeding, the parties will attempt in good faith to resolve any dispute through informal negotiation for thirty (30) days. Any unresolved dispute will be finally settled by binding arbitration administered by the American Arbitration Association under its Commercial Arbitration Rules, seated in San Francisco, California. Each party waives the right to participate in any class or representative action.

## 17. Changes to These Terms

We may update these Terms from time to time. Material changes will be communicated by re-prompting you to accept the new version through the Service ("clickwrap"). Your continued use of the Service after acceptance constitutes agreement to the updated Terms. The version and effective date appear at the top of these Terms.

## 18. Contact

Questions or notices: legal@batchrite.com.
```

- [ ] **Step 4: Replace the placeholder Privacy Policy markdown**

Overwrite `backend/app/legal/versions/2026-04-27/privacy.md` with:

```markdown
<!-- TODO: Have counsel review before signing first paid contract or accepting any regulated data. Last drafted: 2026-04-27 by Wesley + Claude. -->
# Privacy Policy

**Version:** 2026-04-27
**Effective Date:** 2026-04-27

This Privacy Policy describes how Batchrite, LLC ("Batchrite", "we", "us") collects, uses, and shares information when you use the Batchrite service (the "Service"). This policy applies to use of the Service and does not apply to third-party websites or services we do not control.

## 1. Information We Collect

We collect the following categories of information:

- **Account information:** name, email address, job title, password hash, OAuth provider identifiers, organization affiliations.
- **Customer Data:** the protocols, experiment runs, attachments, comments, and other content you create or upload to the Service.
- **Usage telemetry:** pages and features used, request timing, error reports, device and browser metadata, IP address, and approximate location derived from IP.
- **AI prompts and responses:** when you use AI-assisted features, the prompts you send and the responses you receive are stored on your account so you can refer back to them.
- **Billing information:** processed by Stripe, our payment processor. We receive a payment method token and the last four digits of your card; we do not see full payment card numbers.
- **Communications:** messages you send to support and any notices you submit.

## 2. How We Use It

We use the information to deliver and operate the Service; provide customer support; send service-related notices and security alerts; maintain and improve product performance; investigate and prevent abuse, fraud, and security incidents; comply with legal obligations; and, where you have consented, to send product updates and marketing communications.

We use aggregated and de-identified information to analyze product usage patterns and improve Batchrite. **We do not use customer data to train AI models.**

## 3. AI Processing Disclosure

The Service includes AI-assisted features (chat, suggestion, summarization, transcription) that send prompts and supporting context to third-party large-language-model ("LLM") providers (such as OpenAI, Anthropic, and similar). Under our contractual configuration with these providers, your data is **not** retained by them beyond the immediate request and is **not** used to train their models. Your organization administrator can disable AI features for the organization at any time. AI prompts and responses are stored on your Batchrite account; you can delete them through the Service.

## 4. How We Share It

We share information only as follows:

- **Sub-processors** that help us operate the Service: cloud hosting (e.g., AWS or Google Cloud), email delivery, error reporting, payment processing (Stripe), and the LLM providers described in Section 3. These sub-processors act on our behalf under written contracts.
- **Legal requirements:** when required by law, subpoena, court order, or other valid legal process; to protect rights, property, or safety; or to enforce our Terms.
- **Business transfers:** in connection with a merger, acquisition, financing, or sale of assets, subject to confidentiality protections.

We do **not** sell personal information.

## 5. Cookies & Local Storage

The Service uses browser local storage to keep your session token, your preferences, and an offline cache of recently viewed content. We do not use third-party advertising cookies. Some sub-processors may set cookies for security or analytics; these are described in their own policies.

## 6. Retention

We retain Customer Data for the lifetime of your account plus a thirty (30) day grace period after termination, after which we will delete it (subject to backup retention of up to ninety (90) days). Audit logs of system actions are retained for a longer period to support compliance and security investigations. You can request earlier deletion through the Service or by contacting us.

## 7. Security

We use technical and organizational measures to protect your information, including encryption in transit (TLS) and at rest, role-based access controls, audit logging, and least-privilege administration. No system is perfectly secure; if we discover a breach affecting your data we will notify you as required by applicable law.

## 8. Your Rights

Depending on your jurisdiction, you may have rights to access, correct, export, or delete your personal information, restrict or object to certain processing, and lodge a complaint with a supervisory authority. To exercise these rights, contact privacy@batchrite.com from the email associated with your account. We will respond within the time frames required by applicable law.

## 9. Children

The Service is not directed to individuals under 18, and we do not knowingly collect personal information from children. If you believe a child has provided us personal information, contact us and we will delete it.

## 10. International Transfers

Batchrite is hosted in the United States. By using the Service from outside the United States, you consent to the transfer of your information to and processing in the United States, which may have different data protection rules than your country of residence.

## 11. Changes to This Policy

We may update this Privacy Policy from time to time. Material changes will be communicated by re-prompting you to accept the updated policy through the Service. The version and effective date appear at the top of this policy.

## 12. Contact

Questions, requests, or complaints: privacy@batchrite.com.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_legal_content.py tests/unit/test_legal_service.py -v`
Expected: PASS — all content sanity checks green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/legal/versions/2026-04-27/terms.md \
        backend/app/legal/versions/2026-04-27/privacy.md \
        backend/tests/unit/test_legal_content.py
git commit -m "feat(legal): draft v2026-04-27 ToS and Privacy Policy

Drafts initial Terms of Service and Privacy Policy with RUO
designation, HIPAA-aligned PHI prohibition, AI training
commitments, California governing law, and limitation of
liability. Source includes counsel-review TODO marker."
```

---

## Task 3: Add tos columns to User and Organization models

**Files:**
- Modify: `backend/app/models/iam.py:143-182` (User class) and `:75-125` (Organization class)
- Test: `backend/tests/unit/test_iam_models.py` (create if absent; otherwise append)

- [ ] **Step 1: Write the failing test**

Append to or create `backend/tests/unit/test_iam_models.py`:

```python
from app.models.iam import Organization, User


def test_user_has_tos_columns():
    user_columns = {c.name for c in User.__table__.columns}
    assert "tos_accepted_at" in user_columns
    assert "tos_version" in user_columns


def test_user_tos_columns_are_nullable():
    cols = {c.name: c for c in User.__table__.columns}
    assert cols["tos_accepted_at"].nullable is True
    assert cols["tos_version"].nullable is True


def test_organization_has_legal_terms_overridden_column():
    org_columns = {c.name for c in Organization.__table__.columns}
    assert "legal_terms_overridden" in org_columns


def test_organization_legal_terms_overridden_default_false():
    cols = {c.name: c for c in Organization.__table__.columns}
    col = cols["legal_terms_overridden"]
    assert col.nullable is False
    # SQLAlchemy stores server_default as a TextClause whose .text is "false"
    assert getattr(col.server_default, "arg", None) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_iam_models.py -v`
Expected: FAIL — `KeyError: 'tos_accepted_at'` (or similar) and `KeyError: 'legal_terms_overridden'`.

- [ ] **Step 3: Add the columns**

In `backend/app/models/iam.py`, modify the `User` class (around line 143) to add the two ToS columns after `oauth_email_verified` and before `selected_org_id`:

```python
    oauth_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    tos_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tos_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    selected_org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
```

Make sure the imports at the top of `iam.py` include `from datetime import datetime` (likely already present) and `DateTime` from `sqlalchemy` (likely already present). If not, add them.

In the same file, modify the `Organization` class (around line 75) to add the override column. Place it near other boolean flags or at the end of the column block, before `# Relationships`:

```python
    legal_terms_overridden: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_iam_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/iam.py backend/tests/unit/test_iam_models.py
git commit -m "feat(iam): add tos_accepted_at, tos_version, legal_terms_overridden columns

User gains nullable tos_accepted_at and tos_version. Organization
gains a non-null legal_terms_overridden boolean defaulted to false.
Migration in the next task."
```

---

## Task 4: Generate and apply the Alembic migration

**Files:**
- Create: `backend/alembic/versions/<rev>_add_tos_fields.py` (autogenerated)
- Test: `backend/tests/integration/test_tos_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_tos_migration.py
"""Migration sanity test — verifies that the columns are present on
the actual DB schema (not just on the model class) after migrations
have been applied. Runs against the fixture-managed test DB.
"""

import pytest
from sqlalchemy import inspect


@pytest.mark.asyncio
async def test_users_table_has_tos_columns(db):
    def _inspect(sync_conn):
        inspector = inspect(sync_conn)
        cols = {c["name"] for c in inspector.get_columns("users")}
        return cols

    cols = await db.run_sync(_inspect)
    assert "tos_accepted_at" in cols
    assert "tos_version" in cols


@pytest.mark.asyncio
async def test_organizations_table_has_legal_terms_overridden_column(db):
    def _inspect(sync_conn):
        inspector = inspect(sync_conn)
        cols = {c["name"] for c in inspector.get_columns("organizations")}
        return cols

    cols = await db.run_sync(_inspect)
    assert "legal_terms_overridden" in cols
```

(`db` fixture is already defined in the codebase's conftest. If the fixture has a different name, adapt — search `backend/tests/conftest.py` for the async DB session fixture name.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_tos_migration.py -v`
Expected: FAIL — columns not yet in the schema.

- [ ] **Step 3: Generate the migration**

Run from `backend/`:
```bash
source .venv/bin/activate
alembic revision --autogenerate -m "add tos_accepted_at, tos_version, legal_terms_overridden"
```

- [ ] **Step 4: Review the generated migration**

Open the new file in `backend/alembic/versions/` (it will have a hash prefix). Verify the `upgrade()` function contains:
- `op.add_column("users", sa.Column("tos_accepted_at", sa.DateTime(timezone=True), nullable=True))`
- `op.add_column("users", sa.Column("tos_version", sa.String(), nullable=True))`
- `op.add_column("organizations", sa.Column("legal_terms_overridden", sa.Boolean(), server_default=sa.text("false"), nullable=False))`

And the `downgrade()` drops these columns.

If the autogenerator produced extra spurious changes (it occasionally re-detects unrelated fields), edit the migration to keep only the three column additions and their reverse drops. Do not commit a noisy migration.

- [ ] **Step 5: Apply the migration**

Run from `backend/`:
```bash
alembic upgrade head
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_tos_migration.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/*_add_tos_accepted_at_tos_version_legal_terms_overridden.py \
        backend/tests/integration/test_tos_migration.py
git commit -m "feat(iam): alembic migration for tos fields

Adds tos_accepted_at and tos_version to users (both nullable) and
legal_terms_overridden to organizations (NOT NULL, default false)."
```

---

## Task 5: Add `legal_gate_enabled` setting

**Files:**
- Modify: `backend/app/core/config.py` (Settings class)
- Test: `backend/tests/unit/test_config_legal.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_config_legal.py
import os
from unittest.mock import patch

from app.core.config import Settings


def test_legal_gate_enabled_default_true():
    s = Settings()
    assert s.legal_gate_enabled is True


def test_legal_gate_enabled_can_be_disabled_via_env():
    with patch.dict(os.environ, {"BATCHRITE_LEGAL_GATE_ENABLED": "false"}):
        s = Settings()
        assert s.legal_gate_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_config_legal.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'legal_gate_enabled'`.

- [ ] **Step 3: Add the field to Settings**

Open `backend/app/core/config.py`. Add the field to the `Settings` class (near other boolean feature flags; preserve the existing alphabetical/grouped ordering used in the file):

```python
    legal_gate_enabled: bool = True  # env: BATCHRITE_LEGAL_GATE_ENABLED
```

(The existing `BATCHRITE_` env prefix is configured in the class's `model_config`; you don't need to add an alias.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_config_legal.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/unit/test_config_legal.py
git commit -m "feat(config): add legal_gate_enabled flag

Defaults to True. Set BATCHRITE_LEGAL_GATE_ENABLED=false on pure
on-prem deployments where users are governed by a separately-
negotiated agreement."
```

---

## Task 6: Extend `UserResponse` with ToS fields and `tos_current`

**Files:**
- Modify: `backend/app/schemas/auth.py` (UserResponse)
- Modify: `backend/app/api/endpoints/auth.py` (the `_user_response` helper)
- Test: `backend/tests/unit/test_user_response_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_user_response_schema.py
"""Unit tests for the tos_current computation logic. We test the helper
directly with simple objects rather than spinning up the DB — this is a
pure logic test."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.schemas.auth import compute_tos_current


def _user(tos_version=None, selected_org=None):
    return SimpleNamespace(
        tos_version=tos_version,
        tos_accepted_at=None,
        selected_organization=selected_org,
    )


def _org(overridden=False):
    return SimpleNamespace(legal_terms_overridden=overridden)


def test_tos_current_false_when_user_has_never_accepted(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", True)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    assert compute_tos_current(_user()) is False


def test_tos_current_false_when_user_accepted_old_version(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", True)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    assert compute_tos_current(_user(tos_version="2026-01-01")) is False


def test_tos_current_true_when_user_accepted_current_version(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", True)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    assert compute_tos_current(_user(tos_version="2026-04-27")) is True


def test_tos_current_true_when_gate_disabled(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", False)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    assert compute_tos_current(_user()) is True


def test_tos_current_true_when_org_overrides(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", True)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    overridden_org = _org(overridden=True)
    assert compute_tos_current(_user(selected_org=overridden_org)) is True


def test_tos_current_false_when_org_does_not_override_and_version_stale(monkeypatch):
    monkeypatch.setattr("app.schemas.auth.settings.legal_gate_enabled", True)
    monkeypatch.setattr("app.schemas.auth.get_current_version", lambda: "2026-04-27")
    org = _org(overridden=False)
    assert compute_tos_current(_user(selected_org=org)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_user_response_schema.py -v`
Expected: FAIL — `compute_tos_current` doesn't exist yet.

- [ ] **Step 3: Implement the helper and update the schema**

In `backend/app/schemas/auth.py`, add at the top (after existing imports):

```python
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.legal.service import get_current_version
```

(Merge with existing imports — don't duplicate.)

Add the helper above the `UserResponse` class:

```python
def compute_tos_current(user: Any) -> bool:
    """Return True if the user is considered current on ToS acceptance.

    True when ANY of:
      * the deployment-level gate is disabled, OR
      * the user's selected organization has legal_terms_overridden=True, OR
      * the user's tos_version equals the current version.
    """
    if not settings.legal_gate_enabled:
        return True
    org = getattr(user, "selected_organization", None)
    if org is not None and getattr(org, "legal_terms_overridden", False):
        return True
    return user.tos_version == get_current_version()
```

Update `UserResponse`:

```python
class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    job_title: Optional[str] = None
    avatar_url: Optional[str] = None
    preferences: dict[str, Any] = {}
    is_active: bool
    email_verified: bool
    tos_accepted_at: Optional[datetime] = None
    tos_version: Optional[str] = None
    tos_current: bool

    model_config = ConfigDict(from_attributes=True)
```

In `backend/app/api/endpoints/auth.py`, update the `_user_response` helper to populate the new fields. Locate it (around line 38) and replace its body:

```python
def _user_response(user: User) -> UserResponse:
    """Build UserResponse with computed avatar_url and tos_current."""
    avatar_url = None
    if user.avatar_path:
        avatar_url = f"/auth/avatars/{user.id}"
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        job_title=user.job_title,
        avatar_url=avatar_url,
        preferences=user.preferences or {},
        is_active=user.is_active,
        email_verified=user.email_verified,
        tos_accepted_at=user.tos_accepted_at,
        tos_version=user.tos_version,
        tos_current=compute_tos_current(user),
    )
```

Add `compute_tos_current` to the imports at the top of `auth.py`:

```python
from app.schemas.auth import (
    # ... existing imports ...
    UserResponse,
    compute_tos_current,
)
```

Other call sites in the file that construct `UserResponse` directly (search for `UserResponse(` and `email_verified=`) need the same three new keyword arguments. There are at least three direct constructions around lines 270–280, 370–380, 415–425 — update each. Using `_user_response(user)` is preferred when a `User` object is in scope, so where you can replace a direct construction with the helper call, do so.

Quick check:
```bash
cd backend && grep -n "UserResponse(" app/api/endpoints/auth.py
```
Each location must either (a) call `_user_response(user)`, or (b) include `tos_accepted_at`, `tos_version`, and `tos_current` keyword args.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_user_response_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Run the existing auth test suite to confirm no regressions**

Run: `cd backend && pytest tests/integration/ -v -k "auth"`
Expected: PASS — all existing auth tests still green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/auth.py \
        backend/app/api/endpoints/auth.py \
        backend/tests/unit/test_user_response_schema.py
git commit -m "feat(auth): expose tos_accepted_at, tos_version, tos_current on UserResponse

tos_current is computed from three branches: gate disabled,
org override, or version match. /auth/me and other endpoints
that return UserResponse now surface this for the frontend gate."
```

---

## Task 7: `GET /legal/...` public endpoints

**Files:**
- Create: `backend/app/api/endpoints/legal.py`
- Modify: `backend/app/main.py` (router registration)
- Modify: `backend/app/middleware/auth.py` or wherever public-path bypasses are listed (search needed)
- Test: `backend/tests/integration/test_legal_endpoints.py`

- [ ] **Step 1: Find where public auth bypass paths are configured**

Run:
```bash
cd backend && grep -rn "public_paths\|public_path\|/auth/login\|skip_auth\|exempt" app/middleware/ app/main.py app/core/
```

Expected output: a list of exempt path prefixes. You will need to add `/legal` to this list so the GET endpoints don't require auth. Note the file and pattern.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/integration/test_legal_endpoints.py
"""Integration tests for the public /legal/* endpoints.

These endpoints must work WITHOUT authentication so prospective users
and the marketing-page footer links function properly.
"""

import pytest


@pytest.mark.asyncio
async def test_legal_current_returns_version_and_effective_date(client):
    resp = await client.get("/legal/current")
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body
    assert "effective_date" in body
    assert body["version"] == body["effective_date"]


@pytest.mark.asyncio
async def test_legal_current_does_not_require_auth(unauthenticated_client):
    resp = await unauthenticated_client.get("/legal/current")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_legal_terms_returns_markdown(client):
    current = (await client.get("/legal/current")).json()["version"]
    resp = await client.get(f"/legal/versions/{current}/terms")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == current
    assert body["effective_date"] == current
    assert isinstance(body["markdown"], str)
    assert "Research Use Only" in body["markdown"]


@pytest.mark.asyncio
async def test_legal_privacy_returns_markdown(client):
    current = (await client.get("/legal/current")).json()["version"]
    resp = await client.get(f"/legal/versions/{current}/privacy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == current
    assert "do not use customer data to train" in body["markdown"]


@pytest.mark.asyncio
async def test_legal_versions_unknown_returns_404(client):
    resp = await client.get("/legal/versions/does-not-exist/terms")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_legal_versions_unknown_doc_type_returns_404(client):
    current = (await client.get("/legal/current")).json()["version"]
    resp = await client.get(f"/legal/versions/{current}/wat")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_legal_endpoints_do_not_require_auth(unauthenticated_client):
    current = (await unauthenticated_client.get("/legal/current")).json()["version"]
    resp = await unauthenticated_client.get(f"/legal/versions/{current}/terms")
    assert resp.status_code == 200
    resp = await unauthenticated_client.get(f"/legal/versions/{current}/privacy")
    assert resp.status_code == 200
```

If the conftest doesn't have an `unauthenticated_client` fixture yet, search `backend/tests/conftest.py` for a similar bare httpx client fixture and reuse its name. If only `client` exists (always authenticated), add a fixture; otherwise rename references in the test to whatever the unauthenticated fixture is called.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_legal_endpoints.py -v`
Expected: FAIL — endpoints return 404 (router not registered).

- [ ] **Step 4: Implement the router**

Create `backend/app/api/endpoints/legal.py`:

```python
"""Public endpoints for the versioned legal documents (Terms of Service,
Privacy Policy). All endpoints in this router are unauthenticated — they
are intended to be reachable by prospective users from marketing pages,
the login/register footer, and the in-app /legal/accept gate.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException

from app.legal import service as legal_service

router = APIRouter()


@router.get("/current")
async def get_current() -> dict:
    version = legal_service.get_current_version()
    return {"version": version, "effective_date": version}


@router.get("/versions/{version}/{doc}")
async def get_version(version: str, doc: Literal["terms", "privacy"]) -> dict:
    try:
        return legal_service.get_document(version, doc)
    except (KeyError, ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Document not found")
```

(The `Literal["terms", "privacy"]` type hint causes FastAPI to return 422 for any other value; the spec wants 404, so keep the broader path param and let `get_document` raise. Adjust:)

```python
@router.get("/versions/{version}/{doc}")
async def get_version(version: str, doc: str) -> dict:
    try:
        return legal_service.get_document(version, doc)
    except (KeyError, ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Document not found")
```

Register the router in `backend/app/main.py` (around line 391, alongside the other `include_router` calls):

```python
from app.api.endpoints import (
    # ... existing imports including auth, projects, etc ...
    legal,
)

# ... down where other routers are registered ...
app.include_router(legal.router, prefix="/legal", tags=["legal"])
```

Add `/legal` to the public-paths list discovered in Step 1. The exact code change depends on what you found; common patterns:

```python
# If a list:
PUBLIC_PATHS = [
    "/auth/login",
    "/auth/register",
    # ...
    "/legal/",
]

# If a startswith check:
if path.startswith("/legal/"):
    return await call_next(request)
```

Match whatever style is already in the codebase.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_legal_endpoints.py -v`
Expected: PASS — all 7 tests green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/legal.py \
        backend/app/main.py \
        backend/app/middleware/  # or wherever public paths live \
        backend/tests/integration/test_legal_endpoints.py
git commit -m "feat(legal): public GET /legal/current and /legal/versions/{v}/{doc}

Serves versioned ToS and Privacy markdown to the frontend
without requiring auth, so login-footer links and the
/legal/accept gate can fetch content."
```

---

## Task 8: `POST /auth/accept-tos` endpoint

**Files:**
- Modify: `backend/app/api/endpoints/auth.py`
- Test: `backend/tests/integration/test_auth_tos.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_auth_tos.py
"""Integration tests for POST /auth/accept-tos."""

import pytest
from sqlalchemy import select

from app.legal.service import get_current_version
from app.models.execution import AuditLog


@pytest.mark.asyncio
async def test_accept_tos_requires_auth(unauthenticated_client):
    resp = await unauthenticated_client.post("/auth/accept-tos")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_accept_tos_sets_user_fields(client, current_user, db):
    resp = await client.post("/auth/accept-tos")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tos_version"] == get_current_version()
    assert body["tos_accepted_at"] is not None
    assert body["tos_current"] is True

    # Verify in DB
    await db.refresh(current_user)
    assert current_user.tos_version == get_current_version()
    assert current_user.tos_accepted_at is not None


@pytest.mark.asyncio
async def test_accept_tos_writes_audit_log(client, current_user, db):
    resp = await client.post(
        "/auth/accept-tos",
        headers={"User-Agent": "test-suite/1.0"},
    )
    assert resp.status_code == 200

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.entity_type == "user")
        .where(AuditLog.entity_id == current_user.id)
        .where(AuditLog.action == "ACCEPT_TOS")
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_id == current_user.id
    assert row.changes["version"] == get_current_version()
    assert row.changes["user_agent"] == "test-suite/1.0"
    assert "ip_address" in row.changes


@pytest.mark.asyncio
async def test_accept_tos_idempotent_writes_two_audit_rows(client, current_user, db):
    await client.post("/auth/accept-tos")
    await client.post("/auth/accept-tos")

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.entity_type == "user")
        .where(AuditLog.entity_id == current_user.id)
        .where(AuditLog.action == "ACCEPT_TOS")
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    # User row still has only the latest acceptance
    await db.refresh(current_user)
    assert current_user.tos_version == get_current_version()


@pytest.mark.asyncio
async def test_auth_me_reports_tos_current_after_acceptance(client, current_user, db):
    me_before = (await client.get("/auth/me")).json()
    assert me_before["tos_current"] is False

    await client.post("/auth/accept-tos")

    me_after = (await client.get("/auth/me")).json()
    assert me_after["tos_current"] is True
    assert me_after["tos_version"] == get_current_version()
```

(Adapt fixture names — `current_user`, `client`, `db` — to whatever conventions the existing conftest uses. If `current_user` doesn't exist, search for the equivalent and adjust.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_auth_tos.py -v`
Expected: FAIL — endpoint doesn't exist (404 or 405).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/endpoints/auth.py`, add at the appropriate location (alongside other authenticated endpoints, e.g. near `/auth/me`):

```python
from datetime import datetime, timezone

from app.legal.service import get_current_version
from app.services.core.audit import log_audit


@router.post("/accept-tos", response_model=UserResponse)
async def accept_tos(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record the calling user's acceptance of the current Terms of
    Service and Privacy Policy version. Idempotent — repeated calls
    rewrite the User row's timestamp and write additional AuditLog rows.
    """
    version = get_current_version()
    user.tos_accepted_at = datetime.now(timezone.utc)
    user.tos_version = version

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    await log_audit(
        db,
        actor_id=user.id,
        action="ACCEPT_TOS",
        entity_type="user",
        entity_id=user.id,
        changes={
            "version": version,
            "ip_address": ip_address,
            "user_agent": user_agent,
        },
    )

    await db.commit()
    await db.refresh(user)
    return _user_response(user)
```

Imports at the top of `auth.py` may need additions — verify each is already present and add only the missing ones:
- `from datetime import datetime, timezone`
- `from app.legal.service import get_current_version`
- `from app.services.core.audit import log_audit`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_auth_tos.py -v`
Expected: PASS — all 5 tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/auth.py backend/tests/integration/test_auth_tos.py
git commit -m "feat(auth): POST /auth/accept-tos endpoint

Records the calling user's acceptance of the current ToS version.
Sets users.tos_accepted_at and users.tos_version, writes an
AuditLog row with version, ip_address, user_agent. Idempotent."
```

---

## Task 9: Gate-bypass tests (covering env flag and org override)

**Files:**
- Test: `backend/tests/integration/test_auth_tos_bypass.py`

This task adds explicit integration tests for the two bypass paths. The logic was already implemented in Task 6 (`compute_tos_current`); these tests pin the behavior end-to-end via `/auth/me`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_auth_tos_bypass.py
"""End-to-end tests for the two ToS gate bypass mechanisms:
    1. Settings.legal_gate_enabled = False  (deployment-level)
    2. Organization.legal_terms_overridden = True  (per-org)
"""

import pytest

from app.core.config import settings


@pytest.mark.asyncio
async def test_gate_disabled_makes_tos_current_true(client, current_user, monkeypatch):
    monkeypatch.setattr(settings, "legal_gate_enabled", False)
    me = (await client.get("/auth/me")).json()
    assert me["tos_current"] is True


@pytest.mark.asyncio
async def test_org_override_makes_tos_current_true(
    client, current_user, current_org, db
):
    current_org.legal_terms_overridden = True
    await db.commit()
    me = (await client.get("/auth/me")).json()
    assert me["tos_current"] is True


@pytest.mark.asyncio
async def test_org_override_false_and_stale_version_means_not_current(
    client, current_user, current_org, db
):
    current_org.legal_terms_overridden = False
    current_user.tos_version = None
    await db.commit()
    me = (await client.get("/auth/me")).json()
    assert me["tos_current"] is False


@pytest.mark.asyncio
async def test_no_selected_org_falls_back_to_version_check(
    client, current_user, db
):
    current_user.selected_org_id = None
    current_user.tos_version = None
    await db.commit()
    me = (await client.get("/auth/me")).json()
    assert me["tos_current"] is False
```

(Adapt `current_org` fixture name as needed. If the test conftest doesn't expose the user's selected org, query for it inside the test.)

- [ ] **Step 2: Run test to verify it fails (or sanity-check it passes)**

Run: `cd backend && pytest tests/integration/test_auth_tos_bypass.py -v`
Expected: PASS or FAIL — if PASS, this just locks in already-correct behavior. If FAIL, fix the related code (most likely the helper or schema).

- [ ] **Step 3: If any test fails, revisit `compute_tos_current` and `_user_response`**

Most likely fix: ensure `_user_response` passes `selected_organization` through to `compute_tos_current`. The User SQLAlchemy relationship `selected_organization` is defined in `iam.py` — verify it's eagerly loaded for `/auth/me`. If not, add a `selectinload(User.selected_organization)` to the `/auth/me` query.

- [ ] **Step 4: Re-run tests**

Run: `cd backend && pytest tests/integration/test_auth_tos_bypass.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/integration/test_auth_tos_bypass.py
git commit -m "test(auth): pin ToS gate-bypass behavior

Verifies that legal_gate_enabled=false and
Organization.legal_terms_overridden=true both surface
tos_current=true on /auth/me, while a missing org falls back
to the version check."
```

---

## Task 10: Frontend API helpers for legal content and acceptance

**Files:**
- Create: `frontend/src/lib/legal-api.ts`
- Test: `frontend/src/lib/legal-api.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/legal-api.test.ts
import { describe, expect, it, vi } from 'vitest';

// Mock the api client used elsewhere
vi.mock('./api', () => ({
    api: {
        get: vi.fn(),
        post: vi.fn(),
    },
}));

import { api } from './api';
import {
    fetchCurrentLegalVersion,
    fetchLegalDocument,
    acceptTos,
} from './legal-api';

describe('fetchCurrentLegalVersion', () => {
    it('calls GET /legal/current', async () => {
        vi.mocked(api.get).mockResolvedValueOnce({
            version: '2026-04-27',
            effective_date: '2026-04-27',
        });
        const result = await fetchCurrentLegalVersion();
        expect(api.get).toHaveBeenCalledWith('/legal/current');
        expect(result).toEqual({
            version: '2026-04-27',
            effective_date: '2026-04-27',
        });
    });
});

describe('fetchLegalDocument', () => {
    it('calls GET /legal/versions/{version}/terms', async () => {
        vi.mocked(api.get).mockResolvedValueOnce({
            version: '2026-04-27',
            effective_date: '2026-04-27',
            markdown: '# Terms',
        });
        const result = await fetchLegalDocument('2026-04-27', 'terms');
        expect(api.get).toHaveBeenCalledWith('/legal/versions/2026-04-27/terms');
        expect(result.markdown).toBe('# Terms');
    });

    it('calls GET /legal/versions/{version}/privacy', async () => {
        vi.mocked(api.get).mockResolvedValueOnce({
            version: '2026-04-27',
            effective_date: '2026-04-27',
            markdown: '# Privacy',
        });
        await fetchLegalDocument('2026-04-27', 'privacy');
        expect(api.get).toHaveBeenCalledWith('/legal/versions/2026-04-27/privacy');
    });
});

describe('acceptTos', () => {
    it('calls POST /auth/accept-tos', async () => {
        vi.mocked(api.post).mockResolvedValueOnce({ tos_current: true });
        const result = await acceptTos();
        expect(api.post).toHaveBeenCalledWith('/auth/accept-tos', {});
        expect(result.tos_current).toBe(true);
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- legal-api`
Expected: FAIL — `legal-api.ts` doesn't exist.

- [ ] **Step 3: Create the API helpers**

Check first what shape `api.get` / `api.post` use in this codebase:
```bash
cd frontend && grep -n "export.*api\b\|api.get\|api.post" src/lib/api.ts | head -20
```

Adjust the implementation if the API client takes a schema object — the pattern in `frontend-components.md` is `api.get('/items', { schema: ItemListSchema })`. If schemas are required, define them with Zod inline.

`frontend/src/lib/legal-api.ts`:
```typescript
import { z } from 'zod';

import { api } from './api';

export const CurrentLegalVersionSchema = z.object({
    version: z.string(),
    effective_date: z.string(),
});

export type CurrentLegalVersion = z.infer<typeof CurrentLegalVersionSchema>;

export const LegalDocumentSchema = z.object({
    version: z.string(),
    effective_date: z.string(),
    markdown: z.string(),
});

export type LegalDocument = z.infer<typeof LegalDocumentSchema>;

export type LegalDocType = 'terms' | 'privacy';

export async function fetchCurrentLegalVersion(): Promise<CurrentLegalVersion> {
    return await api.get('/legal/current', { schema: CurrentLegalVersionSchema });
}

export async function fetchLegalDocument(
    version: string,
    doc: LegalDocType,
): Promise<LegalDocument> {
    return await api.get(`/legal/versions/${version}/${doc}`, {
        schema: LegalDocumentSchema,
    });
}

export async function acceptTos(): Promise<unknown> {
    return await api.post('/auth/accept-tos', {});
}
```

(If `api.get`/`api.post` have a different signature in this repo, adjust accordingly. The vitest mock above uses positional args, so the test may also need a tweak — keep them in sync.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- legal-api`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/legal-api.ts frontend/src/lib/legal-api.test.ts
git commit -m "feat(legal): frontend API helpers for legal endpoints

Adds fetchCurrentLegalVersion, fetchLegalDocument, and acceptTos
backed by Zod schemas, ready for use by the layout gate and the
/legal/* routes."
```

---

## Task 11: Auth state additions (`isTosCurrent`, `acceptTos`)

**Files:**
- Modify: `frontend/src/lib/auth.svelte.ts`
- Test: `frontend/src/lib/auth.svelte.test.ts` (create or extend)

- [ ] **Step 1: Inspect current auth state shape**

Run:
```bash
cd frontend && grep -n "interface User\|type User\|email_verified\|tos_" src/lib/auth.svelte.ts | head -20
```

Locate the User type/interface. You'll add three fields to it: `tos_accepted_at: string | null`, `tos_version: string | null`, `tos_current: boolean`. Locate the `isEmailVerified` getter as a template for `isTosCurrent`.

- [ ] **Step 2: Write the failing test**

```typescript
// frontend/src/lib/auth.svelte.test.ts (add to existing or create)
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('./legal-api', () => ({
    acceptTos: vi.fn(),
}));

vi.mock('./api', () => ({
    api: { get: vi.fn(), post: vi.fn() },
}));

import { acceptTos as apiAcceptTos } from './legal-api';
import {
    isTosCurrent,
    acceptTos,
    __setUserForTest,  // test-only export below
} from './auth.svelte';

describe('isTosCurrent', () => {
    it('returns true when user.tos_current is true', () => {
        __setUserForTest({ tos_current: true } as any);
        expect(isTosCurrent()).toBe(true);
    });

    it('returns false when user.tos_current is false', () => {
        __setUserForTest({ tos_current: false } as any);
        expect(isTosCurrent()).toBe(false);
    });

    it('returns false when no user is loaded', () => {
        __setUserForTest(null);
        expect(isTosCurrent()).toBe(false);
    });
});

describe('acceptTos', () => {
    beforeEach(() => vi.clearAllMocks());

    it('calls the API and updates user state', async () => {
        vi.mocked(apiAcceptTos).mockResolvedValueOnce({
            tos_current: true,
            tos_version: '2026-04-27',
            tos_accepted_at: '2026-04-27T00:00:00Z',
        });
        __setUserForTest({ tos_current: false } as any);
        await acceptTos();
        expect(apiAcceptTos).toHaveBeenCalled();
        expect(isTosCurrent()).toBe(true);
    });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm run test -- auth.svelte`
Expected: FAIL — `isTosCurrent`, `acceptTos`, `__setUserForTest` exports don't exist.

- [ ] **Step 4: Add the auth state**

In `frontend/src/lib/auth.svelte.ts`:

1. Extend the User type/interface to include `tos_accepted_at: string | null`, `tos_version: string | null`, `tos_current: boolean`.

2. Add the getter near `isEmailVerified`:

```typescript
export function isTosCurrent(): boolean {
    return user?.tos_current === true;
}
```

3. Add the action — its location depends on existing patterns; place it near other state-mutating exports:

```typescript
import { acceptTos as apiAcceptTos } from './legal-api';

export async function acceptTos(): Promise<void> {
    const response = await apiAcceptTos() as {
        tos_current: boolean;
        tos_version: string | null;
        tos_accepted_at: string | null;
    };
    if (user) {
        user = { ...user, ...response };
    }
}
```

(`user` is the module-level `$state` rune. Adapt if the codebase uses an object wrapper or a different setter convention.)

4. Add the test-only export at the bottom of the file:

```typescript
// Test-only: allow tests to inject a user state. Not exported in production
// usage; if you need this in real code, you almost certainly want a
// different abstraction.
export function __setUserForTest(value: any): void {
    user = value;
}
```

(If the file already has a more idiomatic test-injection pattern, use it instead.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm run test -- auth.svelte`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/auth.svelte.ts frontend/src/lib/auth.svelte.test.ts
git commit -m "feat(auth): add isTosCurrent and acceptTos to client state

User type gains tos_accepted_at, tos_version, tos_current fields
matching the backend UserResponse. acceptTos() posts to the
backend and merges the response into local user state."
```

---

## Task 12: `LegalDocument.svelte` and `AcceptForm.svelte` components

**Files:**
- Create: `frontend/src/lib/components/legal/LegalDocument.svelte`
- Create: `frontend/src/lib/components/legal/AcceptForm.svelte`
- Test: `frontend/src/lib/components/legal/LegalDocument.test.ts`
- Test: `frontend/src/lib/components/legal/AcceptForm.test.ts`

- [ ] **Step 1: Write failing tests for LegalDocument**

```typescript
// frontend/src/lib/components/legal/LegalDocument.test.ts
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import LegalDocument from './LegalDocument.svelte';

describe('LegalDocument', () => {
    it('renders the title', () => {
        render(LegalDocument, {
            props: {
                title: 'Terms of Service',
                markdown: '# Hello',
                version: '2026-04-27',
                effectiveDate: '2026-04-27',
            },
        });
        expect(screen.getByText('Terms of Service')).toBeInTheDocument();
    });

    it('renders the version and effective date', () => {
        render(LegalDocument, {
            props: {
                title: 'Privacy Policy',
                markdown: '# Hi',
                version: '2026-04-27',
                effectiveDate: '2026-04-27',
            },
        });
        expect(screen.getByText(/2026-04-27/)).toBeInTheDocument();
    });

    it('renders the markdown content (H1 from #)', () => {
        render(LegalDocument, {
            props: {
                title: 'Terms',
                markdown: '# Section',
                version: '2026-04-27',
                effectiveDate: '2026-04-27',
            },
        });
        // Use a substring match because MarkdownRenderer may wrap output
        expect(screen.getByText(/Section/)).toBeInTheDocument();
    });
});
```

- [ ] **Step 2: Write failing tests for AcceptForm**

```typescript
// frontend/src/lib/components/legal/AcceptForm.test.ts
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import AcceptForm from './AcceptForm.svelte';

describe('AcceptForm', () => {
    it('disables the Accept button until both checkboxes are checked', async () => {
        render(AcceptForm, { props: { onAccept: vi.fn() } });
        const button = screen.getByRole('button', { name: /accept/i });
        expect(button).toBeDisabled();

        await fireEvent.click(screen.getByLabelText(/Terms of Service/i));
        expect(button).toBeDisabled();

        await fireEvent.click(screen.getByLabelText(/Privacy Policy/i));
        expect(button).toBeEnabled();
    });

    it('calls onAccept when both boxes are checked and button is clicked', async () => {
        const onAccept = vi.fn().mockResolvedValueOnce(undefined);
        render(AcceptForm, { props: { onAccept } });

        await fireEvent.click(screen.getByLabelText(/Terms of Service/i));
        await fireEvent.click(screen.getByLabelText(/Privacy Policy/i));
        await fireEvent.click(screen.getByRole('button', { name: /accept/i }));

        expect(onAccept).toHaveBeenCalledOnce();
    });

    it('shows an error message when onAccept rejects', async () => {
        const onAccept = vi.fn().mockRejectedValueOnce(new Error('boom'));
        render(AcceptForm, { props: { onAccept } });

        await fireEvent.click(screen.getByLabelText(/Terms of Service/i));
        await fireEvent.click(screen.getByLabelText(/Privacy Policy/i));
        await fireEvent.click(screen.getByRole('button', { name: /accept/i }));

        await screen.findByText(/boom/);
    });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm run test -- legal/`
Expected: FAIL — components don't exist.

- [ ] **Step 4: Implement LegalDocument**

`frontend/src/lib/components/legal/LegalDocument.svelte`:
```svelte
<script lang="ts">
    import MarkdownRenderer from '$lib/components/shared/MarkdownRenderer.svelte';

    interface Props {
        title: string;
        markdown: string;
        version: string;
        effectiveDate: string;
    }

    let { title, markdown, version, effectiveDate }: Props = $props();
</script>

<article class="legal-document">
    <header class="mb-6">
        <h1 class="text-2xl font-semibold text-foreground">{title}</h1>
        <p class="text-sm text-muted-foreground mt-1">
            Version {version} · Effective {effectiveDate}
        </p>
    </header>
    <div class="prose prose-sm max-w-none dark:prose-invert">
        <MarkdownRenderer content={markdown} format="markdown" />
    </div>
</article>

<style>
    .legal-document :global(h1) {
        @apply text-xl font-semibold mt-6 mb-3;
    }
    .legal-document :global(h2) {
        @apply text-lg font-semibold mt-5 mb-2;
    }
    .legal-document :global(p) {
        @apply mb-3 leading-relaxed;
    }
    .legal-document :global(ul),
    .legal-document :global(ol) {
        @apply mb-3 pl-6 list-disc;
    }
</style>
```

(`MarkdownRenderer` exists at `frontend/src/lib/components/shared/MarkdownRenderer.svelte` — it accepts `content` and a `format` prop. Verify the prop names match by reading the file before saving this.)

- [ ] **Step 5: Implement AcceptForm**

`frontend/src/lib/components/legal/AcceptForm.svelte`:
```svelte
<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import { Checkbox } from '$lib/components/ui/checkbox';

    interface Props {
        onAccept: () => Promise<void>;
    }

    let { onAccept }: Props = $props();

    let agreedTerms = $state(false);
    let agreedPrivacy = $state(false);
    let submitting = $state(false);
    let error = $state<string | null>(null);

    const canAccept = $derived(agreedTerms && agreedPrivacy && !submitting);

    async function handleAccept() {
        if (!canAccept) return;
        error = null;
        submitting = true;
        try {
            await onAccept();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to record acceptance';
        } finally {
            submitting = false;
        }
    }
</script>

<form
    class="accept-form border-t pt-4 mt-6 space-y-3"
    onsubmit={(e) => {
        e.preventDefault();
        handleAccept();
    }}
>
    <label class="flex items-start gap-3 cursor-pointer">
        <Checkbox bind:checked={agreedTerms} aria-label="Terms of Service" />
        <span class="text-sm leading-relaxed">
            I have read and agree to the <strong>Terms of Service</strong>.
        </span>
    </label>
    <label class="flex items-start gap-3 cursor-pointer">
        <Checkbox bind:checked={agreedPrivacy} aria-label="Privacy Policy" />
        <span class="text-sm leading-relaxed">
            I have read and agree to the <strong>Privacy Policy</strong>.
        </span>
    </label>
    {#if error}
        <p class="text-sm text-destructive">{error}</p>
    {/if}
    <Button type="submit" disabled={!canAccept} class="cursor-pointer">
        {submitting ? 'Recording…' : 'Accept and continue'}
    </Button>
</form>
```

(Verify the `Checkbox` component is available at `$lib/components/ui/checkbox`. If not, search for the actual export path — the codebase uses shadcn-svelte, so it should exist; if it doesn't, install/scaffold per existing pattern in `lib/components/ui/`.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm run test -- legal/`
Expected: PASS — all 6 tests green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/components/legal/
git commit -m "feat(legal): LegalDocument and AcceptForm components

LegalDocument renders title, version, effective date, and markdown
via the existing shared MarkdownRenderer. AcceptForm gates an
Accept button on two checkboxes and surfaces errors from the
caller-provided onAccept handler."
```

---

## Task 13: Public `/legal/terms` and `/legal/privacy` routes

**Files:**
- Create: `frontend/src/routes/legal/terms/+page.svelte`
- Create: `frontend/src/routes/legal/terms/+page.ts`
- Create: `frontend/src/routes/legal/privacy/+page.svelte`
- Create: `frontend/src/routes/legal/privacy/+page.ts`

(No dedicated unit tests for these page wrappers — they're thin, and the layout-gating test in Task 15 covers public-route accessibility.)

- [ ] **Step 1: Create the Terms page**

`frontend/src/routes/legal/terms/+page.ts`:
```typescript
import { fetchCurrentLegalVersion, fetchLegalDocument } from '$lib/legal-api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async () => {
    const { version } = await fetchCurrentLegalVersion();
    const doc = await fetchLegalDocument(version, 'terms');
    return { doc };
};
```

`frontend/src/routes/legal/terms/+page.svelte`:
```svelte
<script lang="ts">
    import LegalDocument from '$lib/components/legal/LegalDocument.svelte';
    import type { PageData } from './$types';

    let { data }: { data: PageData } = $props();
</script>

<svelte:head>
    <title>Terms of Service · Batchrite</title>
</svelte:head>

<main class="max-w-3xl mx-auto px-4 sm:px-6 py-8">
    <LegalDocument
        title="Terms of Service"
        markdown={data.doc.markdown}
        version={data.doc.version}
        effectiveDate={data.doc.effective_date}
    />
</main>
```

- [ ] **Step 2: Create the Privacy page**

`frontend/src/routes/legal/privacy/+page.ts`:
```typescript
import { fetchCurrentLegalVersion, fetchLegalDocument } from '$lib/legal-api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async () => {
    const { version } = await fetchCurrentLegalVersion();
    const doc = await fetchLegalDocument(version, 'privacy');
    return { doc };
};
```

`frontend/src/routes/legal/privacy/+page.svelte`:
```svelte
<script lang="ts">
    import LegalDocument from '$lib/components/legal/LegalDocument.svelte';
    import type { PageData } from './$types';

    let { data }: { data: PageData } = $props();
</script>

<svelte:head>
    <title>Privacy Policy · Batchrite</title>
</svelte:head>

<main class="max-w-3xl mx-auto px-4 sm:px-6 py-8">
    <LegalDocument
        title="Privacy Policy"
        markdown={data.doc.markdown}
        version={data.doc.version}
        effectiveDate={data.doc.effective_date}
    />
</main>
```

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run check`
Expected: PASS — no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/legal/terms/ frontend/src/routes/legal/privacy/
git commit -m "feat(legal): public /legal/terms and /legal/privacy routes

Both routes load the current version's markdown via the public
backend endpoints and render through LegalDocument. Accessible
without auth so prospective users and login-footer links work."
```

---

## Task 14: `/legal/accept` route (clickwrap form)

**Files:**
- Create: `frontend/src/routes/legal/accept/+page.svelte`
- Create: `frontend/src/routes/legal/accept/+page.ts`
- Test: `frontend/src/routes/legal/accept/+page.test.ts`

**Design intent:**

Restrained, deliberate, professional — this is the moment a user is signing a real legal document. Specific design decisions baked into the implementation below:

1. **Anchor logo at top** — nav is hidden on this route (Task 15), so a small centered Logo component anchors the user.
2. **"At a glance" callout** — three highlighted bullets surfacing the material terms (RUO, no-PHI, no-AI-training) above the full document. Both UX (smart, busy users want the gist first) and legal (conspicuous surfacing of unusual restrictions strengthens clickwrap defensibility).
3. **Subtle entrance animation** — a single 200ms fade on the page wrapper. No staggered choreography; tonal register is "law office", not "product launch."
4. **Sticky accept bar on `<md`** — the document panel can be tall on tablet/mobile. The accept form is wrapped in a sticky bottom bar below the `md` breakpoint so the action is always reachable.
5. **Hairline separator** between document and form — visual cue that reading is complete, action is next.
6. **Match existing app typography and tokens** — no custom fonts. `--foreground`, `--background`, `--card`, `--border`, `--primary`, `--muted` only. Matches Batchrite's clinical-but-warm aesthetic.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/routes/legal/accept/+page.test.ts
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/auth.svelte', () => ({
    isAuthenticated: () => true,
    isEmailVerified: () => true,
    isTosCurrent: () => false,
    acceptTos: vi.fn().mockResolvedValue(undefined),
}));

import AcceptPage from './+page.svelte';

describe('/legal/accept', () => {
    const data = {
        terms: { markdown: '# T', version: '2026-04-27', effective_date: '2026-04-27' },
        privacy: { markdown: '# P', version: '2026-04-27', effective_date: '2026-04-27' },
    };

    it('renders both documents and the accept form', () => {
        render(AcceptPage, { props: { data } });
        expect(screen.getByText('Terms of Service')).toBeInTheDocument();
        expect(screen.getByText('Privacy Policy')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
    });

    it('shows the at-a-glance callout with the three material terms', () => {
        render(AcceptPage, { props: { data } });
        // Must surface RUO, no-PHI, and no-AI-training above the document.
        expect(screen.getByText(/At a glance/i)).toBeInTheDocument();
        expect(screen.getByText(/research use only/i)).toBeInTheDocument();
        expect(screen.getByText(/Protected Health Information/i)).toBeInTheDocument();
        expect(screen.getByText(/train AI models/i)).toBeInTheDocument();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- legal/accept`
Expected: FAIL — page doesn't exist.

- [ ] **Step 3: Implement the route loader**

`frontend/src/routes/legal/accept/+page.ts`:
```typescript
import { fetchCurrentLegalVersion, fetchLegalDocument } from '$lib/legal-api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async () => {
    const { version } = await fetchCurrentLegalVersion();
    const [terms, privacy] = await Promise.all([
        fetchLegalDocument(version, 'terms'),
        fetchLegalDocument(version, 'privacy'),
    ]);
    return { terms, privacy };
};
```

- [ ] **Step 4: Implement the page**

`frontend/src/routes/legal/accept/+page.svelte`:
```svelte
<script lang="ts">
    import { onMount } from 'svelte';
    import { fade } from 'svelte/transition';
    import { goto } from '$app/navigation';
    import Logo from '$lib/components/layout/Logo.svelte';
    import LegalDocument from '$lib/components/legal/LegalDocument.svelte';
    import AcceptForm from '$lib/components/legal/AcceptForm.svelte';
    import { acceptTos, isTosCurrent } from '$lib/auth.svelte';
    import type { PageData } from './$types';

    let { data }: { data: PageData } = $props();

    let activeTab = $state<'terms' | 'privacy'>('terms');

    onMount(() => {
        if (isTosCurrent()) {
            goto('/');
        }
    });

    async function handleAccept() {
        await acceptTos();
        goto('/');
    }
</script>

<svelte:head>
    <title>Accept Terms · Batchrite</title>
</svelte:head>

<div class="min-h-screen bg-background pb-32 md:pb-12" in:fade={{ duration: 200 }}>
    <main class="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
        <!-- Anchor logo (nav is hidden on this route) -->
        <div class="flex justify-center mb-8">
            <Logo size="md" />
        </div>

        <!-- Hero copy -->
        <header class="mb-8">
            <h1 class="text-2xl sm:text-3xl font-semibold text-foreground tracking-tight">
                Please review and accept our terms
            </h1>
            <p class="text-sm sm:text-base text-muted-foreground mt-2 leading-relaxed">
                Before you can use Batchrite, take a moment to review the
                Terms of Service and Privacy Policy. Both apply to every
                user account.
            </p>
        </header>

        <!-- "At a glance" callout — surfaces material terms before the full document -->
        <aside
            class="mb-8 rounded-md border border-border/60 bg-muted/40 border-l-4 border-l-primary p-5"
            aria-label="Summary of material terms"
        >
            <h2 class="text-sm font-semibold text-foreground tracking-wide uppercase mb-3">
                At a glance
            </h2>
            <ul class="space-y-2 text-sm text-foreground leading-relaxed">
                <li class="flex gap-2">
                    <span class="text-primary mt-0.5" aria-hidden="true">•</span>
                    <span>
                        Batchrite is for <strong>research use only</strong> — not
                        validated for cGMP, GLP, or clinical use.
                    </span>
                </li>
                <li class="flex gap-2">
                    <span class="text-primary mt-0.5" aria-hidden="true">•</span>
                    <span>
                        You may not upload <strong>Protected Health Information</strong>
                        (HIPAA PHI).
                    </span>
                </li>
                <li class="flex gap-2">
                    <span class="text-primary mt-0.5" aria-hidden="true">•</span>
                    <span>
                        We don't sell your data and don't use it
                        to <strong>train AI models</strong>.
                    </span>
                </li>
            </ul>
        </aside>

        <!-- Tabs -->
        <div class="border-b border-border" role="tablist" aria-label="Legal documents">
            <button
                class="px-4 py-2 -mb-px cursor-pointer transition-all duration-150 {activeTab === 'terms' ? 'border-b-2 border-primary text-foreground font-medium' : 'text-muted-foreground hover:text-foreground'}"
                type="button"
                role="tab"
                aria-selected={activeTab === 'terms'}
                onclick={() => (activeTab = 'terms')}
            >Terms of Service</button>
            <button
                class="px-4 py-2 -mb-px cursor-pointer transition-all duration-150 {activeTab === 'privacy' ? 'border-b-2 border-primary text-foreground font-medium' : 'text-muted-foreground hover:text-foreground'}"
                type="button"
                role="tab"
                aria-selected={activeTab === 'privacy'}
                onclick={() => (activeTab = 'privacy')}
            >Privacy Policy</button>
        </div>

        <!-- Document panel -->
        <div class="max-h-[60vh] overflow-y-auto border border-border border-t-0 rounded-b-md p-6 sm:p-8 bg-card">
            {#if activeTab === 'terms'}
                <LegalDocument
                    title="Terms of Service"
                    markdown={data.terms.markdown}
                    version={data.terms.version}
                    effectiveDate={data.terms.effective_date}
                />
            {:else}
                <LegalDocument
                    title="Privacy Policy"
                    markdown={data.privacy.markdown}
                    version={data.privacy.version}
                    effectiveDate={data.privacy.effective_date}
                />
            {/if}
        </div>

        <!-- Hairline separator (desktop only — sticky bar replaces this on mobile) -->
        <hr class="hidden md:block border-border my-8" />

        <!-- Accept form: inline on desktop, sticky bottom bar on mobile/tablet -->
        <div
            class="md:static fixed bottom-0 left-0 right-0 md:bottom-auto md:left-auto md:right-auto bg-background/95 md:bg-transparent backdrop-blur md:backdrop-blur-none border-t md:border-t-0 border-border px-4 sm:px-6 md:px-0 py-4 md:py-0 z-10"
        >
            <div class="max-w-3xl mx-auto md:mx-0">
                <AcceptForm onAccept={handleAccept} />
            </div>
        </div>
    </main>
</div>
```

(Verify `Logo` is exported from `$lib/components/layout/Logo.svelte` — it's referenced in the existing `+layout.svelte`. If the size prop name differs, adjust.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm run test -- legal/accept`
Expected: PASS — both tests green (renders document/form, and shows the three at-a-glance bullets).

- [ ] **Step 6: Run check**

Run: `cd frontend && npm run check`
Expected: PASS — no Svelte/TS type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/legal/accept/
git commit -m "feat(legal): /legal/accept clickwrap route with at-a-glance callout

Loads both ToS and Privacy markdown for the current version,
renders them in tabbed scrollable panels with an at-a-glance
callout above (RUO, no-PHI, no-AI-training) and the AcceptForm
underneath. Sticky accept bar on mobile/tablet keeps the action
reachable when the document panel is tall. Anchors with a small
logo since nav is hidden. Subtle 200ms fade on entry.
Redirects already-accepted users to /."
```

---

## Task 15: Layout gating and `publicRoutes`

**Files:**
- Modify: `frontend/src/routes/+layout.svelte` (publicRoutes, onMount, beforeNavigate, showNav)
- Test: `frontend/src/routes/layout-gate.test.ts` (or whatever convention exists for layout tests)

- [ ] **Step 1: Identify existing layout test pattern**

Run:
```bash
cd frontend && find src -name "*layout*test*" -o -name "*+layout*test*" | head
```

If layout-gating tests don't exist yet, create a fresh file for this. The layout has logic that's hard to test in isolation (uses `$page` store, `goto`, `onMount`); for this task we'll write a focused test that mocks the relevant deps and asserts the redirect behavior of a small extracted helper.

- [ ] **Step 2: Extract gate-logic helper for testability**

Create `frontend/src/lib/auth-gate.ts`:
```typescript
export interface GateState {
    initialized: boolean;
    authenticated: boolean;
    emailVerified: boolean;
    tosCurrent: boolean;
    pathname: string;
}

export type GateRedirect =
    | { kind: 'login' }
    | { kind: 'check-email' }
    | { kind: 'accept-tos' }
    | { kind: 'home' }
    | { kind: 'none' };

const PUBLIC_ROUTES = ['/login', '/register', '/check-email', '/legal/terms', '/legal/privacy'];

export function decideRedirect(state: GateState): GateRedirect {
    if (!state.initialized) return { kind: 'none' };
    const isPublic = PUBLIC_ROUTES.includes(state.pathname);

    if (!state.authenticated) {
        if (isPublic) return { kind: 'none' };
        return { kind: 'login' };
    }
    if (!state.emailVerified) {
        if (state.pathname === '/check-email') return { kind: 'none' };
        return { kind: 'check-email' };
    }
    if (!state.tosCurrent) {
        if (state.pathname === '/legal/accept') return { kind: 'none' };
        if (isPublic) return { kind: 'none' };
        return { kind: 'accept-tos' };
    }
    if (isPublic) return { kind: 'home' };
    return { kind: 'none' };
}

export { PUBLIC_ROUTES };
```

Create `frontend/src/lib/auth-gate.test.ts`:
```typescript
import { describe, expect, it } from 'vitest';

import { decideRedirect } from './auth-gate';

const base = {
    initialized: true,
    authenticated: true,
    emailVerified: true,
    tosCurrent: true,
    pathname: '/',
};

describe('decideRedirect', () => {
    it('returns none when uninitialized', () => {
        expect(decideRedirect({ ...base, initialized: false }).kind).toBe('none');
    });

    it('redirects unauthenticated users to login', () => {
        expect(decideRedirect({ ...base, authenticated: false, pathname: '/projects' }).kind).toBe('login');
    });

    it('lets unauthenticated users view public legal pages', () => {
        expect(decideRedirect({ ...base, authenticated: false, pathname: '/legal/terms' }).kind).toBe('none');
        expect(decideRedirect({ ...base, authenticated: false, pathname: '/legal/privacy' }).kind).toBe('none');
    });

    it('redirects unverified users to check-email', () => {
        expect(decideRedirect({ ...base, emailVerified: false, pathname: '/projects' }).kind).toBe('check-email');
    });

    it('redirects authenticated email-verified users with stale ToS to /legal/accept', () => {
        expect(decideRedirect({ ...base, tosCurrent: false, pathname: '/projects' }).kind).toBe('accept-tos');
    });

    it('does not redirect a stale-ToS user already on /legal/accept', () => {
        expect(decideRedirect({ ...base, tosCurrent: false, pathname: '/legal/accept' }).kind).toBe('none');
    });

    it('lets a stale-ToS user view /legal/terms and /legal/privacy', () => {
        expect(decideRedirect({ ...base, tosCurrent: false, pathname: '/legal/terms' }).kind).toBe('none');
        expect(decideRedirect({ ...base, tosCurrent: false, pathname: '/legal/privacy' }).kind).toBe('none');
    });

    it('redirects authenticated users from public auth pages to home', () => {
        expect(decideRedirect({ ...base, pathname: '/login' }).kind).toBe('home');
        expect(decideRedirect({ ...base, pathname: '/register' }).kind).toBe('home');
    });

    it('returns none for fully-authenticated user on a normal page', () => {
        expect(decideRedirect({ ...base, pathname: '/projects' }).kind).toBe('none');
    });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm run test -- auth-gate`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 4: Run again after creating files**

After saving both files in Step 2, run again:
Run: `cd frontend && npm run test -- auth-gate`
Expected: PASS — all 9 tests green.

- [ ] **Step 5: Refactor `+layout.svelte` to use the helper**

Open `frontend/src/routes/+layout.svelte`. The current logic in `onMount` and `beforeNavigate` does sequential `if/else` checks. Replace with calls to `decideRedirect`.

Replace the imports at the top (merge with existing):
```typescript
import { initialize, isAuthenticated, isEmailVerified, isInitialized, isTosCurrent, getCurrentOrg, getUserPreferences, handleVerificationCallback } from '$lib/auth.svelte';
import { decideRedirect, PUBLIC_ROUTES } from '$lib/auth-gate';
```

Remove the existing `publicRoutes` constant and replace usage with `PUBLIC_ROUTES`.

Update the `isPublicRoute` derivation:
```typescript
const isPublicRoute = $derived(PUBLIC_ROUTES.includes($page.url.pathname));
```

Replace the inline if/else chain in `onMount` (after `await initialize()` and `await initFieldMode()`):
```typescript
const decision = decideRedirect({
    initialized: isInitialized(),
    authenticated: isAuthenticated(),
    emailVerified: isEmailVerified(),
    tosCurrent: isTosCurrent(),
    pathname: $page.url.pathname,
});
switch (decision.kind) {
    case 'login': goto('/login'); break;
    case 'check-email': goto('/check-email'); break;
    case 'accept-tos': goto('/legal/accept'); break;
    case 'home': goto('/'); break;
    case 'none': break;
}
```

Replace `beforeNavigate`:
```typescript
beforeNavigate(({ to, cancel }) => {
    if (!isInitialized()) return;
    const path = to?.url.pathname ?? '/';
    const decision = decideRedirect({
        initialized: true,
        authenticated: isAuthenticated(),
        emailVerified: isEmailVerified(),
        tosCurrent: isTosCurrent(),
        pathname: path,
    });
    switch (decision.kind) {
        case 'login': cancel(); goto('/login'); break;
        case 'check-email': cancel(); goto('/check-email'); break;
        case 'accept-tos': cancel(); goto('/legal/accept'); break;
        // 'home' is for landing on auth pages while authenticated; let onMount handle it
        case 'home':
        case 'none': break;
    }
});
```

Update `showNav` to also hide on `/legal/accept`:
```typescript
const showNav = $derived(
    !isPublicRoute && !isFieldMode && isAuthenticated() && $page.url.pathname !== '/legal/accept'
);
```

Update `isFullBleed` to include `/legal/accept` and `/legal/terms` and `/legal/privacy` if you want them edge-to-edge — leave default if you want the existing bordered layout:
(Skip this — the legal routes use `<main class="max-w-3xl mx-auto ...">` already.)

- [ ] **Step 6: Run all frontend tests to confirm no regressions**

Run: `cd frontend && npm run test`
Expected: PASS.

Run: `cd frontend && npm run check`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/auth-gate.ts frontend/src/lib/auth-gate.test.ts \
        frontend/src/routes/+layout.svelte frontend/src/lib/auth.svelte.ts
git commit -m "feat(layout): gate authenticated users on /legal/accept

Extracts gate decision into a pure helper (auth-gate.ts) covering
auth, email verification, ToS, and public-route logic. Layout
calls the helper from onMount and beforeNavigate. Public legal
pages bypass auth and the gate; /legal/accept hides nav."
```

---

## Task 16: Login and register footer notice

**Files:**
- Modify: `frontend/src/routes/login/+page.svelte`
- Modify: `frontend/src/routes/register/+page.svelte`

- [ ] **Step 1: Identify the form footer area on each page**

Run:
```bash
cd frontend && grep -n "</form>\|Sign in\|Sign up\|Create account" src/routes/login/+page.svelte src/routes/register/+page.svelte | head
```

You'll add a single line of help text below each form (after the submit button, above any "already have an account?" link if present).

- [ ] **Step 2: Add the notice to the login page**

In `frontend/src/routes/login/+page.svelte`, find the form's closing area and add (or merge with the existing footer block):

```svelte
<p class="text-xs text-muted-foreground text-center mt-4">
    By continuing, you agree to our
    <a href="/legal/terms" class="underline hover:text-foreground transition-all duration-150">Terms of Service</a>
    and
    <a href="/legal/privacy" class="underline hover:text-foreground transition-all duration-150">Privacy Policy</a>.
</p>
```

- [ ] **Step 3: Add the notice to the register page**

Same change in `frontend/src/routes/register/+page.svelte`.

- [ ] **Step 4: Run frontend checks**

Run: `cd frontend && npm run check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/login/+page.svelte frontend/src/routes/register/+page.svelte
git commit -m "feat(auth): add ToS/Privacy notice to login and register footers

Provides notice before sign-up so users have meaningful consent
before their first authenticated load triggers the gate."
```

---

## Task 17: Settings page Legal section

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte` (or the appropriate settings route — search for it)

- [ ] **Step 1: Find the settings page entry**

Run:
```bash
cd frontend && find src/routes/settings -type f -name "*.svelte" | head
```

The exact structure depends on whether settings is a single page or tabbed sub-routes. Open the main settings page (or the "account" tab page if tabbed) and find a sensible spot for a new "Legal" section/card.

- [ ] **Step 2: Add the Legal section**

In the chosen settings page, add a card/section like:

```svelte
<script lang="ts">
    import { getUser } from '$lib/auth.svelte';
    // ... existing imports ...

    const user = $derived(getUser());

    function formatDate(iso: string | null): string {
        if (!iso) return '—';
        return new Date(iso).toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
        });
    }
</script>

<!-- ... existing settings sections ... -->

<section class="mt-6 rounded-lg border border-border bg-card p-6">
    <h2 class="text-lg font-semibold mb-3">Legal</h2>
    {#if user?.tos_accepted_at && user?.tos_version}
        <p class="text-sm text-muted-foreground mb-4">
            You accepted our Terms of Service version
            <strong class="text-foreground">{user.tos_version}</strong>
            on
            <strong class="text-foreground">{formatDate(user.tos_accepted_at)}</strong>.
        </p>
    {:else}
        <p class="text-sm text-muted-foreground mb-4">
            You have not yet accepted our Terms of Service.
        </p>
    {/if}
    <div class="flex gap-3">
        <a
            href="/legal/terms"
            class="text-sm underline hover:text-foreground transition-all duration-150 cursor-pointer"
        >View Terms of Service</a>
        <a
            href="/legal/privacy"
            class="text-sm underline hover:text-foreground transition-all duration-150 cursor-pointer"
        >View Privacy Policy</a>
    </div>
</section>
```

(`getUser()` may not exist by that exact name — search `auth.svelte.ts` for the user accessor and adapt. If the codebase uses `getCurrentOrg()` and similar, follow the same naming pattern.)

- [ ] **Step 3: Run checks**

Run: `cd frontend && npm run check`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/settings/
git commit -m "feat(settings): show ToS acceptance state and document links

Adds a Legal card showing the user's last-accepted version and
date plus links to the public ToS and Privacy pages. No re-accept
button — re-acceptance is triggered automatically by the gate
when a new version is activated."
```

---

## Task 18: Manual browser verification (qa-verify agent)

**Files:** none (verification only)

- [ ] **Step 1: Make sure backend and frontend dev servers are running**

Worktree convention (alternate ports — see `.claude/rules/conventions.md`):
- Backend: 8010
- Frontend: 5183

Start backend (from `backend/`):
```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8010
```

Start frontend (from `frontend/`, in another shell):
```bash
VITE_API_PORT=8010 npm run dev -- --port 5183
```

If `frontend/src/lib/config.ts` reads `VITE_API_PORT`, this will route the frontend to the right backend. If a different env var is in use, adjust per existing convention in the worktree.

- [ ] **Step 2: Reset and reseed the dev DB to confirm migration applies cleanly**

Run from the worktree root:
```bash
./scripts/reset.sh
cd backend && source .venv/bin/activate && alembic upgrade head
```

This wipes user data, reseeds, and confirms the migration applies. Optional but valuable.

- [ ] **Step 3: Launch the qa-verify agent**

Use the Agent tool with `subagent_type: "qa-verify"` and brief it with:

> Verify the new Terms of Service / Privacy Policy clickwrap flow.
>
> **How to login:** Register a fresh user at http://localhost:5183/register (any email format and password ≥ 8 chars works in dev). Email verification is automatic in dev — check the backend log for the verify URL and click it, or use the dev shortcut if there's one.
>
> **What was implemented:** A new clickwrap acceptance gate at `/legal/accept`, public legal pages at `/legal/terms` and `/legal/privacy`, a settings "Legal" section, and login/register footer notices. ToS and Privacy content lives in the backend at `app/legal/versions/2026-04-27/`.
>
> **Pages affected:** `/login`, `/register`, `/legal/terms`, `/legal/privacy`, `/legal/accept`, settings page, and the layout gate logic on every authenticated page.
>
> **Acceptance criteria:**
> 1. Logged-out user can visit `/legal/terms` and `/legal/privacy` directly — content renders, version + effective date are visible.
> 2. Login and register pages show "By continuing you agree to..." text linking to the legal pages.
> 3. New user, after email verification, lands on `/legal/accept` automatically — not on `/`.
> 4. The Accept button on `/legal/accept` is disabled until both checkboxes are checked.
> 5. After clicking Accept, user is sent to `/` and `/auth/me` returns `tos_current: true`.
> 6. Settings page shows "You accepted Terms of Service version 2026-04-27 on [date]" with links to view both documents.
> 7. Already-accepted user navigating directly to `/legal/accept` is redirected to `/`.
> 8. Manually setting `users.tos_version = NULL` for the user (via psql) and reloading any authenticated page redirects to `/legal/accept`.
> 9. Layout: nav is hidden on `/legal/accept`. The Logo is visible at the top of the page. Tabs work to switch between Terms and Privacy. Document panel is scrollable. Accept button is reachable on tablet-sized viewports.
> 10. The "At a glance" callout is visible above the document, with a left-border accent in the primary color, surfacing three bullets: research use only, no PHI, no AI training. The bullets are legible and visually distinct from regular body text.
> 11. On viewports below 768px (md breakpoint): the AcceptForm is rendered as a sticky bottom bar with a subtle backdrop blur and top border. It remains in view as the user scrolls the document. There is bottom padding on the page so content isn't trapped behind the sticky bar.
> 12. On viewports ≥768px: the AcceptForm appears inline below the document, separated by a hairline `<hr>`. No sticky bar.
> 13. Page-load fade-in animation is subtle (≤200ms), not theatrical. No staggered choreography.
>
> **Edge cases worth testing:**
> - 404 from `/legal/versions/bogus/terms` returns a clean error page (not a Svelte crash).
> - The "View Terms of Service" link in the settings page opens in the same tab and renders the public route.
> - Layout tweaks (header, spacing, font sizes) feel consistent with the rest of the app — flag any oversized buttons, misaligned checkboxes, or content that overflows on small screens.
>
> The agent must FIX any FAIL or POLISH issues it finds before returning.

- [ ] **Step 4: Address any issues the agent reports back**

Iterate until qa-verify returns clean.

- [ ] **Step 5: Commit any verification fixes**

```bash
git add -A
git commit -m "fix(legal): qa-verify follow-ups"
```

(Skip if the agent made no changes.)

---

## Task 19: Full test sweep

- [ ] **Step 1: Run the full backend test suite**

Run from `backend/`:
```bash
source .venv/bin/activate
pytest -v
```

Expected: PASS — all tests green, including pre-existing ones.

- [ ] **Step 2: Run the full frontend test suite**

Run from `frontend/`:
```bash
npm run test
npm run check
```

Expected: PASS for both.

- [ ] **Step 3: Run the linters**

```bash
cd backend && black app tests && isort app tests && mypy app
cd frontend && npm run check
```

Expected: PASS.

- [ ] **Step 4: Final commit if any formatter changes were made**

```bash
git add -A
git commit -m "chore(f-0020a): formatter pass"
```

(Skip if nothing changed.)

---

## Self-review checklist (run after completing all tasks)

- Spec coverage: every acceptance criterion in the spec maps to a task above.
- Public legal endpoints (`GET /legal/...`) work without auth — verified by tests in Task 7.
- ToS gate enforces three scenarios: never-accepted, stale-version, current — verified in Tasks 8 and 9.
- Bypasses for `legal_gate_enabled=false` and `Organization.legal_terms_overridden=true` work — verified in Task 9.
- Frontend gate redirects users to `/legal/accept` and lets them out once accepted — verified by `decideRedirect` tests in Task 15.
- Markdown content includes RUO, PHI prohibition, AI training commitments, California governing law — verified in Task 2.
- ToS version is bump-able via the `CURRENT_VERSION` constant; activation is grep-able in commit log via the convention `feat(legal): activate ToS/Privacy version <date>`.
- Manual browser verification covers the user-visible flows.
