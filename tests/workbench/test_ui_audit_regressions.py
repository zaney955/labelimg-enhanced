"""User-visible regressions found by the full workbench UI audit."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication, QDialogButtonBox, QLabel, QScrollArea, QMessageBox
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.localization.runtime import ENGLISH, set_language


class UiAuditRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": self.temp.name})
        self.environment.start()
        set_language(ENGLISH)
        classes = os.path.join(self.temp.name, "classes.txt")
        open(classes, "w").close()
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=classes))
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.deleteLater()
        self.window.stop_directory_load()
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def test_settings_switches_render_different_on_and_off_states(self):
        menu = self.window.menus.settings
        actions = (self.window.auto_saving, self.window.single_class_mode,
                   self.window.auto_update_check)
        images = []
        for checked in (False, True):
            for action in actions:
                action.setChecked(checked)
            menu.popup(QPoint(40, 40))
            self.app.processEvents()
            QTest.qWait(80)
            images.append(menu.grab(menu.actionGeometry(actions[0])).toImage())
            menu.hide()
        self.assertNotEqual(images[0], images[1], "Settings switches must visibly show their state")

    def test_menu_keeps_action_artwork_while_checkmark_changes(self):
        menu = self.window.menus.settings
        action = self.window.auto_saving
        self.assertFalse(action.icon().isNull())
        self.assertTrue(action.isIconVisibleInMenu())
        images = []
        for checked in (False, True):
            action.setChecked(checked)
            menu.popup(QPoint(40, 40))
            self.app.processEvents()
            row = menu.actionGeometry(action)
            images.append(menu.grab(row).toImage())
            menu.hide()
        # The shared menu reserves independent 20px check and icon columns.
        self.assertEqual(images[0].copy(28, 0, 20, images[0].height()),
                         images[1].copy(28, 0, 20, images[1].height()))
        self.assertNotEqual(images[0].copy(4, 0, 20, images[0].height()),
                            images[1].copy(4, 0, 20, images[1].height()))
        menu.popup(QPoint(40, 40))
        menu.setActiveAction(action)
        before = action.isChecked()
        QTest.keyClick(menu, Qt.Key_Return)
        self.assertEqual(action.isChecked(), not before)

    def test_dropdown_rows_have_readable_height_and_can_be_selected(self):
        from labelimg.ui.control_style import ComboBox as QComboBox
        combo = self.window.default_category_selector
        self.window.show()
        combo.showPopup()
        self.app.processEvents()
        view = combo.view()
        for row in range(combo.count()):
            rect = view.visualRect(combo.model().index(row, 0))
            self.assertGreaterEqual(rect.height(), max(32, combo.fontMetrics().height() + 12))
        QTest.mouseClick(view.viewport(), Qt.LeftButton,
                         pos=view.visualRect(combo.model().index(1, 0)).center())
        self.assertEqual(combo.currentIndex(), 1)
        combo.hidePopup()
        # A fresh editable combo uses the same popup delegate, including long labels.
        other = QComboBox(self.window)
        other.setEditable(True)
        other.addItems(['IPD_BTLY', 'Very long category name with spaces'])
        other.show()
        other.showPopup()
        self.app.processEvents()
        self.assertGreaterEqual(other.view().sizeHintForRow(0), 32)
        other.hidePopup()
        other.hide()
        other.deleteLater()
        self.app.processEvents()

    def test_preferences_action_buttons_are_content_sized(self):
        from PyQt5.QtWidgets import QPushButton
        from labelimg.workbench.preferences import PreferencesDialog
        dialog = PreferencesDialog(self.window)
        self.widgets.append(dialog)
        dialog.show()
        self.app.processEvents()
        for _key, _frame, controls in dialog.groups:
            for button, _action, _menu in controls:
                if isinstance(button, QPushButton):
                    self.assertLess(button.width(), button.parentWidget().width() * .85)

    def test_document_choice_input_uses_spaced_rows_and_returns_the_chosen_item(self):
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QComboBox
        from labelimg.ui.input_dialog import InputDialog
        heights = []
        def choose():
            dialog = self.app.activeModalWidget()
            combo = dialog.findChild(QComboBox)
            combo.showPopup()
            self.app.processEvents()
            heights.append(combo.view().sizeHintForRow(0))
            combo.hidePopup()
            combo.setCurrentIndex(1)
            dialog.accept()
        QTimer.singleShot(0, choose)
        value, accepted = InputDialog.getItem(self.window, 'Choose document', 'Document',
                                             ['sample.xml', 'sample.txt'], 0, False)
        self.assertTrue(accepted)
        self.assertEqual(value, 'sample.txt')
        self.assertGreaterEqual(heights[0], 32)
        QTimer.singleShot(0, lambda: self.app.activeModalWidget().reject())
        self.assertEqual(InputDialog.getItem(self.window, 'Choose document', 'Document',
                                            ['sample.xml', 'sample.txt'], 1, False), ('', False))

    def test_help_contains_no_tutorial_command(self):
        self.assertFalse(hasattr(self.window.actions, 'helpDefault'))
        self.assertFalse(any('tutorial' in action.text().lower()
                             for action in self.window.menus.help.actions()))

    def test_canceling_close_during_reset_keeps_settings_and_does_not_restart(self):
        self.window.settings['audit-sentinel'] = 'keep'
        self.window.settings.save()
        path = self.window.settings.path
        with open(path, 'rb') as stream:
            before = stream.read()
        with patch('labelimg.workbench.main_window.localized_question', return_value=QMessageBox.Yes), \
             patch.object(self.window, 'may_continue', return_value=False), \
             patch('PyQt5.QtCore.QProcess.startDetached') as restart:
            self.window.actions.resetAll.trigger()
        self.assertEqual(self.window.settings.get('audit-sentinel'), 'keep')
        self.assertEqual(self.window.settings.path, path)
        with open(path, 'rb') as stream:
            self.assertEqual(stream.read(), before)
        restart.assert_not_called()

    def test_shortcut_help_has_no_visible_unlaid_explanation_over_header(self):
        from labelimg.workbench.help_ui import ShortcutCatalogDialog
        dialog = ShortcutCatalogDialog(self.window)
        self.widgets.append(dialog)
        dialog.show()
        self.app.processEvents()
        overlaps = [label for label in dialog.findChildren(QLabel)
                    if label.isVisible() and label.parent() is dialog and label.pos() == QPoint(0, 0)]
        self.assertEqual(overlaps, [])

    def test_quality_form_fits_initial_window_without_two_axis_scrolling(self):
        from labelimg.image_tools.ui.quality_panel import ImageQualityDialog
        dialog = ImageQualityDialog('sample.png', (), ('sample.png',), self.window)
        self.widgets.append(dialog)
        dialog.show()
        self.app.processEvents()
        for area in dialog.findChildren(QScrollArea):
            self.assertEqual(area.horizontalScrollBar().maximum(), 0)
            self.assertEqual(area.verticalScrollBar().maximum(), 0)
        initial = dialog.height()
        dialog.custom_toggle.setChecked(True)
        self.app.processEvents()
        self.app.processEvents()
        self.assertGreater(dialog.height(), initial)
        for area in dialog.findChildren(QScrollArea):
            self.assertEqual(area.horizontalScrollBar().maximum(), 0)

    def test_category_confirmation_uses_the_shared_button_order(self):
        from labelimg.annotations.ui.candidate_label_dialog import CandidateLabelDialog
        dialog = CandidateLabelDialog(parent=self.window, list_item=['crack'])
        self.widgets.append(dialog)
        dialog.show()
        self.app.processEvents()
        buttons = dialog.button_box
        self.assertLess(buttons.button(QDialogButtonBox.Ok).x(),
                        buttons.button(QDialogButtonBox.Cancel).x())

    def test_default_category_displays_effective_reuse_strategy(self):
        self.window.single_class_mode.setChecked(True)
        selector = self.window.default_category_selector
        self.assertNotIn('each time', selector.currentText().lower())
        selector.activated[int].emit(0)
        self.assertFalse(self.window.single_class_mode.isChecked())

    def test_preferences_search_and_toggle_reuse_existing_action(self):
        from labelimg.workbench.preferences import PreferencesDialog, _ActionControl
        dialog = PreferencesDialog(self.window)
        self.widgets.append(dialog)
        dialog.show()
        dialog.search.setText('autosave')
        self.app.processEvents()
        visible = [box for box in dialog.findChildren(_ActionControl) if box.isVisible()]
        self.assertEqual(len(visible), 1)
        before = self.window.auto_saving.isChecked()
        visible[0].click()
        self.assertEqual(self.window.auto_saving.isChecked(), not before)
        self.window.auto_saving.trigger()
        self.assertEqual(visible[0].isChecked(), before)
        dialog.search.setText('no-such-setting')
        self.assertTrue(dialog.empty.isVisible())

    def test_autosave_button_names_its_current_state(self):
        self.window.resize(1800, 900)
        self.window.show()
        QTest.qWait(20)
        button = self.window.top_commands.auto_save_button
        self.window.auto_saving.setChecked(False)
        self.assertIn('Off', button.text())
        button.click()
        self.assertIn('On', button.text())
        self.assertEqual(button.toolButtonStyle(), Qt.ToolButtonTextBesideIcon)
        self.window.resize(1024, 720)
        self.window.ui_scale.set_percent(200)
        QTest.qWait(20)
        self.assertEqual(button.toolButtonStyle(), Qt.ToolButtonIconOnly)
        self.assertIn('On', button.accessibleName())
        self.assertTrue(button.isChecked())

    def test_restore_layout_preserves_preferences_and_restores_dock_positions(self):
        from PyQt5.QtWidgets import QDockWidget
        docks = self.window.findChildren(QDockWidget)
        before = [(dock, self.window.dockWidgetArea(dock), dock.isHidden()) for dock in docks]
        self.window.auto_saving.setChecked(True)
        for dock in docks:
            self.window.addDockWidget(Qt.LeftDockWidgetArea, dock)
            dock.setFloating(True)
            dock.hide()
        self.window.actions.restoreLayout.trigger()
        self.assertTrue(self.window.auto_saving.isChecked())
        for dock, area, hidden in before:
            self.assertEqual(self.window.dockWidgetArea(dock), area)
            self.assertFalse(dock.isFloating())
            self.assertEqual(dock.isHidden(), hidden)

    def test_color_hex_validation_restore_and_advanced_cancel(self):
        picker = self.window.color_dialog
        picker.setCurrentColor(QColor('#3878C8'))
        picker.hex_edit.setText('#BAD')
        self.assertFalse(picker.bb.button(QDialogButtonBox.Ok).isEnabled())
        picker.hex_edit.setText('#FF0022')
        self.assertEqual(picker.currentColor().name(), '#ff0022')
        picker.default = QColor('#123456')
        picker.check_restore(picker.bb.button(QDialogButtonBox.RestoreDefaults))
        self.assertEqual(picker.currentColor().name(), '#123456')
        with patch('labelimg.ui.color_dialog.QColorDialog.exec_', return_value=0):
            picker._more_colors()
        self.assertEqual(picker.currentColor().name(), '#123456')

    def test_quality_empty_state_offers_start_and_passed_results_are_distinct(self):
        from types import SimpleNamespace
        panel = self.window.image_quality_panel
        panel.clear()
        self.assertFalse(panel.start_button.isHidden())
        self.assertIn('No quality', panel.summary.text())
        panel.set_results([SimpleNamespace(path='example.png', findings=())])
        self.assertTrue(panel.start_button.isHidden())
        self.assertIn('passed', panel.summary.text())
        panel.set_failure('unavailable device')
        self.assertIn('unavailable device', panel.summary.toolTip())
        panel.clear()
        panel.set_failure('unavailable device')
        self.assertFalse(panel.start_button.isHidden())

    def test_declining_reset_retains_preferences_without_attempting_close(self):
        with patch('labelimg.workbench.main_window.localized_question', return_value=QMessageBox.No), \
             patch.object(self.window, 'close') as close:
            self.window.reset_all()
        close.assert_not_called()

    def test_accepted_reset_clears_settings_only_when_close_succeeds(self):
        self.window.settings['audit-sentinel'] = 'keep'
        self.window.settings.save()
        self.window.show()
        with patch('labelimg.workbench.main_window.localized_question', return_value=QMessageBox.Yes), \
             patch.object(self.window, 'may_continue', return_value=True), \
             patch('PyQt5.QtCore.QProcess.startDetached') as restart:
            self.window.reset_all()
        restart.assert_called_once()
        self.assertIsNone(self.window.settings.get('audit-sentinel'))

    def test_restore_appearance_is_previewed_and_cancel_preserves_original(self):
        from labelimg.ui.appearance import AppearanceDialog
        self.window.appearance.apply_preferences('dark', 'blue')
        dialog = AppearanceDialog(self.window.appearance, self.window)
        self.widgets.append(dialog)
        dialog.buttons.button(QDialogButtonBox.RestoreDefaults).click()
        self.assertEqual((self.window.appearance.mode, self.window.appearance.accent), ('light', 'plum'))
        dialog.reject()
        self.assertEqual((self.window.appearance.mode, self.window.appearance.accent), ('dark', 'blue'))
