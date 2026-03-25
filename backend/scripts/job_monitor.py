#!/usr/bin/env python3
"""Live monitor for background jobs.

Usage:
    python scripts/job_monitor.py              # watch all active jobs
    python scripts/job_monitor.py --all        # include completed/failed
    python scripts/job_monitor.py --doc ID     # watch jobs for a specific document
    python scripts/job_monitor.py --reset ID   # reset a stuck job to FAILED
"""

import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/runbook"
POLL_INTERVAL = 2  # seconds

# ANSI colors
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"

STATUS_COLORS = {
    "PENDING": YELLOW,
    "RUNNING": BLUE,
    "COMPLETED": GREEN,
    "FAILED": RED,
}


def color(status: str) -> str:
    return STATUS_COLORS.get(status, RESET)


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m"


def progress_bar(percent: int, width: int = 30) -> str:
    filled = int(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {percent}%"


async def fetch_jobs(engine, show_all: bool, doc_id: str | None):
    async with engine.begin() as conn:
        where_clauses = []
        if not show_all:
            where_clauses.append("j.status IN ('PENDING', 'RUNNING')")
        if doc_id:
            where_clauses.append(f"j.entity_id = '{doc_id}'")

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        r = await conn.execute(text(f"""
            SELECT
                j.id,
                j.job_type,
                j.status,
                j.entity_id,
                j.output_data,
                j.error_message,
                j.started_at,
                j.completed_at,
                j.created_at,
                j.worker_id,
                j.attempts,
                extract(epoch from (now() - j.started_at))::int as running_seconds,
                d.title as doc_title,
                d.status as doc_status,
                d.page_count
            FROM background_jobs j
            LEFT JOIN documents d ON d.id = j.entity_id AND j.entity_type = 'document'
            {where}
            ORDER BY j.created_at DESC
            LIMIT 20
        """))
        return r.fetchall()


async def reset_job(engine, job_id: str):
    async with engine.begin() as conn:
        r = await conn.execute(text(f"""
            UPDATE background_jobs
            SET status = 'FAILED',
                error_message = 'Manually reset via job_monitor',
                completed_at = now()
            WHERE id = '{job_id}' AND status IN ('PENDING', 'RUNNING')
            RETURNING id, entity_id
        """))
        row = r.fetchone()
        if row:
            # Also reset the document if it's stuck in PROCESSING
            await conn.execute(text(f"""
                UPDATE documents
                SET status = 'UPLOADED',
                    processing_started_at = NULL,
                    error_message = NULL
                WHERE id = '{row[1]}' AND status = 'PROCESSING'
            """))
            return row[0]
        return None


def render(jobs, clear: bool = True):
    if clear:
        print("\033[2J\033[H", end="")  # clear screen

    now = datetime.now(timezone.utc)
    print(f"{BOLD}Background Job Monitor{RESET}  {DIM}{now.strftime('%H:%M:%S')}{RESET}")
    print(f"{DIM}{'─' * 90}{RESET}")

    if not jobs:
        print(f"\n  {DIM}No jobs found.{RESET}\n")
        return

    for row in jobs:
        (
            job_id, job_type, status, entity_id, output_data,
            error_msg, started_at, completed_at, created_at,
            worker_id, attempts, running_secs,
            doc_title, doc_status, page_count,
        ) = row

        c = color(status)
        short_id = str(job_id)[:8]
        short_entity = str(entity_id)[:8] if entity_id else "-"

        # Header line
        print(
            f"\n  {c}{BOLD}{status:10s}{RESET} "
            f"{BOLD}{job_type}{RESET}  "
            f"{DIM}job:{short_id}  doc:{short_entity}{RESET}"
        )

        # Document info
        if doc_title:
            title_display = doc_title[:50] + "..." if len(doc_title) > 50 else doc_title
            print(f"           {DIM}Document:{RESET} {title_display}  {DIM}({doc_status}, {page_count or '?'} pages){RESET}")

        # Duration
        if status == "RUNNING" and running_secs is not None:
            duration_str = format_duration(running_secs)
            stale_warning = ""
            if running_secs > 600:
                stale_warning = f"  {RED}⚠ possibly stuck{RESET}"
            elif running_secs > 300:
                stale_warning = f"  {YELLOW}⚠ slow{RESET}"
            print(f"           {DIM}Running for:{RESET} {duration_str}{stale_warning}")
        elif status == "COMPLETED" and started_at and completed_at:
            dur = (completed_at - started_at).total_seconds()
            print(f"           {DIM}Completed in:{RESET} {format_duration(dur)}")

        # Progress
        if output_data and isinstance(output_data, dict):
            stage = output_data.get("stage")
            if stage:
                label = output_data.get("stage_label", stage)
                current = output_data.get("current", 0)
                total = output_data.get("total", 0)
                percent = output_data.get("percent", 0)
                print(f"           {CYAN}{label}{RESET}: {current}/{total}  {progress_bar(percent)}")
            elif "chunk_count" in output_data:
                # Completed job summary
                pc = output_data.get("page_count", "?")
                cc = output_data.get("chunk_count", "?")
                print(f"           {DIM}Result:{RESET} {pc} pages, {cc} chunks")
            elif "pages_classified" in output_data:
                pc = output_data.get("pages_classified", "?")
                roles = output_data.get("roles", [])
                print(f"           {DIM}Result:{RESET} {pc} pages classified, roles: {', '.join(roles)}")

        # Error
        if error_msg:
            err_display = error_msg[:80] + "..." if len(error_msg) > 80 else error_msg
            print(f"           {RED}Error: {err_display}{RESET}")

        # Worker
        if worker_id and status == "RUNNING":
            print(f"           {DIM}Worker: {worker_id}{RESET}")

    print(f"\n{DIM}{'─' * 90}{RESET}")
    print(f"{DIM}  Showing {len(jobs)} job(s). Press Ctrl+C to exit.{RESET}\n")


async def watch(show_all: bool, doc_id: str | None):
    engine = create_async_engine(DB_URL)
    try:
        while True:
            jobs = await fetch_jobs(engine, show_all, doc_id)
            render(jobs)
            await asyncio.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print(f"\n{DIM}Stopped.{RESET}")
    finally:
        await engine.dispose()


async def do_reset(job_id: str):
    engine = create_async_engine(DB_URL)
    try:
        result = await reset_job(engine, job_id)
        if result:
            print(f"{GREEN}Reset job {job_id} to FAILED and document to UPLOADED.{RESET}")
        else:
            print(f"{RED}Job {job_id} not found or not in PENDING/RUNNING state.{RESET}")
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Monitor background jobs")
    parser.add_argument("--all", action="store_true", help="Show all jobs (including completed/failed)")
    parser.add_argument("--doc", type=str, help="Filter by document ID")
    parser.add_argument("--reset", type=str, metavar="JOB_ID", help="Reset a stuck job to FAILED")
    parser.add_argument("--once", action="store_true", help="Print once and exit (no live watch)")
    args = parser.parse_args()

    if args.reset:
        asyncio.run(do_reset(args.reset))
        return

    if args.once:
        engine = create_async_engine(DB_URL)

        async def run():
            jobs = await fetch_jobs(engine, args.all, args.doc)
            render(jobs, clear=False)
            await engine.dispose()

        asyncio.run(run())
        return

    asyncio.run(watch(args.all, args.doc))


if __name__ == "__main__":
    main()
