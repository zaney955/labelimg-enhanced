import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication

from labelimg.image_tools.application.display_adjustment import (
    DisplayAdjustmentValues,
)
from labelimg.image_tools.ui.display_adjustment import render_adjusted_image
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.canvas.shape import Shape
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class DisplayAdjustmentRenderingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_render_changes_rgb_and_preserves_alpha(self):
        image = QImage(2, 2, QImage.Format_RGBA8888)
        image.fill(QColor(100, 120, 140, 77))

        adjusted = render_adjusted_image(
            image, DisplayAdjustmentValues(20, 0)
        )

        pixel = adjusted.pixelColor(0, 0)
        self.assertEqual(pixel.alpha(), 77)
        self.assertGreater(pixel.red(), 100)
        self.assertGreater(pixel.green(), 120)
        self.assertGreater(pixel.blue(), 140)
        self.assertEqual(image.pixelColor(0, 0), QColor(100, 120, 140, 77))


class DisplayAdjustmentWorkbenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(ENGLISH)
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {"LABELIMG_CONFIG_DIR": self.temporary.name},
        )
        self.environment.start()
        classes_path = os.path.join(self.temporary.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=classes_path,
            save_dir="",
        ))
        self.window.show()
        self.app.processEvents()
        self.first = self._write_image("first.png", QColor(100, 100, 100))
        self.second = self._write_image("second.png", QColor(40, 40, 40))

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()
        set_language(ENGLISH)

    def _write_image(self, name, color):
        path = os.path.join(self.temporary.name, name)
        image = QImage(32, 24, QImage.Format_RGBA8888)
        image.fill(color)
        self.assertTrue(image.save(path))
        return path

    def _wait_until(self, condition, timeout=2.0):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTestWait.qwait(10)
        self.assertTrue(condition())

    def test_panel_is_a_left_dock_and_view_menu_action(self):
        self.assertEqual(
            self.window.dockWidgetArea(self.window.display_adjustment_dock),
            Qt.LeftDockWidgetArea,
        )
        self.assertIs(
            self.window.actions.displayAdjustment,
            self.window.display_adjustment_dock.toggleViewAction(),
        )
        self.assertIn(
            self.window.actions.displayAdjustment,
            self.window.menus.view.actions(),
        )
        self.assertGreaterEqual(self.window.display_adjustment_dock.width(), 180)
        self.assertLessEqual(self.window.display_adjustment_dock.width(), 360)
        self.assertFalse(self.window.display_adjustment_panel.master_frame.isEnabled())
        self.assertEqual(
            self.window.display_adjustment_panel.no_image_label.text(),
            "No image open",
        )

    def test_master_adjustment_changes_only_canvas_projection(self):
        before = Path(self.first).read_bytes()
        self.assertTrue(self.window.load_file(self.first))
        self.window.display_adjustment_panel.master_brightness.slider.setValue(50)

        self._wait_until(
            lambda: self.window.canvas.pixmap.toImage().pixelColor(0, 0).red()
            > 180
        )

        self.assertEqual(Path(self.first).read_bytes(), before)
        self.assertEqual(self.window.image.pixelColor(0, 0).red(), 100)
        self.assertFalse(self.window.dirty)
        self.assertTrue(self.window.display_adjustment_status.isVisible())

    def test_current_values_override_master_and_master_can_restore_clear(self):
        self.assertTrue(self.window.load_file(self.first))
        panel = self.window.display_adjustment_panel
        panel.master_brightness.slider.setValue(100)
        self.window.display_adjustment_controller.finish_master_gesture()
        panel.current_disclosure.setChecked(True)
        panel.current_brightness.slider.setValue(0)
        self.assertEqual(
            self.window.display_adjustment_session.effective(self.first),
            DisplayAdjustmentValues(0, 0),
        )
        self.assertEqual(
            panel.current_status.text(), "Individually Adjusted"
        )

        panel.master_brightness.slider.setValue(80)
        self.window.display_adjustment_controller.finish_master_gesture()
        self.assertFalse(
            self.window.display_adjustment_session.has_override(self.first)
        )
        self.assertTrue(panel.notice_frame.isVisible())

        panel.restore_button.click()
        self.assertEqual(
            self.window.display_adjustment_session.master,
            DisplayAdjustmentValues(100, 0),
        )
        self.assertEqual(
            self.window.display_adjustment_session.effective(self.first),
            DisplayAdjustmentValues(0, 0),
        )

    def test_current_override_follows_navigation_and_disclosure_stays_open(self):
        self.window.import_dir_images(self.temporary.name)
        panel = self.window.display_adjustment_panel
        panel.current_disclosure.setChecked(True)
        panel.current_brightness.slider.setValue(25)
        first_path = self.window.file_path

        self.window.open_next_image()
        self.assertTrue(panel.current_disclosure.isChecked())
        self.assertEqual(panel.current_brightness.value(), 0)

        self.window.open_prev_image()
        self.assertEqual(self.window.file_path, first_path)
        self.assertEqual(panel.current_brightness.value(), 25)
        self.assertEqual(
            panel.current_status.text(), "Individually Adjusted"
        )

    def test_hidden_panel_keeps_effect_and_status_reopens_it(self):
        self.assertTrue(self.window.load_file(self.first))
        panel = self.window.display_adjustment_panel
        panel.master_contrast.slider.setValue(20)
        self.window.display_adjustment_dock.hide()

        self.assertTrue(self.window.display_adjustment_session.has_adjustments)
        self.assertTrue(self.window.display_adjustment_status.isVisible())
        self.window.display_adjustment_status.click()
        self.assertTrue(self.window.display_adjustment_dock.isVisible())

    def test_source_replacement_clears_current_override_and_keeps_shapes(self):
        self.assertTrue(self.window.load_file(self.first))
        panel = self.window.display_adjustment_panel
        panel.master_brightness.slider.setValue(20)
        self.window.display_adjustment_controller.finish_master_gesture()
        panel.current_brightness.slider.setValue(-10)
        sentinel = Shape("box")
        self.window.canvas.shapes = [sentinel]
        replacement = QImage(32, 24, QImage.Format_RGBA8888)
        replacement.fill(QColor(20, 20, 20))
        self.assertTrue(replacement.save(self.first))

        self.assertTrue(
            self.window._refresh_current_image_pixels((self.first,))
        )

        self.assertFalse(
            self.window.display_adjustment_session.has_override(self.first)
        )
        self.assertEqual(
            self.window.display_adjustment_session.effective(self.first),
            DisplayAdjustmentValues(20, 0),
        )
        self.assertEqual(self.window.canvas.shapes, [sentinel])

    def test_canvas_pointer_gesture_temporarily_disables_controls(self):
        self.assertTrue(self.window.load_file(self.first))
        panel = self.window.display_adjustment_panel

        self.window.display_adjustment_controller.set_canvas_gesture_active(True)
        self.assertFalse(panel.master_frame.isEnabled())
        self.window.display_adjustment_controller.set_canvas_gesture_active(False)
        self.assertTrue(panel.master_frame.isEnabled())

    def test_live_language_updates_panel_action_and_accessible_names(self):
        self.assertTrue(self.window.load_file(self.first))
        panel = self.window.display_adjustment_panel
        panel.current_brightness.slider.setValue(12)
        panel.show_restore_notice(2)
        panel.show_render_error(self.first, "boom")
        set_language(SIMPLIFIED_CHINESE)
        self.window.retranslate_ui()

        self.assertEqual(self.window.display_adjustment_dock.windowTitle(), "显示调节")
        self.assertEqual(self.window.actions.displayAdjustment.text(), "显示调节")
        self.assertEqual(
            self.window.display_adjustment_panel.master_brightness.slider.accessibleName(),
            "亮度",
        )
        self.assertEqual(panel.current_status.text(), "单独调整")
        self.assertIn("2 张图像", panel.notice_label.text())
        self.assertIn("无法调节", panel.error_label.text())


class QTestWait:
    @staticmethod
    def qwait(milliseconds):
        from PyQt5.QtTest import QTest

        QTest.qWait(milliseconds)


if __name__ == "__main__":
    unittest.main()
