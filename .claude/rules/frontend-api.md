---
paths:
  - "frontend/src/lib/api.ts"
  - "frontend/src/lib/schemas/**"
  - "frontend/src/lib/validation.ts"
  - "frontend/src/lib/config.ts"
---

# Frontend API Client, Schemas & Validation

## API Client (`api.ts`)

Single `api` object with typed HTTP methods:

```typescript
const res = await api.get('/protocols', { schema: ProtocolListSchema });
const created = await api.post('/protocols', body, { schema: ProtocolResponseSchema });
await api.put(`/protocols/${id}`, body, { schema: ProtocolResponseSchema });
await api.delete(`/protocols/${id}`);
```

- All methods accept optional `{ schema: ZodSchema }` for response validation
- Validation throws in dev mode, warns in prod
- 401 responses auto-trigger `logout()` + redirect to `/login`
- Custom `ApiError` class: `new ApiError(status, message, data)`
- File uploads: `api.uploadFile(endpoint, file)`, `api.uploadWithFields(endpoint, formData)`
- Blob downloads: `api.downloadBlob(endpoint)`, `api.fetchBlobUrl(endpoint)`

## Configuration (`config.ts`)

```typescript
const host = import.meta.env.VITE_API_HOST || 'localhost';
const port = import.meta.env.VITE_API_PORT || '8000';
export const API_BASE = `http://${host}:${port}`;
```

Named exports only, no defaults.

## Zod Schema Organization (`schemas/`)

One file per domain, barrel re-exported from `schemas/index.ts`:

```
schemas/
  chat.ts        # ChatSession, ChatMessage, ChatCompletionResponse
  protocols.ts   # Protocol, ProtocolList
  runs.ts        # Run, RunNote, RunStatus
  projects.ts    # Project, ProjectList
  index.ts       # export * from './chat'; export * from './protocols'; ...
```

### Schema Rules

- **Every API call must have a Zod schema** validating the response
- All schemas use `.passthrough()` to allow unknown fields (forward compat)
- Derive TypeScript types via `z.infer<typeof Schema>` -- never maintain separate interfaces
- List responses: `z.object({ items: z.array(EntitySchema), total: z.number() }).passthrough()`
- Import from `$lib/schemas` (barrel) for shared types, or define inline for page-local types

### Example

```typescript
export const ProtocolSchema = z.object({
    id: z.string(),
    name: z.string(),
    graph: z.record(z.string(), z.unknown()),
    created_at: z.string(),
}).passthrough();

export type Protocol = z.infer<typeof ProtocolSchema>;
```

## Form Validation (`validation.ts`)

```typescript
import { validate, firstError } from '$lib/validation';

const result = validate(MyFormSchema, formData);
if (!result.success) {
    const nameErr = firstError(result.errors, 'name');
}
```

- `validate(schema, data)` returns `{ success, data?, errors }` -- no form framework
- `flattenErrors(zodError)` converts to `Record<string, string[]>`
- `firstError(errors, field)` gets first error for a field
- `buildResultValidator(jsonSchema)` dynamically converts backend JSON Schema to Zod (for run results)
