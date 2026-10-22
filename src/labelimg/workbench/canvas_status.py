"""Canvas-local readouts and zoom, independent of application notifications."""

from PyQt5.QtCore import QEvent, QSize, Qt
from PyQt5.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QToolButton

from labelimg.ui.actions import format_action_tooltip

from labelimg.localization.runtime import language_changed, tr


class CanvasStatusStrip(QFrame):
    def __init__(self, zoom_control, parent=None):
        super().__init__(parent)
        self.setObjectName("canvasStatusStrip")
        self.setAutoFillBackground(True)
        self.zoom = zoom_control
        self.view_controls = QFrame(self)
        controls = QHBoxLayout(self.view_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        self.magnifier_button = QToolButton(self.view_controls)
        self.magnifier_button.setObjectName('crosshairMagnifierButton')
        self.magnifier_button.setAutoRaise(True)
        self.magnifier_button.setFixedSize(28, 28)
        self.magnifier_button.setIconSize(QSize(20, 20))
        self.magnifier_button.setFocusPolicy(Qt.StrongFocus)
        controls.addWidget(self.magnifier_button)
        controls.addWidget(self.zoom)
        self.coordinates = QLabel("X: —  Y: —", self)
        self.dimensions = QLabel("", self)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(8, 4, 8, 4)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(4)
        # The single-row size hint must not prevent shrinking into two rows.
        self._grid.setSizeConstraint(QLayout.SetNoConstraint)
        self._grid.setColumnStretch(2, 1)
        self.set_image_size(QSize())
        self.zoom.installEventFilter(self)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    @property
    def stacked(self):
        return self._grid.getItemPosition(self._grid.indexOf(self.view_controls))[0] > 0

    def set_image_size(self, size):
        # Reserve the widest possible numbers for this image before interaction.
        # Empty W/H and digit changes must not move the slider.
        for label, names in ((self.coordinates, ("X", "Y")),
                             (self.dimensions, ("W", "H"))):
            metrics = label.fontMetrics()
            digit = max("0123456789", key=metrics.horizontalAdvance)
            values = [digit * max(3, len(str(max(0, value))))
                      for value in (size.width(), size.height())]
            sample = "%s: %s  %s: %s" % (
                names[0], values[0], names[1], values[1],
            )
            label.setFixedWidth(metrics.horizontalAdvance(sample) + 2)
            label.setFixedHeight(metrics.height())
        self._arrange()

    def _arrange(self):
        available = max(0, self.width() - 16)
        widths = [self.coordinates.width(), self.dimensions.width()]
        readout_width = sum(widths) + 16
        zoom_chrome = (self.zoom.sizeHint().width() - self.zoom.slider.width()
                       + self.magnifier_button.width() + 6)
        fits_full_zoom = available >= readout_width + 16 + zoom_chrome + 112
        self.zoom.set_slider_width(min(
            112 if fits_full_zoom else 80, max(64, available - zoom_chrome),
        ))
        readout_rows = 1 if available >= readout_width else 2
        stacked = available < readout_width + 16 + zoom_chrome + 80
        self._grid.addWidget(self.coordinates, 0, 0, Qt.AlignLeft)
        self._grid.addWidget(self.dimensions, readout_rows - 1,
                             1 if readout_rows == 1 else 0, Qt.AlignLeft)
        self._grid.addWidget(
            self.view_controls, readout_rows if stacked else 0,
            0 if stacked else 2, 1, 3 if stacked else 1, Qt.AlignRight,
        )
        text_height = self.coordinates.fontMetrics().height() * readout_rows
        text_height += 4 * (readout_rows - 1)
        zoom_height = max(self.zoom.sizeHint().height(), self.magnifier_button.height())
        height = (text_height + 4 + zoom_height if stacked
                  else max(text_height, zoom_height))
        self.setMinimumWidth(max(*widths, zoom_chrome + 64) + 16)
        self.setFixedHeight(height + 8)
        # Styled controls can change their size hint during the image-size
        # update. Settle the reserved row now, before pointer readouts arrive.
        self._grid.activate()
        self.view_controls.layout().activate()
        self.zoom.layout().activate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def eventFilter(self, watched, event):
        if watched is self.zoom and event.type() == QEvent.LayoutRequest:
            self._arrange()
        return super().eventFilter(watched, event)

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
        self._sync_magnifier_copy()
        self.setAccessibleName(tr("canvas.status"))
        self.coordinates.setAccessibleName(tr("canvas.pointerCoordinates"))
        self.dimensions.setAccessibleName(tr("canvas.annotationSize"))
        self.coordinates.setToolTip(tr("canvas.pointerCoordinates"))
        self.dimensions.setToolTip(tr("canvas.annotationSize"))
