#!/usr/bin/env python
# -*- coding: utf-8 -*-
import ctypes
import os.path
import platform
import re
import sys
import subprocess
import shutil
import webbrowser as wb

from dataclasses import replace
from functools import cmp_to_key, partial
from types import SimpleNamespace

from PyQt5.QtCore import QByteArray, QDateTime, QEvent, QFileInfo, QItemSelectionModel, QModelIndex, QPersistentModelIndex, QPoint, QPointF, QProcess, QRect, QRectF, QSignalBlocker, QSize, QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QCursor, QImage, QImageReader, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt5.QtWidgets import QAbstractItemView, QAction, QActionGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QStyle, QStyleOptionViewItem, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget, QWidgetAction

import labelimg.ui.generated_resources  # noqa: F401 - registers Qt resources
from labelimg.platform.settings_keys import (
    SETTING_AUTO_SAVE,
    SETTING_DRAW_SQUARE,
    SETTING_FILENAME,
    SETTING_FILL_COLOR,
    SETTING_FILE_LIST_SORT_DESCENDING,
    SETTING_FILE_LIST_SORT_KEY,
    SETTING_LABEL_FILE_FORMAT,
    SETTING_LANGUAGE,
    SETTING_LAST_OPEN_DIR,
    SETTING_LINE_COLOR,
    SETTING_PAINT_LABEL,
    SETTING_RECENT_FILES,
    SETTING_SAVE_DIR,
    SETTING_SINGLE_CLASS,
    SETTING_WIN_POSE,
    SETTING_WIN_SIZE,
    SETTING_WIN_STATE,
)
from labelimg.ui.actions import (
    add_actions,
    format_shortcut,
    new_action,
    new_icon,
    set_action_copy,
)
from labelimg.annotations.ui.style import generate_color_by_text
from labelimg.platform.settings import Settings
from labelimg.canvas.shape import Shape, DEFAULT_LINE_COLOR, DEFAULT_FILL_COLOR
from labelimg.localization.runtime import (
    ENGLISH,
    LANGUAGE_NAMES,
    SIMPLIFIED_CHINESE,
    current_language,
    critical as localized_critical,
    localize_dialog_buttons,
    localize_message_box_buttons,
    question as localized_question,
    set_language,
    system_language,
    tr,
    translate_history_description,
    warning as localized_warning,
)
from labelimg.canvas.widget import Canvas
from labelimg.workbench.commands import (
    CanvasToolRail,
    FormatSelector,
    ReviewControl,
    TopCommandBar,
    ZoomControl,
)
from labelimg.annotations.ui.candidate_label_dialog import CandidateLabelDialog
from labelimg.annotations.ui.label_list import (
    LabelListItemDelegate,
    LabelListWidget,
)
from labelimg.ui.color_dialog import ColorDialog
from labelimg.annotations.domain.model import (
    AnnotationDocument,
    AnnotationDocumentError,
    AnnotationFormat,
)
from labelimg.annotations.infrastructure.document import image_path_hint
from labelimg.annotations.ui.canvas_adapter import (
    document_from_shapes,
    shapes_from_document,
)
from labelimg.annotations.application.workspace import (
    AmbiguousAnnotationDocuments,
    AnnotationWorkspace,
    annotation_resources,
)
from labelimg.annotations.application.editing import (
    AnnotationEditingController,
    ProjectionFailed,
)
from labelimg.annotations.ui.controller import (
    AnnotationHistoryShortcutFilter,
    CanvasAnnotationScene,
)
from labelimg.annotations.domain.history import UnknownImageHistory
from labelimg.annotations.application.review import ReviewStateTransaction
from labelimg.annotations.application.persistence import AnnotationSaveCoordinator
from labelimg.annotations.infrastructure.storage import (
    AnnotationStorageConflict,
    fingerprint_image,
    fingerprint_path,
)
from labelimg.ui.tool_bar import ToolBar
from labelimg.ui.window import WindowMixin
from labelimg.platform.text import native_text as ustr
from labelimg.files.ui.list_widget import (
    BatchRenameDialog,
    CURRENT_IMAGE_ROLE,
    FILE_ANNOTATION_STATE_ROLE,
    FILE_PERSISTENCE_FLAGS_ROLE,
    FILE_QUALITY_FINDINGS_ROLE,
    FILE_REVIEW_STATE_ROLE,
    FileListItem,
    FileListControlBar,
    FileListItemDelegate,
    FileListWidget,
    compare_relative_image_paths,
    validate_base_name,
    validate_rename_mapping,
)
from labelimg.annotations.ui.label_group_list import LabelGroupListWidget
from labelimg.workbench.session import (
    TransitionFacts,
    TransitionRequirement,
    WorkbenchSession,
)
from labelimg.workbench.help_ui import AboutDialog, ShortcutCatalogDialog
from labelimg.workbench.support import (
    APP_NAME,
    compare_image_paths,
    document_format_name,
    inverted,
    portable_logical_compare,
    read_image as read,
)
from labelimg.annotations.ui.workbench_controller import AnnotationActionsMixin
from labelimg.canvas.workbench_controller import CanvasActionsMixin
from labelimg.files.ui.controller import FileActionsMixin
from labelimg.files.ui.loading import DirectoryLoadingMixin
from labelimg.image_tools.ui.controller import ImageToolsActionsMixin
from labelimg.workbench.recovery_ui import RecoveryActionsMixin

__appname__ = APP_NAME
_UNPREPARED_IMAGE_DATA = object()
















class MainWindow(
    AnnotationActionsMixin,
    CanvasActionsMixin,
    FileActionsMixin,
    DirectoryLoadingMixin,
    ImageToolsActionsMixin,
    RecoveryActionsMixin,
    QMainWindow,
    WindowMixin,
):
    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = list(range(3))

    def __init__(self):
        QMainWindow.__init__(self)


    def _annotation_image_data(self, image_key):
        return (
            self.image_data
            if image_key == self.file_path
            else read(image_key, None)
        )

    @property
    def file_path(self):
        return self.workbench_session.image_path

    @property
    def system_trash(self):
        return self._system_trash

    @system_trash.setter
    def system_trash(self, value):
        self._system_trash = value
        if hasattr(self, 'file_operations'):
            self.file_operations.replace_trash_adapter(value)
        if hasattr(self, 'image_processing_transaction'):
            self.image_processing_transaction.replace_trash_adapter(value)

    def change_language(self, language):
        if not set_language(language):
            return
        self.settings[SETTING_LANGUAGE] = current_language()
        self.settings.save()
        self.retranslate_ui()
        self.status(tr(
            'language.changed',
            language=LANGUAGE_NAMES[current_language()],
        ))

    def retranslate_ui(self):
        if not hasattr(self, '_i18n_action_specs'):
            return
        for action, (text_id, tip_id) in self._i18n_action_specs.items():
            set_action_copy(
                action,
                tr(text_id) if text_id is not None else None,
                tr(tip_id) if tip_id is not None else None,
            )
        self.use_default_label_checkbox.setText(tr('useDefaultLabel'))
        self.diffc_button.setText(tr('useDifficult'))
        self.label_filter.setPlaceholderText(tr('labels.filter'))
        self.restore_near_duplicate_action.setText(
            tr('nearDuplicate.restoreDismissed')
        )
        self.near_duplicate_more_button.setToolTip(
            tr('nearDuplicate.moreActions')
        )
        self.near_duplicate_more_button.setAccessibleName(
            tr('nearDuplicate.moreActions')
        )
        self.file_list_empty_label.setText(tr('files.noMatch'))
        self.file_list_clear_filter_button.setText(tr('files.clearFilter'))
        self.dock.setWindowTitle(tr('boxLabelText'))
        self.file_dock.setWindowTitle(tr('fileList'))
        self.image_quality_dock.setWindowTitle(tr('quality.panelTitle'))
        set_action_copy(self.actions.labels, tr('showHide'))
        self.menus.file.setTitle(tr('menu_file'))
        self.menus.edit.setTitle(tr('menu_edit'))
        self.menus.image.setTitle(tr('menu_image'))
        self.menus.view.setTitle(tr('menu_view'))
        self.menus.settings.setTitle(tr('menu_settings'))
        self.menus.help.setTitle(tr('menu_help'))
        self.menus.recentFiles.setTitle(tr('menu_openRecent'))
        self.menus.annotationDirectory.setTitle(
            tr('annotationDirectory.menu')
        )
        self.menus.geometry.setTitle(tr('geometry.menu'))
        self.menus.specializedRepair.setTitle(tr('specializedRepair.menu'))
        self._sync_annotation_directory_ui()
        self.menus.language.setTitle(tr('language.menu'))
        self.tools.setWindowTitle(tr('toolbar.canvasTools'))
        self.tools.retranslate_ui()
        self.top_commands.retranslate_ui()
        self.review_control.retranslate_ui()
        self.format_selector.retranslate_ui()
        self.zoom_widget.retranslate_ui()
        for button in (
            self.edit_button,
            self.copy_button,
            self.delete_button,
            self.visibility_button,
        ):
            action = button.defaultAction()
            button.setAccessibleName(action.text().replace('&', ''))
            button.setAccessibleDescription(action.toolTip())
        self.crop_controls.retranslate()
        self.zoom_widget.setWhatsThis(tr(
            'zoom.help',
            keyboard=format_shortcut("Ctrl+[-+]"),
            wheel=format_shortcut("Ctrl+Wheel"),
        ))
        for language, action in self.language_actions.items():
            action.setChecked(language == current_language())
        self.canvas.setToolTip(tr('canvas.image'))
        self.update_file_selection_count()
        self.label_summary_label.setText(self.label_list.summary_text())
        if hasattr(self, 'annotation_editing'):
            self._sync_annotation_history_ui()
        self.toggle_all_annotations(
            self.actions.toggleVisibility.isChecked()
        )
        if self.file_list_widget.count():
            self.refresh_file_list_statuses()

    @property
    def default_save_dir(self):
        return self._default_save_dir

    @default_save_dir.setter
    def default_save_dir(self, value):
        self._default_save_dir = value
        if hasattr(self, 'annotation_workspace'):
            self.annotation_workspace.set_save_dir(value)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Control:
            self.canvas.set_multi_selection_mode(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Control:
            self.canvas.set_multi_selection_mode(True)

    def eventFilter(self, watched, event):
        if (
            watched is getattr(self, 'canvas', None)
            and event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_Escape
            and self.canvas.mode in (Canvas.CREATE, Canvas.PAN)
        ):
            if self.canvas.mode == Canvas.CREATE:
                self.canvas.cancel_current_drawing(force=True)
            self.set_edit_mode()
            event.accept()
            return True
        if (
            watched is getattr(self, 'canvas', None)
            and event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_C
            and event.modifiers() == Qt.NoModifier
        ):
            self.enter_crop_mode()
            event.accept()
            return True
        return super(MainWindow, self).eventFilter(watched, event)

    # Support Functions #



























    def toggle_actions(self, value=True):
        """Enable/Disable widgets which depend on an opened image."""
        for z in self.actions.zoomActions:
            z.setEnabled(value)
        for action in self.actions.onLoadActive:
            action.setEnabled(value)
        self.review_control.setEnabled(value)
        if value:
            self.actions.selectTool.setChecked(True)

    def queue_event(self, function):
        QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        self.statusBar().showMessage(message, delay)

    def reset_state(self, preserve_session=False):
        self.label_list.clear()
        self.label_filter.clear()
        if not preserve_session:
            self.workbench_session.clear()
        self.image_data = None
        self.image = QImage()
        self.annotation_document = None
        self.canvas.reset_state()
        self.label_coordinates.clear()
        if hasattr(self, 'file_list_widget'):
            self.update_current_file_marker()

    def _begin_workspace_editing_session(self):
        """Apply preferences that intentionally reset for each workspace."""
        self.auto_saving.setChecked(True)

    def _load_indexed_image(self, filename):
        """Keep the file counter aligned and roll it back after load failure."""
        previous_index = self.cur_img_idx
        self.cur_img_idx = self.m_img_list.index(filename)
        if self.load_file(filename):
            return True
        self.cur_img_idx = previous_index
        self.update_file_navigation_actions()
        return False

    def current_item(self):
        return self.canvas.selection_snapshot.active

    def add_recent_file(self, file_path):
        if file_path in self.recent_files:
            self.recent_files.remove(file_path)
        elif len(self.recent_files) >= self.max_recent:
            self.recent_files.pop()
        self.recent_files.insert(0, file_path)

    def show_tutorial_dialog(self, browser='default', link=None):
        if link is None:
            link = self.screencast

        if browser.lower() == 'default':
            wb.open(link, new=2)
        elif browser.lower() == 'chrome' and self.os_name == 'Windows':
            if shutil.which(browser.lower()):  # 'chrome' not in wb._browsers in windows
                wb.register('chrome', None, wb.BackgroundBrowser('chrome'))
            else:
                chrome_path="D:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
                if os.path.isfile(chrome_path):
                    wb.register('chrome', None, wb.BackgroundBrowser(chrome_path))
            try:
                wb.get('chrome').open(link, new=2)
            except:
                wb.open(link, new=2)
        elif browser.lower() in wb._browsers:
            wb.get(browser.lower()).open(link, new=2)

    def show_default_tutorial_dialog(self):
        self.show_tutorial_dialog(browser='default')

    def show_info_dialog(self):
        from labelimg.__init__ import __version__

        AboutDialog(
            __appname__,
            __version__,
            sys.version.split()[0],
            self,
        ).exec_()

    def show_shortcuts_dialog(self):
        ShortcutCatalogDialog(self).exec_()
















































































    # Tzutalin 20160906 : Add file list and dock to move faster

    # Add chris

    # React to canvas signals.















    @staticmethod
    def _resource_key(path):
        return os.path.normcase(os.path.abspath(os.fspath(path)))





    # Callback functions:










    def load_file(
        self,
        file_path=None,
        prepared_image_data=_UNPREPARED_IMAGE_DATA,
    ):
        """Load the specified file, or the last opened file if None."""
        if prepared_image_data is _UNPREPARED_IMAGE_DATA:
            self.cancel_deferred_image_load()
        if file_path is None:
            file_path = self.settings.get(SETTING_FILENAME)

        # Make sure that filePath is a regular python string, rather than QString
        file_path = ustr(file_path)
        if hasattr(self, 'annotation_editing'):
            self._cancel_annotation_edit_for_navigation()
        if file_path:
            try:
                supplied_format = AnnotationFormat.from_path(file_path)
            except AnnotationDocumentError:
                supplied_format = None
        else:
            supplied_format = None
        if supplied_format is None and file_path and os.path.isfile(file_path):
            try:
                self.annotation_workspace.refresh_document_choices(
                    os.path.abspath(file_path)
                )
            except AnnotationDocumentError as error:
                self.error_message(
                    tr('open.annotationTitle'),
                    u'<b>%s</b>' % error,
                )
                return False
        if (
            supplied_format is None
            and file_path
            and os.path.isfile(file_path)
            and not self._ensure_active_annotation_choice(
                os.path.abspath(file_path)
            )
        ):
            return False

        # Fix bug: An  index error after select a directory when open a new file.
        unicode_file_path = ustr(file_path)
        unicode_file_path = os.path.abspath(unicode_file_path)
        annotation_path = None
        try:
            annotation_format = AnnotationFormat.from_path(
                unicode_file_path
            )
        except AnnotationDocumentError:
            annotation_format = None
        if annotation_format is not None:
            annotation_path = unicode_file_path
            unicode_file_path = image_path_hint(
                annotation_path
            )
            if unicode_file_path is None:
                annotation_stem = os.path.splitext(annotation_path)[0]
                extensions = [
                    '.%s' % image_format.data().decode("ascii").lower()
                    for image_format in QImageReader.supportedImageFormats()
                ]
                unicode_file_path = next(
                    (
                        annotation_stem + extension
                        for extension in extensions
                        if os.path.isfile(annotation_stem + extension)
                    ),
                    None,
                )
            if unicode_file_path is None:
                self.error_message(
                    tr('open.annotationTitle'),
                    u'<p>%s</p>' % tr('open.imageMissing'),
                )
                return False

        if not unicode_file_path or not os.path.exists(unicode_file_path):
            return False
        if prepared_image_data is _UNPREPARED_IMAGE_DATA:
            prepared_image_data = read(unicode_file_path, None)
        prepared_image = (
            prepared_image_data
            if isinstance(prepared_image_data, QImage)
            else QImage.fromData(prepared_image_data)
        )
        if prepared_image.isNull():
            self.error_message(
                tr('open.fileTitle'),
                u"<p>%s</p>" % tr(
                    'open.invalidImage', path=unicode_file_path
                ),
            )
            self.status(tr('status.errorReading', detail=unicode_file_path))
            return False
        try:
            prepared_annotation = (
                self.annotation_workspace.load(
                    annotation_path,
                    unicode_file_path,
                    prepared_image_data,
                )
                if annotation_path is not None
                else self.annotation_workspace.load_for_image(
                    unicode_file_path,
                    prepared_image_data,
                )
            )
        except AnnotationDocumentError as error:
            self.error_message(
                tr('open.annotationTitle'),
                u'<b>%s</b>' % error,
            )
            return False
        transition_ticket = getattr(
            self, '_workbench_transition_ticket', None
        )

        self.reset_state(preserve_session=True)
        self.canvas.setEnabled(False)

        # Tzutalin 20160906 : Add file list and dock to move faster
        # Keep file selection independent from the image being opened.
        if unicode_file_path and self.file_list_widget.count() > 0:
            if unicode_file_path not in self.m_img_list:
                self.file_list_widget.clear()
                self.m_img_list.clear()

        if unicode_file_path and os.path.exists(unicode_file_path):
            # Load image data first and retain it for annotation saving.
            self.image_data = prepared_image_data
            self.annotation_document = None
            self.canvas.verified = False
            self.canvas.questioned = False
            self.review_control.set_state('unreviewed')

            image = prepared_image
            self.status(tr('status.loaded', name=os.path.basename(unicode_file_path)))
            self.image = image
            if (
                transition_ticket is not None
                and transition_ticket.target == unicode_file_path
            ):
                self.workbench_session.commit_transition(transition_ticket)
            else:
                self.workbench_session.cancel_transition(transition_ticket)
                self.workbench_session.activate(unicode_file_path)
            self._workbench_transition_ticket = None
            self.update_current_file_marker()
            self.canvas.load_pixmap(QPixmap.fromImage(image))
            if prepared_annotation is not None:
                self.set_format(document_format_name(
                    prepared_annotation.annotation_format
                ))
                self.load_annotation_document(prepared_annotation.document)
                self.annotation_workspace.record_document(
                    self.file_path,
                    prepared_annotation.annotation_path,
                    (
                        box.label
                        for box in prepared_annotation.document.boxes
                    ),
                )
            self.set_clean()
            self.canvas.setEnabled(True)
            self.adjust_scale(initial=True)
            self.paint_canvas()
            self.add_recent_file(self.file_path)
            self.toggle_actions(True)
            self._activate_annotation_history()
            self.refresh_candidate_labels()

            counter = self.counter_str()
            self.setWindowTitle(__appname__ + ' ' + file_path + ' ' + counter)
            self.update_file_navigation_actions()
            self.set_edit_mode()

            self.canvas.setFocus(True)
            return True
        return False

    def _ensure_active_annotation_choice(self, image_path, force=False):
        choices = self.annotation_workspace.document_choices(image_path)
        if (
            len(choices) < 2
            or (
                not force
                and self.annotation_workspace.active_document_path(image_path)
            )
        ):
            return True
        labels = [
            '%s  |  %s  |  %s'
            % (
                choice.annotation_format.display_name,
                choice.annotation_path,
                QDateTime.fromMSecsSinceEpoch(
                    choice.modified_ns // 1_000_000
                ).toString(Qt.ISODate),
            )
            for choice in choices
        ]
        selected, accepted = QInputDialog.getItem(
            self,
            tr('open.chooseDocument'),
            tr('open.chooseDocumentPrompt'),
            labels,
            0,
            False,
        )
        if not accepted:
            return False
        index = labels.index(selected)
        self.annotation_workspace.select_active_document(
            image_path,
            choices[index].annotation_path,
        )
        return True

    def counter_str(self):
        """
        Converts image counter to string representation.
        """
        return '[{} / {}]'.format(self.cur_img_idx + 1, self.img_count)

    def show_bounding_box_from_annotation_file(self, file_path):
        try:
            loaded = self.annotation_workspace.load_for_image(
                file_path,
                self.image_data,
            )
        except AnnotationDocumentError as error:
            self.status(tr('status.errorReading', detail=error))
            return False
        if loaded is None:
            return False
        self.set_format(document_format_name(loaded.annotation_format))
        self.load_annotation_document(loaded.document)
        self.annotation_workspace.record_document(
            file_path,
            loaded.annotation_path,
            (box.label for box in loaded.document.boxes),
        )
        self.refresh_candidate_labels()
        return True






    def closeEvent(self, event):
        if not self.finish_deferred_image_loads():
            event.ignore()
            self.status(tr('status.imageLoadingBusy'))
            return
        if (
            self.annotation_persistence.conflicts
            and not self._resolve_conflicts_for_close()
        ):
            event.ignore()
            return
        if not self.may_continue():
            event.ignore()
            return
        if (
            self._image_quality_thread is not None
            and self._image_quality_thread.isRunning()
        ):
            self._image_quality_worker.cancel()
            self._image_quality_thread.quit()
            if not self._image_quality_thread.wait(5000):
                event.ignore()
                self.status(tr('quality.busy'))
                return
        settings = self.settings
        # If it loads images from dir, don't load it at the beginning
        if self.dir_name is None:
            settings[SETTING_FILENAME] = self.file_path if self.file_path else ''
        else:
            settings[SETTING_FILENAME] = ''

        settings[SETTING_WIN_SIZE] = self.size()
        settings[SETTING_WIN_POSE] = self.pos()
        settings[SETTING_WIN_STATE] = self.saveState()
        settings[SETTING_LINE_COLOR] = self.line_color
        settings[SETTING_FILL_COLOR] = self.fill_color
        settings[SETTING_RECENT_FILES] = self.recent_files
        if self.default_save_dir and os.path.exists(self.default_save_dir):
            settings[SETTING_SAVE_DIR] = ustr(self.default_save_dir)
        else:
            settings[SETTING_SAVE_DIR] = ''

        if self.last_open_dir and os.path.exists(self.last_open_dir):
            settings[SETTING_LAST_OPEN_DIR] = self.last_open_dir
        else:
            settings[SETTING_LAST_OPEN_DIR] = ''

        settings[SETTING_AUTO_SAVE] = self.auto_saving.isChecked()
        settings[SETTING_SINGLE_CLASS] = self.single_class_mode.isChecked()
        settings[SETTING_PAINT_LABEL] = self.display_label_option.isChecked()
        settings[SETTING_DRAW_SQUARE] = self.draw_squares_option.isChecked()
        settings[SETTING_LABEL_FILE_FORMAT] = self.annotation_format
        settings[SETTING_FILE_LIST_SORT_KEY] = (
            self.file_list_controls.state.sort_key
        )
        settings[SETTING_FILE_LIST_SORT_DESCENDING] = (
            self.file_list_controls.state.descending
        )
        settings[SETTING_LANGUAGE] = current_language()
        settings.save()

    def _resolve_conflicts_for_close(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('conflict.resolveTitle'))
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            tr('conflict.resolvePrompt')
        ))
        conflicts = list(self.annotation_persistence.conflicts.values())
        table = QTableWidget(len(conflicts), 2, dialog)
        table.setHorizontalHeaderLabels((
            tr('conflict.resource'),
            tr('conflict.resolution'),
        ))
        choices = []
        for row, conflict in enumerate(conflicts):
            item = QTableWidgetItem(conflict.resource)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, 0, item)
            combo = QComboBox(table)
            combo.addItems(
                (
                    tr('common.choose'),
                    tr('conflict.loadExternal'),
                    tr('conflict.overwriteExternal'),
                )
            )
            table.setCellWidget(row, 1, combo)
            choices.append(combo)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        apply_to_all = QComboBox(dialog)
        apply_to_all.addItems(
            (
                tr('conflict.applyAll'),
                tr('conflict.loadAll'),
                tr('conflict.overwriteAll'),
            )
        )
        layout.addWidget(apply_to_all)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            dialog,
        )
        localize_dialog_buttons(buttons)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        ok_button.setEnabled(False)

        def update_ok():
            ok_button.setEnabled(
                all(combo.currentIndex() > 0 for combo in choices)
            )

        for combo in choices:
            combo.currentIndexChanged.connect(update_ok)

        def apply_resolution(index):
            if index <= 0:
                return
            for combo in choices:
                combo.setCurrentIndex(index)

        apply_to_all.currentIndexChanged.connect(apply_resolution)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(700, 300)
        if dialog.exec_() != QDialog.Accepted:
            return False

        for conflict, combo in zip(conflicts, choices):
            if combo.currentIndex() == 1:
                if not self._load_external_resource_conflict(conflict):
                    return False
            else:
                if not self._overwrite_resource_conflict(conflict):
                    return False
        return True

    def _load_external_resource_conflict(self, conflict):
        affected = tuple(conflict.image_keys)
        dirty_count = sum(
            1
            for image_key in affected
            if self.annotation_editing.has_image(image_key)
            and self.annotation_editing.view_image(
                image_key, touch=False
            ).dirty
        )
        if conflict.affected_count > 1 or dirty_count > 1:
            answer = localized_question(
                self,
                tr('conflict.loadSharedTitle'),
                tr(
                    'conflict.loadShared',
                    images=conflict.affected_count,
                    dirty=dirty_count,
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False
        try:
            image_resource = any(
                self._resource_key(image_key)
                == self._resource_key(conflict.resource)
                for image_key in affected
            )
            prepared = []
            if (
                not image_resource
                and conflict.resource.lower().endswith('.json')
            ):
                self.annotation_workspace.validate_create_ml_resource(
                    conflict.resource
                )
            for image_key in affected:
                if not self.annotation_editing.has_image(image_key):
                    continue
                view = self.annotation_editing.view_image(
                    image_key, touch=False
                )
                if image_resource:
                    image_data = (
                        self.image_data
                        if image_key == self.file_path
                        else read(image_key, None)
                    )
                    image = (
                        image_data
                        if isinstance(image_data, QImage)
                        else QImage.fromData(image_data)
                    )
                    if image.isNull():
                        raise AnnotationDocumentError(
                            'External image is not readable: %s'
                            % image_key
                        )
                    prepared.append((image_key, view, None))
                    continue
                if self._resource_key(conflict.resource) not in (
                    self.annotation_persistence.resource_keys_for(view)
                ):
                    continue
                image_data = (
                    self.image_data
                    if image_key == self.file_path
                    else read(image_key, None)
                )
                if os.path.isfile(view.current_target):
                    loaded = self.annotation_workspace.load(
                        view.current_target,
                        image_key,
                        image_data,
                    )
                else:
                    loaded = SimpleNamespace(
                        annotation_path=view.current_target,
                        annotation_format=AnnotationFormat.from_path(
                            view.current_target
                        ),
                        document=AnnotationDocument(
                            image_path=image_key,
                            image_data=image_data,
                        ),
                    )
                prepared.append((image_key, view, loaded))

            external_key = self._resource_key(conflict.resource)
            external_fingerprint = fingerprint_path(
                conflict.resource
            )
            external_content = self._read_resource_bytes(
                conflict.resource
            )
            current_item = next(
                (
                    item
                    for item in prepared
                    if item[0] == self.file_path
                ),
                None,
            )
            if current_item is not None and not image_resource:
                image_key, view, loaded = current_item
                old_snapshot = view.snapshot
                try:
                    self.clear_current_labels()
                    self.load_annotation_document(loaded.document)
                    self._rebase_current_history(view.current_target)
                except Exception as commit_error:
                    try:
                        self.annotation_scene.project(
                            self._history_projection_request(
                                old_snapshot,
                                direction='load-external-rollback',
                                preserve_selection=True,
                            )
                        )
                    except Exception as rollback_error:
                        self._annotation_projection_degraded(
                            image_key,
                            commit_error,
                            rollback_error,
                        )
                    raise
                self.annotation_persistence.release(view)

            for image_key, view, _loaded in prepared:
                if _loaded is not None:
                    self.annotation_workspace.record_document(
                        image_key,
                        _loaded.annotation_path,
                        (box.label for box in _loaded.document.boxes),
                    )
                if image_key == self.file_path and not image_resource:
                    continue
                self.annotation_persistence.release(view)
                self.annotation_editing.remove_images((image_key,))
                self.annotation_scene.forget_image(image_key)
            if image_resource and current_item is not None:
                self.load_file(current_item[0])

            self.annotation_workspace.apply_transaction_resources(
                {external_key: external_fingerprint},
                {external_key: external_content},
            )
        except Exception as error:
            self.error_message(
                tr('conflict.resolveFailed'),
                '<p>%s</p>' % error,
            )
            return False
        self.annotation_persistence.clear_conflicts((conflict.resource,))
        self.refresh_candidate_labels()
        self.refresh_file_list_statuses()
        self._watch_current_annotation_document()
        return True

    def _overwrite_resource_conflict(self, conflict):
        if any(
            self._resource_key(image_key)
            == self._resource_key(conflict.resource)
            for image_key in conflict.image_keys
        ):
            self.error_message(
                tr('conflict.imageTitle'),
                '<p>%s</p>' % tr('conflict.imageChanged'),
            )
            return False
        affected_views = [
            self.annotation_editing.view_image(
                image_key, touch=False
            )
            for image_key in conflict.image_keys
            if self.annotation_editing.has_image(image_key)
        ]
        dirty_views = [view for view in affected_views if view.dirty]
        if conflict.affected_count > 1 or len(dirty_views) > 1:
            answer = localized_question(
                self,
                tr('conflict.overwriteSharedTitle'),
                tr(
                    'conflict.overwriteShared',
                    images=conflict.affected_count,
                    dirty=len(dirty_views),
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False
        outcome = self.annotation_persistence.overwrite_conflict(
            conflict.resource, self.annotation_format
        )
        if not outcome.ok:
            self.error_message(
                tr('conflict.saveFailed'),
                '<p>%s</p>' % outcome.failure.error,
            )
            return False
        for receipt in outcome.saved:
            saved = receipt.workspace_save
            if receipt.image_key == self.file_path:
                self.annotation_document = saved.document
            self.update_file_list_item_status(receipt.image_key)
        self.refresh_file_list_statuses()
        return outcome.saved_by_image.get(self.file_path, True)

    def load_recent(self, filename):
        if self.may_continue():
            self.load_file(filename)











    def _sync_annotation_directory_ui(self):
        if not hasattr(self, 'annotation_directory_label'):
            return
        custom_dir = ustr(self.default_save_dir or '')
        if custom_dir:
            name = os.path.basename(os.path.normpath(custom_dir)) or custom_dir
            status_text = tr(
                'annotationDirectory.statusCustom',
                name=name,
            )
            current_text = tr(
                'annotationDirectory.currentCustom',
                name=name,
            )
            tooltip = os.path.abspath(custom_dir)
        else:
            status_text = tr('annotationDirectory.statusImage')
            current_text = tr('annotationDirectory.currentImage')
            image_directory = (
                getattr(self, 'dir_name', None)
                or (
                    os.path.dirname(getattr(self, 'file_path', ''))
                    if getattr(self, 'file_path', '')
                    else ''
                )
            )
            tooltip = (
                os.path.abspath(image_directory)
                if image_directory
                else tr('annotationDirectory.imageTooltip')
            )
        self.annotation_directory_label.setText(status_text)
        self.annotation_directory_label.setToolTip(tooltip)
        if hasattr(self, 'actions') and hasattr(
            self.actions,
            'annotationDirectoryCurrent',
        ):
            self.actions.annotationDirectoryCurrent.setText(current_text)
            self.actions.useImageDirectory.setEnabled(bool(custom_dir))

    def _switch_annotation_directory(self, directory):
        if not self.may_continue():
            return False
        directory = os.path.abspath(directory) if directory else None
        scan_directory = (
            directory
            or self.dir_name
            or (os.path.dirname(self.file_path) if self.file_path else None)
        )
        replacement = AnnotationWorkspace(save_dir=directory)
        try:
            if scan_directory and os.path.isdir(scan_directory):
                replacement.scan(scan_directory)
            loaded = (
                replacement.load_for_image(
                    self.file_path,
                    self.image_data,
                )
                if self.file_path
                else None
            )
        except Exception as error:
            self.error_message(
                tr('error.changeAnnotationDir'),
                '<p>%s</p>' % error,
            )
            return False
        self.annotation_persistence.clear_conflicts(
            tuple(self.annotation_persistence.conflicts)
        )
        self.annotation_persistence.replace_workspace(replacement)
        self.annotation_workspace = replacement
        self.review_state_transaction.replace_workspace(replacement)
        self.file_operations.replace_workspace(replacement)
        self.image_processing.replace_workspace(replacement)
        self._default_save_dir = directory
        for label in replacement.candidate_labels:
            if label not in self.label_hist:
                self.label_hist.append(label)
        self.annotation_editing.clear_workspace()
        self.annotation_scene.clear_workspace()
        self.clear_near_duplicate_session()
        self.file_operations.clear_recovery()
        self.image_processing.clear_recovery()
        self._begin_workspace_editing_session()
        if self.file_path:
            self.clear_current_labels()
            if loaded is not None:
                self.set_format(
                    document_format_name(loaded.annotation_format)
                )
                self.load_annotation_document(loaded.document)
            else:
                self.canvas.verified = False
                self.canvas.questioned = False
            self._activate_annotation_history()
        self.refresh_candidate_labels()
        self.refresh_file_list_statuses()
        self._sync_annotation_directory_ui()
        return True

    def commit_indexed_annotation_directory(self, directory, replacement):
        """Atomically install an annotation workspace built off the UI thread."""
        if not self.may_continue():
            return False
        try:
            loaded = (
                replacement.load_for_image(self.file_path, self.image_data)
                if self.file_path else None
            )
        except Exception as error:
            self.error_message(
                tr('error.changeAnnotationDir'), '<p>%s</p>' % error
            )
            return False
        self.annotation_persistence.clear_conflicts(
            tuple(self.annotation_persistence.conflicts)
        )
        self.annotation_persistence.replace_workspace(replacement)
        self.annotation_workspace = replacement
        self.review_state_transaction.replace_workspace(replacement)
        self.file_operations.replace_workspace(replacement)
        self.image_processing.replace_workspace(replacement)
        self._default_save_dir = directory
        for label in replacement.candidate_labels:
            if label not in self.label_hist:
                self.label_hist.append(label)
        self.annotation_editing.clear_workspace()
        self.annotation_scene.clear_workspace()
        self.clear_near_duplicate_session()
        self.file_operations.clear_recovery()
        self.image_processing.clear_recovery()
        self._begin_workspace_editing_session()
        if self.file_path:
            self.clear_current_labels()
            if loaded is not None:
                self.set_format(document_format_name(loaded.annotation_format))
                self.load_annotation_document(loaded.document)
            else:
                self.canvas.verified = False
                self.canvas.questioned = False
            self._activate_annotation_history()
        self.refresh_candidate_labels()
        self.refresh_file_list_statuses()
        self._sync_annotation_directory_ui()
        return True

    def change_save_dir_dialog(self, _value=False):
        if self.default_save_dir is not None:
            path = ustr(self.default_save_dir)
        else:
            path = '.'

        dir_path = ustr(QFileDialog.getExistingDirectory(self,
                                                         tr('dialog.saveDirectory', app=__appname__), path,  QFileDialog.ShowDirsOnly
                                                         | QFileDialog.DontResolveSymlinks))

        if dir_path is not None and len(dir_path) > 1:
            dir_path = os.path.abspath(dir_path)
            if (
                self.default_save_dir
                and os.path.abspath(self.default_save_dir) == dir_path
            ):
                return
            switched = (
                self.start_annotation_directory_load(dir_path)
                if self.isVisible()
                else self._switch_annotation_directory(dir_path)
            )
            if switched:
                self.statusBar().showMessage(tr(
                    'status.saveDirectoryChanged',
                    path=self.default_save_dir,
                ))
                self.statusBar().show()

    def use_image_directory_for_annotations(self, _value=False):
        if not self.default_save_dir:
            return
        switched = (
            self.start_annotation_directory_load(None)
            if self.isVisible()
            else self._switch_annotation_directory(None)
        )
        if switched:
            self.statusBar().showMessage(
                tr('status.annotationDirectoryUsesImage')
            )
            self.statusBar().show()

    def open_annotation_dialog(self, _value=False):
        if self.file_path is None:
            self.statusBar().showMessage(tr('status.selectImage'))
            self.statusBar().show()
            return
        if not self.may_continue():
            return

        path = os.path.dirname(ustr(self.file_path))\
            if self.file_path else '.'
        filters = tr('dialog.annotationFilter', patterns=' '.join(
            '*%s' % annotation_format.extension
            for annotation_format in AnnotationFormat
        ))
        filename = ustr(
            QFileDialog.getOpenFileName(
                self,
                tr('dialog.chooseAnnotation', app=__appname__),
                path,
                filters,
            )
        )
        if filename and isinstance(filename, (tuple, list)):
            filename = filename[0]
        if filename:
            self.load_annotation_by_filename(filename)

    def open_dir_dialog(self, _value=False, dir_path=None, silent=False):
        if not self.may_continue():
            return

        default_open_dir_path = dir_path if dir_path else '.'
        if self.last_open_dir and os.path.exists(self.last_open_dir):
            default_open_dir_path = self.last_open_dir
        else:
            default_open_dir_path = os.path.dirname(self.file_path) if self.file_path else '.'
        if silent != True:
            target_dir_path = ustr(QFileDialog.getExistingDirectory(self,
                                                                    tr('dialog.openDirectory', app=__appname__), default_open_dir_path,
                                                                    QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks))
        else:
            target_dir_path = ustr(default_open_dir_path)
        self.last_open_dir = target_dir_path
        if self.isVisible():
            self.start_directory_load(target_dir_path)
        else:
            self.import_dir_images(target_dir_path)

    def import_dir_images(self, dir_path, initial_index=0):
        if not self.may_continue() or not dir_path:
            return
        self.workbench_session.commit_transition(
            self._workbench_transition_ticket
        )

        changing_workspace = (
            self.dir_name is None
            or os.path.abspath(self.dir_name)
            != os.path.abspath(dir_path)
        )
        if changing_workspace:
            self.annotation_persistence.clear_conflicts(
                tuple(self.annotation_persistence.conflicts)
            )
            self.annotation_editing.clear_workspace()
            self.annotation_scene.clear_workspace()
            self.clear_near_duplicate_session()
            self.file_operations.clear_recovery()
            self.image_processing.clear_recovery()
            self.file_list_controls.clear_filters(emit=False)
            self._begin_workspace_editing_session()
        self.last_open_dir = dir_path
        self.dir_name = dir_path
        self._sync_annotation_directory_ui()
        image_paths = self.scan_all_images(dir_path)
        annotation_directory = self.default_save_dir or dir_path
        if annotation_directory and os.path.isdir(annotation_directory):
            self.annotation_workspace.scan(annotation_directory, force=False)
            self.refresh_candidate_labels()
        from labelimg.image_tools.domain.quality import ImageQualityPolicy
        self.image_quality_results.update(
            self.image_quality_cache.summaries(
                image_paths, ImageQualityPolicy.standard()
            )
        )
        self.populate_file_list(image_paths)

        if self.img_count:
            self.cur_img_idx = min(max(initial_index, 0), self.img_count - 1)
            self.load_file(self.m_img_list[self.cur_img_idx])
        else:
            self.cur_img_idx = 0
            self.reset_state(preserve_session=True)
            self.set_clean()
            self.toggle_actions(False)
            self.canvas.setEnabled(False)
            self.actions.saveAs.setEnabled(False)

    def commit_discovered_directory(
        self, dir_path, image_paths, initial_index=0
    ):
        """Commit directory-ready state without waiting for annotation index."""
        if not self.may_continue() or not dir_path:
            return False
        self.workbench_session.commit_transition(
            self._workbench_transition_ticket
        )
        changing_workspace = (
            self.dir_name is None
            or os.path.abspath(self.dir_name) != os.path.abspath(dir_path)
        )
        if changing_workspace:
            self.annotation_persistence.clear_conflicts(
                tuple(self.annotation_persistence.conflicts)
            )
            replacement = AnnotationWorkspace(save_dir=self.default_save_dir)
            self.annotation_persistence.replace_workspace(replacement)
            self.annotation_workspace = replacement
            self.review_state_transaction.replace_workspace(replacement)
            self.file_operations.replace_workspace(replacement)
            self.image_processing.replace_workspace(replacement)
            self.annotation_editing.clear_workspace()
            self.annotation_scene.clear_workspace()
            self.clear_near_duplicate_session()
            self.file_operations.clear_recovery()
            self.image_processing.clear_recovery()
            self.file_list_controls.clear_filters(emit=False)
            self._begin_workspace_editing_session()
        self.last_open_dir = dir_path
        self.dir_name = dir_path
        self._sync_annotation_directory_ui()
        from labelimg.image_tools.domain.quality import ImageQualityPolicy
        self.image_quality_results.update(
            self.image_quality_cache.summaries(
                image_paths, ImageQualityPolicy.standard()
            )
        )
        initial_paths = tuple(image_paths[:64])
        self.populate_file_list(initial_paths, indexed=False)
        all_paths = tuple(image_paths)
        self.m_img_list = list(all_paths)
        self.img_count = len(all_paths)
        from labelimg.files import FileListProjection
        self._file_list_projection = FileListProjection(
            os.path.abspath(self.dir_name),
            self.file_list_controls.state.query,
            (),
            all_paths,
            all_paths,
        )
        if self.img_count:
            self.cur_img_idx = min(max(initial_index, 0), self.img_count - 1)
            self.load_file(self.m_img_list[self.cur_img_idx])
        else:
            self.cur_img_idx = 0
            self.reset_state(preserve_session=True)
            self.set_clean()
            self.toggle_actions(False)
            self.canvas.setEnabled(False)
            self.actions.saveAs.setEnabled(False)
        return len(initial_paths)

    def _file_list_item(self, image_path, indexed=True):
        from labelimg.image_tools import quality_finding_text
        if indexed:
            annotation_state, review_state, persistence_flags = (
                self.file_workspace_state(image_path)
            )
        else:
            annotation_state = 'unannotated'
            review_state = 'unreviewed'
            persistence_flags = ()
        item = FileListItem(self.file_list_item_text(image_path))
        item.setData(Qt.UserRole, image_path)
        item.setData(FILE_ANNOTATION_STATE_ROLE, annotation_state)
        item.setData(FILE_REVIEW_STATE_ROLE, review_state)
        item.setData(FILE_PERSISTENCE_FLAGS_ROLE, persistence_flags)
        quality_result = self._quality_result_for_path(image_path)
        item.setData(
            FILE_QUALITY_FINDINGS_ROLE,
            tuple({
                'code': finding.code,
                'severity': finding.severity,
                'explanation': quality_finding_text(finding),
            } for finding in quality_result.findings)
            if quality_result is not None else (),
        )
        item.setData(CURRENT_IMAGE_ROLE, image_path == self.file_path)
        item.setToolTip(image_path)
        return item

    def append_file_list_rows(self, image_paths, indexed=False):
        first = self.file_list_widget.count()
        items = [
            self._file_list_item(path, indexed=indexed)
            for path in image_paths
        ]
        self.file_list_widget.addItems(items)
        for offset, path in enumerate(image_paths):
            self._file_row_by_path[path] = first + offset
        return len(items)

    def populate_file_list(
        self, image_paths, indexed=True, preserve_query=False
    ):
        query = (
            self.file_list_controls.state.query
            if preserve_query and hasattr(self, 'file_list_controls')
            else None
        )
        blocker = QSignalBlocker(self.file_list_widget)
        self.file_list_widget.clear()
        self.m_img_list = list(image_paths)
        self._file_row_by_path = {
            path: index for index, path in enumerate(self.m_img_list)
        }
        self.img_count = len(self.m_img_list)
        items = [self._file_list_item(path, indexed=indexed)
                 for path in self.m_img_list]
        self.file_list_widget.setItems(items)
        del blocker
        if indexed:
            if query is not None:
                self.file_list_controls.state.set_filter(
                    text=query.text,
                    annotation=query.annotation,
                    review=query.review,
                    alert=query.alert,
                    quality=query.quality,
                )
            self.apply_file_list_view(scroll_current=False)
        else:
            from labelimg.files import FileListProjection
            paths = tuple(self.m_img_list)
            self._file_list_projection = FileListProjection(
                os.path.abspath(self.dir_name) if self.dir_name else None,
                self.file_list_controls.state.query,
                (),
                paths,
                paths,
            )
            self.file_list_controls.set_workspace_available(bool(paths))
            self.file_list_stack.setCurrentWidget(self.file_list_widget)
            self.update_current_file_marker()




    def open_prev_image(self, _value=False):
        if self.img_count <= 0:
            return

        if self.file_path is None:
            return

        filename = self._adjacent_visible_file(-1)
        if filename and self._guard_image_navigation(filename):
            self._load_indexed_image(filename)

    def open_next_image(self, _value=False):
        if self.img_count <= 0:
            return

        filename = self._adjacent_visible_file(1)

        if filename and self._guard_image_navigation(filename):
            self._load_indexed_image(filename)

    def _guard_image_navigation(self, target):
        """Resolve only the current image before a user-requested switch."""
        target = os.path.abspath(os.fspath(target))
        if not self.file_path or target == os.path.abspath(self.file_path):
            return True
        self._cancel_annotation_edit_for_navigation()
        self._flush_queued_autosave_for_navigation()
        view = self.annotation_editing.view
        if view is None or not view.dirty:
            return True
        answer = localized_warning(
            self,
            tr('unsaved.navigationTitle'),
            tr(
                'unsaved.navigationPrompt',
                image=os.path.basename(self.file_path),
            ),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            self.save_file()
            current = self.annotation_editing.view
            return current is not None and not current.dirty
        if not self._discard_history_view(view):
            return False
        return True

    def _flush_queued_autosave_for_navigation(self):
        """Complete a safe debounced save before deciding to prompt."""
        view = self.annotation_editing.view
        if (
            view is None
            or not view.dirty
            or not self.auto_saving.isChecked()
            or not self.auto_save_timer.isActive()
            or self.annotation_editing.pending
            or self.annotation_editing.edit_open
            or self.annotation_editing.degraded
            or self.annotation_persistence.has_conflict(view.image_key)
        ):
            return
        self.auto_save_timer.stop()
        self.save_dirty_annotations()

    def open_file(self, _value=False):
        if not self.may_continue():
            return
        path = os.path.dirname(ustr(self.file_path)) if self.file_path else '.'
        formats = ['*.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        filters = tr('dialog.imageAnnotationFilter', patterns=' '.join(
            formats
            + [
                '*%s' % annotation_format.extension
                for annotation_format in AnnotationFormat
            ]
        ))
        filename = QFileDialog.getOpenFileName(
            self,
            tr('dialog.chooseImageOrAnnotation', app=__appname__),
            path,
            filters,
        )
        if filename:
            if isinstance(filename, (tuple, list)):
                filename = filename[0]
            previous_index = self.cur_img_idx
            previous_count = self.img_count
            self.cur_img_idx = 0
            self.img_count = 1
            if not self.load_file(filename):
                self.cur_img_idx = previous_index
                self.img_count = previous_count
                self.update_file_navigation_actions()

    def save_file(self, _value=False):
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self.status(tr('status.finishEdit'))
            return
        if self.default_save_dir is not None and len(ustr(self.default_save_dir)):
            if self.file_path:
                image_file_name = os.path.basename(self.file_path)
                saved_file_name = os.path.splitext(image_file_name)[0]
                saved_path = os.path.join(ustr(self.default_save_dir), saved_file_name)
                self._save_file(saved_path)
        else:
            image_file_dir = os.path.dirname(self.file_path)
            image_file_name = os.path.basename(self.file_path)
            saved_file_name = os.path.splitext(image_file_name)[0]
            saved_path = os.path.join(image_file_dir, saved_file_name)
            self._save_file(saved_path)

    def save_file_as(self, _value=False):
        if (
            self.annotation_editing.pending
            or self.annotation_editing.edit_open
        ):
            self.status(tr('status.finishEdit'))
            return
        assert not self.image.isNull(), "cannot save empty image"
        self._save_file(self.save_file_dialog())

    def save_file_dialog(self, remove_ext=True):
        caption = tr('dialog.chooseFile', app=__appname__)
        filters = tr(
            'dialog.fileFilter', extension=self.annotation_format.extension
        )
        open_dialog_path = self.current_path()
        dlg = QFileDialog(self, caption, open_dialog_path, filters)
        dlg.setDefaultSuffix(self.annotation_format.extension[1:])
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        filename_without_extension = os.path.splitext(self.file_path)[0]
        dlg.selectFile(filename_without_extension)
        dlg.setOption(QFileDialog.DontUseNativeDialog, False)
        if dlg.exec_():
            full_file_path = ustr(dlg.selectedFiles()[0])
            if remove_ext:
                return os.path.splitext(full_file_path)[0]  # Return file path without the extension.
            else:
                return full_file_path
        return ''

    def _save_file(self, annotation_file_path):
        was_degraded = self.annotation_editing.degraded
        if was_degraded and annotation_file_path:
            rescue_path = annotation_file_path
            if not rescue_path.lower().endswith(
                self.annotation_format.extension
            ):
                rescue_path += self.annotation_format.extension
            if os.path.lexists(rescue_path):
                self.error_message(
                    tr('save.rescueTitle'),
                    '<p>%s</p>' % tr('save.rescuePrompt'),
                )
                return
        saved = (
            self.save_labels(annotation_file_path)
            if annotation_file_path
            else None
        )
        if saved:
            self.refresh_candidate_labels()
            if was_degraded:
                self.annotation_editing.clear_degraded(self.file_path)
                self._rebase_current_history(saved.annotation_path)
            self.update_file_list_item_status(self.file_path)
            self._watch_current_annotation_document()
            if saved.removed:
                self.statusBar().showMessage(
                    tr('status.removedEmpty', path=saved.annotation_path)
                )
                self.statusBar().show()
            elif saved.document is not None:
                self.statusBar().showMessage(
                    tr('status.saved', path=saved.annotation_path)
                )
                self.statusBar().show()

    def close_file(self, _value=False):
        if not self.may_continue(target=None):
            return
        self.workbench_session.commit_transition(
            self._workbench_transition_ticket
        )
        self.reset_state(preserve_session=True)
        self.set_clean()
        self.toggle_actions(False)
        self.canvas.setEnabled(False)
        self.actions.saveAs.setEnabled(False)

    def delete_image(self):
        if self.file_path is not None:
            self.delete_file_paths([self.file_path])

    def reset_all(self):
        self.settings.reset()
        self.close()
        QProcess.startDetached(
            sys.executable,
            ['-m', 'labelimg'] + sys.argv[1:],
        )

    def may_continue(self, target=None):
        plan = self.workbench_session.plan_transition(
            target,
            self._transition_facts(),
        )
        requirements = set(plan.requirements)
        if (
            TransitionRequirement.RESOLVE_CROP in requirements
            and not self._resolve_crop_before_leave()
        ):
            return False
        if (
            TransitionRequirement.FINISH_ANNOTATION_EDIT in requirements
        ):
            self._cancel_annotation_edit_for_navigation()
        if (
            TransitionRequirement.RESOLVE_EXTERNAL_CONFLICTS in requirements
            and not self._resolve_conflicts_for_close()
        ):
            return False
        dirty_views = list(self.annotation_editing.dirty_views())
        if not dirty_views:
            return self._authorize_workbench_transition(target)

        dialog = QDialog(self)
        dialog.setWindowTitle(tr('unsaved.title'))
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            tr('unsaved.prompt')
        ))
        table = QTableWidget(len(dirty_views), 2, dialog)
        table.setHorizontalHeaderLabels((
            tr('unsaved.image'),
            tr('unsaved.action'),
        ))
        choices = []
        for row, view in enumerate(dirty_views):
            item = QTableWidgetItem(view.image_key)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, 0, item)
            combo = QComboBox(table)
            combo.addItems((
                tr('common.choose'),
                tr('unsaved.save'),
                tr('unsaved.discard'),
            ))
            table.setCellWidget(row, 1, combo)
            choices.append(combo)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            dialog,
        )
        localize_dialog_buttons(buttons)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        ok_button.setEnabled(False)

        def update_ok():
            ok_button.setEnabled(
                all(combo.currentIndex() > 0 for combo in choices)
            )

        for combo in choices:
            combo.currentIndexChanged.connect(update_ok)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(760, 320)
        if dialog.exec_() != QDialog.Accepted:
            return False

        save_views = [
            view
            for view, combo in zip(dirty_views, choices)
            if combo.currentIndex() == 1
        ]
        if self._save_history_views(save_views) is None:
            return False
        for view, combo in zip(dirty_views, choices):
            if combo.currentIndex() == 2:
                if not self._discard_history_view(view):
                    return False
        self._sync_annotation_history_ui()
        return self._authorize_workbench_transition(target)

    def _transition_facts(self):
        return TransitionFacts(
            crop_active=bool(self._crop_active),
            annotation_edit_open=bool(
                self.annotation_editing.pending
                or self.annotation_editing.edit_open
            ),
            external_conflicts=tuple(
                self.annotation_persistence.conflicts
            ),
            dirty_images=tuple(
                view.image_key
                for view in self.annotation_editing.dirty_views()
            ),
        )

    def _authorize_workbench_transition(self, target):
        facts = self._transition_facts()
        plan = self.workbench_session.plan_transition(target, facts)
        if not plan.ready:
            return False
        self._workbench_transition_ticket = (
            self.workbench_session.authorize_transition(plan, facts)
        )
        return True

    def _save_history_views(self, views):
        views = tuple(views)
        outcome = self.annotation_persistence.save_many(
            (view.image_key for view in views),
            self.annotation_format,
        )
        for receipt in outcome.saved:
            saved = receipt.workspace_save
            if receipt.image_key == self.file_path:
                self.annotation_document = saved.document
            self.update_file_list_item_status(receipt.image_key)
        if not outcome.ok:
            self.error_message(
                tr('conflict.saveFailed'),
                '<p>%s</p>' % outcome.failure.error,
            )
            return None
        return outcome.saved_by_image

    def _discard_history_view(self, view):
        baseline = view.saved_baseline
        if (
            baseline is not None
            and not self.annotation_persistence.baseline_is_current(
                baseline
            )
        ):
            self.annotation_persistence.register_conflict(
                AnnotationStorageConflict(
                    self.annotation_persistence.baseline_mismatches(
                        baseline
                    )
                ),
                view.image_key,
            )
            self.update_file_list_item_status(view.image_key)
            self.error_message(
                tr('conflict.discardFailed'),
                '<p>%s</p>' % tr('conflict.storedChanged'),
            )
            return False
        self.annotation_editing.remove_images((view.image_key,))
        self.annotation_persistence.release(view)
        self.annotation_scene.forget_image(view.image_key)
        if view.image_key == self.file_path:
            self.dirty = False
        self.update_file_list_item_status(view.image_key)
        return True

    def discard_changes_dialog(self):
        yes, no, cancel = QMessageBox.Yes, QMessageBox.No, QMessageBox.Cancel
        return localized_warning(
            self,
            tr('unsaved.attention'),
            tr('unsaved.legacyPrompt'),
            yes | no | cancel,
        )

    def error_message(self, title, message):
        return localized_critical(self, title,
                                    '<p><b>%s</b></p>%s' % (title, message))

    def current_path(self):
        return os.path.dirname(self.file_path) if self.file_path else '.'
