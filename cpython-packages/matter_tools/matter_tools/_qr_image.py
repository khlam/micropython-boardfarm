"""Render a Matter QR setup payload string to a scannable PNG image."""

from __future__ import annotations

from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from qrcode.image.pil import PilImage

_VERSION = 2
_BOX_SIZE = 6


def render(payload: str, path: Path) -> None:
    """Render payload as a QR code PNG at path.

    Explicitly requests the Pillow-backed image factory rather than relying on
    `qrcode`'s default backend selection, so this never silently falls back to
    its pure-Python PNG path -- which depends on `pypng`, the exact abandoned
    package this project replaced `esp-matter-mfg-tool` to stop depending on.

    Args:
        payload: The setup payload string to encode (e.g. "MT:...").
        path: Output PNG path.
    """
    qr = qrcode.QRCode(
        version=_VERSION,
        error_correction=ERROR_CORRECT_M,
        box_size=_BOX_SIZE,
        image_factory=PilImage,
    )
    qr.add_data(payload)
    qr.make(fit=False)
    qr.make_image().save(str(path))
