"""Unit tests for the app_help subagent (F-0089)."""

from pathlib import Path

from app.core.config import settings


def test_user_guide_dir_points_at_repo_docs():
    """user_guide_dir resolves to the repo-root docs/user-guide directory."""
    path = Path(settings.user_guide_dir)
    assert path.name == "user-guide"
    assert path.parent.name == "docs"
    # Absolute so it resolves regardless of process CWD (backend/ at runtime).
    assert path.is_absolute()
