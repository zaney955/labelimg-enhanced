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
    paint_box: bool
    paint_label: bool


class DrawingSceneCache:
    # At most 64 MiB for the retained ARGB layer, even for oversized grabs.
    MAX_PIXELS = 16 * 1024 * 1024

    def __init__(self):
        self.clear()

    def clear(self):
        self._key = None
        self._entries = {}
        self._layer = QPixmap()

    def paint(self, painter, shapes, viewport, is_visible, clip_region=None, presentation=None):
        """Update damaged annotations, then composite the layer in widget space.

        is_visible receives the shape and its cached geometric bounds; clip_region
        is an optional widget-space visible region applied only during composition.
        presentation optionally returns separate box/label visibility. Component changes
        damage only affected entries and their intersecting peers. This method returns
        False to request ordinary rendering when the viewport exceeds the budget.
        """
        density = painter.device().devicePixelRatioF()
        width, height = ceil(viewport.width() * density), ceil(viewport.height() * density)
        if width <= 0 or height <= 0 or width * height > self.MAX_PIXELS:
            self.clear()
            return False

        transform = painter.worldTransform()
        key = (viewport, transform, density, shapes[0].scale if shapes else 1,
               shapes[0].label_font_size if shapes else 0,
               shapes[0].line_width if shapes else 1.5, tuple(shapes))
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
                padding = max(shape.line_width / 2.0 + 2.0, shape.point_size * 2.0 + 2.0)
                paint_bounds = paint_bounds.adjusted(-padding, -padding, padding, padding)
                paint_bounds = paint_bounds.toAlignedRect()
            else:
                bounds, paint_bounds = old.bounds, old.paint_bounds
            visible = is_visible(shape, bounds)
            paint_box, paint_label = (
                presentation(shape, bounds) if presentation is not None
                else (True, shape.paint_label)
            )
            entry = _Entry(signature, bounds, paint_bounds, visible, paint_box, paint_label)
            entries[shape] = entry
            display_changed = old is None or (paint_box, paint_label) != (old.paint_box, old.paint_label)
            if not rebuild and (changed or display_changed or visible != old.visible):
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
                    options = {}
                    if not entry.paint_box:
                        options["paint_box"] = False
                    if entry.paint_label != shape.paint_label:
                        options["paint_label"] = entry.paint_label
                    if entry.paint_box or entry.paint_label:
                        shape.paint(recorder, **options)
            recorder.end()

        painter.save()
        painter.resetTransform()
        if clip_region is not None:
            # Composite a moving cutout without rerasterizing static annotations.
            painter.setClipRegion(clip_region, Qt.IntersectClip)
        painter.drawPixmap(QPointF(viewport.topLeft()), self._layer)
        painter.restore()
        return True
