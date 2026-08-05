import os
import sys
import unittest
from labelimg.utils import (
    Struct,
    add_actions,
    format_shortcut,
    generate_color_by_text,
    label_display_color,
    natural_sort,
    new_action,
    new_icon,
)

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

    def test_nautalSort_noError(self):
        l1 = ['f1', 'f11', 'f3']
        expected_l1 = ['f1', 'f3', 'f11']
        natural_sort(l1)
        for idx, val in enumerate(l1):
            self.assertTrue(val == expected_l1[idx])

if __name__ == '__main__':
    unittest.main()
