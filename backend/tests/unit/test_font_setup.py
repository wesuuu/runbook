import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.documents.font_setup import ensure_cursive_font_registered


def test_copies_font_into_user_fonts_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    fake_run = patch("subprocess.run").start()
    try:
        ensure_cursive_font_registered()
    finally:
        patch.stopall()

    dest = tmp_path / ".fonts" / "DancingScript-Regular.ttf"
    assert dest.exists(), "font should be copied into ~/.fonts"
    fake_run.assert_called_once()
    args = fake_run.call_args.args[0]
    assert args[0] == "fc-cache"


def test_idempotent_when_dest_already_current(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    dest_dir = tmp_path / ".fonts"
    dest_dir.mkdir()
    # Pre-populate dest with a copy that has a NEWER mtime than the source
    from app.services.documents.fonts import FONTS_DIR
    src = FONTS_DIR / "DancingScript-Regular.ttf"
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    # Bump dest mtime to "now + 1 day" so it's strictly newer than src
    future = src.stat().st_mtime + 86400
    import os
    os.utime(dest, (future, future))

    fake_run = patch("subprocess.run").start()
    try:
        ensure_cursive_font_registered()
    finally:
        patch.stopall()

    fake_run.assert_not_called()


def test_swallow_fc_cache_failure(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HOME", str(tmp_path))
    fake_run = patch(
        "subprocess.run",
        side_effect=subprocess.SubprocessError("simulated"),
    ).start()
    try:
        # Must not raise
        ensure_cursive_font_registered()
    finally:
        patch.stopall()

    assert any("fc-cache" in r.getMessage().lower() for r in caplog.records)
