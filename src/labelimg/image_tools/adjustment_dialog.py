"""Modal workspace for composable pixel corrections."""

from __future__ import annotations

from dataclasses import dataclass
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from labelimg.i18n import localize_dialog_buttons, tr
from labelimg.image_tools.adjustment import (
    ImageAdjustmentOptions,
    ImageAdjustmentProcessor,
)
from labelimg.image_tools.geometry_dialog import _array_pixmap


@dataclass(frozen=True)
class ImageAdjustmentRequest:
    paths: tuple[str, ...]
    options: ImageAdjustmentOptions


class ImageAdjustmentDialog(QDialog):
    def __init__(self, current_path, selected_paths=(), parent=None):
        super().__init__(parent)
        self.current_path = os.path.abspath(os.fspath(current_path))
        self.selected_paths = tuple(dict.fromkeys(
            os.path.abspath(os.fspath(path)) for path in selected_paths
        ))
        self.request = None
        self._processor = ImageAdjustmentProcessor()
        self._restoring = False
        self._history = []
        self._redo = []
        self._last_options = ImageAdjustmentOptions()
        self.setWindowTitle(tr("adjustment.title"))
        self.resize(920, 640)

        root = QVBoxLayout(self)
        top = QFormLayout()
        self.scope_combo = QComboBox(self)
        self.scope_combo.addItem(tr("imageTools.scope.current"), "current")
        if len(self.selected_paths) > 1:
            self.scope_combo.addItem(
                tr("imageTools.scope.selected", count=len(self.selected_paths)),
                "selected",
            )
        top.addRow(tr("geometry.workspace.scope"), self.scope_combo)
        root.addLayout(top)

        body = QHBoxLayout()
        self.target_list = QListWidget(self)
        self.target_list.setMinimumWidth(220)
        body.addWidget(self.target_list)
        self.preview_label = QLabel(self)
        self.preview_label.setMinimumSize(460, 340)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            "QLabel { background: #202428; border: 1px solid #5f686f; }"
        )
        body.addWidget(self.preview_label, 1)
        root.addLayout(body, 1)

        controls = QFormLayout()
        self.brightness_spin = QSpinBox(self)
        self.brightness_spin.setRange(-100, 100)
        self.brightness_spin.setSuffix(" %")
        self.contrast_spin = QDoubleSpinBox(self)
        self.contrast_spin.setRange(0.1, 3.0)
        self.contrast_spin.setSingleStep(0.1)
        self.contrast_spin.setValue(1.0)
        self.gamma_spin = QDoubleSpinBox(self)
        self.gamma_spin.setRange(0.1, 5.0)
        self.gamma_spin.setSingleStep(0.1)
        self.gamma_spin.setValue(1.0)
        self.auto_contrast_checkbox = QCheckBox(tr("adjustment.autoContrast"), self)
        self.grayscale_checkbox = QCheckBox(tr("adjustment.grayscale"), self)
        controls.addRow(tr("adjustment.brightness"), self.brightness_spin)
        controls.addRow(tr("adjustment.contrast"), self.contrast_spin)
        controls.addRow(tr("adjustment.gamma"), self.gamma_spin)
        controls.addRow(self.auto_contrast_checkbox)
        controls.addRow(self.grayscale_checkbox)
        root.addLayout(controls)

        history_row = QHBoxLayout()
        self.undo_button = QPushButton(tr("action.undo"), self)
        self.redo_button = QPushButton(tr("action.redo"), self)
        history_row.addWidget(self.undo_button)
        history_row.addWidget(self.redo_button)
        history_row.addStretch(1)
        root.addLayout(history_row)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            self,
        )
        localize_dialog_buttons(self.buttons)
        self.apply_button = self.buttons.button(QDialogButtonBox.Ok)
        self.apply_button.setText(tr("imageTools.apply"))
        root.addWidget(self.buttons)

        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        for control in (
            self.brightness_spin,
            self.contrast_spin,
            self.gamma_spin,
        ):
            control.valueChanged.connect(self._controls_changed)
        self.auto_contrast_checkbox.toggled.connect(self._controls_changed)
        self.grayscale_checkbox.toggled.connect(self._controls_changed)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.buttons.accepted.connect(self._accept_request)
        self.buttons.rejected.connect(self.reject)
        self._scope_changed()
        self._update_history_buttons()

    def _paths(self):
        return (
            self.selected_paths
            if self.scope_combo.currentData() == "selected"
            else (self.current_path,)
        )

    def _scope_changed(self):
        self.target_list.clear()
        self.target_list.addItems(os.path.basename(path) for path in self._paths())
        self._refresh_preview()

    def _options(self):
        return ImageAdjustmentOptions(
            brightness=self.brightness_spin.value(),
            contrast=self.contrast_spin.value(),
            gamma=self.gamma_spin.value(),
            auto_contrast=self.auto_contrast_checkbox.isChecked(),
            grayscale=self.grayscale_checkbox.isChecked(),
        )

    def _controls_changed(self, _value=None):
        if self._restoring:
            return
        current = self._options()
        if current == self._last_options:
            return
        self._history.append(self._last_options)
        self._redo.clear()
        self._last_options = current
        self._refresh_preview()
        self._update_history_buttons()

    def _restore_options(self, options):
        self._restoring = True
        try:
            self.brightness_spin.setValue(options.brightness)
            self.contrast_spin.setValue(options.contrast)
            self.gamma_spin.setValue(options.gamma)
            self.auto_contrast_checkbox.setChecked(options.auto_contrast)
            self.grayscale_checkbox.setChecked(options.grayscale)
        finally:
            self._restoring = False
        self._last_options = options
        self._refresh_preview()
        self._update_history_buttons()

    def undo(self):
        if not self._history:
            return
        previous = self._history.pop()
        self._redo.append(self._last_options)
        self._restore_options(previous)

    def redo(self):
        if not self._redo:
            return
        following = self._redo.pop()
        self._history.append(self._last_options)
        self._restore_options(following)

    def _refresh_preview(self):
        prepared = self._processor.prepare(self.current_path, self._options())
        pixmap = _array_pixmap(prepared.result_pixels)
        self.preview_label.setPixmap(pixmap.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        ))
        self.apply_button.setEnabled(prepared.changed)

    def _update_history_buttons(self):
        self.undo_button.setEnabled(bool(self._history))
        self.redo_button.setEnabled(bool(self._redo))

    def _accept_request(self):
        self.request = ImageAdjustmentRequest(
            paths=tuple(self._paths()),
            options=self._options(),
        )
        self.accept()
