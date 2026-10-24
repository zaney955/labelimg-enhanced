"""Label-group selection uses the same persistent row treatment as files."""

import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent, QPointF, QRect, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QImage, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QWidget,
    QVBoxLayout,
)
from labelimg.annotations.ui.label_group_list import LabelGroupListWidget
from labelimg.canvas.shape import Shape
from labelimg.files.ui.list_widget import FileListItemDelegate, FileListWidget
from labelimg.ui.presentation import present_surface
from labelimg.ui.theme import COLORS, appearance_theme, current_theme, set_theme
from labelimg.ui.theme_palettes import available_accents, blend, contrast_ratio


def box(label, color):
    shape = Shape(label=label)
    for point in (QPointF(10, 10), QPointF(30, 10), QPointF(30, 30), QPointF(10, 30)):
        shape.add_point(point)
    shape.close()
    shape.line_color = QColor(color)
    return shape


class LabelGroupSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.previous_theme = current_theme().identifier
        self.host = QWidget()
        layout = QVBoxLayout(self.host)
        self.list = LabelGroupListWidget()
        self.other = QPushButton("Edit selected")
        layout.addWidget(self.list)
        layout.addWidget(self.other)
        present_surface(self.host)
        self.host.resize(420, 240)
        self.host.show()
        self.shapes = [
            box("alpha", "#E24666"),
            box("alpha", "#E24666"),
            box("bravo", "#2C9E75"),
            box("charlie", "#2278CE"),
        ]
        self.list.set_scene(self.shapes)
        self.app.processEvents()

    def tearDown(self):
        self.host.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        set_theme(self.previous_theme)

    def pixel(self, label, x=18, y=5):
        row = self.list.row_rect_for_label(label)
        return (
            self.list.viewport()
            .grab()
            .toImage()
            .pixelColor(row.left() + x, row.top() + y)
        )

    def test_every_selected_category_has_the_same_full_row_fill(self):
        self.list.project_selection((self.shapes[0], self.shapes[2]), self.shapes[2])
        self.app.processEvents()
        for label in ("alpha", "bravo"):
            self.assertEqual(self.pixel(label), QColor(COLORS["selection_background"]))
        self.assertNotEqual(
            self.pixel("charlie"), QColor(COLORS["selection_background"])
        )
        # Changing the active instance does not weaken any selected category.
        self.list.project_selection((self.shapes[0], self.shapes[2]), self.shapes[0])
        self.assertEqual(self.pixel("bravo"), QColor(COLORS["selection_background"]))

    def test_selection_stays_visible_after_focus_moves_and_while_hovered(self):
        self.list.project_selection((self.shapes[0], self.shapes[2]))
        self.list.setFocus()
        self.app.processEvents()
        expected = self.pixel("alpha")
        self.other.setFocus()
        QTest.mouseMove(
            self.list.viewport(), self.list.group_body_rect("alpha").center()
        )
        self.app.processEvents()
        self.assertFalse(self.list.hasFocus())
        self.assertEqual(self.pixel("alpha"), expected)
        self.assertEqual(expected, QColor(COLORS["selection_background"]))
        self.assertEqual(self.list.selected_shapes(), (self.shapes[0], self.shapes[2]))

    def test_ctrl_group_selection_and_partial_instances_keep_their_semantics(self):
        self.list.selectionRequested.connect(
            lambda shapes, active: self.list.project_selection(shapes, active)
        )
        QTest.mouseClick(
            self.list.viewport(),
            Qt.LeftButton,
            pos=self.list.group_body_rect("alpha").center(),
        )
        QTest.mouseClick(
            self.list.viewport(),
            Qt.LeftButton,
            Qt.ControlModifier,
            self.list.group_body_rect("bravo").center(),
        )
        self.assertEqual(self.list.selected_shapes(), tuple(self.shapes[:3]))
        self.assertEqual(self.pixel("alpha"), self.pixel("bravo"))
        QTest.mouseClick(
            self.list.viewport(),
            Qt.LeftButton,
            Qt.ControlModifier,
            self.list.instance_rect(self.shapes[0]).center(),
        )
        self.assertEqual(self.list.selected_shapes(), (self.shapes[1], self.shapes[2]))
        self.assertEqual(self.pixel("alpha"), QColor(COLORS["selection_background"]))

    def test_theme_switches_match_the_file_selection_fill_in_all_presets(self):
        self.list.project_selection((self.shapes[0], self.shapes[2]))
        for mode in ("light", "dark"):
            for accent in available_accents():
                set_theme(appearance_theme(mode, accent.identifier).identifier)
                self.app.processEvents()
                self.assertEqual(
                    self.pixel("alpha"),
                    QColor(COLORS["selection_background"]),
                    (mode, accent.identifier),
                )
                self.assertEqual(self.pixel("bravo"), self.pixel("alpha"))
                # Extremal category fills bound the ordinal chip's luminance.
                for category in ("#000000", "#FFFFFF"):
                    chip = blend(category, COLORS["selection_background"], 48 / 255)
                    self.assertGreaterEqual(
                        contrast_ratio(COLORS["selection_foreground"], chip), 4.5
                    )
                self.assertEqual(
                    self.list.selected_shapes(), (self.shapes[0], self.shapes[2])
                )

    def test_full_and_partial_groups_use_solid_and_dashed_rows_without_markers(self):
        self.list.project_selection(tuple(self.shapes[:3]))
        solid = self.list.viewport().grab().toImage()
        row = self.list.row_rect_for_label("alpha")
        solid_edge = [solid.pixelColor(x, row.top() + 1).rgba() for x in range(16, 80)]
        self.list.project_selection((self.shapes[0], self.shapes[2]))
        mixed = self.list.viewport().grab().toImage()
        mixed_edge = [mixed.pixelColor(x, row.top() + 1).rgba() for x in range(16, 80)]
        self.assertEqual(len(set(solid_edge)), 1)
        self.assertGreater(len(set(mixed_edge)), 1)
        for label in ("alpha", "bravo"):
            selected_row = self.list.row_rect_for_label(label)
            self.assertEqual(
                mixed.pixelColor(3, selected_row.center().y()),
                QColor(COLORS["selection_background"]),
            )

    def test_partial_selection_count_and_reserved_space_are_stable(self):
        shapes = [box("alpha", "#E24666") for _ in range(1000)]
        self.list.set_scene(shapes)
        rect = self.list.count_rect_for_label("alpha")
        first = self.list.instance_rect(shapes[0])
        self.list.project_selection(shapes[:501])
        painter = Mock()
        self.list._paint_count(
            painter,
            self.list._groups_by_label["alpha"],
            rect,
            QColor(COLORS["selection_foreground"]),
        )
        self.assertEqual(painter.drawText.call_args.args[-1], "501/1000")
        value = self.list._group_count_value_rect(rect).adjusted(0, 0, -4, 0)
        metrics = QFontMetrics(self.list._label_measurement_font())
        self.assertGreaterEqual(value.width(), metrics.horizontalAdvance("1000/1000"))
        self.list.project_selection(shapes)
        self.assertEqual(self.list.count_rect_for_label("alpha"), rect)
        self.assertEqual(self.list.instance_rect(shapes[0]), first)
        painter.reset_mock()
        self.list._paint_count(
            painter, self.list._groups_by_label["alpha"], rect, QColor("black")
        )
        self.assertEqual(painter.drawText.call_args.args[-1], "×1000")

    def test_selection_uses_the_file_delegate_fill_and_keeps_category_color(self):
        files = FileListWidget(self.host)
        files.addItem("sample.png")
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, self.list.viewport().width(), self.list.row_height)
        option.state = QStyle.State_Enabled | QStyle.State_Selected
        option.widget = files
        image = QImage(option.rect.size(), QImage.Format_ARGB32)
        image.fill(QColor(COLORS["surface"]))
        painter = QPainter(image)
        FileListItemDelegate(files).paint(painter, option, files.model().index(0, 0))
        painter.end()
        self.list.project_selection((self.shapes[0], self.shapes[2]))
        self.assertEqual(self.pixel("alpha"), image.pixelColor(18, 5))
        self.assertEqual(self.pixel("bravo", y=1), image.pixelColor(18, 1))
        rendered = self.list.viewport().grab().toImage()
        for label, color in (("alpha", "#E24666"), ("bravo", "#2C9E75")):
            row = self.list.row_rect_for_label(label)
            self.assertEqual(rendered.pixelColor(9, row.center().y()), QColor(color))


if __name__ == "__main__":
    unittest.main()
