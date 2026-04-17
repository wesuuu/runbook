#!/bin/bash

source .venv/bin/activate
uvicorn app.main:app --port 8000 --reload --host 0.0.0.0 --log-level=debug
