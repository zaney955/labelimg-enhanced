"""Canvas overlay and compact controls for direct image cropping."""

from __future__ import annotations

from PyQt5.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QContextMenuEvent,
    QCursor,
    QPainter,
    QPen,
)
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QMenu,
    QPushButton,
    QSpinBox,
    QWidget,
)

from labelimg.localization.runtime import tr
from labelimg.ui.actions import new_icon
from labelimg.image_tools.domain.crop_geometry import CropRegion


class CropOverlay(QWidget):
    regionChanged = pyqtSignal(object)
    pointerPositionChanged = pyqtSignal(object)
    historyChanged = pyqtSignal(bool, bool)
    applyRequested = pyqtSignal()
    cancelRequested = pyqtSignal()

    HANDLE_SIZE = 9
    EDGE_HIT_TOLERANCE = 6
    HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self._image_size = (0, 0)
        self._region = None
        self._ratio = None
        self._states = [None]
        self._state_index = 0
        self._drag_mode = None
        self._drag_anchor = None
        self._drag_region = None
        self._gesture_before = None
        self._cursor_override_owned = False
        self._previous_cursor_shape = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.hide()
        canvas.installEventFilter(self)

    @property
    def region(self):
        return self._region

    @property
    def ratio(self):
        return self._ratio

    @property
    def can_undo(self):
        return self._state_index > 0

    @property
    def can_redo(self):
        return self._state_index + 1 < len(self._states)

    @property
    def handle_rects(self):
        if self._region is None:
            return {}
        rect = self._widget_region(self._region)
        points = {
            "nw": rect.topLeft(),
            "n": QPointF(rect.center().x(), rect.top()),
            "ne": rect.topRight(),
            "e": QPointF(rect.right(), rect.center().y()),
            "se": rect.bottomRight(),
            "s": QPointF(rect.center().x(), rect.bottom()),
            "sw": rect.bottomLeft(),
            "w": QPointF(rect.left(), rect.center().y()),
        }
        half = self.HANDLE_SIZE // 2
        return {
            name: QRect(
                round(point.x()) - half,
                round(point.y()) - half,
                self.HANDLE_SIZE,
                self.HANDLE_SIZE,
            )
            for name, point in points.items()
        }

    def begin(self, image_size):
        previous_cursor = QApplication.overrideCursor()
        self._previous_cursor_shape = (
            previous_cursor.shape() if previous_cursor is not None else None
        )
        self._image_size = tuple(map(int, image_size))
        self._region = None
        self._ratio = None
        self._states = [None]
        self._state_index = 0
        self._sync_geometry()
        self.show()
        self.raise_()
        self.setFocus(Qt.ShortcutFocusReason)
        if not self._cursor_override_owned:
            QApplication.setOverrideCursor(QCursor(Qt.CrossCursor))
            self._cursor_override_owned = True
        else:
            QApplication.changeOverrideCursor(QCursor(Qt.CrossCursor))
        self._emit_history()
        self.update()

    def finish(self):
        self._drag_mode = None
        self._drag_anchor = None
        self._drag_region = None
        self.hide()
        if self._cursor_override_owned:
            QApplication.restoreOverrideCursor()
            self._cursor_override_owned = False
        if self._previous_cursor_shape is not None:
            previous_cursor = QCursor(self._previous_cursor_shape)
            if QApplication.overrideCursor() is None:
                QApplication.setOverrideCursor(previous_cursor)
            else:
                QApplication.changeOverrideCursor(previous_cursor)
        self._previous_cursor_shape = None

    def set_ratio(self, ratio):
        self._ratio = tuple(ratio) if ratio else None
        if self._region is not None and self._ratio is not None:
            self.set_region(
                _fit_ratio_around_center(
                    self._region,
                    self._ratio,
                    self._image_size,
                )
            )

    def set_region(self, region, *, record=True):
        if region is not None:
            region = _clamp_region(region, self._image_size)
        if region == self._region:
            return False
        self._region = region
        if record:
            self._record_state(region)
        self.regionChanged.emit(region)
        self.update()
        return True

    def undo(self):
        if not self.can_undo:
            return False
        self._state_index -= 1
        self._restore_state()
        return True

    def redo(self):
        if not self.can_redo:
            return False
        self._state_index += 1
        self._restore_state()
        return True

    def eventFilter(self, watched, event):
        if watched is self.canvas and event.type() in (
            QEvent.Resize,
            QEvent.Show,
        ):
            self._sync_geometry()
        return super().eventFilter(watched, event)

    def paintEvent(self, _event):
        if self._region is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        image_rect = self._widget_image_rect()
        region_rect = self._widget_region(self._region)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 115))
        painter.drawRect(QRectF(
            image_rect.left(),
            image_rect.top(),
            image_rect.width(),
            max(0.0, region_rect.top() - image_rect.top()),
        ))
        painter.drawRect(QRectF(
            image_rect.left(),
            region_rect.bottom(),
            image_rect.width(),
            max(0.0, image_rect.bottom() - region_rect.bottom()),
        ))
        painter.drawRect(QRectF(
            image_rect.left(),
            region_rect.top(),
            max(0.0, region_rect.left() - image_rect.left()),
            region_rect.height(),
        ))
        painter.drawRect(QRectF(
            region_rect.right(),
            region_rect.top(),
            max(0.0, image_rect.right() - region_rect.right()),
            region_rect.height(),
        ))
        accent = QColor("#2f8fd3")
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(accent, 2))
        painter.drawRect(region_rect)
        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(QPen(accent, 2))
        for handle in self.handle_rects.values():
            painter.drawRect(handle)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        image_point = self._image_point(event.pos())
        handle = self._hit_target(event.pos())
        self._gesture_before = self._region
        self._drag_anchor = image_point
        self._drag_region = self._region
        if handle is not None:
            self._drag_mode = "resize:" + handle
        elif self._region is not None and _contains(self._region, image_point):
            self._drag_mode = "move"
        else:
            self._drag_mode = "create"
            self._assign_region(None)
        event.accept()

    def mouseMoveEvent(self, event):
        image_point = self._image_point(event.pos())
        if self._region is None:
            pointer_position = self._pointer_image_position(event.pos())
            if pointer_position is not None:
                self.pointerPositionChanged.emit(pointer_position)
        if self._drag_mode is None:
            self._update_cursor(event.pos(), image_point)
            return
        if self._drag_mode == "create":
            region = _region_from_points(
                self._drag_anchor,
                image_point,
                self._ratio,
                self._image_size,
            )
        elif self._drag_mode == "move":
            region = _move_region(
                self._drag_region,
                image_point[0] - self._drag_anchor[0],
                image_point[1] - self._drag_anchor[1],
                self._image_size,
            )
        else:
            region = _resize_region(
                self._drag_region,
                self._drag_mode.partition(":")[2],
                image_point,
                self._ratio,
                self._image_size,
            )
        self._assign_region(region)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_mode is not None:
            self._drag_mode = None
            if self._region != self._gesture_before:
                self._record_state(self._region)
            self._gesture_before = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        global_position = event.globalPos()
        if event.reason() == QContextMenuEvent.Keyboard:
            global_position = self.mapToGlobal(self._context_menu_anchor())
        self._show_context_menu(global_position)
        event.accept()

    def build_context_menu(self):
        menu = QMenu(self)
        undo_action = menu.addAction(
            new_icon("undo"),
            tr("crop.undo"),
            self.undo,
        )
        undo_action.setEnabled(self.can_undo)
        redo_action = menu.addAction(
            new_icon("redo"),
            tr("crop.redo"),
            self.redo,
        )
        redo_action.setEnabled(self.can_redo)
        menu.addSeparator()
        apply_action = menu.addAction(
            new_icon("crop"),
            tr("crop.apply"),
            self.applyRequested.emit,
        )
        apply_action.setEnabled(self._valid_region())
        menu.addAction(
            new_icon("close"),
            tr("common.cancel"),
            self.cancelRequested.emit,
        )
        return menu

    def _show_context_menu(self, global_position):
        menu = self.build_context_menu()
        try:
            menu.exec_(global_position)
        finally:
            menu.deleteLater()

    def _valid_region(self):
        return bool(
            self._region is not None
            and not self._region.is_full_image(self._image_size)
        )

    def _context_menu_anchor(self):
        if self._region is None:
            return self.rect().center()
        return self._widget_region(self._region).bottomLeft().toPoint()

    def wheelEvent(self, event):
        self.canvas.wheelEvent(event)

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        if (
            event.key() == Qt.Key_Menu
            or (
                event.key() == Qt.Key_F10
                and modifiers & Qt.ShiftModifier
            )
        ):
            self._show_context_menu(
                self.mapToGlobal(self._context_menu_anchor())
            )
            event.accept()
            return
        if modifiers & Qt.ControlModifier and event.key() == Qt.Key_Z:
            (self.redo if modifiers & Qt.ShiftModifier else self.undo)()
            event.accept()
            return
        if modifiers & Qt.ControlModifier and event.key() == Qt.Key_Y:
            self.redo()
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self._region is not None and not self._region.is_full_image(
                self._image_size
            ):
                self.applyRequested.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.cancelRequested.emit()
            event.accept()
            return
        directions = {
            Qt.Key_Left: (-1, 0),
            Qt.Key_Right: (1, 0),
            Qt.Key_Up: (0, -1),
            Qt.Key_Down: (0, 1),
        }
        if self._region is not None and event.key() in directions:
            step = 10 if modifiers & Qt.ShiftModifier else 1
            dx, dy = directions[event.key()]
            self.set_region(_move_region(
                self._region,
                dx * step,
                dy * step,
                self._image_size,
            ))
            event.accept()
            return
        super().keyPressEvent(event)

    def _sync_geometry(self):
        self.setGeometry(self.canvas.rect())

    def _image_point(self, widget_point):
        point = self.canvas.transform_pos(widget_point)
        width, height = self._image_size
        return (
            min(max(int(round(point.x())), 0), width),
            min(max(int(round(point.y())), 0), height),
        )

    def _pointer_image_position(self, widget_point):
        point = self.canvas.transform_pos(widget_point)
        width, height = self._image_size
        if not (0 <= point.x() < width and 0 <= point.y() < height):
            return None
        return int(point.x()), int(point.y())

    def _widget_point(self, x, y):
        point = (
            QPointF(x, y) + self.canvas.offset_to_center()
        ) * self.canvas.scale
        return point

    def _widget_image_rect(self):
        top_left = self._widget_point(0, 0)
        bottom_right = self._widget_point(*self._image_size)
        return QRectF(top_left, bottom_right).normalized()

    def _widget_region(self, region):
        return QRectF(
            self._widget_point(region.x, region.y),
            self._widget_point(region.right, region.bottom),
        ).normalized()

    def _assign_region(self, region):
        if region == self._region:
            return
        self._region = region
        self.regionChanged.emit(region)
        self.update()

    def _record_state(self, region):
        self._states = self._states[:self._state_index + 1]
        if self._states[-1] != region:
            self._states.append(region)
            self._state_index += 1
        self._emit_history()

    def _restore_state(self):
        self._region = self._states[self._state_index]
        self.regionChanged.emit(self._region)
        self._emit_history()
        self.update()

    def _emit_history(self):
        self.historyChanged.emit(self.can_undo, self.can_redo)

    def _update_cursor(self, widget_point, image_point):
        handle = self._hit_target(widget_point)
        cursors = {
            "n": Qt.SizeVerCursor,
            "s": Qt.SizeVerCursor,
            "e": Qt.SizeHorCursor,
            "w": Qt.SizeHorCursor,
            "nw": Qt.SizeFDiagCursor,
            "se": Qt.SizeFDiagCursor,
            "ne": Qt.SizeBDiagCursor,
            "sw": Qt.SizeBDiagCursor,
        }
        if handle is not None:
            self._set_cursor(cursors[handle])
        elif self._region is not None and _contains(self._region, image_point):
            self._set_cursor(Qt.SizeAllCursor)
        else:
            self._set_cursor(Qt.CrossCursor)

    def _set_cursor(self, shape):
        cursor = QCursor(shape)
        self.setCursor(cursor)
        if self._cursor_override_owned:
            QApplication.changeOverrideCursor(cursor)

    def _hit_target(self, widget_point):
        if self._region is None:
            return None
        rect = self._widget_region(self._region)
        x = widget_point.x()
        y = widget_point.y()
        tolerance = self.EDGE_HIT_TOLERANCE
        near_left = abs(x - rect.left()) <= tolerance
        near_right = abs(x - rect.right()) <= tolerance
        near_top = abs(y - rect.top()) <= tolerance
        near_bottom = abs(y - rect.bottom()) <= tolerance
        within_x = rect.left() - tolerance <= x <= rect.right() + tolerance
        within_y = rect.top() - tolerance <= y <= rect.bottom() + tolerance

        # Corners win over edges, and edges win over moving the interior.
        if near_left and near_top:
            return "nw"
        if near_right and near_top:
            return "ne"
        if near_right and near_bottom:
            return "se"
        if near_left and near_bottom:
            return "sw"
        if near_top and within_x:
            return "n"
        if near_right and within_y:
            return "e"
        if near_bottom and within_x:
            return "s"
        if near_left and within_y:
            return "w"
        return None


class CropControlBar(QFrame):
    """Transient floating controls projected from one crop overlay."""

    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self._image_size = (0, 0)
        self._syncing = False
        self._drag_offset = None
        self._user_moved = False
        self.setObjectName("cropControlBar")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "#cropControlBar { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 4px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(5)
        layout.setSizeConstraint(QLayout.SetFixedSize)

        self.drag_handle = QLabel("⋮⋮", self)
        self.drag_handle.setCursor(Qt.SizeAllCursor)
        self.drag_handle.installEventFilter(self)
        layout.addWidget(self.drag_handle)

        self.labels = {}
        self.labels["ratio"] = QLabel(tr("crop.ratio"), self)
        layout.addWidget(self.labels["ratio"])
        self.ratio_combo = QComboBox(self)
        self._ratio_items = (
            ("crop.ratio.free", None),
            ("crop.ratio.original", "original"),
            ("crop.ratio.square", (1, 1)),
            ("crop.ratio.fourThree", (4, 3)),
            ("crop.ratio.sixteenNine", (16, 9)),
        )
        for message_id, value in self._ratio_items:
            self.ratio_combo.addItem(tr(message_id), value)
        layout.addWidget(self.ratio_combo)
        layout.addWidget(self._separator())

        self.spins = {}
        for key, message_id in (
            ("x", "crop.x"),
            ("y", "crop.y"),
            ("width", "crop.width"),
            ("height", "crop.height"),
        ):
            self.labels[key] = QLabel(tr(message_id), self)
            spin = QSpinBox(self)
            spin.setKeyboardTracking(False)
            spin.setMinimum(0)
            spin.setEnabled(False)
            spin.setFixedWidth(82)
            spin.valueChanged.connect(self._values_changed)
            spin.editingFinished.connect(
                lambda target=overlay: target.setFocus(
                    Qt.OtherFocusReason
                )
            )
            self.spins[key] = spin
            layout.addWidget(self.labels[key])
            layout.addWidget(spin)

        layout.addWidget(self._separator())
        self.apply_button = QPushButton(tr("crop.apply"), self)
        self.cancel_button = QPushButton(tr("common.cancel"), self)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(overlay.applyRequested.emit)
        self.cancel_button.clicked.connect(overlay.cancelRequested.emit)
        layout.addWidget(self.apply_button)
        layout.addWidget(self.cancel_button)

        self.ratio_combo.currentIndexChanged.connect(self._ratio_changed)
        overlay.regionChanged.connect(self._region_changed)
        overlay.pointerPositionChanged.connect(self._pointer_position_changed)
        if parent is not None:
            parent.installEventFilter(self)
        self.hide()

    def begin(self, image_size):
        self._image_size = tuple(map(int, image_size))
        width, height = self._image_size
        self.spins["x"].setRange(0, max(0, width - 1))
        self.spins["y"].setRange(0, max(0, height - 1))
        self.spins["width"].setRange(0, max(1, width))
        self.spins["height"].setRange(0, max(1, height))
        self.ratio_combo.setCurrentIndex(0)
        self._region_changed(None)
        self._user_moved = False
        self.adjustSize()
        self._place_initial()
        self.show()
        self.raise_()

    def finish(self):
        self.hide()

    def retranslate(self):
        self.setWindowTitle(tr("crop.controls"))
        self.labels["ratio"].setText(tr("crop.ratio"))
        for key, message_id in (
            ("x", "crop.x"),
            ("y", "crop.y"),
            ("width", "crop.width"),
            ("height", "crop.height"),
        ):
            self.labels[key].setText(tr(message_id))
        for index, (message_id, _value) in enumerate(
            self._ratio_items
        ):
            self.ratio_combo.setItemText(index, tr(message_id))
        self.apply_button.setText(tr("crop.apply"))
        self.cancel_button.setText(tr("common.cancel"))
        self.adjustSize()
        if self.isVisible():
            if self._user_moved:
                self._clamp_position()
            else:
                self._place_initial()

    def _ratio_changed(self):
        value = self.ratio_combo.currentData()
        if value == "original":
            value = self._image_size
        self.overlay.set_ratio(value)

    def _region_changed(self, region):
        self._syncing = True
        try:
            enabled = region is not None
            self.spins["x"].setEnabled(True)
            self.spins["y"].setEnabled(True)
            self.spins["x"].setReadOnly(not enabled)
            self.spins["y"].setReadOnly(not enabled)
            self.spins["width"].setEnabled(enabled)
            self.spins["height"].setEnabled(enabled)
            if enabled:
                self.spins["x"].setValue(region.x)
                self.spins["y"].setValue(region.y)
                self.spins["width"].setValue(region.width)
                self.spins["height"].setValue(region.height)
            else:
                for key in ("x", "y", "width", "height"):
                    self.spins[key].setValue(0)
            self.apply_button.setEnabled(
                enabled and not region.is_full_image(self._image_size)
            )
        finally:
            self._syncing = False

    def _pointer_position_changed(self, point):
        if self.overlay.region is not None:
            return
        self._syncing = True
        try:
            self.spins["x"].setValue(point[0])
            self.spins["y"].setValue(point[1])
        finally:
            self._syncing = False

    def _values_changed(self):
        if self._syncing or self.overlay.region is None:
            return
        x = self.spins["x"].value()
        y = self.spins["y"].value()
        width = self.spins["width"].value()
        height = self.spins["height"].value()
        ratio = self.overlay.ratio
        sender = self.sender()
        if ratio:
            ratio_width, ratio_height = ratio
            if sender is self.spins["height"]:
                width = max(
                    1,
                    round(height * ratio_width / ratio_height),
                )
            elif sender is self.spins["width"]:
                height = max(
                    1,
                    round(width * ratio_height / ratio_width),
                )
        self.overlay.set_region(CropRegion(x, y, width, height))

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            if self.isVisible():
                if self._user_moved:
                    self._clamp_position()
                else:
                    self._place_initial()
        elif watched is self.drag_handle:
            if (
                event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
            ):
                self._begin_drag(event.globalPos())
                return True
            if (
                event.type() == QEvent.MouseMove
                and self._drag_offset is not None
            ):
                self._continue_drag(event.globalPos())
                return True
            if (
                event.type() == QEvent.MouseButtonRelease
                and event.button() == Qt.LeftButton
            ):
                self._drag_offset = None
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._begin_drag(event.globalPos())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self._continue_drag(event.globalPos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _separator(self):
        separator = QFrame(self)
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        return separator

    def _begin_drag(self, global_position):
        self._drag_offset = global_position - self.mapToGlobal(QPoint())

    def _continue_drag(self, global_position):
        parent = self.parentWidget()
        if parent is None:
            return
        self._user_moved = True
        requested = parent.mapFromGlobal(global_position - self._drag_offset)
        self.move(self._bounded_position(requested))

    def _place_initial(self):
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(self._bounded_position(QPoint(
            (parent.width() - self.width()) // 2,
            8,
        )))

    def _clamp_position(self):
        if self.parentWidget() is not None:
            self.move(self._bounded_position(self.pos()))

    def _bounded_position(self, position):
        parent = self.parentWidget()
        if parent is None:
            return position
        return QPoint(
            min(
                max(position.x(), 0),
                max(0, parent.width() - self.width()),
            ),
            min(
                max(position.y(), 0),
                max(0, parent.height() - self.height()),
            ),
        )


def _contains(region, point):
    x, y = point
    return region.x <= x <= region.right and region.y <= y <= region.bottom


def _clamp_region(region, image_size):
    width, height = image_size
    region_width = min(max(int(region.width), 1), width)
    region_height = min(max(int(region.height), 1), height)
    x = min(max(int(region.x), 0), width - region_width)
    y = min(max(int(region.y), 0), height - region_height)
    return CropRegion(x, y, region_width, region_height)


def _region_from_points(anchor, point, ratio, image_size):
    ax, ay = anchor
    px, py = point
    dx = px - ax
    dy = py - ay
    if dx == 0 and dy == 0:
        return None
    if ratio:
        rw, rh = ratio
        extent_x = abs(dx)
        extent_y = abs(dy)
        if extent_x / rw > extent_y / rh:
            extent_x = round(extent_y * rw / rh)
        else:
            extent_y = round(extent_x * rh / rw)
        dx = max(1, extent_x) * (-1 if dx < 0 else 1)
        dy = max(1, extent_y) * (-1 if dy < 0 else 1)
        px, py = ax + dx, ay + dy
    left, right = sorted((ax, px))
    top, bottom = sorted((ay, py))
    if right <= left or bottom <= top:
        return None
    return _clamp_region(
        CropRegion(left, top, right - left, bottom - top),
        image_size,
    )


def _move_region(region, dx, dy, image_size):
    width, height = image_size
    x = min(max(region.x + int(round(dx)), 0), width - region.width)
    y = min(max(region.y + int(round(dy)), 0), height - region.height)
    return CropRegion(x, y, region.width, region.height)


def _resize_region(region, handle, point, ratio, image_size):
    left, top, right, bottom = (
        region.x,
        region.y,
        region.right,
        region.bottom,
    )
    x, y = point
    if "w" in handle:
        left = min(x, right - 1)
    if "e" in handle:
        right = max(x, left + 1)
    if "n" in handle:
        top = min(y, bottom - 1)
    if "s" in handle:
        bottom = max(y, top + 1)
    resized = _clamp_region(
        CropRegion(left, top, right - left, bottom - top),
        image_size,
    )
    if ratio:
        if handle in ("nw", "ne", "se", "sw"):
            opposite = {
                "nw": (region.right, region.bottom),
                "ne": (region.x, region.bottom),
                "se": (region.x, region.y),
                "sw": (region.right, region.y),
            }[handle]
            return _region_from_points(opposite, point, ratio, image_size)
        return _fit_ratio_around_center(resized, ratio, image_size)
    return resized


def _fit_ratio_around_center(region, ratio, image_size):
    rw, rh = ratio
    center_x = region.x + region.width / 2
    center_y = region.y + region.height / 2
    if region.width / rw > region.height / rh:
        width = region.width
        height = max(1, round(width * rh / rw))
    else:
        height = region.height
        width = max(1, round(height * rw / rh))
    image_width, image_height = image_size
    if width > image_width or height > image_height:
        factor = min(image_width / width, image_height / height)
        width = max(1, round(width * factor))
        height = max(1, round(height * factor))
    return _clamp_region(
        CropRegion(
            round(center_x - width / 2),
            round(center_y - height / 2),
            width,
            height,
        ),
        image_size,
    )
