"""Small top-level Qt window construction helpers."""

from labelimg.ui.actions import add_actions
from labelimg.ui.tool_bar import ToolBar
from labelimg.ui.menu import Menu

class WindowMixin(object):

    def menu(self, title, actions=None):
        menu = Menu(title, self)
        self.menuBar().addMenu(menu)
        if actions:
            add_actions(menu, actions)
        return menu

    def toolbar(self, title, actions=None):
        toolbar = ToolBar(title)
        toolbar.setObjectName(u'%sToolBar' % title)
        # toolbar.setOrientation(Qt.Vertical)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        if actions:
            add_actions(toolbar, actions)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        return toolbar

