"""QA-0008: get_mock_context() must include every new template surface key."""

from app.services.protocols.template_engine import KNOWN_VARIABLES, get_mock_context


def test_mock_context_covers_known_variables():
    ctx = get_mock_context()
    missing = KNOWN_VARIABLES - set(ctx.keys())
    assert not missing, f"get_mock_context is missing keys: {sorted(missing)}"
