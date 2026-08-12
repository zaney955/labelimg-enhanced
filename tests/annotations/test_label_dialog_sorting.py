import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QStyle,
    QStyleOptionViewItem,
)

from labelimg.annotations.ui.candidate_label_dialog import (
    CandidateLabelDialog,
    CandidateLabelList,
    contrast_text_color,
)
from labelimg.annotations.ui.style import label_display_color


class CandidateLabelDialogSortingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = CandidateLabelDialog(
            list_item=["zebra", "apple", "middle"]
        )

    def tearDown(self):
        self.dialog.deleteLater()
        self.app.processEvents()

    def candidate_names(self):
        return [
            self.dialog.list_widget.item(index).text()
            for index in range(self.dialog.list_widget.count())
        ]

    def test_candidate_labels_are_sorted_by_name(self):
        self.assertEqual(
            self.candidate_names(),
            ["apple", "middle", "zebra"],
        )

    def test_candidate_labels_update_in_place(self):
        dialog_identity = id(self.dialog)

        self.dialog.set_candidate_labels(["pear", "banana"])

        self.assertEqual(id(self.dialog), dialog_identity)
        self.assertEqual(self.candidate_names(), ["banana", "pear"])

    def test_candidate_labels_keep_qt_default_text_sorting(self):
        dialog = CandidateLabelDialog(list_item=["2", "10", "1"])
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(
            [
                dialog.list_widget.item(index).text()
                for index in range(dialog.list_widget.count())
            ],
            ["1", "10", "2"],
        )

    def test_clicking_a_sorted_candidate_updates_the_label_text(self):
        first_candidate = self.dialog.list_widget.item(0)

        self.dialog.list_item_click(first_candidate)

        self.assertEqual(self.dialog.edit.text(), "apple")
        self.assertIs(
            self.dialog.list_widget.currentItem(),
            first_candidate,
        )

    def test_double_clicking_a_candidate_accepts_the_dialog(self):
        first_candidate = self.dialog.list_widget.item(0)

        self.dialog.list_item_double_click(first_candidate)

        self.assertEqual(self.dialog.result(), QDialog.Accepted)
        self.assertEqual(self.dialog.edit.text(), "apple")

    def test_candidates_use_five_equal_width_columns(self):
        dialog = CandidateLabelDialog(
            list_item=["label-{}".format(index) for index in range(6)]
        )
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        first_row = [
            dialog.list_widget.visualItemRect(
                dialog.list_widget.item(index)
            )
            for index in range(5)
        ]
        last_item_rect = dialog.list_widget.visualItemRect(
            dialog.list_widget.item(5)
        )

        self.assertTrue(all(rect.y() == first_row[0].y() for rect in first_row))
        self.assertTrue(
            all(rect.width() == first_row[0].width() for rect in first_row)
        )
        self.assertGreater(last_item_rect.y(), first_row[0].y())
        self.assertEqual(last_item_rect.x(), first_row[0].x())
        self.assertEqual(
            dialog.list_widget.gridSize().height(),
            CandidateLabelList.cell_height,
        )

    def test_candidate_width_adapts_and_is_capped_at_eighty_percent(self):
        short_dialog = CandidateLabelDialog(list_item=["a"])
        long_dialog = CandidateLabelDialog(
            list_item=["a very long label name"] * 5
        )
        extreme_dialog = CandidateLabelDialog(
            list_item=["x" * 1000] * 5
        )
        self.addCleanup(short_dialog.deleteLater)
        self.addCleanup(long_dialog.deleteLater)
        self.addCleanup(extreme_dialog.deleteLater)

        self.assertGreater(
            long_dialog.list_widget.width(),
            short_dialog.list_widget.width(),
        )
        maximum_width = int(
            extreme_dialog.available_screen_geometry().width()
            * extreme_dialog.maximum_screen_width_ratio
        )
        self.assertLessEqual(extreme_dialog.width(), maximum_width)
        self.assertEqual(
            extreme_dialog.list_widget.horizontalScrollBarPolicy(),
            Qt.ScrollBarAlwaysOff,
        )

    def test_candidate_height_shows_all_rows_until_screen_limit(self):
        small_dialog = CandidateLabelDialog(
            list_item=["label-{}".format(index) for index in range(10)]
        )
        large_dialog = CandidateLabelDialog(
            list_item=["label-{}".format(index) for index in range(500)]
        )
        self.addCleanup(small_dialog.deleteLater)
        self.addCleanup(large_dialog.deleteLater)
        small_dialog.show()
        large_dialog.show()
        self.app.processEvents()

        self.assertEqual(
            small_dialog.list_widget.height(),
            small_dialog.list_widget.natural_height,
        )
        self.assertEqual(
            small_dialog.list_widget.verticalScrollBar().maximum(),
            0,
        )
        maximum_height = int(
            large_dialog.available_screen_geometry().height()
            * large_dialog.maximum_screen_height_ratio
        )
        self.assertLessEqual(large_dialog.height(), maximum_height)
        self.assertGreater(
            large_dialog.list_widget.verticalScrollBar().maximum(),
            0,
        )

    def test_capsule_reuses_annotation_color_and_full_name_tooltip(self):
        label = "apple"
        item = self.dialog.list_widget.item(0)
        background = item.data(Qt.BackgroundRole)
        base = self.dialog.list_widget.palette().base().color()

        self.assertEqual(background, label_display_color(label))
        self.assertEqual(background.alpha(), 255)
        self.assertEqual(
            item.data(Qt.ForegroundRole),
            contrast_text_color(background, base),
        )
        self.assertEqual(item.toolTip(), label)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 120, 30)
        option.state = QStyle.State_Enabled
        option.widget = self.dialog.list_widget
        image = QImage(120, 30, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        self.dialog.list_widget.itemDelegate().paint(
            painter,
            option,
            self.dialog.list_widget.model().index(0, 0),
        )
        painter.end()

        self.assertEqual(image.pixelColor(12, 15), background)


if __name__ == "__main__":
    unittest.main()
