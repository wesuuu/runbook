"""YAML-backed pydantic-settings source.

Provides `YamlConfigSettingsSource`, a `PydanticBaseSettingsSource` that loads
settings values from a YAML file. Discovery:

1. If `BATCHRITE_SETTINGS_FILE` is set, load that path (must exist).
2. Else, if `backend/settings.yaml` exists, load it.
3. Else, contribute nothing.

Precedence is controlled by `Settings.settings_customise_sources` -- see
`app.core.config`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic.fields import FieldInfo
from pydantic_settings import PydanticBaseSettingsSource

_SETTINGS_FILE_ENV_VAR = "BATCHRITE_SETTINGS_FILE"

# Resolves to `backend/settings.yaml` -- this file lives at
# `backend/app/core/yaml_source.py`, so three parents up is `backend/`.
_DEFAULT_YAML_PATH = Path(__file__).parent.parent.parent / "settings.yaml"


def _resolve_yaml_path() -> Path | None:
    """Return the YAML file path to load, or None if no YAML should be used.

    Raises FileNotFoundError if `BATCHRITE_SETTINGS_FILE` is set but the
    target file doesn't exist.
    """
    explicit = os.environ.get(_SETTINGS_FILE_ENV_VAR)
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(
                f"{_SETTINGS_FILE_ENV_VAR} points at {path}, " f"which does not exist."
            )
        return path
    if _DEFAULT_YAML_PATH.is_file():
        return _DEFAULT_YAML_PATH
    return None


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """Pydantic settings source backed by a YAML file."""

    def __init__(self, settings_cls: type) -> None:
        super().__init__(settings_cls)
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        path = _resolve_yaml_path()
        if path is None:
            return {}
        with path.open("r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise ValueError(
                f"YAML settings file {path} must contain a mapping at the "
                f"top level, got {type(parsed).__name__}."
            )
        return parsed

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        value = self._data.get(field_name)
        return value, field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._data
