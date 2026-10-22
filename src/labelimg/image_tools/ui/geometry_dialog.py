"""Preview and request geometry-changing image transforms."""

from __future__ import annotations

from labelimg.ui.presentation import present_dialog, section

from dataclasses import dataclass
import os

import cv2
import numpy as np

from PyQt5.QtCore import QEvent, QTimer, Qt
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
    QSizePolicy,
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

    PREVIEW_MAX_PIXELS = 1_500_000

    def __init__(
        self,
        current_path,
        selected_paths=(),
        *,
        workspace_paths=(),
        preselected=GeometryOperation.ROTATE_CLOCKWISE,
        parent=None,
    ):
        super().__init__(parent)
        self.current_path = os.path.abspath(os.fspath(current_path))
        selected = tuple(
            os.path.abspath(os.fspath(path)) for path in selected_paths
        )
        self.selected_paths = tuple(dict.fromkeys(selected))
        workspace = tuple(
            os.path.abspath(os.fspath(path)) for path in workspace_paths
        )
        self.workspace_paths = tuple(dict.fromkeys(workspace))
        self.request = None
        self._codec = ImageFileCodec()
        self._preview = self._codec.load_preview(
            self.current_path,
            max_pixels=self.PREVIEW_MAX_PIXELS,
        )
        self._source_size = self._preview.size
        self._updating_size = False
        self._preview_failed = False
        self.setWindowTitle(tr("geometry.workspace.title"))
        self.resize(980, 620)

        root = QVBoxLayout(self)
        controls = QFormLayout()
        self.scope_combo = QComboBox(self)
        self.scope_combo.addItem(tr("imageTools.scope.current"), "current")
        if len(self.selected_paths) > 1:
            self.scope_combo.addItem(
                tr("imageTools.scope.selected", count=len(self.selected_paths)),
                "selected",
            )
        if len(self.workspace_paths) > 1:
            self.scope_combo.addItem(
                tr("imageTools.scope.workspace", count=len(self.workspace_paths)),
                "workspace",
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
        scope_panel = section("ui.section.transform", controls)

        body = QHBoxLayout()
        self.target_list = QListWidget(self)
        self.target_list.setMinimumHeight(100)
        preview_column = QVBoxLayout()
        self.preview_label = QLabel(self)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(400, 300)
        self.preview_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview_label.setStyleSheet(
            "QLabel { background: #202428; border: 1px solid #5f686f; }"
        )
        preview_column.addWidget(self.preview_label, 1)
        self.preview_size_label = QLabel(self)
        self.preview_size_label.setAlignment(Qt.AlignCenter)
        preview_column.addWidget(self.preview_size_label)
        body.addWidget(section("ui.section.preview", preview_column, stretch=1), 1)

        self.resize_panel = QWidget(self)
        resize_form = QFormLayout(self.resize_panel)
        width, height = self._source_size
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
        sidebar = QWidget(self)
        sidebar.setFixedWidth(310)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(12)
        sidebar_layout.addWidget(scope_panel)
        scope_panel.layout().addWidget(self.resize_panel)
        sidebar_layout.addWidget(section("ui.section.targets", self.target_list, stretch=1), 1)
        body.addWidget(sidebar)
        root.addLayout(body, 1)

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
        present_dialog(self, primary=self.apply_button, scroll=True, icon="geometry-transform")
        self.preview_label.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.preview_label and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._refresh)
        return super().eventFilter(watched, event)

    def _paths(self):
        scope = self.scope_combo.currentData()
        if scope == "selected":
            return self.selected_paths
        if scope == "workspace":
            return self.workspace_paths or (self.current_path,)
        return (self.current_path,)

    def _scope_changed(self):
        paths = self._paths()
        self.target_list.clear()
        self.target_list.addItems(
            os.path.basename(path) for path in paths
        )
        for index, path in enumerate(paths):
            self.target_list.item(index).setToolTip(path)
        current_only = self.scope_combo.currentData() == "current"
        self.width_spin.setEnabled(current_only)
        self.height_spin.setEnabled(current_only)
        self._refresh()

    def _percent_changed(self, value):
        if self._updating_size:
            return
        width, height = self._source_size
        self._updating_size = True
        self.width_spin.setValue(max(1, round(width * value / 100.0)))
        self.height_spin.setValue(max(1, round(height * value / 100.0)))
        self._updating_size = False
        self._refresh()

    def _width_changed(self, value):
        if self._updating_size:
            return
        width, height = self._source_size
        self._updating_size = True
        percent = 100.0 * value / width
        self.percent_spin.setValue(percent)
        self.height_spin.setValue(max(1, round(height * percent / 100.0)))
        self._updating_size = False
        self._refresh()

    def _height_changed(self, value):
        if self._updating_size:
            return
        width, height = self._source_size
        self._updating_size = True
        percent = 100.0 * value / height
        self.percent_spin.setValue(percent)
        self.width_spin.setValue(max(1, round(width * percent / 100.0)))
        self._updating_size = False
        self._refresh()

    def _output_size(self):
        width, height = self._source_size
        percent = self.percent_spin.value() / 100.0
        return max(1, round(width * percent)), max(1, round(height * percent))

    def _refresh(self):
        operation = self.operation_combo.currentData()
        resize = operation is GeometryOperation.RESIZE
        self.resize_panel.setVisible(resize)
        output_size = self._output_size() if resize else None
        try:
            if resize:
                pixels = self._preview.pixels
                size = output_size
            else:
                pixels, _preview_size = transform_pixels(
                    self._preview.pixels,
                    operation,
                )
                width, height = self._source_size
                size = (
                    (height, width)
                    if operation in (
                        GeometryOperation.ROTATE_CLOCKWISE,
                        GeometryOperation.ROTATE_COUNTERCLOCKWISE,
                    )
                    else (width, height)
                )
            pixmap = _array_pixmap(pixels)
            self.preview_label.setPixmap(pixmap.scaled(
                self.preview_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            ))
            self.preview_size_label.setText("%d × %d" % size)
        except Exception as error:
            self._preview_failed = True
            self.preview_label.setText(
                tr(
                    "imageTools.preview.failed",
                    path=os.path.basename(self.current_path),
                    error=error,
                )
            )
            self.preview_size_label.clear()
            self.apply_button.setEnabled(False)
            return
        self._preview_failed = False
        self.apply_button.setEnabled(True)

    def _accept_request(self):
        if self._preview_failed:
            return
        self.request = GeometryTransformRequest(
            paths=tuple(self._paths()),
            operation=self.operation_combo.currentData(),
            resize_percent=self.percent_spin.value(),
        )
        self.accept()


def _array_pixmap(array):
    return QPixmap.fromImage(_array_qimage(array))


def _array_qimage(array):
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
    return image.copy()
