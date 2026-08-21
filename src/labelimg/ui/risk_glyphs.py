"""Small shared risk glyphs for Qt presentation surfaces."""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QPen


def draw_not_equal_glyph(painter, rect, color, width=1.2):
    """Draw a font-independent not-equal glyph inside ``rect``."""
    rect = QRectF(rect)
    inset = max(1.0, float(width))
    left = rect.left() + inset
    right = rect.right() - inset
    center_y = rect.center().y()
    gap = max(1.25, rect.height() * 0.16)
    top = rect.top() + inset
    bottom = rect.bottom() - inset

    painter.save()
    painter.setPen(QPen(
        color,
        float(width),
        Qt.SolidLine,
        Qt.RoundCap,
        Qt.RoundJoin,
    ))
    painter.drawLine(
        QPointF(left, center_y - gap),
        QPointF(right, center_y - gap),
    )
    painter.drawLine(
        QPointF(left, center_y + gap),
        QPointF(right, center_y + gap),
    )
    painter.drawLine(
        QPointF(right - inset * 0.35, top),
        QPointF(left + inset * 0.35, bottom),
    )
    painter.restore()
