"""A bounded, derived annotation layer for the otherwise static Draw-mode scene."""

from dataclasses import dataclass
from math import ceil

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QPainter, QPixmap, QRegion


@dataclass
class _Entry:
    signature: tuple
    bounds: QRectF
    paint_bounds: QRect
    visible: bool


class DrawingSceneCache:
    # At most 64 MiB for the retained ARGB layer, even for oversized grabs.
    MAX_PIXELS = 16 * 1024 * 1024

    def __init__(self):
        self.clear()

    def clear(self):
        self._key = None
        self._entries = {}
        self._layer = QPixmap()

    def paint(self, painter, shapes, viewport, is_visible):
        """Update damaged annotations, then composite the layer in widget space.

        is_visible receives the shape and its cached geometric bounds. This method
        returns False to request ordinary rendering when the viewport exceeds the budget.
        """
        density = painter.device().devicePixelRatioF()
        width, height = ceil(viewport.width() * density), ceil(viewport.height() * density)
        if width <= 0 or height <= 0 or width * height > self.MAX_PIXELS:
            self.clear()
            return False

        transform = painter.worldTransform()
        key = (viewport, transform, density, shapes[0].scale if shapes else 1,
               shapes[0].label_font_size if shapes else 0, tuple(shapes))
        rebuild = key != self._key
        if rebuild:
            self._layer = QPixmap(width, height)
            self._layer.setDevicePixelRatio(density)
            self._layer.fill(Qt.transparent)
            self._entries = {}
            self._key = key
        damage = QRegion(viewport) if rebuild else QRegion()
        entries = {}
        for shape in shapes:
            signature = (
                tuple((point.x(), point.y()) for point in shape.points),
                shape.label, shape.paint_label, shape.line_color.rgba(),
                shape.selected, shape.is_closed(), shape.point_type, shape.point_size,
                shape._highlight_index, shape._highlight_mode,
            )
            old = self._entries.get(shape)
            changed = old is None or signature != old.signature
            if changed:
                bounds = shape.bounding_rect().normalized()
                paint_bounds = transform.mapRect(bounds)
                if shape.paint_label:
                    label_bounds = shape.label_text_rect()
                    if label_bounds is not None:
                        paint_bounds = paint_bounds.united(transform.mapRect(label_bounds))
                # Covers the largest highlighted handle, outline AA and label padding.
                padding = max(3.0, shape.point_size * 2.0 + 2.0)
                paint_bounds = paint_bounds.adjusted(-padding, -padding, padding, padding)
                paint_bounds = paint_bounds.toAlignedRect()
            else:
                bounds, paint_bounds = old.bounds, old.paint_bounds
            visible = is_visible(shape, bounds)
            entry = _Entry(signature, bounds, paint_bounds, visible)
            entries[shape] = entry
            if not rebuild and (changed or visible != old.visible):
                if old.visible:
                    damage |= QRegion(old.paint_bounds)
                if visible:
                    damage |= QRegion(paint_bounds)
        damage &= QRegion(viewport)
        self._entries = entries

        if not damage.isEmpty():
            recorder = QPainter(self._layer)
            recorder.setRenderHints(painter.renderHints())
            recorder.translate(-viewport.x(), -viewport.y())
            recorder.setClipRegion(damage)
            recorder.setCompositionMode(QPainter.CompositionMode_Source)
            recorder.fillRect(viewport, Qt.transparent)
            recorder.setCompositionMode(QPainter.CompositionMode_SourceOver)
            recorder.setWorldTransform(transform, True)
            for shape, entry in entries.items():
                if entry.visible and damage.intersects(entry.paint_bounds):
                    shape.fill = shape.selected
                    shape.paint(recorder)
            recorder.end()

        painter.save()
        painter.resetTransform()
        painter.drawPixmap(QPointF(viewport.topLeft()), self._layer)
        painter.restore()
        return True
