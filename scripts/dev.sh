#!/usr/bin/env bash
# Start backend (uvicorn :8000) and frontend (vite :5173) together.
# If either process exits, kill the other and exit.

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill -- "-$BACKEND_PID" 2>/dev/null || kill "$BACKEND_PID" 2>/dev/null
  fi
  if [[ -n "${FRONTEND_PID:-}" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill -- "-$FRONTEND_PID" 2>/dev/null || kill "$FRONTEND_PID" 2>/dev/null
  fi
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Backend
(
  cd "$ROOT/backend"
  source .venv/bin/activate
  exec uvicorn app.main:app --reload --host 0.0.0.0
) &
BACKEND_PID=$!

# Frontend
(
  cd "$ROOT/frontend"
  exec npm run dev:tailscale
) &
FRONTEND_PID=$!

echo "backend pid=$BACKEND_PID  frontend pid=$FRONTEND_PID"

# Wait for whichever exits first, then the trap kills the other.
wait -n "$BACKEND_PID" "$FRONTEND_PID"
EXIT_CODE=$?

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "backend exited; shutting down frontend" >&2
elif ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  echo "frontend exited; shutting down backend" >&2
fi

exit "$EXIT_CODE"
