import os
from unittest.mock import patch

from app.core.config import Settings


def test_legal_gate_enabled_default_true():
    s = Settings()
    assert s.legal_gate_enabled is True


def test_legal_gate_enabled_can_be_disabled_via_env():
    with patch.dict(os.environ, {"BATCHRITE_LEGAL_GATE_ENABLED": "false"}):
        s = Settings()
        assert s.legal_gate_enabled is False
