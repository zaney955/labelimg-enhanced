import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPixmap
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QAbstractItemView

from labelimg.app import MainWindow
from labelimg.canvas import Canvas
from labelimg.shape import Shape


def rectangle(label, left, top, right, bottom, color=None):
    shape = Shape(label=label)
    for point in (
        QPointF(left, top),
        QPointF(right, top),
        QPointF(right, bottom),
        QPointF(left, bottom),
    ):
        shape.add_point(point)
    shape.close()
    if color is not None:
        shape.line_color = QColor(color)
        shape.fill_color = QColor(color)
    return shape


def mouse_event(event_type, position, button=Qt.NoButton,
                buttons=Qt.NoButton, modifiers=Qt.NoModifier):
    return QMouseEvent(
        event_type,
        QPointF(*position),
        button,
        buttons,
        modifiers,
    )


class CanvasMultiSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.window.file_path = None
        self.window.label_coordinates = QLabel(self.window)
        self.canvas = Canvas(self.window)
        self.canvas.resize(120, 120)
        self.canvas.load_pixmap(QPixmap(120, 120))

    def tearDown(self):
        self.canvas.deleteLater()
        self.window.deleteLater()
        self.app.processEvents()

    def ctrl_click(self, position):
        self.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            position,
            button=Qt.LeftButton,
            buttons=Qt.LeftButton,
            modifiers=Qt.ControlModifier,
        ))
        self.canvas.mouseReleaseEvent(mouse_event(
            QEvent.MouseButtonRelease,
            position,
            button=Qt.LeftButton,
            modifiers=Qt.ControlModifier,
        ))

    def test_ctrl_marquee_selects_only_fully_contained_visible_shapes(self):
        inside = rectangle("inside", 10, 10, 30, 30)
        partial = rectangle("partial", 40, 40, 70, 70)
        hidden = rectangle("hidden", 15, 15, 25, 25)
        self.canvas.load_shapes([inside, partial, hidden])
        self.canvas.set_shape_visible(hidden, False)

        self.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            (5, 5),
            button=Qt.LeftButton,
            buttons=Qt.LeftButton,
            modifiers=Qt.ControlModifier,
        ))
        self.canvas.mouseMoveEvent(mouse_event(
            QEvent.MouseMove,
            (50, 50),
            buttons=Qt.LeftButton,
            modifiers=Qt.ControlModifier,
        ))

        self.assertEqual(self.canvas.selected_shapes, [inside])
        self.assertIsNotNone(self.canvas.selection_rect)

        # Releasing Ctrl before the mouse must still commit the marquee.
        self.canvas.mouseReleaseEvent(mouse_event(
            QEvent.MouseButtonRelease,
            (50, 50),
            button=Qt.LeftButton,
        ))

        self.assertEqual(self.canvas.selected_shapes, [inside])
        self.assertIsNone(self.canvas.selection_rect)

    def test_escape_cancels_marquee_and_restores_previous_selection(self):
        first = rectangle("first", 10, 10, 30, 30)
        second = rectangle("second", 70, 70, 100, 100)
        self.canvas.load_shapes([first, second])
        self.canvas.select_shape(second)

        self.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            (5, 5),
            button=Qt.LeftButton,
            buttons=Qt.LeftButton,
            modifiers=Qt.ControlModifier,
        ))
        self.canvas.mouseMoveEvent(mouse_event(
            QEvent.MouseMove,
            (40, 40),
            buttons=Qt.LeftButton,
            modifiers=Qt.ControlModifier,
        ))
        self.assertEqual(self.canvas.selected_shapes, [first])

        self.canvas.keyPressEvent(QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_Escape,
            Qt.NoModifier,
        ))

        self.assertEqual(self.canvas.selected_shapes, [second])
        self.assertIsNone(self.canvas.selection_rect)

    def test_ctrl_click_toggles_non_overlapping_shapes(self):
        first = rectangle("first", 10, 10, 30, 30)
        second = rectangle("second", 70, 70, 100, 100)
        self.canvas.load_shapes([first, second])

        self.ctrl_click((20, 20))
        self.ctrl_click((80, 80))
        self.assertEqual(self.canvas.selected_shapes, [first, second])

        self.ctrl_click((20, 20))
        self.assertEqual(self.canvas.selected_shapes, [second])

    def test_repeated_ctrl_click_cycles_overlaps_one_at_a_time(self):
        lower = rectangle("lower", 10, 10, 90, 90)
        upper = rectangle("upper", 20, 20, 80, 80)
        self.canvas.load_shapes([lower, upper])

        self.ctrl_click((50, 50))
        self.assertEqual(self.canvas.selected_shapes, [upper])

        self.ctrl_click((50, 50))
        self.assertEqual(self.canvas.selected_shapes, [lower])

        self.ctrl_click((50, 50))
        self.assertEqual(self.canvas.selected_shapes, [upper])

    def test_right_click_preserves_selected_member_and_collapses_on_other(self):
        first = rectangle("first", 10, 10, 30, 30)
        second = rectangle("second", 40, 40, 60, 60)
        third = rectangle("third", 80, 80, 100, 100)
        self.canvas.load_shapes([first, second, third])
        self.canvas.set_selected_shapes([first, second])

        self.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            (20, 20),
            button=Qt.RightButton,
            buttons=Qt.RightButton,
        ))
        self.assertEqual(self.canvas.selected_shapes, [first, second])

        self.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            (90, 90),
            button=Qt.RightButton,
            buttons=Qt.RightButton,
        ))
        self.assertEqual(self.canvas.selected_shapes, [third])

        self.canvas.set_selected_shapes([first, second])
        self.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            (110, 10),
            button=Qt.RightButton,
            buttons=Qt.RightButton,
        ))
        self.assertEqual(self.canvas.selected_shapes, [first, second])

    def test_right_drag_from_multi_selection_collapses_to_one_shape(self):
        first = rectangle("first", 10, 10, 30, 30)
        second = rectangle("second", 50, 50, 80, 80)
        self.canvas.load_shapes([first, second])
        self.canvas.set_selected_shapes([first, second])

        self.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            (20, 20),
            button=Qt.RightButton,
            buttons=Qt.RightButton,
        ))
        self.canvas.mouseMoveEvent(mouse_event(
            QEvent.MouseMove,
            (35, 35),
            buttons=Qt.RightButton,
        ))

        self.assertEqual(self.canvas.selected_shapes, [first])
        self.assertIsNotNone(self.canvas.selected_shape_copy)

    def test_arrow_keys_do_not_move_multiple_selected_shapes(self):
        first = rectangle("first", 10, 10, 30, 30)
        second = rectangle("second", 50, 50, 80, 80)
        self.canvas.load_shapes([first, second])
        self.canvas.set_selected_shapes([first, second])
        original_points = [
            [QPointF(point) for point in shape.points]
            for shape in (first, second)
        ]

        self.canvas.keyPressEvent(QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_Left,
            Qt.NoModifier,
        ))

        self.assertEqual(first.points, original_points[0])
        self.assertEqual(second.points, original_points[1])

    def test_hover_does_not_fill_an_unselected_shape(self):
        shape = rectangle("shape", 10, 10, 80, 80)
        pixmap = QPixmap(120, 120)
        pixmap.fill(QColor("white"))
        self.canvas.load_pixmap(pixmap)
        self.canvas.load_shapes([shape])
        self.canvas.h_shape = shape
        image = QImage(120, 120, QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        self.canvas.render(image)

        self.assertFalse(shape.fill)

    def test_ctrl_during_active_drawing_does_not_start_marquee(self):
        self.canvas.set_editing(False)
        self.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            (10, 10),
            button=Qt.LeftButton,
            buttons=Qt.LeftButton,
        ))
        self.assertIsNotNone(self.canvas.current)

        self.canvas.mouseMoveEvent(mouse_event(
            QEvent.MouseMove,
            (40, 40),
            buttons=Qt.LeftButton,
            modifiers=Qt.ControlModifier,
        ))

        self.assertIsNotNone(self.canvas.current)
        self.assertIsNone(self.canvas.selection_press_pos)


class MainWindowMultiSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        classes_path = os.path.join(self.temp_dir.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass
        self.window = MainWindow(
            default_prefdef_class_file=classes_path,
        )
        self.window.file_path = os.path.join(
            self.temp_dir.name,
            "image.png",
        )
        self.window.canvas.resize(120, 120)
        self.window.canvas.load_pixmap(QPixmap(120, 120))

    def tearDown(self):
        self.window.deleteLater()
        self.app.processEvents()
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        self.temp_dir.cleanup()

    def load_shapes(self, shapes):
        self.window.canvas.load_shapes(shapes)
        for shape in shapes:
            self.window.add_label(shape)
        self.app.processEvents()

    def test_canvas_and_label_list_keep_the_same_multi_selection(self):
        first = rectangle("zebra", 10, 10, 30, 30)
        second = rectangle("apple", 50, 50, 80, 80)
        self.load_shapes([first, second])

        self.window.canvas.set_selected_shapes([first, second])
        selected_items = set(self.window.label_list.selectedItems())
        self.assertEqual(
            selected_items,
            {
                self.window.shapes_to_items[first],
                self.window.shapes_to_items[second],
            },
        )

        self.window.label_list.clearSelection()
        self.window.shapes_to_items[first].setSelected(True)
        self.window.shapes_to_items[second].setSelected(True)
        self.app.processEvents()

        self.assertEqual(
            self.window.canvas.selected_shapes,
            [first, second],
        )
        self.assertEqual(
            self.window.label_list.selectionMode(),
            QAbstractItemView.ExtendedSelection,
        )
        self.assertTrue(self.window.actions.delete.isEnabled())
        self.assertTrue(self.window.actions.copy.isEnabled())
        self.assertFalse(self.window.actions.edit.isEnabled())

        self.window.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            (5, 5),
            button=Qt.LeftButton,
            buttons=Qt.LeftButton,
            modifiers=Qt.ControlModifier,
        ))
        self.window.canvas.mouseMoveEvent(mouse_event(
            QEvent.MouseMove,
            (40, 40),
            buttons=Qt.LeftButton,
            modifiers=Qt.ControlModifier,
        ))
        self.assertTrue(
            self.window.shapes_to_items[first].isSelected()
        )
        self.assertFalse(
            self.window.shapes_to_items[second].isSelected()
        )
        self.window.canvas.mouseReleaseEvent(mouse_event(
            QEvent.MouseButtonRelease,
            (40, 40),
            button=Qt.LeftButton,
        ))

    def test_shift_click_selects_the_visible_sorted_range(self):
        shapes = [
            rectangle("charlie", 10, 10, 20, 20),
            rectangle("alpha", 30, 30, 40, 40),
            rectangle("bravo", 50, 50, 60, 60),
        ]
        self.load_shapes(shapes)
        self.window.label_list.resize(300, 200)
        self.app.processEvents()

        first_rect = self.window.label_list.visualItemRect(
            self.window.label_list.item(0)
        )
        last_rect = self.window.label_list.visualItemRect(
            self.window.label_list.item(2)
        )
        first_pos = QPoint(
            max(first_rect.left() + 60, first_rect.center().x()),
            first_rect.center().y(),
        )
        last_pos = QPoint(
            max(last_rect.left() + 60, last_rect.center().x()),
            last_rect.center().y(),
        )
        QTest.mouseClick(
            self.window.label_list.viewport(),
            Qt.LeftButton,
            pos=first_pos,
        )
        QTest.mouseClick(
            self.window.label_list.viewport(),
            Qt.LeftButton,
            Qt.ShiftModifier,
            pos=last_pos,
        )
        self.app.processEvents()

        self.assertEqual(len(self.window.label_list.selectedItems()), 3)
        self.assertEqual(
            self.window.canvas.selected_shapes,
            shapes,
        )

    def test_visibility_checkbox_does_not_change_selection(self):
        first = rectangle("first", 10, 10, 20, 20)
        second = rectangle("second", 30, 30, 40, 40)
        third = rectangle("third", 50, 50, 60, 60)
        self.load_shapes([first, second, third])
        self.window.canvas.set_selected_shapes([first, second])
        self.window.label_list.resize(300, 200)
        self.app.processEvents()

        third_item = self.window.shapes_to_items[third]
        third_index = self.window.label_list.indexFromItem(third_item)
        checkbox_rect = self.window.label_list.checkbox_rect(third_index)
        QTest.mouseClick(
            self.window.label_list.viewport(),
            Qt.LeftButton,
            pos=checkbox_rect.center(),
        )
        self.app.processEvents()

        self.assertEqual(
            self.window.canvas.selected_shapes,
            [first, second],
        )
        self.assertEqual(third_item.checkState(), Qt.Unchecked)
        self.assertFalse(self.window.canvas.isVisible(third))

    def test_clicking_empty_list_space_clears_selection(self):
        shape = rectangle("shape", 10, 10, 20, 20)
        self.load_shapes([shape])
        self.window.canvas.select_shape(shape)
        self.window.label_list.resize(300, 200)
        self.window.label_list.setMinimumHeight(160)
        self.app.processEvents()

        empty_pos = QPoint(
            self.window.label_list.viewport().width() // 2,
            self.window.label_list.viewport().height() - 2,
        )
        self.assertIsNone(self.window.label_list.itemAt(empty_pos))
        QTest.mouseClick(
            self.window.label_list.viewport(),
            Qt.LeftButton,
            pos=empty_pos,
        )
        self.app.processEvents()

        self.assertEqual(self.window.canvas.selected_shapes, [])

    def test_ctrl_a_keeps_show_all_action_instead_of_selecting_all(self):
        first = rectangle("first", 10, 10, 20, 20)
        second = rectangle("second", 30, 30, 40, 40)
        self.load_shapes([first, second])
        self.window.shapes_to_items[second].setCheckState(Qt.Unchecked)
        self.window.canvas.select_shape(first)
        self.window.label_list.setFocus()
        self.app.processEvents()

        self.window.label_list.keyPressEvent(QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_A,
            Qt.ControlModifier,
        ))
        self.app.processEvents()

        self.assertEqual(self.window.canvas.selected_shapes, [first])
        self.assertTrue(self.window.canvas.isVisible(second))

    def test_ctrl_enters_selection_mode_without_enabling_square_drawing(self):
        self.window.canvas.set_drawing_shape_to_square(False)

        self.window.keyPressEvent(QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_Control,
            Qt.ControlModifier,
        ))
        self.assertTrue(self.window.canvas.multi_selection_mode)
        self.assertFalse(self.window.canvas.draw_square)

        self.window.keyReleaseEvent(QKeyEvent(
            QEvent.KeyRelease,
            Qt.Key_Control,
            Qt.NoModifier,
        ))
        self.assertFalse(self.window.canvas.multi_selection_mode)
        self.assertFalse(self.window.canvas.draw_square)

    def test_bulk_duplicate_selects_only_new_offset_copies(self):
        first = rectangle("first", 10, 10, 30, 30)
        second = rectangle("second", 50, 50, 80, 80)
        self.load_shapes([first, second])
        original_points = [
            [QPointF(point) for point in shape.points]
            for shape in (first, second)
        ]
        self.window.canvas.set_selected_shapes([first, second])

        self.window.copy_selected_shape()

        copies = self.window.canvas.selected_shapes
        self.assertEqual(len(self.window.canvas.shapes), 4)
        self.assertEqual(len(copies), 2)
        self.assertNotIn(first, copies)
        self.assertNotIn(second, copies)
        self.assertEqual(self.window.label_list.count(), 4)
        for copy, points in zip(copies, original_points):
            self.assertNotEqual(copy.points, points)

    def test_bulk_delete_removes_hidden_selected_shapes(self):
        visible = rectangle("visible", 10, 10, 30, 30)
        hidden = rectangle("hidden", 50, 50, 80, 80)
        self.load_shapes([visible, hidden])
        self.window.canvas.set_shape_visible(hidden, False)
        self.window.canvas.set_selected_shapes([visible, hidden])

        self.window.delete_selected_shape()

        self.assertEqual(self.window.canvas.shapes, [])
        self.assertEqual(self.window.label_list.count(), 0)
        self.assertEqual(self.window.canvas.selected_shapes, [])

    def test_clipboard_copy_uses_selection_and_paste_appends(self):
        first = rectangle("first", 10, 10, 30, 30)
        second = rectangle("second", 50, 50, 80, 80)
        existing = rectangle("existing", 85, 85, 105, 105)
        self.load_shapes([first, second, existing])
        self.window.canvas.set_selected_shapes([first, second])

        self.window.copy_current_bounding_boxes()
        self.window.paste_copied_bounding_boxes()

        self.assertEqual(len(self.window.canvas.shapes), 5)
        self.assertIn(existing, self.window.canvas.shapes)
        self.assertEqual(len(self.window.canvas.selected_shapes), 2)
        self.assertNotIn(first, self.window.canvas.selected_shapes)
        self.assertNotIn(second, self.window.canvas.selected_shapes)
        self.assertEqual(self.window.label_list.count(), 5)


if __name__ == "__main__":
    unittest.main()
