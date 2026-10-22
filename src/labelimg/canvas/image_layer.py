"""A viewport-sized raster of the current image, independent of annotations."""
from math import ceil

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QPainter, QPixmap


class ImageLayerCache:
    MAX_PIXELS = 16 * 1024 * 1024

    def __init__(self):
        self.clear()

    def clear(self):
        self._key = None
        self._layer = QPixmap()

    def paint(self, painter, pixmap, logical_size, viewport):
        density = painter.device().devicePixelRatioF()
        # Align the layer origin to device pixels, including fractional DPR.
        viewport = QRectF(viewport)
        x = int(viewport.x() * density) / density
        y = int(viewport.y() * density) / density
        width = ceil((viewport.right() - x) * density)
        height = ceil((viewport.bottom() - y) * density)
        if width <= 0 or height <= 0 or width * height > self.MAX_PIXELS:
            self.clear()
            self._draw_source(painter, pixmap, logical_size)
            return
        origin = QPointF(x, y)
        key = (pixmap.cacheKey(), logical_size, painter.worldTransform(),
               origin, width, height, density, int(painter.renderHints()))
        if key != self._key:
            self._layer = self._rasterize(
                painter, pixmap, logical_size, origin, width, height, density)
            self._key = key
        painter.save()
        painter.resetTransform()
        painter.drawPixmap(origin, self._layer)
        painter.restore()

    def _rasterize(self, painter, pixmap, logical_size, origin, width, height, density):
        layer = QPixmap(width, height)
        layer.setDevicePixelRatio(density)
        layer.fill(Qt.transparent)
        recorder = QPainter(layer)
        recorder.setRenderHints(painter.renderHints())
        recorder.translate(-origin.x(), -origin.y())
        recorder.setWorldTransform(painter.worldTransform(), True)
        self._draw_source(recorder, pixmap, logical_size)
        recorder.end()
        return layer

    @staticmethod
    def _draw_source(painter, pixmap, logical_size):
        painter.drawPixmap(
            QRectF(0, 0, logical_size.width(), logical_size.height()),
            pixmap, QRectF(pixmap.rect()))
