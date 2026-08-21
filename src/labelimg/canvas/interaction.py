"""Transient Canvas interaction state and transitions."""

from dataclasses import dataclass, replace

try:
    from PyQt5.QtCore import QPointF, QRectF
except ImportError:
    from PyQt4.QtCore import QPointF, QRectF


@dataclass(frozen=True)
class HoverTarget:
    shape: object = None
    vertex: int | None = None
    edge: int | None = None


@dataclass(frozen=True)
class CanvasContextRequest:
    """One target-scoped request to open Canvas context commands."""

    kind: str
    global_position: object


@dataclass(frozen=True)
class CanvasInteractionSnapshot:
    """Immutable observable state for all transient Canvas gestures."""

    selection_press_pos: object = None
    selection_rect: object = None
    selection_before_drag: tuple = ()
    selection_dragging: bool = False
    selection_target: HoverTarget = HoverTarget()
    right_press_pos: object = None
    right_press_shape: object = None
    hover: HoverTarget = HoverTarget()


class CanvasInteraction:
    """Keep Canvas gesture, drag, hover, and reset invariants local."""

    def __init__(self):
        self._snapshot = CanvasInteractionSnapshot()

    @property
    def snapshot(self):
        return self._snapshot

    @property
    def selection_press_pos(self):
        return self._snapshot.selection_press_pos

    @property
    def selection_rect(self):
        return self._snapshot.selection_rect

    @property
    def selection_before_drag(self):
        return self._snapshot.selection_before_drag

    @property
    def selection_dragging(self):
        return self._snapshot.selection_dragging

    @property
    def selection_target(self):
        return self._snapshot.selection_target

    @property
    def right_press_pos(self):
        return self._snapshot.right_press_pos

    @property
    def right_press_shape(self):
        return self._snapshot.right_press_shape

    @property
    def hover_shape(self):
        return self._snapshot.hover.shape

    @property
    def hover_vertex(self):
        return self._snapshot.hover.vertex

    @property
    def hover_edge(self):
        return self._snapshot.hover.edge

    def begin_selection(self, position, selected, target=None):
        self._snapshot = replace(
            self._snapshot,
            selection_press_pos=QPointF(position),
            selection_rect=None,
            selection_before_drag=tuple(selected),
            selection_dragging=False,
            selection_target=target or HoverTarget(),
        )

    def update_selection(self, position, scale, drag_distance):
        if self.selection_press_pos is None:
            return None
        delta = position - self.selection_press_pos
        distance = delta.manhattanLength() * max(scale, 0.01)
        if not self.selection_dragging and distance < drag_distance:
            return None
        selection_rect = QRectF(
            self.selection_press_pos,
            position,
        ).normalized()
        self._snapshot = replace(
            self._snapshot,
            selection_dragging=True,
            selection_rect=selection_rect,
        )
        return selection_rect

    def finish_selection(self):
        was_dragging = self.selection_dragging
        self._clear_selection()
        return was_dragging

    def cancel_selection(self):
        previous = self.selection_before_drag
        self._clear_selection()
        return previous

    def _clear_selection(self):
        self._snapshot = replace(
            self._snapshot,
            selection_press_pos=None,
            selection_rect=None,
            selection_before_drag=(),
            selection_dragging=False,
            selection_target=HoverTarget(),
        )

    def begin_right_press(self, position, shape):
        self._snapshot = replace(
            self._snapshot,
            right_press_pos=QPointF(position),
            right_press_shape=shape,
        )

    def finish_right_press(self):
        self._snapshot = replace(
            self._snapshot,
            right_press_pos=None,
            right_press_shape=None,
        )

    def set_hover(self, shape=None, vertex=None, edge=None):
        if vertex is not None and edge is not None:
            raise ValueError("hover target cannot be a vertex and an edge")
        self._snapshot = replace(
            self._snapshot,
            hover=HoverTarget(shape, vertex, edge),
        )

    def set_hover_target(self, target):
        self.set_hover(target.shape, target.vertex, target.edge)

    @property
    def hover(self):
        return self._snapshot.hover

    def update_hover(
        self,
        shapes,
        position,
        nearest_vertex_hit,
        nearest_edge_hit,
        distance_tolerance=1e-6,
    ):
        """Resolve and publish the deterministic target at ``position``."""
        previous = self.hover
        target = self.resolve_target(
            shapes,
            position,
            nearest_vertex_hit,
            nearest_edge_hit,
            distance_tolerance,
        )
        self.set_hover_target(target)
        return previous, self.hover

    def resolve_target(
        self,
        shapes,
        position,
        nearest_vertex_hit,
        nearest_edge_hit,
        distance_tolerance=1e-6,
    ):
        """Choose one target from visible box geometry.

        Scene order is bottom-to-top. Corners outrank edges, edges outrank
        interiors, and drawing order is used only for approximate ties.
        """
        shapes = tuple(shapes)
        target = self._nearest_feature_target(
            shapes,
            position,
            nearest_vertex_hit,
            "vertex",
            distance_tolerance,
        )
        if target.shape is not None:
            return target

        target = self._nearest_feature_target(
            shapes,
            position,
            nearest_edge_hit,
            "edge",
            distance_tolerance,
        )
        if target.shape is not None:
            return target

        return self._interior_target(
            shapes,
            position,
            distance_tolerance,
        )

    def resolve_label_target(
        self,
        shapes,
        position,
        label_hit_rect,
        distance_tolerance=1e-6,
    ):
        """Choose one visible label-text target for a label-edit gesture."""
        return self._label_target(
            tuple(shapes),
            position,
            label_hit_rect,
            distance_tolerance,
        )

    @staticmethod
    def _nearest_feature_target(
        shapes,
        position,
        hit_test,
        feature,
        tolerance,
    ):
        best = None
        for layer, shape in enumerate(shapes):
            hit = hit_test(shape, position)
            if hit is None:
                continue
            index, hit_distance = hit
            candidate = (float(hit_distance), layer, shape, index)
            if (
                best is None
                or candidate[0] < best[0] - tolerance
                or (
                    abs(candidate[0] - best[0]) <= tolerance
                    and candidate[1] > best[1]
                )
            ):
                best = candidate
        if best is None:
            return HoverTarget()
        if feature == "vertex":
            return HoverTarget(shape=best[2], vertex=best[3])
        return HoverTarget(shape=best[2], edge=best[3])

    @classmethod
    def _interior_target(cls, shapes, position, tolerance):
        candidates = [
            (layer, shape, shape.bounding_rect())
            for layer, shape in enumerate(shapes)
            if shape.contains_point(position)
        ]
        return cls._rectangle_target(candidates, position, tolerance)

    @classmethod
    def _label_target(cls, shapes, position, label_hit_rect, tolerance):
        candidates = []
        for layer, shape in enumerate(shapes):
            bounds = label_hit_rect(shape)
            if bounds is not None and bounds.contains(position):
                candidates.append((layer, shape, bounds))
        return cls._rectangle_target(candidates, position, tolerance)

    @classmethod
    def _rectangle_target(cls, candidates, position, tolerance):
        if not candidates:
            return HoverTarget()

        innermost = [
            candidate
            for candidate in candidates
            if not any(
                other[1] is not candidate[1]
                and cls._strictly_contains(
                    candidate[2],
                    other[2],
                    tolerance,
                )
                for other in candidates
            )
        ]

        best = None
        for layer, shape, bounds in innermost:
            boundary_distance = min(
                abs(position.x() - bounds.left()),
                abs(bounds.right() - position.x()),
                abs(position.y() - bounds.top()),
                abs(bounds.bottom() - position.y()),
            )
            candidate = (boundary_distance, layer, shape)
            if (
                best is None
                or candidate[0] < best[0] - tolerance
                or (
                    abs(candidate[0] - best[0]) <= tolerance
                    and candidate[1] > best[1]
                )
            ):
                best = candidate
        return HoverTarget(shape=best[2])

    @staticmethod
    def _strictly_contains(outer, inner, tolerance):
        contains = (
            outer.left() <= inner.left() + tolerance
            and outer.top() <= inner.top() + tolerance
            and outer.right() >= inner.right() - tolerance
            and outer.bottom() >= inner.bottom() - tolerance
        )
        strict = (
            outer.left() < inner.left() - tolerance
            or outer.top() < inner.top() - tolerance
            or outer.right() > inner.right() + tolerance
            or outer.bottom() > inner.bottom() + tolerance
        )
        return contains and strict

    def clear_hover(self):
        previous = self.hover_shape
        self.set_hover()
        return previous

    def reset(self):
        self._snapshot = CanvasInteractionSnapshot()
