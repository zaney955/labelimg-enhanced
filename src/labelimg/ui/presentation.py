"""Shared light surfaces for the workbench and application-owned Qt windows.

This module owns presentation only: it never changes action bindings, widget
values, selection models, annotation colors, or transaction behavior.
"""

import os

from PyQt5.QtCore import QEvent, QObject, QRect, Qt
from PyQt5.QtGui import QColor, QPalette, QPainter
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

COLORS = {
    "surface": "#FFFFFF",
    "background": "#F5F6F9",
    "border": "#D7DEE8",
    "divider": "#E2E7EF",
    "text": "#253047",
    "muted": "#68758A",
    "accent": "#756B9E",
    "accent_hover": "#665B8E",
    "selected": "#ECEAF5",
    "danger": "#A65F5F",
    "warning": "#9A7640",
}

# Keep selectors on Qt controls; Canvas paint and category swatches remain data.
SURFACE_STYLE = """
QDialog { background: #FFFFFF; }
QLabel[uiRole="heading"] { color: #253047; font-size: 16px; font-weight: 600; }
QLabel[uiRole="sectionTitle"] { color: #526078; font-size: 12px; font-weight: 600; }
QFrame[uiRole="iconTile"] { background: #F0EDF7; border: none; border-radius: 8px; }
QLabel[uiRole="metricValue"] { color: #253047; font-size: 24px; font-weight: 600; }
QLabel[uiRole="supporting"] { color: #68758A; }
QLabel[uiRole="summary"] { background: #F5F6F9; color: #455468; padding: 10px;
    border: 1px solid #E2E7EF; border-radius: 6px; }
QFrame[uiRole="section"], QGroupBox { background: #FFFFFF;
    border: 1px solid #E2E7EF; border-radius: 6px; }
QGroupBox { margin-top: 12px; padding: 12px 10px 8px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #455468; }
QFrame[uiRole="divider"] { border: none; background: #E2E7EF; min-height: 1px; max-height: 1px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { min-height: 28px;
    border: 1px solid #D7DEE8; border-radius: 4px; background: #FFFFFF;
    color: #253047; padding: 0 7px; selection-background-color: #ECEAF5; selection-color: #45385F; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #756B9E; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #939CAA; background: #F5F6F9; border-color: #E2E7EF; }
QComboBox { padding-right: 25px; }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox::down-arrow { image: url(:/chevron-down); width: 16px; height: 16px; }
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { width: 20px; border: none; }
QSpinBox::down-button, QDoubleSpinBox::down-button { width: 20px; border: none; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(:/chevron-up); width: 12px; height: 12px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(:/chevron-down); width: 12px; height: 12px; }
QPushButton { min-height: 30px; min-width: 68px; padding: 0 12px;
    border: 1px solid #D7DEE8; border-radius: 4px; background: #FFFFFF; color: #253047; }
QPushButton:hover { background: #F5F6F9; border-color: #B9C3D2; }
QPushButton:focus { border-color: #756B9E; }
QPushButton:pressed { background: #ECEAF5; }
QPushButton[uiRole="primary"] { background: #756B9E; color: #FFFFFF; border-color: #756B9E; }
QPushButton[uiRole="primary"]:hover { background: #665B8E; border-color: #665B8E; }
QPushButton[uiRole="destructive"] { color: #A65F5F; border-color: #DDBDBD; }
QPushButton:disabled, QPushButton[uiRole="primary"]:disabled {
    color: #929AA6; background: #F0F2F6; border-color: #E2E7EF; }
QToolButton { border: 1px solid transparent; border-radius: 4px; padding: 3px; }
QToolButton:hover { background: #F0EEF7; }
QToolButton:checked { background: #ECEAF5; border-color: #D6CFE6; color: #645887; }
QToolButton:focus { border-color: #756B9E; }
QToolButton::menu-button { background: transparent; border: none; width: 16px; }
QToolButton::menu-arrow { image: url(:/chevron-down); width: 12px; height: 12px; }
QToolButton[uiRole="menuButton"] { padding-right: 18px; }
QToolButton[uiRole="menuButton"]::menu-indicator,
QToolButton[uiRole="menuButton"]::menu-arrow { image: none; }
QToolButton[uiRole="menuButton"]::menu-button { width: 0; }
QCheckBox, QRadioButton { spacing: 7px; min-height: 24px; }
QTableView, QTreeView, QListView { border: 1px solid #E2E7EF; border-radius: 4px;
    background: #FFFFFF; alternate-background-color: #F8F9FC; outline: none;
    selection-background-color: #ECEAF5; selection-color: #45385F; }
QTableView::item, QTreeView::item { padding: 5px 7px; }
QTableView::item:selected, QTreeView::item:selected { background: #ECEAF5; color: #45385F; }
QHeaderView::section { background: #F5F6F9; color: #68758A; border: none;
    border-bottom: 1px solid #E2E7EF; padding: 7px; }
QTableCornerButton::section { background: #F5F6F9; border: none; }
QTabWidget::pane { border: 1px solid #E2E7EF; border-radius: 4px; background: #FFFFFF; }
QTabBar::tab { padding: 8px 13px; background: #F5F6F9; color: #68758A; border: none; }
QTabBar::tab:selected { background: #ECEAF5; color: #645887; }
QTabBar::tab:focus { border-bottom: 2px solid #756B9E; }
QScrollArea[uiRole="dialogBody"] { border: none; background: #FFFFFF; }
QScrollArea { border: 1px solid #E2E7EF; background: #FFFFFF; }
QWidget[uiRole="dialogBodyContent"] { background: #F7F8FB; border-radius: 8px; }
QProgressBar { min-height: 12px; border: 1px solid #E2E7EF; border-radius: 4px;
    background: #F5F6F9; text-align: center; }
QProgressBar::chunk { background: #756B9E; border-radius: 3px; }
QSlider::groove:horizontal { height: 4px; background: #E2E7EF; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #A59ABB; border-radius: 2px; }
QSlider::handle:horizontal { width: 13px; margin: -5px 0; border: 1px solid #B5ABC8;
    background: #FFFFFF; border-radius: 4px; }
QSlider::handle:horizontal:focus { border-color: #756B9E; }
"""


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
            QRect(self.width() - 17, (self.height() - 12) // 2, 12, 12),
            "chevron-down",
            enabled=self.isEnabled(),
            size=12,
        )


def _surface_palette(widget):
    palette = widget.palette()
    for channel, color in (
        (QPalette.Window, "#F5F6FA"),
        (QPalette.Base, "#FFFFFF"),
        (QPalette.AlternateBase, "#F6F7FB"),
        (QPalette.Text, "#2B3446"),
        (QPalette.WindowText, "#2B3446"),
        (QPalette.ButtonText, "#2B3446"),
        (QPalette.Mid, "#A0AABC"),
        (QPalette.Highlight, "#756B9E"),
    ):
        palette.setColor(channel, QColor(color))
    for channel in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, channel, QColor("#929CAD"))
    widget.setPalette(palette)


def present_panel(dock, stylesheet):
    """Style the actual header/content roots across the QDockWidget boundary."""
    dock.setStyleSheet(stylesheet)
    for surface in (dock.titleBarWidget(), dock.widget()):
        if surface is not None:
            _surface_palette(surface)
            surface.setStyleSheet(SURFACE_STYLE + stylesheet)


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
    header = QFrame()
    header.setObjectName("resultPanelHeader")
    layout = QHBoxLayout(header)
    layout.setContentsMargins(12, 9, 12, 9)
    layout.setSpacing(8)
    layout.addWidget(icon_tile(icon, size=24, icon_size=16))
    title = role(QLabel(dock.windowTitle()), "sectionTitle")
    dock.windowTitleChanged.connect(title.setText)
    layout.addWidget(title, 1)
    close = _PanelCloseButton(header)
    close.clicked.connect(dock.hide)
    layout.addWidget(close)
    dock.setTitleBarWidget(header)
    present_panel(
        dock,
        "QFrame#resultPanelHeader { background: #FFFFFF; border-bottom: 1px solid #EAEDF3; }",
    )


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


def present_dialog(
    dialog, *, primary=None, minimum_width=380, scroll=False, title=True, icon="file"
):
    """Apply the common header/body/footer shell to a constructed dialog."""
    if getattr(dialog, "_presentation_chrome", None) is not None:
        return
    explicit_size = dialog.testAttribute(Qt.WA_Resized)
    previous_size = dialog.size()
    _surface_palette(dialog)
    dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    dialog.setStyleSheet(SURFACE_STYLE + "\n" + dialog.styleSheet())
    layout = dialog.layout()
    if not isinstance(layout, QVBoxLayout):
        return
    layout.setContentsMargins(18, 16, 18, 14)
    layout.setSpacing(12)
    dialog.ensurePolished()
    natural_size = layout.totalSizeHint()

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
        scroller = role(QScrollArea(), "dialogBody")
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
    header_height = 0
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
        header_height = 44
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
        dialog.resize(
            max(minimum_width, natural_size.width()),
            natural_size.height() + header_height,
        )


def present_workbench(window):
    _surface_palette(window)
    window.setStyleSheet(SURFACE_STYLE + """
        QMainWindow { background: #F5F6F9; }
        QToolBar { background: #FFFFFF; border: none; border-bottom: 1px solid #E2E7EF; spacing: 4px; }
        QToolBar::separator { background: #E2E7EF; width: 1px; height: 1px; margin: 6px; }
        QMenuBar { background: #FFFFFF; color: #455468; padding: 2px 4px; }
        QMenuBar::item { padding: 4px 8px; border-radius: 3px; }
        QMenuBar::item:selected { background: #ECEAF5; }
        QMenu { background: #FFFFFF; border: 1px solid #D7DEE8; padding: 5px; }
        QMenu::item { padding: 6px 28px 6px 24px; border-radius: 3px; }
        QMenu::item:selected { background: #ECEAF5; color: #45385F; }
        QMenu::item:disabled { color: #939CAA; }
        QMenu::separator { background: #E2E7EF; height: 1px; margin: 5px 8px; }
        QStatusBar { background: #FFFFFF; color: #68758A; border-top: 1px solid #E2E7EF; }
        QStatusBar::item { border: none; }
    """)
