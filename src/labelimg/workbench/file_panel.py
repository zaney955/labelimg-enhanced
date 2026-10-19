"""Compose the file dock without changing navigation or file transactions."""

from functools import partial

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (
    QDockWidget, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
    QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from labelimg.annotations import AnnotationFormat
from labelimg.files.ui.list_widget import FileListControlBar, FileListItemDelegate, FileListWidget
from labelimg.localization.runtime import tr
from labelimg.platform.settings_keys import SETTING_FILE_LIST_SORT_DESCENDING, SETTING_FILE_LIST_SORT_KEY
from labelimg.ui.actions import new_icon


class _ElidedLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().text().color())
        painter.drawText(self.contentsRect(), Qt.AlignVCenter | Qt.AlignLeft,
                         self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.contentsRect().width()))


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
    w.file_header = QWidget()
    header = QHBoxLayout(w.file_header)
    header.setContentsMargins(12, 10, 12, 8)
    header.setSpacing(8)
    w.file_panel_title = QLabel(tr('fileList'))
    w.file_panel_title.setObjectName('filePanelTitle')
    header.addWidget(w.file_panel_title)
    w.file_summary_label = _ElidedLabel()
    w.file_summary_label.setObjectName('filePanelSummary')
    header.addWidget(w.file_summary_label, 1)
    w.file_list_controls = FileListControlBar(
        settings.get(SETTING_FILE_LIST_SORT_KEY, 'name'),
        settings.get(SETTING_FILE_LIST_SORT_DESCENDING, False),
    )
    header.addWidget(w.file_list_controls.sort_button)
    w.file_dock.setTitleBarWidget(w.file_header)

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(12, 0, 12, 10)
    layout.setSpacing(9)
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
    icon = QLabel()
    icon.setPixmap(new_icon('choose-annotation-directory').pixmap(16, 16))
    icon.setAttribute(Qt.WA_TransparentForMouseEvents)
    directory.addWidget(icon)
    w.annotation_directory_button = w.annotation_directory_bar
    layout.addWidget(w.annotation_directory_bar)
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
    w.file_more_button.setText('…')
    w.file_more_button.setFixedWidth(26)
    w.file_more_menu = QMenu(w.file_more_button)
    w.file_more_menu.aboutToShow.connect(lambda: w.populate_file_selection_menu(w.file_more_menu))
    w.file_more_button.setMenu(w.file_more_menu)
    w.file_more_button.setPopupMode(QToolButton.InstantPopup)
    layout.addWidget(w.file_selection_bar)
    w.file_selection_bar.hide()
    w.file_dock.setWidget(container)
    w.file_dock.setStyleSheet('''
        QDockWidget { background: palette(base); }
        QLabel#filePanelTitle { font-size: 15px; font-weight: 600; }
        QLabel#filePanelSummary, QLabel#fileSelectionCount { color: #8A93A3; font-size: 11px; }
        QToolButton { border: none; border-radius: 4px; padding: 4px 6px; }
        QToolButton:hover { background: palette(alternate-base); }
        QToolButton::menu-indicator { image: none; }
        QToolButton#annotationDirectoryBar { background: palette(alternate-base); padding: 0; }
        QToolButton#annotationDirectoryBar:hover { background: #EBEEF4; }
        QLineEdit { min-height: 28px; padding: 0 6px 0 0; border: 1px solid #D7DEE8; border-radius: 4px; }
        QLineEdit:focus { border-color: #756B9E; }
        QToolButton#fileFilterChip { background: #ECEAF5; color: #645887; padding: 3px 7px; font-size: 11px; }
        QListView { border: 1px solid #E2E7EF; border-radius: 3px; background: palette(base); outline: none; padding: 4px 0; }
        QFrame#fileSelectionBar { border: none; border-top: 1px solid #E0E5ED; background: palette(alternate-base); border-radius: 3px; }
    ''')
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
