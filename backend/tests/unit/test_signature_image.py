"""Unit tests for the typed-name signature image generator.

When a signer has not uploaded a hand-drawn signature, an APPROVED sign-off
falls back to a cursive image rendered from the signer's name so the
21 CFR §11.50 attestation-and-image requirement is still met.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

from PIL import Image

from app.services.signoffs.signature_image import (
    render_name_signature_png,
    signer_display_name,
)


def test_render_returns_png_bytes() -> None:
    png = render_name_signature_png("Wesley Chen")
    assert isinstance(png, bytes)
    # PNG magic number.
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_produces_transparent_rgba_image() -> None:
    img = Image.open(io.BytesIO(render_name_signature_png("Wesley Chen")))
    assert img.mode == "RGBA"
    # Top-left corner pixel must be fully transparent (background).
    assert img.getpixel((0, 0))[3] == 0
    # Some pixel must be opaque (the rendered glyphs).
    alphas = img.getdata(band=3)
    assert max(alphas) > 0


def test_render_handles_blank_name_without_crashing() -> None:
    png = render_name_signature_png("")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    png_ws = render_name_signature_png("   ")
    assert png_ws[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_different_names_differ() -> None:
    assert render_name_signature_png("Wesley Chen") != render_name_signature_png(
        "Ada Lovelace"
    )


def test_signer_display_name_prefers_full_name() -> None:
    user = SimpleNamespace(full_name="Wesley Chen", email="wes@bioprocess.com")
    assert signer_display_name(user) == "Wesley Chen"


def test_signer_display_name_falls_back_to_email_local_part() -> None:
    user = SimpleNamespace(full_name=None, email="wes@bioprocess.com")
    assert signer_display_name(user) == "wes"
    blank = SimpleNamespace(full_name="   ", email="wes@bioprocess.com")
    assert signer_display_name(blank) == "wes"


def test_signer_display_name_final_fallback() -> None:
    user = SimpleNamespace(full_name=None, email=None)
    assert signer_display_name(user) == "Signer"
