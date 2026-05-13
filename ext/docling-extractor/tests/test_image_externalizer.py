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
