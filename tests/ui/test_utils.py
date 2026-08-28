import os
import sys
import unittest
from PyQt5.QtGui import QColor

from labelimg.annotations.ui.style import (
    generate_color_by_text,
    LabelColorPalette,
    label_display_color,
)
from labelimg.files.model import natural_sort

class TestUtils(unittest.TestCase):

    def test_generateColorByGivingUniceText_noError(self):
        res = generate_color_by_text(u'\u958B\u555F\u76EE\u9304')
        self.assertTrue(res.green() >= 0)
        self.assertTrue(res.red() >= 0)
        self.assertTrue(res.blue() >= 0)

    def test_label_display_color_is_opaque_without_changing_source_color(self):
        source = generate_color_by_text("apple")
        display = label_display_color("apple")

        self.assertEqual(display.getRgb()[:3], source.getRgb()[:3])
        self.assertEqual(display.alpha(), 255)
        self.assertEqual(source.alpha(), 100)

    def test_session_palette_uses_exact_label_overrides_and_opaque_colors(self):
        palette = LabelColorPalette()
        automatic = palette.color("cat")

        self.assertTrue(palette.set_color("cat", QColor(1, 2, 3, 40)))
        self.assertEqual(palette.color("cat"), QColor(1, 2, 3, 255))
        self.assertEqual(palette.color("Cat"), label_display_color("Cat"))
        self.assertNotEqual(palette.color("cat"), automatic)

        returned = palette.color("cat")
        returned.setRed(200)
        self.assertEqual(palette.color("cat"), QColor(1, 2, 3, 255))

    def test_session_palette_restore_replace_and_clear(self):
        palette = LabelColorPalette()
        palette.set_color("cat", QColor("red"))
        palette.set_color("dog", QColor("blue"))

        self.assertEqual(palette.labels, ("cat", "dog"))
        self.assertTrue(palette.restore("cat"))
        self.assertIsNone(palette.override("cat"))
        self.assertTrue(palette.replace({"bird": QColor("green")}))
        self.assertEqual(palette.labels, ("bird",))
        self.assertTrue(palette.clear())
        self.assertFalse(palette.clear())

    def test_nautalSort_noError(self):
        l1 = ['f1', 'f11', 'f3']
        expected_l1 = ['f1', 'f3', 'f11']
        natural_sort(l1)
        for idx, val in enumerate(l1):
            self.assertTrue(val == expected_l1[idx])

if __name__ == '__main__':
    unittest.main()
