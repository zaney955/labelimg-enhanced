import hashlib
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt5.QtGui import QGuiApplication, QIcon, QImage

import labelimg
import labelimg.ui.generated_resources  # noqa: F401 - registers the compiled Qt resources


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
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

    def test_qt_resource_uses_square_svg(self):
        resource_tree = ElementTree.parse(REPOSITORY_ROOT / "resources.qrc")
        app_resources = [
            element
            for element in resource_tree.iter("file")
            if element.get("alias") == "app"
        ]
        self.assertEqual(len(app_resources), 1)
        self.assertEqual(app_resources[0].text, "resources/icons/app.svg")

        svg_root = ElementTree.parse(ICON_DIRECTORY / "app.svg").getroot()
        self.assertEqual(svg_root.get("width"), "1024")
        self.assertEqual(svg_root.get("height"), "1024")
        self.assertEqual(svg_root.get("viewBox"), "95.75 103.14 832.5 832.5")
        self.assertIsNone(svg_root.get("preserveAspectRatio"))

    def test_runtime_resources_are_svg_only(self):
        resource_tree = ElementTree.parse(REPOSITORY_ROOT / "resources.qrc")
        resource_elements = list(resource_tree.iter("file"))
        runtime_paths = [element.text for element in resource_elements]
        self.assertTrue(runtime_paths)
        self.assertTrue(all(
            path.endswith(".svg") for path in runtime_paths
        ))
        self.assertEqual(
            sorted(path.name for path in ICON_DIRECTORY.glob("*.png")),
            [],
        )
        self.assertEqual(
            set(runtime_paths),
            {
                path.relative_to(REPOSITORY_ROOT).as_posix()
                for path in ICON_DIRECTORY.glob("*.svg")
            },
        )
        for element in resource_elements:
            alias = element.get("alias")
            with self.subTest(alias=alias):
                icon = QIcon(":/" + alias)
                self.assertFalse(icon.isNull())
                self.assertFalse(icon.pixmap(24, 24).isNull())
        for relative_path in sorted(set(runtime_paths)):
            if relative_path.endswith("/app.svg"):
                continue
            svg_root = ElementTree.parse(
                REPOSITORY_ROOT / relative_path
            ).getroot()
            with self.subTest(path=relative_path):
                self.assertEqual(svg_root.get("width"), "24")
                self.assertEqual(svg_root.get("height"), "24")
                self.assertEqual(svg_root.get("viewBox"), "0 0 24 24")

    def test_operation_svg_style_is_uniform_and_font_independent(self):
        expected_root_attributes = {
            "width": "24",
            "height": "24",
            "viewBox": "0 0 24 24",
            "fill": "none",
            "stroke": "#3c4043",
            "stroke-width": "1.8",
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
        }
        forbidden_elements = {"foreignObject", "image", "script", "text"}
        allowed_paints = {"#3c4043", "none"}

        for path in sorted(ICON_DIRECTORY.glob("*.svg")):
            if path.name == "app.svg":
                continue
            root = ElementTree.parse(path).getroot()
            with self.subTest(path=path.name):
                for name, value in expected_root_attributes.items():
                    self.assertEqual(root.get(name), value)
                for element in root.iter():
                    tag = element.tag.rsplit("}", 1)[-1]
                    self.assertNotIn(tag, forbidden_elements)
                    self.assertNotIn("style", element.attrib)
                    for attribute in ("fill", "stroke"):
                        paint = element.get(attribute)
                        if paint is not None:
                            self.assertIn(paint, allowed_paints)

    def test_operation_svgs_render_cleanly_and_uniquely_at_menu_size(self):
        signatures = {}
        for path in sorted(ICON_DIRECTORY.glob("*.svg")):
            if path.name == "app.svg":
                continue
            icon = QIcon(str(path))
            with self.subTest(path=path.name):
                self.assertFalse(icon.isNull())
                for size in (16, 20, 24):
                    image = icon.pixmap(size, size).toImage()
                    opaque_points = [
                        (x, y)
                        for y in range(size)
                        for x in range(size)
                        if image.pixelColor(x, y).alpha()
                    ]
                    self.assertTrue(opaque_points)
                    bounds = (
                        min(x for x, _y in opaque_points),
                        min(y for _x, y in opaque_points),
                        max(x for x, _y in opaque_points),
                        max(y for _x, y in opaque_points),
                    )
                    self.assertGreater(bounds[0], 0)
                    self.assertGreater(bounds[1], 0)
                    self.assertLess(bounds[2], size - 1)
                    self.assertLess(bounds[3], size - 1)

                image = icon.pixmap(24, 24).toImage().convertToFormat(
                    QImage.Format_ARGB32
                )
                signatures[path.name] = hashlib.sha256(
                    image.bits().asstring(image.byteCount())
                ).digest()

        self.assertEqual(len(set(signatures.values())), len(signatures))

    def test_compiled_qt_icon_renders_at_windows_sizes(self):
        icon = QIcon(":/app")
        self.assertFalse(icon.isNull())
        for size in (16, 24, 32, 48, 64, 128, 256):
            with self.subTest(size=size):
                self.assertFalse(icon.pixmap(size, size).isNull())

    def test_generated_platform_assets_are_valid(self):
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
