"""Render the application icon to a multi-resolution ``.ico``.

The mark is drawn in code (:mod:`obs_overlay.ui.icons`), so there is no binary
asset to keep in sync with the theme. This script bakes it into the ``.ico``
that PyInstaller embeds in the executable.

The ICO container is assembled by hand rather than through ``QImage.save``:
Qt's ICO writer emits a single image, which leaves Windows to downscale 256px
artwork for the 16px tray slot, and the result is mush. Writing the directory
ourselves lets every size be rendered at its own scale, where the hinted
geometry in ``icons.py`` stays crisp. Each entry is stored as PNG, which every
Windows version since Vista reads.

Run:  python packaging/make_icon.py
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# None of this needs a display, but Qt still needs an application object
# before it will paint.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

from obs_overlay.ui.icons import app_pixmap  # noqa: E402

#: Sizes Explorer, the taskbar, Alt-Tab and the tray actually ask for.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

DEFAULT_OUTPUT = PROJECT_ROOT / "packaging" / "obs-overlay.ico"

_ICONDIR = "<HHH"  # reserved, type, count
_ICONDIRENTRY = "<BBBBHHII"  # w, h, colours, reserved, planes, bpp, size, offset


def _png_bytes(size: int) -> bytes:
    """One icon image, rendered at its native size and PNG-encoded."""
    # The QByteArray must outlive the QBuffer that writes into it; passing a
    # temporary lets Python free it while Qt still holds the pointer.
    storage = QByteArray()
    buffer = QBuffer(storage)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    try:
        if not app_pixmap(size).save(buffer, "PNG"):
            raise SystemExit(f"Could not encode the {size}px icon image")
    finally:
        buffer.close()
    return bytes(storage)


def build_icon(destination: Path = DEFAULT_OUTPUT) -> Path:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    assert app is not None

    images = [(size, _png_bytes(size)) for size in ICON_SIZES]

    header = struct.pack(_ICONDIR, 0, 1, len(images))
    offset = len(header) + len(images) * struct.calcsize(_ICONDIRENTRY)

    entries = bytearray()
    for size, payload in images:
        # 0 means 256 in the ICO directory; anything larger is not representable.
        dimension = 0 if size >= 256 else size
        entries += struct.pack(
            _ICONDIRENTRY, dimension, dimension, 0, 0, 1, 32, len(payload), offset
        )
        offset += len(payload)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        handle.write(header)
        handle.write(entries)
        for _, payload in images:
            handle.write(payload)
    return destination


def main() -> int:
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    written = build_icon(destination)
    print(f"Wrote {written} ({written.stat().st_size} bytes, {len(ICON_SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
