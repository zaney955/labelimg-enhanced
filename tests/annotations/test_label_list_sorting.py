import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPalette
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from labelimg.workbench.main_window import MainWindow
from labelimg.canvas.shape import Shape


def rectangle(label, left, color=None):
    shape = Shape(label=label)
    for point in (
        QPointF(left, 10),
        QPointF(left + 10, 10),
        QPointF(left + 10, 20),
        QPointF(left, 20),
    ):
        shape.add_point(point)
    shape.close()
    if color is not None:
        shape.line_color = QColor(color)
    return shape


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
        self.window.label_list.resize(360, 180)
        self.window.label_list.show()

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp_dir.cleanup()

    def load_shapes(self, shapes):
        self.window.canvas.load_shapes(shapes)
        for shape in shapes:
            self.window.add_label(shape)
        self.app.processEvents()

    def render_view(self):
        image = QImage(
            self.window.label_list.viewport().size(),
            QImage.Format_ARGB32,
        )
        image.fill(QColor("white"))
        painter = QPainter(image)
        self.window.label_list.viewport().render(painter)
        painter.end()
        return image

    def test_same_label_is_grouped_and_groups_use_natural_order(self):
        shapes = [
            rectangle("car10", 10),
            rectangle("car2", 30),
            rectangle("car2", 50),
            rectangle("Car2", 70),
        ]
        self.load_shapes(shapes)

        self.assertEqual(
            self.window.label_list.group_labels(),
            ["Car2", "car2", "car10"],
        )
        self.assertEqual(
            self.window.label_list.group_shapes("car2"),
            (shapes[1], shapes[2]),
        )

    def test_group_row_uses_the_theme_background(self):
        self.load_shapes([rectangle("apple", 10)])
        image = self.render_view()
        label_rect = self.window.label_list.group_body_rect("apple")

        self.assertEqual(
            image.pixelColor(label_rect.right() - 3, label_rect.center().y()),
            self.window.label_list.palette().color(QPalette.Base),
        )

    def test_instance_buttons_use_actual_box_colors_only_on_outlines(self):
        first = rectangle("car", 10, QColor(12, 34, 56, 70))
        second = rectangle("car", 30, QColor(180, 90, 20, 80))
        self.load_shapes([first, second])
        image = self.render_view()

        for shape, expected in (
            (first, QColor(12, 34, 56, 255)),
            (second, QColor(180, 90, 20, 255)),
        ):
            rect = self.window.label_list.instance_rect(shape)
            self.assertEqual(
                image.pixelColor(rect.left() + 1, rect.center().y()),
                expected,
            )
            self.assertEqual(
                image.pixelColor(rect.left() + 5, rect.top() + 5),
                self.window.label_list.palette().color(QPalette.Base),
            )

    def test_canvas_selection_projects_partial_and_full_group_state(self):
        first = rectangle("car", 10)
        second = rectangle("car", 30)
        self.load_shapes([first, second])

        self.window.canvas.set_selected_shapes((first,), active_shape=first)
        self.assertEqual(self.window.label_list.selected_shapes(), (first,))

        QTest.mouseClick(
            self.window.label_list.viewport(),
            Qt.LeftButton,
            pos=self.window.label_list.group_body_rect("car").center(),
        )
        self.assertEqual(
            self.window.canvas.selected_shapes,
            [first, second],
        )
        self.assertIsNone(self.window.canvas.selection_snapshot.active)

    def test_group_visibility_is_three_state_and_does_not_change_selection(self):
        first = rectangle("car", 10)
        second = rectangle("car", 30)
        self.load_shapes([first, second])
        self.window.canvas.select_shape(first)
        self.window.label_visibility_requested((second,), False)

        self.assertEqual(
            self.window.label_list.group_visibility("car"),
            Qt.PartiallyChecked,
        )
        QTest.mouseClick(
            self.window.label_list.viewport(),
            Qt.LeftButton,
            pos=self.window.label_list.visibility_rect_for_label("car").center(),
        )

        self.assertEqual(self.window.canvas.selected_shapes, [first])
        self.assertTrue(self.window.canvas.isVisible(first))
        self.assertTrue(self.window.canvas.isVisible(second))

    def test_instance_rename_moves_button_and_group_rename_merges(self):
        first = rectangle("car", 10)
        second = rectangle("person", 30)
        self.load_shapes([first, second])

        with patch.object(
            self.window.candidate_label_dialog,
            "choose",
            return_value="person",
        ):
            self.window.edit_shape_label(first)

        self.assertEqual(self.window.label_list.group_labels(), ["person"])
        self.assertEqual(
            self.window.label_list.group_shapes("person"),
            (first, second),
        )

        third = rectangle("bike", 50)
        self.window.canvas.shapes.append(third)
        self.window.add_label(third)
        with patch.object(
            self.window.candidate_label_dialog,
            "choose",
            return_value="person",
        ):
            self.window.edit_label_group("bike")

        self.assertEqual(self.window.label_list.group_labels(), ["person"])
        self.assertEqual(len(self.window.label_list.group_shapes("person")), 3)

    def test_group_rename_is_one_undoable_edit(self):
        self.assertTrue(self.window.load_file(
            os.path.abspath("tests/test.512.512.bmp")
        ))
        self.window.annotation_clipboard = [
            (
                "car",
                ((10, 10), (20, 10), (20, 20), (10, 20)),
                None,
                None,
                False,
            ),
            (
                "car",
                ((30, 10), (40, 10), (40, 20), (30, 20)),
                None,
                None,
                False,
            ),
        ]
        self.window.paste_copied_bounding_boxes()

        with patch.object(
            self.window.candidate_label_dialog,
            "choose",
            return_value="vehicle",
        ):
            self.window.edit_label_group("car")

        self.assertEqual(self.window.label_list.group_labels(), ["vehicle"])
        self.window.undo_annotation()
        self.assertEqual(self.window.label_list.group_labels(), ["car"])
        self.assertEqual(len(self.window.label_list.group_shapes("car")), 2)

    def test_group_delete_preserves_unrelated_selection_and_undo_restores_group(self):
        self.assertTrue(self.window.load_file(
            os.path.abspath("tests/test.512.512.bmp")
        ))
        self.window.annotation_clipboard = [
            (
                "car",
                ((10, 10), (20, 10), (20, 20), (10, 20)),
                None,
                None,
                False,
            ),
            (
                "car",
                ((30, 10), (40, 10), (40, 20), (30, 20)),
                None,
                None,
                False,
            ),
            (
                "person",
                ((50, 10), (60, 10), (60, 20), (50, 20)),
                None,
                None,
                False,
            ),
        ]
        self.window.paste_copied_bounding_boxes()
        person = self.window.label_list.group_shapes("person")[0]
        self.window.canvas.set_selected_shapes((person,), active_shape=person)

        self.window.delete_annotation_shapes(
            self.window.label_list.group_shapes("car"),
            "Delete label group: car",
        )

        self.assertEqual(self.window.label_list.group_labels(), ["person"])
        self.assertEqual(self.window.canvas.selected_shapes, [person])
        self.window.undo_annotation()
        self.assertEqual(
            self.window.label_list.group_labels(),
            ["car", "person"],
        )


if __name__ == "__main__":
    unittest.main()
