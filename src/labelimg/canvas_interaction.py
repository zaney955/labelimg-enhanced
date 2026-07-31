"""Transient Canvas interaction state and transitions."""

from dataclasses import dataclass

try:
    from PyQt5.QtCore import QPointF, QRectF
except ImportError:
    from PyQt4.QtCore import QPointF, QRectF


@dataclass(frozen=True)
class HoverTarget:
    shape: object = None
    vertex: int | None = None
    edge: int | None = None


class CanvasInteraction:
    """Keep Canvas gesture, drag, hover, and reset invariants local."""

    def __init__(self):
        self.reset()

    def begin_selection(self, position, selected):
        self.selection_press_pos = QPointF(position)
        self.selection_rect = None
        self.selection_before_drag = tuple(selected)
        self.selection_dragging = False

    def update_selection(self, position, scale, drag_distance):
        if self.selection_press_pos is None:
            return None
        delta = position - self.selection_press_pos
        distance = delta.manhattanLength() * max(scale, 0.01)
        if not self.selection_dragging and distance < drag_distance:
            return None
        self.selection_dragging = True
        self.selection_rect = QRectF(
            self.selection_press_pos,
            position,
        ).normalized()
        return self.selection_rect

    def finish_selection(self):
        was_dragging = self.selection_dragging
        self._clear_selection()
        return was_dragging

    def cancel_selection(self):
        previous = self.selection_before_drag
        self._clear_selection()
        return previous

    def _clear_selection(self):
        self.selection_press_pos = None
        self.selection_rect = None
        self.selection_before_drag = ()
        self.selection_dragging = False

    def begin_right_press(self, position, shape):
        self.right_press_pos = QPointF(position)
        self.right_press_shape = shape
        self.right_dragging = False

    def update_right_drag(self, position, scale, drag_distance):
        if self.right_press_shape is None or self.right_dragging:
            return False
        delta = position - self.right_press_pos
        if (
            delta.manhattanLength() * max(scale, 0.01)
            < drag_distance
        ):
            return False
        self.right_dragging = True
        return True

    def finish_right_press(self):
        self.right_press_pos = None
        self.right_press_shape = None
        self.right_dragging = False

    def set_hover(self, shape=None, vertex=None, edge=None):
        if vertex is not None and edge is not None:
            raise ValueError("hover target cannot be a vertex and an edge")
        self.hover_shape = shape
        self.hover_vertex = vertex
        self.hover_edge = edge

    @property
    def hover(self):
        return HoverTarget(
            self.hover_shape,
            self.hover_vertex,
            self.hover_edge,
        )

    def update_hover(
        self,
        shapes,
        position,
        nearest_vertex,
        nearest_edge,
    ):
        """Resolve vertices before edges before interiors."""
        previous = self.hover
        shapes = tuple(shapes)
        for shape in reversed(shapes):
            vertex = nearest_vertex(shape, position)
            if vertex is not None:
                self.set_hover(shape, vertex=vertex)
                return previous, self.hover
        for shape in reversed(shapes):
            edge = nearest_edge(shape, position)
            if edge is not None:
                self.set_hover(shape, edge=edge)
                return previous, self.hover
        for shape in reversed(shapes):
            if shape.contains_point(position):
                self.set_hover(shape)
                return previous, self.hover
        self.clear_hover()
        return previous, self.hover

    def clear_hover(self):
        previous = self.hover_shape
        self.set_hover()
        return previous

    def reset(self):
        self._clear_selection()
        self.finish_right_press()
        self.set_hover()
