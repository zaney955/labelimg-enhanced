"""Cancelable UI adapter for progressive directory loading."""

from __future__ import annotations

import os
import time

from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QPushButton

from labelimg.annotations import AnnotationWorkspace
from labelimg.files import discover_images
from labelimg.localization.runtime import tr


UI_BATCH_SIZE = 64


class _DirectoryLoadWorker(QObject):
    discovered = pyqtSignal(int, object)
    indexed = pyqtSignal(int, object)
    failed = pyqtSignal(int, object)
    finished = pyqtSignal(int)

    def __init__(self, generation, image_directory, annotation_directory, extensions):
        super().__init__()
        self.generation = generation
        self.image_directory = image_directory
        self.annotation_directory = annotation_directory
        self.extensions = tuple(extensions)

    @pyqtSlot()
    def run(self):
        try:
            paths = discover_images(self.image_directory, self.extensions)
            self.discovered.emit(self.generation, paths)
            workspace = AnnotationWorkspace(save_dir=self.annotation_directory)
            scan_directory = self.annotation_directory or self.image_directory
            if scan_directory and os.path.isdir(scan_directory):
                workspace.scan(scan_directory)
            self.indexed.emit(self.generation, workspace)
        except Exception as error:
            self.failed.emit(self.generation, error)
        finally:
            self.finished.emit(self.generation)


class _AnnotationDirectoryWorker(QObject):
    indexed = pyqtSignal(int, object, object)
    failed = pyqtSignal(int, object)
    finished = pyqtSignal(int)

    def __init__(self, generation, directory):
        super().__init__()
        self.generation = generation
        self.directory = directory

    @pyqtSlot()
    def run(self):
        try:
            workspace = AnnotationWorkspace(save_dir=self.directory)
            if self.directory and os.path.isdir(self.directory):
                workspace.scan(self.directory)
            self.indexed.emit(self.generation, self.directory, workspace)
        except Exception as error:
            self.failed.emit(self.generation, error)
        finally:
            self.finished.emit(self.generation)


class DirectoryLoadingMixin:
    """Own worker generations while application modules remain Qt-free."""

    def _ensure_directory_loading(self):
        if hasattr(self, "_directory_load_generation"):
            return
        self._directory_load_generation = 0
        self._directory_load_jobs = {}
        self._directory_load_request = None
        self._directory_pending_paths = ()
        self._directory_pending_workspace = None
        self._directory_projection_pending = False
        self._directory_ready_commit_seconds = 0.0
        self._directory_max_ui_batch_seconds = 0.0
        self.directory_load_button = QPushButton(self)
        self.directory_load_button.hide()
        self.directory_load_button.clicked.connect(self._toggle_directory_load)
        self.statusBar().addPermanentWidget(self.directory_load_button)

    def start_directory_load(self, directory, initial_index=0):
        if not directory or not self.may_continue():
            return False
        self._ensure_directory_loading()
        self._directory_load_generation += 1
        generation = self._directory_load_generation
        directory = os.path.abspath(os.fspath(directory))
        annotation_directory = self.default_save_dir
        self._directory_load_request = (directory, initial_index)
        extensions = tuple(
            ".%s" % value.data().decode("ascii").lower()
            for value in self.supported_image_formats()
        )
        thread = QThread(self)
        worker = _DirectoryLoadWorker(
            generation,
            directory,
            annotation_directory,
            extensions,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.discovered.connect(
            lambda current, paths: self._directory_paths_discovered(
                current, directory, initial_index, paths
            )
        )
        worker.indexed.connect(self._directory_index_completed)
        worker.failed.connect(self._directory_load_failed)
        worker.finished.connect(self._directory_worker_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._directory_load_jobs[generation] = (thread, worker)
        self.directory_load_button.setText(tr("directoryLoading.stop"))
        self.directory_load_button.show()
        self.status(tr("directoryLoading.discovering"))
        thread.start()
        return True

    def start_annotation_directory_load(self, directory):
        if not self.may_continue():
            return False
        self._ensure_directory_loading()
        self._directory_load_generation += 1
        generation = self._directory_load_generation
        directory = os.path.abspath(os.fspath(directory)) if directory else None
        thread = QThread(self)
        worker = _AnnotationDirectoryWorker(generation, directory)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.indexed.connect(self._annotation_directory_index_completed)
        worker.failed.connect(self._directory_load_failed)
        worker.finished.connect(self._directory_worker_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._directory_load_jobs[generation] = (thread, worker)
        self.directory_load_button.setText(tr("directoryLoading.stop"))
        self.directory_load_button.show()
        self.status(tr("directoryLoading.annotation"))
        thread.start()
        return True

    def supported_image_formats(self):
        from PyQt5.QtGui import QImageReader
        return QImageReader.supportedImageFormats()

    def stop_directory_load(self):
        self._ensure_directory_loading()
        self._directory_load_generation += 1
        self._directory_pending_paths = ()
        self._directory_pending_workspace = None
        self._directory_projection_pending = False
        self.directory_load_button.setText(tr("directoryLoading.resume"))
        self.status(tr("directoryLoading.stopped"))

    def _toggle_directory_load(self):
        if self.directory_load_button.text() == tr("directoryLoading.resume"):
            if self._directory_load_request:
                self.start_directory_load(*self._directory_load_request)
        else:
            self.stop_directory_load()

    def _directory_paths_discovered(
        self, generation, directory, initial_index, paths
    ):
        if generation != self._directory_load_generation:
            return
        started = time.perf_counter()
        published = self.commit_discovered_directory(
            directory, paths, initial_index=initial_index
        )
        elapsed = time.perf_counter() - started
        self._directory_ready_commit_seconds = elapsed
        self._directory_max_ui_batch_seconds = max(
            self._directory_max_ui_batch_seconds, elapsed
        )
        if published is False:
            self.stop_directory_load()
            return
        self._directory_pending_paths = tuple(paths[published:])
        self._directory_projection_pending = bool(
            self._directory_pending_paths
        )
        self.file_list_controls.set_index_complete(False)
        if self._directory_projection_pending:
            QTimer.singleShot(0, self._publish_next_path_batch)
        self.status(tr("directoryLoading.indexing", count=len(paths)))

    def _publish_next_path_batch(self):
        if not self._directory_pending_paths:
            if self._directory_pending_workspace is not None:
                workspace = self._directory_pending_workspace
                self._directory_pending_workspace = None
                self._begin_status_projection(workspace)
            else:
                self._directory_projection_pending = False
            return
        started = time.perf_counter()
        batch = self._directory_pending_paths[:UI_BATCH_SIZE]
        self._directory_pending_paths = self._directory_pending_paths[UI_BATCH_SIZE:]
        self.append_file_list_rows(batch, indexed=False)
        elapsed = time.perf_counter() - started
        self._directory_max_ui_batch_seconds = max(
            self._directory_max_ui_batch_seconds, elapsed
        )
        QTimer.singleShot(0, self._publish_next_path_batch)

    def _directory_index_completed(self, generation, workspace):
        if generation != self._directory_load_generation:
            return
        self.annotation_workspace.adopt_index(workspace)
        for label in self.annotation_workspace.candidate_labels:
            if label not in self.label_hist:
                self.label_hist.append(label)
        self.refresh_candidate_labels()
        if self._directory_pending_paths:
            self._directory_pending_workspace = workspace
        else:
            self._begin_status_projection(workspace)

    def _begin_status_projection(self, _workspace):
        self._directory_status_offset = 0
        self._directory_projection_pending = True
        QTimer.singleShot(0, self._project_next_status_batch)

    def _project_next_status_batch(self):
        started = time.perf_counter()
        first = self._directory_status_offset
        last = min(first + UI_BATCH_SIZE, len(self.m_img_list))
        for path in self.m_img_list[first:last]:
            self.update_file_list_item_status(path, refresh_view=False)
        self._directory_status_offset = last
        elapsed = time.perf_counter() - started
        self._directory_max_ui_batch_seconds = max(
            self._directory_max_ui_batch_seconds, elapsed
        )
        if last < len(self.m_img_list):
            QTimer.singleShot(0, self._project_next_status_batch)
            return
        self._directory_projection_pending = False
        self.file_list_controls.set_index_complete(True)
        self.file_list_widget.viewport().update()
        self.update_file_selection_count()
        self.directory_load_button.hide()
        self.status(tr("directoryLoading.complete", count=len(self.m_img_list)))

    def _annotation_directory_index_completed(
        self, generation, directory, workspace
    ):
        if generation != self._directory_load_generation:
            return
        if self.commit_indexed_annotation_directory(directory, workspace):
            self.directory_load_button.hide()
            self.status(tr("directoryLoading.complete", count=len(self.m_img_list)))

    def _directory_load_failed(self, generation, error):
        if generation != self._directory_load_generation:
            return
        self.directory_load_button.setText(tr("directoryLoading.resume"))
        self.status(tr("directoryLoading.failed", error=error))

    def _directory_worker_finished(self, generation):
        self._directory_load_jobs.pop(generation, None)
