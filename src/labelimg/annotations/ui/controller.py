"""Qt projection adapters for annotation editing."""

from labelimg.annotations.application.editing import SessionIdentityAllocator
from labelimg.annotations.domain.history import AnnotationBoxState, AnnotationSnapshot
from labelimg.annotations.infrastructure.storage import fingerprint_image

class CanvasAnnotationScene:
    """Capture and project immutable snapshots at the real Canvas seam."""

    def __init__(
        self,
        canvas,
        identity_allocator=None,
        on_project=None,
        default_paint_labels=False,
    ):
        self.canvas = canvas
        self.identities = identity_allocator or SessionIdentityAllocator()
        self._on_project = on_project
        self._default_paint_labels = default_paint_labels
        self._last_snapshots = {}

    def capture(self, image_key):
        image_key = str(image_key)
        previous = self._last_snapshots.get(image_key)
        prior_boxes = {
            box.session_id: box
            for box in previous.boxes
        } if previous is not None else {}
        boxes = []
        for shape in self.canvas.shapes:
            session_id = self.identities.assign(shape)
            state = _box_state_from_shape(shape, session_id)
            prior = prior_boxes.get(session_id)
            boxes.append(prior if prior == state else state)
        pixmap = self.canvas.pixmap
        snapshot = AnnotationSnapshot(
            image_key=image_key,
            image_size=(
                pixmap.width() if pixmap is not None else 0,
                pixmap.height() if pixmap is not None else 0,
            ),
            boxes=tuple(boxes),
            verified=bool(self.canvas.verified),
            questioned=bool(self.canvas.questioned),
            image_fingerprint=(
                previous.image_fingerprint
                if previous is not None
                else fingerprint_image(
                    image_key,
                    (
                        pixmap.width() if pixmap is not None else 0,
                        pixmap.height() if pixmap is not None else 0,
                    ),
                )
            ),
        )
        self._last_snapshots[image_key] = snapshot
        return snapshot

    def project(self, request):
        from PyQt5.QtCore import QSignalBlocker

        snapshot = request.snapshot
        old_by_id = {
            shape.session_id: shape
            for shape in self.canvas.shapes
            if getattr(shape, "session_id", None) is not None
        }
        selected_ids = tuple(
            shape.session_id
            for shape in self.canvas.selected_shapes
            if getattr(shape, "session_id", None) is not None
        )
        active_id = (
            self.canvas.selected_shape.session_id
            if self.canvas.selected_shape is not None
            else None
        )
        visible_by_id = {
            session_id: self.canvas.isVisible(shape)
            for session_id, shape in old_by_id.items()
        }
        shapes = [
            _shape_from_box_state(
                state,
                old_by_id.get(state.session_id),
                self._default_paint_labels,
            )
            for state in snapshot.boxes
        ]
        by_id = {shape.session_id: shape for shape in shapes}

        blocker = QSignalBlocker(self.canvas)
        try:
            self.canvas.load_shapes(shapes)
            self.canvas.verified = bool(snapshot.verified)
            self.canvas.questioned = bool(snapshot.questioned)
            for session_id, visible in visible_by_id.items():
                shape = by_id.get(session_id)
                if shape is not None:
                    self.canvas.visible[shape] = visible

            if request.preserve_selection:
                result_ids = tuple(
                    session_id
                    for session_id in selected_ids
                    if session_id in by_id
                )
                result_active = (
                    by_id.get(active_id)
                    if active_id in result_ids
                    else None
                )
            else:
                affected = set(request.affected_ids)
                result_ids = tuple(
                    state.session_id
                    for state in snapshot.boxes
                    if state.session_id in affected
                )
                result_active = (
                    by_id[result_ids[-1]] if result_ids else None
                )
            self.canvas.set_selected_shapes(
                tuple(by_id[session_id] for session_id in result_ids),
                active_shape=result_active,
                emit=False,
            )
            self.canvas.un_highlight()
            self.canvas.set_external_hover_shape(None)
            if self._on_project is not None:
                self._on_project(snapshot, tuple(shapes), result_active)
            self.canvas.update()
        finally:
            del blocker
        self._last_snapshots[snapshot.image_key] = snapshot
        return tuple(shapes)

    def forget_image(self, image_key):
        self._last_snapshots.pop(str(image_key), None)

    def clear_workspace(self):
        self._last_snapshots.clear()
        self.identities.clear()


def _box_state_from_shape(shape, session_id):
    return AnnotationBoxState(
        session_id=session_id,
        label=str(shape.label or ""),
        points=tuple(
            (float(point.x()), float(point.y()))
            for point in shape.points
        ),
        line_rgba=_rgba(getattr(shape, "line_color", None)),
        fill_rgba=_rgba(getattr(shape, "fill_color", None)),
        difficult=bool(shape.difficult),
    )


def _rgba(color):
    return tuple(color.getRgb()) if color is not None else None


def _shape_from_box_state(state, prior_shape, default_paint_labels):
    from PyQt5.QtCore import QPointF
    from PyQt5.QtGui import QColor

    from labelimg.canvas import Shape

    shape = Shape(label=state.label)
    shape.session_id = state.session_id
    for x, y in state.points:
        shape.add_point(QPointF(x, y))
    shape.close()
    shape.difficult = bool(state.difficult)
    if state.line_rgba is not None:
        shape.line_color = QColor(*state.line_rgba)
    if state.fill_rgba is not None:
        shape.fill_color = QColor(*state.fill_rgba)
    if prior_shape is not None:
        shape.fill = prior_shape.fill
        shape.paint_label = prior_shape.paint_label
    else:
        shape.paint_label = bool(default_paint_labels)
    return shape


class AnnotationHistoryShortcutFilter:
    """Route history shortcuts without preempting native text Undo/Redo."""

    def __init__(
        self,
        window,
        undo,
        redo,
        file_list,
        scoped_history_active=None,
    ):
        from PyQt5.QtCore import QObject

        class _Filter(QObject):
            def eventFilter(filter_self, watched, event):
                return self._event_filter(event)

        self._filter = _Filter(window)
        self._window = window
        self._undo = undo
        self._redo = redo
        self._file_list = file_list
        self._scoped_history_active = (
            scoped_history_active or (lambda: False)
        )

    @property
    def qobject(self):
        return self._filter

    def _event_filter(self, event):
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtWidgets import (
            QApplication,
            QComboBox,
            QLineEdit,
            QPlainTextEdit,
            QSpinBox,
            QDoubleSpinBox,
            QTextEdit,
        )

        if event.type() not in (
            QEvent.ShortcutOverride,
            QEvent.KeyPress,
        ):
            return False
        modifiers = event.modifiers()
        if not (modifiers & Qt.ControlModifier):
            return False
        key = event.key()
        redo = (
            key == Qt.Key_Y
            or (
                key == Qt.Key_Z
                and modifiers & Qt.ShiftModifier
            )
        )
        undo = key == Qt.Key_Z and not redo
        if not undo and not redo:
            return False
        if QApplication.activeModalWidget() is not None:
            return False

        if self._scoped_history_active():
            event.accept()
            if event.type() == QEvent.ShortcutOverride:
                return True
            if not event.isAutoRepeat():
                (self._redo if redo else self._undo)()
            return True

        focus = QApplication.focusWidget()
        if _is_descendant(focus, self._file_list):
            event.accept()
            return True
        if isinstance(
            focus,
            (
                QLineEdit,
                QTextEdit,
                QPlainTextEdit,
                QSpinBox,
                QDoubleSpinBox,
            ),
        ):
            return False
        if isinstance(focus, QComboBox) and focus.isEditable():
            return False
        if focus is not None and not _is_descendant(focus, self._window):
            return False

        event.accept()
        if event.type() == QEvent.ShortcutOverride:
            return True
        if event.isAutoRepeat():
            return True
        (self._redo if redo else self._undo)()
        return True


def _is_descendant(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parentWidget()
    return False

