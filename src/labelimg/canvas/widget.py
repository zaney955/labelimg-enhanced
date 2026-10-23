import math

from PyQt5.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
    QContextMenuEvent,
)
from PyQt5.QtWidgets import QApplication, QWidget

from labelimg.localization.runtime import language_changed, tr
from labelimg.ui.theme import COLORS
from labelimg.ui.risk_glyphs import draw_not_equal_glyph


from labelimg.canvas.shape import Shape
from labelimg.canvas.drawing_preview import paint_drawing_crosshair, paint_pending_box
from labelimg.canvas.drawing_scene import DrawingSceneCache
from labelimg.canvas.image_layer import ImageLayerCache
from labelimg.canvas.magnifier import paint_magnifier
from labelimg.canvas.interaction import (
    CanvasContextRequest,
    CanvasInteraction,
    HoverTarget,
)
from labelimg.canvas.selection import SelectionSet
from labelimg.canvas.geometry import distance
from labelimg.canvas.near_duplicates import (
    CATEGORY_CONFLICT,
    cluster_bounds,
)

CURSOR_DEFAULT = Qt.ArrowCursor
CURSOR_POINT = Qt.PointingHandCursor
CURSOR_DRAW = Qt.BlankCursor
CURSOR_SELECT = Qt.CrossCursor
CURSOR_MOVE = Qt.ClosedHandCursor
CURSOR_GRAB = Qt.OpenHandCursor
CURSOR_SIZE_HORIZONTAL = Qt.SizeHorCursor
CURSOR_SIZE_VERTICAL = Qt.SizeVerCursor
CURSOR_SIZE_FORWARD_DIAGONAL = Qt.SizeFDiagCursor
CURSOR_SIZE_BACKWARD_DIAGONAL = Qt.SizeBDiagCursor

# class Canvas(QGLWidget):


class Canvas(QWidget):
    zoomRequest = pyqtSignal(float, QPointF)
    scrollRequest = pyqtSignal(float, int, bool)
    panRequest = pyqtSignal(int, int)
    coordinatesChanged = pyqtSignal(str)
    annotationSizeChanged = pyqtSignal(str)
    imageSizeChanged = pyqtSignal(QSize)
    statusRequest = pyqtSignal(str)
    interactionHintChanged = pyqtSignal(str, bool)
    newShape = pyqtSignal()
    selectionChanged = pyqtSignal(bool)
    shapeMoved = pyqtSignal()
    drawingPolygon = pyqtSignal(bool)
    modeChanged = pyqtSignal(int)
    annotationGestureStarted = pyqtSignal(str)
    annotationGestureFinished = pyqtSignal(str)
    annotationGestureCanceled = pyqtSignal(str)
    hoverShapeChanged = pyqtSignal(object)
    shapeLabelEditRequested = pyqtSignal(object)
    nearDuplicateRequested = pyqtSignal(object, object, object)
    contextMenuRequested = pyqtSignal(object)

    CREATE, EDIT, PAN = list(range(3))

    epsilon = 11.0
    edge_epsilon = 5.0

    def __init__(self, *args, **kwargs):
        super(Canvas, self).__init__(*args, **kwargs)
        self.setProperty("uiScaleGeometryExcluded", True)
        # Initialise local state.
        self.mode = self.EDIT
        self.shapes = []
        self.current = None
        self._pending_label_shape = None
        self._overlap_drag_shape = None
        self._pixmap_logical_size = QSize()
        self._selection = SelectionSet()
        self._interaction = CanvasInteraction()
        self._external_hover_shapes = tuple()
        self._last_pointer_pos = None
        self._pointer_global_pos = None
        self._near_duplicate_clusters = tuple()
        self._near_duplicate_marker_hits = tuple()
        self._near_duplicate_focus = None
        self._near_duplicate_focus_shape = None
        self._near_duplicate_hover_cluster = None
        self.drawing_line_color = QColor(0, 0, 255)
        self.drawing_rect_color = QColor(0, 0, 255)
        self.line = Shape(line_color=self.drawing_line_color)
        self.prev_point = QPointF()
        self.offsets = QPointF(), QPointF()
        self.scale = 1.0
        self._view_offset = QPointF()
        self._content_margins = (0.0, 0.0, 0.0, 0.0)
        self.annotation_font_size = 25.0
        self.label_font_size = 25.0
        self.annotation_line_width = 1.5
        self.magnifier_enabled = False
        self.pixmap = QPixmap()
        self.visible = {}
        self._hide_background = False
        self.hide_background = False
        self.hide_at_crosshair = False
        self.protect_selected_annotations = False
        self._drawing_scene_cache = DrawingSceneCache()
        self._image_layer_cache = ImageLayerCache()
        self._painter = QPainter()
        self._cursor = CURSOR_DEFAULT
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
        language_changed.connect(self.refresh_interaction_hint)

    def _publish_interaction_hint(self, text, interactive=False):
        self.setToolTip(text or tr("canvas.image"))
        # Canvas hints use the direct signal; native StatusTip events must not
        # replay a cached shape after the pointer/tool has already changed.
        self.setStatusTip("")
        self.interactionHintChanged.emit(text, interactive)

    def refresh_interaction_hint(self, _language=None, *, interactive=False, control_down=False):
        """Project current interaction state, without retaining category text."""
        text = ""
        if self.pixmap is not None and not self.pixmap_size.isEmpty():
            if self._pan_dragging or self.panning():
                text = tr("canvas.hintPan")
            elif self.drawing():
                text = tr("canvas.hintDrawFinish" if self.current else "canvas.hintDrawStart")
            elif self._annotation_gesture_source == "keyboard" and self.selected_shape is not None:
                text = tr("canvas.hintKeyboardMove", label=self.selected_shape.label)
            elif self._pointer_global_pos is not None:
                target = self.interaction_snapshot.hover
                shape = target.shape
                if self._near_duplicate_hover_cluster is not None:
                    text = self._near_duplicate_tooltip(self._near_duplicate_hover_cluster)
                elif self.selection_dragging:
                    text = tr("canvas.hintMultiSelect")
                elif shape is not None and shape in self.shapes and self.isVisible(shape):
                    if self._annotation_gesture_source == "mouse":
                        text = tr("canvas.hintResizing" if target.vertex is not None or target.edge is not None
                                  else "canvas.hintMoving", label=shape.label)
                    elif self.multi_selection_mode or control_down:
                        text = tr("canvas.ctrlToggle", label=shape.label)
                    elif target.vertex is not None:
                        text = tr("canvas.movePoint")
                    elif target.edge is not None:
                        text = tr("canvas.resizeShape", label=shape.label)
                    else:
                        text = tr("canvas.moveShape", label=shape.label)
                else:
                    text = tr("canvas.hintMultiSelect" if self.multi_selection_mode or control_down else "canvas.hintSelect")
            elif self.hasFocus():
                text = tr("canvas.hintSelect")
        self._publish_interaction_hint(text, interactive)

    def set_drawing_color(self, qcolor):
        self.drawing_line_color = qcolor
        self.drawing_rect_color = qcolor

    def enterEvent(self, ev):
        self.multi_selection_mode = bool(
            QApplication.keyboardModifiers() & Qt.ControlModifier
        )
        self.refresh_pointer_coordinates(self.mapFromGlobal(QCursor.pos()))
        self.override_cursor(
            CURSOR_SELECT
            if self.multi_selection_mode and self.current is None
            else CURSOR_DRAW if self.drawing()
            else self._cursor
        )
        self.refresh_interaction_hint(interactive=True)

    def leaveEvent(self, ev):
        self._pointer_global_pos = None
        self.update()
        self._emit_coordinates(None, self._active_readout_shape())
        self.clear_near_duplicate_focus()
        self._set_near_duplicate_hover(None)
        if (
            self.selection_press_pos is None
            and self.right_press_shape is None
            and self._annotation_gesture_source != "mouse"
        ):
            self.un_highlight()
        self.restore_cursor()

        self._publish_interaction_hint("")

    def focusOutEvent(self, ev):
        self.multi_selection_mode = False
        self.restore_cursor()
        if self._held_arrow_keys:
            self._held_arrow_keys.clear()
            self._finish_annotation_gesture()
        super(Canvas, self).focusOutEvent(ev)
        self.refresh_interaction_hint()
        if self._pointer_global_pos is None:
            self._publish_interaction_hint("")

    def event(self, ev):
        if ev.type() == QEvent.ToolTip:
            # Keep hover guidance in the status bar without obscuring the image.
            ev.ignore()
            return True
        if (
            ev.type() == QEvent.UngrabMouse
            and self._annotation_gesture_source == "mouse"
        ):
            self.cancel_annotation_gesture()
        return super(Canvas, self).event(ev)

    def isVisible(self, shape):
        return self.visible.get(shape, True)

    def set_hide_at_crosshair(self, enabled):
        self.hide_at_crosshair = bool(enabled)
        self._near_duplicate_marker_hits = tuple()
        self.update()

    def set_protect_selected_annotations(self, enabled):
        self.protect_selected_annotations = bool(enabled)
        self._near_duplicate_marker_hits = tuple()
        self.update()

    def set_magnifier_enabled(self, enabled):
        self.magnifier_enabled = bool(enabled)
        self.update()

    def set_annotation_style(self, line_width, font_size):
        self.annotation_line_width = max(0.5, min(6.0, float(line_width)))
        self.annotation_font_size = max(6.0, min(128.0, float(font_size)))
        self.label_font_size = self.annotation_font_size / max(self.scale, 0.01)
        self._drawing_scene_cache.clear()
        self._near_duplicate_marker_hits = tuple()
        self.update()

    def set_auto_hide_overlapping(self, enabled):
        """Compatibility for callers of the former combined control."""
        self.set_hide_at_crosshair(enabled)
        self.set_protect_selected_annotations(enabled)

    def _drawing_crosshair_position(self):
        """The scene-space center used by the crosshair and drawing visibility."""
        if not self.drawing() or self._pending_label_shape is not None or self._pan_dragging:
            return None
        if self.current is not None and len(self.line) == 2:
            return QPointF(self.line[1])
        point = self._last_pointer_pos
        if (
            self.multi_selection_mode
            or QApplication.keyboardModifiers() & Qt.ControlModifier
            or self.selection_press_pos is not None
            or self._pointer_global_pos is None or point is None
            or not self.rect().contains(self.image_to_widget(point).toPoint())
        ):
            return None
        return QPointF(point)

    def _overlap_protected_shapes(self):
        """Visible selected/manipulated targets; drawing uses center containment."""
        if (
            not self.protect_selected_annotations or self.panning()
            or self.current is not None or self._pending_label_shape is not None
            or self._drawing_crosshair_position() is not None
        ):
            return ()
        targets = set(self.selected_shapes)
        if self.editing() and self._annotation_gesture_source == "mouse":
            targets.add(self._overlap_drag_shape)
        return tuple(
            shape for shape in self.shapes
            if shape in targets and self.isVisible(shape)
        )

    def _shape_label_visible(self, shape):
        if (
            self._near_duplicate_focus is not None
            and shape in self._near_duplicate_focus.members
        ):
            return shape is self._near_duplicate_focus_shape
        return shape.paint_label

    def _overlap_label_rect(self, shape):
        if not self._shape_label_visible(shape):
            return None
        label = shape.label_text_rect(
            scale=self.scale, font_size=self.label_font_size,
        )
        if label is not None and shape.selected:
            padding = shape.selected_label_padding / max(self.scale, 0.01)
            label = label.adjusted(-padding, -padding, padding, padding)
        return label

    def _drawing_shape_presentation(self, shape, point, bounds=None):
        """Independently suppress boxes and displayed labels containing the center."""
        paint_box, paint_label = True, self._shape_label_visible(shape)
        if point is not None and shape is not self._pending_label_shape:
            bounds = shape.bounding_rect().normalized() if bounds is None else bounds
            paint_box = not bounds.contains(point)
            label = self._overlap_label_rect(shape)
            if label is not None and label.contains(point):
                paint_label = False
        return paint_box, paint_label

    def _overlap_hiding_path(self, protected_shapes=None):
        covered = QPainterPath()
        covered.setFillRule(Qt.WindingFill)
        for rectangle in self._overlap_hiding_rectangles(protected_shapes):
            covered.addRect(rectangle)
        return covered

    def _is_overlap_hidden(self, shape, *, covered=None, protected_shapes=None):
        """Whether clipping covers every painted part of a marker's member."""
        if protected_shapes is None:
            protected_shapes = set(self._overlap_protected_shapes())
        if shape is self._pending_label_shape or shape in protected_shapes:
            return False
        if covered is None:
            covered = self._overlap_hiding_path(protected_shapes)
        point = self._drawing_crosshair_position() if self.hide_at_crosshair else None
        paint_box, paint_label = self._drawing_shape_presentation(shape, point)
        if not paint_box and not paint_label:
            return True
        if covered.isEmpty():
            return False
        if paint_box:
            padding = max(self.annotation_line_width / 2.0, shape.point_size / 2.0) / max(self.scale, 0.01)
            bounds = shape.bounding_rect().normalized().adjusted(
                -padding, -padding, padding, padding,
            )
            if not covered.contains(bounds):
                return False
        label = self._overlap_label_rect(shape) if paint_label else None
        return label is None or covered.contains(label)

    def _pending_overlap_rectangle(self):
        """The constrained new rectangle, retained through initial label choice."""
        if not self.hide_at_crosshair:
            return None
        pending = QRectF()
        if self.current is not None and len(self.line) == 2:
            pending = QRectF(self.line[0], self.line[1]).normalized()
        elif self._pending_label_shape is not None:
            pending = self._pending_label_shape.bounding_rect().normalized()
        return None if pending.isEmpty() else pending

    def _overlap_hiding_rectangles(self, protected_shapes=None):
        if self.current is not None or self._pending_label_shape is not None:
            geometry = self._pending_overlap_rectangle()
            return () if geometry is None else (geometry,)
        if protected_shapes is None:
            protected_shapes = self._overlap_protected_shapes()
        rectangles = []
        for shape in protected_shapes:
            bounds = shape.bounding_rect().normalized()
            if not bounds.isEmpty():
                rectangles.append(bounds)
                label = self._overlap_label_rect(shape)
                if label is not None:
                    rectangles.append(label)
        return tuple(rectangles)

    def _overlap_clip_region(self, painter, protected_shapes=None):
        rectangles = self._overlap_hiding_rectangles(protected_shapes)
        if not rectangles:
            return None
        # Use one screen-space pixel boundary for cached and direct painting.
        covered = QRegion()
        transform = painter.worldTransform()
        for rectangle in rectangles:
            bounds = transform.mapRect(rectangle).toAlignedRect()
            covered |= QRegion(bounds)
        return QRegion(self.rect()).subtracted(covered)

    def drawing(self):
        return self.mode == self.CREATE

    def editing(self):
        return self.mode == self.EDIT

    def panning(self):
        return self.mode == self.PAN

    def set_mode(self, mode):
        if mode not in (self.CREATE, self.EDIT, self.PAN):
            raise ValueError("Unknown canvas mode: %r" % (mode,))
        previous_mode = self.mode
        self.mode = mode
        self._overlap_drag_shape = None
        if mode != self.CREATE:
            self._drawing_scene_cache.clear()
            self.current = None
            self._pending_label_shape = None
            self.line.points = []
        if mode != self.EDIT:
            self.clear_near_duplicate_focus()
            self._set_near_duplicate_hover(None)
            self.un_highlight()
            self.set_external_hover_shape(None)
            self.de_select_shape()
        self.prev_point = QPointF()
        self._cursor = (
            CURSOR_DRAW if mode == self.CREATE
            else CURSOR_GRAB if mode == self.PAN
            else CURSOR_DEFAULT
        )
        self.setCursor(QCursor(self._cursor))
        if self.underMouse():
            self.override_cursor(self._cursor)
        self.refresh_interaction_hint(interactive=True)
        self.update()
        if mode != previous_mode:
            self.modeChanged.emit(mode)

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

    def _set_hover(self, shape=None, vertex=None, edge=None):
        previous_shape = self._interaction.hover_shape
        self._interaction.set_hover(shape, vertex=vertex, edge=edge)
        if previous_shape is not shape:
            self.hoverShapeChanged.emit(shape)
        readout = self._active_readout_shape()
        if readout is None and self.editing():
            readout = shape
        self._emit_annotation_size(readout)
        self.refresh_interaction_hint()

    def set_hover_target(self, shape=None, vertex=None, edge=None):
        """Project one coherent hover transition and its Qt side effects."""
        self._set_hover(shape, vertex, edge)
        self.refresh_interaction_hint()
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
        self.refresh_interaction_hint(interactive=True)
        self.update()
        if self.current is not None:
            return
        if self.multi_selection_mode and self.current is None:
            hover_shape = self.interaction_snapshot.hover.shape
            if hover_shape is not None:
                hover_shape.highlight_clear()
            self.override_cursor(CURSOR_SELECT)
        elif not self.selection_dragging:
            self._cursor = CURSOR_DRAW if self.drawing() else CURSOR_DEFAULT
            self.restore_cursor()
            if self.drawing():
                self.override_cursor(CURSOR_DRAW)
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
        tolerance = max(self.epsilon, self.edge_epsilon) / max(self.scale, 0.01)
        visible_shapes = [
            shape for shape in self.shapes if self.isVisible(shape)
            and shape.bounding_rect().adjusted(
                -tolerance, -tolerance, tolerance, tolerance).contains(point)
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
            self._cursor = CURSOR_DRAW if self.drawing() else CURSOR_DEFAULT
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
            self._cursor = CURSOR_DRAW if self.drawing() else CURSOR_DEFAULT
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
        self.refresh_interaction_hint(interactive=True)
        try:
            self._handle_pointer_move(ev)
        finally:
            self.refresh_interaction_hint(control_down=bool(ev.modifiers() & Qt.ControlModifier))

    def _handle_pointer_move(self, ev):
        """Update line with last point and current coordinates."""
        pos = self.transform_pos(ev.pos())
        self._last_pointer_pos = QPointF(pos)
        self._pointer_global_pos = self.mapToGlobal(ev.pos())

        if (
            self._near_duplicate_focus is not None
            and not self._near_duplicate_focus_contains(ev.pos(), pos)
        ):
            self.clear_near_duplicate_focus()

        self._emit_pointer_coordinates(pos)
        if not self.current and not ev.buttons():
            self._emit_annotation_size(None)

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
                color = self.drawing_line_color
                if self.out_of_pixmap(pos):
                    # Don't allow the user to draw outside the pixmap.
                    # Clip the coordinates to 0 or max,
                    # if they are outside the range [0, max]
                    size = self.pixmap_size
                    clipped_x = min(max(0, pos.x()), size.width())
                    clipped_y = min(max(0, pos.y()), size.height())
                    pos = QPointF(clipped_x, clipped_y)
                elif len(self.current) > 1 and self.close_enough(pos, self.current[0]):
                    # Attract line to starting point and colorise to alert the
                    # user:
                    pos = self.current[0]
                    color = self.current.line_color
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
                # Read the constrained preview, not the outside pointer.
                self._emit_annotation_size(self.current)
            else:
                self.prev_point = pos
            self.update()
            return

        # Polygon/Vertex moving.
        if Qt.LeftButton & ev.buttons():
            if self.selected_vertex():
                self._overlap_drag_shape = self.interaction_snapshot.hover.shape
                self.bounded_move_vertex(pos)
                self.override_cursor(self.vertex_cursor())
                self.shapeMoved.emit()
                self.update()

                # Display annotation width and height while moving vertex
                self._emit_coordinates(
                    pos, self.interaction_snapshot.hover.shape
                )
            elif self.selected_edge():
                self._overlap_drag_shape = self.interaction_snapshot.hover.shape
                self.bounded_move_edge(pos)
                self.shapeMoved.emit()
                self.update()

                # Display annotation width and height while moving edge
                self._emit_coordinates(
                    pos, self.interaction_snapshot.hover.shape
                )
            elif self.selected_shape and self.prev_point:
                self._overlap_drag_shape = self.selected_shape
                self.override_cursor(CURSOR_MOVE)
                self.bounded_move_shape(self.selected_shape, pos)
                self.shapeMoved.emit()
                self.update()

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
        self._emit_annotation_size(target.shape)
        if target.vertex is not None:
            self.override_cursor(self.vertex_cursor(target.vertex))
            self.setToolTip(tr("canvas.movePoint"))
        elif target.edge is not None:
            self.setToolTip(
                tr("canvas.resizeShape", label=target.shape.label)
            )
            self.override_cursor(
                CURSOR_SIZE_VERTICAL
                if target.edge % 2 == 0
                else CURSOR_SIZE_HORIZONTAL
            )
        elif target.shape is not None:
            self.setToolTip(
                tr("canvas.moveShape", label=target.shape.label)
            )
            self.override_cursor(CURSOR_GRAB)
        else:
            self.override_cursor(CURSOR_DEFAULT)

    def mousePressEvent(self, ev):
        self.refresh_interaction_hint(interactive=True)
        try:
            self._handle_pointer_press(ev)
        finally:
            self.refresh_interaction_hint(control_down=bool(ev.modifiers() & Qt.ControlModifier))

    def _handle_pointer_press(self, ev):
        pos = self.transform_pos(ev.pos())
        self._pointer_global_pos = self.mapToGlobal(ev.pos())
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

        elif ev.button() == Qt.RightButton:
            if self.drawing():
                self.cancel_current_drawing()
                ev.accept()
                return
            if self.editing():
                target = self.resolve_pointer_target(pos)
                self._apply_hover_target(target)
                shape = target.shape
                if shape is None:
                    self.clear_selection()
                elif shape not in self.selected_shapes:
                    self.set_selected_shapes(
                        [shape],
                        active_shape=shape,
                    )
                else:
                    self.set_selected_shapes(
                        self.selected_shapes,
                        active_shape=shape,
                    )
                self._interaction.begin_right_press(pos, shape)
        self.update()

    def mouseReleaseEvent(self, ev):
        self.refresh_interaction_hint(interactive=True)
        try:
            self._handle_pointer_release(ev)
        finally:
            self.refresh_interaction_hint(control_down=bool(ev.modifiers() & Qt.ControlModifier))

    def _handle_pointer_release(self, ev):
        self._last_pointer_pos = self.transform_pos(ev.pos())
        self._pointer_global_pos = self.mapToGlobal(ev.pos())
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
            self.restore_cursor()
            self._interaction.finish_right_press()
            if self.editing():
                self._refresh_hover(self.transform_pos(ev.pos()))
            ev.accept()
            return
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

    def hide_background_shapes(self, value):
        self.hide_background = value
        if self.selected_shapes:
            # Only hide other shapes if there is a current selection.
            # Otherwise the user will not be able to select a shape.
            self.set_hiding(True)
            self.update()

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
            self._emit_coordinates(pos, self.current)
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
        size = self.pixmap_size
        if x < 0 or x > size.width() or y < 0 or y > size.height():
            x = max(x, 0)
            y = max(y, 0)
            x = min(x, size.width())
            y = min(y, size.height())
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
        tolerance = self.resize_hit_tolerance(
            shape,
            self.epsilon / max(self.scale, 0.01),
        )
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
            size = self.pixmap_size
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
        image_size = self.pixmap_size

        if vertical_coordinate:
            coordinate = min(max(0.0, pos.y()), float(image_size.height()))
            current = (
                shape[first_index].y() + shape[second_index].y()
            ) / 2.0
            opposite = (
                shape[opposite_first].y() + shape[opposite_second].y()
            ) / 2.0
        else:
            coordinate = min(max(0.0, pos.x()), float(image_size.width()))
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
            size = self.pixmap_size
            pos += QPointF(min(0, size.width() - o2.x()),
                           min(0, size.height() - o2.y()))
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
        self.set_selected_shapes(
            copies,
            active_shape=copies[-1],
        )
        return copies

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

        image_size = self.pixmap_size
        self._image_layer_cache.paint(
            p, self.pixmap, image_size,
            self.visibleRegion().boundingRect().united(event.rect()),
        )
        Shape.scale = self.scale
        Shape.label_font_size = self.label_font_size
        Shape.line_width = self.annotation_line_width
        hover_shapes = set(
            self.hover_shapes_for_paint
            if self.editing()
            else ()
        )
        paint_shapes = self.shapes
        protected_shapes = set(self._overlap_protected_shapes())
        drawing_point = self._drawing_crosshair_position() if self.hide_at_crosshair else None
        overlap_clip = self._overlap_clip_region(p, protected_shapes)
        if self._near_duplicate_focus is None:
            shapes = [
                shape for shape in self.shapes
                if shape is not self._pending_label_shape and shape not in protected_shapes
            ]
            cached = self._drawing_scene_cache.paint(
                p, shapes, self.visibleRegion().boundingRect().united(event.rect()),
                lambda shape, bounds: (
                    self.isVisible(shape)
                    and (shape.selected or not self._hide_background or shape in hover_shapes)
                ),
                clip_region=overlap_clip,
                presentation=lambda shape, bounds: self._drawing_shape_presentation(
                    shape, drawing_point, bounds,
                ),
                hovered=hover_shapes,
            )
            if cached:
                paint_shapes = [shape for shape in self.shapes if shape in protected_shapes]
        else:
            self._drawing_scene_cache.clear()
        if overlap_clip is not None and protected_shapes:
            # Keep targets complete and above the clipped background annotations.
            paint_shapes = (
                [shape for shape in paint_shapes if shape not in protected_shapes]
                + [shape for shape in paint_shapes if shape in protected_shapes]
            )
            if self._overlap_drag_shape in paint_shapes:
                paint_shapes.remove(self._overlap_drag_shape)
                paint_shapes.append(self._overlap_drag_shape)
        for shape in paint_shapes:
            if shape is self._pending_label_shape:
                continue
            if (
                (
                    shape.selected
                    or not self._hide_background
                    or shape in hover_shapes
                )
                and self.isVisible(shape)
            ):
                paint_box, paint_label = self._drawing_shape_presentation(shape, drawing_point)
                if not paint_box and not paint_label:
                    continue
                p.save()
                if overlap_clip is not None and shape not in protected_shapes:
                    transform = p.worldTransform()
                    p.resetTransform()
                    p.setClipRegion(overlap_clip, Qt.IntersectClip)
                    p.setWorldTransform(transform)
                shape.fill = shape.selected
                peer_in_focus = (
                    self._near_duplicate_focus is not None
                    and shape in self._near_duplicate_focus.members
                    and shape is not self._near_duplicate_focus_shape
                )
                if peer_in_focus:
                    p.save()
                    p.setOpacity(0.20)
                paint_kwargs = {}
                if not paint_box:
                    paint_kwargs["paint_box"] = False
                if paint_label != shape.paint_label:
                    paint_kwargs["paint_label"] = paint_label
                if shape in hover_shapes:
                    paint_kwargs.update(
                        outline_style=Qt.CustomDashLine,
                        outline_dash_pattern=Shape.hover_dash_pattern,
                    )
                shape.paint(p, **paint_kwargs)
                if peer_in_focus:
                    p.restore()
                p.restore()
        if self.selection_rect is not None:
            p.save()
            selection_color = QColor(COLORS["accent"])
            selection_color.setAlpha(200)
            selection_pen = QPen(
                selection_color,
                1.0 / max(self.scale, 0.01),
                Qt.DashLine,
            )
            p.setPen(selection_pen)
            selection_fill = QColor(COLORS["accent"])
            selection_fill.setAlpha(35)
            p.setBrush(selection_fill)
            p.drawRect(self.selection_rect)
            p.restore()

        # Canvas-wide reverse-screen guides share the pending box's mask.
        inverse, _invertible = p.worldTransform().inverted()
        guide_bounds = inverse.mapRect(QRectF(self.rect()))
        # The pending box has its own presentation, independent of label colors.
        if self.current is not None and len(self.line) == 2:
            paint_pending_box(
                p, image_size, self.line[0], self.line[1],
                guide_bounds=guide_bounds, outline_width=self.annotation_line_width,
            )
        elif self._pending_label_shape is not None:
            bounds = self._pending_label_shape.bounding_rect()
            paint_pending_box(
                p, image_size, bounds.topLeft(), bounds.bottomRight(),
                drawing=False, outline_width=self.annotation_line_width,
            )

        if self.current is None:
            crosshair = self._drawing_crosshair_position()
            if crosshair is not None:
                paint_drawing_crosshair(
                    p, guide_bounds, crosshair, line_width=self.annotation_line_width,
                )

        p.save()
        p.resetTransform()
        self._paint_near_duplicate_markers(p)
        center = self._drawing_crosshair_position() if self.magnifier_enabled else None
        if center is not None and QRectF(0, 0, image_size.width(), image_size.height()).contains(center):
            protected_rect = None
            if self.current is not None and len(self.line) == 2:
                protected_rect = QRectF(
                    self.image_to_widget(self.line[0]),
                    self.image_to_widget(self.line[1]),
                ).normalized()
            paint_magnifier(
                p, self.pixmap, image_size, center, self.image_to_widget(center),
                self.visibleRegion().boundingRect().intersected(self.rect()), self.scale,
                protected_rect=protected_rect, outline_width=self.annotation_line_width,
            )
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
            foreground = QColor(COLORS["on_accent"])
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
        protected_shapes = set(self._overlap_protected_shapes())
        covered = self._overlap_hiding_path(protected_shapes)
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
                and not self._is_overlap_hidden(
                    shape, covered=covered, protected_shapes=protected_shapes,
                )
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
            COLORS["danger"]
            if cluster.risk == CATEGORY_CONFLICT
            else COLORS["warning"]
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
        # Pending geometry can change before the queued repaint updates the cache.
        hits = (
            self._near_duplicate_marker_layout()
            if self.hide_at_crosshair or self.protect_selected_annotations
            else self._near_duplicate_marker_hits or self._near_duplicate_marker_layout()
        )
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
        return QColor(COLORS["background"])

    def transform_pos(self, point):
        """Convert from widget-logical coordinates to painter-logical coordinates."""
        return QPointF(point) / self.scale - self.offset_to_center()

    def image_to_widget(self, point):
        """Convert one image-coordinate point to Canvas widget coordinates."""
        return (QPointF(point) + self.offset_to_center()) * self.scale

    def refresh_pointer_coordinates(self, widget_position):
        """Refresh the status coordinates after view geometry changes."""
        position = self.transform_pos(QPointF(widget_position))
        self._pointer_global_pos = self.mapToGlobal(
            QPointF(widget_position).toPoint()
        )
        self._last_pointer_pos = QPointF(position)
        if self.drawing():
            self.update()
        shape = self._active_readout_shape()
        if shape is None and self._valid_pointer_position(position):
            shape = self.resolve_pointer_target(position).shape
        self._emit_coordinates(position, shape)
        if self.editing() and self._annotation_gesture_source != "mouse":
            self._refresh_hover(position, suppress_handles=self.multi_selection_mode)
        self.refresh_interaction_hint()

    def refresh_tracked_pointer_coordinates(self):
        """Reproject the last screen position after scrolling, panning or zoom."""
        if self._pointer_global_pos is None:
            self._emit_coordinates(None, self._active_readout_shape())
        else:
            self.refresh_pointer_coordinates(
                self.mapFromGlobal(self._pointer_global_pos)
            )

    @property
    def view_offset(self):
        return QPointF(self._view_offset)

    def set_view_offset(self, offset):
        self._view_offset = QPointF(offset)
        self.update()

    def reset_view_offset(self):
        self.set_view_offset(QPointF())

    @property
    def content_margins(self):
        return tuple(self._content_margins)

    def set_content_margins(self, left, top, right, bottom):
        self._content_margins = tuple(
            max(0.0, float(value))
            for value in (left, top, right, bottom)
        )
        self.updateGeometry()

    def reset_view_geometry(self):
        self._view_offset = QPointF()
        self._content_margins = (0.0, 0.0, 0.0, 0.0)
        self.updateGeometry()
        self.update()

    def offset_to_center(self):
        s = self.scale
        area = super(Canvas, self).size()
        image_size = self.pixmap_size
        w, h = image_size.width() * s, image_size.height() * s
        aw, ah = area.width(), area.height()
        left, top, right, bottom = self._content_margins
        content_width = left + w + right
        content_height = top + h + bottom
        x = left + max(0.0, (aw - content_width) / 2.0)
        y = top + max(0.0, (ah - content_height) / 2.0)
        return (
            QPointF(x, y) + self._view_offset
        ) / max(s, 0.01)

    def pan_canvas(self, delta):
        self.panRequest.emit(int(delta.x()), int(delta.y()))

    def _valid_pointer_position(self, pos):
        size = self.pixmap_size
        return (
            pos is not None and not size.isEmpty()
            and 0 <= pos.x() < size.width()
            and 0 <= pos.y() < size.height()
        )

    def _active_readout_shape(self):
        if self.current is not None:
            return self.current
        if self._annotation_gesture_source is not None:
            return self.interaction_snapshot.hover.shape or self.selected_shape
        return None

    def _emit_pointer_coordinates(self, pos):
        text = "X: —  Y: —"
        if self._valid_pointer_position(pos):
            text = "X: %d  Y: %d" % (math.floor(pos.x()), math.floor(pos.y()))
        self.coordinatesChanged.emit(text)

    def _emit_annotation_size(self, shape):
        text = ""
        if shape is self.current and shape is not None and len(self.line) >= 2:
            start, end = self.line[0], self.line[1]
            text = "W: %d  H: %d" % (
                abs(end.x() - start.x()), abs(end.y() - start.y()),
            )
        elif shape is not None and len(shape) >= 4:
            bounds = shape.bounding_rect()
            text = "W: %d  H: %d" % (bounds.width(), bounds.height())
        self.annotationSizeChanged.emit(text)

    def _emit_coordinates(self, pos, shape=None):
        self._emit_pointer_coordinates(pos)
        self._emit_annotation_size(shape)

    def out_of_pixmap(self, p):
        size = self.pixmap_size
        w, h = size.width(), size.height()
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
        self._pending_label_shape = self.current
        self.current = None
        self.set_hiding(False)
        try:
            # The modal label chooser processes repaints inside this signal.
            self.newShape.emit()
        finally:
            self._pending_label_shape = None
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
            left, top, right, bottom = self._content_margins
            scaled = self.scale * self.pixmap_size
            return QSize(
                int(math.ceil(scaled.width() + left + right)),
                int(math.ceil(scaled.height() + top + bottom)),
            )
        return super(Canvas, self).minimumSizeHint()

    def contextMenuEvent(self, event):
        if not self._request_context_menu(event.globalPos()):
            event.ignore()
            return
        event.accept()

    def _request_context_menu(self, global_position=None):
        if (
            not self.editing()
            or self.pixmap is None
            or self.pixmap.isNull()
        ):
            return False
        selected_count = len(self.selected_shapes)
        kind = (
            "blank" if not selected_count
            else "single" if selected_count == 1
            else "multiple"
        )
        if global_position is None:
            global_position = self.mapToGlobal(self._context_menu_anchor())
        self.contextMenuRequested.emit(CanvasContextRequest(
            kind=kind,
            global_position=global_position,
        ))
        return True

    def _context_menu_anchor(self):
        active = self.selection_snapshot.active
        if active is None:
            return self.rect().center()
        bounds = active.bounding_rect()
        scene_point = QPointF(bounds.left(), bounds.bottom())
        widget_point = (
            scene_point + self.offset_to_center()
        ) * self.scale
        return QPoint(
            max(0, min(self.width() - 1, round(widget_point.x()))),
            max(0, min(self.height() - 1, round(widget_point.y()))),
        )

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

        pixel_delta = ev.pixelDelta() if qt_version == 5 else QPoint()
        use_pixels = not pixel_delta.isNull()
        if use_pixels:
            h_delta = pixel_delta.x()
            v_delta = pixel_delta.y()

        mods = ev.modifiers()
        if mods & Qt.ControlModifier and v_delta:
            if ev.buttons() == Qt.NoButton:
                units = float(v_delta) / 120.0
                self.zoomRequest.emit(units, QPointF(ev.pos()))
        elif mods & Qt.ShiftModifier:
            horizontal_delta = v_delta or h_delta
            if horizontal_delta:
                self.scrollRequest.emit(
                    horizontal_delta,
                    Qt.Horizontal,
                    use_pixels,
                )
        else:
            if v_delta:
                self.scrollRequest.emit(v_delta, Qt.Vertical, use_pixels)
            if h_delta:
                self.scrollRequest.emit(h_delta, Qt.Horizontal, use_pixels)
        ev.accept()

    def keyPressEvent(self, ev):
        key = ev.key()
        if (
            key == Qt.Key_Menu
            or (
                key == Qt.Key_F10
                and ev.modifiers() & Qt.ShiftModifier
            )
        ):
            if self._request_context_menu():
                ev.accept()
                return
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
                tr('canvas.singleSelectionForArrows')
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
        self.refresh_interaction_hint(interactive=source == "keyboard")
        self._near_duplicate_marker_hits = tuple()
        self.update()
        self.annotationGestureStarted.emit(description)

    def _finish_annotation_gesture(self):
        self._overlap_drag_shape = None
        description = self._annotation_gesture_description
        if description is None:
            return
        self._annotation_gesture_description = None
        self._annotation_gesture_source = None
        self._near_duplicate_marker_hits = tuple()
        self.annotationGestureFinished.emit(description)
        self.refresh_interaction_hint()
        self.update()

    def cancel_annotation_gesture(self):
        self._overlap_drag_shape = None
        description = self._annotation_gesture_description
        if description is None:
            return
        self._annotation_gesture_description = None
        self._annotation_gesture_source = None
        self._held_arrow_keys.clear()
        self._near_duplicate_marker_hits = tuple()
        self.annotationGestureCanceled.emit(description)
        self.refresh_interaction_hint()
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
        self.update()

    def move_out_of_bound(self, step):
        points = [p1 + p2 for p1, p2 in zip(self.selected_shape.points, [step] * 4)]
        return True in map(self.out_of_pixmap, points)

    def set_last_label(self, text, line_color=None):
        assert text
        self.shapes[-1].label = text
        if line_color:
            self.shapes[-1].line_color = line_color
        self._pending_label_shape = None

        return self.shapes[-1]

    def undo_last_line(self):
        assert self.shapes
        self.current = self.shapes.pop()
        self.current.set_open()
        self.line.points = [self.current[-1], self.current[0]]
        self.drawingPolygon.emit(True)

    def reset_all_lines(self):
        assert self.shapes
        self._pending_label_shape = None
        self.current = self.shapes.pop()
        self.current.set_open()
        self.line.points = [self.current[-1], self.current[0]]
        self.drawingPolygon.emit(True)
        self.current = None
        self.drawingPolygon.emit(False)
        self.update()

    def cancel_current_drawing(self, force=False):
        """Finish the drawing lifecycle after a projected cancellation."""
        was_drawing = self.current is not None or self._pending_label_shape is not None
        self.current = None
        self._pending_label_shape = None
        self.line.points = []
        self.update()
        if was_drawing or force:
            self.drawingPolygon.emit(False)
        self._emit_annotation_size(None)

    @property
    def pixmap_size(self):
        """Logical image dimensions, independent from preview resolution."""
        if not self._pixmap_logical_size.isEmpty():
            return QSize(self._pixmap_logical_size)
        if self.pixmap:
            return self.pixmap.size()
        return QSize()

    def load_pixmap(self, pixmap, logical_size=None):
        self._image_layer_cache.clear()
        self.pixmap = pixmap
        self._pixmap_logical_size = self._coerce_pixmap_size(
            pixmap, logical_size
        )
        self.shapes = []
        self.current = None
        self._view_offset = QPointF()
        self._content_margins = (0.0, 0.0, 0.0, 0.0)
        self._reset_transient_interaction()
        self.imageSizeChanged.emit(self.pixmap_size)
        self._emit_coordinates(None)
        before = self._selection.snapshot
        after = self._selection.set_scene((), selected=())
        self._project_selection(before, after, emit=False)
        self.verified = False
        self.questioned = False
        self.visible.clear()
        self.set_near_duplicate_clusters(())
        self.update()

    def replace_pixmap(self, pixmap, logical_size=None):
        """Refresh only image pixels while preserving annotation view state."""
        self._image_layer_cache.clear()
        self.pixmap = pixmap
        self._pixmap_logical_size = self._coerce_pixmap_size(
            pixmap, logical_size
        )
        self.update()

    @staticmethod
    def _coerce_pixmap_size(pixmap, logical_size):
        if logical_size is None:
            return pixmap.size() if pixmap else QSize()
        size = (
            QSize(logical_size)
            if isinstance(logical_size, QSize)
            else QSize(*logical_size)
        )
        if size.isEmpty():
            raise ValueError("logical pixmap dimensions must be positive")
        return size

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
        self.update()

    def set_shape_visible(self, shape, value):
        self.set_shapes_visible((shape,), value)

    def set_shapes_visible(self, shapes, value):
        shapes = set(shapes)
        self.visible.update((shape, value) for shape in shapes)
        self._near_duplicate_marker_hits = tuple()
        if not value:
            if self.interaction_snapshot.hover.shape in shapes:
                self.un_highlight()
            if shapes.intersection(self._external_hover_shapes):
                self.set_external_hover_shapes(
                    item for item in self._external_hover_shapes
                    if item not in shapes
                )
        self.update()

    def current_cursor(self):
        cursor = QApplication.overrideCursor()
        if cursor is not None:
            cursor = cursor.shape()
        return cursor

    def override_cursor(self, cursor):
        self._cursor = cursor
        if cursor == CURSOR_DRAW:
            # Hide the native drawing cursor only over this Canvas, so modal
            # category choosers and other controls keep their normal pointer.
            self.setCursor(QCursor(cursor))
            self.restore_cursor()
            return
        if self.current_cursor() is None:
            QApplication.setOverrideCursor(cursor)
        else:
            QApplication.changeOverrideCursor(cursor)

    def restore_cursor(self):
        QApplication.restoreOverrideCursor()

    def reset_state(self):
        self.restore_cursor()
        self._image_layer_cache.clear()
        self.pixmap = None
        self._pixmap_logical_size = QSize()
        self.shapes = []
        self.current = None
        self._view_offset = QPointF()
        self._content_margins = (0.0, 0.0, 0.0, 0.0)
        self.set_near_duplicate_clusters(())
        self._reset_transient_interaction()
        self.imageSizeChanged.emit(self.pixmap_size)
        self._emit_coordinates(None)
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
        self._publish_interaction_hint("")
        self._overlap_drag_shape = None
        self._drawing_scene_cache.clear()
        self._pending_label_shape = None
        previous_hover_shape = self.interaction_snapshot.hover.shape
        if previous_hover_shape is not None:
            previous_hover_shape.highlight_clear()
        self._annotation_gesture_description = None
        self._annotation_gesture_source = None
        self._held_arrow_keys.clear()
        self._pan_dragging = False
        self._interaction.reset()
        self._external_hover_shapes = tuple()
        self._last_pointer_pos = None
        self._pointer_global_pos = None
        if previous_hover_shape is not None:
            self.hoverShapeChanged.emit(None)

    def set_drawing_shape_to_square(self, status):
        self.draw_square = status
