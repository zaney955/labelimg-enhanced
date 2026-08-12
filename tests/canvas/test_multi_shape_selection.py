import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPixmap
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QAbstractItemView

from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.canvas.widget import Canvas
from labelimg.canvas.shape import Shape


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
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
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

    def click(self, position):
        self.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            position,
            button=Qt.LeftButton,
            buttons=Qt.LeftButton,
        ))
        self.canvas.mouseReleaseEvent(mouse_event(
            QEvent.MouseButtonRelease,
            position,
            button=Qt.LeftButton,
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
        self.assertIs(self.canvas.interaction_snapshot.hover.shape, partial)

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

    def test_repeated_ctrl_click_toggles_the_innermost_overlap(self):
        lower = rectangle("lower", 10, 10, 90, 90)
        upper = rectangle("upper", 20, 20, 80, 80)
        self.canvas.load_shapes([lower, upper])

        self.ctrl_click((50, 50))
        self.assertEqual(self.canvas.selected_shapes, [upper])

        self.ctrl_click((50, 50))
        self.assertEqual(self.canvas.selected_shapes, [])

        self.ctrl_click((50, 50))
        self.assertEqual(self.canvas.selected_shapes, [upper])

    def test_repeated_plain_click_stably_selects_the_same_overlap_target(self):
        lower = rectangle("lower", 10, 10, 90, 90)
        upper = rectangle("upper", 20, 20, 80, 80)
        self.canvas.load_shapes([lower, upper])

        self.click((50, 50))
        self.assertEqual(self.canvas.selected_shapes, [upper])

        self.click((50, 50))
        self.assertEqual(self.canvas.selected_shapes, [upper])

    def test_partial_overlap_click_uses_nearest_boundary_not_layer_order(self):
        nearer = rectangle("nearer", 37, 20, 100, 80)
        farther_top = rectangle("farther", 10, 10, 70, 70)
        self.canvas.load_shapes([nearer, farther_top])

        self.click((45, 50))

        self.assertEqual(self.canvas.selected_shapes, [nearer])

    def test_identical_overlaps_stably_choose_topmost(self):
        lower = rectangle("lower", 10, 10, 90, 90)
        upper = rectangle("upper", 10, 10, 90, 90)
        self.canvas.load_shapes([lower, upper])

        self.click((50, 50))
        self.click((50, 50))

        self.assertEqual(self.canvas.selected_shapes, [upper])

    def test_hover_and_ctrl_click_resolve_the_same_innermost_target(self):
        outer = rectangle("outer", 10, 10, 100, 100)
        inner = rectangle("inner", 30, 30, 70, 70)
        self.canvas.load_shapes([inner, outer])

        self.canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove, (50, 50)))
        self.assertIs(self.canvas.interaction_snapshot.hover.shape, inner)

        self.ctrl_click((50, 50))
        self.assertEqual(self.canvas.selected_shapes, [inner])

    def test_ctrl_hover_keeps_box_target_but_suppresses_corner_cue(self):
        shape = rectangle("shape", 10, 10, 80, 80)
        self.canvas.load_shapes([shape])

        self.canvas.mouseMoveEvent(mouse_event(
            QEvent.MouseMove,
            (10, 10),
            modifiers=Qt.ControlModifier,
        ))

        self.assertIs(self.canvas.interaction_snapshot.hover.shape, shape)
        self.assertIsNone(shape._highlight_index)
        self.assertEqual(self.canvas.current_cursor(), Qt.CrossCursor)

    def test_ctrl_key_suppresses_and_release_restores_corner_feedback(self):
        shape = rectangle("shape", 10, 10, 80, 80)
        self.canvas.load_shapes([shape])
        self.canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove, (10, 10)))
        self.assertEqual(shape._highlight_index, 0)

        self.canvas.keyPressEvent(QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_Control,
            Qt.ControlModifier,
        ))
        self.assertIs(self.canvas.interaction_snapshot.hover.shape, shape)
        self.assertIsNone(shape._highlight_index)
        self.assertEqual(self.canvas.current_cursor(), Qt.CrossCursor)

        self.canvas.keyReleaseEvent(QKeyEvent(
            QEvent.KeyRelease,
            Qt.Key_Control,
            Qt.NoModifier,
        ))
        self.assertEqual(shape._highlight_index, 0)
        self.assertIn(
            self.canvas.current_cursor(),
            (Qt.SizeFDiagCursor, Qt.SizeBDiagCursor),
        )

    def test_creation_mode_does_not_publish_canvas_hover_target(self):
        shape = rectangle("shape", 10, 10, 80, 80)
        self.canvas.load_shapes([shape])
        self.canvas.set_editing(False)

        self.canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove, (50, 50)))

        self.assertIsNone(self.canvas.interaction_snapshot.hover.shape)

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

    def test_right_click_uses_the_same_overlap_target_as_hover(self):
        nearer = rectangle("nearer", 37, 20, 100, 80)
        farther_top = rectangle("farther", 10, 10, 70, 70)
        self.canvas.load_shapes([nearer, farther_top])

        self.canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove, (45, 50)))
        self.assertIs(self.canvas.interaction_snapshot.hover.shape, nearer)

        self.canvas.mousePressEvent(mouse_event(
            QEvent.MouseButtonPress,
            (45, 50),
            button=Qt.RightButton,
            buttons=Qt.RightButton,
        ))

        self.assertEqual(self.canvas.selected_shapes, [nearer])
        self.assertIs(self.canvas.right_press_shape, nearer)

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
        self.canvas.set_hover_target(shape)
        image = QImage(120, 120, QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        self.canvas.render(image)

        self.assertFalse(shape.fill)

    def test_canvas_renders_hover_target_as_dashed_instead_of_overlay(self):
        shape = rectangle("shape", 10, 10, 80, 80)
        pixmap = QPixmap(120, 120)
        pixmap.fill(QColor("white"))
        self.canvas.load_pixmap(pixmap)
        self.canvas.load_shapes([shape])
        self.canvas.set_hover_target(shape)
        outline_styles = []
        original_paint = shape.paint

        def record_paint(
            painter,
            outline_style=Qt.SolidLine,
            outline_dash_pattern=None,
        ):
            outline_styles.append(
                (outline_style, outline_dash_pattern)
            )
            return original_paint(
                painter,
                outline_style=outline_style,
                outline_dash_pattern=outline_dash_pattern,
            )

        shape.paint = record_paint
        image = QImage(120, 120, QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        self.canvas.render(image)

        self.assertEqual(
            outline_styles,
            [(Qt.CustomDashLine, (4.0, 4.0))],
        )

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
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=classes_path,
        ))
        self.window.workbench_session.activate(os.path.join(
            self.temp_dir.name,
            "image.png",
        ))
        self.window.canvas.resize(120, 120)
        self.window.canvas.load_pixmap(QPixmap(120, 120))

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
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
        self.assertEqual(
            set(self.window.label_list.selected_shapes()),
            {first, second},
        )

        QTest.mouseClick(
            self.window.label_list.viewport(),
            Qt.LeftButton,
            pos=self.window.label_list.instance_rect(first).center(),
        )
        QTest.mouseClick(
            self.window.label_list.viewport(),
            Qt.LeftButton,
            Qt.ControlModifier,
            pos=self.window.label_list.instance_rect(second).center(),
        )
        self.app.processEvents()

        self.assertEqual(
            self.window.canvas.selected_shapes,
            [first, second],
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
        self.assertIn(first, self.window.label_list.selected_shapes())
        self.assertNotIn(second, self.window.label_list.selected_shapes())
        self.window.canvas.mouseReleaseEvent(mouse_event(
            QEvent.MouseButtonRelease,
            (40, 40),
            button=Qt.LeftButton,
        ))

    def test_canvas_hover_projects_to_row_without_changing_selection(self):
        shape = rectangle("shape", 10, 10, 80, 80)
        self.load_shapes([shape])
        before_selection = self.window.canvas.selection_snapshot
        before_dirty = self.window.dirty

        self.window.canvas.mouseMoveEvent(
            mouse_event(QEvent.MouseMove, (50, 50))
        )

        self.assertTrue(self.window.label_list.is_group_hovered("shape"))
        self.assertIs(
            self.window.label_list.projected_hover_shape(),
            shape,
        )
        self.assertIs(
            self.window.canvas.interaction_snapshot.hover.shape,
            shape,
        )
        self.assertIs(
            self.window.canvas.selection_snapshot,
            before_selection,
        )
        self.assertEqual(self.window.dirty, before_dirty)

    def test_row_hover_projects_visible_shape_and_hidden_row_stays_row_only(self):
        shape = rectangle("shape", 10, 10, 80, 80)
        self.load_shapes([shape])
        self.window.label_list.resize(300, 100)
        self.window.label_list.show()
        self.app.processEvents()
        row_rect = self.window.label_list.group_body_rect("shape")
        before_selection = self.window.canvas.selection_snapshot
        before_dirty = self.window.dirty

        self.window.label_list.mouseMoveEvent(QMouseEvent(
            QEvent.MouseMove,
            QPointF(row_rect.center()),
            Qt.NoButton,
            Qt.NoButton,
            Qt.NoModifier,
        ))

        self.assertTrue(self.window.label_list.is_group_hovered("shape"))
        self.assertIs(self.window.canvas.hover_shape_for_paint, shape)
        self.assertIs(
            self.window.canvas.selection_snapshot,
            before_selection,
        )
        self.assertEqual(self.window.dirty, before_dirty)

        self.window.label_visibility_requested((shape,), False)
        self.app.processEvents()

        self.assertTrue(self.window.label_list.is_group_hovered("shape"))
        self.assertIsNone(self.window.canvas.hover_shape_for_paint)
        self.assertFalse(self.window.canvas.isVisible(shape))

    def test_group_row_hover_projects_every_visible_instance(self):
        first = rectangle("car", 10, 10, 30, 30)
        second = rectangle("car", 50, 50, 80, 80)
        hidden = rectangle("car", 90, 90, 110, 110)
        self.load_shapes([first, second, hidden])
        self.window.label_visibility_requested((hidden,), False)
        self.window.label_list.resize(300, 100)
        self.window.label_list.show()
        self.app.processEvents()

        point = self.window.label_list.group_body_rect("car").center()
        self.window.label_list.mouseMoveEvent(QMouseEvent(
            QEvent.MouseMove,
            QPointF(point),
            Qt.NoButton,
            Qt.NoButton,
            Qt.NoModifier,
        ))

        self.assertEqual(
            self.window.canvas.hover_shapes_for_paint,
            (first, second),
        )

    def test_shift_click_selects_the_visible_sorted_range(self):
        shapes = [
            rectangle("charlie", 10, 10, 20, 20),
            rectangle("alpha", 30, 30, 40, 40),
            rectangle("bravo", 50, 50, 60, 60),
        ]
        self.load_shapes(shapes)
        self.window.label_list.resize(300, 200)
        self.app.processEvents()

        first_rect = self.window.label_list.group_body_rect("alpha")
        last_rect = self.window.label_list.group_body_rect("charlie")
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

        self.assertEqual(len(self.window.label_list.selected_shapes()), 3)
        self.assertEqual(
            self.window.canvas.selected_shapes,
            shapes,
        )

    def test_visibility_eye_at_right_does_not_change_selection(self):
        first = rectangle("first", 10, 10, 20, 20)
        second = rectangle("second", 30, 30, 40, 40)
        third = rectangle("third", 50, 50, 60, 60)
        self.load_shapes([first, second, third])
        self.window.canvas.set_selected_shapes([first, second])
        self.window.label_list.resize(300, 200)
        self.app.processEvents()

        visibility_rect = self.window.label_list.visibility_rect_for_label(
            "third"
        )
        self.assertGreater(
            visibility_rect.center().x(),
            self.window.label_list.viewport().width() // 2,
        )
        QTest.mouseClick(
            self.window.label_list.viewport(),
            Qt.LeftButton,
            pos=visibility_rect.center(),
        )
        self.app.processEvents()

        self.assertEqual(
            self.window.canvas.selected_shapes,
            [first, second],
        )
        self.assertEqual(
            self.window.label_list.group_visibility("third"),
            Qt.Unchecked,
        )
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
        self.assertIsNone(self.window.label_list.target_at(empty_pos))
        QTest.mouseClick(
            self.window.label_list.viewport(),
            Qt.LeftButton,
            pos=empty_pos,
        )
        self.app.processEvents()

        self.assertEqual(self.window.canvas.selected_shapes, [])

    def test_ctrl_a_selects_all_visible_groups_without_changing_visibility(self):
        first = rectangle("first", 10, 10, 20, 20)
        second = rectangle("second", 30, 30, 40, 40)
        self.load_shapes([first, second])
        self.window.label_visibility_requested((second,), False)
        self.window.canvas.select_shape(first)
        self.window.label_list.setFocus()
        self.app.processEvents()

        self.window.label_list.keyPressEvent(QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_A,
            Qt.ControlModifier,
        ))
        self.app.processEvents()

        self.assertEqual(self.window.canvas.selected_shapes, [first, second])
        self.assertFalse(self.window.canvas.isVisible(second))

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
        self.assertEqual(self.window.label_list.group_count(), 2)
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
        self.assertEqual(self.window.label_list.group_count(), 0)
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
        self.assertEqual(self.window.label_list.group_count(), 3)


if __name__ == "__main__":
    unittest.main()
