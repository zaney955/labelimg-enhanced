"""Screen-sized reverse-screen presentation for an unfinished annotation."""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker


_OUTLINE_WIDTH = 1.5
_GUIDE_WIDTH = 1.0
_START_RADIUS = 2.0
_INTERIOR_FILL = QColor(255, 255, 255, 15)  # Approximately 6% white.


def paint_pending_box(painter, image_size, start, end, *, drawing=True):
    """Invert displayed pixels once, like a Windows reverse-screen cursor.

    Fully covered RGB channels become 255 minus their displayed values; only
    the antialiased boundary has partial coverage. Building a single union
    prevents crossings and coincident guides/edges from being inverted twice.
    ``drawing=False`` keeps the outline and interior lift while the first label
    is pending, without the start marker or alignment guides.
    """
    image_bounds = QRectF(0, 0, image_size.width(), image_size.height())
    if image_bounds.isEmpty():
        return

    scale = max(painter.worldTransform().m11(), 0.01)
    outline = QPainterPath()
    outline.addRect(QRectF(start, end).normalized())
    mask = _stroke(outline, _OUTLINE_WIDTH / scale)

    if drawing:
        guides = QPainterPath()
        guides.moveTo(0, end.y())
        guides.lineTo(image_bounds.right(), end.y())
        guides.moveTo(end.x(), 0)
        guides.lineTo(end.x(), image_bounds.bottom())
        mask = mask.united(_stroke(guides, _GUIDE_WIDTH / scale))

        marker = QPainterPath()
        radius = _START_RADIUS / scale
        marker.addEllipse(QPointF(start), radius, radius)
        mask = mask.united(marker)

    painter.save()
    painter.setClipRect(image_bounds, Qt.IntersectClip)
    # Keep the subtle interior lift out of the reverse-screen geometry so the
    # outline, guides and marker retain their existing pixel inversion.
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.fillPath(outline.subtracted(mask), _INTERIOR_FILL)
    # White difference is exact RGB inversion without a brightness threshold,
    # palette approximation, or sampling that could move as the rectangle grows.
    painter.setCompositionMode(QPainter.CompositionMode_Difference)
    painter.fillPath(mask, QColor(Qt.white))
    painter.restore()


def _stroke(path, width):
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.SquareCap)
    stroker.setJoinStyle(Qt.MiterJoin)
    return stroker.createStroke(path)
