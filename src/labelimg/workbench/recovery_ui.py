"""RecoveryActionsMixin extracted from the top-level workbench window."""

#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os.path

from functools import partial

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImageReader
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QHeaderView, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

import labelimg.ui.generated_resources  # noqa: F401 - registers Qt resources
from labelimg.localization.runtime import localize_dialog_buttons, question as localized_question, tr, warning as localized_warning
from labelimg.files.application.transaction import FileRecoveryBlocked
from labelimg.files.application.recovery import RecoveryOperation


class RecoveryActionsMixin:
    def open_file_recovery_center(self, _checked=False):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('recovery.title'))
        layout = QVBoxLayout(dialog)
        table = QTableWidget(
            len(self.file_operations.recovery_entries), 5, dialog
        )
        table.setHorizontalHeaderLabels(
            (
                tr('recovery.time'),
                tr('recovery.operation'),
                tr('recovery.targets'),
                tr('recovery.status'),
                '',
            )
        )
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        table.horizontalHeader().setStretchLastSection(True)
        for row, entry in enumerate(
            self.file_operations.recovery_entries
        ):
            values = (
                entry.created_at.astimezone().strftime('%H:%M:%S'),
                tr('recovery.operation.%s' % entry.operation),
                str(entry.target_count),
                tr('recovery.status.%s' % entry.status.value),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if entry.detail:
                    item.setToolTip(entry.detail)
                table.setItem(row, column, item)
            recover = QPushButton(tr('recovery.recover'), table)
            recover.setEnabled(entry.recoverable)
            recover.clicked.connect(
                partial(
                    self._confirm_file_recovery,
                    entry.entry_id,
                    dialog,
                )
            )
            table.setCellWidget(row, 4, recover)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, dialog)
        localize_dialog_buttons(buttons)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(680, 360)
        dialog.exec_()


    def _confirm_file_recovery(
        self,
        entry_id,
        dialog=None,
        _checked=False,
    ):
        entry = next(
            item
            for item in self.file_operations.recovery_entries
            if item.entry_id == entry_id
        )
        selected_paths = None
        if entry.operation is RecoveryOperation.IMAGE_PROCESSING:
            selected_paths = self._choose_image_recovery_paths(entry)
            if selected_paths is None:
                return
        else:
            answer = localized_question(
                self,
                tr('recovery.confirmTitle'),
                tr(
                    'recovery.confirm',
                    operation=tr(
                        'recovery.operation.%s' % entry.operation
                    ),
                    count=entry.target_count,
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            outcome = (
                self.image_processing.recover(
                    entry_id,
                    selected_paths=selected_paths,
                )
                if entry.operation is RecoveryOperation.IMAGE_PROCESSING
                else self.file_operations.recover(entry_id)
            )
        except FileRecoveryBlocked as error:
            localized_warning(
                self,
                tr('recovery.blocked'),
                str(error),
            )
            return
        except Exception as error:
            localized_warning(
                self,
                tr('recovery.failed'),
                str(error),
            )
            return

        if entry.operation is RecoveryOperation.IMAGE_PROCESSING:
            self.status(tr('recovery.completed'))
            if dialog is not None:
                dialog.accept()
            return

        selected_before = tuple(self.selected_file_paths())
        renamed = dict(outcome.renamed)
        if self.file_path in renamed:
            self.file_path = renamed[self.file_path]
        if outcome.review_result is not None:
            self._project_review_recovery(outcome.review_result)
        restored_images = []
        if outcome.restored_paths:
            image_extensions = {
                '.%s' % value.data().decode('ascii').lower()
                for value in QImageReader.supportedImageFormats()
            }
            restored_images = [
                path
                for path in outcome.restored_paths
                if os.path.splitext(path)[1].lower()
                in image_extensions
            ]
        if self.dir_name and os.path.isdir(self.dir_name):
            self.populate_file_list(self.scan_all_images(self.dir_name))
            selected_after = set(selected_before)
            if renamed:
                selected_after = {
                    renamed.get(path, path)
                    for path in selected_after
                }
            selected_after.update(restored_images)
            for row in range(self.file_list_widget.count()):
                item = self.file_list_widget.item(row)
                if item.data(Qt.UserRole) in selected_after:
                    item.setSelected(True)
        self.rescan_annotation_workspace()
        self.refresh_file_list_statuses()
        self._refresh_current_image_pixels(restored_images)
        if self.file_path is None and restored_images:
            self.load_file(restored_images[0])
        elif (
            entry.operation == 'clear'
            and self.file_path
            and any(
                os.path.normcase(resource.original_path)
                in {
                    os.path.normcase(path)
                    for path in self.annotation_paths_for_image(
                        self.file_path
                    )
                }
                for resource in entry.payload
            )
        ):
            self.load_file(self.file_path)
        self.status(tr('recovery.completed'))
        if dialog is not None:
            dialog.accept()

