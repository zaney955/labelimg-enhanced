"""QMenu interaction with separate command-icon and checked-state columns."""

from PyQt5.QtGui import QColor, QIcon, QPainter
from PyQt5.QtWidgets import QMenu, QStyleOptionMenuItem, QWidgetAction

from labelimg.ui.control_style import draw_menu_item
from labelimg.ui.theme import COLORS


class Menu(QMenu):
    def __init__(self, *args):
        super().__init__(*args)
        self.setProperty('labelimgMenu', True)

    def addMenu(self, *args):
        if len(args) == 1 and isinstance(args[0], str):
            menu = Menu(args[0], self)
            super().addMenu(menu)
            return menu
        if len(args) == 2 and isinstance(args[0], QIcon):
            menu = Menu(args[1], self)
            menu.setIcon(args[0])
            super().addMenu(menu)
            return menu
        return super().addMenu(*args)

    def paintEvent(self, event):
        # Retain the native frame, scrolling arrows and embedded widget actions.
        super().paintEvent(event)
        painter = QPainter(self)
        for action in self.actions():
            rect = self.actionGeometry(action)
            if not action.isVisible() or not rect.intersects(event.rect()):
                continue
            if isinstance(action, QWidgetAction) and action.defaultWidget() is not None:
                continue
            option = QStyleOptionMenuItem()
            self.initStyleOption(option, action)
            option.rect = rect
            painter.fillRect(rect, QColor(COLORS['surface']))
            draw_menu_item(option, painter)
