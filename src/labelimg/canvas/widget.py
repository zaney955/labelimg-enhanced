
from PyQt5.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

from labelimg.localization.runtime import tr
from labelimg.ui.risk_glyphs import draw_not_equal_glyph


from labelimg.canvas.shape import Shape
from labelimg.canvas.interaction import CanvasInteraction, HoverTarget
from labelimg.canvas.selection import SelectionSet
from labelimg.canvas.geometry import distance
from labelimg.canvas.near_duplicates import (
    CATEGORY_CONFLICT,
    cluster_bounds,
)

CURSOR_DEFAULT = Qt.ArrowCursor
CURSOR_POINT = Qt.PointingHandCursor
CURSOR_DRAW = Qt.CrossCursor
CURSOR_SELECT = Qt.CrossCursor
CURSOR_MOVE = Qt.ClosedHandCursor
CURSOR_GRAB = Qt.OpenHandCursor
CURSOR_SIZE_HORIZONTAL = Qt.SizeHorCursor
CURSOR_SIZE_VERTICAL = Qt.SizeVerCursor
CURSOR_SIZE_FORWARD_DIAGONAL = Qt.SizeFDiagCursor
CURSOR_SIZE_BACKWARD_DIAGONAL = Qt.SizeBDiagCursor

# class Canvas(QGLWidget):


class Canvas(QWidget):
    zoomRequest = pyqtSignal(int)
    scrollRequest = pyqtSignal(int, int)
    panRequest = pyqtSignal(int, int)
    coordinatesChanged = pyqtSignal(str)
    statusRequest = pyqtSignal(str)
    newShape = pyqtSignal()
    selectionChanged = pyqtSignal(bool)
    shapeMoved = pyqtSignal()
    drawingPolygon = pyqtSignal(bool)
    annotationGestureStarted = pyqtSignal(str)
    annotationGestureFinished = pyqtSignal(str)
    annotationGestureCanceled = pyqtSignal(str)
    hoverShapeChanged = pyqtSignal(object)
    shapeLabelEditRequested = pyqtSignal(object)
    nearDuplicateRequested = pyqtSignal(object, object, object)

    CREATE, EDIT, PAN = list(range(3))

    epsilon = 11.0
    edge_epsilon = 5.0

    def __init__(self, *args, **kwargs):
        super(Canvas, self).__init__(*args, **kwargs)
        # Initialise local state.
        self.mode = self.EDIT
        self.shapes = []
        self.current = None
        self._selection = SelectionSet()
        self._interaction = CanvasInteraction()
        self._external_hover_shapes = tuple()
        self._last_pointer_pos = None
        self._near_duplicate_clusters = tuple()
        self._near_duplicate_marker_hits = tuple()
        self._near_duplicate_focus = None
        self._near_duplicate_focus_shape = None
        self._near_duplicate_hover_cluster = None
        self.selected_shape_copy = None
        self.drawing_line_color = QColor(0, 0, 255)
        self.drawing_rect_color = QColor(0, 0, 255)
        self.line = Shape(line_color=self.drawing_line_color)
        self.prev_point = QPointF()
        self.offsets = QPointF(), QPointF()
        self.scale = 1.0
        self.label_font_size = 8
        self.pixmap = QPixmap()
        self.visible = {}
        self._hide_background = False
        self.hide_background = False
        self._painter = QPainter()
        self._cursor = CURSOR_DEFAULT
        # Menus:
        self.menus = (QMenu(), QMenu())
        # Set widget options.
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.WheelFocus)
        self.verified = False
        self.questioned = False
        self.draw_square = False
        self.multi_selection_mode = False
        self._annotation_gesture_description = None
        self._annotation_gesture_source = None
        self._held_arrow_keys = set()

        # initialisation for panning
        self.pan_initial_pos = QPoint()
        self._pan_dragging = False

    def set_drawing_color(self, qcolor):
        self.drawing_line_color = qcolor
        self.drawing_rect_color = qcolor

    def enterEvent(self, ev):
        self.multi_selection_mode = bool(
            QApplication.keyboardModifiers() & Qt.ControlModifier
        )
        self.override_cursor(
            CURSOR_SELECT
            if self.multi_selection_mode and self.current is None
            else self._cursor
        )

    def leaveEvent(self, ev):
        self.clear_near_duplicate_focus()
        self._set_near_duplicate_hover(None)
        if (
            self.selection_press_pos is None
            and self.right_press_shape is None
            and self._annotation_gesture_source != "mouse"
        ):
            self.un_highlight()
        self.restore_cursor()

    def focusOutEvent(self, ev):
        self.multi_selection_mode = False
        self.restore_cursor()
        if self._held_arrow_keys:
            self._held_arrow_keys.clear()
            self._finish_annotation_gesture()
        super(Canvas, self).focusOutEvent(ev)

    def event(self, ev):
        if (
            ev.type() == QEvent.UngrabMouse
            and self._annotation_gesture_source == "mouse"
        ):
            self.cancel_annotation_gesture()
        return super(Canvas, self).event(ev)

    def isVisible(self, shape):
        return self.visible.get(shape, True)

    def drawing(self):
        return self.mode == self.CREATE

    def editing(self):
        return self.mode == self.EDIT

    def panning(self):
        return self.mode == self.PAN

    def set_mode(self, mode):
        if mode not in (self.CREATE, self.EDIT, self.PAN):
            raise ValueError("Unknown canvas mode: %r" % (mode,))
        self.mode = mode
        if mode != self.CREATE:
            self.current = None
            self.line.points = []
        if mode != self.EDIT:
            self.clear_near_duplicate_focus()
            self._set_near_duplicate_hover(None)
            self.un_highlight()
            self.set_external_hover_shape(None)
            self.de_select_shape()
        self.prev_point = QPointF()
        self._cursor = CURSOR_GRAB if mode == self.PAN else CURSOR_DEFAULT
        self.setCursor(QCursor(self._cursor))
        self.repaint()

    @property
    def near_duplicate_clusters(self):
        return self._near_duplicate_clusters

    @property
    def near_duplicate_focus(self):
        return self._near_duplicate_focus

    def set_near_duplicate_clusters(self, clusters):
        self._near_duplicate_clusters = tuple(clusters)
        if (
            self._near_duplicate_focus is not None
            and self._near_duplicate_focus not in self._near_duplicate_clusters
        ):
            self._near_duplicate_focus = None
            self._near_duplicate_focus_shape = None
        if self._near_duplicate_hover_cluster not in self._near_duplicate_clusters:
            self._near_duplicate_hover_cluster = None
        self._near_duplicate_marker_hits = tuple()
        self.update()

    def set_near_duplicate_focus(self, cluster, shape):
        if cluster not in self._near_duplicate_clusters or shape not in cluster.members:
            self.clear_near_duplicate_focus()
            return
        self._near_duplicate_focus = cluster
        self._near_duplicate_focus_shape = shape
        self.set_selected_shapes((shape,), active_shape=shape)
        self.update()

    def clear_near_duplicate_focus(self):
        if self._near_duplicate_focus is None:
            return False
        self._near_duplicate_focus = None
        self._near_duplicate_focus_shape = None
        self.update()
        return True

    def set_editing(self, value=True):
        self.set_mode(self.EDIT if value else self.CREATE)

    def un_highlight(self):
        hover = self.interaction_snapshot.hover
        if hover.shape:
            hover.shape.highlight_clear()
        self._set_hover()

    def selected_vertex(self):
        return self.interaction_snapshot.hover.vertex is not None

    def vertex_cursor(self, index=None):
        if index is None:
            index = self.interaction_snapshot.hover.vertex
        shape = self.interaction_snapshot.hover.shape
        if (
            shape is not None
            and index is not None
            and len(shape) >= 4
        ):
            point = shape[index]
            opposite = shape[(index + 2) % 4]
            diagonal_product = (
                (point.x() - opposite.x())
                * (point.y() - opposite.y())
            )
            if diagonal_product > 0:
                return CURSOR_SIZE_FORWARD_DIAGONAL
            if diagonal_product < 0:
                return CURSOR_SIZE_BACKWARD_DIAGONAL
        return (
            CURSOR_SIZE_FORWARD_DIAGONAL if index % 2 == 0
            else CURSOR_SIZE_BACKWARD_DIAGONAL
        )

    def selected_edge(self):
        return self.interaction_snapshot.hover.edge is not None

    def selection_count(self):
        return len(self.selected_shapes)

    @property
    def selection_snapshot(self):
        return self._selection.snapshot

    @property
    def selected_shapes(self):
        return list(self._selection.snapshot.selected)

    @property
    def selected_shape(self):
        return self._selection.snapshot.active

    @property
    def interaction_snapshot(self):
        return self._interaction.snapshot

    @property
    def selection_press_pos(self):
        return self._interaction.selection_press_pos

    @property
    def selection_rect(self):
        return self._interaction.selection_rect

    @property
    def selection_before_drag(self):
        return list(self._interaction.selection_before_drag)

    @property
    def selection_dragging(self):
        return self._interaction.selection_dragging

    @property
    def right_press_pos(self):
        return self._interaction.right_press_pos

    @property
    def right_press_shape(self):
        return self._interaction.right_press_shape

    @property
    def right_dragging(self):
        return self._interaction.right_dragging

    def _set_hover(self, shape=None, vertex=None, edge=None):
        previous_shape = self._interaction.hover_shape
        self._interaction.set_hover(shape, vertex=vertex, edge=edge)
        if previous_shape is not shape:
            self.hoverShapeChanged.emit(shape)

    def set_hover_target(self, shape=None, vertex=None, edge=None):
        """Project one coherent hover transition and its Qt side effects."""
        self._set_hover(shape, vertex, edge)
        self.update()

    def set_external_hover_shape(self, shape):
        self.set_external_hover_shapes(() if shape is None else (shape,))

    def set_external_hover_shapes(self, shapes):
        if not self.editing():
            shapes = ()
        else:
            shapes = tuple(
                shape for shape in shapes
                if shape in self.shapes and self.isVisible(shape)
            )
        if self._external_hover_shapes == shapes:
            return
        self._external_hover_shapes = shapes
        self.update()

    @property
    def hover_shapes_for_paint(self):
        if self.selection_dragging:
            return tuple()
        if self.interaction_snapshot.hover.shape is not None:
            shapes = (self.interaction_snapshot.hover.shape,)
        else:
            shapes = self._external_hover_shapes
        return tuple(
            shape for shape in shapes
            if shape in self.shapes and self.isVisible(shape)
        )

    @property
    def hover_shape_for_paint(self):
        shapes = self.hover_shapes_for_paint
        return shapes[0] if len(shapes) == 1 else None

    def set_selected_shapes(self, shapes, active_shape=None, emit=True):
        before = self._selection.snapshot
        after = self._selection.set_scene(
            tuple(self.shapes),
            selected=tuple(
                shape for shape in shapes if shape in self.shapes
            ),
            active=active_shape,
        )
        self._project_selection(before, after, emit)

    def _project_selection(self, before, after, emit=True):
        selected_ids = {id(shape) for shape in after.selected}
        for shape in self.shapes:
            shape.selected = id(shape) in selected_ids
        self.set_hiding(bool(after.selected))
        changed = (
            before.selected != after.selected
            or before.active is not after.active
        )
        if emit and changed:
            self.selectionChanged.emit(bool(after.selected))
        self.update()

    def clear_selection(self, emit=True):
        self.set_selected_shapes([], emit=emit)

    def set_multi_selection_mode(self, enabled):
        self.multi_selection_mode = bool(enabled)
        if self.current is not None:
            return
        if self.multi_selection_mode and self.current is None:
            hover_shape = self.interaction_snapshot.hover.shape
            if hover_shape is not None:
                hover_shape.highlight_clear()
            self.override_cursor(CURSOR_SELECT)
            self.update()
        elif not self.selection_dragging:
            self._cursor = CURSOR_DEFAULT
            self.restore_cursor()
            if self._last_pointer_pos is not None and self.editing():
                target = self._refresh_hover(self._last_pointer_pos)
                self._override_target_cursor(target)

    def _override_target_cursor(self, target):
        if target.vertex is not None:
            self.override_cursor(self.vertex_cursor(target.vertex))
        elif target.edge is not None:
            self.override_cursor(
                CURSOR_SIZE_VERTICAL
                if target.edge % 2 == 0
                else CURSOR_SIZE_HORIZONTAL
            )
        elif target.shape is not None:
            self.override_cursor(CURSOR_GRAB)
        else:
            self.override_cursor(CURSOR_DEFAULT)

    def multi_selection_requested(self, ev):
        return (
            self.multi_selection_mode
            or bool(ev.modifiers() & Qt.ControlModifier)
        )

    def resolve_pointer_target(self, point):
        if not self.editing():
            return HoverTarget()
        visible_shapes = [
            shape for shape in self.shapes if self.isVisible(shape)
        ]
        return self._interaction.resolve_target(
            visible_shapes,
            point,
            self.nearest_vertex_hit,
            self.nearest_edge_hit,
            0.5 / max(self.scale, 0.01),
        )

    def resolve_label_edit_target(self, point):
        if not self.editing():
            return HoverTarget()
        visible_shapes = [
            shape for shape in self.shapes if self.isVisible(shape)
        ]
        return self._interaction.resolve_label_target(
            visible_shapes,
            point,
            label_hit_rect=lambda shape: shape.label_hit_rect(
                scale=self.scale,
                font_size=self.label_font_size,
            ),
            distance_tolerance=0.5 / max(self.scale, 0.01),
        )

    def _apply_hover_target(self, target, suppress_handles=False):
        previous = self._interaction.hover
        if previous.shape is not None and previous.vertex is not None:
            previous.shape.highlight_clear()
        self._set_hover(target.shape, target.vertex, target.edge)
        if (
            target.shape is not None
            and target.vertex is not None
            and not suppress_handles
        ):
            target.shape.highlight_vertex(
                target.vertex,
                target.shape.MOVE_VERTEX,
            )
        self.update()

    def _refresh_hover(self, point, suppress_handles=False):
        target = self.resolve_pointer_target(point)
        self._apply_hover_target(target, suppress_handles)
        return target

    def begin_selection_gesture(self, pos):
        target = self.resolve_pointer_target(pos)
        self._apply_hover_target(target, suppress_handles=True)
        self._interaction.begin_selection(
            pos,
            self.selected_shapes,
            target=target,
        )
        self.override_cursor(CURSOR_SELECT)

    def update_selection_gesture(self, pos):
        if self.selection_press_pos is None:
            return False

        was_dragging = self.selection_dragging
        selection_rect = self._interaction.update_selection(
            pos,
            self.scale,
            QApplication.startDragDistance(),
        )
        if selection_rect is None:
            return True
        if not was_dragging:
            self._apply_hover_target(HoverTarget())

        contained = [
            shape for shape in self.shapes
            if self.isVisible(shape)
            and selection_rect.contains(shape.bounding_rect())
        ]
        active_shape = contained[-1] if contained else None
        self.set_selected_shapes(
            contained,
            active_shape=active_shape,
        )
        self.update()
        return True

    def finish_selection_gesture(self, pos, control_down=False):
        if self.selection_press_pos is None:
            return False

        if self.selection_dragging:
            self.update_selection_gesture(pos)
        else:
            self.ctrl_click_shape(
                pos,
                target=self._interaction.selection_target,
            )

        self._interaction.finish_selection()
        if self.multi_selection_mode:
            self.override_cursor(CURSOR_SELECT)
        else:
            self._cursor = CURSOR_DEFAULT
            self.restore_cursor()
        self._refresh_hover(pos, suppress_handles=control_down)
        self.update()
        return True

    def cancel_selection_gesture(self):
        if self.selection_press_pos is None:
            return False

        previous = self._interaction.cancel_selection()
        self.set_selected_shapes(previous)
        if self.multi_selection_mode:
            self.override_cursor(CURSOR_SELECT)
        else:
            self._cursor = CURSOR_DEFAULT
            self.restore_cursor()
        if self._last_pointer_pos is not None:
            self._refresh_hover(
                self._last_pointer_pos,
                suppress_handles=self.multi_selection_mode,
            )
        self.update()
        return True

    def ctrl_click_shape(self, point, target=None):
        target = target or self.resolve_pointer_target(point)
        shape = target.shape
        if shape is None:
            return None

        before = self._selection.snapshot
        after = self._selection.toggle(shape, active=shape)
        self._project_selection(before, after)
        return shape

    def mouseMoveEvent(self, ev):
        """Update line with last point and current coordinates."""
        pos = self.transform_pos(ev.pos())
        self._last_pointer_pos = QPointF(pos)

        if (
            self._near_duplicate_focus is not None
            and not self._near_duplicate_focus_contains(ev.pos(), pos)
        ):
            self.clear_near_duplicate_focus()

        if self.pixmap and not self.pixmap.isNull():
            self._emit_coordinates(pos)

        if self.editing() and not ev.buttons():
            marker = self._near_duplicate_marker_at(ev.pos())
            if marker is not None:
                self._set_near_duplicate_hover(marker)
                self.un_highlight()
                self.override_cursor(CURSOR_POINT)
                self.setToolTip(self._near_duplicate_tooltip(marker))
                return
        self._set_near_duplicate_hover(None)

        if self._pan_dragging:
            delta = ev.globalPos() - self.pan_initial_pos
            self.pan_canvas(delta)
            self.pan_initial_pos = ev.globalPos()
            self.update()
            return

        if (
            self.selection_press_pos is not None
            and Qt.LeftButton & ev.buttons()
        ):
            self.update_selection_gesture(pos)
            return

        if (
            self.current is None
            and self.multi_selection_requested(ev)
            and not ev.buttons()
        ):
            target = self._refresh_hover(pos, suppress_handles=True)
            if target.shape is not None:
                self.setToolTip(
                    tr("canvas.ctrlToggle", label=target.shape.label)
                )
            self.override_cursor(CURSOR_SELECT)
            return

        # Polygon drawing.
        if self.drawing():
            self.override_cursor(CURSOR_DRAW)
            if self.current:
                # Display annotation width and height while drawing
                self._emit_coordinates(pos, self.current)

                color = self.drawing_line_color
                if self.out_of_pixmap(pos):
                    # Don't allow the user to draw outside the pixmap.
                    # Clip the coordinates to 0 or max,
                    # if they are outside the range [0, max]
                    size = self.pixmap.size()
                    clipped_x = min(max(0, pos.x()), size.width())
                    clipped_y = min(max(0, pos.y()), size.height())
                    pos = QPointF(clipped_x, clipped_y)
                elif len(self.current) > 1 and self.close_enough(pos, self.current[0]):
                    # Attract line to starting point and colorise to alert the
                    # user:
                    pos = self.current[0]
                    color = self.current.line_color
                    self.override_cursor(CURSOR_POINT)
                    self.current.highlight_vertex(0, Shape.NEAR_VERTEX)

                if self.draw_square:
                    init_pos = self.current[0]
                    min_x = init_pos.x()
                    min_y = init_pos.y()
                    min_size = min(abs(pos.x() - min_x), abs(pos.y() - min_y))
                    direction_x = -1 if pos.x() - min_x < 0 else 1
                    direction_y = -1 if pos.y() - min_y < 0 else 1
                    self.line[1] = QPointF(min_x + direction_x * min_size, min_y + direction_y * min_size)
                else:
                    self.line[1] = pos

                self.line.line_color = color
                self.prev_point = QPointF()
                self.current.highlight_clear()
            else:
                self.prev_point = pos
            self.repaint()
            return

        # Polygon copy moving.
        if Qt.RightButton & ev.buttons():
            if self.right_press_shape is None:
                return
            if self._interaction.update_right_drag(
                pos,
                self.scale,
                QApplication.startDragDistance(),
            ):
                if len(self.selected_shapes) > 1:
                    self.set_selected_shapes(
                        [self.right_press_shape],
                        active_shape=self.right_press_shape,
                    )
                else:
                    self.set_selected_shapes(
                        self.selected_shapes,
                        active_shape=self.right_press_shape,
                    )
                self.selected_shape_copy = self.selected_shape.copy()
                self.prev_point = QPointF(self.right_press_pos)

            if self.selected_shape_copy and self.prev_point:
                self.override_cursor(CURSOR_MOVE)
                self.bounded_move_shape(self.selected_shape_copy, pos)
                self.repaint()
            return

        # Polygon/Vertex moving.
        if Qt.LeftButton & ev.buttons():
            if self.selected_vertex():
                self.bounded_move_vertex(pos)
                self.override_cursor(self.vertex_cursor())
                self.shapeMoved.emit()
                self.repaint()

                # Display annotation width and height while moving vertex
                self._emit_coordinates(
                    pos, self.interaction_snapshot.hover.shape
                )
            elif self.selected_edge():
                self.bounded_move_edge(pos)
                self.shapeMoved.emit()
                self.repaint()

                # Display annotation width and height while moving edge
                self._emit_coordinates(
                    pos, self.interaction_snapshot.hover.shape
                )
            elif self.selected_shape and self.prev_point:
                self.override_cursor(CURSOR_MOVE)
                self.bounded_move_shape(self.selected_shape, pos)
                self.shapeMoved.emit()
                self.repaint()

                # Display annotation width and height while moving shape
                self._emit_coordinates(pos, self.selected_shape)
            else:
                # pan
                delta = ev.globalPos() - self.pan_initial_pos
                self.pan_canvas(delta)
                self.pan_initial_pos = ev.globalPos()
                self.update()
            return

        # Resolve one geometry-only target shared by every pointer gesture.
        self.setToolTip(tr("canvas.image"))
        target = self._refresh_hover(pos)
        if target.vertex is not None:
            self.override_cursor(self.vertex_cursor(target.vertex))
            self.setToolTip(tr("canvas.movePoint"))
            self.setStatusTip(self.toolTip())
        elif target.edge is not None:
            self.setToolTip(
                tr("canvas.resizeShape", label=target.shape.label)
            )
            self.setStatusTip(self.toolTip())
            self.override_cursor(
                CURSOR_SIZE_VERTICAL
                if target.edge % 2 == 0
                else CURSOR_SIZE_HORIZONTAL
            )
        elif target.shape is not None:
            self.setToolTip(
                tr("canvas.moveShape", label=target.shape.label)
            )
            self.setStatusTip(self.toolTip())
            self.override_cursor(CURSOR_GRAB)
            self._emit_coordinates(pos, target.shape)
        else:
            self.override_cursor(CURSOR_DEFAULT)

    def mousePressEvent(self, ev):
        pos = self.transform_pos(ev.pos())
        self._last_pointer_pos = QPointF(pos)

        if ev.button() == Qt.LeftButton and self.editing():
            cluster = self._near_duplicate_marker_at(ev.pos())
            if cluster is not None:
                preferred = self._near_duplicate_preferred_shape(cluster)
                self.nearDuplicateRequested.emit(
                    cluster,
                    ev.globalPos(),
                    preferred,
                )
                ev.accept()
                return
            self.clear_near_duplicate_focus()

        if ev.button() == Qt.MiddleButton or (
            ev.button() == Qt.LeftButton and self.panning()
        ):
            self._pan_dragging = True
            self.pan_initial_pos = ev.globalPos()
            QApplication.setOverrideCursor(QCursor(Qt.ClosedHandCursor))
            ev.accept()
            return

        if ev.button() == Qt.LeftButton:
            if (
                self.current is None
                and self.multi_selection_requested(ev)
            ):
                self.begin_selection_gesture(pos)
            elif self.drawing():
                self.handle_drawing(pos)
            else:
                target = self.resolve_pointer_target(pos)
                self._apply_hover_target(target)
                selection = self.select_shape_point(pos, target=target)
                self.prev_point = pos
                if selection is not None:
                    description = (
                        "Resize box"
                        if self.selected_vertex() or self.selected_edge()
                        else "Move box"
                    )
                    self._begin_annotation_gesture(
                        description, source="mouse"
                    )

                if selection is None:
                    # pan
                    QApplication.setOverrideCursor(QCursor(Qt.OpenHandCursor))
                    self.pan_initial_pos = ev.globalPos()

        elif ev.button() == Qt.RightButton and self.editing():
            target = self.resolve_pointer_target(pos)
            self._apply_hover_target(target)
            shape = target.shape
            if shape is not None:
                if shape not in self.selected_shapes:
                    self.set_selected_shapes(
                        [shape],
                        active_shape=shape,
                    )
                else:
                    self.set_selected_shapes(
                        self.selected_shapes,
                        active_shape=shape,
                    )
                self.calculate_offsets(shape, pos)
                self.prev_point = pos
            self._interaction.begin_right_press(pos, shape)
        self.update()

    def mouseReleaseEvent(self, ev):
        self._last_pointer_pos = self.transform_pos(ev.pos())
        if self._pan_dragging and ev.button() in (
            Qt.MiddleButton, Qt.LeftButton
        ):
            self._pan_dragging = False
            QApplication.restoreOverrideCursor()
            if self.panning():
                self.override_cursor(CURSOR_GRAB)
            ev.accept()
            return
        if ev.button() == Qt.RightButton:
            menu = self.menus[bool(self.selected_shape_copy)]
            self.restore_cursor()
            if not menu.exec_(self.mapToGlobal(ev.pos()))\
               and self.selected_shape_copy:
                # Cancel the move by deleting the shadow copy.
                self.selected_shape_copy = None
                self.repaint()
            self._interaction.finish_right_press()
            if self.editing():
                self._refresh_hover(self.transform_pos(ev.pos()))
        elif (
            ev.button() == Qt.LeftButton
            and self.selection_press_pos is not None
        ):
            pos = self.transform_pos(ev.pos())
            self.finish_selection_gesture(
                pos,
                control_down=self.multi_selection_requested(ev),
            )
        elif ev.button() == Qt.LeftButton and self.selected_shape:
            if self.selected_vertex():
                self.override_cursor(self.vertex_cursor())
            elif self.selected_edge():
                self.override_cursor(
                    CURSOR_SIZE_VERTICAL
                    if self.interaction_snapshot.hover.edge % 2 == 0
                    else CURSOR_SIZE_HORIZONTAL
                )
            else:
                self.override_cursor(CURSOR_GRAB)
        elif ev.button() == Qt.LeftButton:
            pos = self.transform_pos(ev.pos())
            if self.drawing():
                self.handle_drawing(pos)
            else:
                # pan
                QApplication.restoreOverrideCursor()
        if ev.button() == Qt.LeftButton:
            self._finish_annotation_gesture()
            if (
                self.editing()
                and self.selection_press_pos is None
            ):
                self._refresh_hover(
                    self.transform_pos(ev.pos()),
                    suppress_handles=self.multi_selection_requested(ev),
                )

    def end_move(self, copy=False):
        assert self.selected_shape and self.selected_shape_copy
        shape = self.selected_shape_copy
        # del shape.fill_color
        # del shape.line_color
        if copy:
            self.shapes.append(shape)
            self.set_selected_shapes([shape], active_shape=shape)
        else:
            self.selected_shape.points = [p for p in shape.points]
        self.selected_shape_copy = None

    def hide_background_shapes(self, value):
        self.hide_background = value
        if self.selected_shapes:
            # Only hide other shapes if there is a current selection.
            # Otherwise the user will not be able to select a shape.
            self.set_hiding(True)
            self.repaint()

    def handle_drawing(self, pos):
        if self.current and self.current.reach_max_points() is False:
            init_pos = self.current[0]
            min_x = init_pos.x()
            min_y = init_pos.y()
            target_pos = self.line[1]
            max_x = target_pos.x()
            max_y = target_pos.y()
            self.current.add_point(QPointF(max_x, min_y))
            self.current.add_point(target_pos)
            self.current.add_point(QPointF(min_x, max_y))
            self.finalise()
        elif not self.out_of_pixmap(pos):
            self.current = Shape()
            self.current.add_point(pos)
            self.line.points = [pos, pos]
            self.set_hiding()
            self.drawingPolygon.emit(True)
            self.update()

    def set_hiding(self, enable=True):
        self._hide_background = self.hide_background if enable else False

    def can_close_shape(self):
        return self.drawing() and self.current and len(self.current) > 2

    def mouseDoubleClickEvent(self, ev):
        # We need at least 4 points here, since the mousePress handler
        # adds an extra one before this handler is called.
        if self.can_close_shape() and len(self.current) > 3:
            self.current.pop_point()
            self.finalise()
            ev.accept()
            return
        if (
            self.editing()
            and ev.button() == Qt.LeftButton
            and ev.modifiers() == Qt.NoModifier
        ):
            position = self.transform_pos(ev.pos())
            target = self.resolve_pointer_target(position)
            box_target_hit = target.shape is not None
            if target.shape is None:
                target = self.resolve_label_edit_target(position)
            if target.shape is not None:
                if box_target_hit:
                    self._apply_hover_target(target)
                self.select_shape(target.shape)
                # The second press in a Qt double-click has already opened a
                # no-op Move/Resize gesture. Close it before the modal label
                # editor starts its own annotation transaction.
                self._finish_annotation_gesture()
                self.shapeLabelEditRequested.emit(target.shape)
                ev.accept()
                return
        super(Canvas, self).mouseDoubleClickEvent(ev)

    def select_shape(self, shape):
        self.set_selected_shapes([shape], active_shape=shape)

    def select_shape_point(self, point, target=None):
        """Replace selection with the deterministic target at ``point``."""
        target = target or self.resolve_pointer_target(point)
        shape = target.shape
        if shape is None:
            self.clear_selection()
            return None

        if target.vertex is not None:
            index = target.vertex
            shape.highlight_vertex(index, shape.MOVE_VERTEX)
            self.select_shape(shape)
        elif target.edge is not None:
            self.select_shape(shape)
        else:
            self.select_shape(shape)
        self.calculate_offsets(shape, point)
        return shape

    def calculate_offsets(self, shape, point):
        rect = shape.bounding_rect()
        x1 = rect.x() - point.x()
        y1 = rect.y() - point.y()
        x2 = (rect.x() + rect.width()) - point.x()
        y2 = (rect.y() + rect.height()) - point.y()
        self.offsets = QPointF(x1, y1), QPointF(x2, y2)

    def snap_point_to_canvas(self, x, y):
        """
        Moves a point x,y to within the boundaries of the canvas.
        :return: (x,y,snapped) where snapped is True if x or y were changed, False if not.
        """
        if x < 0 or x > self.pixmap.width() or y < 0 or y > self.pixmap.height():
            x = max(x, 0)
            y = max(y, 0)
            x = min(x, self.pixmap.width())
            y = min(y, self.pixmap.height())
            return x, y, True

        return x, y, False

    def resize_hit_tolerance(self, shape, tolerance):
        """Keep a distinct move target inside even the smallest rectangles."""
        if len(shape) != 4:
            return tolerance
        bounds = shape.bounding_rect()
        return min(
            tolerance,
            max(0.0, min(bounds.width(), bounds.height()) / 4.0),
        )

    def nearest_vertex(self, shape, point):
        hit = self.nearest_vertex_hit(shape, point)
        return hit[0] if hit is not None else None

    def nearest_vertex_hit(self, shape, point):
        tolerance = self.resize_hit_tolerance(shape, self.epsilon)
        nearest = None
        for index, vertex in enumerate(shape.points):
            point_distance = distance(vertex - point)
            if (
                point_distance <= tolerance
                and (
                    nearest is None
                    or point_distance < nearest[1]
                )
            ):
                nearest = (index, point_distance)
        return nearest

    def nearest_edge(self, shape, point):
        """Return the nearest rectangle edge within its resize tolerance."""
        hit = self.nearest_edge_hit(shape, point)
        return hit[0] if hit is not None else None

    def nearest_edge_hit(self, shape, point):
        """Return the nearest eligible edge and its geometric distance."""
        if len(shape) != 4:
            return None

        tolerance = self.resize_hit_tolerance(
            shape,
            self.edge_epsilon / max(self.scale, 0.01),
        )
        nearest = None
        nearest_distance = tolerance
        for index in range(4):
            start = shape[index]
            end = shape[(index + 1) % 4]
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            length_squared = dx * dx + dy * dy
            if length_squared == 0:
                continue

            projection = (
                (point.x() - start.x()) * dx
                + (point.y() - start.y()) * dy
            ) / length_squared
            projection = min(max(projection, 0.0), 1.0)
            nearest_x = start.x() + projection * dx
            nearest_y = start.y() + projection * dy
            point_distance = (
                (point.x() - nearest_x) ** 2
                + (point.y() - nearest_y) ** 2
            ) ** 0.5
            if point_distance <= nearest_distance:
                nearest = (index, point_distance)
                nearest_distance = point_distance
        return nearest

    def bounded_move_vertex(self, pos):
        hover = self.interaction_snapshot.hover
        index, shape = hover.vertex, hover.shape
        point = shape[index]
        if self.out_of_pixmap(pos):
            size = self.pixmap.size()
            clipped_x = min(max(0, pos.x()), size.width())
            clipped_y = min(max(0, pos.y()), size.height())
            pos = QPointF(clipped_x, clipped_y)

        if self.draw_square:
            opposite_point_index = (index + 2) % 4
            opposite_point = shape[opposite_point_index]

            min_size = min(abs(pos.x() - opposite_point.x()), abs(pos.y() - opposite_point.y()))
            direction_x = -1 if pos.x() - opposite_point.x() < 0 else 1
            direction_y = -1 if pos.y() - opposite_point.y() < 0 else 1
            shift_pos = QPointF(opposite_point.x() + direction_x * min_size - point.x(),
                                opposite_point.y() + direction_y * min_size - point.y())
        else:
            shift_pos = pos - point

        shape.move_vertex_by(index, shift_pos)

        left_index = (index + 1) % 4
        right_index = (index + 3) % 4
        left_shift = None
        right_shift = None
        if index % 2 == 0:
            right_shift = QPointF(shift_pos.x(), 0)
            left_shift = QPointF(0, shift_pos.y())
        else:
            left_shift = QPointF(shift_pos.x(), 0)
            right_shift = QPointF(0, shift_pos.y())
        shape.move_vertex_by(right_index, right_shift)
        shape.move_vertex_by(left_index, left_shift)

    def bounded_move_edge(self, pos):
        """Move one rectangle edge while preserving its opposite edge."""
        hover = self.interaction_snapshot.hover
        edge, shape = hover.edge, hover.shape
        first_index = edge
        second_index = (edge + 1) % 4
        opposite_first = (edge + 2) % 4
        opposite_second = (edge + 3) % 4
        vertical_coordinate = edge % 2 == 0

        if vertical_coordinate:
            coordinate = min(max(0.0, pos.y()), float(self.pixmap.height()))
            current = (
                shape[first_index].y() + shape[second_index].y()
            ) / 2.0
            opposite = (
                shape[opposite_first].y() + shape[opposite_second].y()
            ) / 2.0
        else:
            coordinate = min(max(0.0, pos.x()), float(self.pixmap.width()))
            current = (
                shape[first_index].x() + shape[second_index].x()
            ) / 2.0
            opposite = (
                shape[opposite_first].x() + shape[opposite_second].x()
            ) / 2.0

        if current < opposite:
            coordinate = min(coordinate, opposite - 1.0)
        elif current > opposite:
            coordinate = max(coordinate, opposite + 1.0)

        for index in (first_index, second_index):
            point = shape[index]
            if vertical_coordinate:
                shift = QPointF(0.0, coordinate - point.y())
            else:
                shift = QPointF(coordinate - point.x(), 0.0)
            shape.move_vertex_by(index, shift)

    def bounded_move_shape(self, shape, pos):
        if self.out_of_pixmap(pos):
            return False  # No need to move
        o1 = pos + self.offsets[0]
        if self.out_of_pixmap(o1):
            pos -= QPointF(min(0, o1.x()), min(0, o1.y()))
        o2 = pos + self.offsets[1]
        if self.out_of_pixmap(o2):
            pos += QPointF(min(0, self.pixmap.width() - o2.x()),
                           min(0, self.pixmap.height() - o2.y()))
        # The next line tracks the new position of the cursor
        # relative to the shape, but also results in making it
        # a bit "shaky" when nearing the border and allows it to
        # go outside of the shape's area for some reason. XXX
        # self.calculateOffsets(self.selectedShape, pos)
        dp = pos - self.prev_point
        if dp:
            shape.move_by(dp)
            self.prev_point = pos
            return True
        return False

    def de_select_shape(self):
        self.clear_selection()

    def delete_selected(self):
        return self.delete_shapes(self.selected_shapes)

    def delete_shapes(self, shapes):
        target_set = set(shapes)
        removed = [
            shape for shape in self.shapes
            if shape in target_set
        ]
        if not removed:
            return []

        if self.interaction_snapshot.hover.shape in target_set:
            self.un_highlight()
        if any(shape in target_set for shape in self._external_hover_shapes):
            self.set_external_hover_shapes(
                shape for shape in self._external_hover_shapes
                if shape not in target_set
            )

        for shape in removed:
            shape.selected = False
        self.shapes = [
            shape for shape in self.shapes
            if shape not in target_set
        ]
        before = self._selection.snapshot
        remaining_selected = tuple(
            shape for shape in before.selected
            if shape not in target_set
        )
        after = self._selection.set_scene(
            tuple(self.shapes),
            selected=remaining_selected,
            active=(
                before.active
                if before.active in remaining_selected
                else None
            ),
        )
        self._project_selection(before, after)
        return removed

    def copy_selected_shape(self):
        copies = self.copy_selected_shapes()
        return copies[0] if len(copies) == 1 else None

    def copy_selected_shapes(self):
        originals = [
            shape for shape in self.shapes
            if shape in self.selected_shapes
        ]
        if not originals:
            return []

        copies = [shape.copy() for shape in originals]
        self.shapes.extend(copies)
        for shape in copies:
            self.bounded_shift_shape(shape)
        self.set_selected_shapes(
            copies,
            active_shape=copies[-1],
        )
        return copies

    def bounded_shift_shape(self, shape):
        # Try to move in one direction, and if it fails in another.
        # Give up if both fail.
        point = shape[0]
        offset = QPointF(2.0, 2.0)
        self.calculate_offsets(shape, point)
        self.prev_point = point
        if not self.bounded_move_shape(shape, point - offset):
            self.bounded_move_shape(shape, point + offset)

    def paintEvent(self, event):
        if not self.pixmap:
            return super(Canvas, self).paintEvent(event)

        p = self._painter
        p.begin(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.HighQualityAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        p.scale(self.scale, self.scale)
        p.translate(self.offset_to_center())

        p.drawPixmap(0, 0, self.pixmap)
        Shape.scale = self.scale
        Shape.label_font_size = self.label_font_size
        hover_shapes = set(
            self.hover_shapes_for_paint
            if self.editing()
            else ()
        )
        for shape in self.shapes:
            if (
                (
                    shape.selected
                    or not self._hide_background
                    or shape in hover_shapes
                )
                and self.isVisible(shape)
            ):
                shape.fill = shape.selected
                peer_in_focus = (
                    self._near_duplicate_focus is not None
                    and shape in self._near_duplicate_focus.members
                    and shape is not self._near_duplicate_focus_shape
                )
                selected_focus_member = (
                    self._near_duplicate_focus is not None
                    and shape is self._near_duplicate_focus_shape
                )
                if peer_in_focus:
                    p.save()
                    p.setOpacity(0.20)
                if shape in hover_shapes:
                    paint_kwargs = {
                        "outline_style": Qt.CustomDashLine,
                        "outline_dash_pattern": Shape.hover_dash_pattern,
                    }
                    if peer_in_focus:
                        paint_kwargs["paint_label"] = False
                    elif selected_focus_member:
                        paint_kwargs["paint_label"] = True
                    shape.paint(p, **paint_kwargs)
                else:
                    if peer_in_focus:
                        shape.paint(p, paint_label=False)
                    elif selected_focus_member:
                        shape.paint(p, paint_label=True)
                    else:
                        shape.paint(p)
                if peer_in_focus:
                    p.restore()
        if self.current:
            self.current.paint(p)
            self.line.paint(p)
        if self.selected_shape_copy:
            self.selected_shape_copy.paint(p)
        if self.selection_rect is not None:
            p.save()
            selection_color = QColor(0, 120, 215, 200)
            selection_pen = QPen(
                selection_color,
                1.0 / max(self.scale, 0.01),
                Qt.DashLine,
            )
            p.setPen(selection_pen)
            p.setBrush(QColor(0, 120, 215, 35))
            p.drawRect(self.selection_rect)
            p.restore()

        # Paint rect
        if self.current is not None and len(self.line) == 2:
            left_top = self.line[0]
            right_bottom = self.line[1]
            rect_width = right_bottom.x() - left_top.x()
            rect_height = right_bottom.y() - left_top.y()
            p.setPen(self.drawing_rect_color)
            brush = QBrush(Qt.BDiagPattern)
            p.setBrush(brush)
            p.drawRect(int(round(left_top.x())), int(round(left_top.y())),
                       int(round(rect_width)), int(round(rect_height)))

        if self.drawing() and not self.prev_point.isNull() and not self.out_of_pixmap(self.prev_point):
            p.setPen(QColor(0, 0, 0))
            p.drawLine(int(round(self.prev_point.x())), 0,
                       int(round(self.prev_point.x())), self.pixmap.height())
            p.drawLine(0, int(round(self.prev_point.y())),
                       self.pixmap.width(), int(round(self.prev_point.y())))

        p.save()
        p.resetTransform()
        self._paint_near_duplicate_markers(p)
        p.restore()

        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(
            self.backgroundRole(),
            self.status_background_color(),
        )
        self.setPalette(pal)

        p.end()

    def _paint_near_duplicate_markers(self, painter):
        hits = self._near_duplicate_marker_layout()
        self._near_duplicate_marker_hits = tuple(hits)
        for rect, cluster, anchor in hits:
            conflict = cluster.risk == CATEGORY_CONFLICT
            color = self._near_duplicate_marker_color(
                cluster,
                hovered=cluster is self._near_duplicate_hover_cluster,
            )
            foreground = QColor("white")
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            if self._near_duplicate_marker_needs_leader(rect, anchor):
                painter.setPen(QPen(color, 1.3, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(
                    anchor,
                    self._leader_destination(rect, anchor),
                )
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 5, 5)
            icon_rect = QRectF(rect.left() + 5, rect.top() + 4, 12, 12)
            painter.setPen(QPen(foreground, 1.3, Qt.SolidLine))
            painter.setBrush(Qt.NoBrush)
            if conflict:
                draw_not_equal_glyph(
                    painter,
                    icon_rect,
                    foreground,
                    width=1.3,
                )
            else:
                painter.drawRect(icon_rect.adjusted(0, 2, -3, -1))
                painter.drawRect(icon_rect.adjusted(3, -1, 0, -4))
            font = QFont(painter.font())
            font.setBold(True)
            font.setPointSize(8)
            painter.setFont(font)
            painter.setPen(foreground)
            painter.drawText(
                rect.adjusted(20, 0, -5, 0),
                Qt.AlignVCenter | Qt.AlignRight,
                self._near_duplicate_marker_text(cluster),
            )
            painter.restore()

    def _near_duplicate_marker_layout(self):
        if not self._near_duplicate_clusters:
            return tuple()
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(8)
        metrics = QFontMetrics(font)
        scale = max(float(self.scale), 0.01)
        offset = self.offset_to_center()
        available = QRectF(self.rect())
        placed = []
        hits = []
        for cluster in self._near_duplicate_clusters:
            if (
                self._annotation_gesture_description is not None
                and any(
                    shape in self.selected_shapes
                    for shape in cluster.members
                )
            ):
                continue
            visible = [
                shape for shape in cluster.members
                if shape in self.shapes and self.isVisible(shape)
            ]
            if not visible:
                continue
            left, top, right, _bottom = cluster_bounds(cluster)
            anchor = QPointF(
                (right + offset.x()) * scale,
                (top + offset.y()) * scale,
            )
            text = self._near_duplicate_marker_text(cluster)
            measure = getattr(metrics, "horizontalAdvance", metrics.width)
            width = max(42.0, float(28 + measure(text)))
            height = 20.0
            x = anchor.x() + 6.0
            if x + width > available.right() - 2:
                x = anchor.x() - width - 6.0
            y = anchor.y() - height - 5.0
            if y < available.top() + 2:
                y = anchor.y() + 5.0
            rect = QRectF(x, y, width, height)
            rect.moveLeft(max(2.0, min(rect.left(), available.right() - width - 2)))
            rect.moveTop(max(2.0, min(rect.top(), available.bottom() - height - 2)))
            while any(rect.adjusted(-2, -2, 2, 2).intersects(item) for item in placed):
                rect.translate(0, height + 4)
                if rect.bottom() > available.bottom() - 2:
                    rect.moveTop(max(2.0, y - height - 4))
                    break
            placed.append(QRectF(rect))
            hits.append((rect, cluster, anchor))
        return tuple(hits)

    def _near_duplicate_marker_text(self, cluster):
        total = len(cluster.members)
        return self._compact_near_duplicate_count(total)

    @staticmethod
    def _compact_near_duplicate_count(count):
        return "99+" if int(count) > 99 else str(int(count))

    @staticmethod
    def _near_duplicate_marker_color(cluster, hovered=False):
        color = QColor(
            "#C026D3"
            if cluster.risk == CATEGORY_CONFLICT
            else "#D97706"
        )
        return color.lighter(112) if hovered else color

    @staticmethod
    def _near_duplicate_marker_needs_leader(rect, anchor):
        default_left = anchor.x() + 6.0
        default_top = anchor.y() - rect.height() - 5.0
        return (
            abs(rect.left() - default_left) > 0.5
            or abs(rect.top() - default_top) > 0.5
        )

    @staticmethod
    def _leader_destination(rect, anchor):
        x = rect.left() if anchor.x() <= rect.center().x() else rect.right()
        return QPointF(x, rect.center().y())

    def _near_duplicate_marker_at(self, point):
        hits = self._near_duplicate_marker_hits or self._near_duplicate_marker_layout()
        for rect, cluster, _anchor in reversed(hits):
            if rect.contains(QPointF(point)):
                return cluster
        return None

    def _near_duplicate_preferred_shape(self, cluster):
        hover = self.interaction_snapshot.hover.shape
        if hover in cluster.members and self.isVisible(hover):
            return hover
        if (
            self._near_duplicate_focus is cluster
            and self._near_duplicate_focus_shape in cluster.members
        ):
            return self._near_duplicate_focus_shape
        return next(
            (
                shape for shape in reversed(cluster.members)
                if shape in self.shapes and self.isVisible(shape)
            ),
            cluster.members[-1],
        )

    def _near_duplicate_tooltip(self, cluster):
        visible = sum(
            shape in self.shapes and self.isVisible(shape)
            for shape in cluster.members
        )
        risk = tr(
            "nearDuplicate.categoryConflict"
            if cluster.risk == CATEGORY_CONFLICT
            else "nearDuplicate.duplicateLabel"
        )
        counts = {}
        order = []
        for shape in cluster.members:
            label = str(shape.label)
            if label not in counts:
                counts[label] = 0
                order.append(label)
            counts[label] += 1
        labels = ", ".join(
            "%s ×%d" % (label, counts[label])
            for label in order
        )
        return tr(
            "nearDuplicate.canvasTooltip",
            risk=risk,
            labels=labels,
            visible=visible,
            total=len(cluster.members),
        )

    def _set_near_duplicate_hover(self, cluster):
        if cluster is self._near_duplicate_hover_cluster:
            return False
        self._near_duplicate_hover_cluster = cluster
        self.update()
        return True

    def _near_duplicate_focus_contains(self, widget_point, scene_point):
        cluster = self._near_duplicate_focus
        if cluster is None:
            return False
        if self._near_duplicate_marker_at(widget_point) is cluster:
            return True
        left, top, right, bottom = cluster_bounds(cluster)
        return QRectF(
            left,
            top,
            max(0.0, right - left),
            max(0.0, bottom - top),
        ).contains(scene_point)

    def status_background_color(self):
        if self.verified:
            return QColor(184, 239, 38, 128)
        if self.questioned:
            return QColor(255, 193, 7, 128)
        return QColor(232, 232, 232, 255)

    def transform_pos(self, point):
        """Convert from widget-logical coordinates to painter-logical coordinates."""
        return point / self.scale - self.offset_to_center()

    def offset_to_center(self):
        s = self.scale
        area = super(Canvas, self).size()
        w, h = self.pixmap.width() * s, self.pixmap.height() * s
        aw, ah = area.width(), area.height()
        x = (aw - w) / (2 * s) if aw > w else 0
        y = (ah - h) / (2 * s) if ah > h else 0
        return QPointF(x, y)

    def pan_canvas(self, delta):
        self.panRequest.emit(int(delta.x()), int(delta.y()))

    def _emit_coordinates(self, pos, shape=None):
        if shape is None:
            text = 'X: %d; Y: %d' % (pos.x(), pos.y())
        else:
            if len(shape) >= 4:
                point1 = shape[1]
                point3 = shape[3]
            else:
                point1 = shape[0]
                point3 = pos
            text = (
                'Width: %d, Height: %d / X: %d; Y: %d'
                % (
                    abs(point1.x() - point3.x()),
                    abs(point1.y() - point3.y()),
                    pos.x(),
                    pos.y(),
                )
            )
        self.coordinatesChanged.emit(text)

    def out_of_pixmap(self, p):
        w, h = self.pixmap.width(), self.pixmap.height()
        return not (0 <= p.x() <= w and 0 <= p.y() <= h)

    def finalise(self):
        assert self.current
        if self.current.points[0] == self.current.points[-1]:
            self.current = None
            self.drawingPolygon.emit(False)
            self.update()
            return

        self.current.close()
        self.shapes.append(self.current)
        self.current = None
        self.set_hiding(False)
        self.newShape.emit()
        self.update()

    def close_enough(self, p1, p2):
        # d = distance(p1 - p2)
        # m = (p1-p2).manhattanLength()
        # print "d %.2f, m %d, %.2f" % (d, m, d - m)
        return distance(p1 - p2) < self.epsilon

    # These two, along with a call to adjustSize are required for the
    # scroll area.
    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        if self.pixmap:
            return self.scale * self.pixmap.size()
        return super(Canvas, self).minimumSizeHint()

    def wheelEvent(self, ev):
        qt_version = 4 if hasattr(ev, "delta") else 5
        if qt_version == 4:
            if ev.orientation() == Qt.Vertical:
                v_delta = ev.delta()
                h_delta = 0
            else:
                h_delta = ev.delta()
                v_delta = 0
        else:
            delta = ev.angleDelta()
            h_delta = delta.x()
            v_delta = delta.y()

        mods = ev.modifiers()
        if Qt.ControlModifier == int(mods) and v_delta:
            self.zoomRequest.emit(v_delta)
        else:
            v_delta and self.scrollRequest.emit(v_delta, Qt.Vertical)
            h_delta and self.scrollRequest.emit(h_delta, Qt.Horizontal)
        ev.accept()

    def keyPressEvent(self, ev):
        key = ev.key()
        if key == Qt.Key_Escape and self.clear_near_duplicate_focus():
            ev.accept()
            return
        if key == Qt.Key_Control:
            self.set_multi_selection_mode(True)
            ev.accept()
            return
        if key == Qt.Key_Escape and self.cancel_selection_gesture():
            ev.accept()
            return
        if key == Qt.Key_Escape and self.current:
            print('ESC press')
            self.current = None
            self.drawingPolygon.emit(False)
            self.update()
        elif key == Qt.Key_Return and self.can_close_shape():
            self.finalise()
        elif (
            key in (
                Qt.Key_Left,
                Qt.Key_Right,
                Qt.Key_Up,
                Qt.Key_Down,
            )
            and len(self.selected_shapes) > 1
        ):
            self.statusRequest.emit(
                'Arrow-key movement requires a single selected label'
            )
            ev.accept()
        elif key == Qt.Key_Left and len(self.selected_shapes) == 1:
            self._begin_arrow_gesture(ev)
            self.move_one_pixel('Left')
        elif key == Qt.Key_Right and len(self.selected_shapes) == 1:
            self._begin_arrow_gesture(ev)
            self.move_one_pixel('Right')
        elif key == Qt.Key_Up and len(self.selected_shapes) == 1:
            self._begin_arrow_gesture(ev)
            self.move_one_pixel('Up')
        elif key == Qt.Key_Down and len(self.selected_shapes) == 1:
            self._begin_arrow_gesture(ev)
            self.move_one_pixel('Down')

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key_Control:
            self.set_multi_selection_mode(False)
            ev.accept()
            return
        if (
            ev.key() in self._held_arrow_keys
            and not ev.isAutoRepeat()
        ):
            self._held_arrow_keys.discard(ev.key())
            if not self._held_arrow_keys:
                self._finish_annotation_gesture()
            ev.accept()
            return
        super(Canvas, self).keyReleaseEvent(ev)

    def _begin_annotation_gesture(self, description, source=None):
        if self._annotation_gesture_description is not None:
            return
        self._annotation_gesture_description = description
        self._annotation_gesture_source = source
        self._near_duplicate_marker_hits = tuple()
        self.update()
        self.annotationGestureStarted.emit(description)

    def _finish_annotation_gesture(self):
        description = self._annotation_gesture_description
        if description is None:
            return
        self._annotation_gesture_description = None
        self._annotation_gesture_source = None
        self._near_duplicate_marker_hits = tuple()
        self.annotationGestureFinished.emit(description)
        self.update()

    def cancel_annotation_gesture(self):
        description = self._annotation_gesture_description
        if description is None:
            return
        self._annotation_gesture_description = None
        self._annotation_gesture_source = None
        self._held_arrow_keys.clear()
        self._near_duplicate_marker_hits = tuple()
        self.annotationGestureCanceled.emit(description)
        self.update()

    def _begin_arrow_gesture(self, event):
        if not event.isAutoRepeat():
            self._held_arrow_keys.add(event.key())
        self._begin_annotation_gesture("Move box", source="keyboard")

    def move_one_pixel(self, direction):
        # print(self.selectedShape.points)
        if direction == 'Left' and not self.move_out_of_bound(QPointF(-1.0, 0)):
            # print("move Left one pixel")
            self.selected_shape.points[0] += QPointF(-1.0, 0)
            self.selected_shape.points[1] += QPointF(-1.0, 0)
            self.selected_shape.points[2] += QPointF(-1.0, 0)
            self.selected_shape.points[3] += QPointF(-1.0, 0)
        elif direction == 'Right' and not self.move_out_of_bound(QPointF(1.0, 0)):
            # print("move Right one pixel")
            self.selected_shape.points[0] += QPointF(1.0, 0)
            self.selected_shape.points[1] += QPointF(1.0, 0)
            self.selected_shape.points[2] += QPointF(1.0, 0)
            self.selected_shape.points[3] += QPointF(1.0, 0)
        elif direction == 'Up' and not self.move_out_of_bound(QPointF(0, -1.0)):
            # print("move Up one pixel")
            self.selected_shape.points[0] += QPointF(0, -1.0)
            self.selected_shape.points[1] += QPointF(0, -1.0)
            self.selected_shape.points[2] += QPointF(0, -1.0)
            self.selected_shape.points[3] += QPointF(0, -1.0)
        elif direction == 'Down' and not self.move_out_of_bound(QPointF(0, 1.0)):
            # print("move Down one pixel")
            self.selected_shape.points[0] += QPointF(0, 1.0)
            self.selected_shape.points[1] += QPointF(0, 1.0)
            self.selected_shape.points[2] += QPointF(0, 1.0)
            self.selected_shape.points[3] += QPointF(0, 1.0)
        self.shapeMoved.emit()
        self.repaint()

    def move_out_of_bound(self, step):
        points = [p1 + p2 for p1, p2 in zip(self.selected_shape.points, [step] * 4)]
        return True in map(self.out_of_pixmap, points)

    def set_last_label(self, text, line_color=None, fill_color=None):
        assert text
        self.shapes[-1].label = text
        if line_color:
            self.shapes[-1].line_color = line_color

        if fill_color:
            self.shapes[-1].fill_color = fill_color

        return self.shapes[-1]

    def undo_last_line(self):
        assert self.shapes
        self.current = self.shapes.pop()
        self.current.set_open()
        self.line.points = [self.current[-1], self.current[0]]
        self.drawingPolygon.emit(True)

    def reset_all_lines(self):
        assert self.shapes
        self.current = self.shapes.pop()
        self.current.set_open()
        self.line.points = [self.current[-1], self.current[0]]
        self.drawingPolygon.emit(True)
        self.current = None
        self.drawingPolygon.emit(False)
        self.update()

    def cancel_current_drawing(self, force=False):
        """Finish the drawing lifecycle after a projected cancellation."""
        was_drawing = self.current is not None
        self.current = None
        self.line.points = []
        self.update()
        if was_drawing or force:
            self.drawingPolygon.emit(False)

    def load_pixmap(self, pixmap):
        self.pixmap = pixmap
        self.shapes = []
        self.current = None
        self._reset_transient_interaction()
        before = self._selection.snapshot
        after = self._selection.set_scene((), selected=())
        self._project_selection(before, after, emit=False)
        self.verified = False
        self.questioned = False
        self.visible.clear()
        self.set_near_duplicate_clusters(())
        self.repaint()

    def replace_pixmap(self, pixmap):
        """Refresh only image pixels while preserving annotation view state."""
        self.pixmap = pixmap
        self.repaint()

    def load_shapes(self, shapes):
        self.shapes = list(shapes)
        for shape in self.shapes:
            shape.selected = False
        self.current = None
        self._reset_transient_interaction()
        before = self._selection.snapshot
        after = self._selection.set_scene(
            tuple(self.shapes),
            selected=(),
        )
        self._project_selection(before, after)
        self.visible.clear()
        self.set_near_duplicate_clusters(())
        self.repaint()

    def set_shape_visible(self, shape, value):
        self.visible[shape] = value
        self._near_duplicate_marker_hits = tuple()
        if not value:
            if self.interaction_snapshot.hover.shape is shape:
                self.un_highlight()
            if shape in self._external_hover_shapes:
                self.set_external_hover_shapes(
                    item for item in self._external_hover_shapes
                    if item is not shape
                )
        self.repaint()

    def current_cursor(self):
        cursor = QApplication.overrideCursor()
        if cursor is not None:
            cursor = cursor.shape()
        return cursor

    def override_cursor(self, cursor):
        self._cursor = cursor
        if self.current_cursor() is None:
            QApplication.setOverrideCursor(cursor)
        else:
            QApplication.changeOverrideCursor(cursor)

    def restore_cursor(self):
        QApplication.restoreOverrideCursor()

    def reset_state(self):
        self.restore_cursor()
        self.pixmap = None
        self.shapes = []
        self.current = None
        self.set_near_duplicate_clusters(())
        self._reset_transient_interaction()
        before = self._selection.snapshot
        after = self._selection.set_scene((), selected=())
        self._project_selection(before, after)
        self.line = Shape(line_color=self.drawing_line_color)
        self.prev_point = QPointF()
        self.verified = False
        self.questioned = False
        self.visible.clear()
        self.update()

    def _reset_transient_interaction(self):
        previous_hover_shape = self.interaction_snapshot.hover.shape
        if previous_hover_shape is not None:
            previous_hover_shape.highlight_clear()
        self.selected_shape_copy = None
        self._annotation_gesture_description = None
        self._annotation_gesture_source = None
        self._held_arrow_keys.clear()
        self._pan_dragging = False
        self._interaction.reset()
        self._external_hover_shapes = tuple()
        self._last_pointer_pos = None
        if previous_hover_shape is not None:
            self.hoverShapeChanged.emit(None)

    def set_drawing_shape_to_square(self, status):
        self.draw_square = status
