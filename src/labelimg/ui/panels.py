"""Shared dock chrome and workspace sections, independent of feature commands."""

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
)
from labelimg.localization.runtime import language_changed, tr
from labelimg.ui.icons import IconLabel, icon
from labelimg.ui.theme import theme_style

PANEL_STYLE = theme_style("""
QDockWidget { background: transparent; border: none; }
QFrame[uiRole="panelHeader"] { background: ${panel_header}; border: 1px solid ${panel_border};
    border-bottom-color: ${divider}; border-top-left-radius: 5px; border-top-right-radius: 5px; }
QLabel[uiRole="panelTitle"] { color: ${text}; font-size: 12px; font-weight: 600; background: transparent; border: none; }
QLabel[uiRole="panelCount"] { color: ${muted}; font-size: 10px; background: ${surface};
    border: none; border-radius: 4px; padding: 2px 5px; }
QFrame[uiRole="panelBody"], QWidget[uiRole="panelBody"] { background: ${surface};
    border: 1px solid ${panel_border}; border-top: none; border-bottom-left-radius: 5px; border-bottom-right-radius: 5px; }
QFrame[uiRole="panelContext"] { background: ${surface}; border: none; border-bottom: 1px solid ${divider}; }
QFrame[uiRole="panelList"] { background: ${surface}; border: none; }
QFrame[uiRole="panelFooter"] { background: ${panel_header}; border: none; border-top: 1px solid ${divider}; }
QToolButton[panelAction="true"] { min-height: 0; border: 1px solid transparent; border-radius: 4px; padding: 0; }
QToolButton[panelAction="true"]:hover { background: ${selected}; }
QToolButton[panelAction="true"]:focus { border-color: ${accent}; }
QToolButton[panelAction="true"]::menu-indicator { image: none; }
QToolButton[panelAction="true"][uiRole="menuButton"] { padding-right: 18px; }
QFrame[uiRole="panelHeader"]:focus { border-color: ${accent}; }
""")


class PanelHeader(QFrame):
    HEIGHT = 38

    def __init__(self, dock, artwork, title=None, count=None):
        super().__init__(dock)
        self.dock = dock
        self.setProperty("uiRole", "panelHeader")
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.OpenHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(10, 0, 10, 0)
        self.row.setSpacing(6)
        glyph = IconLabel(artwork, size=16)
        glyph.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.row.addWidget(glyph)
        self.title = title or QLabel(dock.windowTitle())
        self.title.setProperty("uiRole", "panelTitle")
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.row.addWidget(self.title)
        self.count = count or QLabel()
        self.count.setProperty("uiRole", "panelCount")
        self.count.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.count.setTextFormat(Qt.PlainText)
        self.count.setFixedHeight(20)
        self.count.setMaximumWidth(112)
        self.row.addWidget(self.count)
        self.row.addStretch(1)
        dock.windowTitleChanged.connect(self._sync_title)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        dock.setTitleBarWidget(self)
        dock.panel_header = self

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(hint.width(), self.HEIGHT)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(hint.width(), self.HEIGHT)

    def add_control(self, widget, *, text=False):
        widget.setProperty("panelAction", True)
        widget.setCursor(Qt.ArrowCursor)
        widget.setFixedHeight(26)
        if not text:
            widget.setFixedWidth(26)
        widget.setAccessibleName(widget.accessibleName() or widget.toolTip())
        close = getattr(self, "close_button", None)
        if close is not None and widget is not close:
            self.row.insertWidget(self.row.indexOf(close), widget)
        else:
            self.row.addWidget(widget)

    def set_count(self, text, detail=""):
        self.count.setText(str(text))
        self.count.setVisible(bool(str(text)))
        self.count.setToolTip(detail)
        self.count.setAccessibleName(detail or str(text))

    def _sync_title(self, text):
        self.title.setText(text)
        self.setAccessibleName(text)

    def retranslate_ui(self, _language=None):
        self.setToolTip(tr("panels.moveTip"))
        self.setAccessibleName(self.dock.windowTitle())

    def move_to(self, area):
        window = self.dock.parentWidget()
        self.dock.setFloating(False)
        window.addDockWidget(area, self.dock)
        self.dock.show()

    def toggle_floating(self):
        self.dock.setFloating(not self.dock.isFloating())
        self.dock.show()

    def position_menu(self):
        menu = QMenu(self)
        window = self.dock.parentWidget()
        for key, area in (
            ("left", Qt.LeftDockWidgetArea),
            ("right", Qt.RightDockWidgetArea),
            ("bottom", Qt.BottomDockWidgetArea),
            ("top", Qt.TopDockWidgetArea),
        ):
            if not self.dock.allowedAreas() & area:
                continue
            action = menu.addAction(tr("panels.move." + key))
            action.setCheckable(True)
            action.setChecked(
                not self.dock.isFloating() and window.dockWidgetArea(self.dock) == area
            )
            action.triggered.connect(
                lambda _checked=False, target=area: self.move_to(target)
            )
        menu.addSeparator()
        action = menu.addAction(
            tr("panels.dock" if self.dock.isFloating() else "panels.float")
        )
        action.triggered.connect(self.toggle_floating)
        if self.dock.features() & QDockWidget.DockWidgetClosable:
            menu.addSeparator()
            close = menu.addAction(icon("close"), tr("standard.close"))
            close.triggered.connect(self.dock.hide)
        return menu

    def _show_menu(self, point):
        menu = self.position_menu()
        menu.exec_(self.mapToGlobal(point))
        menu.deleteLater()


def panel_body(name):
    body = QFrame()
    body.setObjectName(name)
    body.setProperty("uiRole", "panelBody")
    layout = QVBoxLayout(body)
    layout.setContentsMargins(1, 0, 1, 1)
    layout.setSpacing(0)
    return body, layout


def panel_context():
    frame = QFrame()
    frame.setProperty("uiRole", "panelContext")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(6)
    return frame, layout


def panel_list(widget):
    frame = QFrame()
    frame.setProperty("uiRole", "panelList")
    frame.setMinimumHeight(60)
    frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 4, 10, 4)
    layout.setSpacing(0)
    layout.addWidget(widget)
    return frame
