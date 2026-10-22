"""Shared presentation preserves values, decisions, and runtime language."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QScreen
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
)

from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.ui.color_dialog import ColorDialog
from labelimg.ui.presentation import present_dialog, present_table, section


class PresentationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        set_language(ENGLISH)

    def test_dialog_shell_preserves_input_state_and_disabled_commit(self):
        dialog = QDialog()
        self.widgets.append(dialog)
        dialog.setWindowTitle("Preview")
        layout = QVBoxLayout(dialog)
        entry = QLineEdit("a genuine category")
        combo = QComboBox()
        combo.addItem("Selected images", "selected")
        layout.addWidget(entry)
        layout.addWidget(combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        commit = buttons.button(QDialogButtonBox.Ok)
        commit.setEnabled(False)
        layout.addWidget(buttons)
        present_dialog(dialog, primary=commit, scroll=True)
        present_dialog(dialog, primary=commit, scroll=True)
        self.assertEqual(entry.text(), "a genuine category")
        self.assertEqual(combo.currentData(), "selected")
        self.assertFalse(commit.isEnabled())
        self.assertEqual(commit.property("uiRole"), "primary")
        headings = [
            label
            for label in dialog.findChildren(QLabel)
            if label.property("uiRole") == "heading"
        ]
        self.assertEqual(len(headings), 1)
        dialog.setWindowTitle("Updated title")
        self.assertEqual(headings[0].text(), "Updated title")
        dialog.show()
        self.app.processEvents()
        self.assertTrue(buttons.isVisible())

    def test_path_column_retains_identity_and_has_room_for_filename(self):
        dialog = QDialog()
        self.widgets.append(dialog)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(1, 2)
        path = "H:/images/" + "long-directory/" * 4 + "different-target.png"
        item = QTableWidgetItem(path)
        item.setData(Qt.UserRole, "document identity")
        table.setItem(0, 0, item)
        choices = QComboBox()
        choices.addItems(("Choose…", "Save", "Discard"))
        table.setCellWidget(0, 1, choices)
        layout.addWidget(table)
        dialog.resize(700, 300)
        present_dialog(dialog)
        present_table(table, path_columns=(0,), stretch_path=True)
        dialog.show()
        self.app.processEvents()
        self.assertGreater(table.columnWidth(0), table.columnWidth(1))
        self.assertEqual(item.text(), path)
        self.assertEqual(item.toolTip(), path)
        self.assertEqual(item.data(Qt.UserRole), "document identity")
        self.assertEqual(choices.currentIndex(), 0)

    def test_small_desktop_keeps_nested_footer_visible_and_body_reachable(self):
        dialog = QDialog()
        self.widgets.append(dialog)
        layout = QVBoxLayout(dialog)
        for number in range(24):
            layout.addWidget(QLineEdit(f"Value {number}"))
        footer = QHBoxLayout()
        footer.addWidget(QPushButton("Undo preview"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        dialog.resize(900, 1200)
        present_dialog(dialog, scroll=True)
        with patch.object(
            QScreen, "availableGeometry", return_value=QRect(0, 0, 800, 600)
        ):
            dialog.show()
            self.app.processEvents()
        self.assertLessEqual(dialog.width(), 776)
        self.assertLessEqual(dialog.height(), 576)
        scroller = dialog.findChild(QScrollArea)
        self.assertFalse(scroller.isAncestorOf(buttons))
        self.assertLessEqual(
            buttons.mapTo(dialog, QPoint()).y() + buttons.height(), dialog.height()
        )
        last = scroller.findChildren(QLineEdit)[-1]
        scroller.ensureWidgetVisible(last)
        self.app.processEvents()
        self.assertGreater(scroller.verticalScrollBar().value(), 0)
        self.assertTrue(
            scroller.viewport()
            .rect()
            .contains(last.mapTo(scroller.viewport(), last.rect().center()))
        )
        self.assertEqual(last.text(), "Value 23")

    def test_sections_retranslate_without_changing_user_text(self):
        set_language(SIMPLIFIED_CHINESE)
        value = QLineEdit("裂纹.keep-exact-text")
        frame = section("ui.section.parameters", value)
        self.widgets.append(frame)
        title = next(
            label
            for label in frame.findChildren(QLabel)
            if label.property("uiRole") == "sectionTitle"
        )
        self.assertEqual(title.text(), "参数设置")
        set_language(ENGLISH)
        self.assertEqual(title.text(), "Parameters")
        self.assertEqual(value.text(), "裂纹.keep-exact-text")

    def test_color_picker_translates_qt_owned_labels_live(self):
        set_language(SIMPLIFIED_CHINESE)
        picker = ColorDialog(show_alpha=True)
        self.widgets.append(picker)
        picker.setCurrentColor(QColor(12, 34, 56, 78))
        texts = lambda: {
            widget.text()
            for widget in picker.findChildren(QLabel) + picker.findChildren(QPushButton)
        }
        self.assertIn("基本颜色(&B)", texts())
        self.assertIn("拾取屏幕颜色(&P)", texts())
        set_language(ENGLISH)
        self.app.processEvents()
        self.assertIn("&Basic colors", texts())
        self.assertIn("&Pick Screen Color", texts())
        self.assertEqual(picker.currentColor().getRgb(), (12, 34, 56, 78))


if __name__ == "__main__":
    unittest.main()
