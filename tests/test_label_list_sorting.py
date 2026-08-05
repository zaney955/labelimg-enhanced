import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, QRect, Qt
from PyQt5.QtGui import QColor, QImage, QMouseEvent, QPainter, QPalette
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from labelimg.app import (
    LabelListItemDelegate,
    LabelListWidget,
    MainWindow,
)
from labelimg.shape import Shape
from labelimg.utils import label_display_color


class LabelListSortingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        classes_path = os.path.join(self.temp_dir.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass

        self.window = MainWindow(default_prefdef_class_file=classes_path)

    def tearDown(self):
        self.window.deleteLater()
        self.app.processEvents()
        self.temp_dir.cleanup()

    def label_names(self):
        return [
            self.window.label_list.item(index).text()
            for index in range(self.window.label_list.count())
        ]

    def render_first_item(self, selected, checked=True):
        item = self.window.label_list.item(0)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 180, 30)
        option.state = QStyle.State_Enabled
        if selected:
            option.state |= QStyle.State_Selected
        option.widget = self.window.label_list

        image = QImage(180, 30, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        self.window.label_list.itemDelegate().paint(
            painter,
            option,
            self.window.label_list.model().index(0, 0),
        )
        painter.end()
        return image

    @staticmethod
    def icon_strength(image, background):
        return max(
            abs(color.red() - background.red())
            + abs(color.green() - background.green())
            + abs(color.blue() - background.blue())
            for color in (
                image.pixelColor(x, y)
                for x in range(156, 180)
                for y in range(4, 26)
            )
        )

    def test_labels_are_sorted_by_name_when_added(self):
        for label in ("zebra", "apple", "middle"):
            self.window.add_label(Shape(label=label))

        self.assertEqual(self.label_names(), ["apple", "middle", "zebra"])

    def test_label_row_uses_the_opaque_label_display_color(self):
        self.window.add_label(Shape(label="apple"))

        background = self.window.label_list.item(0).background().color()

        self.assertEqual(background, label_display_color("apple"))
        self.assertEqual(background.alpha(), 255)
        self.assertEqual(
            self.render_first_item(selected=False).pixelColor(140, 15),
            background,
        )

    def test_labels_are_resorted_after_renaming(self):
        for label in ("apple", "middle", "zebra"):
            self.window.add_label(Shape(label=label))

        self.window.label_list.item(2).setText("aardvark")

        self.assertEqual(self.label_names(), ["aardvark", "apple", "middle"])

    def test_selected_label_keeps_background_and_uses_theme_marker(self):
        self.window.add_label(Shape(label="apple"))
        item = self.window.label_list.item(0)
        item.setBackground(QColor(210, 160, 90))

        unselected_image = self.render_first_item(selected=False)
        selected_image = self.render_first_item(selected=True)
        theme_color = self.window.label_list.palette().highlight().color()

        self.assertEqual(
            selected_image.pixelColor(140, 15),
            unselected_image.pixelColor(140, 15),
        )
        self.assertEqual(
            selected_image.pixelColor(1, 15),
            theme_color,
        )
        self.assertEqual(
            selected_image.pixelColor(1, 1),
            unselected_image.pixelColor(1, 1),
        )
        self.assertEqual(
            selected_image.pixelColor(90, 1),
            unselected_image.pixelColor(90, 1),
        )

    def test_selected_label_text_is_bold(self):
        self.window.add_label(Shape(label="apple"))
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 180, 30)
        option.state = QStyle.State_Enabled | QStyle.State_Selected
        option.widget = self.window.label_list

        image = QImage(180, 30, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        with patch.object(QStyledItemDelegate, "paint") as base_paint:
            self.window.label_list.itemDelegate().paint(
                painter,
                option,
                self.window.label_list.model().index(0, 0),
            )
        painter.end()

        painted_option = base_paint.call_args.args[1]
        self.assertTrue(painted_option.font.bold())

    def test_row_hover_keeps_background_and_draws_neutral_gray_border(self):
        self.window.add_label(Shape(label="apple"))
        item = self.window.label_list.item(0)
        background = QColor(210, 160, 90)
        item.setBackground(background)

        unhovered = self.render_first_item(selected=False)
        self.window.label_list.set_projected_hover_item(item)
        hovered = self.render_first_item(selected=False)

        self.assertEqual(
            hovered.pixelColor(90, 15),
            unhovered.pixelColor(90, 15),
        )
        self.assertNotEqual(
            hovered.pixelColor(90, 1),
            unhovered.pixelColor(90, 1),
        )
        border = hovered.pixelColor(90, 1)
        expected = self.window.label_list.palette().color(QPalette.Mid)
        before_border = unhovered.pixelColor(90, 1)
        self.assertLess(
            sum(abs(a - e) for a, e in zip(
                border.getRgb()[:3], expected.getRgb()[:3]
            )),
            sum(abs(a - e) for a, e in zip(
                before_border.getRgb()[:3], expected.getRgb()[:3]
            )),
        )

    def test_native_mouse_over_never_recolors_or_bolds_row(self):
        self.window.add_label(Shape(label="apple"))
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 180, 30)
        option.state = QStyle.State_Enabled | QStyle.State_MouseOver
        option.widget = self.window.label_list
        image = QImage(180, 30, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)

        with patch.object(QStyledItemDelegate, "paint") as base_paint:
            self.window.label_list.itemDelegate().paint(
                painter,
                option,
                self.window.label_list.model().index(0, 0),
            )
        painter.end()

        painted_option = base_paint.call_args.args[1]
        self.assertFalse(painted_option.state & QStyle.State_MouseOver)
        self.assertFalse(painted_option.font.bold())

    def test_selected_hovered_row_keeps_selection_marker_and_bold_text(self):
        self.window.add_label(Shape(label="apple"))
        item = self.window.label_list.item(0)
        self.window.label_list.set_projected_hover_item(item)

        image = self.render_first_item(selected=True)

        self.assertEqual(
            image.pixelColor(1, 15),
            self.window.label_list.palette().highlight().color(),
        )

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 180, 30)
        option.state = QStyle.State_Enabled | QStyle.State_Selected
        option.widget = self.window.label_list
        paint_image = QImage(180, 30, QImage.Format_ARGB32)
        painter = QPainter(paint_image)
        with patch.object(QStyledItemDelegate, "paint") as base_paint:
            self.window.label_list.itemDelegate().paint(
                painter,
                option,
                self.window.label_list.model().index(0, 0),
            )
        painter.end()
        self.assertTrue(base_paint.call_args.args[1].font.bold())

    def test_visibility_indicator_moves_right_and_reserves_text_space(self):
        self.window.add_label(Shape(label="a very long annotation label"))
        item = self.window.label_list.item(0)
        background = QColor(210, 160, 90)
        item.setBackground(background)
        index = self.window.label_list.model().index(0, 0)

        style_option = QStyleOptionViewItem()
        self.window.label_list.itemDelegate().initStyleOption(
            style_option,
            index,
        )
        self.assertFalse(
            style_option.features & QStyleOptionViewItem.HasCheckIndicator
        )

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 180, 30)
        option.state = QStyle.State_Enabled
        option.widget = self.window.label_list
        image = QImage(180, 30, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        with patch.object(QStyledItemDelegate, "paint") as base_paint:
            self.window.label_list.itemDelegate().paint(
                painter,
                option,
                index,
            )
        painter.end()

        painted_option = base_paint.call_args.args[1]
        self.assertEqual(
            painted_option.rect.right(),
            option.rect.right() - 24,
        )

        visible_image = self.render_first_item(selected=False, checked=True)
        self.assertGreater(self.icon_strength(visible_image, background), 0)

    def test_hidden_eye_is_distinct_and_dimmed_until_hovered(self):
        self.window.add_label(Shape(label="apple"))
        item = self.window.label_list.item(0)
        background = QColor(210, 160, 90)
        item.setBackground(background)

        visible_image = self.render_first_item(selected=False, checked=True)
        hidden_image = self.render_first_item(selected=False, checked=False)
        visible_strength = self.icon_strength(visible_image, background)
        hidden_strength = self.icon_strength(hidden_image, background)

        self.assertNotEqual(visible_image, hidden_image)
        self.assertGreater(hidden_strength, 0)
        self.assertLess(hidden_strength, visible_strength)

        self.window.label_list.resize(180, 60)
        self.window.label_list.show()
        self.app.processEvents()
        index = self.window.label_list.model().index(0, 0)
        icon_rect = self.window.label_list.visibility_rect(index)
        self.window.label_list.mouseMoveEvent(
            QMouseEvent(
                QEvent.MouseMove,
                QPointF(icon_rect.center()),
                Qt.NoButton,
                Qt.NoButton,
                Qt.NoModifier,
            )
        )
        self.app.processEvents()

        hovered_image = self.render_first_item(
            selected=False,
            checked=False,
        )
        self.assertGreater(
            self.icon_strength(hovered_image, background),
            visible_strength,
        )

    def test_visibility_eye_click_does_not_change_selection(self):
        label_list = LabelListWidget()
        label_list.setItemDelegate(LabelListItemDelegate(label_list))
        item = QListWidgetItem(
            "a very long annotation label that must leave room for the eye"
        )
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        label_list.addItem(item)
        item.setSelected(True)
        label_list.resize(180, 60)
        label_list.show()
        self.app.processEvents()

        index = label_list.indexFromItem(item)
        visibility_rect = label_list.visibility_rect(index)
        self.assertEqual(
            visibility_rect.right(),
            label_list.viewport().width() - 1,
        )
        self.assertEqual(
            label_list.horizontalScrollBarPolicy(),
            Qt.ScrollBarAlwaysOff,
        )
        self.assertGreater(
            visibility_rect.center().x(),
            label_list.viewport().width() // 2,
        )
        QTest.mouseClick(
            label_list.viewport(),
            Qt.LeftButton,
            pos=visibility_rect.center(),
        )
        self.app.processEvents()

        self.assertEqual(item.checkState(), Qt.Unchecked)
        self.assertTrue(item.isSelected())
        label_list.deleteLater()


if __name__ == "__main__":
    unittest.main()
