"""Shared themed surfaces for the workbench and application-owned Qt windows.

This module owns presentation only: it never changes action bindings, widget
values, selection models, annotation colors, or transaction behavior.
"""

from labelimg.ui.theme import (
    apply_theme_palette,
    apply_theme_style,
    theme_style,
    widget_theme_style,
)

import os

from PyQt5.QtCore import QEvent, QObject, QRect, QSize, Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (
    QDialogButtonBox,
    QFrame,
    QHeaderView,
    QLabel,
    QHBoxLayout,
    QScrollArea,
    QTableWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QToolButton,
)
from labelimg.localization.runtime import language_changed, tr
from labelimg.ui.icons import IconLabel, paint_icon, icon as operation_icon
from labelimg.ui.panels import PANEL_STYLE, PanelHeader
from labelimg.ui.metrics import dp

# Keep selectors on Qt controls; Canvas paint and category swatches remain data.
SURFACE_STYLE = theme_style("""
QWidget { font-size: ${font_body}px; }
QDialog { background: ${surface}; }
QLabel[uiRole="heading"] { color: ${text}; font-size: ${font_heading}px; font-weight: 600; }
QLabel[uiRole="sectionTitle"] { color: ${text}; font-size: ${font_section}px; font-weight: 600; }
QFrame[uiRole="iconTile"] { background: ${selected}; border: none; border-radius: 8px; }
QLabel[uiRole="metricValue"] { color: ${text}; font-size: ${font_metric}px; font-weight: 600; }
QLabel[uiRole="supporting"] { color: ${muted}; font-size: ${font_supporting}px; }
QLabel[uiRole="summary"] { background: ${background}; color: ${text}; padding: 10px;
    border: none; border-radius: 6px; }
QFrame[uiRole="section"], QGroupBox { background: ${background};
    border: none; border-radius: 6px; }
QGroupBox { margin-top: 12px; padding: 12px 10px 8px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: ${text}; }
QFrame[uiRole="divider"] { border: none; background: ${divider}; min-height: 1px; max-height: 1px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { min-height: 28px;
    border: 1px solid ${border}; border-radius: 4px; background: ${surface};
    color: ${text}; padding: 0 7px; selection-background-color: ${selected}; selection-color: ${accent_hover}; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: ${accent}; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: ${disabled_text}; background: ${background}; border-color: ${divider}; }
QComboBox { padding-right: 25px; }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox::down-arrow { image: url(:/chevron-down); width: 16px; height: 16px; }
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { width: 20px; border: none; }
QSpinBox::down-button, QDoubleSpinBox::down-button { width: 20px; border: none; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(:/chevron-up); width: 12px; height: 12px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(:/chevron-down); width: 12px; height: 12px; }
QPushButton { min-height: 30px; min-width: 68px; padding: 0 12px;
    border: 1px solid ${border}; border-radius: 4px; background: ${surface}; color: ${text}; }
QPushButton:hover { background: ${background}; border-color: ${border}; }
QPushButton:focus { border-color: ${accent}; }
QPushButton:pressed { background: ${selected}; }
QPushButton[uiRole="primary"] { background: ${accent}; color: ${on_accent}; border-color: ${accent}; }
QPushButton[uiRole="primary"]:hover { background: ${accent_hover}; border-color: ${accent_hover}; }
QPushButton[uiRole="destructive"] { color: ${danger}; border-color: ${danger_border}; }
QPushButton:disabled, QPushButton[uiRole="primary"]:disabled {
    color: ${disabled_text}; background: ${disabled_background}; border-color: ${divider}; }
QToolButton { border: 1px solid transparent; border-radius: 4px; padding: 3px; }
QToolButton:hover { background: ${background}; }
QToolButton:checked { background: ${selected}; border-color: ${accent_border}; color: ${selection_foreground}; }
QToolButton:focus { border-color: ${accent}; border-style: dotted; }
QToolButton::menu-button { background: transparent; border: none; width: 16px; }
QToolButton::menu-arrow { image: url(:/chevron-down); width: 12px; height: 12px; }
QToolButton[uiRole="menuButton"] { padding-right: 18px; }
QToolButton[uiRole="menuButton"]::menu-indicator,
QToolButton[uiRole="menuButton"]::menu-arrow { image: none; }
QToolButton[uiRole="menuButton"]::menu-button { width: 0; }
QCheckBox, QRadioButton { spacing: 7px; min-height: 24px; }
QTableView, QTreeView, QListView { border: 1px solid ${divider}; border-radius: 4px;
    background: ${surface}; alternate-background-color: ${background}; outline: none;
    selection-background-color: ${selection_background}; selection-color: ${selection_foreground}; }
QTableView::item, QTreeView::item { padding: 5px 7px; }
QTableView::item:selected, QTreeView::item:selected { background: ${selection_background}; color: ${selection_foreground}; }
QHeaderView::section { background: ${background}; color: ${muted}; border: none;
    border-bottom: 1px solid ${divider}; padding: 7px; }
QTableCornerButton::section { background: ${background}; border: none; }
QTabWidget::pane { border: 1px solid ${divider}; border-radius: 4px; background: ${surface}; }
QTabBar::tab { padding: 8px 13px; background: ${background}; color: ${muted};
    border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { background: ${selection_background}; color: ${selection_foreground};
    border-bottom-color: ${accent}; }
QScrollArea[uiRole="dialogBody"] { border: none; background: ${surface}; }
QScrollArea { border: 1px solid ${divider}; background: ${surface}; }
QWidget[uiRole="dialogBodyContent"] { background: ${surface}; }
QProgressBar { min-height: 12px; border: 1px solid ${divider}; border-radius: 4px;
    background: ${background}; text-align: center; }
QProgressBar::chunk { background: ${accent}; border-radius: 3px; }
QSlider::groove:horizontal { height: 4px; background: ${divider}; border-radius: 2px; }
QSlider::sub-page:horizontal { background: ${accent}; border-radius: 2px; }
QSlider::handle:horizontal { width: 13px; margin: -5px 0; border: 1px solid ${accent_border};
    background: ${surface}; border-radius: 4px; }
QSlider::handle:horizontal:focus { border-color: ${accent}; }
QMenu, QToolTip { background: ${surface}; color: ${text}; border: 1px solid ${border}; padding: 5px; }
QMenu::item { padding: 6px 24px 6px 24px; min-height: 20px; }
QMenu[labelimgMenu="true"]::item { padding-left: 54px; }
QMenu::item:selected { background: ${selected}; color: ${selection_foreground}; }
QMenu::item:disabled { color: ${disabled_text}; }
QMenu::separator { background: ${divider}; height: 1px; margin: 5px 8px; }
QComboBox QAbstractItemView { background: ${surface}; color: ${text}; border: 1px solid ${border};
    padding: 4px; selection-background-color: ${selection_background};
    selection-color: ${selection_foreground}; outline: none; }
QComboBox QAbstractItemView::item { min-height: 32px; padding: 0 8px; border: none; }
QComboBox QAbstractItemView::item:selected { background: ${selection_background}; color: ${selection_foreground}; }
QScrollBar:vertical { background: ${background}; width: 12px; margin: 2px; border: none; }
QScrollBar:horizontal { background: ${background}; height: 12px; margin: 2px; border: none; }
QScrollBar::handle { background: ${border}; border-radius: 4px; }
QScrollBar::handle:vertical { min-height: 24px; }
QScrollBar::handle:horizontal { min-width: 24px; }
QScrollBar::handle:hover { background: ${accent}; }
QScrollBar::handle:pressed { background: ${accent_hover}; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle { background: ${divider}; }
QSplitter::handle:hover { background: ${accent_border}; }
""")


def role(widget, name):
    """Assign one presentation role without changing widget behavior."""
    widget.setProperty("uiRole", name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


def icon_tile(name, *, size=32, icon_size=20):
    tile = role(QFrame(), "iconTile")
    tile.setFixedSize(size, size)
    layout = QHBoxLayout(tile)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(IconLabel(name, size=icon_size), 0, Qt.AlignCenter)
    return tile


class MenuButton(QToolButton):
    """A menu affordance aligned with the label instead of native corner arrows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("uiRole", "menuButton")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        paint_icon(
            painter,
            QRect(self.width() - dp(17), (self.height() - dp(12)) // 2, dp(12), dp(12)),
            "chevron-down",
            enabled=self.isEnabled(),
            size=12,
        )


def _surface_palette(widget):
    apply_theme_palette(widget)


def present_surface(widget, stylesheet=""):
    """Bind a standalone popup/floating surface to the shared theme."""
    apply_theme_palette(widget)
    # Embedded surfaces inherit the common controls from their region root.
    # Copying them at every level makes each zoom repolish the same subtree.
    if widget.isWindow():
        widget.setProperty("labelimgSurfaceRoot", True)
        stylesheet = SURFACE_STYLE + stylesheet
    apply_theme_style(widget, stylesheet)


def install_application_theme():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None and not app.property("labelimgApplicationTheme"):
        from labelimg.ui.theme_palettes import luminance

        app.setProperty(
            "labelimgSystemColorMode",
            (
                "dark"
                if luminance(app.palette().window().color().name()) < 0.45
                else "light"
            ),
        )
        apply_theme_palette(app)
        apply_theme_style(app, SURFACE_STYLE)
        app.setProperty("labelimgApplicationTheme", True)


def present_panel(dock, stylesheet):
    """Style the actual header/content roots across the QDockWidget boundary."""
    body = dock.widget()
    layout = body.layout() if body is not None else None
    if isinstance(layout, QVBoxLayout) and not getattr(body, '_panel_scroll', None):
        content = QWidget()
        content.setProperty('uiRole', 'panelScrollContent')
        contents = QVBoxLayout(content)
        contents.setContentsMargins(0, 0, 0, 0)
        contents.setSpacing(layout.spacing())
        footers = []
        while layout.count():
            stretch = layout.stretch(0)
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget.property('uiRole') == 'panelFooter':
                footers.append(widget)
            elif widget is not None:
                contents.addWidget(widget, stretch)
            elif item.layout() is not None:
                child = item.layout()
                child.setParent(None)
                contents.addLayout(child, stretch)
            else:
                contents.addItem(item)
        scroller = QScrollArea()
        scroller.setProperty('uiRole', 'panelScroll')
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setMinimumSize(0, 0)
        scroller.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        scroller.setWidget(content)
        layout.addWidget(scroller, 1)
        for footer in footers:
            layout.addWidget(footer)
        body._panel_scroll = scroller
    apply_theme_style(dock, PANEL_STYLE + stylesheet)
    for surface in (dock.titleBarWidget(), dock.widget()):
        if surface is not None:
            _surface_palette(surface)


class _PanelCloseButton(QToolButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setIcon(operation_icon("close"))
        self.setFixedSize(26, 26)
        self.setAutoRaise(True)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def retranslate_ui(self, _language=None):
        self.setToolTip(tr("standard.close"))
        self.setAccessibleName(tr("standard.close"))


def present_result_panel(dock, icon):
    header = PanelHeader(dock, icon)
    close = _PanelCloseButton(header)
    close.clicked.connect(dock.hide)
    header.add_control(close)
    header.close_button = close
    present_panel(dock, "")
    return header


class _TranslatedLabel(QLabel):
    def __init__(self, message_id):
        super().__init__()
        self.message_id = message_id
        self.setTextFormat(Qt.PlainText)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def retranslate_ui(self, _language=None):
        self.setText(tr(self.message_id))


def section(message_id, content=None, *, action=None, stretch=0):
    frame = role(QFrame(), "section")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(8)
    label = role(_TranslatedLabel(message_id), "sectionTitle")
    header = QHBoxLayout()
    header.addWidget(label, 1)
    if action is not None:
        header.addWidget(action)
    layout.addLayout(header)
    if content is not None:
        if isinstance(content, QWidget):
            layout.addWidget(content, stretch)
        else:
            layout.addLayout(content, stretch)
    return frame


def metric_card(message_id):
    frame = role(QFrame(), "section")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(2)
    frame.value = role(QLabel("—"), "metricValue")
    layout.addWidget(frame.value)
    layout.addWidget(role(_TranslatedLabel(message_id), "supporting"))
    return frame


def compact_paths(label, image_dir, annotation_dir):
    """Show directory names, keeping full user paths selectable in the tooltip."""
    full = tr("ui.paths", images=image_dir, annotations=annotation_dir)
    label.setText(
        tr(
            "ui.paths",
            images=os.path.basename(os.path.normpath(image_dir)),
            annotations=os.path.basename(os.path.normpath(annotation_dir)),
        )
    )
    label.setToolTip(full)
    label.setAccessibleDescription(full)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)


def empty_table_hint(table, message_id):
    label = role(_TranslatedLabel(message_id), "supporting")
    label.setParent(table.viewport())
    label.setAlignment(Qt.AlignCenter)
    label.setWordWrap(True)
    label.setAttribute(Qt.WA_TransparentForMouseEvents)
    layout = QVBoxLayout(table.viewport())
    layout.addWidget(label)
    return label


def present_table(table, *, path_columns=(), stretch_path=False):
    """Uniform tables, preserving editors, selection and data-role colors."""
    table.setAlternatingRowColors(True)
    if isinstance(table, QTableWidget):
        table.setShowGrid(False)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(32)
    table.setTextElideMode(Qt.ElideMiddle)
    table.setWordWrap(False)
    header = (
        table.horizontalHeader() if isinstance(table, QTableWidget) else table.header()
    )
    header.setMinimumSectionSize(32)
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    if stretch_path and path_columns:
        header.setStretchLastSection(False)
        for column in range(table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(path_columns[0], QHeaderView.Stretch)
    if isinstance(table, QTableWidget):
        for row in range(table.rowCount()):
            for column in path_columns:
                item = table.item(row, column)
                if item is not None and not item.toolTip():
                    item.setToolTip(item.text())


class _DialogChrome(QObject):
    def __init__(self, dialog, heading):
        super().__init__(dialog)
        self.heading = heading
        dialog.installEventFilter(self)

    def eventFilter(self, dialog, event):
        if event.type() == QEvent.WindowTitleChange and self.heading is not None:
            self.heading.setText(dialog.windowTitle().rstrip(".…"))
        elif event.type() == QEvent.Show:
            screen = dialog.screen()
            if screen is not None:
                available = screen.availableGeometry().adjusted(12, 12, -12, -12)
                dialog.resize(
                    min(dialog.width(), available.width()),
                    min(dialog.height(), available.height()),
                )
        return False


class _DialogScrollArea(QScrollArea):
    """Measure the finished content, rather than Qt's capped scroll viewport."""

    def sizeHint(self):
        if self.widget() is None:
            return super().sizeHint()
        return self.widget().sizeHint() + QSize(2 * self.frameWidth(), 2 * self.frameWidth())


def present_dialog(
    dialog, *, primary=None, minimum_width=380, scroll=True, title=True, icon="file"
):
    """Apply the common header/body/footer shell to a constructed dialog."""
    if getattr(dialog, "_presentation_chrome", None) is not None:
        return
    explicit_size = dialog.testAttribute(Qt.WA_Resized)
    previous_size = dialog.size()
    dialog._ui_scale_minimum_width = minimum_width
    dialog._ui_scale_preferred_size = previous_size if explicit_size else None
    _surface_palette(dialog)
    dialog.setProperty("labelimgSurfaceRoot", True)
    dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    apply_theme_style(dialog, SURFACE_STYLE + "\n" + widget_theme_style(dialog))
    layout = dialog.layout()
    if not isinstance(layout, QVBoxLayout):
        return
    layout.setContentsMargins(18, 16, 18, 14)
    layout.setSpacing(12)
    dialog.ensurePolished()

    def is_footer(item):
        if isinstance(item.widget(), QDialogButtonBox):
            return True
        child = item.layout()
        return child is not None and any(
            is_footer(child.itemAt(i)) for i in range(child.count())
        )

    items = [(layout.itemAt(i), layout.stretch(i)) for i in range(layout.count())]
    footers = [item for item, _stretch in items if is_footer(item)]
    if scroll:
        body = role(QWidget(), "dialogBodyContent")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(12)
        for _original, stretch in items:
            item = layout.takeAt(0)
            if item in footers:
                continue
            if item.widget() is not None:
                body_layout.addWidget(item.widget(), stretch)
            elif item.layout() is not None:
                child_layout = item.layout()
                child_layout.setParent(None)
                body_layout.addLayout(child_layout, stretch)
            else:
                body_layout.addItem(item)
        scroller = role(_DialogScrollArea(), "dialogBody")
        scroller.setWidgetResizable(True)
        scroller.setWidget(body)
        layout.addWidget(scroller, 1)
        for item in footers:
            if item.widget() is not None:
                layout.addWidget(item.widget())
            else:
                child = item.layout()
                child.setParent(None)
                layout.addLayout(child)
    heading = None
    if title:
        heading = role(QLabel(dialog.windowTitle().rstrip(".…")), "heading")
        heading.setTextFormat(Qt.PlainText)
        heading.setWordWrap(True)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        header_layout.addWidget(icon_tile(icon))
        header_layout.addWidget(heading, 1)
        layout.insertWidget(0, header)
    dialog._presentation_chrome = _DialogChrome(dialog, heading)
    for table in dialog.findChildren(QTableWidget) + dialog.findChildren(QTreeWidget):
        present_table(table)
    for index in reversed(range(layout.count())):
        if not is_footer(layout.itemAt(index)):
            continue
        divider = role(QFrame(), "divider")
        divider.setFixedHeight(1)
        layout.insertWidget(index, divider)
    if primary is not None:
        role(primary, "primary")
    dialog.setMinimumSize(minimum_width, 0)
    layout.invalidate()
    layout.activate()
    if explicit_size:
        dialog.resize(max(minimum_width, previous_size.width()), previous_size.height())
    else:
        natural_size = layout.totalSizeHint()
        dialog.resize(
            max(minimum_width, natural_size.width()),
            natural_size.height(),
        )


def present_workbench(window):
    from PyQt5.QtWidgets import QMainWindow, QTabWidget

    window.setDockOptions(window.dockOptions() | QMainWindow.AllowNestedDocks)
    window.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
    _surface_palette(window)
    window.setProperty("labelimgSurfaceRoot", True)
    apply_theme_style(
        window,
        SURFACE_STYLE + theme_style("""
        QMainWindow { background: ${workspace_gutter}; }
        QMainWindow::separator { background: ${workspace_gutter}; width: 6px; height: 6px; }
        QMainWindow::separator:hover { background: ${accent_border}; }
        QFrame#canvasWorkspace { background: ${background}; border: 1px solid ${panel_border}; border-radius: 5px; }
        QScrollArea#canvasScrollArea { border: none; background: ${background}; }
        QToolBar#canvasToolRail { background: ${panel_header}; border: none; border-right: 1px solid ${panel_border}; }
        QToolBar { background: ${surface}; border: none; border-bottom: 1px solid ${divider}; spacing: 4px; }
        QToolBar::separator { background: ${divider}; width: 1px; height: 1px; margin: 6px; }
        QMenuBar { background: ${surface}; color: ${text}; padding: 2px 4px; }
        QMenuBar::item { padding: 4px 8px; border-radius: 3px; }
        QMenuBar::item:selected { background: ${selected}; }
        QMenu { background: ${surface}; border: 1px solid ${border}; padding: 5px; }
        QStatusBar { background: ${panel_header}; color: ${text}; border-top: 1px solid ${divider}; }
        QStatusBar::item { border: none; }
    """),
    )


def scope_workbench_styles(window):
    """Give independent regions one shared sheet, without a changing ancestor."""
    from PyQt5.QtWidgets import QDialog

    if window.property("labelimgScopedStyles"):
        return
    base = window.property("labelimgThemeStyle")
    # Replace the ancestor first: doing it after the regional rules can reset
    # fonts cached by already-polished controls in a subsequent workbench.
    window.ensurePolished()
    apply_theme_style(window, """
        QMainWindow { background: ${workspace_gutter}; }
        QMainWindow::separator { background: ${workspace_gutter}; }
        QMainWindow::separator:hover { background: ${accent_border}; }
    """)
    for surface in window.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
        if isinstance(surface, QDialog):
            continue
        own = widget_theme_style(surface).template
        if own.startswith(SURFACE_STYLE.template):
            own = own[len(SURFACE_STYLE.template):]
        apply_theme_style(surface, base + "\n" + own)
        surface.setProperty("labelimgSurfaceRoot", True)
    # Native dock separator metrics are scaled by IconStyle; the frame's
    # palette-only sheet stays stable while the regional dimensions change.
    window.setProperty("labelimgScopedStyles", True)
