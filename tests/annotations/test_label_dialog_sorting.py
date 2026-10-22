import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QRect, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QImage, QPainter, QPalette
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QStyle,
    QStyleOptionViewItem,
)

from labelimg.annotations.ui.candidate_label_dialog import (
    CandidateLabelDialog,
    CandidateLabelList,
)
from labelimg.annotations.ui.style import LABEL_INDICATOR_FILL_ALPHA, label_display_color
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language


class CandidateLabelDialogSortingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(ENGLISH)
        self.dialog = CandidateLabelDialog(
            list_item=["zebra", "apple", "middle"]
        )

    def tearDown(self):
        self.dialog.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        set_language(ENGLISH)

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

    def test_candidate_labels_use_natural_numeric_sorting(self):
        dialog = CandidateLabelDialog(list_item=["2", "10", "1"])
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(
            [
                dialog.list_widget.item(index).text()
                for index in range(dialog.list_widget.count())
            ],
            ["1", "2", "10"],
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

    def test_candidates_use_four_equal_width_columns_when_the_screen_allows(self):
        dialog = CandidateLabelDialog(
            list_item=["label-{}".format(index) for index in range(6)]
        )
        self.addCleanup(dialog.deleteLater)
        dialog.available_screen_geometry = lambda: QRect(0, 0, 1920, 1080)
        dialog.update_candidate_geometry()
        dialog.show()
        self.app.processEvents()

        first_row = [
            dialog.list_widget.visualItemRect(
                dialog.list_widget.item(index)
            )
            for index in range(4)
        ]
        last_item_rect = dialog.list_widget.visualItemRect(
            dialog.list_widget.item(4)
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

    def test_candidate_reuses_annotation_color_for_stripe_outline_and_light_fill(self):
        label = "apple"
        item = self.dialog.list_widget.item(0)
        background = item.data(Qt.BackgroundRole)

        self.assertEqual(background, label_display_color(label))
        self.assertEqual(background.alpha(), 255)
        self.assertEqual(
            item.data(Qt.ForegroundRole),
            self.dialog.palette().color(QPalette.Text),
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

        self.assertEqual(image.pixelColor(6, 15), background)
        # Away from text and border, match the annotation-list alpha-48 fill.
        expected = QColor(*(
            round(255 * (1 - LABEL_INDICATOR_FILL_ALPHA / 255)
                  + channel * LABEL_INDICATOR_FILL_ALPHA / 255)
            for channel in background.getRgb()[:3]
        ))
        self.assertEqual(image.pixelColor(113, 15), expected)
        edge = image.pixelColor(60, 3)
        self.assertNotEqual(edge, expected)
        self.assertNotEqual(edge, QColor("white"))

    def test_item_width_measures_the_longest_name_and_is_stable_while_filtering(self):
        labels = ["P_LS_LM2", "P_LS_LM10", "P_LS_LM123456789"]
        self.dialog.set_candidate_labels(labels)
        self.dialog.show()
        self.app.processEvents()
        before_size = self.dialog.size()
        before_grid = self.dialog.list_widget.gridSize()
        self.dialog.edit.setText("lm2")
        self.assertEqual(self.candidate_names(), ["P_LS_LM2"])
        self.assertEqual(self.dialog.size(), before_size)
        self.assertEqual(self.dialog.list_widget.gridSize(), before_grid)
        delegate = self.dialog.list_widget.itemDelegate()
        text_width = QFontMetrics(self.dialog.list_widget.font()).horizontalAdvance(max(labels, key=len))
        self.assertGreaterEqual(before_grid.width(), text_width + 2 * delegate.horizontal_padding)

    def test_live_filter_ranks_exact_prefix_then_contained_matches_naturally(self):
        labels = ["aLM10", "LM2", "LM10", "LM1", "zLM1", "other"]
        self.dialog.set_candidate_labels(labels)
        self.dialog.edit.setText("lm1")
        self.assertEqual(self.candidate_names(), ["LM1", "LM10", "aLM10", "zLM1"])
        self.dialog.list_item_click(self.dialog.list_widget.item(1))
        self.assertEqual(self.dialog.edit.text(), "LM10")
        self.assertEqual(self.dialog.list_widget.count(), 4)
        self.dialog.edit.clear()
        self.assertEqual(len(self.candidate_names()), len(labels))

    def test_color_refresh_preserves_full_candidate_pool_and_active_query(self):
        self.dialog.show()
        self.dialog.edit.setText("APP")
        self.assertEqual(self.candidate_names(), ["apple"])
        self.dialog.refresh_colors()
        self.assertEqual(self.dialog.edit.text(), "APP")
        self.assertEqual(self.candidate_names(), ["apple"])
        self.dialog.edit.clear()
        self.assertEqual(self.candidate_names(), ["apple", "middle", "zebra"])

    def test_no_match_preserves_new_name_without_creating_a_candidate(self):
        self.dialog.show()
        size = self.dialog.size()
        self.dialog.edit.setText("new-category")
        self.assertEqual(self.candidate_names(), [])
        self.assertIs(self.dialog.candidate_stack.currentWidget(), self.dialog.empty_label)
        self.assertEqual(self.dialog.size(), size)
        self.assertTrue(self.dialog.button_box.button(QDialogButtonBox.Ok).isEnabled())
        self.dialog.validate()
        self.assertEqual(self.dialog.result(), QDialog.Accepted)
        self.dialog.edit.clear()
        self.assertEqual(self.candidate_names(), ["apple", "middle", "zebra"])

    def test_keyboard_navigation_updates_the_draft_and_enter_confirms(self):
        self.dialog.show()
        self.dialog.edit.setFocus()
        QTest.keyClick(self.dialog.edit, Qt.Key_Down)
        self.assertEqual(self.dialog.edit.text(), "apple")
        QTest.keyClick(self.dialog.edit, Qt.Key_Down)
        self.assertEqual(self.dialog.edit.text(), "middle")
        self.assertEqual(self.dialog.list_widget.count(), 3)
        QTest.keyClick(self.dialog.edit, Qt.Key_Return)
        self.assertEqual(self.dialog.result(), QDialog.Accepted)

    def test_empty_name_cannot_confirm_and_escape_cancels(self):
        self.dialog.show()
        self.dialog.edit.setText(" ")
        self.assertFalse(self.dialog.button_box.button(QDialogButtonBox.Ok).isEnabled())
        self.dialog.validate()
        self.assertEqual(self.dialog.result(), QDialog.Rejected)
        QTest.keyClick(self.dialog.edit, Qt.Key_Escape)
        self.assertFalse(self.dialog.isVisible())

    def test_feedback_retranslates_and_help_button_is_absent(self):
        self.dialog.edit.setText("app")
        set_language(SIMPLIFIED_CHINESE)
        self.assertEqual(self.dialog.title_label.text(), "选择类别")
        self.assertEqual(self.dialog.count_label.text(), "1 / 3 个类别")
        self.assertEqual(self.dialog.edit.text(), "app")
        self.assertEqual(self.dialog.edit.placeholderText(), "输入或查找类别")
        self.assertFalse(self.dialog.windowFlags() & Qt.WindowContextHelpButtonHint)

    def test_body_places_candidates_before_footer_actions(self):
        self.dialog.show()
        self.app.processEvents()
        self.assertLess(self.dialog.edit.geometry().bottom(), self.dialog.candidate_stack.y())
        self.assertLess(self.dialog.candidate_stack.geometry().bottom(), self.dialog.button_box.y())

    def test_reopening_clears_previous_filter_and_prefills_without_narrowing_candidates(self):
        self.dialog.edit.setText("app")

        def accept():
            self.assertEqual(self.dialog.edit.text(), "middle")
            self.assertEqual(self.candidate_names(), ["apple", "middle", "zebra"])
            return QDialog.Accepted

        with patch.object(self.dialog, "exec_", side_effect=accept):
            self.assertEqual(self.dialog.choose("middle", move=False), "middle")
        with patch.object(self.dialog, "exec_", return_value=QDialog.Rejected):
            self.assertIsNone(self.dialog.choose("new-category", move=False))


if __name__ == "__main__":
    unittest.main()
