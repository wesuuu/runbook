---
name: frontend_dev
description: Starts the Vite frontend development server on localhost and the Tailscale IP (100.120.2.59).
---

# Start Frontend Servers

Run two separate Vite dev server processes from the `frontend/` directory.

## Steps

1. **Register tasks**: Use `TaskCreate` to create two tasks:

   **Task 1 — Localhost**:
   - **subject**: "Frontend dev server — localhost (port 5173)"
   - **description**: "Vite dev server on http://localhost:5173. API calls go to http://localhost:8000. Kill the background process to stop."
   - **activeForm**: "Running frontend server on :5173"

   **Task 2 — Tailscale**:
   - **subject**: "Frontend dev server — Tailscale (port 5174)"
   - **description**: "Vite dev server on http://100.120.2.59:5174. API calls go to http://100.120.2.59:8000. Kill the background process to stop."
   - **activeForm**: "Running frontend server on :5174"

2. **Start both servers** (run each in background):

   ```bash
   cd frontend && npm run dev:local
   ```

   ```bash
   cd frontend && npm run dev:tailscale
   ```

   Use `run_in_background: true` for both so the processes run in the background.

3. **Update both tasks to in_progress** after the servers start successfully.

## Notes

- The API base URL is set via the `VITE_API_HOST` env var (statically replaced by Vite at build time). Each npm script sets it appropriately.
- Both processes must be running simultaneously.
- The backend must also be listening on the Tailscale IP for the second instance to work (use `--host 0.0.0.0` with uvicorn).
