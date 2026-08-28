import os
import tempfile
import unittest

from labelimg.image_tools.application.display_adjustment import (
    CanvasDisplayAdjustmentSession,
    DisplayAdjustmentValues,
    contrast_factor,
)


class CanvasDisplayAdjustmentSessionTest(unittest.TestCase):
    def setUp(self):
        self.session = CanvasDisplayAdjustmentSession()
        self.session.replace_workspace("workspace-a")
        self.first = os.path.join(tempfile.gettempdir(), "first.png")
        self.second = os.path.join(tempfile.gettempdir(), "second.png")

    def test_current_values_are_absolute_overrides(self):
        self.session.set_master(DisplayAdjustmentValues(60, 25))
        self.session.finish_master_gesture()
        self.session.set_override(self.first, DisplayAdjustmentValues(0, -20))

        self.assertEqual(
            self.session.effective(self.first),
            DisplayAdjustmentValues(0, -20),
        )
        self.assertEqual(
            self.session.effective(self.second),
            DisplayAdjustmentValues(60, 25),
        )

    def test_master_gesture_clears_overrides_and_can_restore_once(self):
        self.session.set_override(self.first, DisplayAdjustmentValues(5, 6))
        self.session.set_override(self.second, DisplayAdjustmentValues(7, 8))

        self.session.begin_master_gesture()
        self.assertEqual(
            self.session.set_master(DisplayAdjustmentValues(10, 0)), 2
        )
        self.session.set_master(DisplayAdjustmentValues(20, 0))
        self.assertEqual(self.session.finish_master_gesture(), 2)
        self.assertTrue(self.session.can_restore)
        self.assertTrue(self.session.restore_last_clear())
        self.assertEqual(
            self.session.effective(self.first), DisplayAdjustmentValues(5, 6)
        )
        self.assertFalse(self.session.restore_last_clear())

    def test_current_change_expires_clear_restore(self):
        self.session.set_override(self.first, DisplayAdjustmentValues(5, 0))
        self.session.set_master(DisplayAdjustmentValues(10, 0))
        self.session.finish_master_gesture()
        self.assertTrue(self.session.can_restore)

        self.session.set_override(self.second, DisplayAdjustmentValues(1, 1))

        self.assertFalse(self.session.can_restore)

    def test_master_change_clears_even_equal_absolute_override(self):
        values = DisplayAdjustmentValues(100, 100)
        self.session.set_master(values)
        self.session.finish_master_gesture()
        self.session.set_override(self.first, values)

        self.session.begin_master_gesture()
        self.assertEqual(self.session.set_master(values), 1)
        self.session.finish_master_gesture()

        self.assertFalse(self.session.has_override(self.first))
        self.assertEqual(self.session.effective(self.first), values)

    def test_rename_follows_and_source_replacement_clears_override(self):
        renamed = self.first + ".renamed"
        self.session.set_override(self.first, DisplayAdjustmentValues(12, 13))
        self.assertTrue(self.session.rename_paths({self.first: renamed}))
        self.assertFalse(self.session.has_override(self.first))
        self.assertTrue(self.session.has_override(renamed))

        self.assertEqual(self.session.source_pixels_replaced((renamed,)), 1)
        self.assertFalse(self.session.has_override(renamed))

    def test_observing_changed_source_token_clears_only_that_override(self):
        self.session.set_override(self.first, DisplayAdjustmentValues(12, 13))
        self.session.observe_source(self.first, (10, 100))
        self.assertFalse(self.session.observe_source(self.first, (10, 100)))

        self.assertTrue(self.session.observe_source(self.first, (11, 101)))
        self.assertFalse(self.session.has_override(self.first))

    def test_new_workspace_resets_values_but_same_workspace_does_not(self):
        self.session.set_master(DisplayAdjustmentValues(25, -25))
        self.session.finish_master_gesture()

        self.assertFalse(self.session.replace_workspace("workspace-a"))
        self.assertEqual(
            self.session.master, DisplayAdjustmentValues(25, -25)
        )
        self.assertTrue(self.session.replace_workspace("workspace-b"))
        self.assertEqual(self.session.master, DisplayAdjustmentValues())

    def test_slider_bounds_and_contrast_mapping(self):
        self.assertEqual(
            DisplayAdjustmentValues(200, -200),
            DisplayAdjustmentValues(100, -100),
        )
        self.assertAlmostEqual(contrast_factor(-100), 0.1)
        self.assertAlmostEqual(contrast_factor(0), 1.0)
        self.assertAlmostEqual(contrast_factor(100), 3.0)


if __name__ == "__main__":
    unittest.main()
