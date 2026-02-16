---
name: Start Backend Server
description: Starts the FastAPI backend server in development mode using Uvicorn.
---

# Start Backend Server

To start the backend server, run the following command from the project root:

```bash
cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000
```
