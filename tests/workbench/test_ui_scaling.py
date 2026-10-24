"""Application zoom changes the real workbench without changing image scale."""

import os
import tempfile
import unittest
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QSize, Qt
from PyQt5.QtGui import QImage, QColor, QFont, QFontDatabase, QFontMetrics, QKeyEvent, QKeySequence
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QFrame, QInputDialog, QLineEdit, QPushButton

from labelimg.ui.appearance import AppearanceDialog
from labelimg.ui.metrics import dp
from labelimg.platform.settings import Settings
from labelimg.platform.settings_keys import SETTING_UI_SCALE
from labelimg.workbench.preferences import PreferencesDialog
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE

from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class UiScalingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # The offscreen platform otherwise requests Helvetica on Windows, where
        # it is absent and Qt substitutes full-width missing-glyph boxes.
        font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
        if font_path.is_file():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            cls.app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 9))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": self.temporary.name})
        self.environment.start()
        self.window = create_workbench(WorkbenchLaunchOptions(class_file="", save_dir=""))
        self.window.resize(1200, 800)
        self.window.show()
        self.window.activateWindow()
        QTest.qWait(30)

    def tearDown(self):
        if hasattr(self.window, "ui_scale"):
            self.window.ui_scale.reset()
        self.window.stop_directory_load()
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()

    def settle_scale(self):
        # Wait for the transaction, rather than assuming a fixed number of
        # milliseconds while other test processes may be using the machine.
        for _ in range(200):
            self.app.processEvents()
            if not (self.window.ui_scale.command_timer.isActive()
                    or self.window.ui_scale.prepare_timer.isActive()
                    or self.window._ui_scale_binding.settle_timer.isActive()
                    or (getattr(self.window, '_fit_resize_timer', None) is not None
                        and self.window._fit_resize_timer.isActive())
                    or getattr(self.window, '_pending_manual_resize_anchor', None) is not None):
                return
            QTest.qWait(5)
        self.fail('Interface scale transaction did not settle')

    def test_global_shortcuts_work_without_an_image_and_reset_exact_geometry(self):
        baseline = self.window.tools.width()
        image_scale = self.window.zoom_widget.value()
        QTest.keyClick(self.window, Qt.Key_Equal, Qt.ControlModifier)
        QTest.qWait(20)
        self.assertEqual(self.window.ui_scale.percent, 110)
        self.assertGreater(self.window.tools.width(), baseline)
        self.assertEqual(self.window.zoom_widget.value(), image_scale)
        QTest.keyClick(self.window, Qt.Key_Minus, Qt.ControlModifier)
        QTest.keyClick(self.window, Qt.Key_0, Qt.ControlModifier)
        QTest.qWait(20)
        self.assertEqual(self.window.ui_scale.percent, 100)
        self.assertEqual(self.window.tools.width(), baseline)

    def test_shortcuts_only_rebind_styles_whose_scaled_dimensions_change(self):
        from labelimg.ui.theme import apply_theme_style

        color_only = QFrame(self.window)
        sized = QFrame(self.window)
        apply_theme_style(color_only, 'QFrame { color: ${text}; }')
        apply_theme_style(sized, 'QFrame { padding: 10px; color: ${text}; }')
        color_only.ensurePolished()
        sized.ensurePolished()
        color_only.show()
        sized.show()
        self.app.processEvents()
        with patch.object(color_only, 'setStyleSheet', wraps=color_only.setStyleSheet) as color_style, \
                patch.object(sized, 'setStyleSheet', wraps=sized.setStyleSheet) as sized_style:
            QTest.keyClick(self.window, Qt.Key_Equal, Qt.ControlModifier)
            self.app.processEvents()
            self.assertEqual(self.window.ui_scale.percent, 110)
            color_style.assert_not_called()
            self.assertEqual(sized_style.call_count, 1)
            self.assertIn('padding: 11px', sized.styleSheet())
            self.assertTrue(all(call.args[0] for call in sized_style.call_args_list))

    def test_reapplying_same_style_does_not_repolish_controls(self):
        from labelimg.ui.theme import apply_theme_style

        control = QFrame(self.window)
        style = 'QFrame { padding: 10px; color: ${text}; }'
        apply_theme_style(control, style)
        control.ensurePolished()
        with patch.object(control, 'setStyleSheet', wraps=control.setStyleSheet) as setter:
            apply_theme_style(control, style)
            setter.assert_not_called()

    def test_zoom_does_not_restyle_application_hidden_editors_or_window_root(self):
        dialog = AppearanceDialog(self.window.appearance, self.window)
        with patch.object(self.app, 'setStyleSheet', wraps=self.app.setStyleSheet) as app_style, \
                patch.object(self.window, 'setStyleSheet', wraps=self.window.setStyleSheet) as window_style, \
                patch.object(dialog, 'setStyleSheet', wraps=dialog.setStyleSheet) as dialog_style:
            QTest.keyClick(self.window, Qt.Key_Equal, Qt.ControlModifier)
            self.app.processEvents()
            self.assertEqual(self.window.ui_scale.percent, 110)
            app_style.assert_not_called()
            window_style.assert_not_called()
            dialog_style.assert_not_called()

    def test_hidden_and_parentless_dialogs_pick_up_latest_scale_on_show(self):
        dialog = AppearanceDialog(self.window.appearance, self.window)
        dialog.show()
        QTest.qWait(10)
        dialog.hide()
        self.window.ui_scale.set_percent(150)
        dialog.show()
        QTest.qWait(20)
        self.assertEqual(dialog.mode_caption.font().pixelSize(), 20)
        self.assertEqual(dialog.scale_control.combo.currentData(), 150)
        self.assertEqual(dialog.mode_buttons['light'].iconSize(), QSize(30, 30))
        for button in dialog.buttons.findChildren(QPushButton):
            self.assertEqual(button.font().pixelSize(), 20, button.text())
        parentless = QInputDialog()
        try:
            parentless.setLabelText('Input')
            parentless.show()
            QTest.qWait(20)
            self.assertEqual(parentless.findChild(QLineEdit).font().pixelSize(), 20)
        finally:
            parentless.close()
            parentless.deleteLater()

    def test_held_shortcut_combines_queued_repeats_without_losing_steps(self):
        changes = []
        self.window.ui_scale.changed.connect(changes.append)
        QTest.keyClick(self.window, Qt.Key_Equal, Qt.ControlModifier)
        changes.clear()
        for _ in range(3):
            QApplication.postEvent(self.window, QKeyEvent(
                QEvent.KeyPress, Qt.Key_Equal, Qt.ControlModifier, '=', True,
            ))
        self.settle_scale()
        self.assertEqual(self.window.ui_scale.percent, 175)
        self.assertEqual(changes, [175])
        for _ in range(2):
            QApplication.sendEvent(self.window, QKeyEvent(
                QEvent.KeyPress, Qt.Key_Minus, Qt.ControlModifier, '-', True,
            ))
        self.window.ui_scale.reset()
        QTest.qWait(10)
        self.assertEqual(self.window.ui_scale.percent, 100)

    def test_footer_magnifier_precedes_zoom_after_position_restore(self):
        bar = self.window.canvas_status
        row = bar.view_controls.layout()
        self.assertIs(row.itemAt(0).widget(), bar.magnifier_button)
        self.assertIs(row.itemAt(1).widget(), self.window.zoom_widget)
        self.window.ui_scale.set_percent(150)
        QTest.qWait(30)
        self.assertLess(bar.magnifier_button.geometry().right(), self.window.zoom_widget.geometry().left())

    def test_existing_and_new_modal_dialogs_share_scale_and_input_keeps_focus(self):
        dialog = AppearanceDialog(self.window.appearance, self.window)
        dialog.setModal(True)
        dialog.show()
        QTest.qWait(20)
        button = dialog.mode_buttons['light']
        self.window.ui_scale.set_percent(150)
        QTest.qWait(20)
        self.assertEqual(button.iconSize(), QSize(30, 30))
        self.assertGreaterEqual(button.height(), 57)
        self.assertEqual(dialog.scale_control.combo.currentData(), 150)
        QTest.keyClick(dialog, Qt.Key_0, Qt.ControlModifier)
        QTest.qWait(20)
        self.assertEqual(self.window.ui_scale.percent, 100)
        dialog.hide()
        self.window.ui_scale.set_percent(150)
        later = AppearanceDialog(self.window.appearance, self.window)
        later.show()
        QTest.qWait(20)
        self.assertEqual(later.mode_buttons['light'].iconSize(), QSize(30, 30))
        self.assertEqual(later.mode_buttons['light'].height(), button.height())
        later.hide()
        editor = PreferencesDialog(self.window)
        editor.show()
        editor.search.setText('zoom')
        editor.search.setFocus()
        QTest.keyClick(editor.search, Qt.Key_Minus, Qt.ControlModifier)
        QTest.qWait(20)
        self.assertEqual(self.window.ui_scale.percent, 125)
        self.assertEqual(editor.search.text(), 'zoom')
        self.assertIs(self.app.focusWidget(), editor.search)
        self.assertTrue(editor.scale_control.isVisible())

    def test_image_zoom_shortcuts_are_independent_and_fit_mode_survives_reflow(self):
        path = os.path.join(self.temporary.name, 'image.png')
        image = QImage(1800, 1200, QImage.Format_RGB32)
        image.fill(QColor('gray'))
        image.save(path)
        self.window.load_file(path)
        QTest.qWait(20)
        self.window.set_zoom(150)
        dirty = self.window.dirty
        center = self.window._capture_zoom_anchor()[0]
        self.window.ui_scale.set_percent(150)
        self.settle_scale()
        self.assertEqual(self.window.zoom_widget.value(), 150)
        self.assertEqual(self.window.dirty, dirty)
        restored = self.window._capture_zoom_anchor()[0]
        self.assertAlmostEqual(restored.x(), center.x(), delta=1)
        self.assertAlmostEqual(restored.y(), center.y(), delta=1)
        QTest.keyClick(self.window, Qt.Key_Equal, Qt.ControlModifier | Qt.AltModifier)
        QTest.qWait(20)
        self.assertAlmostEqual(self.window.zoom_widget.value(), 165)
        self.assertEqual(self.window.ui_scale.percent, 150)
        QTest.keyClick(self.window, Qt.Key_0, Qt.ControlModifier | Qt.AltModifier)
        QTest.qWait(30)
        self.assertEqual(self.window.zoom_mode, self.window.FIT_WINDOW)
        self.window.ui_scale.set_percent(200)
        self.settle_scale()
        self.assertEqual(self.window.zoom_mode, self.window.FIT_WINDOW)
        self.assertTrue(self.window.actions.fitWindow.isChecked())
        self.assertLessEqual(self.window.canvas.width(), self.window.scroll_area.viewport().width() + 2)

    def test_zoom_limits_persist_and_reset_does_not_restore_layout(self):
        self.window.file_dock.hide()
        self.window.ui_scale.set_percent(200)
        self.window.ui_scale.zoom_in()
        self.assertEqual(self.window.ui_scale.percent, 200)
        self.assertFalse(self.window.actions.uiZoomIn.isEnabled())
        saved = Settings()
        self.assertTrue(saved.load())
        self.assertEqual(saved[SETTING_UI_SCALE], 200)
        self.window.ui_scale.set_percent(75)
        self.window.ui_scale.zoom_out()
        self.assertEqual(self.window.ui_scale.percent, 75)
        self.assertFalse(self.window.actions.uiZoomOut.isEnabled())
        self.window.actions.uiZoomReset.trigger()
        QTest.qWait(20)
        self.assertFalse(self.window.file_dock.isVisible())
        self.assertEqual(self.window.ui_scale.percent, 100)

    def test_appearance_cancel_keeps_immediate_zoom_and_preferences_can_reset_it(self):
        original = (self.window.appearance.mode, self.window.appearance.accent)
        dialog = AppearanceDialog(self.window.appearance, self.window)
        dialog.show()
        dialog.scale_control.combo.setCurrentIndex(
            dialog.scale_control.combo.findData(175)
        )
        QTest.qWait(20)
        dialog.reject()
        self.assertEqual(self.window.ui_scale.percent, 175)
        self.assertEqual((self.window.appearance.mode, self.window.appearance.accent), original)
        saved = Settings()
        self.assertTrue(saved.load())
        self.assertEqual(saved[SETTING_UI_SCALE], 175)
        preferences = PreferencesDialog(self.window)
        preferences.show()
        preferences.scale_control.reset_button.click()
        self.assertEqual(self.window.ui_scale.percent, 100)
        self.assertEqual(dialog.scale_control.combo.currentData(), 100)

    def test_repeated_zoom_and_theme_language_switch_do_not_accumulate_sizes(self):
        header = self.window.dock.panel_header
        original = (self.window.tools.width(), header.height(), self.window.tools.buttons['select'].iconSize())
        for percent in (150, 75, 200, 125, 100, 175, 100):
            self.window.ui_scale.set_percent(percent)
            QTest.qWait(10)
        self.assertEqual((self.window.tools.width(), header.height(), self.window.tools.buttons['select'].iconSize()), original)
        self.window.ui_scale.set_percent(150)
        self.window.appearance.apply_preferences('dark', 'plum')
        self.window.change_language(SIMPLIFIED_CHINESE)
        QTest.qWait(20)
        self.assertEqual(self.window.actions.uiZoomIn.text(), '放大界面')
        self.assertEqual(header.height(), 57)
        self.assertGreaterEqual(self.window.label_list.row_height, 48)
        self.assertEqual(self.window.actions.zoomIn.shortcut(), QKeySequence('Ctrl+Alt+='))
        self.window.change_language(ENGLISH)

    def test_fractional_zoom_uses_pixel_fonts_and_new_controls_do_not_scale_twice(self):
        self.window.ui_scale.set_percent(150)
        dialog = AppearanceDialog(self.window.appearance, self.window)
        dialog.show()
        QTest.qWait(30)
        self.assertEqual(dialog.mode_caption.font().pixelSize(), 20)
        self.assertLess(dialog.scale_control.combo.minimumHeight(), 55)
        self.assertEqual(dialog.mode_buttons['light'].iconSize(), QSize(30, 30))

    def test_theme_changed_before_first_show_repaints_toolbar_at_every_zoom(self):
        from labelimg.ui.theme import COLORS
        other = create_workbench(WorkbenchLaunchOptions(class_file='', save_dir=''))
        try:
            other.appearance.apply_preferences('dark', 'plum')
            other.show()
            for percent in (100, 125, 150, 200, 100):
                other.ui_scale.set_percent(percent, persist=False)
                QTest.qWait(20)
                toolbar = other.top_commands
                color = toolbar.grab().toImage().pixelColor(toolbar.width() - 4, 2)
                self.assertEqual(color, QColor(COLORS['surface']), percent)
        finally:
            other.stop_directory_load()
            other.shutdown_image_decode_cache()
            other.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.window.ui_scale.attach(self.window, self.window.settings)

    def test_saved_zoom_restores_in_new_workbench_before_show(self):
        self.window.ui_scale.set_percent(150)
        other = create_workbench(WorkbenchLaunchOptions(class_file='', save_dir=''))
        try:
            self.assertEqual(other.ui_scale.percent, 150)
            self.assertEqual(other.tools.width(), 78)
            self.assertEqual(other.tools.buttons['select'].iconSize(), QSize(36, 36))
        finally:
            other.stop_directory_load()
            other.shutdown_image_decode_cache()
            other.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.window.ui_scale.attach(self.window, self.window.settings)

    def test_large_zoom_keeps_main_window_size_and_panel_footers_outside_scroll(self):
        self.window.change_language(ENGLISH)
        self.window.resize(1200, 800)
        self.window.ui_scale.set_percent(200)
        QTest.qWait(50)
        self.assertEqual(self.window.size(), QSize(1200, 800))
        panel = self.window.file_dock.widget()
        self.assertIsNotNone(panel._panel_scroll.widget())
        self.assertIsNot(self.window.file_selection_bar.parentWidget(), panel._panel_scroll.widget())

    def test_200_percent_remains_usable_at_supported_narrow_window(self):
        self.window.change_language(ENGLISH)
        self.window.resize(1024, 720)
        self.window.ui_scale.set_percent(200)
        QTest.qWait(60)
        self.assertEqual(self.window.size(), QSize(1024, 720))
        self.assertTrue(self.window.top_commands.save_button.isVisible())

    def test_large_zoom_keeps_review_command_names_readable_in_narrow_viewport(self):
        self.window.change_language(ENGLISH)
        self.window.resize(1200, 800)
        self.window.ui_scale.set_percent(200)
        QTest.qWait(30)
        controls = self.window.review_control
        for state, button in controls.buttons.items():
            font = QFont(button.font())
            font.setBold(True)
            text_width = QFontMetrics(font).horizontalAdvance(controls.actions[state].text())
            self.assertGreaterEqual(button.width(), text_width + button.iconSize().width())
            self.assertTrue(controls.rect().contains(button.geometry()))

    def test_crop_controls_remain_inside_canvas_at_large_interface_zoom(self):
        path = os.path.join(self.temporary.name, 'crop.png')
        image = QImage(1200, 900, QImage.Format_RGB32)
        image.fill(QColor('gray'))
        image.save(path)
        self.window.load_file(path)
        self.window.change_language(ENGLISH)
        self.window.ui_scale.set_percent(200)
        QTest.qWait(20)
        self.window.display_adjustment_overlay.open()
        self.window.tools.buttons['crop'].click()
        QTest.qWait(20)
        controls = self.window.crop_controls
        self.assertTrue(controls.isVisible())
        self.assertEqual(controls.layout().horizontalSpacing(), dp(6))
        self.assertFalse(self.window.review_control.isVisible())
        self.assertFalse(self.window.display_adjustment_overlay.button.isVisible())
        self.assertFalse(self.window.display_adjustment_overlay.panel_shell.isVisible())
        for width, height in ((1200, 800), (1024, 720)):
            self.window.resize(width, height)
            QTest.qWait(30)
            self.assertTrue(controls.parentWidget().rect().contains(controls.geometry()),
                            (controls.geometry(), controls.parentWidget().size()))
            for widget in (controls.apply_button, controls.cancel_button,
                           controls.ratio_combo, *controls.spins.values(), *controls.labels.values()):
                self.assertTrue(controls.rect().contains(widget.geometry()), widget.objectName())
            inputs = (controls.ratio_combo, *controls.spins.values(),
                      controls.apply_button, controls.cancel_button)
            for index, first in enumerate(inputs):
                for second in inputs[index + 1:]:
                    self.assertFalse(first.geometry().intersects(second.geometry()),
                                     (first.geometry(), second.geometry()))
        self.window.ui_scale.reset()
        self.window.resize(1600, 900)
        QTest.qWait(30)
        self.assertLess(controls.height(), 60)
        controls.cancel_button.click()
        self.assertTrue(self.window.review_control.isVisible())
        self.assertTrue(self.window.display_adjustment_overlay.button.isVisible())
        self.assertTrue(self.window.display_adjustment_overlay.panel_shell.isVisible())
        self.assertTrue(self.window.top_commands.auto_save_button.isVisible())

    def test_closed_application_is_collectible_before_python_shutdown(self):
        code = """
import gc, weakref
from labelimg.workbench.bootstrap import get_main_app
def exercise():
    app, window = get_main_app()
    window.appearance.apply_preferences('system', 'blue')
    window.close()
    app.quit()
    return weakref.ref(app)
reference = exercise()
gc.collect()
assert reference() is None, 'Closed QApplication retained by UI controllers'
"""
        result = subprocess.run(
            [sys.executable, '-X', 'faulthandler', '-B', '-c', code],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
