"""Native menus and combo popups with independent state/artwork and roomy rows."""

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QIcon
from PyQt5.QtWidgets import QComboBox, QStyle, QStyleOptionMenuItem, QStyledItemDelegate

from labelimg.ui.theme import COLORS


class PopupItemDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(32, size.height(), option.fontMetrics.height() + 12))
        size.setWidth(size.width() + 16)
        return size


class ComboBox(QComboBox):
    """Application dropdowns share spacing without a global Qt event filter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # The view owns its delegate so it cannot outlive a sibling delegate
        # during native Qt destruction at application exit.
        self._popup_delegate = PopupItemDelegate(self.view())
        self.setItemDelegate(self._popup_delegate)
        self.setMaxVisibleItems(12)

    def showPopup(self):
        # Qt can replace a combo's default delegate when its editable mode changes.
        if self.itemDelegate() is not self._popup_delegate:
            self.setItemDelegate(self._popup_delegate)
        super().showPopup()


def draw_menu_item(option, painter):
    # QMenu still owns hit testing, QAction dispatch, shortcuts and accessibility.
    from labelimg.ui.icons import outline_icon, paint_icon

    rect = option.rect
    painter.save()
    if option.menuItemType == QStyleOptionMenuItem.Separator:
        painter.setPen(QColor(COLORS['divider']))
        painter.drawLine(rect.left() + 8, rect.center().y(), rect.right() - 8, rect.center().y())
        painter.restore()
        return
    enabled = bool(option.state & QStyle.State_Enabled)
    selected = bool(option.state & QStyle.State_Selected)
    if selected:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS['selection_background']))
        painter.drawRoundedRect(rect.adjusted(1, 0, -1, 0), 3, 3)
    ink = COLORS['selection_foreground' if selected else 'text'] if enabled else COLORS['disabled_text']

    def box(x, width=16):
        logical = QRect(rect.left() + x, rect.center().y() - 8, width, 16)
        return QStyle.visualRect(option.direction, rect, logical)

    if option.checked:
        outline_icon('done', ink).paint(painter, box(6))
    if not option.icon.isNull():
        option.icon.paint(painter, box(28), Qt.AlignCenter, QIcon.Normal if enabled else QIcon.Disabled)
    title, _, shortcut = option.text.partition('\t')
    font = option.font
    if option.menuItemType == QStyleOptionMenuItem.DefaultItem:
        font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(ink))
    text_rect = QStyle.visualRect(option.direction, rect, rect.adjusted(54, 0, -24, 0))
    leading = Qt.AlignRight if option.direction == Qt.RightToLeft else Qt.AlignLeft
    trailing = Qt.AlignLeft if option.direction == Qt.RightToLeft else Qt.AlignRight
    painter.drawText(text_rect, leading | Qt.AlignVCenter | Qt.TextShowMnemonic, title)
    if shortcut:
        painter.drawText(text_rect, trailing | Qt.AlignVCenter, shortcut)
    if option.menuItemType == QStyleOptionMenuItem.SubMenu:
        paint_icon(painter, box(rect.width() - 20),
                   'chevron-left' if option.direction == Qt.RightToLeft else 'chevron-right',
                   enabled=enabled, size=16)
    painter.restore()
