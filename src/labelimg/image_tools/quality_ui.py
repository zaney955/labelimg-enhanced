"""Scope/policy dialog and nonmodal result panel for quality checks."""

from __future__ import annotations

from dataclasses import dataclass
import os
import threading

from PyQt5.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from labelimg.i18n import language_changed, localize_dialog_buttons, tr
from labelimg.image_tools.quality import ImageQualityPolicy


@dataclass(frozen=True)
class ImageQualityRequest:
    paths: tuple[str, ...]
    policy: ImageQualityPolicy


class ImageQualityDialog(QDialog):
    def __init__(
        self,
        current_path,
        selected_paths,
        workspace_paths,
        parent=None,
    ):
        super().__init__(parent)
        self.current_path = os.path.abspath(os.fspath(current_path))
        self.selected_paths = _normalized_paths(selected_paths)
        self.workspace_paths = _normalized_paths(workspace_paths)
        self.request = None
        self.setWindowTitle(tr("quality.dialogTitle"))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.scope_combo = QComboBox()
        self.scope_combo.addItem(tr("imageTools.scopeCurrent"), "current")
        self.scope_combo.addItem(tr("imageTools.scopeSelected"), "selected")
        self.scope_combo.addItem(tr("imageTools.scopeWorkspace"), "workspace")
        self.scope_combo.setCurrentIndex(2)
        form.addRow(tr("imageTools.scope"), self.scope_combo)
        standard = ImageQualityPolicy.standard()
        self.min_width = QSpinBox()
        self.min_width.setRange(1, 100000)
        self.min_width.setValue(standard.min_width)
        self.min_height = QSpinBox()
        self.min_height.setRange(1, 100000)
        self.min_height.setValue(standard.min_height)
        self.max_aspect = QDoubleSpinBox()
        self.max_aspect.setRange(1.0, 100.0)
        self.max_aspect.setDecimals(2)
        self.max_aspect.setValue(standard.max_aspect_ratio)
        self.blur = QDoubleSpinBox()
        self.blur.setRange(-1.0, 1000000.0)
        self.blur.setValue(standard.blur_variance)
        self.dark = QDoubleSpinBox()
        self.dark.setRange(0.0, 255.0)
        self.dark.setValue(standard.dark_mean)
        self.overexposed = QDoubleSpinBox()
        self.overexposed.setRange(0.0, 255.0)
        self.overexposed.setValue(standard.overexposed_mean)
        form.addRow(tr("quality.minWidth"), self.min_width)
        form.addRow(tr("quality.minHeight"), self.min_height)
        form.addRow(tr("quality.maxAspect"), self.max_aspect)
        form.addRow(tr("quality.blurThreshold"), self.blur)
        form.addRow(tr("quality.darkThreshold"), self.dark)
        form.addRow(tr("quality.overexposedThreshold"), self.overexposed)
        layout.addLayout(form)
        self.note = QLabel(tr("quality.analysisOnly"))
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        localize_dialog_buttons(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def accept(self):
        scope = self.scope_combo.currentData()
        paths = {
            "current": (self.current_path,),
            "selected": self.selected_paths or (self.current_path,),
            "workspace": self.workspace_paths or (self.current_path,),
        }[scope]
        standard = ImageQualityPolicy.standard()
        self.request = ImageQualityRequest(
            paths,
            standard.with_overrides(
                min_width=self.min_width.value(),
                min_height=self.min_height.value(),
                max_aspect_ratio=self.max_aspect.value(),
                blur_variance=self.blur.value(),
                dark_mean=self.dark.value(),
                overexposed_mean=self.overexposed.value(),
            ),
        )
        super().accept()


class ImageQualityPanel(QWidget):
    refreshRequested = pyqtSignal()
    clearRequested = pyqtSignal()
    openRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results = ()
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels((
            tr("quality.file"), tr("quality.findings")
        ))
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        self.refresh_button = QPushButton(tr("quality.refresh"))
        self.clear_button = QPushButton(tr("quality.clear"))
        self.refresh_button.clicked.connect(self.refreshRequested)
        self.clear_button.clicked.connect(self.clearRequested)
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.clear_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    @property
    def result_paths(self):
        return tuple(result.path for result in self._results)

    def set_results(self, results):
        self._results = tuple(results)
        self.table.setRowCount(len(self._results))
        issue_count = 0
        for row, result in enumerate(self._results):
            codes = tuple(item.code for item in result.findings)
            issue_count += bool(codes)
            file_item = QTableWidgetItem(os.path.basename(result.path))
            file_item.setData(Qt.UserRole, result.path)
            file_item.setToolTip(result.path)
            finding_item = QTableWidgetItem(
                ", ".join(quality_finding_name(code) for code in codes)
                or tr("quality.passed")
            )
            finding_item.setData(Qt.UserRole, codes)
            finding_item.setToolTip("\n".join(
                quality_finding_text(item) for item in result.findings
            ))
            self.table.setItem(row, 0, file_item)
            self.table.setItem(row, 1, finding_item)
        self.summary.setText(tr(
            "quality.summary", total=len(self._results), issues=issue_count
        ))

    def retranslate_ui(self, _language=None):
        self.table.setHorizontalHeaderLabels((
            tr("quality.file"), tr("quality.findings")
        ))
        self.refresh_button.setText(tr("quality.refresh"))
        self.clear_button.setText(tr("quality.clear"))
        self.set_results(self._results)

    def clear(self):
        self.set_results(())

    def _open_row(self, row, _column):
        item = self.table.item(row, 0)
        if item is not None and item.data(Qt.UserRole):
            self.openRequested.emit(item.data(Qt.UserRole))


class ImageQualityWorker(QObject):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    canceled = pyqtSignal()
    progressChanged = pyqtSignal(int, int)

    def __init__(self, scanner, request):
        super().__init__()
        self._scanner = scanner
        self.request = request
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    @pyqtSlot()
    def run(self):
        try:
            results = self._scanner.scan_many(
                self.request.paths,
                self.request.policy,
                should_cancel=self._cancel.is_set,
                progress=self.progressChanged.emit,
            )
        except Exception as error:
            self.failed.emit(str(error))
            return
        if results is None or self._cancel.is_set():
            self.canceled.emit()
        else:
            self.completed.emit(results)


def _normalized_paths(paths):
    result = []
    seen = set()
    for path in paths:
        absolute = os.path.abspath(os.fspath(path))
        key = os.path.normcase(absolute)
        if key not in seen:
            seen.add(key)
            result.append(absolute)
    return tuple(result)


def quality_finding_name(code):
    message_id = {
        "unreadable": "quality.unreadable",
        "low_resolution": "quality.lowResolution",
        "aspect_anomaly": "quality.aspectAnomaly",
        "blur": "quality.blur",
        "dark": "quality.dark",
        "overexposed": "quality.overexposed",
    }.get(code)
    return tr(message_id) if message_id is not None else str(code)


def quality_finding_text(finding):
    name = quality_finding_name(finding.code)
    if finding.metric is None or finding.threshold is None:
        return tr("quality.reasonUnreadable", name=name, detail=finding.error if hasattr(finding, "error") else finding.explanation)
    return tr(
        "quality.reasonMetric",
        name=name,
        metric="%.2f" % finding.metric,
        threshold="%.2f" % finding.threshold,
    )
