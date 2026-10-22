"""Compose the file dock without changing navigation or file transactions."""

from labelimg.ui.theme import theme_style

from functools import partial

from PyQt5.QtCore import QEvent, QSize, Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (
    QDockWidget, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
    QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget, QStyle, QStyleOption,
)

from labelimg.annotations import AnnotationFormat
from labelimg.files.ui.list_widget import FileListControlBar, FileListItemDelegate, FileListWidget
from labelimg.localization.runtime import tr
from labelimg.platform.settings_keys import SETTING_FILE_LIST_SORT_DESCENDING, SETTING_FILE_LIST_SORT_KEY
from labelimg.ui.actions import new_icon
from labelimg.ui.icons import IconLabel
from labelimg.ui.presentation import icon_tile, present_panel


class _ElidedLabel(QLabel):
    def __init__(self, parent=None, elide_mode=Qt.ElideRight):
        super().__init__(parent)
        self._elide_mode = elide_mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)
        painter.setFont(self.font())
        painter.setPen(self.palette().windowText().color())
        painter.drawText(self.contentsRect(), Qt.AlignVCenter | Qt.AlignLeft,
                         self.fontMetrics().elidedText(self.text(), self._elide_mode, self.contentsRect().width()))


class _FileSelectionBar(QFrame):
    def __init__(self, file_list):
        super().__init__()
        file_list.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.EnabledChange:
            self.setEnabled(watched.isEnabled())
        return super().eventFilter(watched, event)


def build_file_panel(w, settings):
    w.file_dock = QDockWidget(tr('fileList'), w)
    w.file_dock.setObjectName(tr('files'))
    w.file_dock.setMinimumWidth(320)
    w.file_header = QFrame()
    w.file_header.setObjectName('filePanelHeader')
    header = QHBoxLayout(w.file_header)
    header.setContentsMargins(12, 9, 12, 9)
    header.setSpacing(6)
    header.addWidget(icon_tile('file', size=24, icon_size=16))
    w.file_panel_title = QLabel(tr('fileList'))
    w.file_panel_title.setObjectName('filePanelTitle')
    header.addWidget(w.file_panel_title)
    w.file_summary_label = _ElidedLabel()
    w.file_summary_label.setObjectName('filePanelSummary')
    w.file_summary_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    w.file_summary_label.setFixedHeight(22)
    w.file_summary_label.setMaximumWidth(116)
    header.addWidget(w.file_summary_label)
    header.addStretch(1)
    w.file_list_controls = FileListControlBar(
        settings.get(SETTING_FILE_LIST_SORT_KEY, 'name'),
        settings.get(SETTING_FILE_LIST_SORT_DESCENDING, False),
    )
    header.addWidget(w.file_list_controls.sort_button)
    w.file_dock.setTitleBarWidget(w.file_header)

    container = QFrame()
    container.setObjectName('filePanelSurface')
    layout = QVBoxLayout(container)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    # The action is installed later by composition, after commands are created.
    w.annotation_directory_bar = QToolButton()
    w.annotation_directory_bar.setObjectName('annotationDirectoryBar')
    w.annotation_directory_bar.setFixedHeight(28)
    w.annotation_directory_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    directory = QHBoxLayout(w.annotation_directory_bar)
    directory.setContentsMargins(9, 0, 8, 0)
    directory.setSpacing(6)
    w.annotation_directory_label = _ElidedLabel()
    w.annotation_directory_label.setAttribute(Qt.WA_TransparentForMouseEvents)
    directory.addWidget(w.annotation_directory_label, 1)
    icon = IconLabel('choose-annotation-directory')
    icon.setAttribute(Qt.WA_TransparentForMouseEvents)
    directory.addWidget(icon)
    w.annotation_directory_button = w.annotation_directory_bar
    location_card = QFrame()
    w.annotation_location_card = location_card
    location_card.setObjectName('annotationLocationCard')
    location = QVBoxLayout(location_card)
    location.setContentsMargins(7, 5, 7, 7)
    location.setSpacing(3)
    location.addWidget(w.annotation_directory_bar)
    w.annotation_target_label = _ElidedLabel(elide_mode=Qt.ElideMiddle)
    w.annotation_target_label.setObjectName('annotationSaveTarget')
    w.annotation_target_label.setMinimumHeight(20)
    location.addWidget(w.annotation_target_label)
    layout.addWidget(location_card)
    w.file_list_controls.viewChanged.connect(w.apply_file_list_view)
    w.file_list_controls.openFirstSearchResultRequested.connect(w.open_first_image_search_result)
    layout.addWidget(w.file_list_controls)

    w.file_list_widget = FileListWidget()
    w.file_list_widget.setItemDelegate(FileListItemDelegate(w.file_list_widget))
    w.file_list_widget.setTextElideMode(Qt.ElideMiddle)
    w.file_list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    w.file_list_widget.setVerticalScrollMode(w.file_list_widget.ScrollPerPixel)
    w.file_list_widget.setMouseTracking(True)
    w.file_list_widget.itemOpenRequested.connect(w.file_item_double_clicked)
    w.file_list_widget.itemSelectionChanged.connect(w.update_file_selection_count)
    w.file_list_widget.openRequested.connect(w.open_selected_file)
    w.file_list_widget.renameRequested.connect(w.rename_selected_files)
    w.file_list_widget.deleteRequested.connect(w.delete_selected_files)
    w.file_list_widget.searchRequested.connect(w.focus_image_search)
    w.file_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
    w.file_list_widget.customContextMenuRequested.connect(w.pop_file_list_menu)
    w.file_list_stack = QStackedWidget()
    w.file_list_stack.addWidget(w.file_list_widget)
    w.file_list_empty_state = QWidget()
    empty = QVBoxLayout(w.file_list_empty_state)
    empty.addStretch(1)
    empty.addWidget(icon_tile('search', size=42, icon_size=22), 0, Qt.AlignHCenter)
    w.file_list_empty_label = QLabel(tr('files.noMatch'))
    w.file_list_empty_label.setAlignment(Qt.AlignCenter)
    empty.addWidget(w.file_list_empty_label)
    w.file_list_clear_filter_button = QPushButton(tr('files.clearFilter'))
    w.file_list_clear_filter_button.clicked.connect(w.file_list_controls.clear_all_conditions)
    empty.addWidget(w.file_list_clear_filter_button, 0, Qt.AlignHCenter)
    empty.addStretch(1)
    w.file_list_stack.addWidget(w.file_list_empty_state)
    layout.addWidget(w.file_list_stack, 1)

    w.file_selection_bar = _FileSelectionBar(w.file_list_widget)
    w.file_selection_bar.setObjectName('fileSelectionBar')
    footer = QHBoxLayout(w.file_selection_bar)
    footer.setContentsMargins(7, 5, 4, 5)
    footer.setSpacing(2)
    w.file_selection_count_label = _ElidedLabel()
    w.file_selection_count_label.setObjectName('fileSelectionCount')
    footer.addWidget(w.file_selection_count_label, 1)

    def button(slot=None):
        result = QToolButton()
        result.setIconSize(QSize(18, 18))
        result.setFixedHeight(28)
        if slot:
            result.clicked.connect(lambda: slot())
        footer.addWidget(result)
        return result

    w.file_rename_button = button(w.rename_selected_files)
    w.file_reveal_button = button(w.reveal_selected_file)
    w.file_review_button = button()
    w.file_review_menu = QMenu(w.file_review_button)
    w.file_review_actions = []
    for state in ('verified', 'questioned', 'unreviewed'):
        action = w.file_review_menu.addAction('')
        action.triggered.connect(partial(w.set_selected_review_state, state))
        w.file_review_actions.append(action)
    w.file_review_button.setMenu(w.file_review_menu)
    w.file_review_button.setPopupMode(QToolButton.InstantPopup)
    w.file_more_button = button()
    w.file_more_button.setIcon(new_icon('more'))
    w.file_more_button.setFixedWidth(26)
    w.file_more_menu = QMenu(w.file_more_button)
    w.file_more_menu.aboutToShow.connect(lambda: w.populate_file_selection_menu(w.file_more_menu))
    w.file_more_button.setMenu(w.file_more_menu)
    w.file_more_button.setPopupMode(QToolButton.InstantPopup)
    layout.addWidget(w.file_selection_bar)
    w.file_selection_bar.hide()
    w.file_dock.setWidget(container)
    present_panel(w.file_dock, theme_style('''
        QDockWidget, QWidget#filePanelSurface { background: ${surface}; }
        QFrame#filePanelHeader { background: ${surface}; }
        QWidget#filePanelSurface { border-top: 1px solid ${divider}; }
        QLabel#filePanelTitle { color: ${text}; font-size: 13px; font-weight: 600; }
        QLabel#filePanelSummary { color: ${muted}; font-size: 10px; background: ${background};
            border-radius: 6px; padding: 2px 5px; }
        QLabel#fileSelectionCount { color: ${accent_hover}; font-size: 11px; }
        QToolButton { border: none; border-radius: 4px; padding: 4px 6px; }
        QToolButton:hover { background: ${background}; }
        QToolButton::menu-indicator { image: none; }
        QFrame#annotationLocationCard { background: ${background}; border: 1px solid ${border}; border-radius: 7px; }
        QToolButton#annotationDirectoryBar { background: transparent; padding: 0; color: ${text}; }
        QToolButton#annotationDirectoryBar:hover { background: ${selected}; }
        QLabel#annotationSaveTarget { color: ${muted}; font-size: 11px; padding-left: 9px; }
        QLineEdit { min-height: 30px; padding: 0 6px 0 0; border: 1px solid ${background};
            border-radius: 6px; background: ${background}; color: ${text}; }
        QLineEdit:focus { border-color: ${accent}; background: ${surface}; }
        QToolButton#fileFilterChip { background: ${selected}; color: ${accent_hover}; padding: 3px 7px; font-size: 11px; }
        QListView { border: none; background: ${surface}; outline: none; padding: 2px 0; }
        QFrame#fileSelectionBar { border: 1px solid ${accent_border}; background: ${selected}; border-radius: 6px; }
    '''))
    retranslate_file_panel(w)
    w.update_file_selection_count()


def retranslate_file_panel(w):
    w.file_panel_title.setText(tr('fileList'))
    w.file_reveal_button.setText(tr('filePanel.reveal'))
    w.file_reveal_button.setToolTip(tr('fileMenu.reveal'))
    w.file_review_button.setText(tr('filePanel.review'))
    w.file_review_button.setToolTip(tr('fileMenu.setReview'))
    w.file_more_button.setToolTip(tr('filePanel.more'))
    w.file_more_button.setAccessibleName(tr('filePanel.more'))
    for action, message in zip(w.file_review_actions, ('fileMenu.markVerified', 'fileMenu.markQuestioned', 'fileMenu.clearReview')):
        action.setText(tr(message))


def update_file_panel_selection(w, detail):
    items = w.file_list_widget.selectedItems()
    count = len(items)
    total = w.file_list_widget.count()
    filtered = w.file_list_controls.state.filter_active
    visible = len(w.file_list_widget.visible_items()) if filtered else total
    summary = tr('filePanel.filteredCount', visible=visible, total=total) if filtered else tr('filePanel.count', total=total)
    if filtered and w.file_path in w.m_img_list and w.file_path not in w.visible_file_paths():
        summary += ' · ' + tr('filePanel.currentHidden')
    w.file_summary_label.setText(summary)
    w.file_summary_label.setToolTip(detail)
    w.file_summary_label.setAccessibleName(detail)
    selected = tr('filePanel.selected', count=count)
    hidden = sum(item.isHidden() for item in items)
    if hidden:
        selected += tr('fileCount.hidden', hidden=hidden)
    w.file_selection_count_label.setText(selected)
    w.file_selection_count_label.setToolTip(detail)
    w.file_selection_count_label.setAccessibleName(detail)
    w.file_selection_bar.setVisible(count > 0)
    w.file_rename_button.setText(tr('filePanel.batchRename' if count > 1 else 'filePanel.rename'))
    w.file_rename_button.setEnabled(count > 0)
    w.file_reveal_button.setVisible(count == 1)
    w.file_review_button.setVisible(count > 1)
    w.file_review_button.setEnabled(count > 0 and w.annotation_format is AnnotationFormat.PASCAL_VOC)
