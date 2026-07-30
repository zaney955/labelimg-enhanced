
try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
except ImportError:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

# from PyQt4.QtOpenGL import *

from labelimg.shape import Shape
from labelimg.selection import (
    ChoiceMode,
    ChooseIntent,
    SceneIntent,
    SelectionSet,
)
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
        self.h_shape = None
        self.h_vertex = None
        self.h_edge = None
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
        self.selection_press_pos = None
        self.selection_rect = None
        self.selection_before_drag = []
        self.selection_dragging = False

        # initialisation for panning
        self.pan_initial_pos = QPoint()
        self.right_press_pos = None
        self.right_press_shape = None
        self.right_dragging = False

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
        self.restore_cursor()

    def focusOutEvent(self, ev):
        self.multi_selection_mode = False
        self.restore_cursor()

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
            self.de_select_shape()
        self.prev_point = QPointF()
        self.repaint()

    def un_highlight(self):
        if self.h_shape:
            self.h_shape.highlight_clear()
        self.h_vertex = self.h_edge = self.h_shape = None

    def selected_vertex(self):
        return self.h_vertex is not None

    def vertex_cursor(self, index=None):
        if index is None:
            index = self.h_vertex
        return (
            CURSOR_SIZE_FORWARD_DIAGONAL if index % 2 == 0
            else CURSOR_SIZE_BACKWARD_DIAGONAL
        )

    def selected_edge(self):
        return self.h_edge is not None

    def selection_count(self):
        return len(self.selected_shapes)

    @property
    def selected_shapes(self):
        return list(self._selection.snapshot.selected)

    @property
    def selected_shape(self):
        return self._selection.snapshot.active

    def reset_overlap_cycle(self):
        before = self._selection.snapshot
        self._selection.apply(
            SceneIntent(
                boxes=tuple(self.shapes),
                select=before.selected,
                active=before.active,
            )
        )

    def set_selected_shapes(self, shapes, active_shape=None,
                             emit=True, reset_cycle=True):
        before = self._selection.snapshot
        if reset_cycle:
            after = self._selection.apply(
                SceneIntent(
                    boxes=tuple(self.shapes),
                    select=tuple(
                        shape for shape in shapes if shape in self.shapes
                    ),
                    active=active_shape,
                )
            )
        else:
            after = self._selection.apply(
                ChooseIntent(
                    tuple(shape for shape in shapes if shape in self.shapes),
                    ChoiceMode.REPLACE,
                    active_shape,
                )
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

    def clear_selection(self, emit=True, reset_cycle=True):
        self.set_selected_shapes(
            [],
            emit=emit,
            reset_cycle=reset_cycle,
        )

    def set_multi_selection_mode(self, enabled):
        self.multi_selection_mode = bool(enabled)
        if self.current is not None:
            return
        if self.multi_selection_mode and self.current is None:
            self.override_cursor(CURSOR_SELECT)
        elif not self.selection_dragging:
            self._cursor = CURSOR_DEFAULT
            self.restore_cursor()

    def multi_selection_requested(self, ev):
        return (
            self.multi_selection_mode
            or bool(ev.modifiers() & Qt.ControlModifier)
        )

    def visible_shapes_at(self, point):
        return [
            shape for shape in reversed(self.shapes)
            if self.isVisible(shape) and shape.contains_point(point)
        ]

    def begin_selection_gesture(self, pos):
        self.selection_press_pos = QPointF(pos)
        self.selection_rect = None
        self.selection_before_drag = list(self.selected_shapes)
        self.selection_dragging = False
        self.override_cursor(CURSOR_SELECT)

    def update_selection_gesture(self, pos):
        if self.selection_press_pos is None:
            return False

        delta = pos - self.selection_press_pos
        distance = delta.manhattanLength() * max(self.scale, 0.01)
        if not self.selection_dragging:
            if distance < QApplication.startDragDistance():
                return True
            self.selection_dragging = True
            self.reset_overlap_cycle()

        self.selection_rect = QRectF(
            self.selection_press_pos,
            pos,
        ).normalized()
        contained = [
            shape for shape in self.shapes
            if self.isVisible(shape)
            and self.selection_rect.contains(shape.bounding_rect())
        ]
        active_shape = contained[-1] if contained else None
        self.set_selected_shapes(
            contained,
            active_shape=active_shape,
            reset_cycle=False,
        )
        self.update()
        return True

    def finish_selection_gesture(self, pos):
        if self.selection_press_pos is None:
            return False

        if self.selection_dragging:
            self.update_selection_gesture(pos)
        else:
            self.ctrl_click_shape(pos)

        self.selection_press_pos = None
        self.selection_rect = None
        self.selection_before_drag = []
        self.selection_dragging = False
        if self.multi_selection_mode:
            self.override_cursor(CURSOR_SELECT)
        else:
            self._cursor = CURSOR_DEFAULT
            self.restore_cursor()
        self.update()
        return True

    def cancel_selection_gesture(self):
        if self.selection_press_pos is None:
            return False

        previous = list(self.selection_before_drag)
        self.selection_press_pos = None
        self.selection_rect = None
        self.selection_before_drag = []
        self.selection_dragging = False
        self.set_selected_shapes(previous)
        if self.multi_selection_mode:
            self.override_cursor(CURSOR_SELECT)
        else:
            self._cursor = CURSOR_DEFAULT
            self.restore_cursor()
        self.update()
        return True

    def ctrl_click_shape(self, point):
        candidates = tuple(self.visible_shapes_at(point))
        if not candidates:
            self.reset_overlap_cycle()
            return None

        before = self._selection.snapshot
        if len(candidates) > 1:
            after = self._selection.apply(
                ChooseIntent(candidates, ChoiceMode.CYCLE)
            )
            self._project_selection(before, after)
            return after.active

        shape = candidates[0]
        after = self._selection.apply(
            ChooseIntent((shape,), ChoiceMode.TOGGLE, active=shape)
        )
        self._project_selection(before, after)
        return shape

    def mouseMoveEvent(self, ev):
        """Update line with last point and current coordinates."""
        pos = self.transform_pos(ev.pos())

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
            self.un_highlight()
            self.override_cursor(CURSOR_SELECT)
            self.update()
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
            delta = pos - self.right_press_pos
            if (
                not self.right_dragging
                and delta.manhattanLength() * max(self.scale, 0.01)
                >= QApplication.startDragDistance()
            ):
                self.right_dragging = True
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
                self.override_cursor(self.vertex_cursor())
                self.bounded_move_vertex(pos)
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

        # Just hovering over the canvas, 3 possibilities:
        # - Highlight shapes
        # - Highlight vertex
        # - Resize an edge
        # Update shape/vertex/edge state and tooltip value accordingly.
        self.setToolTip("Image")
        visible_shapes = [s for s in self.shapes if self.isVisible(s)]
        for shape in reversed(visible_shapes):
            # Vertices take priority over shape interiors, including vertices
            # belonging to shapes underneath the topmost shape.
            index = shape.nearest_vertex(pos, self.epsilon)
            if index is not None:
                if self.selected_vertex():
                    self.h_shape.highlight_clear()
                self.h_vertex, self.h_edge, self.h_shape = index, None, shape
                shape.highlight_vertex(index, shape.MOVE_VERTEX)
                self.override_cursor(self.vertex_cursor(index))
                self.setToolTip("Click & drag to move point")
                self.setStatusTip(self.toolTip())
                self.update()
                break
        else:
            for shape in reversed(visible_shapes):
                edge = self.nearest_edge(shape, pos)
                if edge is not None:
                    if self.selected_vertex():
                        self.h_shape.highlight_clear()
                    self.h_vertex, self.h_edge, self.h_shape = None, edge, shape
                    self.setToolTip(
                        "Click & drag to resize shape '%s'" % shape.label)
                    self.setStatusTip(self.toolTip())
                    self.override_cursor(
                        CURSOR_SIZE_VERTICAL if edge % 2 == 0
                        else CURSOR_SIZE_HORIZONTAL
                    )
                    self.update()
                    break
            else:
                for shape in reversed(visible_shapes):
                    if not shape.contains_point(pos):
                        continue
                    if self.selected_vertex():
                        self.h_shape.highlight_clear()
                    self.h_vertex, self.h_edge, self.h_shape = None, None, shape
                    self.setToolTip(
                        "Click & drag to move shape '%s'" % shape.label)
                    self.setStatusTip(self.toolTip())
                    self.override_cursor(CURSOR_GRAB)
                    self.update()

                    # Display annotation width and height while hovering inside
                    self._emit_coordinates(pos, self.h_shape)
                    break
                else:  # Nothing found, clear highlights, reset state.
                    if self.h_shape:
                        self.h_shape.highlight_clear()
                        self.update()
                    self.h_vertex, self.h_edge, self.h_shape = None, None, None
                    self.override_cursor(CURSOR_DEFAULT)

    def mousePressEvent(self, ev):
        pos = self.transform_pos(ev.pos())

        if ev.button() == Qt.LeftButton:
            if (
                self.current is None
                and self.multi_selection_requested(ev)
            ):
                self.begin_selection_gesture(pos)
            elif self.drawing():
                self.handle_drawing(pos)
            else:
                selection = self.select_shape_point(pos)
                self.prev_point = pos

                if selection is None:
                    # pan
                    QApplication.setOverrideCursor(QCursor(Qt.OpenHandCursor))
                    self.pan_initial_pos = ev.globalPos()

        elif ev.button() == Qt.RightButton and self.editing():
            self.reset_overlap_cycle()
            candidates = self.visible_shapes_at(pos)
            shape = candidates[0] if candidates else None
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
            self.right_press_pos = QPointF(pos)
            self.right_press_shape = shape
            self.right_dragging = False
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.RightButton:
            menu = self.menus[bool(self.selected_shape_copy)]
            self.restore_cursor()
            if not menu.exec_(self.mapToGlobal(ev.pos()))\
               and self.selected_shape_copy:
                # Cancel the move by deleting the shadow copy.
                self.selected_shape_copy = None
                self.repaint()
            self.right_press_pos = None
            self.right_press_shape = None
            self.right_dragging = False
        elif (
            ev.button() == Qt.LeftButton
            and self.selection_press_pos is not None
        ):
            pos = self.transform_pos(ev.pos())
            self.finish_selection_gesture(pos)
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

    def select_shape_point(self, point):
        """Select the first shape created which contains this point."""
        if self.selected_vertex():  # A vertex is marked for selection.
            index, shape = self.h_vertex, self.h_shape
            shape.highlight_vertex(index, shape.MOVE_VERTEX)
            self.select_shape(shape)
            return self.h_vertex
        if self.selected_edge():  # An edge is marked for resizing.
            shape = self.h_shape
            self.select_shape(shape)
            return self.h_edge
        for shape in reversed(self.shapes):
            if self.isVisible(shape) and shape.contains_point(point):
                self.select_shape(shape)
                self.calculate_offsets(shape, point)
                return self.selected_shape
        self.clear_selection()
        return None

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

    def nearest_edge(self, shape, point):
        """Return the nearest rectangle edge within the screen hit tolerance."""
        if len(shape) != 4:
            return None

        tolerance = self.edge_epsilon / max(self.scale, 0.01)
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
                nearest = index
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

        selected_set = set(selected)
        for shape in selected:
            shape.selected = False
        self.shapes = [
            shape for shape in self.shapes
            if shape not in selected_set
        ]
        before = self._selection.snapshot
        after = self._selection.apply(
            SceneIntent(
                boxes=tuple(self.shapes),
                select=(),
            )
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
            self.move_one_pixel('Left')
        elif key == Qt.Key_Right and len(self.selected_shapes) == 1:
            self.move_one_pixel('Right')
        elif key == Qt.Key_Up and len(self.selected_shapes) == 1:
            self.move_one_pixel('Up')
        elif key == Qt.Key_Down and len(self.selected_shapes) == 1:
            self.move_one_pixel('Down')

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key_Control:
            self.set_multi_selection_mode(False)
            ev.accept()
            return
        super(Canvas, self).keyReleaseEvent(ev)

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

    def load_pixmap(self, pixmap):
        self.pixmap = pixmap
        self.shapes = []
        self.current = None
        self.selected_shape_copy = None
        self.selection_press_pos = None
        self.selection_rect = None
        self.selection_before_drag = []
        self.selection_dragging = False
        before = self._selection.snapshot
        after = self._selection.apply(
            SceneIntent(boxes=(), select=())
        )
        self._project_selection(before, after, emit=False)
        self.right_press_pos = None
        self.right_press_shape = None
        self.right_dragging = False
        self.h_shape = None
        self.h_vertex = None
        self.h_edge = None
        self.verified = False
        self.questioned = False
        self.visible.clear()
        self.repaint()

    def load_shapes(self, shapes):
        self.shapes = list(shapes)
        for shape in self.shapes:
            shape.selected = False
        self.current = None
        self.selected_shape_copy = None
        self.selection_press_pos = None
        self.selection_rect = None
        self.selection_before_drag = []
        self.selection_dragging = False
        before = self._selection.snapshot
        after = self._selection.apply(
            SceneIntent(
                boxes=tuple(self.shapes),
                select=(),
            )
        )
        self._project_selection(before, after)
        self.right_press_pos = None
        self.right_press_shape = None
        self.right_dragging = False
        self.h_shape = None
        self.h_vertex = None
        self.h_edge = None
        self.visible.clear()
        self.repaint()

    def set_shape_visible(self, shape, value):
        self.visible[shape] = value
        self.reset_overlap_cycle()
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
        self.selected_shape_copy = None
        self.selection_press_pos = None
        self.selection_rect = None
        self.selection_before_drag = []
        self.selection_dragging = False
        before = self._selection.snapshot
        after = self._selection.apply(
            SceneIntent(boxes=(), select=())
        )
        self._project_selection(before, after)
        self.right_press_pos = None
        self.right_press_shape = None
        self.right_dragging = False
        self.line = Shape(line_color=self.drawing_line_color)
        self.prev_point = QPointF()
        self.h_shape = None
        self.h_vertex = None
        self.h_edge = None
        self.verified = False
        self.questioned = False
        self.visible.clear()
        self.update()

    def set_drawing_shape_to_square(self, status):
        self.draw_square = status
