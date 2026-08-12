import unittest

from PyQt5.QtCore import QPointF

from labelimg.canvas.interaction import CanvasInteraction


class CanvasInteractionTest(unittest.TestCase):
    def setUp(self):
        self.interaction = CanvasInteraction()
        self.first = object()
        self.second = object()

    def test_selection_gesture_owns_threshold_rectangle_and_reset(self):
        self.interaction.begin_selection(
            QPointF(10, 20),
            (self.first,),
        )

        below_threshold = self.interaction.update_selection(
            QPointF(12, 22),
            scale=1.0,
            drag_distance=5,
        )
        above_threshold = self.interaction.update_selection(
            QPointF(30, 50),
            scale=1.0,
            drag_distance=5,
        )

        self.assertIsNone(below_threshold)
        self.assertEqual(above_threshold.left(), 10)
        self.assertEqual(above_threshold.top(), 20)
        self.assertTrue(self.interaction.selection_dragging)

        was_dragging = self.interaction.finish_selection()
        self.assertTrue(was_dragging)
        self.assertIsNone(self.interaction.selection_press_pos)
        self.assertIsNone(self.interaction.selection_rect)

    def test_cancel_selection_returns_original_selection(self):
        self.interaction.begin_selection(
            QPointF(1, 2),
            (self.first, self.second),
        )
        self.interaction.update_selection(
            QPointF(20, 30),
            scale=1.0,
            drag_distance=5,
        )

        original = self.interaction.cancel_selection()

        self.assertEqual(original, (self.first, self.second))
        self.assertIsNone(self.interaction.selection_press_pos)

    def test_right_drag_reports_only_the_threshold_transition(self):
        self.interaction.begin_right_press(QPointF(5, 5), self.first)

        below_threshold = self.interaction.update_right_drag(
            QPointF(7, 7),
            scale=1.0,
            drag_distance=5,
        )
        started = self.interaction.update_right_drag(
            QPointF(15, 15),
            scale=1.0,
            drag_distance=5,
        )
        already_started = self.interaction.update_right_drag(
            QPointF(20, 20),
            scale=1.0,
            drag_distance=5,
        )

        self.assertFalse(below_threshold)
        self.assertTrue(started)
        self.assertFalse(already_started)
        self.assertTrue(self.interaction.right_dragging)

        self.interaction.finish_right_press()
        self.assertIsNone(self.interaction.right_press_shape)
        self.assertFalse(self.interaction.right_dragging)

    def test_hover_target_keeps_vertex_and_edge_mutually_exclusive(self):
        self.interaction.set_hover(self.first, vertex=2)
        self.assertEqual(self.interaction.hover_vertex, 2)
        self.assertIsNone(self.interaction.hover_edge)

        self.interaction.set_hover(self.second, edge=1)
        self.assertIsNone(self.interaction.hover_vertex)
        self.assertEqual(self.interaction.hover_edge, 1)

        with self.assertRaises(ValueError):
            self.interaction.set_hover(self.first, vertex=0, edge=0)

    def test_hover_resolution_prioritises_vertices_edges_then_interiors(self):
        class FakeShape:
            def __init__(self, bounds, vertex=None, edge=None, contains=False):
                self.bounds = bounds
                self.vertex = vertex
                self.edge = edge
                self.contains = contains

            def nearest_vertex(self, _position, _distance):
                return self.vertex

            def contains_point(self, _position):
                return self.contains

            def bounding_rect(self):
                return self.bounds

        from PyQt5.QtCore import QRectF

        lower_vertex = FakeShape(QRectF(0, 0, 20, 20), vertex=(2, 2.0))
        upper_interior = FakeShape(QRectF(0, 0, 20, 20), contains=True)

        _previous, target = self.interaction.update_hover(
            (lower_vertex, upper_interior),
            QPointF(),
            nearest_vertex_hit=lambda shape, _position: shape.vertex,
            nearest_edge_hit=lambda shape, _position: shape.edge,
        )

        self.assertIs(target.shape, lower_vertex)
        self.assertEqual(target.vertex, 2)

        lower_vertex.vertex = None
        lower_vertex.edge = (1, 1.0)
        _previous, target = self.interaction.update_hover(
            (lower_vertex, upper_interior),
            QPointF(),
            nearest_vertex_hit=lambda shape, _position: shape.vertex,
            nearest_edge_hit=lambda shape, _position: shape.edge,
        )

        self.assertIs(target.shape, lower_vertex)
        self.assertEqual(target.edge, 1)

    def test_resolution_chooses_nearest_corner_across_drawing_layers(self):
        from PyQt5.QtCore import QRectF

        class FakeShape:
            def __init__(self, bounds, vertex_hit):
                self.bounds = bounds
                self.vertex_hit = vertex_hit

            def contains_point(self, position):
                return self.bounds.contains(position)

            def bounding_rect(self):
                return self.bounds

        lower = FakeShape(QRectF(0, 0, 100, 100), (0, 1.0))
        upper = FakeShape(QRectF(0, 0, 100, 100), (2, 4.0))

        target = self.interaction.resolve_target(
            (lower, upper),
            QPointF(10, 10),
            nearest_vertex_hit=lambda shape, _position: shape.vertex_hit,
            nearest_edge_hit=lambda _shape, _position: None,
        )

        self.assertIs(target.shape, lower)
        self.assertEqual(target.vertex, 0)

    def test_containment_prefers_innermost_candidate(self):
        from PyQt5.QtCore import QRectF

        class FakeShape:
            def __init__(self, bounds):
                self.bounds = bounds

            def contains_point(self, position):
                return self.bounds.contains(position)

            def bounding_rect(self):
                return self.bounds

        inner = FakeShape(QRectF(30, 30, 20, 20))
        outer = FakeShape(QRectF(0, 0, 100, 100))

        target = self.interaction.resolve_target(
            (inner, outer),
            QPointF(40, 40),
            nearest_vertex_hit=lambda _shape, _position: None,
            nearest_edge_hit=lambda _shape, _position: None,
        )

        self.assertIs(target.shape, inner)

    def test_partial_overlap_prefers_nearest_boundary(self):
        from PyQt5.QtCore import QRectF

        class FakeShape:
            def __init__(self, bounds):
                self.bounds = bounds

            def contains_point(self, position):
                return self.bounds.contains(position)

            def bounding_rect(self):
                return self.bounds

        nearer = FakeShape(QRectF(40, 20, 60, 60))
        farther = FakeShape(QRectF(10, 10, 60, 60))

        target = self.interaction.resolve_target(
            (nearer, farther),
            QPointF(45, 50),
            nearest_vertex_hit=lambda _shape, _position: None,
            nearest_edge_hit=lambda _shape, _position: None,
        )

        self.assertIs(target.shape, nearer)

    def test_geometrically_identical_candidates_choose_topmost(self):
        from PyQt5.QtCore import QRectF

        class FakeShape:
            def __init__(self):
                self.bounds = QRectF(10, 10, 80, 80)

            def contains_point(self, position):
                return self.bounds.contains(position)

            def bounding_rect(self):
                return self.bounds

        lower = FakeShape()
        upper = FakeShape()

        target = self.interaction.resolve_target(
            (lower, upper),
            QPointF(50, 50),
            nearest_vertex_hit=lambda _shape, _position: None,
            nearest_edge_hit=lambda _shape, _position: None,
        )

        self.assertIs(target.shape, upper)


if __name__ == "__main__":
    unittest.main()
