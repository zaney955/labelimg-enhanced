import re

try:
    from PyQt5.QtCore import *
    from PyQt5.QtGui import *
    from PyQt5.QtWidgets import *
except ImportError:
    from PyQt4.QtCore import *
    from PyQt4.QtGui import *

def _natural_label_key(text):
    parts = []
    for part in re.split(r"(\d+)", str(text).casefold()):
        if part.isdigit():
            parts.append((0, int(part), len(part)))
        else:
            parts.append((1, part))
    return tuple(parts), str(text)


class _LabelGroup(object):
    def __init__(self, label, shapes, scroll=0):
        self.label = label
        self.shapes = tuple(shapes)
        self.scroll = int(scroll)


class LabelGroupListWidget(QAbstractScrollArea):
    """Virtualized current-image label groups and annotation buttons.

    Canvas state is projected through ``set_scene`` and
    ``project_selection``. User gestures are returned as intent signals; the
    widget never mutates annotations or Canvas selection directly.
    """

    selectionRequested = pyqtSignal(object, object)
    visibilityRequested = pyqtSignal(object, bool)
    hoverRequested = pyqtSignal(object)
    groupEditRequested = pyqtSignal(str)
    instanceEditRequested = pyqtSignal(object)
    contextMenuRequested = pyqtSignal(object, object)
    summaryChanged = pyqtSignal(str)
    rowHoverChanged = pyqtSignal(object)

    row_height = 32
    marker_width = 3
    row_inset = 1
    label_min_width = 64
    label_max_width = 120
    label_width_ratio = 0.35
    count_area_width = 34
    visibility_area_width = 26
    arrow_area_width = 16
    chip_size = 24
    chip_gap = 4
    chip_step = chip_size + chip_gap
    drag_threshold = 5
    selected_fill_alpha = 48
    hover_background_alpha = 45
    separator_alpha = 45
    hidden_opacity = 0.45
    outline_width = 2.0

    def __init__(self, parent=None):
        super(LabelGroupListWidget, self).__init__(parent)
        self._scene_shapes = tuple()
        self._visible_shapes = set()
        self._groups = []
        self._groups_by_label = {}
        self._shape_to_group = {}
        self._selected = tuple()
        self._active = None
        self._filter_text = ""
        self._anchor = None
        self._focus_target = None
        self._local_hover = None
        self._projected_hover_shape = None
        self._last_hover_payload = None
        self._press = None
        self._dragging_strip = False
        self._context_target = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.verticalScrollBar().valueChanged.connect(self.viewport().update)

    # Scene projection -------------------------------------------------
    def set_scene(self, shapes, visible_shapes=None, reset_scroll=False):
        shapes = tuple(shapes)
        old_scroll = {
            group.label: group.scroll
            for group in self._groups
        }
        buckets = {}
        for shape in shapes:
            buckets.setdefault(str(shape.label), []).append(shape)
        groups = []
        for label in sorted(buckets, key=_natural_label_key):
            groups.append(_LabelGroup(
                label,
                buckets[label],
                0 if reset_scroll else old_scroll.get(label, 0),
            ))
        self._scene_shapes = shapes
        self._groups = groups
        self._groups_by_label = {group.label: group for group in groups}
        self._shape_to_group = {
            shape: group
            for group in groups
            for shape in group.shapes
        }
        self._visible_shapes = set(
            shapes if visible_shapes is None else visible_shapes
        )
        self._selected = tuple(
            shape for shape in self._selected if shape in self._shape_to_group
        )
        if self._active not in self._shape_to_group:
            self._active = None
        self._clamp_all_group_scrolls()
        self._update_scroll_range()
        self._emit_summary()
        self.viewport().update()

    def clear(self):
        self._selected = tuple()
        self._active = None
        self._anchor = None
        self._focus_target = None
        self._local_hover = None
        self._projected_hover_shape = None
        self.set_scene((), visible_shapes=(), reset_scroll=True)

    def add_shape(self, shape, visible=True):
        if shape in self._scene_shapes:
            self.set_shape_visible(shape, visible)
            self.refresh_shape(shape)
            return
        visible_shapes = set(self._visible_shapes)
        if visible:
            visible_shapes.add(shape)
        self.set_scene(
            self._scene_shapes + (shape,),
            visible_shapes=visible_shapes,
        )

    def remove_shape(self, shape):
        self.set_scene(
            tuple(item for item in self._scene_shapes if item is not shape),
            visible_shapes=tuple(
                item for item in self._visible_shapes if item is not shape
            ),
        )

    def refresh_shape(self, shape):
        if shape in self._scene_shapes:
            self.set_scene(self._scene_shapes, self._visible_shapes)

    def set_shape_visible(self, shape, visible):
        if visible:
            self._visible_shapes.add(shape)
        else:
            self._visible_shapes.discard(shape)
        self._emit_summary()
        self.viewport().update()

    def project_selection(self, shapes, active=None, reveal=True):
        selected_set = set(shapes)
        self._selected = tuple(
            shape for shape in self._scene_shapes if shape in selected_set
        )
        self._active = (
            active
            if active in selected_set and active in self._shape_to_group
            else None
        )
        if reveal and self._active is not None:
            self.ensure_shape_visible(self._active)
            self.ensure_group_visible(self._shape_to_group[self._active].label)
        self._emit_summary()
        self.viewport().update()

    def project_canvas_hover(self, shape):
        self._projected_hover_shape = (
            shape if shape in self._shape_to_group else None
        )
        self.viewport().update()

    def set_filter_text(self, text):
        text = str(text).strip().casefold()
        if text == self._filter_text:
            return
        self._filter_text = text
        self.verticalScrollBar().setValue(0)
        self._update_scroll_range()
        self._emit_summary()
        self.viewport().update()

    # Public queries ---------------------------------------------------
    def all_group_labels(self):
        return [group.label for group in self._groups]

    def group_labels(self):
        return [group.label for group in self._filtered_groups()]

    def group_shapes(self, label):
        group = self._groups_by_label.get(str(label))
        return tuple() if group is None else group.shapes

    def group_count(self):
        return len(self._filtered_groups())

    def total_group_count(self):
        return len(self._groups)

    def annotation_count(self):
        return sum(len(group.shapes) for group in self._filtered_groups())

    def total_annotation_count(self):
        return len(self._scene_shapes)

    def selected_shapes(self):
        return self._selected

    def active_shape(self):
        return self._active

    def projected_hover_shape(self):
        return self._projected_hover_shape

    def is_group_hovered(self, label):
        group = self._groups_by_label.get(str(label))
        return group is not None and self._row_is_hovered(group)

    def summary_text(self):
        groups = self._filtered_groups()
        shown_group_count = len(groups)
        shown_shapes = {
            shape for group in groups for shape in group.shapes
        }
        shown_annotation_count = len(shown_shapes)
        if self._filter_text:
            text = "显示 %d/%d 个标签组 · %d/%d 个标注" % (
                shown_group_count,
                len(self._groups),
                shown_annotation_count,
                len(self._scene_shapes),
            )
        else:
            text = "%d 个标签组 · %d 个标注" % (
                len(self._groups),
                len(self._scene_shapes),
            )
        hidden_selected = sum(
            1 for shape in self._selected if shape not in shown_shapes
        )
        if hidden_selected:
            text += " · 另有 %d 个已选标注未显示" % hidden_selected
        return text

    def group_visibility(self, label):
        shapes = self.group_shapes(label)
        visible_count = sum(
            shape in self._visible_shapes for shape in shapes
        )
        if not shapes or visible_count == 0:
            return Qt.Unchecked
        if visible_count == len(shapes):
            return Qt.Checked
        return Qt.PartiallyChecked

    def group_scroll(self, label):
        group = self._groups_by_label[str(label)]
        return group.scroll

    def maximum_group_scroll(self, label):
        group = self._groups_by_label[str(label)]
        return max(0, self._group_content_width(group) - self._button_view_width(group))

    def ensure_shape_visible(self, shape):
        group = self._shape_to_group.get(shape)
        if group is None:
            return
        index = group.shapes.index(shape)
        view_width = self._button_view_width(group)
        if view_width <= 0:
            return
        left = index * self.chip_step
        right = left + self.chip_size
        if left < group.scroll:
            group.scroll = left
        elif right > group.scroll + view_width:
            group.scroll = right - view_width
        self._clamp_group_scroll(group)
        self.viewport().update()

    def ensure_group_visible(self, label):
        labels = self.group_labels()
        if label not in labels:
            return
        index = labels.index(label)
        top = index * self.row_height
        bottom = top + self.row_height
        bar = self.verticalScrollBar()
        if top < bar.value():
            bar.setValue(top)
        elif bottom > bar.value() + self.viewport().height():
            bar.setValue(bottom - self.viewport().height())

    # Semantic geometry -----------------------------------------------
    def row_rect_for_label(self, label):
        labels = self.group_labels()
        if label not in labels:
            return QRect()
        return self._row_rect(labels.index(label))

    def group_body_rect(self, label):
        group = self._groups_by_label.get(str(label))
        if group is None:
            return QRect()
        return self._layout(group, self.row_rect_for_label(label))["label"]

    def visibility_rect_for_label(self, label):
        group = self._groups_by_label.get(str(label))
        if group is None:
            return QRect()
        return self._layout(group, self.row_rect_for_label(label))["visibility"]

    def count_rect_for_label(self, label):
        group = self._groups_by_label.get(str(label))
        if group is None:
            return QRect()
        return self._layout(group, self.row_rect_for_label(label))["count"]

    def instance_rect(self, shape):
        group = self._shape_to_group.get(shape)
        if group is None:
            return QRect()
        row_rect = self.row_rect_for_label(group.label)
        if not row_rect.isValid():
            return QRect()
        layout = self._layout(group, row_rect)
        index = group.shapes.index(shape)
        return self._chip_rect(group, index, layout)

    def target_at(self, point):
        hit = self._hit_test(point)
        return None if hit is None else hit[1]

    def tooltip_at(self, point):
        hit = self._hit_test(point)
        if hit is None:
            return ""
        kind, target, group = hit
        if kind == "instance":
            index = group.shapes.index(target) + 1
            bounds = target.bounding_rect()
            return "%s #%d｜x:%s y:%s w:%s h:%s" % (
                group.label,
                index,
                self._format_geometry(bounds.x()),
                self._format_geometry(bounds.y()),
                self._format_geometry(bounds.width()),
                self._format_geometry(bounds.height()),
            )
        visible = sum(
            shape in self._visible_shapes for shape in group.shapes
        )
        selected = sum(
            shape in self._selected for shape in group.shapes
        )
        return "%s｜%d 个标注｜可见 %d｜已选 %d" % (
            group.label,
            len(group.shapes),
            visible,
            selected,
        )

    # Painting ---------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, True)
        groups = self._filtered_groups()
        if not groups:
            self._paint_empty_state(painter)
            return
        first = max(0, self.verticalScrollBar().value() // self.row_height)
        last = min(
            len(groups),
            (self.verticalScrollBar().value() + self.viewport().height())
            // self.row_height + 2,
        )
        for row in range(first, last):
            self._paint_group(painter, groups[row], self._row_rect(row))

    def _paint_group(self, painter, group, row_rect):
        layout = self._layout(group, row_rect)
        foreground = self.palette().color(QPalette.Text)
        selected = [shape for shape in group.shapes if shape in self._selected]
        all_selected = bool(selected) and len(selected) == len(group.shapes)
        partial_selected = bool(selected) and not all_selected
        row_hovered = self._row_is_hovered(group)

        painter.save()
        if row_hovered:
            hover_background = QColor(self.palette().color(QPalette.Mid))
            hover_background.setAlpha(self.hover_background_alpha)
            painter.fillRect(row_rect, hover_background)

        separator = QColor(self.palette().color(QPalette.Mid))
        separator.setAlpha(self.separator_alpha)
        painter.fillRect(
            QRect(row_rect.left(), row_rect.bottom(), row_rect.width(), 1),
            separator,
        )

        if partial_selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.palette().color(QPalette.Highlight))
            painter.drawEllipse(QPointF(row_rect.left() + 3, row_rect.center().y()), 3, 3)
        elif all_selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.palette().color(QPalette.Highlight))
            painter.drawRoundedRect(
                QRectF(
                    row_rect.left(),
                    row_rect.top() + 4,
                    self.marker_width,
                    row_rect.height() - 8,
                ),
                1.5,
                1.5,
            )

        font = QFont(painter.font())
        font.setBold(all_selected)
        painter.setFont(font)
        painter.setPen(foreground)
        text = painter.fontMetrics().elidedText(
            group.label,
            Qt.ElideRight,
            max(0, layout["label"].width() - 8),
        )
        painter.drawText(layout["label"].adjusted(5, 0, -3, 0), Qt.AlignVCenter, text)

        self._paint_strip(painter, group, layout, foreground)
        self._paint_count(painter, group, layout["count"], foreground)
        self._paint_visibility(painter, group, layout["visibility"], foreground)
        self._paint_column_dividers(painter, layout)

        if row_hovered:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(
                self.palette().color(QPalette.Mid),
                1,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            ))
            painter.drawRoundedRect(QRectF(row_rect.adjusted(1, 1, -1, -1)), 3, 3)
        painter.restore()

    def _paint_strip(self, painter, group, layout, row_foreground):
        strip = layout["buttons"]
        painter.save()
        painter.setClipRect(strip)
        hovered_shape = self._hovered_shape()
        for index, shape in enumerate(group.shapes):
            rect = self._chip_rect(group, index, layout)
            if not rect.intersects(strip):
                continue
            color = QColor(shape.line_color)
            color.setAlpha(255)
            is_visible = shape in self._visible_shapes
            is_selected = shape in self._selected
            is_hovered = shape is hovered_shape
            painter.save()
            if not is_visible:
                painter.setOpacity(self.hidden_opacity)
            if is_selected and is_visible:
                fill = QColor(color)
                fill.setAlpha(self.selected_fill_alpha)
                painter.setBrush(fill)
            else:
                painter.setBrush(Qt.NoBrush)
            pen = QPen(
                color,
                self.outline_width,
                Qt.CustomDashLine if is_hovered else Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
            if is_hovered:
                pen.setDashPattern([3.0, 2.5])
            painter.setPen(pen)
            painter.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), 3, 3)
            font = QFont(painter.font())
            font.setBold(is_selected)
            painter.setFont(font)
            painter.setPen(self.palette().color(QPalette.Text))
            painter.drawText(rect, Qt.AlignCenter, str(index + 1))
            if not is_visible:
                slash = QColor(self.palette().color(QPalette.Text))
                painter.setPen(QPen(slash, 1.2, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(rect.topLeft() + QPoint(4, 4), rect.bottomRight() - QPoint(4, 4))
            painter.restore()
        painter.restore()

        if layout["overflow"]:
            self._paint_arrow(painter, group, layout["left_arrow"], -1, row_foreground)
            self._paint_arrow(painter, group, layout["right_arrow"], 1, row_foreground)

    def _paint_arrow(self, painter, group, rect, direction, color):
        enabled = group.scroll > 0 if direction < 0 else group.scroll < self.maximum_group_scroll(group.label)
        target = self._projected_hover_shape
        target_group = self._shape_to_group.get(target)
        emphasized = False
        if target_group is group and target is not None:
            index = group.shapes.index(target)
            content_left = index * self.chip_step
            content_right = content_left + self.chip_size
            if direction < 0:
                emphasized = content_left < group.scroll
            else:
                emphasized = content_right > group.scroll + self._button_view_width(group)
        painter.save()
        painter.setOpacity(1.0 if enabled else 0.25)
        pen = QPen(
            color,
            1.2,
            Qt.DashLine if emphasized else Qt.SolidLine,
            Qt.RoundCap,
            Qt.RoundJoin,
        )
        painter.setPen(pen)
        center = rect.center()
        dx = 3 * direction
        path = QPainterPath()
        path.moveTo(center.x() - dx, center.y() - 4)
        path.lineTo(center.x() + dx, center.y())
        path.lineTo(center.x() - dx, center.y() + 4)
        painter.drawPath(path)
        painter.restore()

    def _paint_count(self, painter, group, rect, foreground):
        painter.save()
        painter.setPen(foreground)
        painter.drawText(
            rect.adjusted(3, 0, -5, 0),
            Qt.AlignVCenter | Qt.AlignRight,
            "×%d" % len(group.shapes),
        )
        painter.restore()

    def _paint_column_dividers(self, painter, layout):
        color = QColor(self.palette().color(QPalette.Mid))
        color.setAlpha(self.separator_alpha)
        painter.save()
        top = layout["row"].top() + 5
        bottom = layout["row"].bottom() - 5
        height = max(0, bottom - top + 1)
        painter.fillRect(
            QRect(layout["count"].left(), top, 1, height),
            color,
        )
        painter.fillRect(
            QRect(layout["visibility"].left(), top, 1, height),
            color,
        )
        painter.restore()

    def _paint_visibility(self, painter, group, rect, color):
        state = self.group_visibility(group.label)
        center = rect.center()
        icon = QRectF(center.x() - 8, center.y() - 8, 16, 16)
        left = icon.left() + 1.5
        right = icon.right() - 1.5
        top = center.y() - 4
        bottom = center.y() + 4
        path = QPainterPath()
        path.moveTo(left, center.y())
        path.cubicTo(left + 3, top, right - 3, top, right, center.y())
        path.cubicTo(right - 3, bottom, left + 3, bottom, left, center.y())
        painter.save()
        painter.setOpacity(0.8 if state != Qt.Unchecked else 0.35)
        painter.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        if state == Qt.Checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(center, 2.25, 2.25)
        elif state == Qt.PartiallyChecked:
            painter.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(center.x() - 3, center.y()), QPointF(center.x() + 3, center.y()))
        else:
            painter.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(icon.topLeft() + QPointF(2, 2), icon.bottomRight() - QPointF(2, 2))
        painter.restore()

    def _paint_empty_state(self, painter):
        painter.save()
        painter.setPen(self.palette().color(QPalette.Mid))
        if self._filter_text and self._groups:
            title = "没有匹配的标签组"
            detail = "清除筛选以显示全部标签组"
        else:
            title = "当前图片暂无标注"
            detail = "按 W 创建标注框"
        center = self.viewport().rect().center()
        painter.drawText(
            QRect(8, center.y() - 24, self.viewport().width() - 16, 24),
            Qt.AlignCenter,
            title,
        )
        painter.drawText(
            QRect(8, center.y(), self.viewport().width() - 16, 24),
            Qt.AlignCenter,
            detail,
        )
        painter.restore()

    # Mouse interaction ------------------------------------------------
    def mouseMoveEvent(self, event):
        if self._press is not None and self._press[0] in ("instance", "strip"):
            distance = abs(event.pos().x() - self._press[3].x())
            if self._dragging_strip or distance >= self.drag_threshold:
                self._dragging_strip = True
                group = self._press[1]
                group.scroll = self._press[4] - (event.pos().x() - self._press[3].x())
                self._clamp_group_scroll(group)
                self.viewport().update()
                event.accept()
                return

        hit = self._hit_test(event.pos())
        local_hover = None if hit is None else (hit[0], hit[1])
        if local_hover != self._local_hover:
            self._local_hover = local_hover
            payload = self._hover_payload_for_hit(hit)
            self._emit_hover(payload)
            self.viewport().update()
        super(LabelGroupListWidget, self).mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._local_hover = None
        self._emit_hover(tuple())
        self.viewport().update()
        super(LabelGroupListWidget, self).leaveEvent(event)

    def mousePressEvent(self, event):
        hit = self._hit_test(event.pos())
        if event.button() != Qt.LeftButton:
            return super(LabelGroupListWidget, self).mousePressEvent(event)
        if hit is None:
            if event.modifiers() == Qt.NoModifier:
                self._request_selection(tuple(), None)
            return

        kind, target, group = hit
        if kind == "visibility":
            show = self.group_visibility(group.label) != Qt.Checked
            self.visibilityRequested.emit(group.shapes, show)
            event.accept()
            return
        if kind in ("left_arrow", "right_arrow"):
            direction = -1 if kind == "left_arrow" else 1
            if self._projected_hover_shape in group.shapes:
                self.ensure_shape_visible(self._projected_hover_shape)
            else:
                group.scroll += direction * max(self.chip_step, self._button_view_width(group) // 2)
                self._clamp_group_scroll(group)
                self.viewport().update()
            event.accept()
            return

        self._press = (kind, group, target, QPoint(event.pos()), group.scroll)
        self._dragging_strip = False
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._press is None:
            return super(LabelGroupListWidget, self).mouseReleaseEvent(event)
        kind, group, target, _point, _scroll = self._press
        dragged = self._dragging_strip
        self._press = None
        self._dragging_strip = False
        if dragged:
            event.accept()
            return
        if kind == "instance":
            self._select_instance(target, event.modifiers())
        elif kind in ("group", "label", "count", "strip"):
            self._select_group(group, event.modifiers())
        event.accept()

    def mouseDoubleClickEvent(self, event):
        hit = self._hit_test(event.pos())
        if hit is None:
            return
        kind, target, group = hit
        if kind == "instance":
            self.instanceEditRequested.emit(target)
        elif kind == "label":
            self.groupEditRequested.emit(group.label)
        event.accept()

    def wheelEvent(self, event):
        hit = self._hit_test(event.pos())
        horizontal = event.pixelDelta().x()
        if not horizontal and event.modifiers() & Qt.ShiftModifier:
            horizontal = event.angleDelta().y() / 2
        if horizontal and hit is not None:
            group = hit[2]
            group.scroll -= int(horizontal)
            self._clamp_group_scroll(group)
            self.viewport().update()
            event.accept()
            return
        super(LabelGroupListWidget, self).wheelEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.ContextMenu:
            self._handle_right_click(self._hit_test(event.pos()), event)
            return True
        if event.type() == QEvent.ToolTip:
            text = self.tooltip_at(event.pos())
            if not text:
                QToolTip.hideText()
                return True
            QToolTip.showText(event.globalPos(), text, self.viewport())
            return True
        return super(LabelGroupListWidget, self).viewportEvent(event)

    def _handle_right_click(self, hit, event):
        if hit is None:
            return
        kind, target, group = hit
        if kind == "instance":
            if target not in self._selected:
                self._anchor = self._point_anchor(target)
                self._request_selection((target,), target)
            context = ("instance", target)
        else:
            context = ("group", group.label)
        self._context_target = context
        global_pos = self.viewport().mapToGlobal(event.pos())
        self.contextMenuRequested.emit(context, global_pos)
        event.accept()

    # Selection --------------------------------------------------------
    def _select_instance(self, shape, modifiers):
        order = self._visual_shape_order()
        if shape not in order:
            return
        point = order.index(shape)
        if modifiers & Qt.ShiftModifier and self._anchor is not None:
            selected = self._range_from_anchor(point, order)
        elif modifiers & Qt.ControlModifier:
            selected_set = set(self._selected)
            if shape in selected_set:
                selected_set.remove(shape)
            else:
                selected_set.add(shape)
            selected = [
                item for item in self._scene_shapes
                if item in selected_set
            ]
        else:
            selected = [shape]
        self._anchor = (point, point)
        active = shape if shape in selected else (selected[-1] if len(selected) == 1 else None)
        self._focus_target = ("instance", shape)
        self._request_selection(tuple(selected), active)

    def _select_group(self, group, modifiers):
        order = self._visual_shape_order()
        indexes = [order.index(shape) for shape in group.shapes if shape in order]
        if not indexes:
            return
        interval = (min(indexes), max(indexes))
        if modifiers & Qt.ShiftModifier and self._anchor is not None:
            low = min(self._anchor[0], interval[0])
            high = max(self._anchor[1], interval[1])
            selected = order[low:high + 1]
        elif modifiers & Qt.ControlModifier:
            selected_set = set(self._selected)
            if all(shape in selected_set for shape in group.shapes):
                selected_set.difference_update(group.shapes)
            else:
                selected_set.update(group.shapes)
            selected = [
                shape for shape in self._scene_shapes
                if shape in selected_set
            ]
        else:
            selected = list(group.shapes)
        self._anchor = interval
        self._focus_target = ("group", group.label)
        active = selected[0] if len(selected) == 1 else None
        self._request_selection(tuple(selected), active)

    def _range_from_anchor(self, point, order):
        low = min(self._anchor[0], point)
        high = max(self._anchor[1], point)
        return order[low:high + 1]

    def _point_anchor(self, shape):
        order = self._visual_shape_order()
        if shape not in order:
            return None
        index = order.index(shape)
        return index, index

    def _request_selection(self, shapes, active):
        self.selectionRequested.emit(tuple(shapes), active)

    # Keyboard ---------------------------------------------------------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            order = self._visual_shape_order()
            self._anchor = (0, len(order) - 1) if order else None
            self._request_selection(tuple(order), None if len(order) != 1 else order[0])
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self._focus_target is not None:
            kind, target = self._focus_target
            if kind == "instance" and target in self._shape_to_group:
                self._focus_target = ("group", self._shape_to_group[target].label)
                self.viewport().update()
                event.accept()
                return
        if event.key() == Qt.Key_F2 and self._focus_target is not None:
            kind, target = self._focus_target
            if kind == "instance":
                self.instanceEditRequested.emit(target)
            else:
                self.groupEditRequested.emit(target)
            event.accept()
            return
        if event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            if self._move_focus(event.key()):
                if event.modifiers() & Qt.ShiftModifier:
                    self._select_focused(event.modifiers())
                event.accept()
                return
        if event.key() == Qt.Key_Space and self._focus_target is not None:
            self._select_focused(event.modifiers())
            event.accept()
            return
        super(LabelGroupListWidget, self).keyPressEvent(event)

    def _move_focus(self, key):
        groups = self._filtered_groups()
        if not groups:
            return False
        if self._focus_target is None:
            self._focus_target = ("group", groups[0].label)
            return True
        kind, target = self._focus_target
        if kind == "group":
            labels = [group.label for group in groups]
            row = labels.index(target) if target in labels else 0
            if key == Qt.Key_Right:
                shape = groups[row].shapes[0]
                self._focus_target = ("instance", shape)
                self.ensure_shape_visible(shape)
            elif key == Qt.Key_Up and row > 0:
                self._focus_target = ("group", labels[row - 1])
            elif key == Qt.Key_Down and row + 1 < len(labels):
                self._focus_target = ("group", labels[row + 1])
            else:
                return False
        else:
            group = self._shape_to_group.get(target)
            if group not in groups:
                return False
            row = groups.index(group)
            index = group.shapes.index(target)
            if key == Qt.Key_Left:
                if index > 0:
                    target = group.shapes[index - 1]
                elif row > 0:
                    target = groups[row - 1].shapes[-1]
                else:
                    self._focus_target = ("group", group.label)
                    return True
            elif key == Qt.Key_Right:
                if index + 1 < len(group.shapes):
                    target = group.shapes[index + 1]
                elif row + 1 < len(groups):
                    target = groups[row + 1].shapes[0]
                else:
                    return False
            elif key == Qt.Key_Up:
                if row == 0:
                    return False
                target = groups[row - 1].shapes[min(index, len(groups[row - 1].shapes) - 1)]
            else:
                if row + 1 >= len(groups):
                    return False
                target = groups[row + 1].shapes[min(index, len(groups[row + 1].shapes) - 1)]
            self._focus_target = ("instance", target)
            self.ensure_shape_visible(target)
            self.ensure_group_visible(self._shape_to_group[target].label)
        self.viewport().update()
        return True

    def _select_focused(self, modifiers):
        kind, target = self._focus_target
        if kind == "instance":
            self._select_instance(target, modifiers)
        else:
            group = self._groups_by_label.get(target)
            if group is not None:
                self._select_group(group, modifiers)

    # Layout and helpers ----------------------------------------------
    def resizeEvent(self, event):
        self._clamp_all_group_scrolls()
        self._update_scroll_range()
        super(LabelGroupListWidget, self).resizeEvent(event)

    def _filtered_groups(self):
        if not self._filter_text:
            return list(self._groups)
        return [
            group for group in self._groups
            if self._filter_text in group.label.casefold()
        ]

    def _visual_shape_order(self):
        return [
            shape
            for group in self._filtered_groups()
            for shape in group.shapes
        ]

    def _row_rect(self, row):
        top = row * self.row_height - self.verticalScrollBar().value()
        return QRect(0, top, max(0, self.viewport().width() - 1), self.row_height)

    def _layout(self, group, row_rect):
        available = max(0, row_rect.width())
        fixed_right = self.count_area_width + self.visibility_area_width
        maximum_label = min(self.label_max_width, int(available * self.label_width_ratio))
        label_width = max(
            min(self.label_min_width, max(34, available - fixed_right - self.chip_size - 12)),
            maximum_label,
        )
        label_width = min(label_width, max(34, available - fixed_right - self.chip_size - 12))
        label_rect = QRect(row_rect.left() + 6, row_rect.top(), label_width, row_rect.height())
        visibility = QRect(
            row_rect.right() - self.visibility_area_width + 1,
            row_rect.top(),
            self.visibility_area_width,
            row_rect.height(),
        )
        count = QRect(
            visibility.left() - self.count_area_width,
            row_rect.top(),
            self.count_area_width,
            row_rect.height(),
        )
        strip = QRect(
            label_rect.right() + 1,
            row_rect.top(),
            max(0, count.left() - label_rect.right() - 1),
            row_rect.height(),
        )
        overflow = self._group_content_width(group) > max(0, strip.width())
        if overflow:
            left_arrow = QRect(strip.left(), strip.top(), self.arrow_area_width, strip.height())
            right_arrow = QRect(strip.right() - self.arrow_area_width + 1, strip.top(), self.arrow_area_width, strip.height())
            buttons = strip.adjusted(self.arrow_area_width, 0, -self.arrow_area_width, 0)
        else:
            left_arrow = QRect()
            right_arrow = QRect()
            buttons = QRect(strip)
        return {
            "row": row_rect,
            "label": label_rect,
            "strip": strip,
            "buttons": buttons,
            "left_arrow": left_arrow,
            "right_arrow": right_arrow,
            "count": count,
            "visibility": visibility,
            "overflow": overflow,
        }

    def _chip_rect(self, group, index, layout):
        buttons = layout["buttons"]
        left = buttons.left() + index * self.chip_step - group.scroll
        top = buttons.top() + (buttons.height() - self.chip_size) // 2
        return QRect(left, top, self.chip_size, self.chip_size)

    def _group_content_width(self, group):
        if not group.shapes:
            return 0
        return len(group.shapes) * self.chip_step - self.chip_gap

    def _button_view_width(self, group):
        row = self.row_rect_for_label(group.label)
        if not row.isValid():
            row = QRect(0, 0, max(0, self.viewport().width() - 1), self.row_height)
        return max(0, self._layout(group, row)["buttons"].width())

    def _clamp_group_scroll(self, group):
        group.scroll = max(0, min(group.scroll, self.maximum_group_scroll(group.label)))

    def _clamp_all_group_scrolls(self):
        for group in self._groups:
            self._clamp_group_scroll(group)

    def _update_scroll_range(self):
        content_height = len(self._filtered_groups()) * self.row_height
        maximum = max(0, content_height - self.viewport().height())
        bar = self.verticalScrollBar()
        bar.setPageStep(self.viewport().height())
        bar.setSingleStep(self.row_height)
        bar.setRange(0, maximum)

    def _hit_test(self, point):
        groups = self._filtered_groups()
        content_y = point.y() + self.verticalScrollBar().value()
        row = content_y // self.row_height
        if row < 0 or row >= len(groups):
            return None
        group = groups[row]
        row_rect = self._row_rect(row)
        layout = self._layout(group, row_rect)
        if layout["visibility"].contains(point):
            return "visibility", group.label, group
        if layout["count"].contains(point):
            return "count", group.label, group
        if layout["overflow"] and layout["left_arrow"].contains(point):
            return "left_arrow", group.label, group
        if layout["overflow"] and layout["right_arrow"].contains(point):
            return "right_arrow", group.label, group
        if layout["buttons"].contains(point):
            for index, shape in enumerate(group.shapes):
                if self._chip_rect(group, index, layout).contains(point):
                    return "instance", shape, group
            return "strip", group.label, group
        if layout["label"].contains(point):
            return "label", group.label, group
        return "group", group.label, group

    def _hover_payload_for_hit(self, hit):
        if hit is None:
            return tuple()
        kind, target, group = hit
        if kind == "instance":
            return (target,) if target in self._visible_shapes else tuple()
        return tuple(
            shape for shape in group.shapes if shape in self._visible_shapes
        )

    def _emit_hover(self, payload):
        payload = tuple(payload)
        if payload == self._last_hover_payload:
            return
        self._last_hover_payload = payload
        self.hoverRequested.emit(payload)
        self.rowHoverChanged.emit(payload)

    def _row_is_hovered(self, group):
        if self._local_hover is not None:
            target = self._local_hover[1]
            if target == group.label:
                return True
            if target in group.shapes:
                return True
        return self._projected_hover_shape in group.shapes

    def _hovered_shape(self):
        if self._local_hover is not None and self._local_hover[0] == "instance":
            return self._local_hover[1]
        return self._projected_hover_shape

    def _emit_summary(self):
        self.summaryChanged.emit(self.summary_text())

    @staticmethod
    def _format_geometry(value):
        rounded = round(float(value))
        if abs(float(value) - rounded) < 0.01:
            return str(int(rounded))
        return ("%.1f" % float(value)).rstrip("0").rstrip(".")
