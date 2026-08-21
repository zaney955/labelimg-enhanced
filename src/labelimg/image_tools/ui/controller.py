"""ImageToolsActionsMixin extracted from the top-level workbench window."""

#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os.path


from PyQt5.QtCore import QSignalBlocker, QThread, Qt
from PyQt5.QtGui import QImage, QImageReader, QPixmap
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox, QProgressDialog

import labelimg.ui.generated_resources  # noqa: F401 - registers Qt resources
from labelimg.localization.runtime import question as localized_question, tr, warning as localized_warning
from labelimg.annotations import fingerprint_path
from labelimg.image_tools.application.recovery import ImageProcessingOperation
from labelimg.image_tools.application.session import AdjustmentChange, CropChange, GeometryTransformChange, ImageProcessingProjectionKind, PreparedPixelChange
from labelimg.workbench.support import read_image as read


class ImageToolsActionsMixin:
    def update_image_menu(self):
        image_available = (
            bool(self.file_path)
            and not self._image_processing_projection_blocked
        )
        quick_enabled = image_available and not self._crop_active
        self.actions.removeColoredFrames.setEnabled(quick_enabled)
        for quick_action in (
            self.actions.rotateClockwise,
            self.actions.rotateCounterclockwise,
            self.actions.rotate180,
            self.actions.flipHorizontal,
            self.actions.flipVertical,
        ):
            quick_action.setEnabled(quick_enabled)
        self.actions.transformImage.setEnabled(quick_enabled)
        self.actions.adjustImage.setEnabled(quick_enabled)
        self.actions.checkImageQuality.setEnabled(image_available)
        self.actions.cropImage.setEnabled(image_available)
        self.actions.undoImageProcessing.setEnabled(
            self._latest_image_processing_recovery() is not None
            and (
                not self._crop_active
                or self._image_processing_projection_blocked
            )
        )


    def _project_image_processing(self, request):
        """Project one committed image-processing result into Qt state."""
        if request.kind is ImageProcessingProjectionKind.PIXEL_COMMIT:
            self._invalidate_image_quality(request.paths)
            self._refresh_current_image_pixels(request.paths)
            self.actions.undoImageProcessing.setEnabled(True)
            return None

        if (
            request.kind
            is ImageProcessingProjectionKind.CURRENT_GEOMETRY_COMMIT
        ):
            target = request.current_target
            old_scroll = {
                orientation: bar.value()
                for orientation, bar in self.scroll_bars.items()
            }
            zoom = self.zoom_widget.value()
            self.image_data = target.prepared.image_replacement.content
            self.image = QImage.fromData(self.image_data)
            self.canvas.replace_pixmap(QPixmap.fromImage(self.image))
            self.annotation_scene.project(
                self._history_projection_request(
                    request.snapshot,
                    direction=request.direction,
                    preserve_selection=True,
                )
            )
            if target.annotation_preparation is not None:
                self.annotation_document = (
                    target.annotation_preparation.document
                )
            self.zoom_widget.setValue(zoom)
            self.paint_canvas()
            if request.direction == 'crop':
                QApplication.processEvents()
                scale = 0.01 * zoom
                region = target.prepared.region
                self.scroll_bars[Qt.Horizontal].setValue(
                    max(0, round(
                        old_scroll[Qt.Horizontal] - region.x * scale
                    ))
                )
                self.scroll_bars[Qt.Vertical].setValue(
                    max(0, round(
                        old_scroll[Qt.Vertical] - region.y * scale
                    ))
                )
            self._invalidate_image_quality(request.paths)

            def finalize_current_geometry():
                if request.direction == 'crop':
                    self._finish_crop_mode()
                self.rescan_annotation_workspace()
                self.update_file_list_item_status(self.file_path)
                self.actions.undoImageProcessing.setEnabled(True)
                self._sync_annotation_history_ui()

            return finalize_current_geometry

        if (
            request.kind
            is ImageProcessingProjectionKind.GEOMETRY_BATCH_COMMIT
        ):
            self._invalidate_image_quality(request.paths)
            self.rescan_annotation_workspace()
            current_key = (
                os.path.normcase(os.path.abspath(self.file_path))
                if self.file_path
                else None
            )
            changed = {
                os.path.normcase(os.path.abspath(path))
                for path in request.paths
            }
            if current_key in changed:
                if not self.load_file(self.file_path):
                    raise RuntimeError(
                        "the transformed current image could not reload"
                    )
            else:
                self.refresh_file_list_statuses()
            self.actions.undoImageProcessing.setEnabled(True)
            return None

        if request.kind is ImageProcessingProjectionKind.RECOVERY:
            outcome = request.outcome
            selected_before = tuple(self.selected_file_paths())
            image_extensions = {
                '.%s' % value.data().decode('ascii').lower()
                for value in QImageReader.supportedImageFormats()
            }
            restored_images = tuple(
                path
                for path in request.paths
                if os.path.splitext(path)[1].lower() in image_extensions
            )
            if self.dir_name and os.path.isdir(self.dir_name):
                self.populate_file_list(self.scan_all_images(self.dir_name))
                selected_after = set(selected_before)
                selected_after.update(restored_images)
                for row in range(self.file_list_widget.count()):
                    item = self.file_list_widget.item(row)
                    if item.data(Qt.UserRole) in selected_after:
                        item.setSelected(True)
            geometry_images = tuple(outcome.reload_images)
            if geometry_images:
                self.annotation_persistence.propagate_resource_fingerprints(
                    tuple(
                        (path, fingerprint_path(path))
                        for path in outcome.restored_paths
                    )
                )
                self.rescan_annotation_workspace()
            self._invalidate_image_quality(restored_images)
            self.refresh_file_list_statuses()
            current_key = (
                os.path.normcase(os.path.abspath(self.file_path))
                if self.file_path
                else None
            )
            geometry_keys = {
                os.path.normcase(os.path.abspath(path))
                for path in geometry_images
            }
            if current_key in geometry_keys:
                self.load_file(self.file_path)
            else:
                self._refresh_current_image_pixels(restored_images)
            if self.file_path is None and restored_images:
                self.load_file(restored_images[0])
            self.actions.undoImageProcessing.setEnabled(
                self._latest_image_processing_recovery() is not None
            )
            if self._image_processing_projection_blocked:
                self._image_processing_projection_blocked = False
                has_image = bool(self.file_path)
                self.canvas.setEnabled(has_image)
                self.toggle_actions(has_image)
                if has_image:
                    self.set_edit_mode()
                self.update_file_navigation_actions()
                self.update_image_menu()
                self._sync_annotation_history_ui()
            return None

        if request.kind is ImageProcessingProjectionKind.PROJECTION_FAILED:
            self._image_processing_projection_blocked = True
            self.canvas.setEnabled(False)
            for name in (
                'create',
                'delete',
                'copy',
                'pasteAnnotations',
                'undoAnnotation',
                'redoAnnotation',
                'save',
                'saveAs',
                'openPrev',
                'openNext',
                'cropImage',
                'transformImage',
                'adjustImage',
                'removeColoredFrames',
            ):
                action = getattr(self.actions, name, None)
                if action is not None:
                    action.setEnabled(False)
            self.update_image_menu()
            return None

        raise ValueError(
            "unsupported image-processing projection: %s" % request.kind
        )


    def open_transform_image(self, _checked=False, preselected=None):
        if not self.file_path or self._crop_active:
            return False
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self.status(tr('imageTools.pendingAnnotation'))
            return False
        if self.annotation_persistence.conflicts:
            self.status(tr('geometry.conflict'))
            return False
        current_path = self.file_path
        if self.annotation_editing.dirty_views():
            if not self.may_continue():
                return False
            if not self.load_file(current_path):
                return False

        from labelimg.image_tools.ui.geometry_dialog import (
            GeometryTransformDialog,
        )
        from labelimg.image_tools.application.geometry_transform import GeometryOperation

        dialog = GeometryTransformDialog(
            self.file_path,
            tuple(self.selected_file_paths()),
            preselected=(
                GeometryOperation.ROTATE_CLOCKWISE
                if preselected is None
                else GeometryOperation(preselected)
            ),
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted or dialog.request is None:
            return False
        request = dialog.request
        if (
            request.operation is GeometryOperation.RESIZE
            and request.resize_percent > 100
            and QMessageBox.question(
                self,
                tr('geometry.workspace.title'),
                tr(
                    'geometry.enlargeWarning',
                    percent=request.resize_percent,
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes
        ):
            return False
        if len(request.paths) == 1 and request.paths[0] == self.file_path:
            output_size = None
            if request.operation is GeometryOperation.RESIZE:
                scale = request.resize_percent / 100.0
                output_size = (
                    max(1, round(self.image.width() * scale)),
                    max(1, round(self.image.height() * scale)),
                )
            return self.quick_transform_current_image(
                request.operation.value,
                output_size=output_size,
            )
        try:
            return self._apply_geometry_transform_batch(request)
        except Exception as error:
            localized_warning(
                self,
                tr('geometry.failedTitle'),
                tr('geometry.failed', error=error),
            )
            return False


    def _apply_geometry_transform_batch(self, request):
        plan = self.image_processing.prepare(GeometryTransformChange(
            paths=tuple(request.paths),
            operation=request.operation,
            current_path=self.file_path,
            resize_percent=(
                request.resize_percent
                if request.operation.value == 'resize'
                else None
            ),
        ))
        self.image_processing.commit(plan)
        self.status(tr('imageTools.completed', count=len(request.paths)))
        return True


    def open_adjust_image(self, _checked=False):
        if not self.file_path or self._crop_active:
            return False
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self.status(tr('imageTools.pendingAnnotation'))
            return False
        from labelimg.image_tools.ui.adjustment_dialog import ImageAdjustmentDialog

        dialog = ImageAdjustmentDialog(
            self.file_path,
            tuple(self.selected_file_paths()),
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted or dialog.request is None:
            return False
        try:
            plan = self.image_processing.prepare(AdjustmentChange(
                paths=tuple(dialog.request.paths),
                options=dialog.request.options,
            ))
            if plan is None:
                return False
            self.image_processing.commit(plan)
        except Exception as error:
            localized_warning(
                self,
                tr('adjustment.failedTitle'),
                tr('adjustment.failed', error=error),
            )
            return False
        self.status(
            tr('imageTools.completed', count=len(plan.target_paths))
        )
        return True


    def open_image_quality_check(self, _checked=False):
        if not self.file_path:
            return False
        from labelimg.image_tools.ui.quality_panel import ImageQualityDialog
        dialog = ImageQualityDialog(
            self.file_path,
            tuple(self.selected_file_paths()),
            tuple(self.m_img_list),
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted or dialog.request is None:
            return False
        self._image_quality_last_request = dialog.request
        return self._run_image_quality_request(dialog.request)


    def _run_image_quality_request(self, request, *, force=False):
        if (
            self._image_quality_thread is not None
            and self._image_quality_thread.isRunning()
        ):
            self.status(tr('quality.busy'))
            return False
        try:
            cached = (
                tuple(
                    self.image_quality_cache.get(path, request.policy)
                    for path in request.paths
                )
                if not force
                else ()
            )
            if cached and all(result is not None for result in cached):
                results = {result.path: result for result in cached}
            else:
                return self._start_image_quality_scan(request)
        except Exception as error:
            localized_warning(
                self,
                tr('quality.failedTitle'),
                tr('quality.failed', error=error),
            )
            return False
        self._apply_image_quality_results(request, results)
        return True


    def _start_image_quality_scan(self, request):
        from labelimg.image_tools.ui.quality_panel import ImageQualityWorker
        thread = QThread(self)
        worker = ImageQualityWorker(self.image_quality_scanner, request)
        worker.moveToThread(thread)
        progress = QProgressDialog(
            tr('quality.checking'),
            tr('common.cancel'),
            0,
            len(request.paths),
            self,
        )
        progress.setWindowTitle(tr('quality.dialogTitle'))
        progress.setWindowModality(Qt.NonModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(worker.cancel)
        worker.progressChanged.connect(
            lambda completed, total: (
                progress.setMaximum(total),
                progress.setValue(completed),
            )
        )
        worker.completed.connect(
            lambda results: self._complete_image_quality_scan(
                request, results
            )
        )
        worker.failed.connect(self._fail_image_quality_scan)
        worker.canceled.connect(self._cancel_image_quality_scan)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.canceled.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda: self._cleanup_image_quality_scan(thread)
        )
        self._image_quality_thread = thread
        self._image_quality_worker = worker
        self._image_quality_progress = progress
        progress.show()
        thread.start()
        return True


    def _complete_image_quality_scan(self, request, results):
        self.image_quality_cache.put_many(results.values())
        self._apply_image_quality_results(request, results)


    def _apply_image_quality_results(self, request, results):
        self.image_quality_results.update(results)
        for path in results:
            self.update_file_list_item_status(path, refresh_view=False)
        self.apply_file_list_view(scroll_current=False)
        ordered = tuple(results[path] for path in request.paths)
        self.image_quality_panel.set_results(ordered)
        self.image_quality_dock.show()
        self.image_quality_dock.raise_()
        self.status(tr('quality.completed', count=len(ordered)))


    def _fail_image_quality_scan(self, error):
        localized_warning(
            self,
            tr('quality.failedTitle'),
            tr('quality.failed', error=error),
        )


    def _cancel_image_quality_scan(self):
        self.status(tr('quality.cancelled'))


    def _cleanup_image_quality_scan(self, thread):
        if thread is not self._image_quality_thread:
            return
        if self._image_quality_progress is not None:
            try:
                self._image_quality_progress.close()
                self._image_quality_progress.deleteLater()
            except RuntimeError:
                # Qt may auto-delete the progress dialog after the worker
                # finishes; cleanup remains idempotent in that race.
                pass
        self._image_quality_progress = None
        self._image_quality_worker = None
        self._image_quality_thread = None
        thread.deleteLater()


    def refresh_image_quality(self, _checked=False):
        if self._image_quality_last_request is None:
            return False
        return self._run_image_quality_request(
            self._image_quality_last_request,
            force=True,
        )


    def clear_image_quality_results(self, _checked=False):
        if self._image_quality_worker is not None:
            self._image_quality_worker.cancel()
        self.image_quality_cache.clear()
        affected = tuple(self.image_quality_results)
        self.image_quality_results.clear()
        self._image_quality_last_request = None
        self.image_quality_panel.clear()
        for path in affected:
            self.update_file_list_item_status(path, refresh_view=False)
        self.apply_file_list_view(scroll_current=False)
        return True


    def quick_transform_current_image(
        self,
        operation,
        _checked=False,
        *,
        output_size=None,
    ):
        if not self.file_path or self._crop_active:
            return False
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self.status(tr('imageTools.pendingAnnotation'))
            return False
        if self.annotation_persistence.conflicts:
            self.status(tr('geometry.conflict'))
            return False

        current_path = self.file_path
        if self.annotation_editing.dirty_views():
            if not self.may_continue():
                return False
            if not self.load_file(current_path):
                return False

        try:
            plan = self.image_processing.prepare(GeometryTransformChange(
                paths=(self.file_path,),
                operation=operation,
                current_path=self.file_path,
                output_size=output_size,
                preserve_current=True,
            ))
            self.image_processing.commit(plan)
        except Exception as error:
            localized_warning(
                self,
                tr('geometry.failedTitle'),
                tr('geometry.failed', error=error),
            )
            return False

        self.status(tr('geometry.completed'))
        self.update_image_menu()
        return True


    def enter_crop_mode(self, _checked=False):
        if self._crop_active:
            blocker = QSignalBlocker(self.actions.cropImage)
            self.actions.cropImage.setChecked(True)
            del blocker
            return True
        if not self.file_path:
            self.status(tr('imageTools.noImage'))
            return False
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self.status(tr('imageTools.pendingAnnotation'))
            return False

        current_path = self.file_path
        has_unsaved_annotations = bool(
            self.annotation_persistence.conflicts
            or self.annotation_editing.dirty_views()
        )
        if has_unsaved_annotations:
            if not self.may_continue():
                blocker = QSignalBlocker(self.actions.cropImage)
                self.actions.cropImage.setChecked(False)
                del blocker
                return False
            # Discard removes the history view; saving can also change the
            # serialized document. Reload once so crop always starts from the
            # committed image/annotation pair.
            if not self.load_file(current_path):
                return False

        self._crop_active = True
        self._crop_previous_canvas_mode = self.canvas.mode
        guarded = (
            self.actions.selectTool,
            self.actions.panTool,
            self.actions.create,
            self.actions.edit,
            self.actions.delete,
            self.actions.copy,
            self.actions.copyAnnotations,
            self.actions.pasteAnnotations,
            self.actions.copyPrevBounding,
            self.actions.shapeLineColor,
            self.actions.shapeFillColor,
            self.actions.toggleVisibility,
            self.actions.hideAll,
            self.actions.showAll,
            self.actions.undoAnnotation,
            self.actions.redoAnnotation,
            self.actions.removeColoredFrames,
        )
        self._crop_action_states = {
            action: action.isEnabled() for action in guarded
        }
        for action in guarded:
            action.setEnabled(False)
        blocker = QSignalBlocker(self.actions.cropImage)
        self.actions.cropImage.setChecked(True)
        del blocker
        image_size = (self.image.width(), self.image.height())
        self.crop_overlay.begin(image_size)
        self.crop_controls.begin(image_size)
        self.status(tr('crop.noRegion'))
        return True


    def cancel_crop(self):
        if not self._crop_active:
            return True
        self._finish_crop_mode()
        return True


    def apply_crop(self):
        if not self._crop_active:
            return False
        region = self.crop_overlay.region
        image_size = (self.image.width(), self.image.height())
        if region is None or region.is_full_image(image_size):
            self.status(tr('crop.noRegion'))
            return False

        try:
            plan = self.image_processing.prepare(CropChange(
                path=self.file_path,
                region=region,
            ))
            impact = plan.impact
            if impact.clipped_annotations or impact.removed_annotations:
                answer = localized_question(
                    self,
                    tr('crop.confirmTitle'),
                    tr(
                        'crop.confirmImpact',
                        clipped=impact.clipped_annotations,
                        removed=impact.removed_annotations,
                    ),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return False
            self.image_processing.commit(plan)
        except Exception as error:
            localized_warning(
                self,
                tr('crop.failedTitle'),
                tr('crop.failed', error=error),
            )
            self.crop_overlay.setFocus(Qt.OtherFocusReason)
            return False
        self.status(tr('crop.completed'))
        return True


    def _finish_crop_mode(self):
        self.crop_overlay.finish()
        self.crop_controls.finish()
        self._crop_active = False
        blocker = QSignalBlocker(self.actions.cropImage)
        self.actions.cropImage.setChecked(False)
        del blocker
        for action, enabled in self._crop_action_states.items():
            action.setEnabled(enabled)
        self._crop_action_states = {}
        self.set_edit_mode()
        self._crop_previous_canvas_mode = None
        self.canvas.setFocus(Qt.OtherFocusReason)
        self.update_image_menu()


    def _resolve_crop_before_leave(self):
        if not self._crop_active:
            return True
        region = self.crop_overlay.region
        if region is None or region.is_full_image(
            (self.image.width(), self.image.height())
        ):
            return self.cancel_crop()
        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Question)
        prompt.setWindowTitle(tr('crop.leaveTitle'))
        prompt.setText(tr('crop.leavePrompt'))
        apply_button = prompt.addButton(
            tr('crop.leaveApply'), QMessageBox.AcceptRole
        )
        discard_button = prompt.addButton(
            tr('crop.leaveDiscard'), QMessageBox.DestructiveRole
        )
        cancel_button = prompt.addButton(
            tr('common.cancel'), QMessageBox.RejectRole
        )
        prompt.setDefaultButton(cancel_button)
        prompt.exec_()
        clicked = prompt.clickedButton()
        if clicked is apply_button:
            return self.apply_crop()
        if clicked is discard_button:
            return self.cancel_crop()
        return False


    def open_remove_colored_frames(self, _checked=False):
        if self._crop_active:
            return False
        if not self.file_path:
            self.status(tr('imageTools.noImage'))
            return False
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self.status(tr('imageTools.pendingAnnotation'))
            return

        from labelimg.image_tools.ui.colored_frame_dialog import ImageToolsDialog

        def commit(replacements, *, target_count=None):
            plan = self.image_processing.prepare(PreparedPixelChange(
                tuple(replacements),
                target_count=target_count,
            ))
            return self.image_processing.commit(plan)

        dialog = ImageToolsDialog(
            self.file_path,
            tuple(self.selected_file_paths()),
            commit=commit,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted or dialog.outcome is None:
            return
        resources = tuple(dialog.outcome.file_result.resources)
        processed_paths = tuple(
            resource.original_path for resource in resources
        )
        self.status(tr('imageTools.completed', count=len(processed_paths)))


    def undo_last_image_processing(self, _checked=False):
        if (
            self._crop_active
            and not self._image_processing_projection_blocked
        ):
            return False
        entry = self._latest_image_processing_recovery()
        if entry is None:
            self.status(tr('imageTools.recovery.none'))
            self.actions.undoImageProcessing.setEnabled(False)
            return
        self._confirm_file_recovery(entry.entry_id)
        self.update_image_menu()


    def _latest_image_processing_recovery(self):
        return next(
            (
                entry
                for entry in self.image_processing.recovery_entries
                if entry.operation is ImageProcessingOperation.PROCESS
                and entry.recoverable
            ),
            None,
        )


    def _choose_image_recovery_paths(self, entry):
        resources = tuple(entry.payload)
        if len(resources) == 1:
            answer = localized_question(
                self,
                tr('imageTools.recovery.title'),
                tr('imageTools.recovery.confirm', count=1),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return None
            return (resources[0].original_path,)

        from labelimg.image_tools.ui.recovery_dialog import (
            ImageRecoverySelectionDialog,
        )

        selection = ImageRecoverySelectionDialog(resources, self)
        if selection.exec_() != QDialog.Accepted:
            return None
        return selection.selected_paths


    def _invalidate_image_quality(self, changed_paths):
        changed = tuple(os.path.abspath(os.fspath(path)) for path in changed_paths)
        for path in changed:
            self.image_quality_results.pop(path, None)
            self.update_file_list_item_status(path, refresh_view=False)
        if changed:
            self.apply_file_list_view(scroll_current=False)


    def _quality_result_for_path(self, image_path):
        image_path = os.path.abspath(os.fspath(image_path))
        return self.image_quality_results.get(image_path)


    def _refresh_current_image_pixels(self, changed_paths):
        if not self.file_path:
            return False
        changed = {
            os.path.normcase(os.path.abspath(path))
            for path in changed_paths
        }
        current = os.path.normcase(os.path.abspath(self.file_path))
        if current not in changed:
            return False

        image_data = read(self.file_path, None)
        image = (
            image_data
            if isinstance(image_data, QImage)
            else QImage.fromData(image_data)
        )
        if image.isNull():
            self.status(
                tr('status.errorReading', detail=self.file_path)
            )
            return False
        self.image_data = image_data
        self.image = image
        self.canvas.replace_pixmap(QPixmap.fromImage(image))
        self.paint_canvas()
        return True

