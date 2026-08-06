"""Modal shared workspace for built-in image tools."""

from __future__ import annotations

from dataclasses import dataclass
import os

import cv2
import numpy as np
from PyQt5.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from labelimg.i18n import localize_dialog_buttons, tr, warning
from labelimg.image_tools.colored_frame_removal import (
    DetectionStrength,
    FrameColor,
    FrameRemovalOptions,
)
from labelimg.image_tools.image_tool_processor import (
    ImageToolProcessor,
    UnsupportedImageToolTarget,
)


class TargetStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    NO_FRAME = "noFrame"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    EXCLUDED = "excluded"


@dataclass
class _TargetState:
    path: str
    status: str = TargetStatus.QUEUED
    included: bool = True
    result: object = None
    error: str = ""
    token: int = 0


class _WorkerSignals(QObject):
    finished = pyqtSignal(int, str, object, object)


class _PrepareWorker(QRunnable):
    def __init__(self, generation, path, processor, options):
        super().__init__()
        self.generation = generation
        self.path = path
        self.processor = processor
        self.options = options
        self.signals = _WorkerSignals()

    def run(self):
        result = None
        error = None
        try:
            result = self.processor.prepare(self.path, self.options)
        except Exception as caught:
            error = caught
        self.signals.finished.emit(
            self.generation,
            self.path,
            result,
            error,
        )


class _SelectionWorker(QRunnable):
    def __init__(self, token, path, processor, prepared, candidate_ids):
        super().__init__()
        self.token = token
        self.path = path
        self.processor = processor
        self.prepared = prepared
        self.candidate_ids = candidate_ids
        self.signals = _WorkerSignals()

    def run(self):
        result = None
        error = None
        try:
            result = self.processor.select_candidates(
                self.prepared,
                self.candidate_ids,
            )
        except Exception as caught:
            error = caught
        self.signals.finished.emit(
            self.token,
            self.path,
            result,
            error,
        )


class _PreviewLabel(QLabel):
    imageClicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self._image_size = (0, 0)
        self._display_rect = (0, 0, 0, 0)

    def set_preview_pixmap(self, pixmap, image_size):
        self._image_size = image_size
        if pixmap.isNull():
            self.clear()
            self._display_rect = (0, 0, 0, 0)
            return
        available = self.size()
        scaled = pixmap.scaled(
            max(1, available.width()),
            max(1, available.height()),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        left = (available.width() - scaled.width()) // 2
        top = (available.height() - scaled.height()) // 2
        self._display_rect = (left, top, scaled.width(), scaled.height())
        self.setPixmap(scaled)

    def mousePressEvent(self, event):
        left, top, width, height = self._display_rect
        image_width, image_height = self._image_size
        if (
            event.button() == Qt.LeftButton
            and width > 0
            and height > 0
            and left <= event.x() < left + width
            and top <= event.y() < top + height
        ):
            x = int((event.x() - left) * image_width / width)
            y = int((event.y() - top) * image_height / height)
            self.imageClicked.emit(x, y)
        super().mousePressEvent(event)


class ImageToolsDialog(QDialog):
    """Preview, filter, and atomically commit an image-tool target set."""

    def __init__(
        self,
        current_path,
        selected_paths=(),
        *,
        commit,
        processor=None,
        thread_pool=None,
        asynchronous=True,
        parent=None,
    ):
        super().__init__(parent)
        self.current_path = os.path.abspath(os.fspath(current_path))
        self.selected_paths = tuple(
            dict.fromkeys(
                os.path.abspath(os.fspath(path))
                for path in selected_paths
            )
        )
        self._commit = commit
        self._processor = processor or ImageToolProcessor()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._asynchronous = asynchronous
        self._generation = 0
        self._states = {}
        self._items = {}
        self._active_path = None
        self._workers = set()
        self._selection_history = []
        self._selection_redo = []
        self._restoring_controls = False
        self._candidate_change_active = False
        self.outcome = None
        self._preview_source = None

        self.setWindowTitle(tr("imageTools.title"))
        self.setModal(True)
        self.resize(1180, 760)
        self._build_ui()
        self._connect_ui()
        self._populate_scope()
        self._set_targets((self.current_path,))

    @property
    def target_paths(self):
        return tuple(self._states)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel(tr("imageTools.scope"), self))
        self.scope_combo = QComboBox(self)
        header.addWidget(self.scope_combo)
        header.addStretch(1)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Horizontal, self)
        outer.addWidget(splitter, 1)

        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel(tr("imageTools.tools"), left))
        self.tool_list = QListWidget(left)
        tool = QListWidgetItem(tr("imageTools.removeFrames"))
        tool.setData(Qt.UserRole, "removeFrames")
        self.tool_list.addItem(tool)
        self.tool_list.setCurrentRow(0)
        left_layout.addWidget(self.tool_list)
        left_layout.addWidget(QLabel(tr("imageTools.targets"), left))
        self.target_list = QTreeWidget(left)
        self.target_list.setColumnCount(2)
        self.target_list.setHeaderLabels((
            tr("imageTools.target"),
            tr("imageTools.status"),
        ))
        left_layout.addWidget(self.target_list, 1)

        center = QWidget(splitter)
        center_layout = QVBoxLayout(center)
        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel(tr("imageTools.preview"), center))
        self.preview_mode = QComboBox(center)
        for message_id, value in (
            ("imageTools.preview.original", "original"),
            ("imageTools.preview.result", "result"),
            ("imageTools.preview.mask", "mask"),
        ):
            self.preview_mode.addItem(tr(message_id), value)
        self.preview_mode.setCurrentIndex(1)
        preview_header.addWidget(self.preview_mode)
        preview_header.addStretch(1)
        center_layout.addLayout(preview_header)
        self.preview_label = _PreviewLabel(center)
        self.preview_label.setMinimumSize(420, 360)
        self.preview_label.setStyleSheet(
            "QLabel { background: #202124; border: 1px solid #555; }"
        )
        center_layout.addWidget(self.preview_label, 1)
        self.preview_summary = QLabel(center)
        self.preview_summary.setWordWrap(True)
        center_layout.addWidget(self.preview_summary)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        colors = QGroupBox(tr("imageTools.colors"), right)
        colors_layout = QVBoxLayout(colors)
        self.red_checkbox = QCheckBox(tr("imageTools.color.red"), colors)
        self.yellow_checkbox = QCheckBox(
            tr("imageTools.color.yellow"),
            colors,
        )
        self.red_checkbox.setChecked(True)
        self.yellow_checkbox.setChecked(True)
        colors_layout.addWidget(self.red_checkbox)
        colors_layout.addWidget(self.yellow_checkbox)
        right_layout.addWidget(colors)

        strength_form = QFormLayout()
        self.strength_combo = QComboBox(right)
        for message_id, value in (
            ("imageTools.strength.conservative", DetectionStrength.CONSERVATIVE),
            ("imageTools.strength.standard", DetectionStrength.STANDARD),
            ("imageTools.strength.loose", DetectionStrength.LOOSE),
        ):
            self.strength_combo.addItem(tr(message_id), value)
        self.strength_combo.setCurrentIndex(1)
        strength_form.addRow(
            tr("imageTools.strength"),
            self.strength_combo,
        )
        right_layout.addLayout(strength_form)

        right_layout.addWidget(QLabel(tr("imageTools.candidates"), right))
        self.candidate_list = QTreeWidget(right)
        self.candidate_list.setColumnCount(2)
        self.candidate_list.setHeaderLabels((
            tr("imageTools.candidate"),
            tr("imageTools.color"),
        ))
        right_layout.addWidget(self.candidate_list, 1)

        self.advanced_toggle = QToolButton(right)
        self.advanced_toggle.setText(tr("imageTools.advanced"))
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        right_layout.addWidget(self.advanced_toggle)
        self.advanced_panel = QWidget(right)
        advanced_form = QFormLayout(self.advanced_panel)
        self.radius_spin = QSpinBox(self.advanced_panel)
        self.radius_spin.setRange(1, 15)
        self.radius_spin.setValue(3)
        self.halo_spin = QSpinBox(self.advanced_panel)
        self.halo_spin.setRange(0, 5)
        self.halo_spin.setValue(0)
        self.grayscale_checkbox = QCheckBox(
            tr("imageTools.normalizeGrayscale"),
            self.advanced_panel,
        )
        advanced_form.addRow(tr("imageTools.inpaintRadius"), self.radius_spin)
        advanced_form.addRow(tr("imageTools.halo"), self.halo_spin)
        advanced_form.addRow(self.grayscale_checkbox)
        self.advanced_panel.setVisible(False)
        right_layout.addWidget(self.advanced_panel)

        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setSizes((250, 650, 280))

        footer = QHBoxLayout()
        self.undo_button = QPushButton(tr("imageTools.undo"), self)
        self.redo_button = QPushButton(tr("imageTools.redo"), self)
        footer.addWidget(self.undo_button)
        footer.addWidget(self.redo_button)
        footer.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel, self)
        self.apply_button = self.buttons.addButton(
            tr("imageTools.apply"),
            QDialogButtonBox.AcceptRole,
        )
        localize_dialog_buttons(self.buttons)
        footer.addWidget(self.buttons)
        outer.addLayout(footer)

        self.undo_action = QAction(self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.addAction(self.undo_action)
        self.redo_action = QAction(self)
        self.redo_action.setShortcuts((
            QKeySequence.Redo,
            QKeySequence("Ctrl+Shift+Z"),
        ))
        self.redo_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.addAction(self.redo_action)
        self._update_actions()

    def _connect_ui(self):
        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        self.target_list.currentItemChanged.connect(self._target_changed)
        self.target_list.itemChanged.connect(self._target_inclusion_changed)
        self.preview_mode.currentIndexChanged.connect(self._refresh_preview)
        self.preview_label.imageClicked.connect(self._preview_clicked)
        self.candidate_list.itemChanged.connect(self._candidate_changed)
        self.red_checkbox.toggled.connect(self._options_changed)
        self.yellow_checkbox.toggled.connect(self._options_changed)
        self.strength_combo.currentIndexChanged.connect(self._options_changed)
        self.radius_spin.valueChanged.connect(self._options_changed)
        self.halo_spin.valueChanged.connect(self._options_changed)
        self.grayscale_checkbox.toggled.connect(self._options_changed)
        self.advanced_toggle.toggled.connect(self._advanced_toggled)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action.triggered.connect(self.redo)
        self.buttons.rejected.connect(self.reject)
        self.apply_button.clicked.connect(self._apply)

    def _populate_scope(self):
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        self.scope_combo.addItem(tr("imageTools.scope.current"), "current")
        if len(self.selected_paths) > 1:
            self.scope_combo.addItem(
                tr(
                    "imageTools.scope.selected",
                    count=len(self.selected_paths),
                ),
                "selected",
            )
        self.scope_combo.blockSignals(False)

    def _scope_changed(self):
        scope = self.scope_combo.currentData()
        paths = (
            self.selected_paths
            if scope == "selected"
            else (self.current_path,)
        )
        self._set_targets(paths)

    def _set_targets(self, paths):
        self._generation += 1
        self._states = {
            path: _TargetState(path=path)
            for path in tuple(dict.fromkeys(paths))
        }
        self._items.clear()
        self.target_list.blockSignals(True)
        self.target_list.clear()
        for path, state in self._states.items():
            item = QTreeWidgetItem((os.path.basename(path), ""))
            item.setData(0, Qt.UserRole, path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked)
            item.setToolTip(0, path)
            self.target_list.addTopLevelItem(item)
            self._items[path] = item
            self._project_state(state)
        self.target_list.blockSignals(False)
        self._selection_history.clear()
        self._selection_redo.clear()
        if self.target_list.topLevelItemCount():
            self.target_list.setCurrentItem(self.target_list.topLevelItem(0))
        self._prepare_all()

    def _options(self):
        colors = set()
        if self.red_checkbox.isChecked():
            colors.add(FrameColor.RED)
        if self.yellow_checkbox.isChecked():
            colors.add(FrameColor.YELLOW)
        return FrameRemovalOptions(
            colors=frozenset(colors),
            strength=self.strength_combo.currentData(),
            inpaint_radius=self.radius_spin.value(),
            halo_dilate_iterations=self.halo_spin.value(),
            normalize_near_grayscale=self.grayscale_checkbox.isChecked(),
        )

    def _options_changed(self):
        if self._restoring_controls:
            return
        if not self.red_checkbox.isChecked() and not self.yellow_checkbox.isChecked():
            sender = self.sender()
            self._restoring_controls = True
            if sender in (self.red_checkbox, self.yellow_checkbox):
                sender.setChecked(True)
            self._restoring_controls = False
            return
        self._selection_history.clear()
        self._selection_redo.clear()
        self._prepare_all()

    def _prepare_all(self):
        self._generation += 1
        generation = self._generation
        options = self._options()
        for state in self._states.values():
            state.status = TargetStatus.PROCESSING
            state.result = None
            state.error = ""
            state.token = generation
            self._project_state(state)
            if self._asynchronous:
                worker = _PrepareWorker(
                    generation,
                    state.path,
                    self._processor,
                    options,
                )
                self._start_worker(worker, self._prepared)
            else:
                try:
                    result = self._processor.prepare(state.path, options)
                    error = None
                except Exception as caught:
                    result = None
                    error = caught
                self._prepared(generation, state.path, result, error)
        self._update_apply()

    def _start_worker(self, worker, callback):
        self._workers.add(worker)
        worker.signals.finished.connect(callback)
        worker.signals.finished.connect(
            lambda *_args, item=worker: self._workers.discard(item)
        )
        self._thread_pool.start(worker)

    def _prepared(self, generation, path, result, error):
        state = self._states.get(path)
        if state is None or state.token != generation:
            return
        state.error = "" if error is None else str(error)
        if error is not None:
            state.status = (
                TargetStatus.UNSUPPORTED
                if isinstance(error, UnsupportedImageToolTarget)
                else TargetStatus.FAILED
            )
            state.included = False
            state.result = None
        else:
            state.result = result
            if not result.candidates:
                state.status = TargetStatus.NO_FRAME
                state.included = False
            else:
                state.status = TargetStatus.READY
        self._project_state(state)
        if path == self._active_path:
            self._show_active_result()
        self._update_apply()

    def _project_state(self, state):
        item = self._items.get(state.path)
        if item is None:
            return
        signals_were_blocked = self.target_list.blockSignals(True)
        try:
            item.setText(1, tr("imageTools.status.%s" % state.status))
            item.setToolTip(1, state.error)
            item.setCheckState(
                0,
                Qt.Checked if state.included else Qt.Unchecked,
            )
        finally:
            self.target_list.blockSignals(signals_were_blocked)

    def _target_changed(self, current, _previous):
        self._active_path = (
            current.data(0, Qt.UserRole) if current is not None else None
        )
        self._show_active_result()

    def _target_inclusion_changed(self, item, _column):
        path = item.data(0, Qt.UserRole)
        state = self._states.get(path)
        if state is None:
            return
        requested = item.checkState(0) == Qt.Checked
        if requested and (
            state.result is None or state.result.replacement is None
        ):
            requested = False
            item.setCheckState(0, Qt.Unchecked)
        state.included = requested
        if state.status not in (
            TargetStatus.PROCESSING,
            TargetStatus.FAILED,
            TargetStatus.NO_FRAME,
        ):
            state.status = (
                TargetStatus.READY if requested else TargetStatus.EXCLUDED
            )
            self._project_state(state)
        self._update_apply()

    def _show_active_result(self):
        self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        state = self._states.get(self._active_path)
        if state is None or state.result is None:
            self.preview_summary.setText(
                tr("imageTools.preview.pending")
                if state is not None and state.status == TargetStatus.PROCESSING
                else (state.error if state is not None else "")
            )
            self._preview_source = None
            self.preview_label.clear()
            self.candidate_list.blockSignals(False)
            return
        result = state.result
        selected = set(result.selected_candidate_ids)
        for index, candidate in enumerate(result.candidates, 1):
            item = QTreeWidgetItem((
                tr("imageTools.candidateNumber", number=index),
                tr("imageTools.color.%s" % candidate.color.value),
            ))
            item.setData(0, Qt.UserRole, candidate.candidate_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                0,
                Qt.Checked
                if candidate.candidate_id in selected
                else Qt.Unchecked,
            )
            self.candidate_list.addTopLevelItem(item)
        self.candidate_list.blockSignals(False)
        self.preview_summary.setText(
            tr(
                "imageTools.preview.summary",
                detected=len(result.candidates),
                selected=len(selected),
            )
        )
        self._refresh_preview()

    def _candidate_changed(self, _item, _column):
        state = self._states.get(self._active_path)
        if state is None or state.result is None:
            return
        previous = tuple(state.result.selected_candidate_ids)
        selected = self._checked_candidate_ids()
        if selected == previous:
            return
        self._selection_history.append((state.path, previous, selected))
        self._selection_redo.clear()
        self._candidate_change_active = True
        try:
            self._render_selection(state.path, selected)
        finally:
            self._candidate_change_active = False
        self._update_actions()

    def _checked_candidate_ids(self):
        return tuple(
            item.data(0, Qt.UserRole)
            for index in range(self.candidate_list.topLevelItemCount())
            for item in (self.candidate_list.topLevelItem(index),)
            if item.checkState(0) == Qt.Checked
        )

    def _render_selection(self, path, candidate_ids):
        state = self._states[path]
        state.token += 1
        token = state.token
        prepared = state.result
        state.status = TargetStatus.PROCESSING
        self._project_state(state)
        if self._asynchronous:
            worker = _SelectionWorker(
                token,
                path,
                self._processor,
                prepared,
                candidate_ids,
            )
            self._start_worker(worker, self._selection_rendered)
        else:
            try:
                result = self._processor.select_candidates(
                    prepared,
                    candidate_ids,
                )
                error = None
            except Exception as caught:
                result = None
                error = caught
            self._selection_rendered(token, path, result, error)
        self._update_apply()

    def _selection_rendered(self, token, path, result, error):
        state = self._states.get(path)
        if state is None or state.token != token:
            return
        if error is not None:
            state.status = TargetStatus.FAILED
            state.error = str(error)
            state.included = False
        else:
            state.result = result
            state.error = ""
            if result.replacement is None:
                state.included = False
                state.status = TargetStatus.EXCLUDED
            else:
                state.status = (
                    TargetStatus.READY
                    if state.included
                    else TargetStatus.EXCLUDED
                )
        self._project_state(state)
        if path == self._active_path:
            if self._candidate_change_active:
                selected = len(result.selected_candidate_ids)
                self.preview_summary.setText(
                    tr(
                        "imageTools.preview.summary",
                        detected=len(result.candidates),
                        selected=selected,
                    )
                )
                self._refresh_preview()
            else:
                self._show_active_result()
        self._update_apply()

    def undo(self):
        if not self._selection_history:
            return
        change = self._selection_history.pop()
        self._selection_redo.append(change)
        path, previous, _selected = change
        self._render_selection(path, previous)
        self._update_actions()

    def redo(self):
        if not self._selection_redo:
            return
        change = self._selection_redo.pop()
        self._selection_history.append(change)
        path, _previous, selected = change
        self._render_selection(path, selected)
        self._update_actions()

    def _update_actions(self):
        can_undo = bool(self._selection_history)
        can_redo = bool(self._selection_redo)
        self.undo_button.setEnabled(can_undo)
        self.redo_button.setEnabled(can_redo)
        self.undo_action.setEnabled(can_undo)
        self.redo_action.setEnabled(can_redo)

    def _preview_clicked(self, x, y):
        state = self._states.get(self._active_path)
        if state is None or state.result is None:
            return
        hits = [
            candidate
            for candidate in state.result.candidates
            if candidate.x <= x < candidate.right
            and candidate.y <= y < candidate.bottom
        ]
        if not hits:
            return
        candidate = min(hits, key=lambda item: item.width * item.height)
        for index in range(self.candidate_list.topLevelItemCount()):
            item = self.candidate_list.topLevelItem(index)
            if item.data(0, Qt.UserRole) == candidate.candidate_id:
                item.setCheckState(
                    0,
                    Qt.Unchecked
                    if item.checkState(0) == Qt.Checked
                    else Qt.Checked,
                )
                break

    def _refresh_preview(self):
        state = self._states.get(self._active_path)
        if state is None or state.result is None:
            return
        result = state.result
        mode = self.preview_mode.currentData()
        if mode == "original":
            array = result.original_pixels
        elif mode == "mask":
            array = result.mask
        else:
            array = result.result_pixels
        pixmap = _array_pixmap(array)
        if mode != "mask":
            pixmap = _draw_candidates(pixmap, result)
        self._preview_source = (pixmap, result.original_pixels.shape[:2])
        self._project_preview_pixmap()

    def _project_preview_pixmap(self):
        if self._preview_source is None:
            return
        pixmap, shape = self._preview_source
        height, width = shape
        self.preview_label.set_preview_pixmap(
            pixmap,
            (width, height),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._project_preview_pixmap()

    def _advanced_toggled(self, checked):
        self.advanced_toggle.setArrowType(
            Qt.DownArrow if checked else Qt.RightArrow
        )
        self.advanced_panel.setVisible(checked)

    def _update_apply(self):
        included = [
            state
            for state in self._states.values()
            if state.included
        ]
        ready = bool(included) and all(
            state.status == TargetStatus.READY
            and state.result is not None
            and state.result.replacement is not None
            for state in included
        )
        self.apply_button.setEnabled(ready)

    def _apply(self):
        replacements = tuple(
            state.result.replacement
            for state in self._states.values()
            if state.included
            and state.status == TargetStatus.READY
            and state.result is not None
            and state.result.replacement is not None
        )
        if not replacements or not self.apply_button.isEnabled():
            return
        self.setEnabled(False)
        try:
            self.outcome = self._commit(replacements)
        except Exception as error:
            self.setEnabled(True)
            warning(
                self,
                tr("imageTools.commitFailedTitle"),
                tr("imageTools.commitFailed", error=str(error)),
                QMessageBox.Ok,
            )
            return
        self.setEnabled(True)
        self.accept()

    def reject(self):
        self._generation += 1
        for state in self._states.values():
            state.token += 1
        super().reject()


def _array_pixmap(array):
    array = np.ascontiguousarray(array)
    if array.ndim == 2:
        image = QImage(
            array.data,
            array.shape[1],
            array.shape[0],
            array.strides[0],
            QImage.Format_Grayscale8,
        ).copy()
    elif array.shape[2] == 4:
        rgba = cv2.cvtColor(array, cv2.COLOR_BGRA2RGBA)
        image = QImage(
            rgba.data,
            rgba.shape[1],
            rgba.shape[0],
            rgba.strides[0],
            QImage.Format_RGBA8888,
        ).copy()
    else:
        rgb = cv2.cvtColor(array, cv2.COLOR_BGR2RGB)
        image = QImage(
            rgb.data,
            rgb.shape[1],
            rgb.shape[0],
            rgb.strides[0],
            QImage.Format_RGB888,
        ).copy()
    return QPixmap.fromImage(image)


def _draw_candidates(pixmap, result):
    pixmap = QPixmap(pixmap)
    painter = QPainter(pixmap)
    selected = set(result.selected_candidate_ids)
    for candidate in result.candidates:
        color = (
            QColor("#ff3b30")
            if candidate.color is FrameColor.RED
            else QColor("#ffd60a")
        )
        pen = QPen(color, 2)
        if candidate.candidate_id not in selected:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawRect(
            candidate.x,
            candidate.y,
            max(1, candidate.width - 1),
            max(1, candidate.height - 1),
        )
    painter.end()
    return pixmap
