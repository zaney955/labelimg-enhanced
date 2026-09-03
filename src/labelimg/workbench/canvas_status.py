"""Canvas-local readouts and zoom, independent of application notifications."""

from PyQt5.QtCore import QEvent, QSize, Qt
from PyQt5.QtWidgets import QFrame, QGridLayout, QLabel, QLayout

from labelimg.localization.runtime import language_changed, tr


class CanvasStatusStrip(QFrame):
    def __init__(self, zoom_control, parent=None):
        super().__init__(parent)
        self.setObjectName("canvasStatusStrip")
        self.setAutoFillBackground(True)
        self.zoom = zoom_control
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
        return self._grid.getItemPosition(self._grid.indexOf(self.zoom))[0] > 0

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
        zoom_chrome = self.zoom.sizeHint().width() - self.zoom.slider.width()
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
            self.zoom, readout_rows if stacked else 0,
            0 if stacked else 2, 1, 3 if stacked else 1, Qt.AlignRight,
        )
        text_height = self.coordinates.fontMetrics().height() * readout_rows
        text_height += 4 * (readout_rows - 1)
        zoom_height = self.zoom.sizeHint().height()
        height = (text_height + 4 + zoom_height if stacked
                  else max(text_height, zoom_height))
        self.setMinimumWidth(max(*widths, zoom_chrome + 64) + 16)
        self.setFixedHeight(height + 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def eventFilter(self, watched, event):
        if watched is self.zoom and event.type() == QEvent.LayoutRequest:
            self._arrange()
        return super().eventFilter(watched, event)

    def retranslate_ui(self, _language=None):
        self.setAccessibleName(tr("canvas.status"))
        self.coordinates.setAccessibleName(tr("canvas.pointerCoordinates"))
        self.dimensions.setAccessibleName(tr("canvas.annotationSize"))
        self.coordinates.setToolTip(tr("canvas.pointerCoordinates"))
        self.dimensions.setToolTip(tr("canvas.annotationSize"))
