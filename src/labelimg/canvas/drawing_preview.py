"""Screen-sized reverse-screen presentation for an unfinished annotation."""

from math import floor

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker


_OUTLINE_WIDTH = 1.5
_START_RADIUS = 2.0
_INTERIOR_FILL = QColor(255, 255, 255, 15)  # Approximately 6% white.


def paint_pending_box(painter, image_size, start, end, *, drawing=True, guide_bounds=None, outline_width=_OUTLINE_WIDTH):
    """Invert displayed pixels once, like a Windows reverse-screen cursor.

    Fully covered RGB channels become 255 minus their displayed values; only
    the antialiased boundary has partial coverage. Building a single union
    prevents crossings and coincident guides/edges from being inverted twice.
    ``drawing=False`` keeps the outline and interior lift while the first label
    is pending, without the start marker or alignment guides. ``guide_bounds``
    extends the shared crosshair through Canvas margins in scene coordinates.
    """
    image_bounds = QRectF(0, 0, image_size.width(), image_size.height())
    if image_bounds.isEmpty():
        return

    scale = max(painter.worldTransform().m11(), 0.01)
    outline = QPainterPath()
    outline.addRect(QRectF(start, end).normalized())
    image_clip = QPainterPath()
    image_clip.addRect(image_bounds)
    mask = _stroke(outline, outline_width / scale).intersected(image_clip)
    crosshair_bounds = image_bounds if guide_bounds is None else QRectF(guide_bounds)

    if drawing:
        mask = mask.united(_crosshair_mask(painter, crosshair_bounds, end, outline_width))

        marker = QPainterPath()
        radius = _START_RADIUS / scale
        marker.addEllipse(QPointF(start), radius, radius)
        mask = mask.united(marker.intersected(image_clip))

    painter.save()
    painter.setClipRect(crosshair_bounds if drawing else image_bounds, Qt.IntersectClip)
    # Keep the subtle interior lift out of the reverse-screen geometry so the
    # outline, guides and marker retain their existing pixel inversion.
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.fillPath(outline.intersected(image_clip).subtracted(mask), _INTERIOR_FILL)
    # White difference is exact RGB inversion without a brightness threshold,
    # palette approximation, or sampling that could move as the rectangle grows.
    painter.setCompositionMode(QPainter.CompositionMode_Difference)
    painter.fillPath(mask, QColor(Qt.white))
    painter.restore()


def paint_drawing_crosshair(painter, bounds, position, *, line_width=_OUTLINE_WIDTH):
    """Extend the reverse-screen cursor with the configured screen-space width."""
    if bounds.isEmpty():
        return
    painter.save()
    painter.setClipRect(bounds, Qt.IntersectClip)
    painter.setCompositionMode(QPainter.CompositionMode_Difference)
    painter.fillPath(_crosshair_mask(painter, bounds, position, line_width), QColor(Qt.white))
    painter.restore()


def _crosshair_mask(painter, bounds, position, line_width):
    transform = painter.worldTransform()
    scale = max(transform.m11(), 0.01)
    density = painter.device().devicePixelRatioF()
    screen = transform.map(position)
    # Align one edge of the configured stroke to device pixels for crisp inversion.
    half = line_width / 2.0
    x = floor((screen.x() - half) * density + 0.5) / density + half
    y = floor((screen.y() - half) * density + 0.5) / density + half
    inverse, _invertible = transform.inverted()
    position = inverse.map(QPointF(x, y))
    guides = QPainterPath()
    guides.moveTo(bounds.left(), position.y())
    guides.lineTo(bounds.right(), position.y())
    guides.moveTo(position.x(), bounds.top())
    guides.lineTo(position.x(), bounds.bottom())
    return _stroke(guides, line_width / scale)


def _stroke(path, width):
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.SquareCap)
    stroker.setJoinStyle(Qt.MiterJoin)
    return stroker.createStroke(path)
