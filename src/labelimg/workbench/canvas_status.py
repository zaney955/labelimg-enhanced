"""One full-width workbench footer: readouts, feedback, and view controls."""

from PyQt5.QtCore import QEvent, QSize, Qt, QTimer
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QSizePolicy,
    QStatusBar, QToolButton,
)

from labelimg.localization.runtime import information, language_changed, tr
from labelimg.ui.actions import format_action_tooltip
from labelimg.ui.icons import icon
from labelimg.ui.metrics import dp, scale_changed


class _MessageLabel(QLabel):
    """Keep the full accessible message while painting only available text."""

    def __init__(self, parent):
        super().__init__(parent)
        self.fallback_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        text = self.text()
        if self.fallback_text and self.fontMetrics().horizontalAdvance(text) > self.contentsRect().width():
            text = self.fallback_text
        painter.drawText(
            self.contentsRect(), Qt.AlignLeft | Qt.AlignVCenter,
            self.fontMetrics().elidedText(
                text, Qt.ElideRight, self.contentsRect().width(),
            ),
        )


class WorkbenchStatusBar(QStatusBar):
    """Arbitrate transient hints without overwriting task feedback.

    Keep QStatusBar's public message API for existing Python callers. The main
    window routes Qt StatusTip events here explicitly: Qt's C++ showMessage
    slot is not virtual and would paint another message behind this surface.
    """

    def __init__(self, zoom_control, parent=None):
        super().__init__(parent)
        self.setObjectName("workbenchStatusBar")
        self.setSizeGripEnabled(False)
        self._image_size = QSize()
        self._arranging = False
        self._compact_actions = False
        self._hover = ""
        self._canvas_hint = ""
        self._tool_hint = None
        self._notice = ""
        self._important = ""
        self._important_source = None
        self._important_translation = None
        self._task = None
        self._current_message = ""
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(self.clearMessage)
        self._important_timer = QTimer(self)
        self._important_timer.setSingleShot(True)
        self._important_timer.timeout.connect(self.clear_important_message)

        self.surface = QFrame(self)
        self.surface.setObjectName("workbenchStatusContent")
        self.addPermanentWidget(self.surface, 1)
        self.layout().setContentsMargins(0, 0, 0, 0)
        self._row = QHBoxLayout(self.surface)
        self._row.setContentsMargins(8, 2, 8, 2)
        self._row.setSpacing(16)
        self._row.setSizeConstraint(QLayout.SetNoConstraint)
        self.readouts = QFrame(self.surface)
        self._readouts = QGridLayout(self.readouts)
        self._readouts.setContentsMargins(0, 0, 0, 0)
        self._readouts.setHorizontalSpacing(12)
        self._readouts.setVerticalSpacing(0)
        self.coordinates = QLabel("X: —  Y: —", self.readouts)
        self.dimensions = QLabel("", self.readouts)
        self.coordinates.installEventFilter(self)
        self.dimensions.installEventFilter(self)
        self._row.addWidget(self.readouts)

        self.feedback = QFrame(self.surface)
        self.feedback.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        feedback_layout = QHBoxLayout(self.feedback)
        feedback_layout.setSizeConstraint(QLayout.SetNoConstraint)
        feedback_layout.setContentsMargins(0, 0, 0, 0)
        feedback_layout.setSpacing(6)
        self.message_label = _MessageLabel(self.feedback)
        feedback_layout.addWidget(self.message_label, 1)
        self.details_button = QToolButton(self.feedback)
        self.details_button.setAutoRaise(True)
        self.details_button.setIcon(icon("more"))
        self.details_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.details_button.setProperty("uiScaleGeometryExcluded", True)
        self.details_button.clicked.connect(self._show_details)
        self.details_button.hide()
        feedback_layout.addWidget(self.details_button)
        self._row.addWidget(self.feedback, 1)

        self.zoom = zoom_control
        self.view_controls = QFrame(self.surface)
        controls = QHBoxLayout(self.view_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        self.magnifier_button = QToolButton(self.view_controls)
        self.magnifier_button.setObjectName("crosshairMagnifierButton")
        self.magnifier_button.setAutoRaise(True)
        self.magnifier_button.setFixedSize(28, 28)
        self.magnifier_button.setIconSize(QSize(20, 20))
        self.magnifier_button.setFocusPolicy(Qt.StrongFocus)
        controls.addWidget(self.magnifier_button)
        controls.addWidget(self.zoom)
        self._row.addWidget(self.view_controls)
        # These constraints derive from content, rather than design lengths.
        for widget in (self.surface, self.readouts, self.coordinates,
                       self.dimensions, self.feedback, self.view_controls):
            widget.setProperty("uiScaleGeometryExcluded", True)
        self.zoom.installEventFilter(self)
        language_changed.connect(self.retranslate_ui)
        scale_changed.connect(self._scale_changed)
        self.retranslate_ui()

    @property
    def stacked(self):
        """Only readouts stack; zoom never adds another footer row."""
        return self._readouts.getItemPosition(
            self._readouts.indexOf(self.dimensions),
        )[0] == 1

    def set_image_size(self, size):
        self._image_size = QSize(size)
        for label, names in ((self.coordinates, ("X", "Y")),
                             (self.dimensions, ("W", "H"))):
            label.ensurePolished()
            metrics = label.fontMetrics()
            digit = max("0123456789", key=metrics.horizontalAdvance)
            values = [digit * max(3, len(str(max(0, value))))
                      for value in (size.width(), size.height())]
            sample = "%s: %s  %s: %s" % (
                names[0], values[0], names[1], values[1],
            )
            label.setFixedSize(metrics.horizontalAdvance(sample) + dp(2), metrics.height())
        self._arrange()

    def _arrange(self):
        if self._arranging:
            return
        self._arranging = True
        try:
            self._row.setContentsMargins(dp(8), dp(2), dp(8), dp(2))
            self._row.setSpacing(dp(16))
            self._readouts.setHorizontalSpacing(dp(12))
            self.feedback.layout().setSpacing(dp(6))
            self.view_controls.layout().setSpacing(dp(6))
            available = max(0, self.surface.width() - dp(16 + 32))
            widths = [self.coordinates.width(), self.dimensions.width()]
            readout_width = sum(widths) + dp(12)
            zoom_chrome = (self.zoom.sizeHint().width() - self.zoom.slider.width()
                           + self.magnifier_button.width() + dp(6))
            # Independent of text and button visibility: feedback changes must
            # never move a slider being dragged by the user.
            feedback_minimum = max(dp(180), dp(80) + sum(
                self.fontMetrics().horizontalAdvance(tr(key))
                for key in ("directoryLoading.resume", "workbenchStatus.details")
            ))
            room = available - readout_width - zoom_chrome - feedback_minimum
            slider_width = dp(112) if room >= dp(112) else dp(80) if room >= dp(80) else dp(64)
            stacked = room < dp(64)
            self.zoom.set_slider_width(slider_width)
            self._readouts.addWidget(self.coordinates, 0, 0)
            self._readouts.addWidget(self.dimensions, 1 if stacked else 0,
                                     0 if stacked else 1)
            self.readouts.setFixedWidth(max(widths) if stacked else readout_width)
            self.feedback.setMinimumWidth(0)
            self.view_controls.setFixedWidth(zoom_chrome + slider_width)
            feedback_width = (available - self.readouts.width()
                              - zoom_chrome - slider_width)
            compact_actions = feedback_width < feedback_minimum
            self._compact_actions = compact_actions
            for button in (self.details_button, getattr(self, "task_button", None)):
                if button is None:
                    continue
                button.setIconSize(QSize(dp(20), dp(20)))
                if compact_actions:
                    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
                    button.setFixedSize(dp(28), dp(28))
                else:
                    button.setToolButtonStyle(Qt.ToolButtonTextOnly)
                    button.setMinimumSize(0, 0)
                    button.setMaximumSize(16777215, 16777215)
            height = max(
                self.coordinates.height() * (2 if stacked else 1),
                self.view_controls.sizeHint().height(),
                self.feedback.sizeHint().height(), dp(28),
            ) + dp(4)
            self.surface.setFixedHeight(height)
            self._readouts.activate()
            self._row.activate()
            self.view_controls.layout().activate()
            self.zoom.layout().activate()
            self._refresh_message()
        finally:
            self._arranging = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "zoom"):
            self._arrange()

    def eventFilter(self, watched, event):
        if watched is getattr(self, "zoom", None) and event.type() == QEvent.LayoutRequest:
            self._arrange()
        if (watched in (getattr(self, "coordinates", None),
                        getattr(self, "dimensions", None))
                and event.type() in (QEvent.FontChange, QEvent.StyleChange)
                and hasattr(self, "zoom")):
            QTimer.singleShot(0, self._refresh_metrics)
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange) and hasattr(self, "zoom"):
            QTimer.singleShot(0, self._refresh_metrics)

    def _refresh_metrics(self):
        self.set_image_size(self._image_size)

    def _scale_changed(self, _percent):
        QTimer.singleShot(0, self._refresh_metrics)

    def showMessage(self, message, timeout=0):
        self._notice_timer.stop()
        self._notice = str(message)
        self._hover = ""
        if timeout > 0:
            self._notice_timer.start(timeout)
        self._refresh_message()

    def clearMessage(self):
        self._notice_timer.stop()
        self._notice = ""
        self._refresh_message()

    def currentMessage(self):
        return self._current_message

    def show_important_message(self, message, timeout=0, *, source=None):
        self._important_timer.stop()
        self._important = str(message)
        self._important_source = source
        self._important_translation = None
        if timeout > 0:
            self._important_timer.start(timeout)
        self._refresh_message()

    def show_important_translation(self, message_id, timeout=0, *, source=None, **values):
        self.show_important_message(tr(message_id, **values), timeout, source=source)
        self._important_translation = (message_id, values)

    def clear_important_message(self, *, source=None):
        if source is not None and source != self._important_source:
            return
        self._important_timer.stop()
        self._important = ""
        self._important_source = None
        self._important_translation = None
        self._refresh_message()

    def set_hover_message(self, message):
        self._hover = str(message)
        if self._hover:
            self._discard_notice()
        self._refresh_message()

    def _discard_notice(self):
        self._notice_timer.stop()
        self._notice = ""

    def set_canvas_hint(self, message, interactive=False):
        self._canvas_hint = str(message)
        if interactive:
            self._hover = ""
            self._discard_notice()
        self._refresh_message()

    def set_tool_hint(self, message_id):
        """Overlay tools supply a localized context without a result timeout."""
        self._tool_hint = message_id
        self.coordinates.setText("X: —  Y: —")
        self.dimensions.setText("")
        self._canvas_hint = ""
        self._hover = ""
        self._discard_notice()
        self._refresh_message()

    def set_canvas_coordinates(self, text):
        if self._tool_hint is None:
            self.coordinates.setText(text)

    def set_annotation_size(self, text):
        self.dimensions.setText("" if self._tool_hint else text)

    def set_tool_pointer_position(self, position):
        if self._tool_hint is not None:
            self.coordinates.setText(
                "X: —  Y: —" if position is None else
                "X: %d  Y: %d" % (position[0], position[1])
            )

    def resume_tool_hint(self, _position=None):
        if self._tool_hint is not None:
            self._hover = ""
            self._discard_notice()
            self._refresh_message()

    def reset_context(self, _size=None):
        """Drop text and timers tied to the previous image, retaining tasks."""
        self._discard_notice()
        self._important_timer.stop()
        self._important = ""
        self._important_source = None
        self._important_translation = None
        self._hover = ""
        self._canvas_hint = ""
        self._tool_hint = None
        self._refresh_message()

    def set_task_message(self, message_id, **values):
        self._discard_notice()
        self._task = (message_id, values)
        self._refresh_message()

    def clear_task_message(self):
        self._discard_notice()
        self._task = None
        self._refresh_message()

    def _refresh_message(self):
        if self._important_translation is not None:
            self._important = tr(self._important_translation[0], **self._important_translation[1])
        task_text = tr(self._task[0], **self._task[1]) if self._task else ""
        task_failed = self._task and self._task[0] == "directoryLoading.failed"
        important = bool(self._important or task_failed)
        text = (self._important or task_text) if important else (
            task_text or self._notice or self._hover
            or (tr(self._tool_hint) if self._tool_hint else self._canvas_hint)
        )
        self.message_label.fallback_text = (
            tr("workbenchStatus.failedShort" if task_failed else "workbenchStatus.attentionShort")
            if important and self._compact_actions else ""
        )
        self.message_label.setText(text)
        self.message_label.update()
        self.message_label.setToolTip(text)
        self.message_label.setAccessibleDescription(text)
        self.details_button.setVisible(important)
        if text != self._current_message:
            self._current_message = text
            self.messageChanged.emit(text)

    def set_task_button(self, button):
        self.task_button = button
        button.setProperty("uiScaleGeometryExcluded", True)
        self.feedback.layout().addWidget(button)
        self._arrange()

    def _show_details(self):
        information(self, tr("workbenchStatus.detailsTitle"), self.currentMessage())

    def set_magnifier_action(self, action):
        self.magnifier_button.setDefaultAction(action)
        action.changed.connect(self._sync_magnifier_copy)
        self._sync_magnifier_copy()
        self._arrange()

    def _sync_magnifier_copy(self):
        action = self.magnifier_button.defaultAction()
        if action is not None:
            self.magnifier_button.setToolTip(format_action_tooltip(action.text(), action.shortcuts()))
            self.magnifier_button.setAccessibleName(action.text())
            self.magnifier_button.setAccessibleDescription(action.statusTip())

    def retranslate_ui(self, _language=None):
        # Transient strings have no translation identity. Clear them instead
        # of resurrecting an old-language result after a timer/menu closes.
        self._hover = ""
        self._discard_notice()
        self._sync_magnifier_copy()
        self.setAccessibleName(tr("workbenchStatus.title"))
        self.message_label.setAccessibleName(tr("workbenchStatus.message"))
        self.details_button.setText(tr("workbenchStatus.details"))
        self.details_button.setToolTip(tr("workbenchStatus.detailsTitle"))
        self.details_button.setAccessibleName(tr("workbenchStatus.detailsTitle"))
        self.coordinates.setAccessibleName(tr("canvas.pointerCoordinates"))
        self.dimensions.setAccessibleName(tr("canvas.annotationSize"))
        self.coordinates.setToolTip(tr("canvas.pointerCoordinates"))
        self.dimensions.setToolTip(tr("canvas.annotationSize"))
        self._refresh_message()
        self._refresh_metrics()
