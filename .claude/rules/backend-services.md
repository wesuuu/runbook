---
paths:
  - "backend/app/services/**"
---

# Backend Service Patterns

## Service Types in This Codebase

### Pattern A: Stateless Module Functions (most common)

Used when functions are independent and only need `db` + domain args. No class wrapper.

```python
# ai_config.py, permissions.py, audit.py, embedding.py
async def check_permission(db: AsyncSession, user_id: UUID, ...) -> bool: ...
async def log_audit(db: AsyncSession, ...) -> None: ...
async def embed_texts(texts: list[str], db: AsyncSession, org_id: UUID) -> list[list[float]]: ...
```

- Import and call directly: `from app.services.permissions import check_permission`
- Config accessed via `from app.core.config import settings` at call time
- Custom exception classes co-located in the module (e.g., `EmbeddingError`)

### Pattern B: Classes with State (when methods share config)

Used when multiple methods need shared initialization state.

```python
# file_storage.py
class FileStorageService:
    def __init__(self, storage_root: str = "./uploads"):
        self.storage_root = Path(storage_root)
    async def store_file(self, ...) -> StoredFile: ...
    def resolve_path(self, ...) -> Path: ...
```

- Instantiated inline in endpoints: `storage = FileStorageService()`
- Lightweight -- only immutable config as state

### Pattern C: Abstract Base + Factory (for swappable backends)

Used when the implementation may change (email provider, task runner).

```python
# email_service.py
class EmailProvider(ABC):
    async def send(self, to, subject, html, text) -> None: ...

class SMTPProvider(EmailProvider):
    def __init__(self, host, port, ...): ...

def get_email_provider() -> EmailProvider:
    return SMTPProvider(settings.smtp_host, ...)

# task_runner.py
class TaskRunner(ABC): ...
class ThreadTaskRunner(TaskRunner): ...
def get_task_runner() -> TaskRunner:  # singleton, cached
```

- Factory functions return configured instances
- `get_task_runner()` is a singleton; `get_email_provider()` creates per call
- `reset_task_runner()` exists for testing

## Background Task Pattern

Background tasks that outlive the request create their own DB session:

```python
# document_processor.py
async def process_document(document_id: UUID) -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(bind=engine, ...)
    async with session_factory() as session:
        # SELECT ... FOR UPDATE SKIP LOCKED for concurrency
        # Update BackgroundJob.heartbeat_at periodically
```

- Submitted via `get_task_runner().submit(coroutine)`
- Progress tracked in `BackgroundJob` table with heartbeat
- Recovery: stalled jobs (heartbeat > 60s old) recovered on startup

## Chat Service Dependencies

The chat service uses pydantic-ai's `RunContext` for dependency injection into tools and subagents:

```python
@dataclass
class ChatDeps:
    db: AsyncSession
    org_id: UUID
    user_id: UUID
    is_org_admin: bool
    sources: list[RetrievedChunk] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    subagents: dict[str, Any] = field(default_factory=dict)

    def clone_for_subagent(self, max_depth: int = 0) -> "ChatDeps": ...

# Tools receive context automatically
async def search_documents_tool(ctx: RunContext[ChatDeps], query: str) -> SearchResult: ...
```

For the broader chat-agent architecture (harness, capabilities, subagents, workflows), see `.claude/rules/backend-ai.md`.

## AI Tools vs Domain Services

Tools called by chat subagents (under `services/ai/subagents/<name>/tools.py`) must stay thin: argument mapping, domain-service delegation, and `tool_calls` audit logging. Pure business logic — graph validation, parameter checks, structural transforms — belongs in `services/<domain>/`, not in the AI package.

Example: `services/protocols/validation.py` exposes `validate_protocol_graph(graph, unit_ops) -> ValidationResult` with no DB or LLM dependency. The chat tool `validate_protocol(ctx, protocol_id)` loads the row, calls the validator, returns the dataclass. This keeps the validator unit-testable without pydantic-ai and reusable from non-chat code paths.
