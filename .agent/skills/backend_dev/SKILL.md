---
name: backend_dev
description: Starts the FastAPI backend server in development mode using Uvicorn.
---

# Start Backend Server

## Steps

1. **Register task**: Use `TaskCreate` to create a task:
   - **subject**: "Backend dev server (port 8000)"
   - **description**: "FastAPI backend running with uvicorn --reload on 0.0.0.0:8000. Kill the background process to stop."
   - **activeForm**: "Running backend server on :8000"

2. **Start the server** (run in background):
   ```bash
   cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   Use `run_in_background: true` so the process runs in the background.

3. **Update task to in_progress** after the server starts successfully.
