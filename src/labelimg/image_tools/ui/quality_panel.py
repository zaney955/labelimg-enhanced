"""Scope/policy dialog and nonmodal result panel for quality checks."""

from __future__ import annotations


from labelimg.ui.presentation import (
    present_surface,
    present_dialog,
    present_table,
    role,
    section,
    empty_table_hint,
)

from dataclasses import dataclass
import os
import threading

from PyQt5.QtCore import QEvent, QObject, QSize, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QSpinBox,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from labelimg.localization.runtime import language_changed, localize_dialog_buttons, tr
from labelimg.image_tools.domain.quality import ImageQualityPolicy
from labelimg.ui.panels import PANEL_STYLE, panel_context, panel_list
from labelimg.ui.theme import theme_style
from labelimg.ui.icons import icon


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
        workspace_count = len(self.workspace_paths or (self.current_path,))
        self.scope_combo.addItem(
            tr("imageTools.scope.workspace", count=workspace_count),
            "workspace",
        )
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
        dimensions = QFormLayout()
        dimensions.addRow(tr("quality.minWidth"), self.min_width)
        dimensions.addRow(tr("quality.minHeight"), self.min_height)
        dimensions.addRow(tr("quality.maxAspect"), self.max_aspect)
        thresholds = QFormLayout()
        thresholds.addRow(tr("quality.blurThreshold"), self.blur)
        thresholds.addRow(tr("quality.darkThreshold"), self.dark)
        thresholds.addRow(tr("quality.overexposedThreshold"), self.overexposed)
        layout.addLayout(form)
        self.custom_toggle = QCheckBox(tr("quality.customize"))
        layout.addWidget(self.custom_toggle)
        self.parameter_box = QWidget()
        parameters = QVBoxLayout(self.parameter_box)
        parameters.setContentsMargins(0, 0, 0, 0)
        parameters.addWidget(section("ui.section.resolution", dimensions), 1)
        parameters.addWidget(section("ui.section.thresholds", thresholds), 1)
        layout.addWidget(self.parameter_box)
        self.parameter_box.hide()
        self.custom_toggle.toggled.connect(self.parameter_box.setVisible)
        for field, key in ((self.min_width, 'quality.minWidth'),
                           (self.min_height, 'quality.minHeight'),
                           (self.max_aspect, 'quality.maxAspect'),
                           (self.blur, 'quality.blurThreshold'),
                           (self.dark, 'quality.darkThreshold'),
                           (self.overexposed, 'quality.overexposedThreshold')):
            field.setAccessibleName(tr(key))
            field.valueChanged.connect(lambda _value: self.custom_toggle.setChecked(True))
        for field in (self.min_width, self.min_height):
            field.setSuffix(' px')
        explanation = QLabel(tr('quality.thresholdHelp'))
        explanation.setWordWrap(True)
        role(explanation, 'supporting')
        parameters.addWidget(explanation)
        self.policy_summary = QLabel(tr('quality.standardSummary'))
        self.policy_summary.setWordWrap(True)
        role(self.policy_summary, 'supporting')
        layout.addWidget(self.policy_summary)
        self.custom_toggle.toggled.connect(self._toggle_custom)
        self.note = QLabel(tr("ui.quality.analysis"))
        self.note.setToolTip(tr("quality.analysisOnly"))
        self.note.setWordWrap(True)
        role(self.note, "supporting")
        layout.addWidget(self.note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        localize_dialog_buttons(self.buttons)
        self.buttons.button(QDialogButtonBox.Ok).setText(tr('quality.start'))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        present_dialog(
            self,
            primary=self.buttons.button(QDialogButtonBox.Ok),
            minimum_width=620,
            scroll=True,
            icon="image-quality",
        )
        field_labels = [form.labelForField(field) for form, fields in (
            (dimensions, (self.min_width, self.min_height, self.max_aspect)),
            (thresholds, (self.blur, self.dark, self.overexposed)),
        ) for field in fields]
        label_width = max(label.sizeHint().width() for label in field_labels)
        for label in field_labels:
            label.setMinimumWidth(label_width)

    def _toggle_custom(self, enabled):
        self.policy_summary.setVisible(not enabled)
        QTimer.singleShot(0, self._fit_policy)

    def _fit_policy(self):
        for area in self.findChildren(QScrollArea):
            area.widget().layout().activate()
            area.updateGeometry()
        self.layout().invalidate()
        self.layout().activate()
        available = self.screen().availableGeometry().adjusted(12, 12, -12, -12)
        self.resize(self.width(), min(self.layout().totalSizeHint().height(), available.height()))

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
            ) if self.custom_toggle.isChecked() else standard,
        )
        super().accept()


class ImageQualityPanel(QWidget):
    checkRequested = pyqtSignal()
    refreshRequested = pyqtSignal()
    clearRequested = pyqtSignal()
    openRequested = pyqtSignal(str)
    summaryChanged = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results = ()
        self._failure = None
        self.setProperty("uiRole", "panelBody")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 0, 1, 1)
        layout.setSpacing(0)
        context, context_layout = panel_context()
        self.context = context
        self.summary = QLabel()
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(
            (tr("quality.file"), tr("quality.findings"))
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.table.horizontalHeader().setStretchLastSection(True)
        controls = QHBoxLayout()
        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(icon("refresh"))
        self.clear_button = QToolButton()
        self.clear_button.setIcon(icon("clear-results"))
        for button in (self.refresh_button, self.clear_button):
            button.setIconSize(QSize(18, 18))
            button.setFixedSize(26, 26)
        self.refresh_button.clicked.connect(self.refreshRequested)
        self.clear_button.clicked.connect(self.clearRequested)
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.clear_button)
        controls.insertWidget(0, self.summary, 1)
        context_layout.addLayout(controls)
        self.start_button = QPushButton()
        self.start_button.clicked.connect(self.checkRequested)
        layout.addWidget(context)
        result_area = panel_list(self.table)
        result_area.setMinimumHeight(70)
        layout.addWidget(result_area, 1)
        self.empty_hint = empty_table_hint(self.table, "ui.quality.empty")
        empty_layout = self.table.viewport().layout()
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(4)
        self.empty_hint.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        empty_layout.insertStretch(0, 1)
        empty_layout.addWidget(self.start_button, 0, Qt.AlignHCenter)
        empty_layout.addStretch(1)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        present_surface(
            self,
            PANEL_STYLE + theme_style("""
            QTableView { border: none; border-radius: 0; background: ${surface}; }
            QHeaderView::section { padding: 6px; }
        """),
        )
        present_table(self.table, path_columns=(0,), stretch_path=True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 170)
        role(self.summary, "supporting")

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange and hasattr(self, "refresh_button"):
            for button in (self.refresh_button, self.clear_button):
                button.setEnabled(self.isEnabled() and bool(self._results))

    @property
    def result_paths(self):
        return tuple(result.path for result in self._results)

    def set_results(self, results):
        self._failure = None
        self.summary.setToolTip('')
        self._results = tuple(results)
        self.table.setRowCount(len(self._results))
        self.empty_hint.setVisible(not self._results)
        self.empty_hint.setText(tr('ui.quality.empty'))
        self.empty_hint.setToolTip('')
        self.context.setVisible(bool(self._results))
        self.table.horizontalHeader().setVisible(bool(self._results))
        self.start_button.setVisible(not self._results)
        self.refresh_button.setEnabled(self.isEnabled() and bool(self._results))
        self.clear_button.setEnabled(self.isEnabled() and bool(self._results))
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
            finding_item.setToolTip(
                "\n".join(quality_finding_text(item) for item in result.findings)
            )
            self.table.setItem(row, 0, file_item)
            self.table.setItem(row, 1, finding_item)
        failed = sum(any(item.code == 'unreadable' for item in result.findings) for result in self._results)
        if not self._results:
            text = tr('quality.notChecked')
        elif failed:
            text = tr('quality.failedCount', total=len(self._results), issues=issue_count, failed=failed)
        elif not issue_count:
            text = tr('quality.allPassed', total=len(self._results))
        else:
            text = tr('quality.summary', total=len(self._results), issues=issue_count)
        self.summary.setText(text)
        self.summary.setWordWrap(True)
        self.summaryChanged.emit(len(self._results), issue_count)

    def set_failure(self, error):
        self._failure = str(error)
        self.summary.setText(tr('quality.failedTitle'))
        self.summary.setToolTip(tr('quality.failed', error=self._failure))
        if not self._results:
            self.empty_hint.setText(tr('quality.failedTitle'))
            self.empty_hint.setToolTip(tr('quality.failed', error=self._failure))
        self.start_button.setVisible(not self._results)

    def retranslate_ui(self, _language=None):
        self.table.setHorizontalHeaderLabels(
            (tr("quality.file"), tr("quality.findings"))
        )
        self.refresh_button.setText(tr("quality.refresh"))
        self.clear_button.setText(tr("quality.clear"))
        self.start_button.setText(tr('quality.start'))
        for button in (self.refresh_button, self.clear_button):
            button.setToolTip(button.text())
            button.setAccessibleName(button.text())
        failure = self._failure
        self.set_results(self._results)
        if failure is not None:
            self.set_failure(failure)

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
        return tr(
            "quality.reasonUnreadable",
            name=name,
            detail=finding.error if hasattr(finding, "error") else finding.explanation,
        )
    return tr(
        "quality.reasonMetric",
        name=name,
        metric="%.2f" % finding.metric,
        threshold="%.2f" % finding.threshold,
    )
