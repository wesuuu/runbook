"""Generate a cursive signature image from a typed name.

Used when an APPROVED sign-off is created for a signer who has not uploaded a
hand-drawn signature: ``create_signoff`` falls back to a generated image so the
21 CFR §11.50 attestation-and-image requirement is still met, and the
``GET /auth/me/default-signature`` preview endpoint renders the same image in
the sign-off modal so the signer can see what will be pinned.

The signer can always replace the generated default with a real signature via
Settings → Profile; uploads take precedence over the generated fallback.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from app.services.documents.fonts import FONTS_DIR

_CURSIVE_FONT_PATH = str(FONTS_DIR / "DancingScript-Regular.ttf")
_FONT_SIZE = 64
_PADDING = 24
# Near-black, fully opaque — matches the ink weight of an uploaded signature.
_INK = (17, 24, 39, 255)


def signer_display_name(user: object) -> str:
    """Resolve the human-readable name to render into a signature.

    Prefers ``full_name``; falls back to the local part of ``email``; finally
    a generic ``"Signer"`` so the generator never receives an empty string.
    """
    full_name = (getattr(user, "full_name", None) or "").strip()
    if full_name:
        return full_name
    email = (getattr(user, "email", None) or "").strip()
    if email:
        return email.split("@", 1)[0] or "Signer"
    return "Signer"


def render_name_signature_png(name: str) -> bytes:
    """Render ``name`` in cursive on a transparent background; return PNG bytes."""
    text = (name or "").strip() or "Signer"
    font = ImageFont.truetype(_CURSIVE_FONT_PATH, _FONT_SIZE)

    # Measure the glyphs so the canvas fits the text snugly.
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = measure.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    image = Image.new(
        "RGBA",
        (text_w + _PADDING * 2, text_h + _PADDING * 2),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(image)
    # Offset by the bbox origin so glyphs with negative bearings aren't clipped.
    draw.text(
        (_PADDING - bbox[0], _PADDING - bbox[1]), text, font=font, fill=_INK
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
