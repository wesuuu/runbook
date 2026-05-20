---
paths:
  - "backend/app/models/**"
  - "backend/app/schemas/**"
  - "backend/alembic/**"
---

# Backend Models, Schemas & Migrations

## Model Structure

All models inherit from `Base` (DeclarativeBase) plus mixins:

```python
class MyModel(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "my_models"  # plural snake_case
```

- **UUIDMixin**: `id` column as `UUID(as_uuid=True)` primary key with `uuid.uuid4` default
- **TimestampMixin**: `created_at` and `updated_at` with `server_default=func.now()`

## Relationship Patterns

**One-to-Many with cascade:**
```python
runs: Mapped[List["Run"]] = relationship(back_populates="project", cascade="all, delete-orphan")
```

**Many-to-One FK:**
```python
project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
project: Mapped["Project"] = relationship(back_populates="runs")
```

**Multiple FKs to same table** -- use `foreign_keys=`:
```python
user = relationship("User", foreign_keys=[user_id])
revoker = relationship("User", foreign_keys=[revoked_by])
```

**Circular/self-references** -- use `use_alter=True`:
```python
ForeignKey("document_templates.id", use_alter=True, name="fk_org_sop_tpl")
```

## Constraints

**Scoping constraints** (entity belongs to exactly one parent):
```python
__table_args__ = (
    CheckConstraint(
        "(project_id IS NOT NULL AND organization_id IS NULL) OR "
        "(project_id IS NULL AND organization_id IS NOT NULL)",
        name="ck_protocol_scope",
    ),
)
```

**Unique constraints** -- table-level in `__table_args__`:
```python
UniqueConstraint("user_id", "organization_id", name="uq_org_member")
```

**Partial unique indexes** (PostgreSQL):
```python
Index("ix_pending_invitation", "organization_id", "invited_email",
      unique=True, postgresql_where="status = 'PENDING'")
```

**Polymorphic FK** -- one row references one of N parents via mutually-exclusive nullable FK columns + CHECK enforcing "exactly one non-null". Pair with a partial unique index using `postgresql_where=text(...)` to enforce uniqueness conditional on which FK is populated. Example: `glp_signoffs.protocol_id` / `run_id` (see `backend/app/models/signoffs.py`).

**Composite indexes** for common query patterns:
```python
Index("ix_audit_logs_entity", "entity_type", "entity_id", "created_at")
```

## JSONB Column Patterns

JSONB is used for flexible/nested data. Always provide `default` and `server_default`:

```python
graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
tags: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
credentials: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
```

Common JSONB uses: graph data (Protocol/Run), param schemas, document metadata, AI credentials, chat message history.

## Postgres ARRAY columns (multi-valued enums)

For a column holding multiple enum values (e.g. additive roles), use
`ARRAY(String)` plus a CHECK that the array is contained by the allowed set:

```python
roles: Mapped[List[str]] = mapped_column(
    ARRAY(String), nullable=False,
    server_default=text("ARRAY['MEMBER']::varchar[]"),
)
__table_args__ = (
    CheckConstraint(
        "roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER','SITE_MANAGER']::varchar[]",
        name="ck_roles_allowed",
    ),
)
```

Query containment with `Column.contains([value])` (Postgres `@>`).
Treat one element as canonical/implicit (e.g. MEMBER) and enforce it
server-side on every write — don't rely on the DB default for updates.

## Enum Pattern

Define as `str` + `Enum`, store as `String` column:

```python
class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"

# In model:
status: Mapped[str] = mapped_column(String, default=RunStatus.PLANNED, nullable=False)
```

Ranking dicts for ordered enums: `TIER_RANK = {SubscriptionTier.ESSENTIALS: 0, ...}`

## Soft Delete / Archival

No global mixin. Use status + archive fields when needed:

```python
status: Mapped[str] = mapped_column(String, default="ACTIVE", server_default="ACTIVE")
archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
archived_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ...), nullable=True)
```

## Pydantic Schema Conventions

Three schema types per entity: `Create`, `Update` (optional), `Response`.

```python
class OrganizationCreate(BaseModel):
    name: str

class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)  # ORM mode
```

- `from_attributes=True` enables `Model.model_validate(orm_instance)`
- Use `@computed_field` for derived properties (e.g., `scope` from nullable FKs)
- Use `@field_validator` for domain validation (e.g., allowed flags)
- Nested schemas compose via inheritance: `class DetailResponse(BaseResponse): ...`

## Migration Workflow

1. Modify model in `backend/app/models/`
2. `alembic revision --autogenerate -m "description"`
3. Review generated migration -- Alembic doesn't catch everything (JSONB defaults, partial indexes)
4. `alembic upgrade head`

Data migrations use raw SQL: `op.execute("UPDATE ... SET ...")`
