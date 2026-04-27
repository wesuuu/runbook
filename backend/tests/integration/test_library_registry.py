"""Tests for the unit op library registry (F-0075)."""
import uuid
from pathlib import Path

import pytest

from app.services.science import library_registry as lr


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test starts with an empty registry."""
    lr._reset_for_tests()
    yield
    lr._reset_for_tests()


@pytest.mark.asyncio
async def test_synthetic_uuid_is_deterministic():
    a = lr.synthetic_uuid("core", "mixing")
    b = lr.synthetic_uuid("core", "mixing")
    assert a == b
    assert isinstance(a, uuid.UUID)


@pytest.mark.asyncio
async def test_synthetic_uuid_differs_per_op():
    assert lr.synthetic_uuid("core", "mixing") != lr.synthetic_uuid("core", "centrifugation")
    assert lr.synthetic_uuid("core", "mixing") != lr.synthetic_uuid("other", "mixing")


@pytest.mark.asyncio
async def test_bundled_source_loads_core_library():
    src = lr.BundledJSONSource(
        Path(__file__).resolve().parents[2] / "app/data/unit_op_libraries"
    )
    libs = await src.load()
    assert len(libs) == 1
    core = libs[0]
    assert core.slug == "core"
    assert core.is_default is True
    assert core.version == "1.0.0"
    assert len(core.unit_ops) == 12
    slugs = {op.slug for op in core.unit_ops}
    assert "solution_preparation" in slugs
    assert "mixing" in slugs
    assert "storage" in slugs


@pytest.mark.asyncio
async def test_register_and_reload_populates_cache():
    fake = _FakeSource([
        lr.Library(
            slug="alpha", name="Alpha", domain="general",
            description="", is_default=True, version="1.0.0",
            unit_ops=[
                lr.UnitOp(
                    slug="op_one", name="Op One", category="Cat",
                    description="", param_schema={}, result_schema={},
                ),
            ],
        ),
    ])
    lr.register_source(fake)
    await lr.reload_libraries()

    assert [lib.slug for lib in lr.list_libraries()] == ["alpha"]
    assert lr.get_library("alpha") is not None
    assert lr.get_op("alpha", "op_one") is not None
    assert lr.get_op("alpha", "missing") is None
    assert lr.default_library_slugs() == ["alpha"]


@pytest.mark.asyncio
async def test_reload_is_atomic_on_source_failure():
    fake_ok = _FakeSource([
        lr.Library(slug="good", name="Good", domain="general",
                   description="", is_default=False, version="1",
                   unit_ops=[]),
    ])
    lr.register_source(fake_ok)
    await lr.reload_libraries()
    assert lr.get_library("good") is not None

    # Replace with a failing source. Reload must raise but leave cache intact.
    lr._reset_sources_for_tests()
    lr.register_source(_FailingSource())
    with pytest.raises(RuntimeError):
        await lr.reload_libraries()
    assert lr.get_library("good") is not None  # cache unchanged


@pytest.mark.asyncio
async def test_last_source_wins_on_slug_collision():
    earlier = _FakeSource([
        lr.Library(slug="x", name="Earlier", domain="general",
                   description="", is_default=False, version="1",
                   unit_ops=[]),
    ])
    later = _FakeSource([
        lr.Library(slug="x", name="Later", domain="general",
                   description="", is_default=False, version="2",
                   unit_ops=[]),
    ])
    lr.register_source(earlier)
    lr.register_source(later)
    await lr.reload_libraries()
    assert lr.get_library("x").name == "Later"


# --- Helpers ---


class _FakeSource:
    def __init__(self, libs: list):
        self._libs = libs
    async def load(self):
        return self._libs


class _FailingSource:
    async def load(self):
        raise RuntimeError("boom")
