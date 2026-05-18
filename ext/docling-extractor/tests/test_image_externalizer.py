from pathlib import Path

from docling_extractor.image_externalizer import (ExtractedPicture,
                                                  externalize_images,
                                                  rewrite_markdown_image_refs)

# Minimal 1x1 transparent PNG
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "89000000017352474200aece1ce90000000d49444154789c63"
    "f8cf00000000ffff03000001ff01ff5f5f5f5e0000000049454e44ae426082"
)


def test_writes_pngs_to_disk(tmp_path: Path):
    pics = [
        ExtractedPicture(index=0, png_bytes=PNG_1X1, caption="Fig 1"),
        ExtractedPicture(index=1, png_bytes=PNG_1X1, caption=""),
    ]
    externalize_images(pics, tmp_path)
    assert (tmp_path / "0.png").read_bytes() == PNG_1X1
    assert (tmp_path / "1.png").read_bytes() == PNG_1X1


def test_rewrites_placeholders_in_order():
    pics = [
        ExtractedPicture(index=0, png_bytes=PNG_1X1, caption="Fig 1"),
        ExtractedPicture(index=1, png_bytes=PNG_1X1, caption=""),
    ]
    md_in = "Para 1\n\n<!-- image -->\n\nPara 2\n\n<!-- image -->\n\nPara 3"
    md_out = rewrite_markdown_image_refs(md_in, pics)
    assert "![Fig 1](images/0.png)" in md_out
    assert "![](images/1.png)" in md_out
    assert "<!-- image -->" not in md_out


def test_skipped_pictures_are_not_written(tmp_path: Path):
    """Pictures marked ``skip=True`` are kept in the list (to preserve
    placeholder ↔ picture alignment) but never reach disk."""
    pics = [
        ExtractedPicture(index=0, png_bytes=PNG_1X1, caption="Fig 1"),
        ExtractedPicture(index=1, png_bytes=PNG_1X1, caption="", skip=True),
        ExtractedPicture(index=2, png_bytes=PNG_1X1, caption="Fig 3"),
    ]
    externalize_images(pics, tmp_path)
    assert (tmp_path / "0.png").exists()
    assert not (tmp_path / "1.png").exists()
    assert (tmp_path / "2.png").exists()


def test_skipped_pictures_drop_their_placeholder():
    """A skipped picture's ``<!-- image -->`` placeholder is removed
    entirely (not replaced with a broken link), and subsequent
    placeholders still align with the next non-skipped picture."""
    pics = [
        ExtractedPicture(index=0, png_bytes=PNG_1X1, caption="Fig 1"),
        ExtractedPicture(index=1, png_bytes=PNG_1X1, caption="degenerate", skip=True),
        ExtractedPicture(index=2, png_bytes=PNG_1X1, caption="Fig 3"),
    ]
    md_in = (
        "Para A\n\n<!-- image -->\n\n"
        "Para B\n\n<!-- image -->\n\n"
        "Para C\n\n<!-- image -->\n\nEnd"
    )
    md_out = rewrite_markdown_image_refs(md_in, pics)
    assert "![Fig 1](images/0.png)" in md_out
    assert "images/1.png" not in md_out
    assert "degenerate" not in md_out
    assert "![Fig 3](images/2.png)" in md_out
    assert "<!-- image -->" not in md_out
