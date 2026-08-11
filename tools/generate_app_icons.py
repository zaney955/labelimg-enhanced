"""Generate platform application icons from the canonical SVG artwork."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QGuiApplication, QImage, QPainter
from PyQt5.QtSvg import QSvgRenderer


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ICON_DIRECTORY = REPOSITORY_ROOT / "resources" / "icons"
PACKAGE_DATA_DIRECTORY = REPOSITORY_ROOT / "src" / "labelimg" / "data"
MASTER_SIZE = 1024
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_master(svg_path: Path, png_path: Path) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid SVG application icon: {svg_path}")

    image = QImage(MASTER_SIZE, MASTER_SIZE, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(
        painter,
        QRectF(0, 0, MASTER_SIZE, MASTER_SIZE),
    )
    painter.end()
    if not image.save(str(png_path), "PNG"):
        raise RuntimeError(f"Could not write PNG application icon: {png_path}")

    # Retain the local reference until rendering and image encoding are complete.
    del application


def generate() -> tuple[Path, ...]:
    svg_path = ICON_DIRECTORY / "app.svg"
    ico_path = ICON_DIRECTORY / "app.ico"
    icns_path = ICON_DIRECTORY / "app.icns"
    packaged_ico_path = PACKAGE_DATA_DIRECTORY / "app.ico"

    PACKAGE_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary_directory:
        png_path = Path(temporary_directory) / "app.png"
        render_master(svg_path, png_path)

        with Image.open(png_path) as master:
            rgba_master = master.convert("RGBA")
            rgba_master.save(
                ico_path,
                format="ICO",
                sizes=[(size, size) for size in ICO_SIZES],
            )
            rgba_master.save(icns_path, format="ICNS")

    shutil.copyfile(ico_path, packaged_ico_path)
    return ico_path, icns_path, packaged_ico_path


def main() -> int:
    for generated_path in generate():
        print(generated_path.relative_to(REPOSITORY_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
