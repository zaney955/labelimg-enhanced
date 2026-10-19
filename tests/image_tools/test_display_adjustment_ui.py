import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QAction, QApplication, QWidget

from labelimg.image_tools.application.display_adjustment import (
    DisplayAdjustmentValues,
)
from labelimg.image_tools.ui.display_adjustment import (
    DisplayAdjustmentOverlay,
    DisplayAdjustmentPanel,
    render_adjusted_image,
)
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

    def test_preview_render_stays_bounded_instead_of_expanding_to_source(self):
        image = QImage(400, 200, QImage.Format_RGBA8888)
        image.fill(QColor(100, 120, 140, 255))

        adjusted = render_adjusted_image(
            image,
            DisplayAdjustmentValues(20, 0),
            max_pixels=10_000,
        )

        self.assertLessEqual(adjusted.width() * adjusted.height(), 10_000)
        self.assertLess(adjusted.width(), image.width())
        self.assertLess(adjusted.height(), image.height())


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

    def test_panel_is_a_disabled_canvas_overlay_without_an_image(self):
        overlay = self.window.display_adjustment_overlay
        button = overlay.button

        self.assertIs(button.parentWidget(), self.window.scroll_area.viewport())
        self.assertIs(
            overlay.panel_shell.parentWidget(),
            self.window.scroll_area.viewport(),
        )
        self.assertFalse(overlay.panel_shell.isVisible())
        self.assertFalse(button.isEnabled())
        self.assertFalse(self.window.actions.displayAdjustment.isEnabled())
        self.assertFalse(self.window.actions.displayAdjustment.isCheckable())
        self.assertIn(
            self.window.actions.displayAdjustment,
            self.window.menus.view.actions(),
        )
        self.assertFalse(self.window.display_adjustment_panel.master_frame.isEnabled())
        self.assertEqual(
            button.toolTip(),
            "No image open",
        )
        self.assertEqual(button.x(), 12)
        self.assertEqual(
            button.y(),
            self.window.scroll_area.viewport().height() - 48,
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
        self.assertEqual(
            self.window.display_adjustment_overlay.button._status,
            "active",
        )

    def test_adjusted_navigation_uses_bounded_pixels_with_full_canvas_geometry(self):
        self.window.import_dir_images(self.temporary.name)
        self.window.display_adjustment_panel.master_brightness.slider.setValue(20)
        self.window.display_adjustment_controller.finish_master_gesture()
        with patch(
            "labelimg.image_tools.ui.display_adjustment.PREVIEW_MAX_PIXELS",
            100,
        ):
            self.window.open_next_image()

        self.assertLessEqual(
            self.window.canvas.pixmap.width()
            * self.window.canvas.pixmap.height(),
            100,
        )
        self.assertEqual(
            self.window.canvas.pixmap_size,
            self.window.image.size(),
        )
        snapshot = self.window.annotation_scene.capture(self.window.file_path)
        self.assertEqual(snapshot.image_size, (32, 24))

    def test_adjacent_navigation_uses_prefetched_decode(self):
        self.window.import_dir_images(self.temporary.name)
        target = self.window._adjacent_visible_file(1)
        self.assertIsNotNone(target)
        cache = self.window._ensure_image_decode_cache()
        self._wait_until(lambda: cache.get(target) is not None)

        with patch(
            "labelimg.workbench.main_window.read",
            side_effect=AssertionError("prefetched image should avoid decoding"),
        ):
            self.window.open_next_image()

        self.assertEqual(self.window.file_path, target)

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
        self.assertTrue(panel.current_disclosure.is_adjusted)
        self.assertTrue(panel.reset_current_button.isEnabled())

        panel.master_brightness.slider.setValue(80)
        self.window.display_adjustment_controller.finish_master_gesture()
        self.assertFalse(
            self.window.display_adjustment_session.has_override(self.first)
        )
        self.assertFalse(panel.notice_frame.isHidden())

        panel.restore_button.click()
        self.assertEqual(
            self.window.display_adjustment_session.master,
            DisplayAdjustmentValues(100, 0),
        )
        self.assertEqual(
            self.window.display_adjustment_session.effective(self.first),
            DisplayAdjustmentValues(0, 0),
        )

    def test_visible_reset_buttons_reset_their_own_scope(self):
        self.assertTrue(self.window.load_file(self.first))
        panel = self.window.display_adjustment_panel
        panel.master_brightness.slider.setValue(25)
        self.window.display_adjustment_controller.finish_master_gesture()
        panel.current_brightness.slider.setValue(-10)

        self.assertFalse(panel.reset_all_button.icon().isNull())
        self.assertFalse(panel.reset_current_button.icon().isNull())
        self.assertEqual(panel.reset_all_button.text(), "")
        self.assertEqual(panel.reset_current_button.text(), "")
        self.assertTrue(panel.reset_current_button.isEnabled())
        panel.reset_current_button.click()
        self.assertFalse(
            self.window.display_adjustment_session.has_override(self.first)
        )
        self.assertEqual(
            self.window.display_adjustment_session.effective(self.first),
            DisplayAdjustmentValues(25, 0),
        )
        self.assertFalse(panel.reset_current_button.isEnabled())

        panel.reset_all_button.click()
        self.assertEqual(
            self.window.display_adjustment_session.master,
            DisplayAdjustmentValues(),
        )

    def test_scope_headings_align_and_reset_actions_are_icon_only(self):
        self.assertTrue(self.window.load_file(self.first))
        panel = self.window.display_adjustment_panel
        panel.current_disclosure.setChecked(True)
        panel.adjustSize()
        QApplication.processEvents()

        master_x = panel.master_title.mapTo(panel, QPoint(0, 0)).x()
        current_x = panel.current_disclosure.mapTo(panel, QPoint(0, 0)).x()
        self.assertEqual(master_x, current_x)
        self.assertEqual(
            panel.master_title.height(), panel.current_disclosure.height()
        )
        for button in (panel.reset_all_button, panel.reset_current_button):
            self.assertEqual(button.text(), "")
            self.assertFalse(button.icon().isNull())
            self.assertEqual((button.width(), button.height()), (28, 28))
            self.assertTrue(button.accessibleName())

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
        self.assertTrue(panel.current_disclosure.is_adjusted)

    def test_new_workspace_closes_panel_and_collapses_current_section(self):
        self.assertTrue(self.window.load_file(self.first))
        panel = self.window.display_adjustment_panel
        overlay = self.window.display_adjustment_overlay
        overlay.button.click()
        panel.current_disclosure.setChecked(True)

        self.window.display_adjustment_controller.replace_workspace(
            "another-workspace"
        )

        self.assertFalse(overlay.panel_shell.isVisible())
        self.assertFalse(overlay.button.isChecked())
        self.assertFalse(panel.current_disclosure.isChecked())

    def test_only_floating_button_closes_panel_and_menu_only_opens(self):
        self.assertTrue(self.window.load_file(self.first))
        panel = self.window.display_adjustment_panel
        overlay = self.window.display_adjustment_overlay
        button = overlay.button
        button.click()
        self.assertTrue(overlay.panel_shell.isVisible())
        panel.master_contrast.slider.setValue(20)
        button.click()

        self.assertTrue(self.window.display_adjustment_session.has_adjustments)
        self.assertFalse(overlay.panel_shell.isVisible())
        self.assertEqual(button._status, "active")
        self.window.actions.displayAdjustment.trigger()
        self.assertTrue(overlay.panel_shell.isVisible())
        self.window.actions.displayAdjustment.trigger()
        self.assertTrue(overlay.panel_shell.isVisible())
        button.click()
        self.assertFalse(overlay.panel_shell.isVisible())

    def test_overlay_stays_bounded_and_ignores_outside_click_and_escape(self):
        viewport = QWidget()
        viewport.resize(320, 240)
        viewport.show()
        panel = DisplayAdjustmentPanel()
        action = QAction(viewport)
        overlay = DisplayAdjustmentOverlay(
            viewport, panel, action, viewport
        )
        panel.project(
            DisplayAdjustmentValues(),
            DisplayAdjustmentValues(),
            has_override=False,
            has_image=True,
        )
        overlay.button.click()
        panel.current_disclosure.setChecked(True)
        self.app.processEvents()

        self.assertEqual(overlay.button.pos(), QPoint(12, 192))
        self.assertEqual(overlay.panel_shell.x(), 12)
        self.assertEqual(overlay.panel_shell.width(), 248)
        self.assertGreaterEqual(overlay.panel_shell.y(), 8)
        self.assertLessEqual(
            overlay.panel_shell.y() + overlay.panel_shell.height(),
            overlay.button.y() - 8,
        )
        self.assertGreater(
            overlay.scroller.verticalScrollBar().maximum(), 0
        )

        QTest.mouseClick(viewport, Qt.LeftButton, pos=QPoint(300, 20))
        QTest.keyClick(viewport, Qt.Key_Escape)

        self.assertTrue(overlay.panel_shell.isVisible())
        self.assertTrue(overlay.button.isChecked())
        viewport.close()
        viewport.deleteLater()

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
        self.assertFalse(panel.reset_current_button.isEnabled())
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

        self.assertEqual(self.window.actions.displayAdjustment.text(), "显示调节")
        self.assertEqual(
            self.window.display_adjustment_overlay.button.accessibleName(),
            "显示调节",
        )
        self.assertEqual(
            self.window.display_adjustment_panel.master_brightness.slider.accessibleName(),
            "亮度",
        )
        self.assertEqual(panel.master_title.text(), "所有图像")
        self.assertEqual(panel.current_disclosure.text(), "当前图像")
        self.assertEqual(panel.reset_all_button.text(), "")
        self.assertEqual(panel.reset_current_button.text(), "")
        self.assertEqual(panel.reset_all_button.toolTip(), "重置所有图像")
        self.assertEqual(panel.reset_current_button.toolTip(), "重置当前图像")
        self.assertTrue(panel.current_disclosure.is_adjusted)
        self.assertIn("2 张图像", panel.notice_label.text())
        self.assertIn("无法调节", panel.error_label.text())


class QTestWait:
    @staticmethod
    def qwait(milliseconds):
        from PyQt5.QtTest import QTest

        QTest.qWait(milliseconds)


if __name__ == "__main__":
    unittest.main()
