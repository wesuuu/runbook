"""Unit tests for the pure slug utilities."""

from app.core.slug import SLUG_MAX_LENGTH, dedupe_slugs, slugify


def test_slugify_lowercases_and_hyphenates():
    assert slugify("Buffer Prep") == "buffer-prep"


def test_slugify_strips_accents():
    assert slugify("Crème Brûlée") == "creme-brulee"


def test_slugify_drops_symbols_and_collapses_separators():
    assert slugify("Koch, Inc. ---  (R&D)!!") == "koch-inc-r-d"


def test_slugify_trims_leading_and_trailing_separators():
    assert slugify("  --Hello--  ") == "hello"


def test_slugify_caps_at_64_chars_without_trailing_hyphen():
    out = slugify("x " * 100)
    assert len(out) <= SLUG_MAX_LENGTH
    assert not out.endswith("-")


def test_slugify_returns_empty_for_no_alphanumeric_content():
    assert slugify("🎉🎉🎉") == ""
    assert slugify("") == ""


def test_dedupe_oldest_keeps_bare_slug_later_get_suffixes():
    # items are (row_id, base_slug), passed oldest-first.
    out = dedupe_slugs(
        [("a", "buffer-prep"), ("b", "buffer-prep"), ("c", "buffer-prep")]
    )
    assert out == {"a": "buffer-prep", "b": "buffer-prep-2", "c": "buffer-prep-3"}


def test_dedupe_avoids_colliding_with_a_real_suffixed_name():
    # A row literally slugified to "mix-2" must not be overwritten.
    out = dedupe_slugs([("a", "mix"), ("b", "mix-2"), ("c", "mix")])
    assert out == {"a": "mix", "b": "mix-2", "c": "mix-3"}


def test_dedupe_supplies_fallback_for_empty_base():
    out = dedupe_slugs([("a", "")])
    assert out["a"].startswith("untitled-")
    assert len(out["a"]) == len("untitled-") + 6
