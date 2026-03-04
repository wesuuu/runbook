---
name: local_dev 
description: Instructions for configuring and interacting with the local development environment, specifically for database connections and process management.
---

# Local Development Environment

This skill provides context and instructions for developing in the local environment, avoiding unnecessary containerization (Docker) when native services are available.

## Python Environment

- **Virtual Environment**: All Python projects must use a virtual environment located at `.venv` in the project root.
- **Python Version**: Use the native `python3.13`.
- **Creation**: `python3.13 -m venv .venv`
- **Activation**: `source .venv/bin/activate`
- **Usage**: Always ensure the virtual environment is verified active (check `sys.prefix` or `which python`) before running any Python commands (pip, python, uvicorn, alembic, etc.).

## Database Configuration (PostgreSQL)

A local PostgreSQL instance is running and available for use. Do not attempt to start a new Postgres container via Docker Compose unless explicitly instructed otherwise or if the local instance is unavailable/incompatible.

- **Host**: `localhost`
- **Port**: `5432`
- **Username**: `postgres`
- **Password**: `postgres`
- **Database Names**:
    - `runbook` (Primary application database - to be created if not exists)
    - `postgres` (Default maintenance database)

## Process Management

- **Preference**: Run services natively using their respective runtimes (e.g., `python`, `npm`, `go`) instead of Docker Compose.
- **Frontend**: `npm run dev` (SvelteKit)
- **Backend**: Ensure `.venv` is active, then run: `uvicorn main:app --reload` (FastAPI) or similar.

## Common Issues

- **Port Conflicts**: Ensure ports `5432` (Postgres), `8000` (API), and `5173` (Frontend) are free or adjust configuration accordingly.
- **Environment Variables**: Use `.env` files to configure connection strings pointing to the local Postgres instance.
