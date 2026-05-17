"""Tests for the pipeline's docling-picture extraction + filtering.

We don't invoke real docling here — that's the smoke test's job. Instead
we stub the doc.pictures iterable with shapes that mimic docling's API
surface so we can pin down the size-filter behavior in isolation.
"""

from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from docling_extractor.pipeline import _iter_pictures


def _png_of_size(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color=(128, 64, 200))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fake_picture(width: int, height: int, caption: str = "") -> SimpleNamespace:
    """Mimic the docling picture-item shape ``_iter_pictures`` walks."""
    pil = Image.new("RGB", (width, height))
    png = _png_of_size(width, height)

    image = SimpleNamespace(
        pil_image=pil,
        to_bytes=lambda data=png: data,
    )
    captions = [SimpleNamespace(text=caption)] if caption else []
    return SimpleNamespace(image=image, captions=captions)


def test_keeps_pictures_above_threshold():
    doc = SimpleNamespace(pictures=[_fake_picture(120, 80, "good")])
    [pic] = _iter_pictures(doc)
    assert pic.skip is False
    assert pic.caption == "good"


def test_marks_tiny_pictures_as_skip():
    """16x11 thumbs (the case observed in the wild) get skip=True so
    they get neither written to disk nor referenced from the markdown."""
    doc = SimpleNamespace(pictures=[_fake_picture(16, 11)])
    [pic] = _iter_pictures(doc)
    assert pic.skip is True


def test_filter_preserves_ordering_and_indices():
    """The 1:1 alignment between pictures and ``<!-- image -->``
    placeholders depends on _iter_pictures returning every picture
    docling reported, in order, with original indices intact."""
    doc = SimpleNamespace(pictures=[
        _fake_picture(200, 150, "big-a"),
        _fake_picture(16, 11, "tiny"),
        _fake_picture(180, 120, "big-b"),
    ])
    pics = _iter_pictures(doc)
    assert [p.index for p in pics] == [0, 1, 2]
    assert [p.skip for p in pics] == [False, True, False]
