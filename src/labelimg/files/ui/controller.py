"""FileActionsMixin extracted from the top-level workbench window."""

#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os.path
import platform
import subprocess

from functools import cmp_to_key, partial

from PyQt5.QtCore import QFileInfo, QItemSelectionModel, QModelIndex, QSignalBlocker, Qt
from PyQt5.QtGui import QImageReader
from PyQt5.QtWidgets import QAbstractItemView, QAction, QApplication, QDialog, QInputDialog, QLineEdit, QMenu, QMessageBox, QProgressDialog

import labelimg.ui.generated_resources  # noqa: F401 - registers Qt resources
from labelimg.ui.actions import new_icon
from labelimg.localization.runtime import question as localized_question, tr, warning as localized_warning
from labelimg.annotations import AnnotationFormat
from labelimg.platform.text import native_text as ustr
from labelimg.files.ui.list_widget import BatchRenameDialog, CURRENT_IMAGE_ROLE, FILE_ANNOTATION_STATE_ROLE, FILE_PERSISTENCE_FLAGS_ROLE, FILE_QUALITY_FINDINGS_ROLE, FILE_REVIEW_STATE_ROLE, compare_relative_image_paths, validate_base_name, validate_rename_mapping
from labelimg.files.application.operations import FileOperationError
from labelimg.files.application.transaction import FileOperationBlocked


class FileActionsMixin:
    def update_file_menu(self):
        curr_file_path = self.file_path

        def exists(filename):
            return os.path.exists(filename)
        menu = self.menus.recentFiles
        menu.clear()
        files = [f for f in self.recent_files if f !=
                 curr_file_path and exists(f)]
        for i, f in enumerate(files):
            icon = new_icon('recent-file')
            action = QAction(
                icon, '&%d %s' % (i + 1, QFileInfo(f).fileName()), self)
            action.triggered.connect(partial(self.load_recent, f))
            menu.addAction(action)


    def selected_file_paths(self):
        selected = {
            item.data(Qt.UserRole)
            for item in self.file_list_widget.selectedItems()
        }
        return [
            image_path
            for image_path in self.m_img_list
            if image_path in selected
        ]


    def visible_file_paths(self):
        visible = {
            item.data(Qt.UserRole)
            for item in self.file_list_widget.visible_items()
        }
        return [
            image_path
            for image_path in self.m_img_list
            if image_path in visible
        ]


    def show_file_list_filter(self):
        self.file_list_controls.show_filter_panel()


    def apply_file_list_view(self, scroll_current=True):
        if not hasattr(self, 'file_list_controls'):
            return
        state = self.file_list_controls.state
        items = {
            self.file_list_widget.item(row).data(Qt.UserRole):
            self.file_list_widget.item(row)
            for row in range(self.file_list_widget.count())
        }
        paths = [path for path in items if path]
        annotation_states = {
            path: item.data(FILE_ANNOTATION_STATE_ROLE)
            for path, item in items.items()
        }
        review_states = {
            path: item.data(FILE_REVIEW_STATE_ROLE)
            for path, item in items.items()
        }
        persistence_flags = {
            path: tuple(
                item.data(FILE_PERSISTENCE_FLAGS_ROLE) or ()
            )
            for path, item in items.items()
        }
        quality_findings = {
            path: tuple(item.data(FILE_QUALITY_FINDINGS_ROLE) or ())
            for path, item in items.items()
        }
        projection = state.project(
            paths,
            self.dir_name,
            annotation_state_for=annotation_states.get,
            review_state_for=review_states.get,
            persistence_flags_for=persistence_flags.get,
            quality_findings_for=quality_findings.get,
        )
        ordered = projection.ordered_paths
        self._file_list_projection = projection
        visible_paths = set(projection.visible_paths)
        selected_paths = {
            item.data(Qt.UserRole)
            for item in self.file_list_widget.selectedItems()
        }
        focused_item = self.file_list_widget.currentItem()
        focused_path = (
            focused_item.data(Qt.UserRole)
            if focused_item is not None
            else None
        )
        blocker = QSignalBlocker(self.file_list_widget)
        if ordered != self.m_img_list:
            while self.file_list_widget.count():
                self.file_list_widget.takeItem(0)
            for path in ordered:
                self.file_list_widget.addItem(items[path])
        self.m_img_list = list(ordered)
        self.img_count = len(self.m_img_list)
        visible_count = 0
        current_item = None
        focused_item = None
        for row, path in enumerate(self.m_img_list):
            item = self.file_list_widget.item(row)
            matches = path in visible_paths
            item.setHidden(not matches)
            if matches:
                visible_count += 1
            item.setSelected(path in selected_paths)
            if path == self.file_path:
                current_item = item
            if path == focused_path and matches:
                focused_item = item
        if focused_item is not None:
            self.file_list_widget.selectionModel().setCurrentIndex(
                self.file_list_widget.indexFromItem(focused_item),
                QItemSelectionModel.NoUpdate,
            )
        else:
            self.file_list_widget.selectionModel().setCurrentIndex(
                QModelIndex(),
                QItemSelectionModel.NoUpdate,
            )
        self.file_list_widget._range_anchor_row = None
        del blocker
        if self.file_path in self.m_img_list:
            self.cur_img_idx = self.m_img_list.index(self.file_path)
        self.file_list_controls.set_workspace_available(
            bool(self.dir_name and self.img_count)
        )
        show_empty = bool(
            state.filter_active
            and self.img_count
            and visible_count == 0
        )
        self.file_list_stack.setCurrentWidget(
            self.file_list_empty_state
            if show_empty
            else self.file_list_widget
        )
        self.update_current_file_marker()
        if (
            scroll_current
            and current_item is not None
            and not current_item.isHidden()
        ):
            self.file_list_widget.scrollToItem(
                current_item,
                QAbstractItemView.EnsureVisible,
            )


    def update_file_navigation_actions(self):
        if not hasattr(self, 'actions'):
            return
        self.actions.openPrev.setEnabled(
            self._adjacent_visible_file(-1) is not None
        )
        self.actions.openNext.setEnabled(
            self._adjacent_visible_file(1) is not None
        )
        if hasattr(self, 'top_commands'):
            total = len(self.m_img_list)
            current = (
                self.m_img_list.index(self.file_path) + 1
                if self.file_path in self.m_img_list
                else (1 if self.file_path else 0)
            )
            self.top_commands.set_counter(current, total or current)


    def _adjacent_visible_file(self, direction):
        projection = getattr(self, '_file_list_projection', None)
        return (
            projection.adjacent_visible(self.file_path, direction)
            if projection is not None
            else None
        )


    def update_file_selection_count(self):
        if not hasattr(self, 'file_selection_count_label'):
            return
        selected_count = len(self.file_list_widget.selectedItems())
        total_count = self.file_list_widget.count()
        visible_count = len(self.file_list_widget.visible_items())
        hidden_selected = sum(
            item.isHidden()
            for item in self.file_list_widget.selectedItems()
        )
        filter_active = bool(
            hasattr(self, 'file_list_controls')
            and self.file_list_controls.state.filter_active
        )
        if not filter_active:
            self.file_selection_count_label.setText(
                (
                    tr('fileCount.selected', selected=selected_count, total=total_count)
                    if selected_count
                    else tr('fileCount.total', total=total_count)
                )
            )
            return
        parts = [tr('fileCount.visible', visible=visible_count, total=total_count)]
        if selected_count:
            selection = tr('fileCount.selectedShort', selected=selected_count)
            if hidden_selected:
                selection += tr('fileCount.hidden', hidden=hidden_selected)
            parts.append(selection)
        if (
            filter_active
            and self.file_path
            and self.file_path in self.m_img_list
            and self.file_path not in self.visible_file_paths()
        ):
            parts.append(tr('fileCount.currentHidden'))
        self.file_selection_count_label.setText(' · '.join(parts))


    def update_current_file_marker(self):
        current_path = (
            os.path.abspath(self.file_path)
            if self.file_path
            else None
        )
        for index in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(index)
            item_path = item.data(Qt.UserRole)
            item.setData(
                CURRENT_IMAGE_ROLE,
                bool(
                    current_path
                    and item_path
                    and os.path.abspath(item_path) == current_path
                ),
            )
        self.file_list_widget.viewport().update()
        self.update_file_selection_count()
        self.update_file_navigation_actions()


    def open_selected_file(self):
        paths = self.selected_file_paths()
        if len(paths) != 1:
            return
        self.open_file_list_path(paths[0])


    def open_file_list_path(self, filename):
        filename = ustr(filename)
        if filename not in self.m_img_list:
            return
        self.cur_img_idx = self.m_img_list.index(filename)
        self.load_file(filename)


    def pop_file_list_menu(self, point):
        item = self.file_list_widget.itemAt(point)
        menu = QMenu(self.file_list_widget)
        if item is None:
            select_all = menu.addAction(tr('fileMenu.selectAll'))
            select_all.triggered.connect(
                self.file_list_widget.select_all_visible
            )
            select_all.setEnabled(self.file_list_widget.count() > 0)
            menu.exec_(
                self.file_list_widget.viewport().mapToGlobal(point)
            )
            return

        paths = self.selected_file_paths()
        count = len(paths)

        open_action = menu.addAction(tr('fileMenu.open'))
        open_action.setEnabled(count == 1)
        open_action.triggered.connect(self.open_selected_file)

        rename_text = tr('fileMenu.rename') if count == 1 else tr('fileMenu.batchRename')
        rename_action = menu.addAction(rename_text)
        rename_action.setEnabled(count > 0)
        rename_action.triggered.connect(self.rename_selected_files)

        reveal = menu.addAction(tr('fileMenu.reveal'))
        reveal.setEnabled(count == 1)
        reveal.triggered.connect(self.reveal_selected_file)

        menu.addSeparator()
        review_menu = menu.addMenu(tr('fileMenu.setReview'))
        review_enabled = (
            count > 0
            and self.annotation_format
            is AnnotationFormat.PASCAL_VOC
        )
        for title, state in (
            (tr('fileMenu.markVerified'), 'verified'),
            (tr('fileMenu.markQuestioned'), 'questioned'),
            (tr('fileMenu.clearReview'), 'unreviewed'),
        ):
            review_action = review_menu.addAction(title)
            review_action.setEnabled(review_enabled)
            review_action.triggered.connect(
                partial(self.set_selected_review_state, state)
            )

        select_menu = menu.addMenu(tr('fileMenu.select'))
        select_all = select_menu.addAction(tr('fileMenu.selectAll'))
        select_all.triggered.connect(
            self.file_list_widget.select_all_visible
        )
        invert = select_menu.addAction(tr('fileMenu.invert'))
        invert.triggered.connect(self.invert_file_selection)
        state_menu = select_menu.addMenu(tr('fileMenu.byAnnotation'))
        for title, state in (
            (tr('state.unannotated'), 'unannotated'),
            (tr('state.annotated'), 'annotated'),
        ):
            action = state_menu.addAction(title)
            action.triggered.connect(
                partial(self.select_files_by_annotation_state, state)
            )
        review_state_menu = select_menu.addMenu(tr('fileMenu.byReview'))
        for title, state in (
            (tr('state.unreviewed'), 'unreviewed'),
            (tr('state.questioned'), 'questioned'),
            (tr('state.verified'), 'verified'),
        ):
            action = review_state_menu.addAction(title)
            action.triggered.connect(
                partial(self.select_files_by_review_state, state)
            )
        clear_selection = select_menu.addAction(tr('fileMenu.clearSelection'))
        clear_selection.triggered.connect(
            self.file_list_widget.clearSelection
        )

        copy_menu = menu.addMenu(tr('fileMenu.copy'))
        for title, representation in (
            (tr('fileMenu.fileName'), 'name'),
            (tr('fileMenu.relativePath'), 'relative'),
            (tr('fileMenu.fullPath'), 'absolute'),
        ):
            action = copy_menu.addAction(title)
            action.triggered.connect(
                partial(
                    self.copy_selected_file_paths,
                    representation,
                )
            )

        menu.addSeparator()
        annotation_count = self.file_operations.annotation_count(paths)
        clear_annotations = menu.addAction(
            tr('fileMenu.clearAnnotations', count=count)
        )
        clear_annotations.setEnabled(
            annotation_count > 0
            or (
                self.file_path in paths
                and bool(self.dirty or self.canvas.shapes)
            )
        )
        clear_annotations.triggered.connect(
            self.clear_selected_file_annotations
        )

        delete_files = menu.addAction(
            tr('fileMenu.deleteFiles', count=count)
        )
        delete_files.setEnabled(count > 0)
        delete_files.triggered.connect(self.delete_selected_files)

        menu.exec_(
            self.file_list_widget.viewport().mapToGlobal(point)
        )


    def invert_file_selection(self):
        blocker = QSignalBlocker(self.file_list_widget)
        self.file_list_widget.invert_visible_selection()
        del blocker
        self.update_file_selection_count()
        self.file_list_widget.viewport().update()


    def _select_files_by_role(self, role, state):
        blocker = QSignalBlocker(self.file_list_widget)
        self.file_list_widget.clearSelection()
        for index in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(index)
            if not item.isHidden() and item.data(role) == state:
                item.setSelected(True)
        del blocker
        self.update_file_selection_count()
        self.file_list_widget.viewport().update()


    def select_files_by_annotation_state(
        self, state, _checked=False
    ):
        self._select_files_by_role(FILE_ANNOTATION_STATE_ROLE, state)


    def select_files_by_review_state(self, state, _checked=False):
        self._select_files_by_role(FILE_REVIEW_STATE_ROLE, state)


    def copy_selected_file_paths(self, representation, _checked=False):
        values = []
        for path in self.selected_file_paths():
            if representation == 'name':
                value = os.path.basename(path)
            elif representation == 'relative':
                value = self.file_list_display_path(path)
            else:
                value = os.path.abspath(path)
            values.append(value)
        QApplication.clipboard().setText('\n'.join(values))


    def reveal_selected_file(self):
        paths = self.selected_file_paths()
        if len(paths) != 1:
            return
        path = os.path.abspath(paths[0])
        try:
            if platform.system() == 'Windows':
                subprocess.Popen(
                    ['explorer.exe', '/select,', path]
                )
            elif platform.system() == 'Darwin':
                subprocess.Popen(['open', '-R', path])
            else:
                subprocess.Popen(
                    ['xdg-open', os.path.dirname(path)]
                )
        except OSError as error:
            self.error_message(
                tr('error.fileManager'),
                u'<p>%s</p>' % error,
            )


    def clear_selected_file_annotations(self):
        paths = self.selected_file_paths()
        if not paths:
            return
        count = self.file_operations.annotation_count(paths)
        answer = localized_question(
            self,
            tr('fileOps.clearTitle'),
            tr('fileOps.clearConfirm', files=len(paths), annotations=count),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        current_path = self.file_path
        outcome = self.run_file_operation(
            paths,
            tr('fileOps.clearing'),
            partial(self.file_operations.execute, 'clear'),
        )
        result = outcome.file_result
        self._warn_manual_trash_recovery(result)
        self.rescan_annotation_workspace()
        self.refresh_file_list_statuses()
        processed = set(
            result.succeeded_images + result.failed_images
        )
        if current_path in processed and os.path.isfile(current_path):
            self.load_file(current_path)
        self.report_file_operation_result(
            tr('fileOps.clear'),
            result,
        )


    def delete_selected_files(self):
        paths = self.selected_file_paths()
        if not paths:
            return
        answer = localized_question(
            self,
            tr('fileOps.deleteTitle'),
            tr('fileOps.deleteConfirm', count=len(paths)),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.delete_file_paths(paths)


    def delete_file_paths(self, paths):
        before = list(self.m_img_list)
        old_current = self.file_path
        old_index = (
            before.index(old_current)
            if old_current in before
            else 0
        )
        outcome = self.run_file_operation(
            paths,
            tr('fileOps.deleting'),
            partial(self.file_operations.execute, 'delete'),
        )
        result = outcome.file_result
        self._warn_manual_trash_recovery(result)
        self.rebuild_file_list_after_deletion(
            before,
            old_current,
            old_index,
            result,
        )
        self.rescan_annotation_workspace()
        self.report_file_operation_result(tr('fileOps.delete'), result)
        return result


    def _warn_manual_trash_recovery(self, result):
        manual_count = sum(
            not resource.identity.actionable
            for resource in result.trashed_resources
        )
        if not manual_count:
            return
        localized_warning(
            self,
            tr('fileOps.manualRecoveryTitle'),
            tr('fileOps.manualRecovery', count=manual_count),
        )


    def run_file_operation(self, paths, title, operation):
        progress = None
        position = [0]
        if len(paths) >= 20:
            progress = QProgressDialog(
                title,
                tr('common.cancel'),
                0,
                len(paths),
                self,
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(400)

        def should_continue():
            if progress is None:
                return True
            progress.setValue(position[0])
            QApplication.processEvents()
            if progress.wasCanceled():
                return False
            position[0] += 1
            return True

        result = operation(paths, should_continue=should_continue)
        if progress is not None:
            progress.setValue(len(paths))
        return result


    def rebuild_file_list_after_deletion(
        self,
        before,
        old_current,
        old_index,
        result,
    ):
        succeeded = set(result.succeeded_images)
        failed = set(result.failed_images)
        self.populate_file_list(self.scan_all_images(self.dir_name))

        next_path = None
        if old_current and old_current not in succeeded:
            if old_current in self.m_img_list:
                next_path = old_current
        elif old_current:
            for candidate in before[old_index + 1:]:
                if candidate in self.m_img_list:
                    next_path = candidate
                    break
            if next_path is None:
                for candidate in reversed(before[:old_index]):
                    if candidate in self.m_img_list:
                        next_path = candidate
                        break

        if (
            next_path == old_current
            and old_current not in failed
        ):
            self.cur_img_idx = self.m_img_list.index(old_current)
            self.update_current_file_marker()
        elif next_path is not None:
            self.cur_img_idx = self.m_img_list.index(next_path)
            self.load_file(next_path)
        elif self.m_img_list:
            self.cur_img_idx = min(old_index, len(self.m_img_list) - 1)
            self.load_file(self.m_img_list[self.cur_img_idx])
        else:
            self.cur_img_idx = 0
            self.reset_state()
            self.set_clean()
            self.toggle_actions(False)
            self.canvas.setEnabled(False)
            self.actions.saveAs.setEnabled(False)
            self.update_current_file_marker()

        for index in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(index)
            if item.data(Qt.UserRole) in failed:
                item.setSelected(True)
        self.update_file_selection_count()


    def rescan_annotation_workspace(self):
        directory = self.default_save_dir or self.dir_name
        if directory and os.path.isdir(directory):
            self.annotation_workspace.scan(directory)
        self.refresh_candidate_labels()


    def report_file_operation_result(self, title, result):
        if result.failures:
            self.show_file_operation_failures(
                tr('fileOps.partialFailure', title=title),
                [
                    (
                        failure.path,
                        failure.reason,
                    )
                    for failure in result.failures
                ],
            )
            return
        message = tr(
            'fileOps.complete',
            title=title,
            count=len(result.succeeded_images),
        )
        if result.canceled:
            message += tr('fileOps.canceled')
        self.status(message)


    def show_file_operation_failures(self, title, failures):
        details = '\n'.join(
            '%s: %s' % (path, error)
            for path, error in failures
        )
        localized_warning(
            self,
            title,
            '%s\n\n%s' % (title, details),
        )


    def rename_selected_files(self):
        paths = self.selected_file_paths()
        if not paths:
            return
        if len(paths) == 1:
            self.rename_single_file(paths[0])
            return
        dialog = BatchRenameDialog(
            paths,
            self.dir_name,
            save_dir=self.default_save_dir,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        self.execute_file_rename(dialog.mapping)


    def rename_single_file(self, source):
        stem, extension = os.path.splitext(os.path.basename(source))
        new_stem, accepted = QInputDialog.getText(
            self,
            tr('rename.title'),
            tr('rename.prompt', extension=extension),
            QLineEdit.Normal,
            stem,
        )
        if not accepted:
            return
        new_stem = new_stem.strip()
        target = os.path.join(
            os.path.dirname(source),
            new_stem + extension,
        )
        error = validate_base_name(new_stem, target)
        if not error:
            error = validate_rename_mapping(
                {source: target},
                self.default_save_dir,
            ).get(source, '')
        if error:
            localized_warning(self, tr('rename.unable'), error)
            return
        if source == target:
            return
        self.execute_file_rename({source: target})


    def execute_file_rename(self, mapping):
        if self.annotation_persistence.conflicts:
            localized_warning(
                self,
                tr('rename.unavailable'),
                tr('rename.resolveConflicts'),
            )
            return
        if self.file_path in mapping and self.dirty:
            if not self.save_current_annotations_directly():
                return
        old_current = self.file_path
        selected_before = self.selected_file_paths()
        try:
            outcome = self.file_operations.execute('rename', mapping)
        except FileOperationBlocked:
            localized_warning(
                self,
                tr('rename.unavailable'),
                tr('rename.resolveConflicts'),
            )
            return
        except FileOperationError as error:
            localized_warning(
                self,
                tr('rename.failed'),
                str(error),
            )
            return

        renamed = dict(outcome.renamed)
        current_after = renamed.get(old_current, old_current)
        selected_after = {
            renamed.get(path, path)
            for path in selected_before
        }
        self.populate_file_list(self.scan_all_images(self.dir_name))
        if old_current in renamed and current_after in self.m_img_list:
            self.cur_img_idx = self.m_img_list.index(current_after)
            self.load_file(current_after)
        elif current_after in self.m_img_list:
            self.cur_img_idx = self.m_img_list.index(current_after)
            self.update_current_file_marker()
        for index in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(index)
            if item.data(Qt.UserRole) in selected_after:
                item.setSelected(True)
        self.rescan_annotation_workspace()
        self.refresh_file_list_statuses()
        self.update_file_selection_count()
        self.status(tr('status.renamed', count=len(renamed)))


    def file_item_double_clicked(self, item=None):
        if item is None:
            return
        filename = item.data(Qt.UserRole)
        if not filename:
            filename = item.text()
        filename = ustr(filename)
        if filename not in self.m_img_list:
            return
        if filename:
            self.open_file_list_path(filename)


    def scan_all_images(self, folder_path):
        extensions = ['.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        images = []

        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(tuple(extensions)):
                    relative_path = os.path.join(root, file)
                    path = ustr(os.path.abspath(relative_path))
                    images.append(path)
        images.sort(
            key=cmp_to_key(
                partial(compare_relative_image_paths, root=folder_path)
            )
        )
        return images


    def file_list_display_path(self, image_path):
        if not self.dir_name:
            return os.path.basename(image_path)

        image_path = os.path.abspath(image_path)
        display_root = os.path.abspath(self.dir_name)
        try:
            relative_path = os.path.relpath(image_path, display_root)
        except ValueError:
            return os.path.basename(image_path)

        if (
            relative_path == os.pardir
            or relative_path.startswith(os.pardir + os.sep)
        ):
            return os.path.basename(image_path)
        return relative_path


    def file_list_item_text(self, image_path):
        return self.file_list_display_path(image_path)


    def update_file_list_item_status(self, image_path, refresh_view=True):
        if not image_path or image_path not in self.m_img_list:
            return
        index = self.m_img_list.index(image_path)
        item = self.file_list_widget.item(index)
        if item is None:
            return
        item.setData(Qt.UserRole, image_path)
        item.setData(
            FILE_ANNOTATION_STATE_ROLE,
            self.file_annotation_state(image_path),
        )
        item.setData(
            FILE_REVIEW_STATE_ROLE,
            self.file_review_state(image_path),
        )
        flags = self.file_persistence_flags(image_path)
        item.setData(FILE_PERSISTENCE_FLAGS_ROLE, flags)
        quality_result = self._quality_result_for_path(image_path)
        from labelimg.image_tools import quality_finding_text
        quality_findings = tuple(
            {
                'code': finding.code,
                'severity': finding.severity,
                'explanation': quality_finding_text(finding),
            }
            for finding in quality_result.findings
        ) if quality_result is not None else ()
        item.setData(FILE_QUALITY_FINDINGS_ROLE, quality_findings)
        item.setText(self.file_list_item_text(image_path))
        details = [image_path]
        if 'dirty' in flags:
            details.append(tr('state.dirty'))
        if 'conflict' in flags:
            details.append(tr('state.conflict'))
        if 'ambiguous' in flags:
            details.append(tr('fileStatus.ambiguous'))
        if 'degraded' in flags:
            details.append(tr('fileStatus.degraded'))
        details.extend(
            finding['explanation'] for finding in quality_findings
        )
        item.setToolTip('\n'.join(details))
        if refresh_view:
            self.apply_file_list_view()


    def refresh_file_list_statuses(self):
        for image_path in self.m_img_list:
            self.update_file_list_item_status(
                image_path,
                refresh_view=False,
            )
        self.apply_file_list_view()

