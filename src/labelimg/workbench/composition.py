#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
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
from PyQt5.QtWidgets import QAbstractItemView, QAction, QActionGroup, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QStyle, QStyleOptionViewItem, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget, QWidgetAction

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
    information as localized_information,
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
    FileListControlBar,
    FileListItemDelegate,
    FileListWidget,
    compare_relative_image_paths,
    validate_base_name,
    validate_rename_mapping,
)
from labelimg.files.application.operations import (
    FileOperationError,
    SystemTrashAdapter,
)
from labelimg.files import (
    FileOperationBlocked,
    FileOperationTransaction,
    FileRecoveryBlocked,
    RecoveryOperation,
)
from labelimg.annotations.ui.label_group_list import LabelGroupListWidget
from labelimg.image_tools.application.session import (
    AdjustmentChange,
    CropChange,
    GeometryTransformChange,
    ImageProcessingProjectionKind,
    ImageProcessingSession,
    PreparedPixelChange,
)
from labelimg.image_tools import ImageProcessingTransaction
from labelimg.workbench.session import WorkbenchSession
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
from labelimg.image_tools.ui.controller import ImageToolsActionsMixin
from labelimg.workbench.recovery_ui import RecoveryActionsMixin

__appname__ = APP_NAME
















class WorkbenchComposer:
    """Explicitly assemble one concrete window without joining its MRO."""

    @staticmethod
    def compose(self, default_filename=None, default_prefdef_class_file=None, default_save_dir=None):
        self.workbench_session = WorkbenchSession(default_filename)
        self.setWindowTitle(__appname__)

        # Load setting in the main thread
        self.settings = Settings()
        self.settings.load()
        settings = self.settings

        set_language(settings.get(SETTING_LANGUAGE, system_language()))

        self.os_name = platform.system()

        get_str = tr

        # Save as Pascal voc xml
        self.default_save_dir = default_save_dir
        self.annotation_format = settings.get(
            SETTING_LABEL_FILE_FORMAT,
            AnnotationFormat.PASCAL_VOC,
        )

        # For loading all image under a directory
        self.m_img_list = []
        self.dir_name = None
        self.label_hist = []
        self.last_open_dir = None
        self.cur_img_idx = 0
        self.img_count = 1

        # Whether we need to save or not.
        self.dirty = False
        self._autosave_request = False
        self.system_trash = SystemTrashAdapter()

        self.screencast = "https://youtu.be/p0nR2YsCY_U"

        # Load predefined classes to the list
        self.load_predefined_classes(default_prefdef_class_file)
        self.annotation_workspace = AnnotationWorkspace(
            save_dir=default_save_dir,
        )
        self.candidate_labels = list(
            self.annotation_workspace.candidate_labels
        )

        # Main widgets and related state.
        self.candidate_label_dialog = CandidateLabelDialog(
            parent=self,
            list_item=self.candidate_labels,
        )

        self.annotation_clipboard = []
        self.prev_label_text = ''

        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(6, 4, 6, 6)
        list_layout.setSpacing(6)

        # Create a widget for using default label
        self.use_default_label_checkbox = QCheckBox(get_str('useDefaultLabel'))
        self.use_default_label_checkbox.setChecked(False)
        self.default_label_text_line = QLineEdit()
        use_default_label_qhbox_layout = QHBoxLayout()
        use_default_label_qhbox_layout.setContentsMargins(0, 0, 0, 0)
        use_default_label_qhbox_layout.setSpacing(6)
        use_default_label_qhbox_layout.addWidget(self.use_default_label_checkbox)
        use_default_label_qhbox_layout.addWidget(self.default_label_text_line)
        self.default_label_row = QWidget()
        self.default_label_row.setLayout(use_default_label_qhbox_layout)

        # Create a widget for edit and diffc button
        self.diffc_button = QCheckBox(get_str('useDifficult'))
        self.diffc_button.setChecked(False)
        self.diffc_button.setEnabled(False)
        self.diffc_button.stateChanged.connect(self.button_state)
        self.edit_button = QToolButton()
        self.edit_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.copy_button = QToolButton()
        self.copy_button.setObjectName('annotationCopyButton')
        self.delete_button = QToolButton()
        self.delete_button.setObjectName('annotationDeleteButton')
        self.visibility_button = QToolButton()
        self.visibility_button.setObjectName('annotationVisibilityButton')
        self.annotation_header = QWidget()
        annotation_header_layout = QHBoxLayout(self.annotation_header)
        annotation_header_layout.setContentsMargins(0, 0, 0, 0)
        annotation_header_layout.setSpacing(4)
        for button in (
            self.edit_button,
            self.copy_button,
            self.delete_button,
            self.visibility_button,
        ):
            button.setAutoRaise(True)
            button.setIconSize(QSize(20, 20))
            annotation_header_layout.addWidget(button)
        annotation_header_layout.addStretch(1)

        # Add some of widgets to list_layout
        list_layout.addWidget(self.annotation_header)
        list_layout.addWidget(self.diffc_button)
        list_layout.addWidget(self.default_label_row)

        self.label_filter = QLineEdit()
        self.label_filter.setPlaceholderText(tr('labels.filter'))
        self.label_filter.setClearButtonEnabled(True)
        list_layout.addWidget(self.label_filter)

        self.label_summary_label = QLabel()
        self.label_summary_label.setContentsMargins(6, 1, 6, 2)
        self.label_summary_label.setStyleSheet('color: palette(mid);')
        list_layout.addWidget(self.label_summary_label)

        self.label_list = LabelGroupListWidget()
        label_list_container = QWidget()
        label_list_container.setLayout(list_layout)
        self.label_filter.textChanged.connect(
            self.label_list.set_filter_text
        )
        self.label_list.summaryChanged.connect(
            self.label_summary_label.setText
        )
        self.label_list.selectionRequested.connect(
            self.label_selection_requested
        )
        self.label_list.visibilityRequested.connect(
            self.label_visibility_requested
        )
        self.label_list.groupEditRequested.connect(
            self.edit_label_group
        )
        self.label_list.instanceEditRequested.connect(
            self.edit_shape_label
        )
        self.label_list.contextMenuRequested.connect(
            self.pop_label_group_menu
        )
        self.label_summary_label.setText(
            self.label_list.summary_text()
        )
        list_layout.addWidget(self.label_list)



        self.dock = QDockWidget(get_str('boxLabelText'), self)
        self.dock.setObjectName(get_str('labels'))
        self.dock.setWidget(label_list_container)

        self.file_list_widget = FileListWidget()
        self.file_list_widget.setItemDelegate(
            FileListItemDelegate(self.file_list_widget)
        )
        self.file_list_widget.itemOpenRequested.connect(
            self.file_item_double_clicked
        )
        self.file_list_widget.itemSelectionChanged.connect(
            self.update_file_selection_count
        )
        self.file_list_widget.openRequested.connect(
            self.open_selected_file
        )
        self.file_list_widget.renameRequested.connect(
            self.rename_selected_files
        )
        self.file_list_widget.deleteRequested.connect(
            self.delete_selected_files
        )
        self.file_list_widget.filterRequested.connect(
            self.show_file_list_filter
        )
        self.file_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list_widget.customContextMenuRequested.connect(
            self.pop_file_list_menu
        )
        file_list_layout = QVBoxLayout()
        file_list_layout.setContentsMargins(6, 4, 6, 6)
        file_list_layout.setSpacing(6)
        self.annotation_directory_bar = QWidget()
        annotation_directory_layout = QHBoxLayout(
            self.annotation_directory_bar
        )
        annotation_directory_layout.setContentsMargins(0, 0, 0, 0)
        annotation_directory_layout.setSpacing(4)
        self.annotation_directory_label = QLabel()
        self.annotation_directory_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        self.annotation_directory_label.setSizePolicy(
            QSizePolicy.Ignored,
            QSizePolicy.Preferred,
        )
        self.annotation_directory_button = QToolButton()
        self.annotation_directory_button.setAutoRaise(True)
        self.annotation_directory_button.setToolButtonStyle(
            Qt.ToolButtonIconOnly
        )
        annotation_directory_layout.addWidget(
            self.annotation_directory_label,
            1,
        )
        annotation_directory_layout.addWidget(
            self.annotation_directory_button,
        )
        file_list_layout.addWidget(self.annotation_directory_bar)
        self.file_list_controls = FileListControlBar(
            settings.get(SETTING_FILE_LIST_SORT_KEY, 'name'),
            settings.get(SETTING_FILE_LIST_SORT_DESCENDING, False),
        )
        self.file_list_controls.viewChanged.connect(
            self.apply_file_list_view
        )
        file_list_layout.addWidget(self.file_list_controls)
        self.file_list_stack = QStackedWidget()
        self.file_list_stack.addWidget(self.file_list_widget)
        self.file_list_empty_state = QWidget()
        empty_layout = QVBoxLayout(self.file_list_empty_state)
        empty_layout.addStretch(1)
        self.file_list_empty_label = QLabel(tr('files.noMatch'))
        self.file_list_empty_label.setAlignment(Qt.AlignCenter)
        self.file_list_empty_label.setStyleSheet('color: palette(mid);')
        empty_layout.addWidget(self.file_list_empty_label)
        self.file_list_clear_filter_button = QPushButton(tr('files.clearFilter'))
        self.file_list_clear_filter_button.setSizePolicy(
            QSizePolicy.Fixed,
            QSizePolicy.Fixed,
        )
        self.file_list_clear_filter_button.clicked.connect(
            self.file_list_controls.clear_filters
        )
        empty_layout.addWidget(
            self.file_list_clear_filter_button,
            0,
            Qt.AlignHCenter,
        )
        empty_layout.addStretch(1)
        self.file_list_stack.addWidget(self.file_list_empty_state)
        self.file_list_stack.setCurrentWidget(self.file_list_widget)
        file_list_layout.addWidget(self.file_list_stack)
        self.file_selection_count_label = QLabel()
        self.file_selection_count_label.setContentsMargins(6, 2, 6, 2)
        self.file_selection_count_label.setStyleSheet(
            "color: palette(mid);"
        )
        file_list_layout.addWidget(self.file_selection_count_label)
        self.update_file_selection_count()
        file_list_container = QWidget()
        file_list_container.setLayout(file_list_layout)
        self.file_dock = QDockWidget(get_str('fileList'), self)
        self.file_dock.setObjectName(get_str('files'))
        self.file_dock.setWidget(file_list_container)

        from labelimg.image_tools.domain.quality import (
            ImageQualityCache,
            ImageQualityScanner,
        )
        from labelimg.image_tools.ui.quality_panel import ImageQualityPanel
        self.image_quality_scanner = ImageQualityScanner()
        self.image_quality_cache = ImageQualityCache(
            os.path.join(
                os.path.dirname(self.settings.path),
                'image-quality-cache.json',
            )
        )
        self.image_quality_results = {}
        self._image_quality_last_request = None
        self._image_quality_thread = None
        self._image_quality_worker = None
        self._image_quality_progress = None
        self.image_quality_panel = ImageQualityPanel()
        self.image_quality_panel.refreshRequested.connect(
            self.refresh_image_quality
        )
        self.image_quality_panel.clearRequested.connect(
            self.clear_image_quality_results
        )
        self.image_quality_panel.openRequested.connect(
            self.open_file_list_path
        )
        self.image_quality_dock = QDockWidget(tr('quality.panelTitle'), self)
        self.image_quality_dock.setObjectName('imageQuality')
        self.image_quality_dock.setWidget(self.image_quality_panel)

        self.zoom_widget = ZoomControl()
        self.color_dialog = ColorDialog(parent=self)

        self.canvas = Canvas(parent=self)
        self.canvas.installEventFilter(self)
        self.canvas.zoomRequest.connect(self.zoom_request)
        self.canvas.set_drawing_shape_to_square(settings.get(SETTING_DRAW_SQUARE, False))

        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(True)
        self.scroll_bars = {
            Qt.Vertical: scroll.verticalScrollBar(),
            Qt.Horizontal: scroll.horizontalScrollBar()
        }
        self.scroll_area = scroll
        self.canvas.scrollRequest.connect(self.scroll_request)
        self.canvas.panRequest.connect(self.pan_request)
        self.canvas.statusRequest.connect(self.status)

        self.annotation_scene = CanvasAnnotationScene(
            self.canvas,
            on_project=self._project_annotation_history,
        )
        self.annotation_editing = AnnotationEditingController(
            self.annotation_scene.capture,
            self.annotation_scene.project,
            on_degraded=self._annotation_projection_degraded,
        )
        self.annotation_persistence = AnnotationSaveCoordinator(
            self.annotation_workspace,
            self.annotation_editing,
            image_data_for=self._annotation_image_data,
            image_keys=lambda: tuple(self.m_img_list),
        )
        self.review_state_transaction = ReviewStateTransaction(
            self.annotation_workspace,
            self.annotation_editing,
            self.annotation_persistence,
            image_data_for=self._annotation_image_data,
        )
        self.file_operations = FileOperationTransaction(
            self.annotation_workspace,
            self.annotation_editing,
            self.annotation_scene,
            self.annotation_persistence,
            self.review_state_transaction,
            self.system_trash,
        )
        self.image_processing_transaction = ImageProcessingTransaction(
            self.annotation_editing,
            self.annotation_scene,
            self.annotation_persistence,
            self.system_trash,
        )
        self.image_processing = ImageProcessingSession(
            self.annotation_workspace,
            self.annotation_editing,
            self.annotation_persistence,
            self.image_processing_transaction,
            self._project_image_processing,
            self.annotation_document_for_path,
        )
        self._image_processing_projection_blocked = False
        self.canvas.newShape.connect(self.new_shape)
        self.canvas.shapeMoved.connect(self._legacy_shape_moved)
        self.canvas.selectionChanged.connect(self.shape_selection_changed)
        self.canvas.hoverShapeChanged.connect(
            self.canvas_hover_shape_changed
        )
        self.label_list.hoverRequested.connect(
            self.label_hover_changed
        )
        self.canvas.drawingPolygon.connect(self.toggle_drawing_sensitive)
        self.canvas.drawingPolygon.connect(
            self._annotation_drawing_state_changed
        )
        self.canvas.annotationGestureStarted.connect(
            self._begin_annotation_gesture
        )
        self.canvas.annotationGestureFinished.connect(
            self._finish_annotation_gesture
        )
        self.canvas.annotationGestureCanceled.connect(
            self._cancel_annotation_gesture
        )

        self.setCentralWidget(scroll)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.file_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.image_quality_dock)
        self.image_quality_dock.hide()
        self.file_dock.setFeatures(QDockWidget.DockWidgetFloatable)

        self.dock_features = QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetFloatable
        self.dock.setFeatures(self.dock.features() ^ self.dock_features)

        from labelimg.image_tools.ui.crop_overlay import (
            CropControlBar,
            CropOverlay,
        )
        self.crop_overlay = CropOverlay(self.canvas)
        self.crop_controls = CropControlBar(
            self.crop_overlay,
            self.scroll_area.viewport(),
        )
        self.crop_overlay.applyRequested.connect(self.apply_crop)
        self.crop_overlay.cancelRequested.connect(self.cancel_crop)
        self._crop_active = False
        self._crop_action_states = {}
        self._crop_previous_canvas_mode = None

        # Actions
        action = partial(new_action, self)
        quit = action(get_str('quit'), self.close,
                      'Ctrl+Q', 'quit', get_str('quitApp'))

        open = action(get_str('openFile'), self.open_file,
                      'Ctrl+O', 'open-file', get_str('openFileDetail'))

        open_dir = action(get_str('openDir'), self.open_dir_dialog,
                          'Ctrl+Shift+O', 'open-image-directory',
                          get_str('openDirDetail'))

        change_save_dir = action(get_str('changeSaveDir'), self.change_save_dir_dialog,
                                 None, 'choose-annotation-directory',
                                 get_str('changeSavedAnnotationDir'))
        self.annotation_directory_button.setDefaultAction(change_save_dir)

        open_annotation = action(get_str('openAnnotation'), self.open_annotation_dialog,
                                 None, 'replace-annotation',
                                 get_str('openAnnotationDetail'))
        open_file_menu = QMenu(self)
        open_file_menu.addAction(open)
        open_dir._toolbar_menu = open_file_menu
        copy_annotations = action(tr('action.copyLabels'), self.copy_current_bounding_boxes, 'Ctrl+C',
                                  'copy-annotations', tr('action.copyLabelsTip'),
                                  enabled=False)
        paste_annotations = action(tr('action.pasteLabels'), self.paste_copied_bounding_boxes, 'Ctrl+V',
                                   'paste', tr('action.pasteLabelsTip'))
        copy_prev_bounding = action(get_str('copyPrevBounding'), self.copy_previous_bounding_boxes,
                                    None, 'copy-previous-annotations', get_str('copyPrevBounding'))

        open_next_image = action(get_str('nextImg'), self.open_next_image,
                                 'd', 'next', get_str('nextImgDetail'),
                                 enabled=False)

        open_prev_image = action(get_str('prevImg'), self.open_prev_image,
                                 'a', 'prev', get_str('prevImgDetail'),
                                 enabled=False)

        verify = action(get_str('verifyImg'), self.verify_image,
                        'space', 'verify', get_str('verifyImgDetail'))
        question = action(
            tr('action.questionImage'),
            self.question_image,
            'Ctrl+Space',
            'review-questioned',
            tr('action.questionImageTip'),
        )
        # Keep review shortcuts active even though review state is presented
        # by the explicit top segmented control rather than a toolbar action.
        self.addAction(verify)
        self.addAction(question)

        save = action(get_str('save'), self.save_file,
                      'Ctrl+S', 'save', get_str('saveDetail'), enabled=False)

        def get_format_meta(format):
            """
            returns a tuple containing (title, icon_name) of the selected format
            """
            if format == AnnotationFormat.PASCAL_VOC:
                return '&PascalVOC', 'format_voc'
            elif format == AnnotationFormat.YOLO:
                return '&YOLO', 'format_yolo'
            elif format == AnnotationFormat.CREATE_ML:
                return '&CreateML', 'format_createml'

        save_format = action(get_format_meta(self.annotation_format)[0],
                             self.change_format, None,
                             get_format_meta(self.annotation_format)[1],
                             get_str('changeSaveFormat'), enabled=True)

        save_as = action(get_str('saveAs'), self.save_file_as,
                         'Ctrl+Shift+S', 'save-as', get_str('saveAsDetail'), enabled=False)

        close = action(get_str('closeCur'), self.close_file, 'Ctrl+W', 'close', get_str('closeCurDetail'))

        delete_image = action(get_str('deleteImg'), self.delete_image, 'Ctrl+Delete', 'delete-image', get_str('deleteImgDetail'))
        recent_file_operations = QAction(
            tr('action.recentOperations'),
            self,
        )
        recent_file_operations.setIcon(new_icon('recent-operations'))
        recent_file_operations.triggered.connect(
            self.open_file_recovery_center
        )
        remove_colored_frames = action(
            tr('imageTools.action.removeFrames'),
            self.open_remove_colored_frames,
            icon='remove-frames',
            tip=tr('imageTools.action.removeFramesTip'),
            enabled=False,
        )
        crop_image = action(
            tr('crop.action'),
            self.enter_crop_mode,
            'C',
            'crop',
            tr('crop.actionTip'),
            enabled=False,
            checkable=True,
        )
        crop_image.setShortcutContext(Qt.WidgetShortcut)
        self.canvas.addAction(crop_image)
        rotate_clockwise = action(
            tr('geometry.rotateClockwise'),
            partial(self.quick_transform_current_image, 'rotate-clockwise'),
            icon='rotate-clockwise',
            tip=tr('geometry.rotateClockwiseTip'),
            enabled=False,
        )
        rotate_counterclockwise = action(
            tr('geometry.rotateCounterclockwise'),
            partial(
                self.quick_transform_current_image,
                'rotate-counterclockwise',
            ),
            icon='rotate-counterclockwise',
            tip=tr('geometry.rotateCounterclockwiseTip'),
            enabled=False,
        )
        rotate_180 = action(
            tr('geometry.rotate180'),
            partial(self.quick_transform_current_image, 'rotate-180'),
            icon='rotate-180',
            tip=tr('geometry.rotate180Tip'),
            enabled=False,
        )
        flip_horizontal = action(
            tr('geometry.flipHorizontal'),
            partial(self.quick_transform_current_image, 'flip-horizontal'),
            icon='flip-horizontal',
            tip=tr('geometry.flipHorizontalTip'),
            enabled=False,
        )
        flip_vertical = action(
            tr('geometry.flipVertical'),
            partial(self.quick_transform_current_image, 'flip-vertical'),
            icon='flip-vertical',
            tip=tr('geometry.flipVerticalTip'),
            enabled=False,
        )
        transform_image = action(
            tr('geometry.transform'),
            self.open_transform_image,
            icon='geometry-transform',
            tip=tr('geometry.transformTip'),
            enabled=False,
        )
        adjust_image = action(
            tr('adjustment.action'),
            self.open_adjust_image,
            icon='adjust-image',
            tip=tr('adjustment.actionTip'),
            enabled=False,
        )
        check_image_quality = action(
            tr('quality.action'),
            self.open_image_quality_check,
            icon='image-quality',
            tip=tr('quality.actionTip'),
            enabled=False,
        )
        rotate_toolbar_menu = QMenu(self)
        add_actions(
            rotate_toolbar_menu,
            (rotate_counterclockwise, rotate_180),
        )
        rotate_clockwise._toolbar_menu = rotate_toolbar_menu
        flip_toolbar_menu = QMenu(self)
        add_actions(flip_toolbar_menu, (flip_vertical,))
        flip_horizontal._toolbar_menu = flip_toolbar_menu
        undo_image_processing = action(
            tr('imageTools.action.undoCommitted'),
            self.undo_last_image_processing,
            icon='undo-image-processing',
            tip=tr('imageTools.action.undoCommittedTip'),
            enabled=False,
        )

        reset_all = action(get_str('resetAll'), self.reset_all, None, 'resetall', get_str('resetAllDetail'))

        color1 = action(get_str('boxLineColor'), self.choose_color1,
                        'Ctrl+L', 'color_line', get_str('boxLineColorDetail'))

        select_tool = action(
            tr('tool.select'), self.set_edit_mode,
            ('V', 'Ctrl+J'), 'select-edit', tr('tool.selectTip'),
            enabled=False, checkable=True,
        )
        pan_tool = action(
            tr('tool.pan'), self.set_pan_mode,
            'H', 'pan', tr('tool.panTip'),
            enabled=False, checkable=True,
        )
        create = action(get_str('crtBox'), self.create_shape,
                        'w', 'new', get_str('crtBoxDetail'), enabled=False,
                        checkable=True)
        delete = action(get_str('delBox'), self.delete_selected_shape,
                        'Delete', 'delete-boxes', get_str('delBoxDetail'), enabled=False)
        copy = action(get_str('dupBox'), self.copy_selected_shape,
                      'Ctrl+D', 'duplicate-boxes', get_str('dupBoxDetail'),
                      enabled=False)

        hide_all = action(get_str('hideAllBox'), partial(self.toggle_polygons, False),
                          'Ctrl+H', 'hide-all', get_str('hideAllBoxDetail'),
                          enabled=False)
        show_all = action(get_str('showAllBox'), partial(self.toggle_polygons, True),
                          'Ctrl+A', 'hide', get_str('showAllBoxDetail'),
                          enabled=False)
        toggle_visibility = action(
            get_str('hideAllBox'), self.toggle_all_annotations,
            None, 'hide', get_str('hideAllBoxDetail'),
            enabled=False, checkable=True,
        )
        toggle_visibility.setChecked(True)

        help_default = action(get_str('tutorialDefault'), self.show_default_tutorial_dialog, None, 'tutorial', get_str('tutorialDetail'))
        show_info = action(get_str('info'), self.show_info_dialog, None, 'about', get_str('info'))
        show_shortcut = action(get_str('shortcut'), self.show_shortcuts_dialog, None, 'keyboard-shortcuts', get_str('shortcut'))

        zoom = QWidgetAction(self)
        zoom.setDefaultWidget(self.zoom_widget)
        self.zoom_widget.setWhatsThis(
            tr(
                'zoom.help',
                keyboard=format_shortcut("Ctrl+[-+]"),
                wheel=format_shortcut("Ctrl+Wheel"),
            )
        )
        self.zoom_widget.setEnabled(False)

        zoom_in = action(get_str('zoomin'), partial(self.add_zoom, 10),
                         'Ctrl++', 'zoom-in', get_str('zoominDetail'), enabled=False)
        zoom_out = action(get_str('zoomout'), partial(self.add_zoom, -10),
                          'Ctrl+-', 'zoom-out', get_str('zoomoutDetail'), enabled=False)
        zoom_org = action(get_str('originalsize'), partial(self.set_zoom, 100),
                          'Ctrl+=', 'zoom', get_str('originalsizeDetail'), enabled=False)
        fit_window = action(get_str('fitWin'), self.set_fit_window,
                            'Ctrl+F', 'fit-window', get_str('fitWinDetail'),
                            checkable=True, enabled=False)
        fit_width = action(get_str('fitWidth'), self.set_fit_width,
                           'Ctrl+Shift+F', 'fit-width', get_str('fitWidthDetail'),
                           checkable=True, enabled=False)
        # Group zoom controls into a list for easier toggling.
        zoom_actions = (self.zoom_widget, zoom_in, zoom_out,
                        zoom_org, fit_window, fit_width)
        self.zoom_mode = self.MANUAL_ZOOM
        self.scalers = {
            self.FIT_WINDOW: self.scale_fit_window,
            self.FIT_WIDTH: self.scale_fit_width,
            # Set to one to scale to 100% when loading files.
            self.MANUAL_ZOOM: lambda: 1,
        }

        undo_annotation = QAction(tr('action.undo'), self)
        undo_annotation.setIcon(new_icon('undo'))
        undo_annotation.setEnabled(False)
        undo_annotation.triggered.connect(self.undo_annotation)
        redo_annotation = QAction(
            tr('action.redo'),
            self,
        )
        redo_annotation.setIcon(new_icon('redo'))
        redo_annotation.setEnabled(False)
        redo_annotation.triggered.connect(self.redo_annotation)

        edit = action(get_str('editLabel'), self.edit_label,
                      'Ctrl+E', 'edit-label', get_str('editLabelDetail'),
                      enabled=False)
        self.edit_button.setDefaultAction(edit)
        self.copy_button.setDefaultAction(copy)
        self.delete_button.setDefaultAction(delete)
        self.visibility_button.setDefaultAction(toggle_visibility)

        shape_line_color = action(get_str('shapeLineColor'), self.choose_shape_line_color,
                                  icon='color_line', tip=get_str('shapeLineColorDetail'),
                                  enabled=False)
        shape_fill_color = action(get_str('shapeFillColor'), self.choose_shape_fill_color,
                                  icon='color', tip=get_str('shapeFillColorDetail'),
                                  enabled=False)

        labels = self.dock.toggleViewAction()
        labels.setIcon(new_icon('annotation-panel'))
        labels.setText(get_str('showHide'))
        labels.setShortcut('Ctrl+Shift+L')

        # The grouped annotation list builds scope-explicit context menus
        # from the semantic target under the pointer.
        label_menu = QMenu()

        # Draw squares/rectangles
        self.draw_squares_option = QAction(get_str('drawSquares'), self)
        self.draw_squares_option.setIcon(new_icon('draw-squares'))
        self.draw_squares_option.setShortcut('Ctrl+Shift+R')
        self.draw_squares_option.setCheckable(True)
        self.draw_squares_option.setChecked(settings.get(SETTING_DRAW_SQUARE, False))
        self.draw_squares_option.triggered.connect(self.toggle_draw_square)

        # Store actions for further handling.
        self.actions = SimpleNamespace(save=save, save_format=save_format, saveAs=save_as, open=open, close=close, quit=quit, resetAll=reset_all, deleteImg=delete_image,
                              openDir=open_dir, changeSaveDir=change_save_dir,
                              replaceAnnotation=open_annotation,
                              verify=verify, question=question,
                              openNext=open_next_image, openPrev=open_prev_image,
                              undoAnnotation=undo_annotation,
                              redoAnnotation=redo_annotation,
                              recentFileOperations=recent_file_operations,
                              removeColoredFrames=remove_colored_frames,
                              cropImage=crop_image,
                              rotateClockwise=rotate_clockwise,
                              rotateCounterclockwise=rotate_counterclockwise,
                              rotate180=rotate_180,
                              flipHorizontal=flip_horizontal,
                              flipVertical=flip_vertical,
                              transformImage=transform_image,
                              adjustImage=adjust_image,
                              checkImageQuality=check_image_quality,
                              undoImageProcessing=undo_image_processing,
                              lineColor=color1, selectTool=select_tool,
                              panTool=pan_tool, create=create, delete=delete,
                              edit=edit, copy=copy,
                               copyAnnotations=copy_annotations, pasteAnnotations=paste_annotations,
                               copyPrevBounding=copy_prev_bounding,
                              shapeLineColor=shape_line_color, shapeFillColor=shape_fill_color,
                              hideAll=hide_all, showAll=show_all,
                               toggleVisibility=toggle_visibility,
                               labels=labels,
                               helpDefault=help_default,
                               showInfo=show_info,
                               showShortcut=show_shortcut,
                               zoom=zoom, zoomIn=zoom_in, zoomOut=zoom_out, zoomOrg=zoom_org,
                              fitWindow=fit_window, fitWidth=fit_width,
                              zoomActions=zoom_actions,
                              fileMenuActions=(
                                  open, open_dir, save, save_as, close, quit),
                              editMenu=(undo_annotation, redo_annotation, None,
                                        edit, copy_annotations, paste_annotations,
                                        copy_prev_bounding, copy, delete,
                                        None, color1, self.draw_squares_option),
                              canvasContext=(create, edit, copy, delete),
                               onLoadActive=(
                                   close, select_tool, pan_tool, create,
                                   remove_colored_frames, crop_image,
                                   rotate_clockwise, rotate_counterclockwise,
                                   rotate_180, flip_horizontal, flip_vertical,
                                   transform_image, adjust_image,
                                   check_image_quality),
                              onShapesPresent=(save_as, hide_all, show_all))

        self.menus = SimpleNamespace(
            file=self.menu(get_str('menu_file')),
            edit=self.menu(get_str('menu_edit')),
            image=self.menu(tr('menu_image')),
            view=self.menu(get_str('menu_view')),
            settings=self.menu(tr('menu_settings')),
            help=self.menu(get_str('menu_help')),
            recentFiles=QMenu(get_str('menu_openRecent')),
            labelList=label_menu)
        self.menus.annotationDirectory = QMenu(
            tr('annotationDirectory.menu'),
            self,
        )
        self.menus.recentFiles.setIcon(new_icon('open-recent'))
        self.menus.annotationDirectory.setIcon(new_icon('annotation-directory'))
        annotation_directory_current = QAction(
            tr('annotationDirectory.currentImage'),
            self,
        )
        annotation_directory_current.setIcon(new_icon('annotation-current'))
        annotation_directory_current.setEnabled(False)
        use_image_directory = action(
            tr('annotationDirectory.useImage'),
            self.use_image_directory_for_annotations,
            icon='use-image-directory',
        )
        add_actions(
            self.menus.annotationDirectory,
            (
                annotation_directory_current,
                None,
                change_save_dir,
                use_image_directory,
            ),
        )
        self.actions.annotationDirectoryCurrent = annotation_directory_current
        self.actions.useImageDirectory = use_image_directory
        self.menus.geometry = QMenu(tr('geometry.menu'), self)
        self.menus.geometry.setIcon(new_icon('rotate-flip'))
        add_actions(
            self.menus.geometry,
            (
                rotate_clockwise,
                rotate_counterclockwise,
                rotate_180,
                None,
                flip_horizontal,
                flip_vertical,
            ),
        )
        self.menus.specializedRepair = QMenu(
            tr('specializedRepair.menu'), self
        )
        self.menus.specializedRepair.setIcon(new_icon('specialized-repair'))
        add_actions(
            self.menus.specializedRepair,
            (remove_colored_frames,),
        )

        self.menus.language = QMenu(tr('language.menu'), self)
        self.menus.language.setIcon(new_icon('language'))
        self.language_action_group = QActionGroup(self.menus.language)
        self.language_action_group.setExclusive(True)
        self.language_actions = {}
        for language in (SIMPLIFIED_CHINESE, ENGLISH):
            language_action = self.menus.language.addAction(
                LANGUAGE_NAMES[language]
            )
            language_action.setIcon(new_icon(
                'language-chinese'
                if language == SIMPLIFIED_CHINESE
                else 'language-english'
            ))
            language_action.setCheckable(True)
            language_action.setData(language)
            language_action.setChecked(current_language() == language)
            language_action.triggered.connect(
                lambda checked=False, value=language: self.change_language(value)
            )
            self.language_action_group.addAction(language_action)
            self.language_actions[language] = language_action

        # Auto saving: persist annotation changes shortly after they occur.
        self.auto_saving = QAction(get_str('autoSaveMode'), self)
        self.auto_saving.setIcon(new_icon('auto-save'))
        self.auto_saving.setCheckable(True)
        self.auto_saving.setChecked(settings.get(SETTING_AUTO_SAVE, False))
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.setInterval(200)
        self.auto_save_timer.timeout.connect(self.save_dirty_annotations)
        self._initialize_annotation_live_sync()
        # Sync single class mode from PR#106
        self.single_class_mode = QAction(get_str('singleClsMode'), self)
        self.single_class_mode.setIcon(new_icon('single-class'))
        self.single_class_mode.setCheckable(True)
        self.single_class_mode.setChecked(settings.get(SETTING_SINGLE_CLASS, False))
        self.lastLabel = None
        # Add option to enable/disable labels being displayed at the top of bounding boxes
        self.display_label_option = QAction(get_str('displayLabel'), self)
        self.display_label_option.setIcon(new_icon('show-box-labels'))
        self.display_label_option.setShortcut("Ctrl+Shift+P")
        self.display_label_option.setCheckable(True)
        self.display_label_option.setChecked(settings.get(SETTING_PAINT_LABEL, False))
        self.display_label_option.triggered.connect(self.toggle_paint_labels_option)

        add_actions(self.menus.file,
                    (open_dir, open, self.menus.recentFiles, None,
                     self.menus.annotationDirectory, None,
                     open_annotation, save, save_as, save_format, close, None,
                     delete_image, recent_file_operations, None, quit))
        add_actions(self.menus.image, (
            crop_image,
            self.menus.geometry,
            transform_image,
            None,
            adjust_image,
            None,
            check_image_quality,
            None,
            self.menus.specializedRepair,
            None,
            undo_image_processing,
        ))
        add_actions(self.menus.settings, (
            self.menus.language,
            None,
            self.auto_saving,
            self.single_class_mode,
            None,
            reset_all,
        ))
        add_actions(
            self.menus.help,
            (help_default, show_shortcut, None, show_info),
        )
        add_actions(self.menus.view, (
            self.display_label_option,
            labels, None,
            hide_all, show_all, None,
            zoom_in, zoom_out, zoom_org, None,
            fit_window, fit_width))

        self.menus.file.aboutToShow.connect(self.update_file_menu)
        self.menus.image.aboutToShow.connect(self.update_image_menu)
        self._history_shortcuts = AnnotationHistoryShortcutFilter(
            self,
            self.undo_annotation,
            self.redo_annotation,
            self.file_list_widget,
            scoped_history_active=lambda: self._crop_active,
        )
        QApplication.instance().installEventFilter(
            self._history_shortcuts.qobject
        )

        # Custom context menu for the canvas widget:
        add_actions(self.canvas.menus[0], self.actions.canvasContext)
        self.copy_here_action = action(
            tr('action.copyHere'), self.copy_shape
        )
        self.move_here_action = action(
            tr('action.moveHere'), self.move_shape
        )
        add_actions(self.canvas.menus[1], (
            self.copy_here_action,
            self.move_here_action,
        ))

        self.review_control = ReviewControl(self)
        self.review_control.setEnabled(False)
        self.review_control.stateRequested.connect(
            self.set_current_review_state
        )
        self.format_selector = FormatSelector(
            self.annotation_format, self
        )
        self.format_selector.formatRequested.connect(
            self.set_annotation_format
        )
        self.top_commands = TopCommandBar(
            open_dir,
            open_prev_image,
            open_next_image,
            self.review_control,
            rotate_clockwise,
            flip_horizontal,
            self.format_selector,
            self.auto_saving,
            save,
            self,
        )
        self.addToolBar(Qt.TopToolBarArea, self.top_commands)

        self.tools = CanvasToolRail(
            select_tool, create, pan_tool, crop_image, self
        )
        self.tools.setWindowTitle(tr('toolbar.canvasTools'))
        self.addToolBar(Qt.LeftToolBarArea, self.tools)
        add_actions(
            self.menus.edit,
            (create,) + self.actions.editMenu,
        )
        self.zoom_widget.set_zoom_actions(
            zoom_org, fit_window, fit_width
        )

        self._i18n_action_specs = {
            quit: ('quit', 'quitApp'),
            open: ('openFile', 'openFileDetail'),
            open_dir: ('openDir', 'openDirDetail'),
            change_save_dir: ('changeSaveDir', 'changeSavedAnnotationDir'),
            open_annotation: ('openAnnotation', 'openAnnotationDetail'),
            use_image_directory: ('annotationDirectory.useImage', None),
            copy_annotations: ('action.copyLabels', 'action.copyLabelsTip'),
            paste_annotations: ('action.pasteLabels', 'action.pasteLabelsTip'),
            copy_prev_bounding: ('copyPrevBounding', 'copyPrevBounding'),
            open_next_image: ('nextImg', 'nextImgDetail'),
            open_prev_image: ('prevImg', 'prevImgDetail'),
            verify: ('verifyImg', 'verifyImgDetail'),
            question: ('action.questionImage', 'action.questionImageTip'),
            save: ('save', 'saveDetail'),
            save_format: (None, 'changeSaveFormat'),
            save_as: ('saveAs', 'saveAsDetail'),
            close: ('closeCur', 'closeCurDetail'),
            delete_image: ('deleteImg', 'deleteImgDetail'),
            recent_file_operations: ('action.recentOperations', None),
            remove_colored_frames: (
                'imageTools.action.removeFrames',
                'imageTools.action.removeFramesTip',
            ),
            crop_image: ('crop.action', 'crop.actionTip'),
            rotate_clockwise: (
                'geometry.rotateClockwise',
                'geometry.rotateClockwiseTip',
            ),
            rotate_counterclockwise: (
                'geometry.rotateCounterclockwise',
                'geometry.rotateCounterclockwiseTip',
            ),
            rotate_180: ('geometry.rotate180', 'geometry.rotate180Tip'),
            flip_horizontal: (
                'geometry.flipHorizontal',
                'geometry.flipHorizontalTip',
            ),
            flip_vertical: (
                'geometry.flipVertical',
                'geometry.flipVerticalTip',
            ),
            transform_image: ('geometry.transform', 'geometry.transformTip'),
            adjust_image: ('adjustment.action', 'adjustment.actionTip'),
            check_image_quality: ('quality.action', 'quality.actionTip'),
            undo_image_processing: (
                'imageTools.action.undoCommitted',
                'imageTools.action.undoCommittedTip',
            ),
            reset_all: ('resetAll', 'resetAllDetail'),
            color1: ('boxLineColor', 'boxLineColorDetail'),
            create: ('crtBox', 'crtBoxDetail'),
            select_tool: ('tool.select', 'tool.selectTip'),
            pan_tool: ('tool.pan', 'tool.panTip'),
            delete: ('delBox', 'delBoxDetail'),
            copy: ('dupBox', 'dupBoxDetail'),
            hide_all: ('hideAllBox', 'hideAllBoxDetail'),
            show_all: ('showAllBox', 'showAllBoxDetail'),
            toggle_visibility: ('hideAllBox', 'hideAllBoxDetail'),
            help_default: ('tutorialDefault', 'tutorialDetail'),
            show_info: ('info', 'info'),
            show_shortcut: ('shortcut', 'shortcut'),
            zoom_in: ('zoomin', 'zoominDetail'),
            zoom_out: ('zoomout', 'zoomoutDetail'),
            zoom_org: ('originalsize', 'originalsizeDetail'),
            fit_window: ('fitWin', 'fitWinDetail'),
            fit_width: ('fitWidth', 'fitWidthDetail'),
            edit: ('editLabel', 'editLabelDetail'),
            shape_line_color: ('shapeLineColor', 'shapeLineColorDetail'),
            shape_fill_color: ('shapeFillColor', 'shapeFillColorDetail'),
            labels: ('showHide', None),
            self.draw_squares_option: ('drawSquares', None),
            self.auto_saving: ('autoSaveMode', None),
            self.single_class_mode: ('singleClsMode', None),
            self.display_label_option: ('displayLabel', None),
            self.copy_here_action: ('action.copyHere', None),
            self.move_here_action: ('action.moveHere', None),
        }
        self.retranslate_ui()

        self.statusBar().showMessage(tr('status.started', app=__appname__))
        self.statusBar().show()

        # Application state.
        self.image = QImage()
        self.last_open_dir = None
        self.recent_files = []
        self.max_recent = 7
        self.line_color = None
        self.fill_color = None
        self.zoom_level = 100
        self.fit_window = False
        # Add Chris
        self.difficult = False

        if settings.get(SETTING_RECENT_FILES):
            self.recent_files = list(settings.get(SETTING_RECENT_FILES))

        size = settings.get(SETTING_WIN_SIZE, QSize(600, 500))
        position = QPoint(0, 0)
        saved_position = settings.get(SETTING_WIN_POSE, position)
        # Fix the multiple monitors issue
        for i in range(QApplication.desktop().screenCount()):
            if QApplication.desktop().availableGeometry(i).contains(saved_position):
                position = saved_position
                break
        self.resize(size)
        self.move(position)
        save_dir = ustr(settings.get(SETTING_SAVE_DIR, None))
        self.last_open_dir = ustr(settings.get(SETTING_LAST_OPEN_DIR, None))
        if self.default_save_dir is None and save_dir is not None and os.path.exists(save_dir):
            self.default_save_dir = save_dir
            self.statusBar().showMessage(tr(
                'status.startedSaveDir',
                app=__appname__,
                path=self.default_save_dir,
            ))
            self.statusBar().show()
        if self.default_save_dir\
                and os.path.isdir(ustr(self.default_save_dir)):
            self.load_candidate_labels_from_dir(
                ustr(self.default_save_dir)
            )
        self._sync_annotation_directory_ui()

        self.restoreState(settings.get(SETTING_WIN_STATE, QByteArray()))
        Shape.line_color = self.line_color = QColor(settings.get(SETTING_LINE_COLOR, DEFAULT_LINE_COLOR))
        Shape.fill_color = self.fill_color = QColor(settings.get(SETTING_FILL_COLOR, DEFAULT_FILL_COLOR))
        self.canvas.set_drawing_color(self.line_color)
        # Add chris
        Shape.difficult = self.difficult

        # Populate the File menu dynamically.
        self.update_file_menu()

        # Since loading the file may take some time, make sure it runs in the background.
        if self.file_path and os.path.isdir(self.file_path):
            self.queue_event(partial(
                self.start_directory_load, self.file_path or ""
            ))
        elif self.file_path:
            self.queue_event(partial(self.load_file, self.file_path or ""))

        # Callbacks:
        self.zoom_widget.valueChanged.connect(self.paint_canvas)

        # Display cursor coordinates at the right of status bar
        self.label_coordinates = QLabel('')
        self.statusBar().addPermanentWidget(self.label_coordinates)
        self.statusBar().addPermanentWidget(self.zoom_widget)
        self.canvas.coordinatesChanged.connect(
            self.label_coordinates.setText
        )
        self.top_commands.set_counter(0, 0)

