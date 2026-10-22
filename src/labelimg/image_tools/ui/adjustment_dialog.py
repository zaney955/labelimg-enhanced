"""Modal workspace for composable pixel corrections."""

from __future__ import annotations

from labelimg.ui.theme import apply_theme_style, theme_style


from labelimg.ui.presentation import present_dialog, section

from dataclasses import dataclass
import math
import os

import cv2
import numpy as np
from PyQt5.QtCore import QEvent, QTimer, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from labelimg.localization.runtime import localize_dialog_buttons, tr
from labelimg.image_tools.application.adjustment import (
    ImageAdjustmentOptions,
    apply_adjustments,
    suggest_auto_adjustment,
)
from labelimg.image_tools.infrastructure.image_codec import ImageFileCodec
from labelimg.image_tools.ui.geometry_dialog import _array_pixmap


@dataclass(frozen=True)
class ImageAdjustmentRequest:
    paths: tuple[str, ...]
    options: ImageAdjustmentOptions


@dataclass(frozen=True)
class _AdjustmentPreview:
    pixels: np.ndarray
    source_size: tuple[int, int]


class _AdjustmentSliderRow(QWidget):
    """Theme-adaptive labeled slider with a stable numeric value badge."""

    def __init__(
        self,
        label,
        minimum,
        maximum,
        value,
        formatter,
        *,
        page_step,
        parent=None,
    ):
        super().__init__(parent)
        self._formatter = formatter
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(0)
        layout.setColumnStretch(0, 1)

        self.title_label = QLabel(label, self)
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(minimum, maximum)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(page_step)
        self.slider.setAccessibleName(label)
        self.slider.setFocusPolicy(Qt.StrongFocus)
        self.value_label = QLabel(self)
        self.value_label.setObjectName("adjustmentSliderValue")
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setMinimumWidth(58)
        apply_theme_style(self.value_label, theme_style("""
            QLabel#adjustmentSliderValue {
                background: ${background};
                border: 1px solid ${border};
                border-radius: 6px;
                padding: 3px 7px;
            }
        """))

        layout.addWidget(self.title_label, 0, 0)
        layout.addWidget(self.value_label, 0, 1)
        layout.addWidget(self.slider, 1, 0, 1, 2)
        self.slider.valueChanged.connect(self._update_value)
        self.slider.setValue(value)
        self._update_value(self.slider.value())

    def _update_value(self, value):
        self.value_label.setText(self._formatter(value))


class ImageAdjustmentDialog(QDialog):
    PREVIEW_MAX_PIXELS = 1_500_000
    PREVIEW_DEBOUNCE_MS = 40

    def __init__(
        self,
        current_path,
        selected_paths=(),
        parent=None,
        *,
        workspace_paths=(),
        preview_image=None,
    ):
        super().__init__(parent)
        self.current_path = os.path.abspath(os.fspath(current_path))
        self.selected_paths = tuple(dict.fromkeys(
            os.path.abspath(os.fspath(path)) for path in selected_paths
        ))
        self.workspace_paths = tuple(dict.fromkeys(
            os.path.abspath(os.fspath(path)) for path in workspace_paths
        ))
        self.request = None
        self._preview_image = (
            QImage(preview_image)
            if isinstance(preview_image, QImage) and not preview_image.isNull()
            else QImage()
        )
        self._preview = None
        self._preview_failed = False
        self._updating_controls = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(self.PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self.setWindowTitle(tr("adjustment.title"))
        self.resize(980, 680)

        root = QVBoxLayout(self)
        top = QFormLayout()
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
        top.addRow(tr("geometry.workspace.scope"), self.scope_combo)
        scope_panel = section("ui.section.scope", top)

        body = QHBoxLayout()
        self.target_list = QListWidget(self)
        self.target_list.setMinimumHeight(92)
        self.preview_label = QLabel(self)
        self.preview_label.setMinimumSize(400, 300)
        self.preview_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview_label.setAlignment(Qt.AlignCenter)
        apply_theme_style(self.preview_label, theme_style("QLabel { background: ${preview_background}; border: 1px solid ${preview_border}; }"))
        body.addWidget(section("ui.section.preview", self.preview_label, stretch=1), 1)

        controls = QVBoxLayout()
        controls.setSpacing(8)
        self.brightness_row = _AdjustmentSliderRow(
            tr("adjustment.brightness"),
            -100,
            100,
            0,
            _format_brightness,
            page_step=10,
            parent=self,
        )
        self.contrast_row = _AdjustmentSliderRow(
            tr("adjustment.contrast"),
            1,
            30,
            10,
            lambda value: f"{value / 10.0:.1f}×",
            page_step=5,
            parent=self,
        )
        self.gamma_row = _AdjustmentSliderRow(
            tr("adjustment.gamma"),
            1,
            50,
            10,
            lambda value: f"{value / 10.0:.1f}",
            page_step=5,
            parent=self,
        )
        self.brightness_slider = self.brightness_row.slider
        self.contrast_slider = self.contrast_row.slider
        self.gamma_slider = self.gamma_row.slider
        self.brightness_value_label = self.brightness_row.value_label
        self.contrast_value_label = self.contrast_row.value_label
        self.gamma_value_label = self.gamma_row.value_label
        self.auto_adjust_button = QPushButton(tr("adjustment.autoAdjust"), self)
        self.reset_button = QPushButton(tr("standard.reset"), self)
        self.grayscale_checkbox = QCheckBox(tr("adjustment.grayscale"), self)
        controls.addWidget(self.brightness_row)
        controls.addWidget(self.contrast_row)
        controls.addWidget(self.gamma_row)
        option_row = QHBoxLayout()
        option_row.addWidget(self.auto_adjust_button)
        option_row.addWidget(self.reset_button)
        option_row.addStretch(1)
        controls.addLayout(option_row)
        controls.addWidget(self.grayscale_checkbox)
        sidebar = QWidget(self)
        sidebar.setFixedWidth(310)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(12)
        sidebar_layout.addWidget(scope_panel)
        sidebar_layout.addWidget(section("ui.section.parameters", controls))
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
        for slider in (
            self.brightness_slider,
            self.contrast_slider,
            self.gamma_slider,
        ):
            slider.valueChanged.connect(self._controls_changed)
        self.auto_adjust_button.clicked.connect(self._auto_adjust)
        self.reset_button.clicked.connect(self._reset_adjustments)
        self.grayscale_checkbox.toggled.connect(self._controls_changed)
        self.buttons.accepted.connect(self._accept_request)
        self.buttons.rejected.connect(self.reject)
        root.activate()
        self._preview = self._load_preview()
        self._scope_changed()
        present_dialog(self, primary=self.apply_button, scroll=True, icon="adjust-image")
        self.preview_label.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.preview_label and event.type() == QEvent.Resize:
            self._preview_timer.start()
        return super().eventFilter(watched, event)

    def _load_preview(self):
        max_pixels = self._preview_pixel_budget()
        if not self._preview_image.isNull():
            return _preview_from_qimage(
                self._preview_image,
                max_pixels=max_pixels,
            )
        return ImageFileCodec().load_preview(
            self.current_path,
            max_pixels=max_pixels,
        )

    def _preview_pixel_budget(self):
        size = self.preview_label.size()
        device_ratio = max(1.0, float(self.preview_label.devicePixelRatioF()))
        visible_pixels = int(
            size.width() * size.height() * device_ratio * device_ratio
        )
        return max(250_000, min(self.PREVIEW_MAX_PIXELS, visible_pixels))

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
        self.target_list.addItems(os.path.basename(path) for path in paths)
        for index, path in enumerate(paths):
            self.target_list.item(index).setToolTip(path)
        self._refresh_preview()

    def _options(self):
        return ImageAdjustmentOptions(
            brightness=self.brightness_slider.value(),
            contrast=self.contrast_slider.value() / 10.0,
            gamma=self.gamma_slider.value() / 10.0,
            grayscale=self.grayscale_checkbox.isChecked(),
        )

    def _controls_changed(self, _value=None):
        if self._updating_controls:
            return
        self._update_apply_button()
        self._schedule_preview()

    def _auto_adjust(self):
        suggestion = suggest_auto_adjustment(self._preview.pixels)
        self._updating_controls = True
        try:
            self.brightness_slider.setValue(suggestion.brightness)
            self.contrast_slider.setValue(round(suggestion.contrast * 10))
            self.gamma_slider.setValue(round(suggestion.gamma * 10))
        finally:
            self._updating_controls = False
        self._controls_changed()

    def _reset_adjustments(self):
        defaults = ImageAdjustmentOptions()
        self._updating_controls = True
        try:
            self.brightness_slider.setValue(defaults.brightness)
            self.contrast_slider.setValue(round(defaults.contrast * 10))
            self.gamma_slider.setValue(round(defaults.gamma * 10))
            self.grayscale_checkbox.setChecked(defaults.grayscale)
        finally:
            self._updating_controls = False
        self._controls_changed()

    def _refresh_preview(self):
        try:
            result = apply_adjustments(self._preview.pixels, self._options())
            pixmap = _array_pixmap(result)
            self.preview_label.setPixmap(pixmap.scaled(
                self.preview_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            ))
        except Exception as error:
            self._preview_failed = True
            self.preview_label.setText(
                tr(
                    "imageTools.preview.failed",
                    path=os.path.basename(self.current_path),
                    error=error,
                )
            )
            self._update_apply_button()
            return
        self._preview_failed = False
        self._update_apply_button()

    def _schedule_preview(self):
        self._preview_timer.start()

    def _update_apply_button(self):
        self.auto_adjust_button.setEnabled(not self._preview_failed)
        self.reset_button.setEnabled(self._options() != ImageAdjustmentOptions())
        self.apply_button.setEnabled(
            not self._preview_failed
            and self._options() != ImageAdjustmentOptions()
        )

    def _accept_request(self):
        self.request = ImageAdjustmentRequest(
            paths=tuple(self._paths()),
            options=self._options(),
        )
        self.accept()


def _format_brightness(value):
    return "0%" if not value else f"{value:+d}%"


def _preview_from_qimage(image, *, max_pixels):
    """Build bounded processing pixels from an already decoded Qt image."""
    source_size = (image.width(), image.height())
    working = QImage(image)
    pixel_count = image.width() * image.height()
    if pixel_count > max_pixels:
        ratio = math.sqrt(max_pixels / float(pixel_count))
        working = image.scaled(
            max(1, int(image.width() * ratio)),
            max(1, int(image.height() * ratio)),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
    rgba = working.convertToFormat(QImage.Format_RGBA8888)
    pointer = rgba.bits()
    pointer.setsize(rgba.byteCount())
    rows = np.frombuffer(pointer, dtype=np.uint8).reshape(
        rgba.height(), rgba.bytesPerLine()
    )
    pixels = rows[:, : rgba.width() * 4].reshape(
        rgba.height(), rgba.width(), 4
    ).copy()
    return _AdjustmentPreview(
        cv2.cvtColor(pixels, cv2.COLOR_RGBA2BGRA),
        source_size,
    )
