"""Shared types and helpers for permutation fixtures.

Each ``build_pN()`` returns a :class:`BuiltPermutation`:

- ``kwargs`` is the dict of keyword args passed to ``build_context()``.
- ``expected_on`` is a list of substrings that MUST appear in the rendered
  text.
- ``expected_off`` is a list of substrings that MUST NOT appear.
- ``renders_against`` is the tuple of template keys (``"sop"``,
  ``"batch_record"``) the permutation is configured to render against.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BuiltPermutation:
    name: str
    kwargs: dict
    expected_on: list[str] = field(default_factory=list)
    expected_off: list[str] = field(default_factory=list)
    renders_against: tuple[str, ...] = ("sop", "batch_record")
