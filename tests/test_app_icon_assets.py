import hashlib
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt5.QtGui import QGuiApplication, QIcon

import labelimg
import labelimg.resources  # noqa: F401 - registers the compiled Qt resources


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ICON_DIRECTORY = REPOSITORY_ROOT / "resources" / "icons"
EXPECTED_ICO_SIZES = {
    (16, 16),
    (20, 20),
    (24, 24),
    (32, 32),
    (40, 40),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
}


class TestAppIconAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QGuiApplication.instance() or QGuiApplication([])

    def test_qt_resource_uses_square_stretched_svg(self):
        resource_tree = ElementTree.parse(REPOSITORY_ROOT / "resources.qrc")
        app_resources = [
            element
            for element in resource_tree.iter("file")
            if element.get("alias") == "app"
        ]
        self.assertEqual(len(app_resources), 1)
        self.assertEqual(app_resources[0].text, "resources/icons/app.svg")

        svg_root = ElementTree.parse(ICON_DIRECTORY / "app.svg").getroot()
        self.assertEqual(svg_root.get("width"), "468")
        self.assertEqual(svg_root.get("height"), "468")
        self.assertEqual(svg_root.get("viewBox"), "0 0 468 445")
        self.assertEqual(svg_root.get("preserveAspectRatio"), "none")

    def test_compiled_qt_icon_renders_at_windows_sizes(self):
        icon = QIcon(":/app")
        self.assertFalse(icon.isNull())
        for size in (16, 24, 32, 48, 64, 128, 256):
            with self.subTest(size=size):
                self.assertFalse(icon.pixmap(size, size).isNull())

    def test_generated_platform_assets_are_valid(self):
        with Image.open(ICON_DIRECTORY / "app.png") as png_image:
            self.assertEqual(png_image.format, "PNG")
            self.assertEqual(png_image.size, (1024, 1024))

        with Image.open(ICON_DIRECTORY / "app.ico") as ico_image:
            self.assertEqual(ico_image.format, "ICO")
            self.assertEqual(set(ico_image.ico.sizes()), EXPECTED_ICO_SIZES)

        with Image.open(ICON_DIRECTORY / "app.icns") as icns_image:
            self.assertEqual(icns_image.format, "ICNS")
            icns_sizes = {
                (width * scale, height * scale)
                for width, height, scale in icns_image.icns.itersizes()
            }
            self.assertTrue({(32, 32), (128, 128), (256, 256), (512, 512), (1024, 1024)} <= icns_sizes)

    def test_packaged_shortcut_icon_matches_generated_ico(self):
        packaged_icon = Path(labelimg.__file__).parent / "data" / "app.ico"
        generated_icon = ICON_DIRECTORY / "app.ico"
        self.assertTrue(packaged_icon.is_file())
        self.assertEqual(
            hashlib.sha256(packaged_icon.read_bytes()).digest(),
            hashlib.sha256(generated_icon.read_bytes()).digest(),
        )


if __name__ == "__main__":
    unittest.main()
