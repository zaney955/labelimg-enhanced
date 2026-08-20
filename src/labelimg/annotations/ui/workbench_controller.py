"""AnnotationActionsMixin extracted from the top-level workbench window."""

#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os.path


from PyQt5.QtCore import QFileSystemWatcher, QPointF, QSignalBlocker, QTimer, Qt
from PyQt5.QtGui import QColor, QCursor
from PyQt5.QtWidgets import QApplication, QMenu, QMessageBox

import labelimg.ui.generated_resources  # noqa: F401 - registers Qt resources
from labelimg.ui.actions import set_action_copy
from labelimg.annotations.ui.style import generate_color_by_text
from labelimg.canvas import Shape
from labelimg.localization.runtime import localize_message_box_buttons, question as localized_question, tr, translate_history_description
from labelimg.annotations.domain.model import (
    AnnotationDocument,
    AnnotationDocumentError,
    AnnotationFormat,
)
from labelimg.annotations.ui.canvas_adapter import (
    document_from_shapes,
    shapes_from_document,
)
from labelimg.annotations.application.workspace import annotation_resources
from labelimg.annotations.application.editing import ProjectionFailed
from labelimg.annotations.domain.history import UnknownImageHistory
from labelimg.annotations.infrastructure.storage import AnnotationStorageConflict, fingerprint_path
from labelimg.platform.text import native_text as ustr
from labelimg.workbench.support import document_format_name, read_image as read


class AnnotationActionsMixin:
    def _initialize_annotation_live_sync(self):
        self._annotation_file_watcher = QFileSystemWatcher(self)
        self._annotation_file_watcher.fileChanged.connect(
            self._annotation_resource_changed
        )
        self._annotation_file_watcher.directoryChanged.connect(
            self._annotation_resource_changed
        )
        self._annotation_live_sync_timer = QTimer(self)
        self._annotation_live_sync_timer.setSingleShot(True)
        self._annotation_live_sync_timer.setInterval(400)
        self._annotation_live_sync_timer.timeout.connect(
            self._process_external_annotation_change
        )
        self._annotation_watch_image = None
        self._annotation_watch_target = None
        self._annotation_known_choices = ()

    def _watch_current_annotation_document(self):
        watcher = getattr(self, '_annotation_file_watcher', None)
        if watcher is None:
            return
        watched = watcher.files() + watcher.directories()
        if watched:
            watcher.removePaths(watched)
        self._annotation_watch_image = (
            os.path.abspath(self.file_path) if self.file_path else None
        )
        self._annotation_watch_target = None
        self._annotation_known_choices = ()
        if not self.file_path:
            return
        target = os.path.abspath(self._current_annotation_target())
        self._annotation_watch_target = target
        try:
            choices = self.annotation_workspace.refresh_document_choices(
                self.file_path
            )
        except AnnotationDocumentError:
            choices = self.annotation_workspace.document_choices(
                self.file_path
            )
        self._annotation_known_choices = tuple(
            sorted(os.path.abspath(choice.annotation_path) for choice in choices)
        )
        directory = os.path.dirname(target)
        paths = []
        if os.path.isdir(directory):
            paths.append(directory)
        if os.path.isfile(target):
            paths.append(target)
        if paths:
            watcher.addPaths(paths)

    def _annotation_resource_changed(self, _path):
        if (
            self.file_path
            and self._annotation_watch_image == os.path.abspath(self.file_path)
        ):
            self._annotation_live_sync_timer.start()

    @staticmethod
    def _annotation_content_signature(snapshot):
        return (
            tuple(
                (
                    box.label,
                    box.points,
                    box.line_rgba,
                    box.fill_rgba,
                    box.difficult,
                )
                for box in snapshot.boxes
            ),
            snapshot.verified,
            snapshot.questioned,
        )

    @staticmethod
    def _annotation_document_content_signature(document):
        def color(value, label):
            return (
                tuple(value)
                if value is not None
                else generate_color_by_text(label).getRgb()
            )

        return (
            tuple(
                (
                    box.label,
                    tuple(tuple(point) for point in box.points),
                    color(box.line_color, box.label),
                    color(box.fill_color, box.label),
                    box.difficult,
                )
                for box in document.boxes
            ),
            document.verified,
            document.questioned,
        )

    def _process_external_annotation_change(self):
        if (
            not self.file_path
            or self._annotation_watch_image != os.path.abspath(self.file_path)
        ):
            return
        if self.annotation_editing.pending or self.annotation_editing.edit_open:
            self._annotation_live_sync_timer.start()
            return
        image_key = os.path.abspath(self.file_path)
        view = self.annotation_editing.view
        if view is None:
            return
        try:
            choices = self.annotation_workspace.refresh_document_choices(
                image_key
            )
        except AnnotationDocumentError as error:
            self.status(
                tr(
                    'external.invalid',
                    path=self._annotation_watch_target or '',
                    error=error,
                ),
                0,
            )
            self._watch_current_annotation_document()
            return
        choice_paths = tuple(
            sorted(os.path.abspath(choice.annotation_path) for choice in choices)
        )
        if (
            choice_paths != self._annotation_known_choices
            and len(choice_paths) > 1
        ):
            self._annotation_known_choices = choice_paths
            if not self._ensure_active_annotation_choice(
                image_key, force=True
            ):
                self._watch_current_annotation_document()
                return
        target = os.path.abspath(self._current_annotation_target())
        baseline = view.saved_baseline
        mismatches = (
            self.annotation_persistence.baseline_mismatches(baseline)
            if baseline is not None
            else ()
        )
        if view.dirty and mismatches:
            error = AnnotationStorageConflict(mismatches)
            self.annotation_persistence.register_conflict(error, image_key)
            self._handle_annotation_storage_conflict(error)
            self._watch_current_annotation_document()
            return
        if not mismatches and target == view.current_target:
            self._watch_current_annotation_document()
            return
        try:
            if os.path.isfile(target):
                loaded = self.annotation_workspace.load(
                    target, image_key, self.image_data
                )
                document = loaded.document
                self.set_format(document_format_name(loaded.annotation_format))
            else:
                document = AnnotationDocument(
                    image_path=image_key,
                    image_data=self.image_data,
                )
        except AnnotationDocumentError as error:
            self.status(
                tr('external.invalid', path=target, error=error),
                0,
            )
            self._watch_current_annotation_document()
            return
        if (
            target == view.current_target
            and self._annotation_document_content_signature(document)
            == self._annotation_content_signature(view.snapshot)
        ):
            self.annotation_workspace.refresh_resource(target)
            self.annotation_editing.update_baseline_fingerprint(
                image_key, self._annotation_baseline(target)[1]
            )
            self.annotation_workspace.record_document(
                image_key,
                target,
                (box.label for box in document.boxes),
            )
            self.refresh_candidate_labels()
            self._watch_current_annotation_document()
            return
        self.clear_current_labels()
        self.load_annotation_document(document)
        snapshot = self.annotation_scene.capture(image_key)
        self.annotation_editing.rebase_image(
            image_key,
            snapshot,
            baseline=self._annotation_baseline(target),
        )
        self.annotation_workspace.record_document(
            image_key,
            target,
            (box.label for box in document.boxes),
        )
        self._sync_annotation_history_ui()
        self.refresh_candidate_labels()
        self.update_file_list_item_status(image_key)
        self.status(tr('external.loaded', path=target), 10000)
        self._watch_current_annotation_document()

    def set_format(self, save_format):
        if save_format == AnnotationFormat.PASCAL_VOC.display_name:
            self.annotation_format = AnnotationFormat.PASCAL_VOC

        elif save_format == AnnotationFormat.YOLO.display_name:
            self.annotation_format = AnnotationFormat.YOLO

        elif save_format == AnnotationFormat.CREATE_ML.display_name:
            self.annotation_format = AnnotationFormat.CREATE_ML
        if hasattr(self, 'format_selector'):
            self.format_selector.set_format(self.annotation_format)


    def change_format(self):
        """Open the explicit format choices retained by the File menu."""
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self.status(tr('status.finishEdit'))
            return
        if hasattr(self, 'format_selector'):
            self.format_selector.menu.popup(QCursor.pos())


    def set_annotation_format(self, annotation_format):
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self.status(tr('status.finishEdit'))
            self.format_selector.set_format(self.annotation_format)
            return
        self.set_format(document_format_name(annotation_format))
        if self.annotation_editing.view is not None:
            self.annotation_editing.set_target(
                self.file_path,
                self._current_annotation_target(),
            )
            self._sync_annotation_history_ui()
            self._watch_current_annotation_document()
        else:
            self.set_dirty()


    def no_shapes(self):
        return not self.canvas.shapes


    def _current_annotation_target(self):
        if not self.file_path:
            return None
        active = self.annotation_workspace.active_document_path(
            self.file_path
        )
        if active is not None:
            try:
                if (
                    AnnotationFormat.from_path(active)
                    is self.annotation_format
                ):
                    return active
            except AnnotationDocumentError:
                pass
        return self.annotation_workspace.entry(
            self.file_path
        ).path_for(self.annotation_format)


    def _activate_annotation_history(self):
        if not self.file_path:
            return
        image_key = os.path.abspath(self.file_path)
        try:
            view = self.annotation_editing.view_image(image_key)
        except UnknownImageHistory:
            snapshot = self.annotation_scene.capture(image_key)
            target = self._current_annotation_target()
            view = self.annotation_editing.open_image(
                image_key,
                snapshot,
                saved_baseline=self._annotation_baseline(target),
            )
        else:
            self.annotation_editing.select_image(image_key)
            loaded_snapshot = self.annotation_scene.capture(image_key)
            if view.dirty:
                if loaded_snapshot != view.snapshot:
                    self.annotation_scene.project(
                        self._history_projection_request(
                            view.snapshot,
                            direction='activate',
                            preserve_selection=True,
                        )
                    )
            elif (
                self._annotation_content_signature(loaded_snapshot)
                != self._annotation_content_signature(view.snapshot)
            ):
                target = self._current_annotation_target()
                view = self.annotation_editing.rebase_image(
                    image_key,
                    loaded_snapshot,
                    baseline=self._annotation_baseline(target),
                )
            else:
                target = self._current_annotation_target()
                baseline = view.saved_baseline
                if (
                    baseline is not None
                    and not self.annotation_persistence.baseline_is_current(
                        baseline
                    )
                ):
                    self.annotation_editing.update_baseline_fingerprint(
                        image_key, self._annotation_baseline(target)[1]
                    )
                if loaded_snapshot != view.snapshot:
                    self.annotation_scene.project(
                        self._history_projection_request(
                            view.snapshot,
                            direction='activate',
                            preserve_selection=True,
                        )
                    )
        self._watch_current_annotation_document()
        self._sync_annotation_history_ui()


    @staticmethod
    def _history_projection_request(
        snapshot,
        affected_ids=(),
        direction='project',
        preserve_selection=False,
    ):
        from labelimg.annotations.application.editing import ProjectionRequest
        return ProjectionRequest(
            snapshot=snapshot,
            affected_ids=tuple(affected_ids),
            direction=direction,
            preserve_selection=preserve_selection,
        )


    def _project_annotation_history(
        self,
        snapshot,
        shapes,
        active_shape,
    ):
        focus = QApplication.focusWidget()
        for shape in shapes:
            shape.paint_label = self.display_label_option.isChecked()
        self.label_list.set_scene(
            shapes,
            visible_shapes=(
                shape for shape in shapes
                if self.canvas.isVisible(shape)
            ),
        )
        self.shape_selection_changed(bool(self.canvas.selected_shapes))
        if active_shape is not None:
            self.label_list.ensure_shape_visible(active_shape)
        if focus is not None:
            focus.setFocus(Qt.OtherFocusReason)


    def _annotation_projection_degraded(
        self,
        image_key,
        target_error,
        rollback_error,
    ):
        recovery_error = None
        try:
            view = self.annotation_editing.view_image(
                image_key, touch=False
            )
            baseline = view.saved_baseline
            if (
                baseline is not None
                and baseline.target
                and self.annotation_persistence.baseline_is_current(baseline)
                and os.path.isfile(baseline.target)
            ):
                loaded = self.annotation_workspace.load(
                    baseline.target,
                    image_key,
                    self.image_data,
                )
                self.clear_current_labels()
                self.load_annotation_document(loaded.document)
                snapshot = self.annotation_scene.capture(image_key)
                self.annotation_editing.rebase_image(
                    image_key,
                    snapshot,
                    baseline=(baseline.target, baseline.fingerprint),
                )
                self.annotation_editing.clear_degraded(image_key)
                self.status(
                    tr('history.reloadedAfterFailure'),
                    10000,
                )
                return
        except Exception as error:
            recovery_error = error
        self.status(
            tr(
                'history.failureDetail',
                image=os.path.basename(image_key),
                projection=target_error,
                rollback=rollback_error,
                reload=recovery_error or tr('history.unavailable'),
            ),
            10000,
        )
        for action in (
            self.actions.create,
            self.actions.delete,
            self.actions.copy,
            self.actions.pasteAnnotations,
            self.actions.undoAnnotation,
            self.actions.redoAnnotation,
        ):
            action.setEnabled(False)


    def _begin_annotation_gesture(self, description):
        if not self.file_path or self.annotation_editing.edit_open:
            return
        self.annotation_editing.begin_edit(description)
        self.annotation_editing.set_pending(
            description,
            self.canvas.cancel_annotation_gesture,
        )
        self._sync_annotation_history_ui()


    def _finish_annotation_gesture(self, _description):
        if not self.annotation_editing.edit_open:
            return
        self.annotation_editing.clear_pending()
        affected_ids = tuple(
            shape.session_id
            for shape in self.canvas.selected_shapes
            if shape.session_id is not None
        )
        self.annotation_editing.commit_edit(affected_ids)
        self._after_annotation_edit()


    def _cancel_annotation_gesture(self, _description):
        if not self.annotation_editing.edit_open:
            return
        self.annotation_editing.clear_pending()
        self.annotation_editing.cancel_edit(restore=True)
        self._sync_annotation_history_ui()


    def _cancel_annotation_edit_for_navigation(self):
        if self.annotation_editing.pending:
            self.annotation_editing.cancel_pending_operation()
        elif self.annotation_editing.edit_open:
            self.annotation_editing.cancel_edit(restore=True)
        self._sync_annotation_history_ui()


    def _annotation_drawing_state_changed(self, drawing):
        if not self.file_path:
            return
        if drawing:
            if not self.annotation_editing.edit_open:
                self.annotation_editing.begin_edit('Create box')
                self.annotation_editing.set_pending(
                    'Drawing',
                    self._cancel_pending_drawing,
                )
        elif (
            self.annotation_editing.edit_open
            and self.canvas.current is None
        ):
            self.annotation_editing.clear_pending()
            self.annotation_editing.cancel_edit(restore=False)
        self._sync_annotation_history_ui()


    def _cancel_pending_drawing(self):
        self.annotation_editing.cancel_edit(restore=True)
        self.canvas.cancel_current_drawing(force=True)


    def _after_annotation_edit(self):
        self._sync_annotation_history_ui()
        if self.annotation_editing.view is not None:
            if self.annotation_editing.view.dirty:
                self.annotation_persistence.track(
                    self.annotation_editing.view
                )
            else:
                self.annotation_persistence.release(
                    self.annotation_editing.view
                )
        target = self._current_annotation_target()
        if (
            target
            and target.lower().endswith(AnnotationFormat.YOLO.extension)
            and self.annotation_editing.view is not None
        ):
            self.annotation_workspace.reserve_yolo_labels(
                box.label
                for box in self.annotation_editing.view.snapshot.boxes
            )
        if target:
            self.annotation_workspace.record_document(
                self.file_path,
                target,
                (
                    shape.label
                    for shape in self.canvas.shapes
                    if shape.label
                ),
            )
            self.refresh_candidate_labels()
        self.update_file_list_item_status(self.file_path)


    def _perform_annotation_edit(
        self,
        description,
        mutation,
        affected=None,
        old_label=None,
        new_label=None,
    ):
        if self.annotation_editing.view is None:
            result = mutation()
            self.set_dirty()
            return result
        self.annotation_editing.begin_edit(
            description,
            old_label=old_label,
            new_label=new_label,
        )
        try:
            result = mutation()
            for shape in self.canvas.shapes:
                self.annotation_scene.identities.assign(shape)
            affected_shapes = (
                affected(result)
                if callable(affected)
                else affected
            )
            if affected_shapes is None:
                affected_shapes = self.canvas.selected_shapes
            affected_ids = tuple(
                shape.session_id
                for shape in affected_shapes
                if shape is not None
                and getattr(shape, 'session_id', None) is not None
            )
            self.annotation_editing.commit_edit(affected_ids)
        except Exception:
            if self.annotation_editing.edit_open:
                self.annotation_editing.cancel_edit(restore=True)
            raise
        self._after_annotation_edit()
        return result


    def _sync_annotation_history_ui(self):
        view = self.annotation_editing.view
        if view is None:
            set_action_copy(
                self.actions.undoAnnotation,
                tr('action.undo'),
                tr('history.undo'),
            )
            set_action_copy(
                self.actions.redoAnnotation,
                tr('action.redo'),
                tr('history.redo'),
            )
            self.actions.undoAnnotation.setEnabled(False)
            self.actions.redoAnnotation.setEnabled(False)
            return
        self.dirty = view.dirty
        self.actions.save.setEnabled(
            self.dirty and not self.annotation_editing.degraded
        )
        if self.annotation_editing.degraded:
            self.actions.saveAs.setEnabled(True)
        undo = view.undo_transition
        redo = view.redo_transition
        if self.annotation_editing.pending:
            undo_text = tr(
                'history.cancel',
                operation=translate_history_description(
                    self.annotation_editing.pending_kind
                ),
            )
        else:
            undo_text = self._history_action_text(
                tr('history.undo'), undo, 'Ctrl+Z'
            )
        redo_text = self._history_action_text(
            tr('history.redo'),
            redo,
            'Ctrl+Y / Ctrl+Shift+Z',
        )
        set_action_copy(
            self.actions.undoAnnotation,
            undo_text,
            tr('history.undo'),
        )
        set_action_copy(
            self.actions.redoAnnotation,
            redo_text,
            tr('history.redo'),
        )
        self.actions.undoAnnotation.setEnabled(
            (view.can_undo or self.annotation_editing.pending)
            and not self.annotation_editing.degraded
        )
        self.actions.redoAnnotation.setEnabled(
            view.can_redo
            and not self.annotation_editing.pending
            and not self.annotation_editing.degraded
        )
        if (
            self.dirty
            and self.auto_saving.isChecked()
            and self.file_path
            and not self.annotation_editing.pending
            and not self.annotation_editing.edit_open
        ):
            self.auto_save_timer.start()
        else:
            self.auto_save_timer.stop()


    def _rebase_current_history(self, annotation_path):
        if self.annotation_editing.view is None:
            self.set_clean()
            return
        snapshot = self.annotation_scene.capture(self.file_path)
        self.annotation_editing.rebase_image(
            self.file_path,
            snapshot,
            baseline=self._annotation_baseline(annotation_path),
        )
        self.annotation_editing.select_image(self.file_path)
        self._sync_annotation_history_ui()
        self._watch_current_annotation_document()


    def _annotation_baseline(self, annotation_path):
        annotation_path = os.path.abspath(
            os.fspath(annotation_path)
        )
        annotation_format = AnnotationFormat.from_path(annotation_path)
        return (
            annotation_path,
            tuple(
                (resource, fingerprint_path(resource))
                for resource in annotation_resources(
                    annotation_format, annotation_path
                )
            ),
        )


    @staticmethod
    def _history_action_text(prefix, transition, shortcut):
        description = transition.description if transition else ''
        if (
            transition is not None
            and transition.old_label is not None
            and transition.new_label is not None
        ):
            description = 'Change label: %s \u2192 %s' % (
                transition.old_label,
                transition.new_label,
            )
        description = translate_history_description(description)
        if len(description) > 80:
            description = description[:79].rstrip() + '\u2026'
        description = description.replace('&', '&&')
        count = transition.affected_count if transition else 0
        if count > 1 and str(count) not in description:
            description = tr(
                'history.multiple',
                description=description,
                count=count,
            )
        text = prefix + ((' ' + description) if description else '')
        return '%s\t%s' % (text, shortcut)


    def undo_annotation(self, _checked=False):
        if self._crop_active:
            self.crop_overlay.undo()
            return
        if self.annotation_editing.view is None:
            return
        try:
            result = self.annotation_editing.undo()
        except ProjectionFailed as error:
            self.error_message(
                tr('history.undoFailed'),
                '<p>%s</p>' % error,
            )
            return
        self._after_annotation_edit()
        self.status(result.message)


    def redo_annotation(self, _checked=False):
        if self._crop_active:
            self.crop_overlay.redo()
            return
        if self.annotation_editing.view is None:
            return
        try:
            result = self.annotation_editing.redo()
        except ProjectionFailed as error:
            self.error_message(
                tr('history.redoFailed'),
                '<p>%s</p>' % error,
            )
            return
        self._after_annotation_edit()
        self.status(result.message)


    def set_dirty(self):
        if (
            hasattr(self, 'annotation_editing')
            and self.annotation_editing.view is not None
            and not self.annotation_editing.edit_open
            and not self.annotation_editing.pending
        ):
            self.annotation_editing.record_external_edit(
                'Edit annotations'
            )
            self._after_annotation_edit()
            return
        self.dirty = True
        self.actions.save.setEnabled(True)
        if self.auto_saving.isChecked() and self.file_path:
            self.auto_save_timer.start()


    def _legacy_shape_moved(self):
        if self.annotation_editing.edit_open:
            return
        self.set_dirty()


    def save_dirty_annotations(self):
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            return
        if self.dirty and self.auto_saving.isChecked() and self.file_path:
            self._autosave_request = True
            try:
                self.save_file()
            finally:
                self._autosave_request = False


    def set_clean(self):
        self.auto_save_timer.stop()
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.create.setEnabled(True)


    def _project_review_recovery(self, result):
        for update in result.updates:
            if update.image_path == self.file_path:
                if update.snapshot is not None:
                    self.annotation_scene.project(
                        self._history_projection_request(
                            update.snapshot,
                            direction='recover-review',
                            preserve_selection=True,
                        )
                    )
                self.annotation_document = update.document
                self._sync_annotation_history_ui()


    def pop_label_group_menu(self, context, global_pos):
        kind, target = context
        menu = QMenu(self)
        if kind == 'instance':
            shape = target
            selected = tuple(self.canvas.selected_shapes)
            scoped = selected if shape in selected else (shape,)
            menu.addAction(
                tr('labelMenu.edit'),
                lambda: self.edit_shape_label(shape),
            )
            all_visible = all(self.canvas.isVisible(item) for item in scoped)
            menu.addAction(
                (tr('labelMenu.hideSelected') if len(scoped) > 1 else tr('labelMenu.hideOne'))
                if all_visible
                else (tr('labelMenu.showSelected') if len(scoped) > 1 else tr('labelMenu.showOne')),
                lambda: self.label_visibility_requested(
                    scoped,
                    not all_visible,
                ),
            )
            menu.addSeparator()
            menu.addAction(
                tr('labelMenu.deleteSelected', count=len(scoped))
                if len(scoped) > 1
                else tr('labelMenu.deleteOne'),
                lambda: self.delete_annotation_shapes(
                    scoped,
                    'Delete selected boxes',
                ),
            )
        else:
            label = target
            shapes = tuple(
                shape for shape in self.canvas.shapes
                if shape.label == label
            )
            if not shapes:
                return
            menu.addAction(
                tr('labelMenu.selectGroup', count=len(shapes)),
                lambda: self.canvas.set_selected_shapes(
                    shapes,
                    active_shape=shapes[0] if len(shapes) == 1 else None,
                ),
            )
            menu.addAction(
                tr('labelMenu.renameGroup'),
                lambda: self.edit_label_group(label),
            )
            all_visible = all(self.canvas.isVisible(shape) for shape in shapes)
            menu.addAction(
                tr('labelMenu.hideGroup') if all_visible else tr('labelMenu.showGroup'),
                lambda: self.label_visibility_requested(
                    shapes,
                    not all_visible,
                ),
            )
            menu.addAction(
                tr('labelMenu.isolateGroup'),
                lambda: self.isolate_label_group(label),
            )
            menu.addAction(tr('labelMenu.showAllGroups'), lambda: self.toggle_polygons(True))
            menu.addSeparator()
            menu.addAction(
                tr('labelMenu.deleteGroup', count=len(shapes)),
                lambda: self.delete_annotation_shapes(
                    shapes,
                    'Delete label group: %s' % label,
                ),
            )
        menu.exec_(global_pos)


    def pop_label_list_menu(self, point):
        # Compatibility entry point for extensions using the historical name.
        target = self.label_list.target_at(point)
        if target is not None:
            self.pop_label_group_menu(
                ('instance', target)
                if target in self.canvas.shapes
                else ('group', target),
                self.label_list.viewport().mapToGlobal(point),
            )


    def isolate_label_group(self, label):
        for shape in self.canvas.shapes:
            visible = shape.label == label
            self.canvas.set_shape_visible(shape, visible)
            self.label_list.set_shape_visible(shape, visible)


    def delete_annotation_shapes(self, shapes, description='Delete boxes'):
        requested = set(shapes)
        targets = tuple(
            shape for shape in self.canvas.shapes
            if shape in requested
        )
        if not targets:
            return tuple()

        def delete_shapes():
            removed = self.canvas.delete_shapes(targets)
            for shape in removed:
                self.remove_label(shape)
            return tuple(removed)

        removed = self._perform_annotation_edit(
            description,
            delete_shapes,
            affected=lambda result: result,
        )
        if removed:
            self.status(
                tr('status.deletedAnnotations', count=len(removed))
            )
            if self.no_shapes():
                for action in self.actions.onShapesPresent:
                    action.setEnabled(False)
        return removed


    def file_annotation_state(self, image_path):
        status = self.annotation_workspace.entry(image_path).status
        return 'annotated' if status.has_annotations else 'unannotated'


    def file_review_state(self, image_path):
        status = self.annotation_workspace.entry(image_path).status
        if status.questioned:
            return 'questioned'
        if status.verified:
            return 'verified'
        return 'unreviewed'


    def file_workspace_state(self, image_path):
        """Return all annotation-derived row state with one workspace query."""
        entry = self.annotation_workspace.entry(image_path)
        choices = self.annotation_workspace.document_choices(image_path)
        status = entry.status
        review = (
            'questioned' if status.questioned
            else 'verified' if status.verified
            else 'unreviewed'
        )
        return (
            'annotated' if status.has_annotations else 'unannotated',
            review,
            self.file_persistence_flags(image_path, choices=choices),
        )


    def set_selected_review_state(self, state, _checked=False):
        paths = self.selected_file_paths()
        if not paths:
            return
        self._set_review_state(paths, state, confirm_multiple=True)


    def set_current_review_state(self, state):
        if not self.file_path:
            return
        self._set_review_state(
            (self.file_path,), state, confirm_multiple=False
        )


    def _set_review_state(self, paths, state, confirm_multiple=False):
        paths = tuple(paths)
        if confirm_multiple and len(paths) > 1:
            title = {
                'verified': tr('fileMenu.markVerified'),
                'questioned': tr('fileMenu.markQuestioned'),
                'unreviewed': tr('fileMenu.clearReview'),
            }[state]
            answer = localized_question(
                self,
                title,
                tr('review.confirm', count=len(paths), action=title),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self._cancel_annotation_edit_for_navigation()

        result = self.review_state_transaction.apply(
            paths,
            state,
            self.annotation_format,
        )
        for update in result.updates:
            if update.image_path == self.file_path:
                if update.snapshot is not None:
                    self.annotation_editing.select_image(update.image_path)
                    self.annotation_scene.project(
                        self._history_projection_request(
                            update.snapshot,
                            direction='batch-review',
                            preserve_selection=True,
                        )
                    )
                self.annotation_document = update.document
                self.canvas.verified = bool(
                    update.document and update.document.verified
                )
                self.canvas.questioned = bool(
                    update.document and update.document.questioned
                )
                self.review_control.set_state(state)
        if len(paths) == 1:
            self.update_file_list_item_status(paths[0])
        else:
            self.refresh_file_list_statuses()
        self.refresh_candidate_labels()
        if result.recovery_records:
            self.file_operations.record_review(result.recovery_records)
        if result.failures:
            self.show_file_operation_failures(
                tr('review.partialFailure'),
                result.failures,
            )
        else:
            self.status(tr('status.reviewUpdated', count=len(paths)))


    def annotation_document_for_path(self, image_path):
        if image_path == self.file_path:
            document = document_from_shapes(
                image_path=self.file_path,
                image_data=self.image_data,
                shapes=self.canvas.shapes,
                class_names=self.label_hist,
                verified=self.canvas.verified,
                questioned=self.canvas.questioned,
            )
            if self.annotation_document is not None:
                document.create_ml_record_name = (
                    self.annotation_document.create_ml_record_name
                )
            return document
        image_data = read(image_path, None)
        loaded = self.annotation_workspace.load_for_image(
            image_path,
            image_data,
        )
        if loaded is not None:
            return loaded.document
        return AnnotationDocument(
            image_path=image_path,
            image_data=image_data,
            boxes=(),
            class_names=tuple(self.label_hist),
        )


    def save_current_annotations_directly(self):
        if self.file_path is None:
            return True
        try:
            saved = self.save_labels(
                self.annotation_workspace.entry(
                    self.file_path
                ).path_for(self.annotation_format)
            )
            if saved is None:
                return False
            self.annotation_document = saved.document
            self.update_file_list_item_status(self.file_path)
            return True
        except Exception as error:
            self.error_message(
                tr('error.saveLabelData'),
                u'<p>%s</p>' % error,
            )
            return False


    def edit_label(self):
        if not self.canvas.editing():
            return
        self.edit_shape_label(self.current_item())


    def edit_shape_label(self, shape):
        if shape is None or shape not in self.canvas.shapes:
            return
        old_label = shape.label
        label = self.candidate_label_dialog.choose(old_label)
        if label is None or label == old_label:
            return

        def apply_label():
            shape.label = label
            shape.line_color = generate_color_by_text(label)

        self._perform_annotation_edit(
            'Change label: %s \u2192 %s' % (old_label, label),
            apply_label,
            affected=(shape,),
            old_label=old_label,
            new_label=label,
        )
        self.label_list.refresh_shape(shape)
        self.shape_selection_changed(True)


    def edit_label_group(self, old_label):
        shapes = tuple(
            shape for shape in self.canvas.shapes
            if shape.label == old_label
        )
        if not shapes:
            return
        label = self.candidate_label_dialog.choose(old_label)
        if label is None or label == old_label:
            return

        def apply_label():
            color = generate_color_by_text(label)
            for shape in shapes:
                shape.label = label
                shape.line_color = QColor(color)

        self._perform_annotation_edit(
            'Rename label group: %s \u2192 %s' % (old_label, label),
            apply_label,
            affected=shapes,
            old_label=old_label,
            new_label=label,
        )
        self.label_list.set_scene(
            self.canvas.shapes,
            visible_shapes=(
                shape for shape in self.canvas.shapes
                if self.canvas.isVisible(shape)
            ),
        )
        self.shape_selection_changed(True)


    def button_state(self, item=None):
        """ Function to handle difficult examples
        Update on each object """
        selection = self.canvas.selection_snapshot
        if (
            not self.canvas.editing()
            or not selection.capabilities.can_edit_single
        ):
            return

        shape = selection.active
        difficult = self.diffc_button.isChecked()
        if difficult != shape.difficult:
            self._perform_annotation_edit(
                'Change difficult flag',
                lambda: setattr(shape, 'difficult', difficult),
                affected=(shape,),
            )


    def shape_selection_changed(self, selected=False):
        selection = self.canvas.selection_snapshot
        self.label_list.project_selection(
            selection.selected,
            selection.active,
        )
        self.update_selection_actions(selection)


    def canvas_hover_shape_changed(self, shape):
        """Project Canvas pointer hover onto its group and instance."""
        self.label_list.project_canvas_hover(shape)


    def label_hover_changed(self, shapes):
        """Project grouped row or instance hover onto visible Canvas boxes."""
        shapes = tuple(shapes)
        if shapes:
            self.canvas.un_highlight()
        self.canvas.set_external_hover_shapes(shapes)


    def selected_label_shapes(self):
        return list(self.label_list.selected_shapes())


    def label_selection_requested(self, shapes, active_shape):
        self.canvas.set_selected_shapes(
            shapes,
            active_shape=active_shape,
        )


    def label_visibility_requested(self, shapes, visible):
        for shape in shapes:
            self.canvas.set_shape_visible(shape, visible)
            self.label_list.set_shape_visible(shape, visible)


    def update_selection_actions(self, selection=None):
        if selection is None:
            selection = self.canvas.selection_snapshot
        capabilities = selection.capabilities

        self.actions.delete.setEnabled(capabilities.can_bulk)
        self.actions.copy.setEnabled(capabilities.can_bulk)
        self.actions.copyAnnotations.setEnabled(capabilities.can_bulk)
        self.actions.edit.setEnabled(capabilities.can_edit_single)
        self.actions.shapeLineColor.setEnabled(
            capabilities.can_edit_single
        )
        self.actions.shapeFillColor.setEnabled(
            capabilities.can_edit_single
        )
        self.diffc_button.setEnabled(capabilities.can_edit_single)

        blocker = QSignalBlocker(self.diffc_button)
        if capabilities.can_edit_single:
            self.diffc_button.setChecked(
                selection.active.difficult
            )
        else:
            self.diffc_button.setChecked(False)
        del blocker


    def add_label(self, shape):
        shape.paint_label = self.display_label_option.isChecked()
        self.label_list.add_shape(
            shape,
            visible=self.canvas.isVisible(shape),
        )
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)


    def remove_label(self, shape):
        if shape is None:
            return
        self.label_list.remove_shape(shape)


    def shape_from_annotation(self, annotation_shape):
        label, points, line_color, fill_color, difficult = annotation_shape
        shape = Shape(label=label)
        for x, y in points:
            # Ensure the labels are within the bounds of the image. If not, fix them.
            x, y, snapped = self.canvas.snap_point_to_canvas(x, y)
            shape.add_point(QPointF(x, y))
        shape.difficult = difficult
        shape.close()

        if line_color:
            shape.line_color = QColor(*line_color)
        else:
            shape.line_color = generate_color_by_text(label)

        if fill_color:
            shape.fill_color = QColor(*fill_color)
        else:
            shape.fill_color = generate_color_by_text(label)
        return shape


    def load_labels(self, shapes):
        s = []
        for annotation_shape in shapes:
            shape = self.shape_from_annotation(annotation_shape)
            s.append(shape)
            self.add_label(shape)
        self.update_combo_box()
        self.canvas.load_shapes(s)


    def load_annotation_document(self, document):
        shapes, snapped = shapes_from_document(
            document,
            self.canvas.snap_point_to_canvas,
            generate_color_by_text,
        )
        for shape in shapes:
            self.add_label(shape)
        self.update_combo_box()
        self.canvas.load_shapes(shapes)
        self.annotation_document = document
        self.canvas.verified = document.verified
        self.canvas.questioned = document.questioned
        if hasattr(self, 'review_control'):
            self.review_control.set_state(
                'questioned' if document.questioned
                else 'verified' if document.verified
                else 'unreviewed'
            )


    def update_combo_box(self):
        # Kept as a compatibility seam for legacy call sites. The old
        # visibility combobox was replaced by the side-effect-free group
        # filter, and the grouped list updates itself from scene mutations.
        self.label_list.viewport().update()


    def save_labels(self, annotation_file_path):
        annotation_file_path = ustr(annotation_file_path)
        if self.annotation_editing.view is None:
            return None
        outcome = self.annotation_persistence.save(
            self.file_path,
            self.annotation_format,
            target=annotation_file_path,
        )
        if not outcome.ok:
            error = outcome.failure.error
            if isinstance(error, AnnotationStorageConflict):
                return self._handle_annotation_storage_conflict(error)
            self.error_message(
                tr('error.saveLabelData'), u'<b>%s</b>' % error
            )
            return None
        saved = outcome.saved_by_image[self.file_path]
        self.annotation_document = saved.document
        if saved.document is not None:
            print(
                'Image:{0} -> Annotation:{1}'.format(
                    self.file_path,
                    saved.annotation_path,
                )
            )
        self._sync_annotation_history_ui()
        return saved


    def _handle_annotation_storage_conflict(self, error):
        conflict_resources = tuple(
            self._resource_key(path)
            for path, _expected, _actual in error.mismatches
        )
        self.auto_save_timer.stop()
        self.refresh_file_list_statuses()
        if self._autosave_request:
            self.status(
                tr('conflict.autosavePaused'),
                10000,
            )
            return None

        box = QMessageBox(self)
        box.setWindowTitle(tr('conflict.title'))
        box.setIcon(QMessageBox.Warning)
        box.setText(
            tr('conflict.changed')
        )
        box.setInformativeText(
            tr('conflict.options')
        )
        load_button = box.addButton(
            tr('conflict.loadExternal'),
            QMessageBox.DestructiveRole,
        )
        overwrite_button = box.addButton(
            tr('conflict.overwriteExternal'),
            QMessageBox.AcceptRole,
        )
        box.addButton(QMessageBox.Cancel)
        localize_message_box_buttons(box)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is load_button:
            for resource in conflict_resources:
                conflict = self.annotation_persistence.conflicts.get(resource)
                if (
                    conflict is not None
                    and not self._load_external_resource_conflict(
                        conflict
                    )
                ):
                    return None
            return None
        if clicked is overwrite_button:
            current_saved = None
            for resource in conflict_resources:
                conflict = self.annotation_persistence.conflicts.get(resource)
                if conflict is None:
                    continue
                result = self._overwrite_resource_conflict(conflict)
                if not result:
                    return None
                if getattr(result, 'annotation_path', None):
                    current_saved = result
            return current_saved
        return None


    def combo_selection_changed(self, index):
        return


    def label_selection_changed(self):
        self.label_selection_requested(
            self.label_list.selected_shapes(),
            self.label_list.active_shape(),
        )


    def label_item_changed(self, item):
        return


    def new_shape(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        if not self.use_default_label_checkbox.isChecked() or not self.default_label_text_line.text():
            # Sync single class mode from PR#106
            if self.single_class_mode.isChecked() and self.lastLabel:
                text = self.lastLabel
            else:
                text = self.candidate_label_dialog.choose(
                    text=self.prev_label_text
                )
                self.lastLabel = text
        else:
            text = self.default_label_text_line.text()

        # Add Chris
        self.diffc_button.setChecked(False)
        if text is not None:
            self.prev_label_text = text
            generate_color = generate_color_by_text(text)
            shape = self.canvas.set_last_label(text, generate_color, generate_color)
            self.add_label(shape)
            self.annotation_editing.clear_pending()
            self.annotation_scene.identities.assign(shape)
            self.annotation_editing.commit_edit(
                affected_ids=(shape.session_id,)
            )
            self._after_annotation_edit()
            self.toggle_drawing_sensitive(False)

            if text not in self.label_hist:
                self.label_hist.append(text)
        else:
            self.canvas.reset_all_lines()
            self.annotation_editing.clear_pending()
            self.annotation_editing.cancel_edit(restore=False)
            self._sync_annotation_history_ui()
            self.set_edit_mode()


    def annotation_path_for_image(self, image_path):
        return self.annotation_workspace.entry(image_path).path_for(
            AnnotationFormat.PASCAL_VOC
        )


    def annotation_paths_for_image(self, image_path):
        return list(self.annotation_workspace.entry(image_path).paths)


    def file_persistence_flags(self, image_path, choices=None):
        flags = []
        if self.annotation_editing.has_image(image_path):
            view = self.annotation_editing.view_image(
                image_path, touch=False
            )
            if view.dirty:
                flags.append('dirty')
        if self.annotation_persistence.has_conflict(image_path):
            flags.append('conflict')
        if (
            len(
                choices
                if choices is not None
                else self.annotation_workspace.document_choices(image_path)
            ) > 1
            and not self.annotation_workspace.active_document_path(
                image_path
            )
        ):
            flags.append('ambiguous')
        if self.annotation_editing.is_degraded(image_path):
            flags.append('degraded')
        return tuple(flags)


    def refresh_candidate_labels(self):
        candidate_labels = list(
            self.annotation_workspace.candidate_labels
        )
        if candidate_labels == self.candidate_labels:
            return False

        self.candidate_labels[:] = candidate_labels
        self.candidate_label_dialog.set_candidate_labels(
            self.candidate_labels
        )
        return True


    def load_candidate_labels_from_dir(self, dir_path):
        candidate_labels = self.annotation_workspace.scan(dir_path)
        for label in candidate_labels:
            if label in self.label_hist:
                continue
            self.label_hist.append(label)

        self.refresh_candidate_labels()
        return len(candidate_labels)


    def verify_image(self, _value=False):
        self.toggle_image_status('toggle_verified')


    def question_image(self, _value=False):
        self.toggle_image_status('toggle_questioned')


    def toggle_image_status(self, toggle_method):
        if self.file_path is None:
            return
        def toggle():
            document = document_from_shapes(
                image_path=self.file_path,
                image_data=self.image_data,
                shapes=self.canvas.shapes,
                class_names=self.label_hist,
                verified=self.canvas.verified,
                questioned=self.canvas.questioned,
            )
            getattr(document, toggle_method)()
            self.canvas.verified = document.verified
            self.canvas.questioned = document.questioned
            return document
        document = self._perform_annotation_edit(
            (
                'Toggle verified'
                if toggle_method == 'toggle_verified'
                else 'Toggle questioned'
            ),
            toggle,
            affected=(),
        )
        try:
            saved = self.save_labels(
                self.annotation_workspace.entry(
                    self.file_path
                ).path_for(self.annotation_format)
            )
            if saved is None:
                return
        except Exception as error:
            self.error_message(
                tr('error.saveLabelData'),
                u'<p>%s</p>' % error,
            )
            return
        self.annotation_document = saved.document
        document = saved.document
        self.review_control.set_state(
            'questioned' if document and document.questioned
            else 'verified' if document and document.verified
            else 'unreviewed'
        )
        self.paint_canvas()
        self.update_file_list_item_status(self.file_path)


    def load_predefined_classes(self, predef_classes_file):
        if os.path.exists(predef_classes_file) is True:
            with open(predef_classes_file, 'r', encoding='utf8') as f:
                for line in f:
                    line = line.strip()
                    if self.label_hist is None:
                        self.label_hist = [line]
                    else:
                        self.label_hist.append(line)


    def load_annotation_by_filename(self, annotation_path):
        if self.file_path is None:
            return False
        if not os.path.isfile(annotation_path):
            return False
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self._cancel_annotation_edit_for_navigation()

        try:
            loaded = self.annotation_workspace.load(
                annotation_path,
                self.file_path,
                self.image_data,
            )
        except AnnotationDocumentError as error:
            self.error_message(
                tr('open.annotationTitle'),
                u'<b>%s</b>' % error,
            )
            return False

        self.clear_current_labels()
        self.set_format(document_format_name(loaded.annotation_format))
        self.load_annotation_document(loaded.document)
        if self.annotation_editing.view is not None:
            self.annotation_editing.set_target(
                self.file_path,
                loaded.annotation_path,
            )
            self._rebase_current_history(loaded.annotation_path)
        return True


    def format_shape_for_clipboard(self, shape):
        points = [(p.x(), p.y()) for p in shape.points]
        line_color = shape.line_color.getRgb() if shape.line_color else None
        fill_color = shape.fill_color.getRgb() if shape.fill_color else None
        return shape.label, points, line_color, fill_color, shape.difficult


    def clear_current_labels(self):
        self.label_list.clear()
        self.canvas.load_shapes([])


    def copy_current_bounding_boxes(self):
        selected_shapes = list(self.canvas.selected_shapes)
        if not selected_shapes:
            self.status(tr('status.noSelectedLabels'))
            return

        self.annotation_clipboard = [
            self.format_shape_for_clipboard(shape)
            for shape in selected_shapes
        ]
        self.status(tr('status.copiedLabels', count=len(self.annotation_clipboard)))


    def paste_copied_bounding_boxes(self):
        if not self.annotation_clipboard:
            self.status(tr('status.noCopiedLabels'))
            return
        if self.file_path is None:
            return

        def paste():
            pasted = [
                self.shape_from_annotation(annotation_shape)
                for annotation_shape in self.annotation_clipboard
            ]
            self.canvas.shapes.extend(pasted)
            self.canvas.set_selected_shapes(
                pasted,
                active_shape=pasted[-1],
            )
            return pasted
        pasted_shapes = self._perform_annotation_edit(
            'Paste boxes',
            paste,
            affected=lambda pasted: pasted,
        )
        for shape in pasted_shapes:
            self.add_label(shape)
        self.shape_selection_changed(True)

        self.canvas.setFocus(True)
        self.status(tr('status.pastedLabels', count=len(pasted_shapes)))


    def copy_previous_bounding_boxes(self):
        current_index = self.m_img_list.index(self.file_path)
        if current_index - 1 < 0:
            return
        prev_file_path = self.m_img_list[current_index - 1]
        try:
            source = self.annotation_editing.view_image(
                prev_file_path
            ).snapshot
            source_boxes = source.boxes
        except UnknownImageHistory:
            previous_data = read(prev_file_path, None)
            loaded = self.annotation_workspace.load_for_image(
                prev_file_path,
                previous_data,
            )
            source_boxes = ()
            if loaded is not None:
                source_shapes, _snapped = shapes_from_document(
                    loaded.document,
                    self.canvas.snap_point_to_canvas,
                    generate_color_by_text,
                )
                source_boxes = tuple(
                    (
                        shape.label,
                        tuple((p.x(), p.y()) for p in shape.points),
                        shape.line_color.getRgb(),
                        shape.fill_color.getRgb(),
                        shape.difficult,
                    )
                    for shape in source_shapes
                )

        old_shapes = tuple(self.canvas.shapes)
        def replace_boxes():
            copied = []
            for box in source_boxes:
                if hasattr(box, 'session_id'):
                    annotation_shape = (
                        box.label,
                        box.points,
                        box.line_rgba,
                        box.fill_rgba,
                        box.difficult,
                    )
                else:
                    annotation_shape = box
                shape = self.shape_from_annotation(annotation_shape)
                self.annotation_scene.identities.assign(shape)
                copied.append(shape)
            self.label_list.clear()
            self.canvas.load_shapes(copied)
            for shape in copied:
                self.add_label(shape)
            return copied

        copied = self._perform_annotation_edit(
            'Copy previous boxes',
            replace_boxes,
            affected=lambda new: old_shapes + tuple(new),
        )
        self.canvas.set_selected_shapes(
            copied,
            active_shape=copied[-1] if copied else None,
        )
        self.shape_selection_changed(bool(copied))
        self.save_file()

