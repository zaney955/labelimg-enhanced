"""Qt controls and rendering for non-destructive Canvas display adjustment."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import threading

from PyQt5.QtCore import (
    QEvent,
    QObject,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from labelimg.image_tools.application.adjustment import (
    ImageAdjustmentOptions,
    apply_adjustments,
)
from labelimg.image_tools.application.display_adjustment import (
    CanvasDisplayAdjustmentSession,
    DisplayAdjustmentValues,
    contrast_factor,
)
from labelimg.localization.runtime import language_changed, tr
from labelimg.ui.actions import new_icon


PREVIEW_MAX_PIXELS = 1_500_000
PREVIEW_DEBOUNCE_MS = 40
FULL_RENDER_IDLE_MS = 180
MASTER_GESTURE_IDLE_MS = 240


def display_adjustment_icon():
    """Build a distinct menu icon from the shipped adjustment symbol."""
    pixmap = new_icon("adjust-image").pixmap(24, 24)
    painter = QPainter(pixmap)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#F3C26B"))
    painter.drawEllipse(15, 3, 6, 6)
    painter.setBrush(QColor("#455468"))
    painter.drawEllipse(17, 5, 2, 2)
    painter.end()
    return QIcon(pixmap)


class AdjustmentSliderRow(QWidget):
    valueChanged = pyqtSignal(int)
    gestureStarted = pyqtSignal()
    gestureFinished = pyqtSignal()

    def __init__(self, title_id, parent=None):
        super().__init__(parent)
        self.title_id = title_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(self)
        self.value_label = QLabel("0", self)
        self.value_label.setMinimumWidth(34)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        heading.addWidget(self.title_label)
        heading.addStretch(1)
        heading.addWidget(self.value_label)
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(-100, 100)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(10)
        self.slider.setTracking(True)
        layout.addLayout(heading)
        layout.addWidget(self.slider)
        self.slider.valueChanged.connect(self._value_changed)
        self.slider.sliderPressed.connect(self.gestureStarted.emit)
        self.slider.sliderReleased.connect(self.gestureFinished.emit)
        self.retranslate_ui()

    def _value_changed(self, value):
        self.value_label.setText("%+d" % value if value else "0")
        self.valueChanged.emit(value)

    def value(self):
        return self.slider.value()

    def set_value(self, value):
        blocker = QSignalBlocker(self.slider)
        self.slider.setValue(int(value))
        del blocker
        self.value_label.setText("%+d" % value if value else "0")

    def retranslate_ui(self):
        title = tr(self.title_id)
        self.title_label.setText(title)
        self.slider.setAccessibleName(title)
        self.slider.setAccessibleDescription(
            tr("displayAdjustment.sliderDescription", name=title)
        )


class DisplayAdjustmentPanel(QWidget):
    masterValuesChanged = pyqtSignal(object)
    currentValuesChanged = pyqtSignal(object)
    masterGestureStarted = pyqtSignal()
    masterGestureFinished = pyqtSignal()
    resetAllRequested = pyqtSignal()
    resetCurrentRequested = pyqtSignal()
    restoreRequested = pyqtSignal()
    retryRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("displayAdjustmentPanel")
        self.setMinimumWidth(180)
        self.setMaximumWidth(360)
        self._projecting = False
        self._has_image = False
        self._has_override = False
        self._gesture_active = False
        self._notice_count = None
        self._render_error = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.no_image_label = QLabel(self)
        self.no_image_label.setAlignment(Qt.AlignCenter)
        self.no_image_label.setWordWrap(True)
        self.no_image_label.setStyleSheet("color: palette(mid);")
        root.addWidget(self.no_image_label)

        self.master_frame = QFrame(self)
        self.master_frame.setFrameShape(QFrame.StyledPanel)
        master_layout = QVBoxLayout(self.master_frame)
        master_layout.setContentsMargins(8, 8, 8, 8)
        master_layout.setSpacing(8)
        self.master_title = QLabel(self.master_frame)
        font = self.master_title.font()
        font.setBold(True)
        self.master_title.setFont(font)
        master_layout.addWidget(self.master_title)
        self.master_brightness = AdjustmentSliderRow(
            "adjustment.brightness", self.master_frame
        )
        self.master_contrast = AdjustmentSliderRow(
            "adjustment.contrast", self.master_frame
        )
        master_layout.addWidget(self.master_brightness)
        master_layout.addWidget(self.master_contrast)
        self.reset_all_button = QPushButton(self.master_frame)
        master_layout.addWidget(self.reset_all_button)
        root.addWidget(self.master_frame)

        self.current_disclosure = QToolButton(self)
        self.current_disclosure.setObjectName("currentImageAdjustmentDisclosure")
        self.current_disclosure.setCheckable(True)
        self.current_disclosure.setChecked(False)
        self.current_disclosure.setArrowType(Qt.RightArrow)
        self.current_disclosure.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.current_disclosure.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )
        root.addWidget(self.current_disclosure)

        self.current_frame = QFrame(self)
        self.current_frame.setFrameShape(QFrame.StyledPanel)
        current_layout = QVBoxLayout(self.current_frame)
        current_layout.setContentsMargins(8, 8, 8, 8)
        current_layout.setSpacing(8)
        self.current_status = QLabel(self.current_frame)
        self.current_status.setStyleSheet("color: palette(mid);")
        current_layout.addWidget(self.current_status)
        self.current_brightness = AdjustmentSliderRow(
            "adjustment.brightness", self.current_frame
        )
        self.current_contrast = AdjustmentSliderRow(
            "adjustment.contrast", self.current_frame
        )
        current_layout.addWidget(self.current_brightness)
        current_layout.addWidget(self.current_contrast)
        self.reset_current_button = QPushButton(self.current_frame)
        current_layout.addWidget(self.reset_current_button)
        self.current_frame.hide()
        root.addWidget(self.current_frame)

        self.notice_frame = QFrame(self)
        self.notice_frame.setFrameShape(QFrame.StyledPanel)
        notice_layout = QVBoxLayout(self.notice_frame)
        notice_layout.setContentsMargins(8, 8, 8, 8)
        self.notice_label = QLabel(self.notice_frame)
        self.notice_label.setWordWrap(True)
        self.restore_button = QPushButton(self.notice_frame)
        notice_layout.addWidget(self.notice_label)
        notice_layout.addWidget(self.restore_button)
        self.notice_frame.hide()
        root.addWidget(self.notice_frame)

        self.error_frame = QFrame(self)
        self.error_frame.setFrameShape(QFrame.StyledPanel)
        error_layout = QVBoxLayout(self.error_frame)
        error_layout.setContentsMargins(8, 8, 8, 8)
        self.error_label = QLabel(self.error_frame)
        self.error_label.setWordWrap(True)
        self.retry_button = QPushButton(self.error_frame)
        error_layout.addWidget(self.error_label)
        error_layout.addWidget(self.retry_button)
        self.error_frame.hide()
        root.addWidget(self.error_frame)
        root.addStretch(1)

        self.current_disclosure.toggled.connect(self._toggle_current)
        self.reset_all_button.clicked.connect(self.resetAllRequested.emit)
        self.reset_current_button.clicked.connect(
            self.resetCurrentRequested.emit
        )
        self.restore_button.clicked.connect(self.restoreRequested.emit)
        self.retry_button.clicked.connect(self.retryRequested.emit)
        for row in (self.master_brightness, self.master_contrast):
            row.valueChanged.connect(self._master_changed)
            row.gestureStarted.connect(self.masterGestureStarted.emit)
            row.gestureFinished.connect(self.masterGestureFinished.emit)
        for row in (self.current_brightness, self.current_contrast):
            row.valueChanged.connect(self._current_changed)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        self.project(
            DisplayAdjustmentValues(),
            DisplayAdjustmentValues(),
            has_override=False,
            has_image=False,
        )

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(220, hint.height())

    def _toggle_current(self, expanded):
        self.current_disclosure.setArrowType(
            Qt.DownArrow if expanded else Qt.RightArrow
        )
        self.current_frame.setVisible(bool(expanded))

    def _master_changed(self, _value):
        if not self._projecting:
            self.masterValuesChanged.emit(DisplayAdjustmentValues(
                self.master_brightness.value(),
                self.master_contrast.value(),
            ))

    def _current_changed(self, _value):
        if not self._projecting:
            self.currentValuesChanged.emit(DisplayAdjustmentValues(
                self.current_brightness.value(),
                self.current_contrast.value(),
            ))

    def project(self, master, current, *, has_override, has_image):
        self._projecting = True
        try:
            self.master_brightness.set_value(master.brightness)
            self.master_contrast.set_value(master.contrast)
            self.current_brightness.set_value(current.brightness)
            self.current_contrast.set_value(current.contrast)
        finally:
            self._projecting = False
        self._has_image = bool(has_image)
        self._has_override = bool(has_override)
        self.no_image_label.setVisible(not self._has_image)
        self._retranslate_current_status()
        self.reset_current_button.setEnabled(
            self._has_image and has_override and not self._gesture_active
        )
        self._sync_enabled()

    def _sync_enabled(self):
        enabled = self._has_image and not self._gesture_active
        self.master_frame.setEnabled(enabled)
        self.current_disclosure.setEnabled(enabled)
        self.current_frame.setEnabled(enabled)

    def set_canvas_gesture_active(self, active):
        self._gesture_active = bool(active)
        self._sync_enabled()

    def show_restore_notice(self, count):
        self._notice_count = count
        self.notice_label.setText(
            tr("displayAdjustment.cleared", count=count)
        )
        self.notice_frame.show()

    def hide_restore_notice(self):
        self._notice_count = None
        self.notice_frame.hide()

    def show_render_error(self, path, error):
        self._render_error = (path, error)
        self.error_label.setText(tr(
            "displayAdjustment.renderFailed",
            name=os.path.basename(path),
            error=error,
        ))
        self.error_frame.show()

    def clear_render_error(self):
        self._render_error = None
        self.error_frame.hide()

    def _retranslate_current_status(self):
        self.current_status.setText(tr(
            "displayAdjustment.individuallyAdjusted"
            if self._has_override
            else "displayAdjustment.followingAll"
        ))

    def retranslate_ui(self, _language=None):
        self.master_title.setText(tr("displayAdjustment.allImages"))
        self.current_disclosure.setText(
            tr("displayAdjustment.currentImage")
        )
        self.reset_all_button.setText(tr("displayAdjustment.resetAll"))
        self.reset_current_button.setText(
            tr("displayAdjustment.resetCurrent")
        )
        self.restore_button.setText(tr("displayAdjustment.restore"))
        self.retry_button.setText(tr("displayAdjustment.retry"))
        self.no_image_label.setText(tr("displayAdjustment.noImage"))
        self._retranslate_current_status()
        if self._notice_count is not None:
            self.notice_label.setText(tr(
                "displayAdjustment.cleared", count=self._notice_count
            ))
        if self._render_error is not None:
            path, error = self._render_error
            self.error_label.setText(tr(
                "displayAdjustment.renderFailed",
                name=os.path.basename(path),
                error=error,
            ))
        self.current_disclosure.setAccessibleName(
            tr("displayAdjustment.currentImage")
        )
        self.current_disclosure.setAccessibleDescription(
            tr("displayAdjustment.currentDescription")
        )
        for row in (
            self.master_brightness,
            self.master_contrast,
            self.current_brightness,
            self.current_contrast,
        ):
            row.retranslate_ui()


@dataclass(frozen=True)
class _RenderRequest:
    generation: int
    path: str
    image: QImage
    values: DisplayAdjustmentValues
    max_pixels: int | None
    kind: str


class _RenderBridge(QObject):
    completed = pyqtSignal(object, object)
    failed = pyqtSignal(object, object)


class _LatestRenderWorker(threading.Thread):
    def __init__(self, bridge, name):
        super().__init__(name=name, daemon=True)
        self._bridge = bridge
        self._condition = threading.Condition()
        self._pending = None
        self._stopping = False

    def submit(self, request):
        with self._condition:
            self._pending = request
            self._condition.notify()

    def stop(self):
        with self._condition:
            self._stopping = True
            self._pending = None
            self._condition.notify()

    def run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                request = self._pending
                self._pending = None
            try:
                result = render_adjusted_image(
                    request.image,
                    request.values,
                    max_pixels=request.max_pixels,
                )
            except Exception as error:  # Qt boundary reports localized text.
                with self._condition:
                    if self._stopping:
                        return
                    self._bridge.failed.emit(request, error)
            else:
                with self._condition:
                    if self._stopping:
                        return
                    self._bridge.completed.emit(request, result)


class CanvasDisplayAdjustmentController(QObject):
    """Coordinate session state, panel projection, and latest-only renders."""

    def __init__(
        self,
        session,
        panel,
        *,
        project_pixmap,
        active_changed,
        parent=None,
    ):
        super().__init__(parent)
        self.session = session
        self.panel = panel
        self._project_pixmap = project_pixmap
        self._active_changed = active_changed
        self._path = None
        self._source = QImage()
        self._generation = 0
        self._master_gesture_open = False
        self._shutdown = False
        self._bridge = _RenderBridge(self)
        self._bridge.completed.connect(self._render_completed)
        self._bridge.failed.connect(self._render_failed)
        self._preview_worker = _LatestRenderWorker(
            self._bridge, "labelimg-display-preview"
        )
        self._full_worker = _LatestRenderWorker(
            self._bridge, "labelimg-display-full"
        )
        self._preview_worker.start()
        self._full_worker.start()
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._submit_preview)
        self._full_timer = QTimer(self)
        self._full_timer.setSingleShot(True)
        self._full_timer.setInterval(FULL_RENDER_IDLE_MS)
        self._full_timer.timeout.connect(self._submit_full)
        self._master_idle_timer = QTimer(self)
        self._master_idle_timer.setSingleShot(True)
        self._master_idle_timer.setInterval(MASTER_GESTURE_IDLE_MS)
        self._master_idle_timer.timeout.connect(self.finish_master_gesture)

        panel.masterGestureStarted.connect(self.begin_master_gesture)
        panel.masterGestureFinished.connect(self.finish_master_gesture)
        panel.masterValuesChanged.connect(self.set_master)
        panel.currentValuesChanged.connect(self.set_current)
        panel.resetAllRequested.connect(self.reset_all)
        panel.resetCurrentRequested.connect(self.reset_current)
        panel.restoreRequested.connect(self.restore_last_clear)
        panel.retryRequested.connect(self.retry)
        if parent is not None:
            parent.installEventFilter(self)
            parent.destroyed.connect(self.shutdown)
        self._sync_panel()

    def eventFilter(self, watched, event):
        # deleteLater() destroys QObject children before parent.destroyed is
        # emitted. Stop Python render workers while their Qt bridge and timers
        # are still valid.
        if watched is self.parent() and event.type() == QEvent.DeferredDelete:
            self.shutdown()
        return super().eventFilter(watched, event)

    @property
    def current_path(self):
        return self._path

    def replace_workspace(self, workspace_key):
        if self.session.replace_workspace(workspace_key):
            self.panel.hide_restore_notice()
            self.panel.clear_render_error()
            self._generation += 1
            self._sync_panel()
            self._sync_active()

    def activate_source(self, image, path, workspace_key, source_token=None):
        self.replace_workspace(workspace_key)
        self._path = os.path.abspath(os.fspath(path))
        self._source = QImage(image)
        if source_token is not None:
            self.session.observe_source(self._path, source_token)
        self._generation += 1
        self.panel.clear_render_error()
        self._sync_panel()
        self._sync_active()
        values = self.session.effective(self._path)
        try:
            preview = render_adjusted_image(
                self._source, values, max_pixels=PREVIEW_MAX_PIXELS
            )
        except Exception as error:
            self.panel.show_render_error(self._path, str(error))
            return QPixmap.fromImage(self._source)
        if not values.neutral:
            self._submit_full()
        return QPixmap.fromImage(preview)

    def deactivate_image(self):
        self._generation += 1
        self._path = None
        self._source = QImage()
        self.panel.clear_render_error()
        self._sync_panel()

    def begin_master_gesture(self):
        if self._master_gesture_open:
            return
        self.session.begin_master_gesture()
        self._master_gesture_open = True

    def finish_master_gesture(self):
        if not self._master_gesture_open:
            return
        self._master_idle_timer.stop()
        self._master_gesture_open = False
        cleared = self.session.finish_master_gesture()
        if cleared:
            self.panel.show_restore_notice(cleared)
        else:
            self.panel.hide_restore_notice()
        self._submit_full()

    def set_master(self, values):
        if not self._path:
            return
        self.begin_master_gesture()
        self.session.set_master(values)
        self._master_idle_timer.start()
        self._values_changed()

    def set_current(self, values):
        if not self._path:
            return
        self.finish_master_gesture()
        self.session.set_override(self._path, values)
        self.panel.hide_restore_notice()
        self._values_changed()

    def reset_all(self):
        if not self._path:
            return
        self.finish_master_gesture()
        cleared = self.session.reset_all()
        if cleared:
            self.panel.show_restore_notice(cleared)
        else:
            self.panel.hide_restore_notice()
        self._values_changed(schedule_full=True)

    def reset_current(self):
        if not self._path:
            return
        self.finish_master_gesture()
        self.session.reset_current(self._path)
        self.panel.hide_restore_notice()
        self._values_changed(schedule_full=True)

    def restore_last_clear(self):
        if not self.session.restore_last_clear():
            return
        self.panel.hide_restore_notice()
        self._values_changed(schedule_full=True)

    def retry(self):
        if not self._path:
            return
        self.panel.clear_render_error()
        self._schedule_renders(full=True)

    def source_pixels_replaced(self, paths):
        self.finish_master_gesture()
        self.session.source_pixels_replaced(paths)
        self.panel.hide_restore_notice()
        self._sync_panel()
        self._sync_active()

    def rename_paths(self, mapping):
        self.finish_master_gesture()
        self.session.rename_paths(mapping)
        if self._path in mapping:
            self._path = os.path.abspath(os.fspath(mapping[self._path]))
        self._sync_panel()
        self._sync_active()

    def remove_images(self, paths):
        self.finish_master_gesture()
        self.session.remove_images(paths)
        self._sync_panel()
        self._sync_active()

    def set_canvas_gesture_active(self, active):
        self.panel.set_canvas_gesture_active(active)

    def shutdown(self, _destroyed_object=None):
        if self._shutdown:
            return
        self._shutdown = True
        self._preview_timer.stop()
        self._full_timer.stop()
        self._master_idle_timer.stop()
        self._preview_worker.stop()
        self._full_worker.stop()
        self._preview_worker.join(timeout=0.25)
        self._full_worker.join(timeout=0.25)

    def _values_changed(self, schedule_full=False):
        self._generation += 1
        self.panel.clear_render_error()
        self._sync_panel()
        self._sync_active()
        self._schedule_renders(full=schedule_full)

    def _schedule_renders(self, full=False):
        self._preview_timer.start()
        if full:
            self._full_timer.stop()
            self._submit_full()
        else:
            self._full_timer.start()

    def _request(self, *, max_pixels, kind):
        if not self._path or self._source.isNull():
            return None
        return _RenderRequest(
            self._generation,
            self._path,
            QImage(self._source),
            self.session.effective(self._path),
            max_pixels,
            kind,
        )

    def _submit_preview(self):
        request = self._request(
            max_pixels=PREVIEW_MAX_PIXELS,
            kind="preview",
        )
        if request is not None:
            self._preview_worker.submit(request)

    def _submit_full(self):
        request = self._request(max_pixels=None, kind="full")
        if request is not None:
            self._full_worker.submit(request)

    def _render_completed(self, request, image):
        if not self._request_is_current(request):
            return
        self.panel.clear_render_error()
        self._project_pixmap(QPixmap.fromImage(image))

    def _render_failed(self, request, error):
        if not self._request_is_current(request):
            return
        self.panel.show_render_error(request.path, str(error))
        self._project_pixmap(QPixmap.fromImage(self._source))

    def _request_is_current(self, request):
        return (
            request.generation == self._generation
            and request.path == self._path
            and request.values == self.session.effective(self._path)
        )

    def _sync_panel(self):
        current = self.session.effective(self._path)
        self.panel.project(
            self.session.master,
            current,
            has_override=self.session.has_override(self._path),
            has_image=bool(self._path) and not self._source.isNull(),
        )

    def _sync_active(self):
        self._active_changed(self.session.has_adjustments)


def render_adjusted_image(image, values, *, max_pixels=None):
    """Return a detached adjusted QImage, optionally via a bounded preview."""
    if image.isNull():
        raise ValueError("cannot adjust a null image")
    values = (
        values
        if isinstance(values, DisplayAdjustmentValues)
        else DisplayAdjustmentValues(*values)
    )
    if values.neutral:
        return QImage(image)

    source_size = image.size()
    working = QImage(image)
    pixel_count = image.width() * image.height()
    if max_pixels and pixel_count > max_pixels:
        ratio = math.sqrt(max_pixels / float(pixel_count))
        working = image.scaled(
            max(1, int(round(image.width() * ratio))),
            max(1, int(round(image.height() * ratio))),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
    rgba = working.convertToFormat(QImage.Format_RGBA8888)
    pointer = rgba.bits()
    pointer.setsize(rgba.byteCount())
    import numpy as np

    rows = np.frombuffer(pointer, dtype=np.uint8).reshape(
        rgba.height(), rgba.bytesPerLine()
    )
    pixels = rows[:, : rgba.width() * 4].reshape(
        rgba.height(), rgba.width(), 4
    ).copy()
    adjusted = apply_adjustments(
        pixels,
        ImageAdjustmentOptions(
            brightness=values.brightness,
            contrast=contrast_factor(values.contrast),
        ),
    )
    adjusted = np.ascontiguousarray(adjusted)
    result = QImage(
        adjusted.data,
        adjusted.shape[1],
        adjusted.shape[0],
        adjusted.strides[0],
        QImage.Format_RGBA8888,
    ).copy()
    if result.size() != source_size:
        result = result.scaled(
            source_size,
            Qt.IgnoreAspectRatio,
            Qt.FastTransformation,
        )
    return result


def source_token(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


__all__ = (
    "CanvasDisplayAdjustmentController",
    "DisplayAdjustmentPanel",
    "display_adjustment_icon",
    "render_adjusted_image",
    "source_token",
)
