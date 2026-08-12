"""Annotation label-list rendering and interaction."""

from PyQt5.QtCore import QModelIndex, QPersistentModelIndex, QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QPainter, QPainterPath, QPalette, QPen
from PyQt5.QtWidgets import QListWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem

class LabelListItemDelegate(QStyledItemDelegate):
    selection_marker_width = 3
    selection_marker_inset = 4
    selection_marker_radius = 1.5
    visibility_area_width = 24
    visibility_icon_size = 16
    visible_icon_opacity = 0.8
    hidden_icon_opacity = 0.35
    hovered_icon_opacity = 1.0
    hover_border_width = 1.0
    hover_border_inset = 1.0
    hover_border_radius = 3.0

    def initStyleOption(self, option, index):
        super(LabelListItemDelegate, self).initStyleOption(option, index)
        option.features &= ~QStyleOptionViewItem.HasCheckIndicator

    def paint(self, painter, option, index):
        paint_option = QStyleOptionViewItem(option)
        row_rect = self.visible_row_rect(option)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = (
            option.widget is not None
            and hasattr(option.widget, 'row_hovered')
            and option.widget.row_hovered(index)
        )
        paint_option.state &= ~QStyle.State_MouseOver
        if selected:
            paint_option.state &= ~QStyle.State_Selected
            paint_option.state &= ~QStyle.State_HasFocus
            paint_option.font.setBold(True)

        background = index.data(Qt.BackgroundRole)
        if isinstance(background, QBrush) and background.style() != Qt.NoBrush:
            painter.fillRect(row_rect, background)

        paint_option.rect = row_rect.adjusted(
            0,
            0,
            -self.visibility_area_width,
            0,
        )
        super(LabelListItemDelegate, self).paint(
            painter,
            paint_option,
            index,
        )

        if hovered:
            self.paint_hover_border(painter, option, row_rect)

        if selected:
            painter.save()
            palette = (
                option.widget.palette()
                if option.widget is not None
                else option.palette
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(palette.color(QPalette.Highlight))
            marker_rect = QRectF(
                row_rect.left(),
                row_rect.top() + self.selection_marker_inset,
                self.selection_marker_width,
                max(
                    0,
                    row_rect.height()
                    - (2 * self.selection_marker_inset),
                ),
            )
            painter.drawRoundedRect(
                marker_rect,
                self.selection_marker_radius,
                self.selection_marker_radius,
            )
            painter.restore()

        self.paint_visibility_icon(painter, option, index, row_rect)

    def paint_hover_border(self, painter, option, row_rect):
        palette = (
            option.widget.palette()
            if option.widget is not None
            else option.palette
        )
        border_rect = QRectF(row_rect).adjusted(
            self.hover_border_inset,
            self.hover_border_inset,
            -self.hover_border_inset,
            -self.hover_border_inset,
        )
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(
            palette.color(QPalette.Mid),
            self.hover_border_width,
            Qt.SolidLine,
            Qt.RoundCap,
            Qt.RoundJoin,
        ))
        painter.drawRoundedRect(
            border_rect,
            self.hover_border_radius,
            self.hover_border_radius,
        )
        painter.restore()

    def visible_row_rect(self, option):
        row_rect = QRect(option.rect)
        if option.widget is not None and hasattr(option.widget, 'viewport'):
            row_rect.setRight(
                min(
                    row_rect.right(),
                    option.widget.viewport().width() - 1,
                )
            )
        return row_rect

    def paint_visibility_icon(self, painter, option, index, row_rect):
        checked = index.data(Qt.CheckStateRole) == Qt.Checked
        hovered = (
            option.widget is not None
            and hasattr(option.widget, 'visibility_icon_hovered')
            and option.widget.visibility_icon_hovered(index)
        )
        if hovered:
            opacity = self.hovered_icon_opacity
        elif checked:
            opacity = self.visible_icon_opacity
        else:
            opacity = self.hidden_icon_opacity

        palette = (
            option.widget.palette()
            if option.widget is not None
            else option.palette
        )
        icon_rect = self.visibility_icon_rect(row_rect)
        center = icon_rect.center()
        left = icon_rect.left() + 1.5
        right = icon_rect.right() - 1.5
        top = center.y() - 4
        bottom = center.y() + 4

        eye_path = QPainterPath()
        eye_path.moveTo(left, center.y())
        eye_path.cubicTo(
            left + 3,
            top,
            right - 3,
            top,
            right,
            center.y(),
        )
        eye_path.cubicTo(
            right - 3,
            bottom,
            left + 3,
            bottom,
            left,
            center.y(),
        )

        color = palette.color(QPalette.Text)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setOpacity(opacity)
        painter.setPen(
            QPen(
                color,
                1.5,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        )
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(eye_path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(center, 2.25, 2.25)

        if not checked:
            painter.setPen(
                QPen(
                    color,
                    2,
                    Qt.SolidLine,
                    Qt.RoundCap,
                    Qt.RoundJoin,
                )
            )
            painter.drawLine(
                QPointF(icon_rect.left() + 2, icon_rect.top() + 2),
                QPointF(icon_rect.right() - 2, icon_rect.bottom() - 2),
            )
        painter.restore()

    def visibility_icon_rect(self, row_rect):
        area_left = (
            row_rect.x()
            + row_rect.width()
            - self.visibility_area_width
        )
        icon_left = area_left + (
            self.visibility_area_width - self.visibility_icon_size
        ) / 2.0
        icon_top = row_rect.y() + (
            row_rect.height() - self.visibility_icon_size
        ) / 2.0
        return QRectF(
            icon_left,
            icon_top,
            self.visibility_icon_size,
            self.visibility_icon_size,
        )


class LabelListWidget(QListWidget):
    """Label list with Explorer-style selection and independent visibility checks."""

    rowHoverChanged = pyqtSignal(object)

    def __init__(self, *args, **kwargs):
        super(LabelListWidget, self).__init__(*args, **kwargs)
        self._visibility_press_item = None
        self._visibility_hover_index = QPersistentModelIndex()
        self._row_hover_index = QPersistentModelIndex()
        self._projected_hover_index = QPersistentModelIndex()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideRight)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def visibility_rect(self, index):
        row_rect = self.visualRect(index)
        visible_right = min(
            row_rect.right(),
            self.viewport().width() - 1,
        )
        return QRect(
            visible_right
            - LabelListItemDelegate.visibility_area_width
            + 1,
            row_rect.y(),
            LabelListItemDelegate.visibility_area_width,
            row_rect.height(),
        )

    def visibility_icon_hovered(self, index):
        return (
            self._visibility_hover_index.isValid()
            and self._visibility_hover_index == index
        )

    def row_hovered(self, index):
        return (
            (
                self._row_hover_index.isValid()
                and self._row_hover_index == index
            )
            or (
                self._projected_hover_index.isValid()
                and self._projected_hover_index == index
            )
        )

    def hovered_item(self):
        if not self._row_hover_index.isValid():
            return None
        return self.itemFromIndex(QModelIndex(self._row_hover_index))

    def set_row_hover_index(self, index):
        changed = self._set_hover_index('_row_hover_index', index)
        if changed:
            self.rowHoverChanged.emit(self.hovered_item())

    def set_projected_hover_item(self, item):
        index = (
            self.indexFromItem(item)
            if item is not None
            else QModelIndex()
        )
        self._set_hover_index('_projected_hover_index', index)

    def _set_hover_index(self, attribute, index):
        persistent_index = (
            QPersistentModelIndex(index)
            if index.isValid()
            else QPersistentModelIndex()
        )
        previous = getattr(self, attribute)
        if persistent_index == previous:
            return False

        setattr(self, attribute, persistent_index)
        if previous.isValid():
            self.viewport().update(self.visualRect(QModelIndex(previous)))
        if persistent_index.isValid():
            self.viewport().update(
                self.visualRect(QModelIndex(persistent_index))
            )
        return True

    def set_visibility_hover_index(self, index):
        persistent_index = (
            QPersistentModelIndex(index)
            if index.isValid()
            else QPersistentModelIndex()
        )
        if persistent_index == self._visibility_hover_index:
            return

        previous = self._visibility_hover_index
        self._visibility_hover_index = persistent_index
        if previous.isValid():
            self.viewport().update(
                self.visualRect(QModelIndex(previous))
            )
        if persistent_index.isValid():
            self.viewport().update(
                self.visualRect(QModelIndex(persistent_index))
            )

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.pos())
        self.set_row_hover_index(index)
        if (
            index.isValid()
            and self.visibility_rect(index).contains(event.pos())
        ):
            self.set_visibility_hover_index(index)
        else:
            self.set_visibility_hover_index(QModelIndex())
        super(LabelListWidget, self).mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.set_visibility_hover_index(QModelIndex())
        self.set_row_hover_index(QModelIndex())
        super(LabelListWidget, self).leaveEvent(event)

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            item = self.itemFromIndex(index)
            if (
                event.button() == Qt.LeftButton
                and item.flags() & Qt.ItemIsUserCheckable
                and self.visibility_rect(index).contains(event.pos())
            ):
                self._visibility_press_item = item
                item.setCheckState(
                    Qt.Unchecked
                    if item.checkState() == Qt.Checked
                    else Qt.Checked
                )
                event.accept()
                return
        elif (
            event.button() == Qt.LeftButton
            and event.modifiers() == Qt.NoModifier
        ):
            self.clearSelection()
            self.setCurrentItem(None)

        super(LabelListWidget, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._visibility_press_item is not None:
            self._visibility_press_item = None
            event.accept()
            return
        super(LabelListWidget, self).mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key_A
            and event.modifiers() & Qt.ControlModifier
        ):
            window = self.window()
            if hasattr(window, 'actions'):
                window.actions.showAll.trigger()
            event.accept()
            return
        super(LabelListWidget, self).keyPressEvent(event)

