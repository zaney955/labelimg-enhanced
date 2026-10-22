"""Review commands stay attached to the viewport without intercepting drawing."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.ui.theme import COLORS, LIGHT_THEME, appearance_theme, set_theme
from labelimg.ui.theme_palettes import available_accents, contrast_ratio, blend
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class ReviewOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        self.environment = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": str(self.root / "config")})
        self.environment.start()
        (self.root / "labels").mkdir()
        classes = self.root / "labels/classes.txt"
        classes.write_text("cat\n", encoding="utf-8")
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes), save_dir=str(classes.parent)))
        self.window.auto_saving.setChecked(False)
        self.window.resize(1800, 900)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        self.controls = self.window.review_control
        self.viewport = self.window.scroll_area.viewport()

    def tearDown(self):
        self.window.auto_save_timer.stop()
        self.window.stop_directory_load()
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        set_language(ENGLISH)
        set_theme(LIGHT_THEME.identifier)
        self.environment.stop()
        self.temp.cleanup()

    def load_image(self):
        path = self.root / "image.png"
        image = QImage(1200, 1000, QImage.Format_RGB32)
        image.fill(QColor("#BAC9D8"))
        self.assertTrue(image.save(str(path)))
        self.assertTrue(self.window.load_file(str(path)))
        self.window.set_zoom(100)
        self.app.processEvents()
        for bar in self.window.scroll_bars.values():
            bar.setValue(0)
        self.app.processEvents()
        return path

    def assert_anchored(self):
        self.assertIs(self.controls.parentWidget(), self.viewport)
        self.assertEqual(self.controls.y(), 0)
        self.assertEqual(self.controls.x() + self.controls.width(), self.viewport.width())
        self.assertEqual(self.controls.ribbon.width(), self.viewport.width())
        self.assertEqual(self.controls.ribbon.height(), self.controls.height())
        self.assertEqual(self.controls.ribbon.pos(), QPoint())

    def test_no_image_hides_both_layers_and_removes_review_from_top_bar(self):
        self.assertFalse(self.controls.isVisible())
        self.assertFalse(self.controls.ribbon.isVisible())
        self.assertFalse(self.window.top_commands.isAncestorOf(self.controls))
        self.assertTrue(all(not action.isEnabled() for action in self.controls.actions.values()))
        self.load_image()
        self.assertTrue(self.controls.isVisible())
        self.assertTrue(self.controls.ribbon.isVisible())
        self.assert_anchored()
        self.controls.setEnabled(False)
        self.assertFalse(self.controls.isVisible())
        self.assertFalse(self.controls.ribbon.isVisible())

    def test_all_labels_and_button_positions_remain_stable_across_states(self):
        self.load_image()
        for language in (ENGLISH, SIMPLIFIED_CHINESE, ENGLISH):
            self.window.change_language(language)
            geometries = []
            for state in self.controls.actions:
                self.window.set_current_review_state(state)
                self.app.processEvents()
                geometries.append((self.controls.geometry(), tuple(button.geometry() for button in self.controls.buttons.values())))
                self.assertEqual(self.controls.state, state)
                for key, button in self.controls.buttons.items():
                    self.assertEqual(button.toolButtonStyle(), Qt.ToolButtonTextBesideIcon)
                    self.assertEqual(button.isChecked(), key == state)
                    self.assertTrue(button.accessibleName())
                    self.assertTrue(button.toolTip())
                    self.assertGreaterEqual(button.width(), button.sizeHint().width())
                self.assert_anchored()
            self.assertTrue(all(geometry == geometries[0] for geometry in geometries))

    def test_button_click_shortcut_and_undo_project_the_same_state(self):
        self.load_image()
        self.window.canvas.setFocus()
        QTest.mouseClick(self.controls.buttons['questioned'], Qt.LeftButton)
        self.assertNotIn(self.app.focusWidget(), self.controls.buttons.values())
        self.assertTrue(self.window.canvas.questioned)
        self.assertEqual(self.controls.state, 'questioned')
        self.window.canvas.setFocus()
        QTest.keyClick(self.window.canvas, Qt.Key_Space)
        self.assertTrue(self.window.canvas.verified)
        self.assertEqual(self.controls.state, 'verified')
        self.window.undo_annotation()
        self.assertTrue(self.window.canvas.questioned)
        self.assertEqual(self.controls.state, 'questioned')
        self.window.redo_annotation()
        self.assertEqual(self.controls.state, 'verified')

    def test_failed_review_request_retains_the_projected_selection(self):
        self.load_image()
        with patch.object(self.window, '_set_review_state'):
            QTest.mouseClick(self.controls.buttons['verified'], Qt.LeftButton)
        self.assertEqual(self.controls.state, 'unreviewed')
        self.assertTrue(self.controls.buttons['unreviewed'].isChecked())
        self.assertFalse(self.controls.buttons['verified'].isChecked())
        self.assertEqual(self.controls.ribbon_color.alpha(), 0)

    def test_resize_docking_zoom_and_scroll_do_not_move_controls_with_image(self):
        self.load_image()
        self.window.set_current_review_state('verified')
        for width in (1024, 1500, 1180):
            self.window.resize(width, 800)
            self.app.processEvents()
            self.assert_anchored()
        self.window.addDockWidget(Qt.TopDockWidgetArea, self.window.dock)
        self.window.resizeDocks([self.window.dock], [190], Qt.Vertical)
        self.app.processEvents()
        self.assert_anchored()
        position = self.controls.pos()
        self.window.set_zoom(200)
        self.app.processEvents()
        for bar in self.window.scroll_bars.values():
            bar.setValue(bar.maximum() // 2)
        self.app.processEvents()
        self.assert_anchored()
        self.assertEqual(self.controls.state, 'verified')
        # Scrollbars may change viewport width once, never its top alignment.
        self.assertEqual(self.controls.y(), position.y())

    def test_translucent_ribbon_passes_pointer_events_to_canvas(self):
        self.load_image()
        self.window.set_current_review_state('questioned')
        self.app.processEvents()
        point = QPoint(30, 12)
        global_point = self.viewport.mapToGlobal(point)
        target = QApplication.widgetAt(global_point)
        self.assertIs(target, self.window.canvas)
        canvas_point = self.window.canvas.mapFromGlobal(global_point)
        self.window.default_category_selector.set_fixed_label('cat')
        self.window.create_shape()
        QTest.mousePress(target, Qt.LeftButton, pos=canvas_point)
        self.assertIsNotNone(self.window.canvas.current)
        end = canvas_point + QPoint(90, 70)
        QApplication.sendEvent(target, QMouseEvent(QEvent.MouseMove, QPointF(end), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        QTest.mouseRelease(target, Qt.LeftButton, pos=end)
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertEqual(self.window.canvas.shapes[0].label, 'cat')

    def test_band_is_translucent_and_unreviewed_pixels_have_no_tint(self):
        self.load_image()
        self.window.resize(2400, 900)
        self.app.processEvents()
        point = QPoint(300, 10)
        self.controls.ribbon.hide()
        baseline = self.viewport.grab().toImage().pixelColor(point)
        self.controls.ribbon.show()
        self.assertEqual(self.viewport.grab().toImage().pixelColor(point), baseline)
        self.window.set_current_review_state('verified')
        painted = self.viewport.grab().toImage().pixelColor(point)
        self.assertNotEqual(painted, baseline)
        self.assertNotEqual(painted, QColor(COLORS['icon_success']))
        self.window.set_current_review_state('unreviewed')
        self.assertEqual(self.viewport.grab().toImage().pixelColor(point), baseline)

    def test_live_themes_keep_readability_and_leave_document_pixels_unchanged(self):
        self.load_image()
        pixels = self.window.canvas.pixmap.toImage()
        snapshot = self.window.annotation_scene.capture(self.window.file_path)
        for mode in ('light', 'dark'):
            for accent in available_accents():
                set_theme(appearance_theme(mode, accent.identifier).identifier)
                for state in self.controls.actions:
                    self.controls.set_state(state)
                    color = self.controls.ribbon_color
                    active, muted = self.controls._foregrounds()
                    for base in ('#000000', '#FFFFFF'):
                        background = blend(color.name(), blend(COLORS['surface'], base, 246 / 255), color.alphaF())
                        self.assertGreaterEqual(contrast_ratio(active, background), 4.5)
                        self.assertGreaterEqual(contrast_ratio(muted, background), 4.5)
                    self.assertEqual(color.alpha() == 0, state == 'unreviewed')
                    if state != 'unreviewed':
                        self.assertGreaterEqual(color.alphaF(), .2)
                    self.assertEqual(self.window.canvas.status_background_color(), QColor(COLORS['background']))
        self.assertEqual(self.window.canvas.pixmap.toImage(), pixels)
        self.assertEqual(self.window.annotation_scene.capture(self.window.file_path), snapshot)


if __name__ == '__main__':
    unittest.main()
