"""Native chart, counts, live language and workspace statistics entry."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QDialog

from labelimg.annotations.application.statistics import AnnotationStatistics, CategoryCount, StatisticsCanceled
from labelimg.annotations.ui.statistics_dialog import AnnotationStatisticsDialog
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class AnnotationStatisticsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(ENGLISH)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("images", "labels", "config"):
            (self.root / name).mkdir()
        self.env = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": str(self.root / "config")})
        self.env.start()
        self.images, self.labels = self.root / "images", self.root / "labels"
        (self.labels / "classes.txt").write_text("cat\ndog\nunused\n")
        image = QImage(80, 60, QImage.Format_RGB32)
        image.fill(Qt.white)
        for name in ("a.png", "b.png", "c.png", "missing.png"):
            image.save(str(self.images / name))
        for name, lines in (("a.txt", "0 .5 .5 .2 .2\n" * 2), ("b.txt", "0 .5 .5 .2 .2\n" * 3), ("c.txt", "1 .5 .5 .2 .2\n" * 10)):
            (self.labels / name).write_text(lines)
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=str(self.labels / "classes.txt"), save_dir=str(self.labels)))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.deleteLater()
        self.window.auto_save_timer.stop()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.env.stop()
        self.temp.cleanup()
        set_language(ENGLISH)

    def result(self):
        return AnnotationStatistics((CategoryCount("dog", 10, 1), CategoryCount("cat", 5, 2)), 4, 3, 0, 1, 0, ())

    def dialog(self, result=None, collect=None):
        dialog = AnnotationStatisticsDialog(collect or (lambda _progress: result or self.result()), image_dir=str(self.images), annotation_dir=str(self.labels), color_for_label=self.window.label_color_palette.color, parent=self.window)
        self.dialogs.append(dialog)
        return dialog

    def test_tools_entry_is_secondary_and_becomes_available_for_a_workspace(self):
        action = self.window.actions.annotationStatistics
        self.assertIn(action, self.window.menus.tools.actions())
        self.assertFalse(action.isEnabled())
        self.assertTrue(action.shortcut().isEmpty())
        self.assertFalse(action.icon().isNull())
        self.window.import_dir_images(str(self.images))
        self.assertTrue(action.isEnabled())

    def test_chart_and_table_show_box_counts_and_distinct_image_counts(self):
        dialog = self.dialog()
        dialog.refresh()
        self.assertEqual([(row.label, row.boxes, row.images) for row in dialog.chart.rows], [("dog", 10, 1), ("cat", 5, 2)])
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertEqual(dialog.table.item(0, 0).text(), "dog")
        self.assertEqual(dialog.table.item(0, 3).text(), "66.7%")
        self.assertIn("15 boxes", dialog.summary.text())
        dialog.metric.setCurrentIndex(1)
        self.assertEqual([row.label for row in dialog.chart.rows], ["cat", "dog"])
        self.assertEqual(dialog.chart.metric, "images")

    def test_filter_changes_chart_and_table_without_changing_totals(self):
        dialog = self.dialog()
        dialog.refresh()
        dialog.search.setText("CAT")
        self.assertEqual([row.label for row in dialog.chart.rows], ["cat"])
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertIn("15 boxes", dialog.summary.text())
        self.assertEqual(dialog.table.item(0, 3).text(), "33.3%")
        dialog.search.setText("not found")
        self.assertEqual(dialog.chart.rows, ())
        self.assertEqual(dialog.table.rowCount(), 0)

    def test_numeric_sort_does_not_sort_ten_before_two(self):
        result = AnnotationStatistics((CategoryCount("two", 2, 1), CategoryCount("ten", 10, 1)), 2, 2, 0, 0, 0, ())
        dialog = self.dialog(result)
        dialog.refresh()
        dialog.table.sortItems(1, Qt.AscendingOrder)
        self.assertEqual([dialog.table.item(row, 1).text() for row in range(2)], ["2", "10"])

    def test_live_language_switch_preserves_chart_filter_and_metric(self):
        dialog = self.dialog()
        dialog.refresh()
        dialog.search.setText("cat")
        dialog.metric.setCurrentIndex(1)
        self.window.change_language(SIMPLIFIED_CHINESE)
        self.assertEqual(self.window.actions.annotationStatistics.text(), "标注统计…")
        self.assertEqual(dialog.windowTitle(), "标注统计…")
        self.assertEqual(dialog.metric.currentText(), "包含该类别的图像数")
        self.assertEqual([row.label for row in dialog.chart.rows], ["cat"])
        self.assertIn("15 个标注框", dialog.summary.text())

    def test_cancel_statistics_discards_the_previous_result(self):
        dialog = self.dialog()
        dialog.refresh()
        self.assertIsNotNone(dialog.statistics)
        def cancel(_progress):
            raise StatisticsCanceled()
        dialog._collect = cancel
        dialog.refresh()
        self.assertIsNone(dialog.statistics)
        self.assertEqual(dialog.chart.rows, ())
        self.assertIn("canceled", dialog.summary.text())

    def test_many_categories_are_scrollable_and_paint_as_a_chart(self):
        result = AnnotationStatistics(tuple(CategoryCount("category-%d" % index, index + 1, 1) for index in range(60)), 60, 60, 0, 0, 0, ())
        dialog = self.dialog(result)
        dialog.show()
        dialog.refresh()
        self.app.processEvents()
        scroll = dialog.tabs.widget(0)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        self.assertFalse(dialog.chart.grab().isNull())

    def test_workspace_command_counts_filtered_out_images_without_saving(self):
        self.window.import_dir_images(str(self.images))
        self.window.file_list_controls.search_edit.setText("a.png")
        before = {path.name: path.read_bytes() for path in self.labels.iterdir()}
        observed = []
        def show(dialog):
            self.assertTrue(self.window.annotation_editing.pending)
            self.assertFalse(self.window.auto_save_timer.isActive())
            dialog.refresh()
            observed.append(dialog.statistics)
            return QDialog.Rejected
        with patch.object(AnnotationStatisticsDialog, "exec_", show):
            self.window.show_annotation_statistics()
        self.assertEqual(observed[0].total_images, 4)
        self.assertEqual(observed[0].total_boxes, 15)
        self.assertEqual(len(observed[0].categories), 2)
        self.assertFalse(self.window.annotation_editing.pending)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.labels.iterdir()})

    def test_statistics_entry_refuses_to_interrupt_a_pending_drawing(self):
        self.window.import_dir_images(str(self.images))
        self.window.create_shape()
        from PyQt5.QtCore import QPointF
        self.window.canvas.handle_drawing(QPointF(10, 10))
        with patch.object(AnnotationStatisticsDialog, "exec_") as show:
            self.window.show_annotation_statistics()
        show.assert_not_called()
        self.assertTrue(self.window.annotation_editing.edit_open)
        self.window.undo_annotation()


if __name__ == "__main__":
    unittest.main()
