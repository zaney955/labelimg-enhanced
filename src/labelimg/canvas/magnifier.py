"""A paint-only loupe sampling the displayed image around the drawing center."""

from math import ceil

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

from labelimg.localization.runtime import tr
from labelimg.ui.theme import COLORS

from labelimg.canvas.drawing_preview import paint_drawing_crosshair


def magnifier_rect(center, viewport, protected_rect=None, *, outline_width=1.5):
    """Fit beside the entire pending box; never clamp a loupe back over it.

    Every disjoint axis-aligned rectangle is wholly above, below, left, or
    right of the protected rectangle. Searching those four strips therefore
    also finds safe placements beyond the cursor's immediate quadrants.
    Prefer full size, then compact detail, and hide when neither fits.
    All geometry is in Canvas widget coordinates, independent of drawing direction.
    """
    bounds = QRectF(viewport).adjusted(6, 6, -6, -6)
    if bounds.isEmpty():
        return QRectF()
    protected = QRectF(protected_rect).normalized() if protected_rect is not None else QRectF(
        center.x(), center.y(), 0, 0,
    )
    # Include the cursor even before a nonzero-area rectangle exists. Account
    # for the outline, antialiasing, and a small visual gap on every side.
    left, right = min(protected.left(), center.x()), max(protected.right(), center.x())
    top, bottom = min(protected.top(), center.y()), max(protected.bottom(), center.y())
    clearance = max(8.0, outline_width / 2.0 + 2.0)
    protected = QRectF(left, top, right - left, bottom - top).adjusted(
        -clearance, -clearance, clearance, clearance,
    )
    left = max(bounds.left(), min(bounds.right(), protected.left()))
    right = max(bounds.left(), min(bounds.right(), protected.right()))
    top = max(bounds.top(), min(bounds.bottom(), protected.top()))
    bottom = max(bounds.top(), min(bounds.bottom(), protected.bottom()))
    strips = (
        QRectF(right, bounds.top(), bounds.right() - right, bounds.height()),
        QRectF(bounds.left(), bottom, bounds.width(), bounds.bottom() - bottom),
        QRectF(bounds.left(), bounds.top(), left - bounds.left(), bounds.height()),
        QRectF(bounds.left(), bounds.top(), bounds.width(), top - bounds.top()),
    )
    preferred_x, preferred_y = center.x() + 20.0, center.y() + 20.0

    def candidates(compact):
        for strip in strips:
            width = min(160.0, strip.width()) if compact else 160.0
            height = min(176.0, strip.height()) if compact else 176.0
            if width < 64 or height < 80 or width > strip.width() or height > strip.height():
                continue
            x = max(strip.left(), min(preferred_x, strip.right() - width))
            y = max(strip.top(), min(preferred_y, strip.bottom() - height))
            rect = QRectF(x, y, width, height)
            # Final checks include the full loupe, including its footer/border.
            if bounds.contains(rect) and not protected.intersects(rect):
                distance = (x - preferred_x) ** 2 + (y - preferred_y) ** 2
                yield rect, distance

    full_size = list(candidates(False))
    if full_size:
        return min(full_size, key=lambda item: item[1])[0]
    compact = list(candidates(True))
    if compact:
        return min(compact, key=lambda item: (
            -item[0].width() * item[0].height(), item[1],
        ))[0]
    return QRectF()


def paint_magnifier(
    painter, pixmap, image_size, center, screen_center, viewport, scale,
    *, protected_rect=None, outline_width=1.5,
):
    """Draw image detail only, at least 4x native resolution and 2x the view."""
    rect = magnifier_rect(
        screen_center, viewport, protected_rect, outline_width=outline_width,
    )
    if rect.isEmpty():
        return
    font = QFont(painter.font())
    font.setPointSizeF(9)
    metrics = QFontMetricsF(font)
    hint = tr('crosshairMagnifier.toggleHint')
    text_width = rect.width() - 12
    hint_height = ceil(metrics.boundingRect(
        QRectF(0, 0, text_width, 1000), Qt.TextWrapAnywhere, hint,
    ).height())
    line_height = ceil(metrics.height())
    footer_height = line_height + hint_height + 8
    content = rect.adjusted(4, 4, -4, -footer_height)
    if content.height() < 16:
        return
    painter.save()
    painter.setClipRect(QRectF(viewport), Qt.IntersectClip)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(COLORS['border']), 1.0))
    painter.setBrush(QColor(COLORS['surface']))
    painter.drawRoundedRect(rect, 8, 8)
    painter.fillRect(content, QColor(COLORS['preview_background']))
    factor = max(4.0, scale * 2.0)
    source = QRectF(
        center.x() - content.width() / factor / 2.0,
        center.y() - content.height() / factor / 2.0,
        content.width() / factor, content.height() / factor,
    )
    clipped = source.intersected(QRectF(0, 0, image_size.width(), image_size.height()))
    painter.save()
    painter.setClipRect(content, Qt.IntersectClip)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
    if not clipped.isEmpty():
        target = QRectF(
            content.left() + (clipped.left() - source.left()) * factor,
            content.top() + (clipped.top() - source.top()) * factor,
            clipped.width() * factor, clipped.height() * factor,
        )
        # The display pixmap can use a different pixel grid from the image.
        sx, sy = pixmap.width() / image_size.width(), pixmap.height() / image_size.height()
        painter.drawPixmap(target, pixmap, QRectF(
            clipped.x() * sx, clipped.y() * sy, clipped.width() * sx, clipped.height() * sy,
        ))
    paint_drawing_crosshair(painter, content, content.center(), line_width=outline_width)
    painter.restore()
    painter.setPen(QColor(COLORS['accent']))
    painter.setFont(font)
    footer_top = content.bottom() + 3
    painter.drawText(
        QRectF(rect.left() + 6, footer_top, text_width, line_height),
        Qt.AlignCenter, ('%.2f' % factor).rstrip('0').rstrip('.') + '×',
    )
    painter.setPen(QColor(COLORS['muted']))
    painter.drawText(
        QRectF(rect.left() + 6, footer_top + line_height, text_width, hint_height),
        Qt.AlignCenter | Qt.TextWrapAnywhere, hint,
    )
    painter.restore()
