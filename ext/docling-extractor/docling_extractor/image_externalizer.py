"""Externalize docling picture regions to PNG files on disk.

Docling's ``export_to_markdown()`` inserts literal ``<!-- image -->``
placeholders where a figure would render. We replace each placeholder
in order with ``![caption](images/N.png)`` after writing the PNG bytes
to ``{output_dir}/images/{N}.png``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

_PLACEHOLDER = "<!-- image -->"
_PLACEHOLDER_RE = re.compile(re.escape(_PLACEHOLDER))


@dataclass
class ExtractedPicture:
    index: int
    png_bytes: bytes
    caption: str = ""
    # When ``skip`` is True the picture was detected by docling but
    # rejected (e.g. degenerate sub-50px figure regions). We keep it in
    # the list — preserving 1:1 alignment between docling's pictures and
    # the ``<!-- image -->`` placeholders in the markdown — but neither
    # write its bytes nor emit a markdown reference for it.
    skip: bool = False


def externalize_images(
    pictures: List[ExtractedPicture], images_dir: Path
) -> None:
    images_dir.mkdir(parents=True, exist_ok=True)
    for pic in pictures:
        if pic.skip:
            continue
        (images_dir / f"{pic.index}.png").write_bytes(pic.png_bytes)


def rewrite_markdown_image_refs(
    markdown: str, pictures: List[ExtractedPicture]
) -> str:
    iterator = iter(pictures)

    def _sub(_match: re.Match) -> str:
        try:
            pic = next(iterator)
        except StopIteration:
            return ""
        if pic.skip:
            return ""
        caption = pic.caption or ""
        return f"![{caption}](images/{pic.index}.png)"

    return _PLACEHOLDER_RE.sub(_sub, markdown)
