"""Directory cleanup preview and the workbench adapter for its transaction."""

import os

from PyQt5.QtCore import QSignalBlocker, Qt
from PyQt5.QtGui import QImageReader
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QHeaderView,
    QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
)

from labelimg.files.application.cleanup import CleanupCanceled, CleanupError, scan_cleanup
from labelimg.localization.runtime import (
    language_changed, localize_dialog_buttons, question, tr, warning,
)


def cleanup_error_text(error):
    if isinstance(error, CleanupError):
        return tr("cleanup.error." + error.reason) + ("\n" + error.path if error.path else "")
    return str(error)


class AnnotationCleanupDialog(QDialog):
    def __init__(self, image_dir, annotation_dir, extensions, parent=None):
        super().__init__(parent)
        self.image_dir = image_dir
        self.annotation_dir = annotation_dir
        self.extensions = tuple(extensions)
        self.plan = None
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        layout = QVBoxLayout(self)
        self.scope = QLabel()
        self.scope.setTextFormat(Qt.PlainText)
        self.scope.setWordWrap(True)
        self.scope.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.scope)
        self.scan_button = QPushButton()
        self.scan_button.clicked.connect(self.scan)
        layout.addWidget(self.scan_button)
        categories = QHBoxLayout()
        self.orphans = QCheckBox()
        self.orphans.setChecked(True)
        self.empty = QCheckBox()
        categories.addWidget(self.orphans)
        categories.addWidget(self.empty)
        categories.addStretch()
        layout.addLayout(categories)
        self.orphans.toggled.connect(lambda checked: self._check_category(True, checked))
        self.empty.toggled.connect(lambda checked: self._check_category(False, checked))
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.table = QTableWidget(0, 2)
        self.skipped = QTableWidget(0, 2)
        for table in (self.table, self.skipped):
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            table.setWordWrap(False)
        self.table.itemChanged.connect(self._update_selection)
        self.tabs.addTab(self.table, "")
        self.tabs.addTab(self.skipped, "")
        layout.addWidget(self.tabs)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.apply_button = self.buttons.button(QDialogButtonBox.Ok)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        language_changed.connect(self.retranslate)
        self.resize(880, 600)
        self.retranslate()

    @property
    def selected_items(self):
        if self.plan is None:
            return ()
        return tuple(item for row, item in enumerate(self.plan.items) if self.table.item(row, 0).checkState() == Qt.Checked)

    def retranslate(self, *_args):
        self.setWindowTitle(tr("cleanup.title"))
        self.scope.setText(tr("cleanup.scope", images=self.image_dir, annotations=self.annotation_dir))
        self.scan_button.setText(tr("cleanup.scan"))
        self.orphans.setText(tr("cleanup.orphans"))
        self.empty.setText(tr("cleanup.empty"))
        self.table.setHorizontalHeaderLabels((tr("cleanup.path"), tr("cleanup.reason")))
        self.skipped.setHorizontalHeaderLabels((tr("cleanup.path"), tr("cleanup.diagnostic")))
        self.tabs.setTabText(0, tr("cleanup.candidates"))
        self.tabs.setTabText(1, tr("cleanup.skipped"))
        self.note.setText(tr("cleanup.note"))
        localize_dialog_buttons(self.buttons)
        if self.plan:
            for row, item in enumerate(self.plan.items):
                self.table.item(row, 1).setText(tr("cleanup.reason." + item.reason))
            for row, (_path, error) in enumerate(self.plan.skipped):
                self.skipped.item(row, 1).setText(cleanup_error_text(error))
        self._update_selection()

    def scan(self):
        self.plan = None
        self.table.setRowCount(0)
        self.skipped.setRowCount(0)
        self.apply_button.setEnabled(False)
        self.scan_button.setEnabled(False)
        progress = QProgressDialog(tr("cleanup.scanning"), tr("common.cancel"), 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        def report(_path):
            QApplication.processEvents()
            if progress.wasCanceled():
                raise CleanupCanceled()

        try:
            self.plan = scan_cleanup(self.image_dir, self.annotation_dir, self.extensions, report)
        except CleanupCanceled:
            self.summary.setText(tr("cleanup.scanCanceled"))
            return
        except Exception as error:
            self.summary.setText(cleanup_error_text(error))
            return
        finally:
            progress.close()
            progress.deleteLater()
            self.scan_button.setEnabled(True)
        blocker = QSignalBlocker(self.table)
        self.table.setRowCount(len(self.plan.items))
        for row, item in enumerate(self.plan.items):
            name = QTableWidgetItem(os.path.relpath(item.path, self.annotation_dir))
            name.setToolTip(item.path)
            name.setFlags(name.flags() | Qt.ItemIsUserCheckable)
            selected = self.orphans.isChecked() if item.reason == "orphan" else self.empty.isChecked()
            name.setCheckState(Qt.Checked if selected else Qt.Unchecked)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(tr("cleanup.reason." + item.reason)))
        del blocker
        self.skipped.setRowCount(len(self.plan.skipped))
        for row, (path, error) in enumerate(self.plan.skipped):
            name = QTableWidgetItem(os.path.relpath(path, self.annotation_dir))
            name.setToolTip(path)
            self.skipped.setItem(row, 0, name)
            self.skipped.setItem(row, 1, QTableWidgetItem(cleanup_error_text(error)))
        self._update_selection()

    def _check_category(self, orphan, checked):
        if self.plan is None:
            return
        blocker = QSignalBlocker(self.table)
        for row, item in enumerate(self.plan.items):
            if (item.reason == "orphan") == orphan:
                self.table.item(row, 0).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        del blocker
        self._update_selection()

    def _update_selection(self, *_args):
        count = len(self.selected_items)
        self.apply_button.setEnabled(bool(count))
        self.apply_button.setText(tr("cleanup.apply", count=count))
        if self.plan:
            self.summary.setText(tr(
                "cleanup.summary", candidates=len(self.plan.items), selected=count,
                skipped=len(self.plan.skipped), images=len(self.plan.image_paths),
            ) + "\n" + tr("cleanup.scanScope", paths="; ".join(directory for directory, _recursive in self.plan.scan_directories)))
        else:
            self.summary.setText(tr("cleanup.previewFirst"))

    def accept(self):
        count = len(self.selected_items)
        if count and question(self, tr("cleanup.title"), tr("cleanup.confirm", count=count), QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            super().accept()


def show_annotation_cleanup(window):
    image_dir = window.dir_name
    annotation_dir = window.default_save_dir or image_dir
    if not image_dir or not annotation_dir or not os.path.isdir(image_dir) or not os.path.isdir(annotation_dir):
        warning(window, tr("cleanup.title"), tr("cleanup.error.directories"))
        return
    if window.annotation_editing.pending or window.annotation_editing.edit_open:
        window.status(tr("status.finishEdit"))
        return
    extensions = tuple("." + value.data().decode("ascii").lower() for value in QImageReader.supportedImageFormats())
    dialog = AnnotationCleanupDialog(image_dir, annotation_dir, extensions, window)
    timer_active = window.auto_save_timer.isActive()
    window.auto_save_timer.stop()
    window.annotation_editing.set_pending("Clean annotation files", dialog.reject)
    window._sync_annotation_history_ui()
    try:
        accepted = dialog.exec_()
        window.annotation_editing.clear_pending()
        if not accepted or not dialog.selected_items:
            return
        with window._suspend_annotation_watches():
            outcome = window.run_file_operation(
                dialog.selected_items, tr("cleanup.cleaning"),
                lambda items, should_continue: window.file_operations.cleanup_annotations(dialog.plan, items, should_continue),
            )
            result = outcome.file_result
            window._warn_manual_trash_recovery(result)
            window.rescan_annotation_workspace()
            window.refresh_file_list_statuses()
            if window.file_path in result.affected_images:
                window.load_file(window.file_path)
        window.status(tr("cleanup.completed", count=len(result.removed_paths)) + (tr("fileOps.canceled") if result.canceled else ""))
        if result.failures:
            window.show_file_operation_failures(tr("cleanup.failed"), [(path, cleanup_error_text(error)) for path, error in result.failures])
    except Exception as error:
        warning(window, tr("cleanup.failed"), cleanup_error_text(error))
    finally:
        window.annotation_editing.clear_pending()
        window._sync_annotation_history_ui()
        window._watch_current_annotation_document()
        if timer_active:
            window.auto_save_timer.start()
        dialog.deleteLater()
