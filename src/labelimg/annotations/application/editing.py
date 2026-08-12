"""Intent-level annotation editing and guarded history projection."""

from dataclasses import dataclass

from labelimg.annotations.domain.history import (
    AnnotationBoxState,
    AnnotationHistory,
    AnnotationSnapshot,
    HistoryBusy,
    HistoryUnavailable,
)
from labelimg.annotations.infrastructure.storage import fingerprint_image


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
        if self._edit_token is not None or self.pending:
            raise HistoryBusy(
                "cannot open another image during an annotation edit"
            )
        self._image_key = str(image_key)
        return self._history.open_image(
            self._image_key,
            snapshot,
            saved_baseline,
        )

    def select_image(self, image_key):
        if self._edit_token is not None or self.pending:
            raise HistoryBusy(
                "cannot select another image during an annotation edit"
            )
        self._image_key = str(image_key)
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

    def cancel_pending_operation(self):
        if not self.pending:
            return None
        cancel = self._pending_cancel
        kind = self._pending_kind
        self.clear_pending()
        cancel()
        return kind

    def undo(self):
        if self.pending:
            kind = self.cancel_pending_operation()
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
            view = self._history.peek(self._image_key)
            boundary_evicted = (
                view.undo_boundary_evicted
                if direction == "undo"
                else view.redo_boundary_evicted
            )
            return EditingResult(
                applied=False,
                direction=direction,
                description=None,
                message=(
                    "Earlier %s history was evicted by retention limits"
                    % direction.capitalize()
                    if boundary_evicted
                    else str(error)
                ),
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
