---
paths:
  - "backend/app/api/**"
  - "backend/app/core/deps.py"
  - "backend/app/core/middleware.py"
---

# Backend API Endpoint Patterns

## Endpoint Structure

```python
@router.post("/resource", response_model=ResourceResponse)
async def create_resource(
    request: ResourceCreate,                           # Pydantic body
    user: User = Depends(get_current_user),            # Auth
    db: AsyncSession = Depends(get_db),                # DB session
    _: User = Depends(require_permission(...)),         # Permission gate (optional)
):
    org_id = user.selected_org_id                      # Org context from user
    resource = ResourceModel(org_id=org_id, **request.model_dump())
    db.add(resource)
    await db.commit()
    await db.refresh(resource)
    return ResourceResponse.model_validate(resource)
```

## Authentication Flow

1. `AuthMiddleware` decodes JWT from `Authorization: Bearer <token>` header
2. Stashes `TokenPayload` on `request.state.token_payload`
3. `get_current_user` dependency reads token payload, queries User from DB
4. Public paths bypass auth: `/auth/login`, `/auth/register`, `/auth/verify-email`, `/docs`, `/health`

Token also accepted via `?token=` query param (for iframes/img src).

## Dependency Injection Factories

```python
# Permission check -- factory returns a Depends-compatible function
require_permission(ObjectType.PROJECT, "project_id", PermissionLevel.EDIT)

# Tier gating -- checks subscription tier from token
require_tier(SubscriptionTier.PRO)

# Generic 404
await get_or_404(db, Project, project_id)  # returns instance or raises 404
```

## Service Usage in Endpoints

- **Module functions**: import and call directly
  ```python
  from app.services.audit import log_audit
  await log_audit(db, entity_type="run", entity_id=run.id, ...)
  ```
- **Class services**: instantiate inline
  ```python
  storage = FileStorageService()
  stored = await storage.store_file(content, filename, org_id)
  ```
- **Factory services**: call factory
  ```python
  provider = get_email_provider()
  await provider.send(to, subject, html, text)
  ```
- **Background tasks**: submit via task runner
  ```python
  runner = get_task_runner()
  await runner.submit(process_document(doc.id))
  ```

## Error Response Pattern

- Middleware: `return JSONResponse(status_code=401, content={"detail": "..."})`
- Dependencies: `raise HTTPException(status_code=403, detail="...")`
- Endpoints: `raise HTTPException(status_code=404, detail="...")`
- Pydantic validation: automatic 422 from FastAPI

## Router Organization

Routers in `api/endpoints/` are mounted in `api/router.py`:
- `science.py`: protocols, experiments, runs, unit ops
- `iam.py`: organizations, teams, memberships, permissions
- `projects.py`: project CRUD
- `chat.py`: chat sessions and messages
- `ai.py`: AI provider config, connection testing
- `auth.py`: login, register, verification, password reset
