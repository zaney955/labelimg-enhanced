"""Review commands stay attached to the viewport without intercepting drawing."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QMouseEvent, QPalette
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.ui.theme import COLORS, LIGHT_THEME, appearance_theme, set_theme
from labelimg.ui.theme_palettes import available_accents, contrast_ratio, blend
from labelimg.ui.metrics import dp
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
        self.assertEqual(self.controls.ribbon.height(), self.controls.height() + dp(44))
        self.assertEqual(self.controls.ribbon.pos(), QPoint())

    def test_no_image_hides_both_layers_and_removes_review_from_top_bar(self):
        self.assertFalse(self.controls.isVisible())
        self.assertFalse(self.controls.ribbon.isVisible())
        self.assertFalse(self.window.top_commands.isAncestorOf(self.controls))
        self.assertTrue(all(not action.isEnabled() for action in self.controls.actions.values()))
        self.load_image()
        self.assertTrue(self.controls.isVisible())
        self.assertFalse(self.controls.ribbon.isVisible())
        self.window.set_current_review_state('verified')
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

    def test_draw_tool_hides_both_layers_before_first_corner_and_restores_on_exit(self):
        self.load_image()
        for state in self.controls.actions:
            for exit_tool in ('select', 'pan'):
                with self.subTest(state=state, exit_tool=exit_tool):
                    self.window.set_edit_mode()
                    self.window.set_current_review_state(state)
                    self.window.canvas.setFocus()
                    QTest.keyClick(self.window.canvas, Qt.Key_W)
                    self.app.processEvents()
                    self.assertTrue(self.window.canvas.drawing())
                    self.assertIsNone(self.window.canvas.current)
                    self.assertFalse(self.controls.isVisible())
                    self.assertFalse(self.controls.ribbon.isVisible())
                    self.assertEqual(self.controls.state, state)
                    button = self.window.tools.buttons[exit_tool]
                    QTest.mouseClick(button, Qt.LeftButton)
                    self.app.processEvents()
                    self.assertTrue(self.controls.isVisible())
                    self.assertEqual(self.controls.ribbon.isVisible(), state != 'unreviewed')
                    self.assertEqual(self.controls.state, state)

    def test_review_stays_hidden_through_drawing_and_initial_label_choice(self):
        self.load_image()
        self.window.set_current_review_state('questioned')
        self.window.canvas.setFocus()
        QTest.keyClick(self.window.canvas, Qt.Key_W)
        start = self.window.canvas.image_to_widget(QPointF(40, 50)).toPoint()
        end = self.window.canvas.image_to_widget(QPointF(180, 150)).toPoint()
        QTest.mousePress(self.window.canvas, Qt.LeftButton, pos=start)
        self.assertIsNotNone(self.window.canvas.current)
        self.assertFalse(self.controls.isVisible())
        self.assertFalse(self.controls.ribbon.isVisible())
        QApplication.sendEvent(self.window.canvas, QMouseEvent(
            QEvent.MouseMove, QPointF(end), Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        ))

        def choose_label(*_args, **_kwargs):
            self.assertIsNotNone(self.window.canvas._pending_label_shape)
            self.assertFalse(self.controls.isVisible())
            self.assertFalse(self.controls.ribbon.isVisible())
            return 'cat'

        with patch.object(self.window.candidate_label_dialog, 'choose', side_effect=choose_label) as dialog:
            QTest.mouseRelease(self.window.canvas, Qt.LeftButton, pos=end)
        dialog.assert_called_once()
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertTrue(self.window.canvas.editing())
        self.assertTrue(self.controls.isVisible())
        self.assertEqual(self.controls.ribbon.isVisible(), self.controls.state != 'unreviewed')
        QTest.keyClick(self.window.canvas, Qt.Key_W)
        QTest.mousePress(self.window.canvas, Qt.LeftButton, pos=start)
        QTest.keyClick(self.window.canvas, Qt.Key_Escape)
        self.assertTrue(self.window.canvas.editing())
        self.assertTrue(self.controls.isVisible())
        self.assertEqual(len(self.window.canvas.shapes), 1)

    def test_hidden_review_layers_survive_live_refreshes_and_image_availability(self):
        self.load_image()
        try:
            for language in (ENGLISH, SIMPLIFIED_CHINESE):
                for mode in ('light', 'dark'):
                    for percent in (100, 125, 150):
                        with self.subTest(language=language, mode=mode, percent=percent):
                            self.window.create_shape()
                            self.window.change_language(language)
                            self.window.appearance.apply_preferences(mode, 'plum')
                            self.window.ui_scale.set_percent(percent, persist=False)
                            self.window.resize(1024, 720)
                            self.controls.setEnabled(False)
                            self.controls.setEnabled(True)
                            self.controls.set_state('verified')
                            self.app.processEvents()
                            self.assertFalse(self.controls.isVisible())
                            self.assertFalse(self.controls.ribbon.isVisible())
                            self.window.set_edit_mode()
                            self.assertTrue(self.controls.isVisible())
                            self.assertTrue(self.controls.ribbon.isVisible())
            self.window.create_shape()
            self.controls.setEnabled(False)
            self.window.set_edit_mode()
            self.assertFalse(self.controls.isVisible())
            self.assertFalse(self.controls.ribbon.isVisible())
        finally:
            self.window.ui_scale.set_percent(100, persist=False)

    def test_selected_text_is_bolder_and_visibly_distinct_without_the_ribbon(self):
        self.load_image()
        for mode in ('light', 'dark'):
            for accent in available_accents():
                set_theme(appearance_theme(mode, accent.identifier).identifier)
                for state in self.controls.actions:
                    with self.subTest(mode=mode, accent=accent.identifier, state=state):
                        self.controls.set_state(state)
                        self.app.processEvents()
                        active = self.controls.buttons[state]
                        others = [button for key, button in self.controls.buttons.items() if key != state]
                        self.assertTrue(all(active.font().weight() > button.font().weight() for button in others))
                        if state != 'unreviewed':
                            selected = active.palette().color(QPalette.ButtonText)
                            self.assertGreaterEqual(selected.saturationF(), .45)
                            for other in others:
                                muted = other.palette().color(QPalette.ButtonText)
                                distance = sum((a-b)**2 for a, b in zip(selected.getRgb()[:3], muted.getRgb()[:3])) ** .5
                                self.assertGreaterEqual(distance, 75)

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
        canvas_point = self.window.canvas.image_to_widget(QPointF(40, 12)).toPoint()
        global_point = self.window.canvas.mapToGlobal(canvas_point)
        ribbon_point = self.controls.ribbon.mapFromGlobal(global_point)
        self.assertTrue(self.controls.ribbon.rect().contains(ribbon_point))
        target = QApplication.widgetAt(global_point)
        self.assertIs(target, self.window.canvas)
        self.window.default_category_selector.set_fixed_label('cat')
        self.window.create_shape()
        QTest.mousePress(target, Qt.LeftButton, pos=canvas_point)
        self.assertIsNotNone(self.window.canvas.current)
        end = canvas_point + QPoint(90, 70)
        QApplication.sendEvent(target, QMouseEvent(QEvent.MouseMove, QPointF(end), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        QTest.mouseRelease(target, Qt.LeftButton, pos=end)
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertEqual(self.window.canvas.shapes[0].label, 'cat')

    def test_status_ribbon_spans_width_and_fades_down_to_the_unmodified_image(self):
        self.load_image()
        self.window.resize(2400, 900)
        self.window.set_zoom(200)
        self.app.processEvents()
        for state in ('questioned', 'verified'):
            self.window.set_current_review_state(state)
            self.assertTrue(self.controls.ribbon.isVisible())
            self.controls.ribbon.hide()
            baseline = self.viewport.grab().toImage()
            self.controls.ribbon.show()
            painted = self.viewport.grab().toImage()
            height = self.controls.ribbon.height()
            for x in (30, self.viewport.width() // 2, self.viewport.width() - 5):
                # No labels at y=1, even at the right edge of the command row.
                self.assertNotEqual(painted.pixelColor(x, 1), baseline.pixelColor(x, 1))
                self.assertEqual(painted.pixelColor(x, height - 1), baseline.pixelColor(x, height - 1))
                self.assertEqual(painted.pixelColor(x, height + 1), baseline.pixelColor(x, height + 1))
            distance = lambda y: sum(abs(a-b) for a, b in zip(
                painted.pixelColor(30, y).getRgb()[:3], baseline.pixelColor(30, y).getRgb()[:3]))
            self.assertGreater(distance(self.controls.height()), distance(height - dp(12)))
            self.assertGreater(distance(height - dp(12)), 0)
            # Fade begins at the top; there is no solid block the height of
            # the command row across the canvas.
            self.assertGreater(distance(1), distance(self.controls.height() // 2) * 1.15)
            self.assertEqual(painted.pixelColor(30, 1), painted.pixelColor(self.viewport.width() // 2, 1))
            # The button group adds no separate surface to the shared gradient.
            # Its right padding has no text/icon or transient focus feedback.
            y = self.controls.height() // 2
            self.assertEqual(painted.pixelColor(30, y), painted.pixelColor(self.viewport.width() - 1, y))
        self.window.set_current_review_state('unreviewed')
        self.assertFalse(self.controls.ribbon.isVisible())
        self.assertTrue(self.controls.isVisible())
        self.assertEqual(self.viewport.grab().toImage().pixelColor(30, 1), baseline.pixelColor(30, 1))
        self.controls.setEnabled(False)
        self.controls.setEnabled(True)
        self.assertFalse(self.controls.ribbon.isVisible())
        self.controls.set_state('questioned')
        self.assertTrue(self.controls.ribbon.isVisible())
        self.controls.set_state('unreviewed')
        self.assertFalse(self.controls.ribbon.isVisible())

    def test_gradient_geometry_tracks_live_interface_scaling(self):
        self.load_image()
        self.window.set_current_review_state('verified')
        try:
            for percent in (100, 125, 150, 100):
                self.window.ui_scale.set_percent(percent)
                self.app.processEvents()
                self.assert_anchored()
                self.assertTrue(self.controls.ribbon.isVisible())
        finally:
            self.window.ui_scale.set_percent(100)

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
                    # The command group is transparent. Contrast is defined
                    # against the theme canvas, without assuming an opaque
                    # backing that would conceal arbitrary source-image pixels.
                    opacity = 210 / 255 * (1 - self.controls.height() / 2 / (self.controls.ribbon.height() - 1))
                    background = blend(blend(color.name(), COLORS['surface'], color.alphaF()), COLORS['background'], opacity) if color.alpha() else COLORS['background']
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
