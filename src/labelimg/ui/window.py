"""Small top-level Qt window construction helpers."""

from labelimg.ui.actions import add_actions
from labelimg.ui.menu import Menu

class WindowMixin(object):

    def menu(self, title, actions=None):
        menu = Menu(title, self)
        self.menuBar().addMenu(menu)
        if actions:
            add_actions(menu, actions)
        return menu
