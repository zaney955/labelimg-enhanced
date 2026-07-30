import unittest

from PyQt5.QtCore import QPointF

from labelimg.canvas_interaction import CanvasInteraction


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
            def __init__(self, vertex=None, edge=None, contains=False):
                self.vertex = vertex
                self.edge = edge
                self.contains = contains

            def nearest_vertex(self, _position, _distance):
                return self.vertex

            def contains_point(self, _position):
                return self.contains

        lower_vertex = FakeShape(vertex=2)
        upper_interior = FakeShape(contains=True)

        _previous, target = self.interaction.update_hover(
            (lower_vertex, upper_interior),
            QPointF(),
            vertex_distance=11,
            nearest_edge=lambda shape, _position: shape.edge,
        )

        self.assertIs(target.shape, lower_vertex)
        self.assertEqual(target.vertex, 2)

        lower_vertex.vertex = None
        lower_vertex.edge = 1
        _previous, target = self.interaction.update_hover(
            (lower_vertex, upper_interior),
            QPointF(),
            vertex_distance=11,
            nearest_edge=lambda shape, _position: shape.edge,
        )

        self.assertIs(target.shape, lower_vertex)
        self.assertEqual(target.edge, 1)


if __name__ == "__main__":
    unittest.main()
