---
name: backend_dev
description: Starts the FastAPI backend server in development mode using Uvicorn.
---

# Start Backend Server

To start the backend server, run the following command from the project root:

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
