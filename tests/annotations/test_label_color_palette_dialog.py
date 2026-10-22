import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication, QColorDialog, QMessageBox

from labelimg.annotations.ui.label_color_palette_dialog import (
    LabelColorPaletteDialog,
)
from labelimg.annotations.ui.style import LabelColorPalette
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.ui.color_dialog import ColorDialog


class _StubColorDialog:
    def __init__(self, color):
        self.color = QColor(color)
        self.calls = []

    def getColor(self, value=None, title=None, default=None):
        self.calls.append((QColor(value), title, QColor(default)))
        return QColor(self.color)


class LabelColorPaletteDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(ENGLISH)
        self.palette = LabelColorPalette()
        self.palette.set_color("unused", QColor("red"))
        self.color_dialog = _StubColorDialog(QColor(12, 34, 56))
        self.dialog = LabelColorPaletteDialog(
            ("cat",),
            self.palette,
            self.color_dialog,
        )

    def tearDown(self):
        self.dialog.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        set_language(ENGLISH)

    def test_lists_current_and_retained_unused_labels_without_mutating_palette(self):
        self.assertEqual(
            [
                self.dialog.table.item(row, 0).text()
                for row in range(self.dialog.table.rowCount())
            ],
            ["cat", "unused"],
        )
        self.assertFalse(self.dialog.table.item(0, 1).icon().isNull())
        self.dialog.table.selectRow(0)

        self.dialog.choose_selected_color()

        self.assertEqual(
            self.dialog.overrides["cat"],
            QColor(12, 34, 56, 255),
        )
        self.assertIsNone(self.palette.override("cat"))

    def test_restore_is_staged_and_language_updates_accessibly(self):
        self.dialog.table.selectRow(1)
        self.dialog.restore_selected_color()

        self.assertNotIn("unused", self.dialog.overrides)
        self.assertEqual(self.palette.override("unused"), QColor("red"))

        set_language(SIMPLIFIED_CHINESE)
        self.assertEqual(self.dialog.windowTitle(), "管理标签颜色")
        self.assertEqual(self.dialog.choose_button.text(), "修改颜色")

    def test_restore_all_is_confirmed_and_staged(self):
        with patch.object(
            QMessageBox,
            "exec_",
            return_value=QMessageBox.Yes,
        ):
            self.dialog.restore_all_colors()

        self.assertEqual(self.dialog.overrides, {})
        self.assertEqual(self.palette.override("unused"), QColor("red"))

    def test_search_preserves_staged_colors_across_language_and_row_rebuild(self):
        self.dialog.table.selectRow(0)
        self.dialog.choose_selected_color()
        self.dialog.search.setText("CAT")
        self.assertFalse(self.dialog.table.isRowHidden(0))
        self.assertTrue(self.dialog.table.isRowHidden(1))
        set_language(SIMPLIFIED_CHINESE)
        self.assertEqual(self.dialog.search.text(), "CAT")
        self.assertTrue(self.dialog.table.isRowHidden(1))
        self.assertEqual(self.dialog.overrides["cat"], QColor(12, 34, 56, 255))
        self.dialog.search.setText("not a category")
        self.assertFalse(self.dialog.choose_button.isEnabled())
        self.dialog.search.clear()
        self.assertTrue(all(not self.dialog.table.isRowHidden(row) for row in range(2)))

    def test_palette_color_dialog_hides_alpha_channel(self):
        dialog = ColorDialog()
        try:
            self.assertFalse(dialog.testOption(QColorDialog.ShowAlphaChannel))
        finally:
            dialog.deleteLater()

    def test_selected_row_keeps_the_actual_category_color_visible(self):
        self.dialog.show()
        self.dialog.table.selectRow(0)
        self.app.processEvents()
        table = self.dialog.table
        item = table.item(0, 1)
        rect = table.visualItemRect(item)
        rendered = table.viewport().grab().toImage()
        self.assertEqual(rendered.pixelColor(rect.right() - 4, rect.top() + 4),
                         item.background().color())


if __name__ == "__main__":
    unittest.main()
