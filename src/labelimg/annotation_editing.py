"""Intent-level annotation editing and guarded history projection."""

from dataclasses import dataclass

from labelimg.annotation_history import (
    AnnotationBoxState,
    AnnotationHistory,
    AnnotationSnapshot,
    HistoryBusy,
    HistoryUnavailable,
)
from labelimg.annotation_storage import fingerprint_path


@dataclass(frozen=True)
class ProjectionRequest:
    snapshot: object
    affected_ids: tuple
    direction: str
    preserve_selection: bool


@dataclass(frozen=True)
class EditingResult:
    applied: bool
    direction: str | None
    description: str | None
    message: str
    canceled_pending: bool = False
    degraded: bool = False


class AnnotationEditingError(RuntimeError):
    pass


class ProjectionFailed(AnnotationEditingError):
    def __init__(self, message, target_error, rollback_error=None):
        super().__init__(message)
        self.target_error = target_error
        self.rollback_error = rollback_error


class AnnotationEditingController:
    """Coordinate capture, history state, and all-or-nothing projection."""

    def __init__(self, capture, project, history=None, on_degraded=None):
        self._capture = capture
        self._project = project
        self._history = history or AnnotationHistory()
        self._on_degraded = on_degraded
        self._image_key = None
        self._edit_token = None
        self._pending_cancel = None
        self._pending_kind = None
        self._degraded_images = set()

    @property
    def image_key(self):
        return self._image_key

    @property
    def view(self):
        if self._image_key is None:
            return None
        return self._history.view(self._image_key)

    @property
    def pending(self):
        return self._pending_cancel is not None

    @property
    def pending_kind(self):
        return self._pending_kind

    @property
    def edit_open(self):
        return self._edit_token is not None

    @property
    def degraded(self):
        return self._image_key in self._degraded_images

    def is_degraded(self, image_key):
        return str(image_key) in self._degraded_images

    def clear_degraded(self, image_key):
        self._degraded_images.discard(str(image_key))

    @property
    def history(self):
        return self._history

    @property
    def image_keys(self):
        return self._history.image_keys

    def has_image(self, image_key):
        return self._history.has_image(image_key)

    def view_image(self, image_key, touch=True):
        return (
            self._history.view(image_key)
            if touch
            else self._history.peek(image_key)
        )

    def dirty_views(self):
        return tuple(
            view
            for view in (
                self._history.peek(image_key)
                for image_key in self._history.image_keys
            )
            if view.dirty
        )

    def open_image(self, image_key, snapshot, saved_baseline=None):
        self._image_key = str(image_key)
        self._edit_token = None
        self.clear_pending()
        return self._history.open_image(
            self._image_key,
            snapshot,
            saved_baseline,
        )

    def select_image(self, image_key):
        self._image_key = str(image_key)
        self._edit_token = None
        self.clear_pending()
        return self.view

    def begin_edit(
        self,
        description,
        old_label=None,
        new_label=None,
    ):
        self._ensure_editable()
        if self._edit_token is not None:
            raise HistoryBusy("annotation edit already open")
        before = self._capture(self._image_key)
        self._edit_token = self._history.begin_edit(
            self._image_key,
            before,
            description,
            old_label=old_label,
            new_label=new_label,
        )
        return self._edit_token

    def commit_edit(self, affected_ids=()):
        if self._edit_token is None:
            raise AnnotationEditingError("no annotation edit is open")
        token = self._edit_token
        try:
            after = self._capture(self._image_key)
            transition = self._history.commit_edit(
                token, after, affected_ids=affected_ids
            )
            self._edit_token = None
            return transition
        except Exception as commit_error:
            self._restore_failed_edit(token, commit_error)
            raise

    def record_external_edit(self, description, affected_ids=()):
        """Adopt a legacy caller's already-applied mutation atomically."""
        self._ensure_editable()
        if self._edit_token is not None:
            return None
        view = self.view
        after = self._capture(self._image_key)
        if after == view.snapshot:
            return None
        token = self._history.begin_edit(
            self._image_key,
            view.snapshot,
            description,
        )
        try:
            return self._history.commit_edit(
                token,
                after,
                affected_ids=(
                    tuple(affected_ids)
                    or _changed_session_ids(view.snapshot, after)
                ),
            )
        except Exception as commit_error:
            self._restore_failed_edit(token, commit_error)
            raise

    def cancel_edit(self, restore=True):
        if self._edit_token is None:
            return False
        token = self._edit_token
        self._edit_token = None
        self._history.cancel_edit(token)
        if restore:
            self._project(
                ProjectionRequest(
                    snapshot=token.before,
                    affected_ids=(),
                    direction="cancel",
                    preserve_selection=True,
                )
            )
        return True

    def set_pending(self, kind, cancel):
        if self._pending_cancel is not None:
            raise AnnotationEditingError("pending annotation operation exists")
        self._pending_kind = str(kind)
        self._pending_cancel = cancel

    def clear_pending(self):
        self._pending_kind = None
        self._pending_cancel = None

    def undo(self):
        if self.pending:
            cancel = self._pending_cancel
            kind = self._pending_kind
            self.clear_pending()
            cancel()
            return EditingResult(
                applied=False,
                direction="undo",
                description=None,
                message="%s canceled" % kind,
                canceled_pending=True,
            )
        return self._apply_step("undo")

    def redo(self):
        if self.pending:
            return EditingResult(
                applied=False,
                direction="redo",
                description=None,
                message="Finish or cancel the current annotation operation",
            )
        return self._apply_step("redo")

    def mark_saved(self, revision_id, target, fingerprint):
        return self._history.mark_saved(
            self._image_key,
            revision_id,
            target,
            fingerprint,
        )

    def mark_image_saved(
        self, image_key, revision_id, target, fingerprint
    ):
        return self._history.mark_saved(
            image_key, revision_id, target, fingerprint
        )

    def update_baseline_fingerprint(self, image_key, fingerprint):
        return self._history.update_baseline_fingerprint(
            image_key, fingerprint
        )

    def set_target(self, image_key, target):
        return self._history.set_target(image_key, target)

    def rebase_image(self, image_key, snapshot, baseline):
        view = self._history.rebase(image_key, snapshot, baseline)
        self._degraded_images.discard(str(image_key))
        return view

    def rewrite_review_state(
        self,
        image_key,
        expected,
        replacement,
        fingerprint,
    ):
        return self._history.rewrite_review_state(
            image_key,
            expected,
            replacement,
            fingerprint,
        )

    def migrate_images(
        self,
        path_mapping,
        target_mapping=None,
        fingerprint_mapping=None,
    ):
        mapping = {
            str(source): str(destination)
            for source, destination in path_mapping.items()
        }
        migrated = self._history.migrate_images(
            mapping,
            target_mapping=target_mapping,
            fingerprint_mapping=fingerprint_mapping,
        )
        if self._image_key in mapping:
            self._image_key = mapping[self._image_key]
        self._degraded_images = {
            mapping.get(image_key, image_key)
            for image_key in self._degraded_images
        }
        return migrated

    def remove_images(self, image_keys):
        keys = tuple(str(key) for key in image_keys)
        removed = self._history.remove_images(keys)
        self._degraded_images.difference_update(keys)
        if self._image_key in keys:
            self._image_key = None
            self._edit_token = None
            self.clear_pending()
        return removed

    def clear_workspace(self):
        self._history.clear_workspace()
        self._image_key = None
        self._edit_token = None
        self.clear_pending()
        self._degraded_images.clear()

    def _apply_step(self, direction):
        self._ensure_editable()
        prepare = (
            self._history.prepare_undo
            if direction == "undo"
            else self._history.prepare_redo
        )
        try:
            step = prepare(self._image_key)
        except HistoryUnavailable as error:
            return EditingResult(
                applied=False,
                direction=direction,
                description=None,
                message=str(error),
            )

        request = ProjectionRequest(
            snapshot=step.target_snapshot,
            affected_ids=step.transition.affected_ids,
            direction=direction,
            preserve_selection=not bool(step.transition.affected_ids),
        )
        try:
            self._project(request)
        except Exception as target_error:
            rollback_request = ProjectionRequest(
                snapshot=step.source_snapshot,
                affected_ids=(),
                direction="rollback",
                preserve_selection=True,
            )
            try:
                self._project(rollback_request)
            except Exception as rollback_error:
                baseline = self._history.peek(
                    self._image_key
                ).saved_baseline
                self._history.abort_step(step)
                self._history.remove_images((self._image_key,))
                self._history.open_image(
                    self._image_key,
                    step.source_snapshot,
                    saved_baseline=baseline,
                )
                self._enter_degraded(target_error, rollback_error)
                raise ProjectionFailed(
                    "history projection and rollback both failed",
                    target_error,
                    rollback_error,
                ) from rollback_error
            self._history.abort_step(step)
            raise ProjectionFailed(
                "history projection failed; source was restored",
                target_error,
            ) from target_error

        self._history.commit_step(step)
        return EditingResult(
            applied=True,
            direction=direction,
            description=step.transition.description,
            message="%s %s" % (
                "Undid" if direction == "undo" else "Redid",
                step.transition.description,
            ),
        )

    def _restore_failed_edit(self, token, commit_error):
        """Restore the canonical pre-edit revision after record failure."""
        try:
            self._project(
                ProjectionRequest(
                    snapshot=token.before,
                    affected_ids=(),
                    direction="record-rollback",
                    preserve_selection=True,
                )
            )
        except Exception as rollback_error:
            baseline = self._history.peek(
                token.image_key
            ).saved_baseline
            try:
                self._history.cancel_edit(token)
            finally:
                self._history.remove_images((token.image_key,))
                self._history.open_image(
                    token.image_key,
                    token.before,
                    saved_baseline=baseline,
                )
                self._edit_token = None
                self._enter_degraded(commit_error, rollback_error)
            raise ProjectionFailed(
                "history recording and rollback both failed",
                commit_error,
                rollback_error,
            ) from rollback_error
        self._history.cancel_edit(token)
        self._edit_token = None

    def _ensure_editable(self):
        if self._image_key is None:
            raise AnnotationEditingError("no image history is active")
        if self.degraded:
            raise AnnotationEditingError(
                "annotation document is in degraded read-only state"
            )

    def _enter_degraded(self, target_error, rollback_error):
        self._degraded_images.add(self._image_key)
        if self._on_degraded is not None:
            self._on_degraded(
                self._image_key,
                target_error,
                rollback_error,
            )


class SessionIdentityAllocator:
    """Allocate stable, workspace-local annotation identities."""

    def __init__(self):
        self._next_id = 1

    def assign(self, shape):
        session_id = getattr(shape, "session_id", None)
        if session_id is None:
            session_id = self._next_id
            self._next_id += 1
            shape.session_id = session_id
        else:
            self._next_id = max(self._next_id, session_id + 1)
        return session_id

    def clear(self):
        self._next_id = 1


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
                else fingerprint_path(image_key)
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
            self.canvas.reset_overlap_cycle()
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

    from labelimg.shape import Shape

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

    def __init__(self, window, undo, redo, file_list):
        from PyQt5.QtCore import QObject

        class _Filter(QObject):
            def eventFilter(filter_self, watched, event):
                return self._event_filter(event)

        self._filter = _Filter(window)
        self._window = window
        self._undo = undo
        self._redo = redo
        self._file_list = file_list

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


def _changed_session_ids(before, after):
    before_by_id = {box.session_id: box for box in before.boxes}
    after_by_id = {box.session_id: box for box in after.boxes}
    return tuple(
        session_id
        for session_id in dict.fromkeys(
            tuple(before_by_id) + tuple(after_by_id)
        )
        if before_by_id.get(session_id) != after_by_id.get(session_id)
    )
