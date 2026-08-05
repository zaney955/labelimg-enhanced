
try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
except ImportError:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

# from PyQt4.QtOpenGL import *

from labelimg.shape import Shape
from labelimg.canvas_interaction import CanvasInteraction, HoverTarget
from labelimg.selection import SelectionSet
from labelimg.utils import distance

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

    CREATE, EDIT = list(range(2))

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
        self._external_hover_shape = None
        self._last_pointer_pos = None
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

    def set_editing(self, value=True):
        self.mode = self.EDIT if value else self.CREATE
        if not value:  # Create
            self.un_highlight()
            self.set_external_hover_shape(None)
            self.de_select_shape()
        self.prev_point = QPointF()
        self.repaint()

    def un_highlight(self):
        if self.h_shape:
            self.h_shape.highlight_clear()
        self._set_hover()

    def selected_vertex(self):
        return self.h_vertex is not None

    def vertex_cursor(self, index=None):
        if index is None:
            index = self.h_vertex
        shape = self.h_shape
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
        return self.h_edge is not None

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
    def h_shape(self):
        return self._interaction.hover_shape

    @h_shape.setter
    def h_shape(self, value):
        self._interaction.hover_shape = value

    @property
    def h_vertex(self):
        return self._interaction.hover_vertex

    @h_vertex.setter
    def h_vertex(self, value):
        self._interaction.hover_vertex = value
        if value is not None:
            self._interaction.hover_edge = None

    @property
    def h_edge(self):
        return self._interaction.hover_edge

    @h_edge.setter
    def h_edge(self, value):
        self._interaction.hover_edge = value
        if value is not None:
            self._interaction.hover_vertex = None

    @property
    def selection_press_pos(self):
        return self._interaction.selection_press_pos

    @selection_press_pos.setter
    def selection_press_pos(self, value):
        self._interaction.selection_press_pos = value

    @property
    def selection_rect(self):
        return self._interaction.selection_rect

    @selection_rect.setter
    def selection_rect(self, value):
        self._interaction.selection_rect = value

    @property
    def selection_before_drag(self):
        return list(self._interaction.selection_before_drag)

    @selection_before_drag.setter
    def selection_before_drag(self, value):
        self._interaction.selection_before_drag = tuple(value)

    @property
    def selection_dragging(self):
        return self._interaction.selection_dragging

    @selection_dragging.setter
    def selection_dragging(self, value):
        self._interaction.selection_dragging = bool(value)

    @property
    def right_press_pos(self):
        return self._interaction.right_press_pos

    @right_press_pos.setter
    def right_press_pos(self, value):
        self._interaction.right_press_pos = value

    @property
    def right_press_shape(self):
        return self._interaction.right_press_shape

    @right_press_shape.setter
    def right_press_shape(self, value):
        self._interaction.right_press_shape = value

    @property
    def right_dragging(self):
        return self._interaction.right_dragging

    @right_dragging.setter
    def right_dragging(self, value):
        self._interaction.right_dragging = bool(value)

    def _set_hover(self, shape=None, vertex=None, edge=None):
        previous_shape = self._interaction.hover_shape
        self._interaction.set_hover(shape, vertex=vertex, edge=edge)
        if previous_shape is not shape:
            self.hoverShapeChanged.emit(shape)

    def set_external_hover_shape(self, shape):
        if (
            shape is not None
            and (
                not self.editing()
                or shape not in self.shapes
                or not self.isVisible(shape)
            )
        ):
            shape = None
        if self._external_hover_shape is shape:
            return
        self._external_hover_shape = shape
        self.update()

    @property
    def hover_shape_for_paint(self):
        if self.selection_dragging:
            return None
        shape = (
            self.h_shape
            if self.h_shape is not None
            else self._external_hover_shape
        )
        if (
            shape not in self.shapes
            or not self.isVisible(shape)
        ):
            return None
        return shape

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
            if self.h_shape is not None:
                self.h_shape.highlight_clear()
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

        if self.pixmap and not self.pixmap.isNull():
            self._emit_coordinates(pos)

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
                    "Ctrl-click to toggle shape '%s'" % target.shape.label
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
                self._emit_coordinates(pos, self.h_shape)
            elif self.selected_edge():
                self.bounded_move_edge(pos)
                self.shapeMoved.emit()
                self.repaint()

                # Display annotation width and height while moving edge
                self._emit_coordinates(pos, self.h_shape)
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
        self.setToolTip("Image")
        target = self._refresh_hover(pos)
        if target.vertex is not None:
            self.override_cursor(self.vertex_cursor(target.vertex))
            self.setToolTip("Click & drag to move point")
            self.setStatusTip(self.toolTip())
        elif target.edge is not None:
            self.setToolTip(
                "Click & drag to resize shape '%s'" % target.shape.label
            )
            self.setStatusTip(self.toolTip())
            self.override_cursor(
                CURSOR_SIZE_VERTICAL
                if target.edge % 2 == 0
                else CURSOR_SIZE_HORIZONTAL
            )
        elif target.shape is not None:
            self.setToolTip(
                "Click & drag to move shape '%s'" % target.shape.label
            )
            self.setStatusTip(self.toolTip())
            self.override_cursor(CURSOR_GRAB)
            self._emit_coordinates(pos, target.shape)
        else:
            self.override_cursor(CURSOR_DEFAULT)

    def mousePressEvent(self, ev):
        pos = self.transform_pos(ev.pos())
        self._last_pointer_pos = QPointF(pos)

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
                    CURSOR_SIZE_VERTICAL if self.h_edge % 2 == 0
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
        index, shape = self.h_vertex, self.h_shape
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
        edge, shape = self.h_edge, self.h_shape
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
        selected = [
            shape for shape in self.shapes
            if shape in self.selected_shapes
        ]
        if not selected:
            return []

        if self.h_shape in selected:
            self.un_highlight()
        if self._external_hover_shape in selected:
            self.set_external_hover_shape(None)

        selected_set = set(selected)
        for shape in selected:
            shape.selected = False
        self.shapes = [
            shape for shape in self.shapes
            if shape not in selected_set
        ]
        before = self._selection.snapshot
        after = self._selection.set_scene(
            tuple(self.shapes),
            selected=(),
        )
        self._project_selection(before, after)
        return selected

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
        for shape in self.shapes:
            if (shape.selected or not self._hide_background) and self.isVisible(shape):
                shape.fill = shape.selected
                shape.paint(p)
        hover_shape = self.hover_shape_for_paint
        if (
            self.editing()
            and hover_shape is not None
            and self.isVisible(hover_shape)
        ):
            hover_shape.paint_hover_outline(p)
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

        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(
            self.backgroundRole(),
            self.status_background_color(),
        )
        self.setPalette(pal)

        p.end()

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
        self.annotationGestureStarted.emit(description)

    def _finish_annotation_gesture(self):
        description = self._annotation_gesture_description
        if description is None:
            return
        self._annotation_gesture_description = None
        self._annotation_gesture_source = None
        self.annotationGestureFinished.emit(description)

    def cancel_annotation_gesture(self):
        description = self._annotation_gesture_description
        if description is None:
            return
        self._annotation_gesture_description = None
        self._annotation_gesture_source = None
        self._held_arrow_keys.clear()
        self.annotationGestureCanceled.emit(description)

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
        self.repaint()

    def set_shape_visible(self, shape, value):
        self.visible[shape] = value
        if not value:
            if self.h_shape is shape:
                self.un_highlight()
            if self._external_hover_shape is shape:
                self.set_external_hover_shape(None)
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
        previous_hover_shape = self.h_shape
        if previous_hover_shape is not None:
            previous_hover_shape.highlight_clear()
        self.selected_shape_copy = None
        self._annotation_gesture_description = None
        self._annotation_gesture_source = None
        self._held_arrow_keys.clear()
        self._interaction.reset()
        self._external_hover_shape = None
        self._last_pointer_pos = None
        if previous_hover_shape is not None:
            self.hoverShapeChanged.emit(None)

    def set_drawing_shape_to_square(self, status):
        self.draw_square = status
