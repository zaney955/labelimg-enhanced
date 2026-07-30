import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

from labelimg.canvas import Canvas
from labelimg.shape import Shape


def rectangle(label, left, top, right, bottom):
    shape = Shape(label=label)
    for point in (
        QPointF(left, top),
        QPointF(right, top),
        QPointF(right, bottom),
        QPointF(left, bottom),
    ):
        shape.add_point(point)
    shape.close()
    return shape


def mouse_event(event_type, position, button=Qt.NoButton, buttons=Qt.NoButton):
    return QMouseEvent(
        event_type,
        QPointF(*position),
        button,
        buttons,
        Qt.NoModifier,
    )


class OverlappingShapeVertexDragTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.window.file_path = None
        self.window.label_coordinates = QLabel(self.window)

        self.canvas = Canvas(self.window)
        self.canvas.resize(100, 100)
        self.canvas.load_pixmap(QPixmap(100, 100))

        self.lower_shape = rectangle("lower", 10, 10, 40, 40)
        self.upper_shape = rectangle("upper", 30, 30, 70, 70)
        self.canvas.load_shapes([self.lower_shape, self.upper_shape])

    def tearDown(self):
        self.canvas.deleteLater()
        self.window.deleteLater()
        self.app.processEvents()

    def test_dragging_a_vertex_covered_by_another_shape_moves_that_vertex(self):
        covered_vertex = (40, 40)
        drag_target = (50, 50)

        self.canvas.mouseMoveEvent(
            mouse_event(QEvent.MouseMove, covered_vertex)
        )
        self.assertIs(self.canvas.h_shape, self.lower_shape)
        self.assertEqual(self.canvas.h_vertex, 2)

        self.canvas.mousePressEvent(
            mouse_event(
                QEvent.MouseButtonPress,
                covered_vertex,
                button=Qt.LeftButton,
                buttons=Qt.LeftButton,
            )
        )
        self.canvas.mouseMoveEvent(
            mouse_event(
                QEvent.MouseMove,
                drag_target,
                buttons=Qt.LeftButton,
            )
        )
        self.canvas.mouseReleaseEvent(
            mouse_event(
                QEvent.MouseButtonRelease,
                drag_target,
                button=Qt.LeftButton,
            )
        )

        self.assertEqual(self.lower_shape[2], QPointF(*drag_target))
        self.assertEqual(
            self.upper_shape.points,
            [
                QPointF(30, 30),
                QPointF(70, 30),
                QPointF(70, 70),
                QPointF(30, 70),
            ],
        )

    def test_corner_cursor_matches_its_resize_diagonal_while_hovering_and_dragging(self):
        cases = (
            ((20, 20), (15, 15), 0, Qt.SizeFDiagCursor),
            ((80, 20), (85, 15), 1, Qt.SizeBDiagCursor),
            ((80, 80), (85, 85), 2, Qt.SizeFDiagCursor),
            ((20, 80), (15, 85), 3, Qt.SizeBDiagCursor),
        )

        for start, drag_target, vertex, expected_cursor in cases:
            with self.subTest(vertex=vertex):
                shape = rectangle("resizable", 20, 20, 80, 80)
                self.canvas.load_shapes([shape])

                self.canvas.mouseMoveEvent(
                    mouse_event(QEvent.MouseMove, start)
                )
                self.assertEqual(self.canvas.h_vertex, vertex)
                self.assertEqual(
                    self.canvas.current_cursor(),
                    expected_cursor,
                )

                self.canvas.mousePressEvent(
                    mouse_event(
                        QEvent.MouseButtonPress,
                        start,
                        button=Qt.LeftButton,
                        buttons=Qt.LeftButton,
                    )
                )
                self.canvas.mouseMoveEvent(
                    mouse_event(
                        QEvent.MouseMove,
                        drag_target,
                        buttons=Qt.LeftButton,
                    )
                )
                self.assertEqual(
                    self.canvas.current_cursor(),
                    expected_cursor,
                )
                self.canvas.mouseReleaseEvent(
                    mouse_event(
                        QEvent.MouseButtonRelease,
                        drag_target,
                        button=Qt.LeftButton,
                    )
                )
                self.assertEqual(
                    self.canvas.current_cursor(),
                    expected_cursor,
                )

    def test_dragging_inside_overlapping_shapes_still_moves_the_topmost_shape(self):
        self.lower_shape = rectangle("lower", 10, 10, 90, 90)
        self.upper_shape = rectangle("upper", 20, 20, 80, 80)
        self.canvas.load_shapes([self.lower_shape, self.upper_shape])

        start = (50, 50)
        drag_target = (55, 55)
        original_lower_points = list(self.lower_shape.points)

        self.canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove, start))
        self.assertIs(self.canvas.h_shape, self.upper_shape)
        self.assertIsNone(self.canvas.h_vertex)

        self.canvas.mousePressEvent(
            mouse_event(
                QEvent.MouseButtonPress,
                start,
                button=Qt.LeftButton,
                buttons=Qt.LeftButton,
            )
        )
        self.canvas.mouseMoveEvent(
            mouse_event(
                QEvent.MouseMove,
                drag_target,
                buttons=Qt.LeftButton,
            )
        )
        self.canvas.mouseReleaseEvent(
            mouse_event(
                QEvent.MouseButtonRelease,
                drag_target,
                button=Qt.LeftButton,
            )
        )

        self.assertEqual(self.lower_shape.points, original_lower_points)
        self.assertEqual(
            self.upper_shape.points,
            [
                QPointF(25, 25),
                QPointF(85, 25),
                QPointF(85, 85),
                QPointF(25, 85),
            ],
        )

    def test_dragging_each_border_resizes_only_that_border(self):
        cases = (
            ((50, 20), (50, 10), 0,
             [(20, 10), (80, 10), (80, 80), (20, 80)]),
            ((80, 50), (90, 50), 1,
             [(20, 20), (90, 20), (90, 80), (20, 80)]),
            ((50, 80), (50, 90), 2,
             [(20, 20), (80, 20), (80, 90), (20, 90)]),
            ((20, 50), (10, 50), 3,
             [(10, 20), (80, 20), (80, 80), (10, 80)]),
        )

        for start, drag_target, edge, expected_points in cases:
            with self.subTest(edge=edge):
                shape = rectangle("resizable", 20, 20, 80, 80)
                self.canvas.load_shapes([shape])

                self.canvas.mouseMoveEvent(
                    mouse_event(QEvent.MouseMove, start)
                )
                self.assertIs(self.canvas.h_shape, shape)
                self.assertIsNone(self.canvas.h_vertex)
                self.assertEqual(self.canvas.h_edge, edge)

                self.canvas.mousePressEvent(
                    mouse_event(
                        QEvent.MouseButtonPress,
                        start,
                        button=Qt.LeftButton,
                        buttons=Qt.LeftButton,
                    )
                )
                self.canvas.mouseMoveEvent(
                    mouse_event(
                        QEvent.MouseMove,
                        drag_target,
                        buttons=Qt.LeftButton,
                    )
                )
                self.canvas.mouseReleaseEvent(
                    mouse_event(
                        QEvent.MouseButtonRelease,
                        drag_target,
                        button=Qt.LeftButton,
                    )
                )

                self.assertEqual(
                    shape.points,
                    [QPointF(x, y) for x, y in expected_points],
                )

    def test_dragging_border_cannot_cross_the_opposite_border(self):
        shape = rectangle("resizable", 20, 20, 80, 80)
        self.canvas.load_shapes([shape])

        start = (20, 50)
        drag_target = (95, 50)
        self.canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove, start))
        self.canvas.mousePressEvent(
            mouse_event(
                QEvent.MouseButtonPress,
                start,
                button=Qt.LeftButton,
                buttons=Qt.LeftButton,
            )
        )
        self.canvas.mouseMoveEvent(
            mouse_event(
                QEvent.MouseMove,
                drag_target,
                buttons=Qt.LeftButton,
            )
        )
        self.canvas.mouseReleaseEvent(
            mouse_event(
                QEvent.MouseButtonRelease,
                drag_target,
                button=Qt.LeftButton,
            )
        )

        self.assertEqual(
            shape.points,
            [
                QPointF(79, 20),
                QPointF(80, 20),
                QPointF(80, 80),
                QPointF(79, 80),
            ],
        )

    def test_dragging_border_stops_at_the_canvas_boundary(self):
        shape = rectangle("resizable", 20, 20, 80, 80)
        self.canvas.load_shapes([shape])

        start = (50, 20)
        drag_target = (50, -20)
        self.canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove, start))
        self.canvas.mousePressEvent(
            mouse_event(
                QEvent.MouseButtonPress,
                start,
                button=Qt.LeftButton,
                buttons=Qt.LeftButton,
            )
        )
        self.canvas.mouseMoveEvent(
            mouse_event(
                QEvent.MouseMove,
                drag_target,
                buttons=Qt.LeftButton,
            )
        )
        self.canvas.mouseReleaseEvent(
            mouse_event(
                QEvent.MouseButtonRelease,
                drag_target,
                button=Qt.LeftButton,
            )
        )

        self.assertEqual(
            shape.points,
            [
                QPointF(20, 0),
                QPointF(80, 0),
                QPointF(80, 80),
                QPointF(20, 80),
            ],
        )


if __name__ == "__main__":
    unittest.main()
