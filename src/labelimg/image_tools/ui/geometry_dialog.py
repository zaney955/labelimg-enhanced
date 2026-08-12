"""Preview and request geometry-changing image transforms."""

from __future__ import annotations

from dataclasses import dataclass
import os

import cv2
import numpy as np

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from labelimg.localization.runtime import localize_dialog_buttons, tr
from labelimg.image_tools.application.geometry_transform import (
    GeometryOperation,
    transform_pixels,
)
from labelimg.image_tools.infrastructure.image_codec import ImageFileCodec


@dataclass(frozen=True)
class GeometryTransformRequest:
    paths: tuple[str, ...]
    operation: GeometryOperation
    resize_percent: float = 100.0


class GeometryTransformDialog(QDialog):
    """Collect one explicit transform request with a real image preview."""

    def __init__(
        self,
        current_path,
        selected_paths=(),
        *,
        preselected=GeometryOperation.ROTATE_CLOCKWISE,
        parent=None,
    ):
        super().__init__(parent)
        self.current_path = os.path.abspath(os.fspath(current_path))
        selected = tuple(
            os.path.abspath(os.fspath(path)) for path in selected_paths
        )
        self.selected_paths = tuple(dict.fromkeys(selected))
        self.request = None
        self._codec = ImageFileCodec()
        self._loaded = self._codec.load(self.current_path)
        self._updating_size = False
        self.setWindowTitle(tr("geometry.workspace.title"))
        self.resize(900, 620)

        root = QVBoxLayout(self)
        controls = QFormLayout()
        self.scope_combo = QComboBox(self)
        self.scope_combo.addItem(tr("imageTools.scope.current"), "current")
        if len(self.selected_paths) > 1:
            self.scope_combo.addItem(
                tr("imageTools.scope.selected", count=len(self.selected_paths)),
                "selected",
            )
        controls.addRow(tr("geometry.workspace.scope"), self.scope_combo)

        self.operation_combo = QComboBox(self)
        for operation, text_id in (
            (GeometryOperation.ROTATE_CLOCKWISE, "geometry.rotateClockwise"),
            (
                GeometryOperation.ROTATE_COUNTERCLOCKWISE,
                "geometry.rotateCounterclockwise",
            ),
            (GeometryOperation.ROTATE_180, "geometry.rotate180"),
            (GeometryOperation.FLIP_HORIZONTAL, "geometry.flipHorizontal"),
            (GeometryOperation.FLIP_VERTICAL, "geometry.flipVertical"),
            (GeometryOperation.RESIZE, "geometry.resize"),
        ):
            self.operation_combo.addItem(tr(text_id), operation)
        index = self.operation_combo.findData(GeometryOperation(preselected))
        self.operation_combo.setCurrentIndex(max(0, index))
        controls.addRow(tr("geometry.workspace.operation"), self.operation_combo)
        root.addLayout(controls)

        body = QHBoxLayout()
        self.target_list = QListWidget(self)
        self.target_list.setMinimumWidth(220)
        body.addWidget(self.target_list, 0)
        preview_column = QVBoxLayout()
        self.preview_label = QLabel(self)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(440, 320)
        self.preview_label.setStyleSheet(
            "QLabel { background: #202428; border: 1px solid #5f686f; }"
        )
        preview_column.addWidget(self.preview_label, 1)
        self.preview_size_label = QLabel(self)
        self.preview_size_label.setAlignment(Qt.AlignCenter)
        preview_column.addWidget(self.preview_size_label)
        body.addLayout(preview_column, 1)
        root.addLayout(body, 1)

        self.resize_panel = QWidget(self)
        resize_form = QFormLayout(self.resize_panel)
        width, height = self._loaded.size
        self.width_spin = QSpinBox(self.resize_panel)
        self.width_spin.setRange(1, 200000)
        self.width_spin.setValue(width)
        self.height_spin = QSpinBox(self.resize_panel)
        self.height_spin.setRange(1, 200000)
        self.height_spin.setValue(height)
        self.percent_spin = QDoubleSpinBox(self.resize_panel)
        self.percent_spin.setRange(0.1, 1000.0)
        self.percent_spin.setDecimals(1)
        self.percent_spin.setSuffix(" %")
        self.percent_spin.setValue(100.0)
        resize_form.addRow(tr("geometry.workspace.width"), self.width_spin)
        resize_form.addRow(tr("geometry.workspace.height"), self.height_spin)
        resize_form.addRow(tr("geometry.workspace.percent"), self.percent_spin)
        root.addWidget(self.resize_panel)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            self,
        )
        localize_dialog_buttons(self.buttons)
        self.apply_button = self.buttons.button(QDialogButtonBox.Ok)
        self.apply_button.setText(tr("imageTools.apply"))
        root.addWidget(self.buttons)

        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        self.operation_combo.currentIndexChanged.connect(self._refresh)
        self.percent_spin.valueChanged.connect(self._percent_changed)
        self.width_spin.valueChanged.connect(self._width_changed)
        self.height_spin.valueChanged.connect(self._height_changed)
        self.buttons.accepted.connect(self._accept_request)
        self.buttons.rejected.connect(self.reject)
        self._scope_changed()

    def _paths(self):
        return (
            self.selected_paths
            if self.scope_combo.currentData() == "selected"
            else (self.current_path,)
        )

    def _scope_changed(self):
        self.target_list.clear()
        self.target_list.addItems(
            os.path.basename(path) for path in self._paths()
        )
        current_only = self.scope_combo.currentData() == "current"
        self.width_spin.setEnabled(current_only)
        self.height_spin.setEnabled(current_only)
        self._refresh()

    def _percent_changed(self, value):
        if self._updating_size:
            return
        width, height = self._loaded.size
        self._updating_size = True
        self.width_spin.setValue(max(1, round(width * value / 100.0)))
        self.height_spin.setValue(max(1, round(height * value / 100.0)))
        self._updating_size = False
        self._refresh()

    def _width_changed(self, value):
        if self._updating_size:
            return
        width, height = self._loaded.size
        self._updating_size = True
        percent = 100.0 * value / width
        self.percent_spin.setValue(percent)
        self.height_spin.setValue(max(1, round(height * percent / 100.0)))
        self._updating_size = False
        self._refresh()

    def _height_changed(self, value):
        if self._updating_size:
            return
        width, height = self._loaded.size
        self._updating_size = True
        percent = 100.0 * value / height
        self.percent_spin.setValue(percent)
        self.width_spin.setValue(max(1, round(width * percent / 100.0)))
        self._updating_size = False
        self._refresh()

    def _output_size(self):
        width, height = self._loaded.size
        percent = self.percent_spin.value() / 100.0
        return max(1, round(width * percent)), max(1, round(height * percent))

    def _refresh(self):
        operation = self.operation_combo.currentData()
        resize = operation is GeometryOperation.RESIZE
        self.resize_panel.setVisible(resize)
        output_size = self._output_size() if resize else None
        pixels, size = transform_pixels(
            self._loaded.pixels,
            operation,
            output_size=output_size,
        )
        pixmap = _array_pixmap(pixels)
        self.preview_label.setPixmap(pixmap.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        ))
        self.preview_size_label.setText("%d × %d" % size)

    def _accept_request(self):
        self.request = GeometryTransformRequest(
            paths=tuple(self._paths()),
            operation=self.operation_combo.currentData(),
            resize_percent=self.percent_spin.value(),
        )
        self.accept()


def _array_pixmap(array):
    array = np.ascontiguousarray(array)
    if array.ndim == 2:
        image = QImage(
            array.data,
            array.shape[1],
            array.shape[0],
            array.strides[0],
            QImage.Format_Grayscale8,
        )
    elif array.shape[2] == 3:
        rgb = cv2.cvtColor(array, cv2.COLOR_BGR2RGB)
        image = QImage(
            rgb.data,
            rgb.shape[1],
            rgb.shape[0],
            rgb.strides[0],
            QImage.Format_RGB888,
        )
    else:
        rgba = cv2.cvtColor(array, cv2.COLOR_BGRA2RGBA)
        image = QImage(
            rgba.data,
            rgba.shape[1],
            rgba.shape[0],
            rgba.strides[0],
            QImage.Format_RGBA8888,
        )
    return QPixmap.fromImage(image.copy())
