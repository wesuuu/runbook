---
name: frontend_dev
description: Starts the Vite frontend development server on localhost and the Tailscale IP (100.120.2.59).
---

# Start Frontend Servers

Run two separate Vite dev server processes from the `frontend/` directory.

## Process 1 — Localhost

```bash
cd frontend && npm run dev:local
```

Serves on **http://localhost:5173**. API calls go to `http://localhost:8000`.

## Process 2 — Tailscale

```bash
cd frontend && npm run dev:tailscale
```

Serves on **http://100.120.2.59:5174**. API calls go to `http://100.120.2.59:8000`.

## Notes

- The API base URL is set via the `VITE_API_HOST` env var (statically replaced by Vite at build time). Each npm script sets it appropriately.
- Both processes must be running simultaneously (use separate terminals or background one).
- The backend must also be listening on the Tailscale IP for the second instance to work (use `--host 0.0.0.0` with uvicorn).
