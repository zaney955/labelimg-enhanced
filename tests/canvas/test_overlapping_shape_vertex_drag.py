import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

from labelimg.canvas.widget import Canvas
from labelimg.canvas.shape import Shape


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
        self.assertIs(
            self.canvas.interaction_snapshot.hover.shape,
            self.lower_shape,
        )
        self.assertEqual(self.canvas.interaction_snapshot.hover.vertex, 2)

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
                self.assertEqual(
                    self.canvas.interaction_snapshot.hover.vertex,
                    vertex,
                )
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

    def test_tiny_shape_center_remains_a_box_move_target(self):
        shape = rectangle("tiny", 40, 40, 52, 52)
        self.canvas.load_shapes([shape])

        self.canvas.mouseMoveEvent(
            mouse_event(QEvent.MouseMove, (46, 46))
        )

        self.assertIs(self.canvas.interaction_snapshot.hover.shape, shape)
        self.assertIsNone(self.canvas.interaction_snapshot.hover.vertex)
        self.assertIsNone(self.canvas.interaction_snapshot.hover.edge)
        self.assertEqual(
            self.canvas.current_cursor(),
            Qt.OpenHandCursor,
        )

    def test_zoomed_corner_does_not_capture_a_pointer_seventy_pixels_away(self):
        self.canvas.scale = 8.0
        self.canvas.resize(800, 800)
        shape = rectangle("zoomed", 20, 20, 80, 80)
        self.canvas.load_shapes([shape])
        corner = self.canvas.image_to_widget(shape[3])

        self.canvas.mouseMoveEvent(
            mouse_event(QEvent.MouseMove, (corner.x() - 70, corner.y()))
        )

        self.assertIsNone(self.canvas.interaction_snapshot.hover.shape)
        self.assertEqual(self.canvas.current_cursor(), Qt.ArrowCursor)

    def test_corner_hit_radius_stays_in_screen_pixels_at_every_zoom(self):
        self.canvas.load_pixmap(QPixmap(1000, 1000))
        directions = ((-1, -1), (1, -1), (1, 1), (-1, 1))
        for scale in (0.125, 0.25, 0.5, 1, 2, 4, 8, 16):
            for view_offset in (QPointF(), QPointF(23, -17)):
                self.canvas.scale = scale
                self.canvas.resize(int(1000 * scale + 100), int(1000 * scale + 100))
                self.canvas.set_view_offset(view_offset)
                self.canvas.set_content_margins(12, 16, 20, 24)
                shape = rectangle("resizable", 200, 200, 800, 800)
                self.canvas.load_shapes([shape])
                for vertex, (dx, dy) in enumerate(directions):
                    with self.subTest(scale=scale, offset=view_offset, vertex=vertex):
                        corner = self.canvas.image_to_widget(shape[vertex])
                        # Ten screen pixels away: inside the 11-pixel handle radius.
                        near = corner + QPointF(dx * 6, dy * 8)
                        self.canvas.mouseMoveEvent(
                            mouse_event(QEvent.MouseMove, (near.x(), near.y()))
                        )
                        self.assertIs(self.canvas.interaction_snapshot.hover.shape, shape)
                        self.assertEqual(self.canvas.interaction_snapshot.hover.vertex, vertex)
                        self.assertEqual(
                            self.canvas.current_cursor(),
                            Qt.SizeFDiagCursor if vertex % 2 == 0 else Qt.SizeBDiagCursor,
                        )

                        # Fifteen pixels away: clear both the handle and old hover.
                        far = corner + QPointF(dx * 9, dy * 12)
                        self.canvas.mouseMoveEvent(
                            mouse_event(QEvent.MouseMove, (far.x(), far.y()))
                        )
                        self.assertIsNone(self.canvas.interaction_snapshot.hover.shape)
                        self.assertEqual(self.canvas.current_cursor(), Qt.ArrowCursor)

    def test_tiny_screen_box_keeps_corner_edge_and_interior_targets_at_every_zoom(self):
        self.canvas.load_pixmap(QPixmap(1000, 1000))
        for scale in (0.125, 0.25, 0.5, 1, 2, 4, 8, 16):
            with self.subTest(scale=scale):
                self.canvas.scale = scale
                shape = rectangle("tiny", 400, 400, 400 + 12 / scale, 400 + 12 / scale)
                self.canvas.load_shapes([shape])
                corner = self.canvas.image_to_widget(shape[0])
                cases = (
                    (QPointF(), 0, None, Qt.SizeFDiagCursor),
                    (QPointF(6, 0), None, 0, Qt.SizeVerCursor),
                    (QPointF(6, 6), None, None, Qt.OpenHandCursor),
                )
                for offset, vertex, edge, cursor in cases:
                    position = corner + offset
                    self.canvas.mouseMoveEvent(
                        mouse_event(QEvent.MouseMove, (position.x(), position.y()))
                    )
                    hover = self.canvas.interaction_snapshot.hover
                    self.assertIs(hover.shape, shape)
                    self.assertEqual(hover.vertex, vertex)
                    self.assertEqual(hover.edge, edge)
                    self.assertEqual(self.canvas.current_cursor(), cursor)

    def test_covered_corner_stays_reachable_at_every_zoom(self):
        self.canvas.load_pixmap(QPixmap(1000, 1000))
        for scale in (0.125, 0.25, 0.5, 1, 2, 4, 8, 16):
            with self.subTest(scale=scale):
                self.canvas.scale = scale
                lower = rectangle("lower", 200, 200, 600, 600)
                upper = rectangle("upper", 500, 500, 900, 900)
                self.canvas.load_shapes([lower, upper])
                position = self.canvas.image_to_widget(lower[2]) + QPointF(9, 0)
                self.canvas.mouseMoveEvent(
                    mouse_event(QEvent.MouseMove, (position.x(), position.y()))
                )
                self.assertIs(self.canvas.interaction_snapshot.hover.shape, lower)
                self.assertEqual(self.canvas.interaction_snapshot.hover.vertex, 2)

    def test_zoomed_corner_drag_and_release_follow_the_pointer(self):
        for scale in (0.25, 2, 8):
            for vertex in range(4):
                with self.subTest(scale=scale, vertex=vertex):
                    self.canvas.scale = scale
                    self.canvas.resize(int(100 * scale), int(100 * scale))
                    shape = rectangle("resizable", 20, 20, 80, 80)
                    self.canvas.load_shapes([shape])
                    original = QPointF(shape[vertex])
                    start = self.canvas.image_to_widget(original)
                    end = start + QPointF(-4, 4)
                    self.canvas.mousePressEvent(mouse_event(
                        QEvent.MouseButtonPress, (start.x(), start.y()),
                        button=Qt.LeftButton, buttons=Qt.LeftButton,
                    ))
                    self.canvas.mouseMoveEvent(mouse_event(
                        QEvent.MouseMove, (end.x(), end.y()), buttons=Qt.LeftButton,
                    ))
                    self.canvas.mouseReleaseEvent(mouse_event(
                        QEvent.MouseButtonRelease, (end.x(), end.y()), button=Qt.LeftButton,
                    ))
                    self.assertEqual(shape[vertex], original + QPointF(-4 / scale, 4 / scale))
                    self.assertIs(self.canvas.interaction_snapshot.hover.shape, shape)
                    self.assertEqual(self.canvas.interaction_snapshot.hover.vertex, vertex)

    def test_tiny_shape_corner_and_edge_remain_resize_targets(self):
        shape = rectangle("tiny", 40, 40, 52, 52)
        self.canvas.load_shapes([shape])

        self.canvas.mouseMoveEvent(
            mouse_event(QEvent.MouseMove, (40, 40))
        )
        self.assertEqual(self.canvas.interaction_snapshot.hover.vertex, 0)
        self.assertEqual(
            self.canvas.current_cursor(),
            Qt.SizeFDiagCursor,
        )

        self.canvas.mouseMoveEvent(
            mouse_event(QEvent.MouseMove, (46, 40))
        )
        self.assertIsNone(self.canvas.interaction_snapshot.hover.vertex)
        self.assertEqual(self.canvas.interaction_snapshot.hover.edge, 0)
        self.assertEqual(
            self.canvas.current_cursor(),
            Qt.SizeVerCursor,
        )

    def test_corner_cursor_tracks_box_flips_during_drag_and_release(self):
        cases = (
            (
                0,
                (20, 20),
                (
                    ((90, 15), Qt.SizeBDiagCursor),
                    ((15, 90), Qt.SizeBDiagCursor),
                    ((90, 90), Qt.SizeFDiagCursor),
                ),
            ),
            (
                1,
                (80, 20),
                (
                    ((10, 15), Qt.SizeFDiagCursor),
                    ((85, 90), Qt.SizeFDiagCursor),
                    ((10, 90), Qt.SizeBDiagCursor),
                ),
            ),
            (
                2,
                (80, 80),
                (
                    ((10, 85), Qt.SizeBDiagCursor),
                    ((85, 10), Qt.SizeBDiagCursor),
                    ((10, 10), Qt.SizeFDiagCursor),
                ),
            ),
            (
                3,
                (20, 80),
                (
                    ((90, 85), Qt.SizeFDiagCursor),
                    ((15, 10), Qt.SizeFDiagCursor),
                    ((90, 10), Qt.SizeBDiagCursor),
                ),
            ),
        )

        for vertex, start, flips in cases:
            for drag_target, expected_cursor in flips:
                with self.subTest(
                    vertex=vertex,
                    drag_target=drag_target,
                ):
                    shape = rectangle("flippable", 20, 20, 80, 80)
                    self.canvas.load_shapes([shape])

                    self.canvas.mouseMoveEvent(
                        mouse_event(QEvent.MouseMove, start)
                    )
                    self.assertEqual(
                        self.canvas.interaction_snapshot.hover.vertex,
                        vertex,
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
        self.assertIs(
            self.canvas.interaction_snapshot.hover.shape,
            self.upper_shape,
        )
        self.assertIsNone(self.canvas.interaction_snapshot.hover.vertex)

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
                self.assertIs(
                    self.canvas.interaction_snapshot.hover.shape,
                    shape,
                )
                self.assertIsNone(
                    self.canvas.interaction_snapshot.hover.vertex
                )
                self.assertEqual(
                    self.canvas.interaction_snapshot.hover.edge,
                    edge,
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
