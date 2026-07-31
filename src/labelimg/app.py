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

from functools import cmp_to_key, partial
from collections import defaultdict

try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
except ImportError:
    # needed for py3+qt4
    # Ref:
    # http://pyqt.sourceforge.net/Docs/PyQt4/incompatible_apis.html
    # http://stackoverflow.com/questions/21217399/pyqt4-qtcore-qvariant-object-instead-of-a-string
    if sys.version_info.major >= 3:
        import sip
        sip.setapi('QVariant', 2)
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

from labelimg.combobox import ComboBox
from labelimg.resources import *
from labelimg.constants import *
from labelimg.utils import *
from labelimg.settings import Settings
from labelimg.shape import Shape, DEFAULT_LINE_COLOR, DEFAULT_FILL_COLOR
from labelimg.stringBundle import StringBundle
from labelimg.canvas import Canvas
from labelimg.zoomWidget import ZoomWidget
from labelimg.candidate_label_dialog import CandidateLabelDialog
from labelimg.colorDialog import ColorDialog
from labelimg.annotation_document import (
    AnnotationDocument,
    AnnotationDocumentError,
    AnnotationFormat,
)
from labelimg.annotation_workspace import AnnotationWorkspace
from labelimg.toolBar import ToolBar
from labelimg.ustr import ustr
from labelimg.hashableQListWidgetItem import HashableQListWidgetItem
from labelimg.file_list import (
    BatchRenameDialog,
    CURRENT_IMAGE_ROLE,
    FILE_ANNOTATION_STATE_ROLE,
    FileListItemDelegate,
    FileListWidget,
    validate_base_name,
    validate_rename_mapping,
)
from labelimg.file_operations import (
    AnnotationFileService,
    FileOperationError,
    SynchronizedRenamer,
)

__appname__ = 'labelImg'
FILE_LIST_ANNOTATED_MARK = '\u25cb'
FILE_LIST_VERIFIED_MARK = '\u2713'
FILE_LIST_QUESTIONED_MARK = '?'


def document_format_name(annotation_format):
    return {
        AnnotationFormat.PASCAL_VOC: FORMAT_PASCALVOC,
        AnnotationFormat.YOLO: FORMAT_YOLO,
        AnnotationFormat.CREATE_ML: FORMAT_CREATEML,
    }[annotation_format]


if platform.system() == 'Windows':
    WINDOWS_LOGICAL_COMPARE = ctypes.windll.shlwapi.StrCmpLogicalW
    WINDOWS_LOGICAL_COMPARE.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
    ]
    WINDOWS_LOGICAL_COMPARE.restype = ctypes.c_int
else:
    WINDOWS_LOGICAL_COMPARE = None


def portable_logical_compare(left_name, right_name):
    """Compare names using Windows Explorer-style numeric chunks."""
    left_parts = re.split(r'(\d+)', left_name.casefold())
    right_parts = re.split(r'(\d+)', right_name.casefold())

    for left_part, right_part in zip(left_parts, right_parts):
        left_is_number = left_part.isdigit()
        right_is_number = right_part.isdigit()

        if left_is_number and right_is_number:
            left_number = int(left_part)
            right_number = int(right_part)
            if left_number != right_number:
                return (left_number > right_number) - (left_number < right_number)
            if len(left_part) != len(right_part):
                # StrCmpLogicalW places the longer zero-padded form first
                # when two numeric chunks have the same value.
                return (len(right_part) > len(left_part)) - (
                    len(right_part) < len(left_part)
                )
        elif left_is_number != right_is_number:
            return -1 if left_is_number else 1
        elif left_part != right_part:
            return (left_part > right_part) - (left_part < right_part)

    return (len(left_parts) > len(right_parts)) - (
        len(left_parts) < len(right_parts)
    )


def compare_image_paths(left_path, right_path):
    left_name = os.path.basename(left_path)
    right_name = os.path.basename(right_path)
    if WINDOWS_LOGICAL_COMPARE is not None:
        comparison = WINDOWS_LOGICAL_COMPARE(left_name, right_name)
    else:
        comparison = portable_logical_compare(left_name, right_name)

    if comparison:
        return comparison

    left_key = left_path.casefold()
    right_key = right_path.casefold()
    return (left_key > right_key) - (left_key < right_key)


class LabelListItemDelegate(QStyledItemDelegate):
    selection_marker_width = 3
    selection_marker_inset = 4
    selection_marker_radius = 1.5
    visibility_area_width = 24
    visibility_icon_size = 16
    visible_icon_opacity = 0.8
    hidden_icon_opacity = 0.35
    hovered_icon_opacity = 1.0

    def initStyleOption(self, option, index):
        super(LabelListItemDelegate, self).initStyleOption(option, index)
        option.features &= ~QStyleOptionViewItem.HasCheckIndicator

    def paint(self, painter, option, index):
        paint_option = QStyleOptionViewItem(option)
        row_rect = self.visible_row_rect(option)
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            paint_option.state &= ~QStyle.State_Selected
            paint_option.state &= ~QStyle.State_HasFocus
            paint_option.state &= ~QStyle.State_MouseOver
            paint_option.font.setBold(True)

        background = index.data(Qt.BackgroundRole)
        if isinstance(background, QBrush) and background.style() != Qt.NoBrush:
            painter.fillRect(row_rect, background)

        paint_option.rect = row_rect.adjusted(
            0,
            0,
            -self.visibility_area_width,
            0,
        )
        super(LabelListItemDelegate, self).paint(
            painter,
            paint_option,
            index,
        )

        if selected:
            painter.save()
            palette = (
                option.widget.palette()
                if option.widget is not None
                else option.palette
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(palette.color(QPalette.Highlight))
            marker_rect = QRectF(
                row_rect.left(),
                row_rect.top() + self.selection_marker_inset,
                self.selection_marker_width,
                max(
                    0,
                    row_rect.height()
                    - (2 * self.selection_marker_inset),
                ),
            )
            painter.drawRoundedRect(
                marker_rect,
                self.selection_marker_radius,
                self.selection_marker_radius,
            )
            painter.restore()

        self.paint_visibility_icon(painter, option, index, row_rect)

    def visible_row_rect(self, option):
        row_rect = QRect(option.rect)
        if option.widget is not None and hasattr(option.widget, 'viewport'):
            row_rect.setRight(
                min(
                    row_rect.right(),
                    option.widget.viewport().width() - 1,
                )
            )
        return row_rect

    def paint_visibility_icon(self, painter, option, index, row_rect):
        checked = index.data(Qt.CheckStateRole) == Qt.Checked
        hovered = (
            option.widget is not None
            and hasattr(option.widget, 'visibility_icon_hovered')
            and option.widget.visibility_icon_hovered(index)
        )
        if hovered:
            opacity = self.hovered_icon_opacity
        elif checked:
            opacity = self.visible_icon_opacity
        else:
            opacity = self.hidden_icon_opacity

        palette = (
            option.widget.palette()
            if option.widget is not None
            else option.palette
        )
        icon_rect = self.visibility_icon_rect(row_rect)
        center = icon_rect.center()
        left = icon_rect.left() + 1.5
        right = icon_rect.right() - 1.5
        top = center.y() - 4
        bottom = center.y() + 4

        eye_path = QPainterPath()
        eye_path.moveTo(left, center.y())
        eye_path.cubicTo(
            left + 3,
            top,
            right - 3,
            top,
            right,
            center.y(),
        )
        eye_path.cubicTo(
            right - 3,
            bottom,
            left + 3,
            bottom,
            left,
            center.y(),
        )

        color = palette.color(QPalette.Text)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setOpacity(opacity)
        painter.setPen(
            QPen(
                color,
                1.5,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        )
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(eye_path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(center, 2.25, 2.25)

        if not checked:
            painter.setPen(
                QPen(
                    color,
                    2,
                    Qt.SolidLine,
                    Qt.RoundCap,
                    Qt.RoundJoin,
                )
            )
            painter.drawLine(
                QPointF(icon_rect.left() + 2, icon_rect.top() + 2),
                QPointF(icon_rect.right() - 2, icon_rect.bottom() - 2),
            )
        painter.restore()

    def visibility_icon_rect(self, row_rect):
        area_left = (
            row_rect.x()
            + row_rect.width()
            - self.visibility_area_width
        )
        icon_left = area_left + (
            self.visibility_area_width - self.visibility_icon_size
        ) / 2.0
        icon_top = row_rect.y() + (
            row_rect.height() - self.visibility_icon_size
        ) / 2.0
        return QRectF(
            icon_left,
            icon_top,
            self.visibility_icon_size,
            self.visibility_icon_size,
        )


class LabelListWidget(QListWidget):
    """Label list with Explorer-style selection and independent visibility checks."""

    def __init__(self, *args, **kwargs):
        super(LabelListWidget, self).__init__(*args, **kwargs)
        self._visibility_press_item = None
        self._visibility_hover_index = QPersistentModelIndex()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideRight)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def visibility_rect(self, index):
        row_rect = self.visualRect(index)
        visible_right = min(
            row_rect.right(),
            self.viewport().width() - 1,
        )
        return QRect(
            visible_right
            - LabelListItemDelegate.visibility_area_width
            + 1,
            row_rect.y(),
            LabelListItemDelegate.visibility_area_width,
            row_rect.height(),
        )

    def visibility_icon_hovered(self, index):
        return (
            self._visibility_hover_index.isValid()
            and self._visibility_hover_index == index
        )

    def set_visibility_hover_index(self, index):
        persistent_index = (
            QPersistentModelIndex(index)
            if index.isValid()
            else QPersistentModelIndex()
        )
        if persistent_index == self._visibility_hover_index:
            return

        previous = self._visibility_hover_index
        self._visibility_hover_index = persistent_index
        if previous.isValid():
            self.viewport().update(
                self.visualRect(QModelIndex(previous))
            )
        if persistent_index.isValid():
            self.viewport().update(
                self.visualRect(QModelIndex(persistent_index))
            )

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.pos())
        if (
            index.isValid()
            and self.visibility_rect(index).contains(event.pos())
        ):
            self.set_visibility_hover_index(index)
        else:
            self.set_visibility_hover_index(QModelIndex())
        super(LabelListWidget, self).mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.set_visibility_hover_index(QModelIndex())
        super(LabelListWidget, self).leaveEvent(event)

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            item = self.itemFromIndex(index)
            if (
                event.button() == Qt.LeftButton
                and item.flags() & Qt.ItemIsUserCheckable
                and self.visibility_rect(index).contains(event.pos())
            ):
                self._visibility_press_item = item
                item.setCheckState(
                    Qt.Unchecked
                    if item.checkState() == Qt.Checked
                    else Qt.Checked
                )
                event.accept()
                return
        elif (
            event.button() == Qt.LeftButton
            and event.modifiers() == Qt.NoModifier
        ):
            self.clearSelection()
            self.setCurrentItem(None)

        super(LabelListWidget, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._visibility_press_item is not None:
            self._visibility_press_item = None
            event.accept()
            return
        super(LabelListWidget, self).mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key_A
            and event.modifiers() & Qt.ControlModifier
        ):
            window = self.window()
            if hasattr(window, 'actions'):
                window.actions.showAll.trigger()
            event.accept()
            return
        super(LabelListWidget, self).keyPressEvent(event)


class WindowMixin(object):

    def menu(self, title, actions=None):
        menu = self.menuBar().addMenu(title)
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


class MainWindow(QMainWindow, WindowMixin):
    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = list(range(3))

    def __init__(self, default_filename=None, default_prefdef_class_file=None, default_save_dir=None):
        super(MainWindow, self).__init__()
        self.setWindowTitle(__appname__)

        # Load setting in the main thread
        self.settings = Settings()
        self.settings.load()
        settings = self.settings

        self.os_name = platform.system()

        # Load string bundle for i18n
        self.string_bundle = StringBundle.get_bundle()
        get_str = lambda str_id: self.string_bundle.get_string(str_id)

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

        self._beginner = True
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

        self.items_to_shapes = {}
        self.shapes_to_items = {}
        self.annotation_clipboard = []
        self.prev_label_text = ''

        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(0, 0, 0, 0)

        # Create a widget for using default label
        self.use_default_label_checkbox = QCheckBox(get_str('useDefaultLabel'))
        self.use_default_label_checkbox.setChecked(False)
        self.default_label_text_line = QLineEdit()
        use_default_label_qhbox_layout = QHBoxLayout()
        use_default_label_qhbox_layout.addWidget(self.use_default_label_checkbox)
        use_default_label_qhbox_layout.addWidget(self.default_label_text_line)
        use_default_label_container = QWidget()
        use_default_label_container.setLayout(use_default_label_qhbox_layout)

        # Create a widget for edit and diffc button
        self.diffc_button = QCheckBox(get_str('useDifficult'))
        self.diffc_button.setChecked(False)
        self.diffc_button.setEnabled(False)
        self.diffc_button.stateChanged.connect(self.button_state)
        self.edit_button = QToolButton()
        self.edit_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        # Add some of widgets to list_layout
        list_layout.addWidget(self.edit_button)
        list_layout.addWidget(self.diffc_button)
        list_layout.addWidget(use_default_label_container)

        # Create and add combobox for showing unique labels in group
        self.combo_box = ComboBox(self)
        list_layout.addWidget(self.combo_box)

        # Create and add a widget for showing current label items
        self.label_list = LabelListWidget()
        self.label_list.setSelectionMode(
            QAbstractItemView.ExtendedSelection
        )
        self.label_list.setSortingEnabled(True)
        self.label_list.setItemDelegate(
            LabelListItemDelegate(self.label_list)
        )
        label_list_container = QWidget()
        label_list_container.setLayout(list_layout)
        self.label_list.itemActivated.connect(self.label_selection_changed)
        self.label_list.itemSelectionChanged.connect(self.label_selection_changed)
        self.label_list.itemDoubleClicked.connect(self.edit_label)
        # Connect to itemChanged to detect checkbox changes.
        self.label_list.itemChanged.connect(self.label_item_changed)
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
        self.file_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list_widget.customContextMenuRequested.connect(
            self.pop_file_list_menu
        )
        file_list_layout = QVBoxLayout()
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        file_list_layout.addWidget(self.file_list_widget)
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

        self.zoom_widget = ZoomWidget()
        self.color_dialog = ColorDialog(parent=self)

        self.canvas = Canvas(parent=self)
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

        self.canvas.newShape.connect(self.new_shape)
        self.canvas.shapeMoved.connect(self.set_dirty)
        self.canvas.selectionChanged.connect(self.shape_selection_changed)
        self.canvas.drawingPolygon.connect(self.toggle_drawing_sensitive)

        self.setCentralWidget(scroll)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.file_dock)
        self.file_dock.setFeatures(QDockWidget.DockWidgetFloatable)

        self.dock_features = QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetFloatable
        self.dock.setFeatures(self.dock.features() ^ self.dock_features)

        # Actions
        action = partial(new_action, self)
        quit = action(get_str('quit'), self.close,
                      'Ctrl+Q', 'quit', get_str('quitApp'))

        open = action(get_str('openFile'), self.open_file,
                      'Ctrl+O', 'open', get_str('openFileDetail'))

        open_dir = action(get_str('openDir'), self.open_dir_dialog,
                          'Ctrl+u', 'open', get_str('openDir'))

        change_save_dir = action(get_str('changeSaveDir'), self.change_save_dir_dialog,
                                 'Ctrl+r', 'open', get_str('changeSavedAnnotationDir'))

        open_annotation = action(get_str('openAnnotation'), self.open_annotation_dialog,
                                 'Ctrl+Shift+O', 'open', get_str('openAnnotationDetail'))
        copy_annotations = action('Copy Labels', self.copy_current_bounding_boxes, 'Ctrl+C',
                                  'copy', 'Copy selected labels from the current image',
                                  enabled=False)
        paste_annotations = action('Paste Labels', self.paste_copied_bounding_boxes, 'Ctrl+V',
                                   'copy', 'Paste copied labels to the current image')
        copy_prev_bounding = action(get_str('copyPrevBounding'), self.copy_previous_bounding_boxes,
                                    None, 'copy', get_str('copyPrevBounding'))

        open_next_image = action(get_str('nextImg'), self.open_next_image,
                                 'd', 'next', get_str('nextImgDetail'))

        open_prev_image = action(get_str('prevImg'), self.open_prev_image,
                                 'a', 'prev', get_str('prevImgDetail'))

        verify = action(get_str('verifyImg'), self.verify_image,
                        'space', 'verify', get_str('verifyImgDetail'))
        question = action(
            'Question Image',
            self.question_image,
            'Ctrl+Space',
            'help',
            'Mark or unmark image as needing review',
        )

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
                             self.change_format, 'Ctrl+',
                             get_format_meta(self.annotation_format)[1],
                             get_str('changeSaveFormat'), enabled=True)

        save_as = action(get_str('saveAs'), self.save_file_as,
                         'Ctrl+Shift+S', 'save-as', get_str('saveAsDetail'), enabled=False)

        close = action(get_str('closeCur'), self.close_file, 'Ctrl+W', 'close', get_str('closeCurDetail'))

        delete_image = action(get_str('deleteImg'), self.delete_image, 'Ctrl+Delete', 'close', get_str('deleteImgDetail'))

        reset_all = action(get_str('resetAll'), self.reset_all, None, 'resetall', get_str('resetAllDetail'))

        color1 = action(get_str('boxLineColor'), self.choose_color1,
                        'Ctrl+L', 'color_line', get_str('boxLineColorDetail'))

        create_mode = action(get_str('crtBox'), self.set_create_mode,
                             'w', 'new', get_str('crtBoxDetail'), enabled=False)
        edit_mode = action(get_str('editBox'), self.set_edit_mode,
                           'Ctrl+J', 'edit', get_str('editBoxDetail'), enabled=False)

        create = action(get_str('crtBox'), self.create_shape,
                        'w', 'new', get_str('crtBoxDetail'), enabled=False)
        delete = action(get_str('delBox'), self.delete_selected_shape,
                        'Delete', 'delete', get_str('delBoxDetail'), enabled=False)
        copy = action(get_str('dupBox'), self.copy_selected_shape,
                      'Ctrl+D', 'copy', get_str('dupBoxDetail'),
                      enabled=False)

        advanced_mode = action(get_str('advancedMode'), self.toggle_advanced_mode,
                               'Ctrl+Shift+A', 'expert', get_str('advancedModeDetail'),
                               checkable=True)

        hide_all = action(get_str('hideAllBox'), partial(self.toggle_polygons, False),
                          'Ctrl+H', 'hide', get_str('hideAllBoxDetail'),
                          enabled=False)
        show_all = action(get_str('showAllBox'), partial(self.toggle_polygons, True),
                          'Ctrl+A', 'hide', get_str('showAllBoxDetail'),
                          enabled=False)

        help_default = action(get_str('tutorialDefault'), self.show_default_tutorial_dialog, None, 'help', get_str('tutorialDetail'))
        show_info = action(get_str('info'), self.show_info_dialog, None, 'help', get_str('info'))
        show_shortcut = action(get_str('shortcut'), self.show_shortcuts_dialog, None, 'help', get_str('shortcut'))

        zoom = QWidgetAction(self)
        zoom.setDefaultWidget(self.zoom_widget)
        self.zoom_widget.setWhatsThis(
            u"Zoom in or out of the image. Also accessible with"
            " %s and %s from the canvas." % (format_shortcut("Ctrl+[-+]"),
                                             format_shortcut("Ctrl+Wheel")))
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

        edit = action(get_str('editLabel'), self.edit_label,
                      'Ctrl+E', 'edit', get_str('editLabelDetail'),
                      enabled=False)
        self.edit_button.setDefaultAction(edit)

        shape_line_color = action(get_str('shapeLineColor'), self.choose_shape_line_color,
                                  icon='color_line', tip=get_str('shapeLineColorDetail'),
                                  enabled=False)
        shape_fill_color = action(get_str('shapeFillColor'), self.choose_shape_fill_color,
                                  icon='color', tip=get_str('shapeFillColorDetail'),
                                  enabled=False)

        labels = self.dock.toggleViewAction()
        labels.setText(get_str('showHide'))
        labels.setShortcut('Ctrl+Shift+L')

        # Label list context menu.
        label_menu = QMenu()
        add_actions(label_menu, (edit, delete))
        self.label_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.label_list.customContextMenuRequested.connect(
            self.pop_label_list_menu)

        # Draw squares/rectangles
        self.draw_squares_option = QAction(get_str('drawSquares'), self)
        self.draw_squares_option.setShortcut('Ctrl+Shift+R')
        self.draw_squares_option.setCheckable(True)
        self.draw_squares_option.setChecked(settings.get(SETTING_DRAW_SQUARE, False))
        self.draw_squares_option.triggered.connect(self.toggle_draw_square)

        # Store actions for further handling.
        self.actions = Struct(save=save, save_format=save_format, saveAs=save_as, open=open, close=close, resetAll=reset_all, deleteImg=delete_image,
                              verify=verify, question=question,
                              lineColor=color1, create=create, delete=delete, edit=edit, copy=copy,
                              copyAnnotations=copy_annotations, pasteAnnotations=paste_annotations,
                              createMode=create_mode, editMode=edit_mode, advancedMode=advanced_mode,
                              shapeLineColor=shape_line_color, shapeFillColor=shape_fill_color,
                              hideAll=hide_all, showAll=show_all,
                              zoom=zoom, zoomIn=zoom_in, zoomOut=zoom_out, zoomOrg=zoom_org,
                              fitWindow=fit_window, fitWidth=fit_width,
                              zoomActions=zoom_actions,
                              fileMenuActions=(
                                  open, open_dir, save, save_as, close, reset_all, quit),
                              beginner=(), advanced=(),
                              editMenu=(edit, copy_annotations, paste_annotations, copy, delete,
                                        None, color1, self.draw_squares_option),
                              beginnerContext=(create, edit, copy, delete),
                              advancedContext=(create_mode, edit_mode, edit, copy,
                                               delete, shape_line_color, shape_fill_color),
                              onLoadActive=(
                                  close, create, create_mode, edit_mode),
                              onShapesPresent=(save_as, hide_all, show_all))

        self.menus = Struct(
            file=self.menu(get_str('menu_file')),
            edit=self.menu(get_str('menu_edit')),
            view=self.menu(get_str('menu_view')),
            help=self.menu(get_str('menu_help')),
            recentFiles=QMenu(get_str('menu_openRecent')),
            labelList=label_menu)

        # Auto saving: persist annotation changes shortly after they occur.
        self.auto_saving = QAction(get_str('autoSaveMode'), self)
        self.auto_saving.setCheckable(True)
        self.auto_saving.setChecked(settings.get(SETTING_AUTO_SAVE, False))
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.setInterval(200)
        self.auto_save_timer.timeout.connect(self.save_dirty_annotations)
        # Sync single class mode from PR#106
        self.single_class_mode = QAction(get_str('singleClsMode'), self)
        self.single_class_mode.setShortcut("Ctrl+Shift+S")
        self.single_class_mode.setCheckable(True)
        self.single_class_mode.setChecked(settings.get(SETTING_SINGLE_CLASS, False))
        self.lastLabel = None
        # Add option to enable/disable labels being displayed at the top of bounding boxes
        self.display_label_option = QAction(get_str('displayLabel'), self)
        self.display_label_option.setShortcut("Ctrl+Shift+P")
        self.display_label_option.setCheckable(True)
        self.display_label_option.setChecked(settings.get(SETTING_PAINT_LABEL, False))
        self.display_label_option.triggered.connect(self.toggle_paint_labels_option)

        add_actions(self.menus.file,
                    (open, open_dir, change_save_dir, open_annotation, copy_annotations, paste_annotations,
                     copy_prev_bounding, self.menus.recentFiles, save, save_format, save_as, close,
                     reset_all, delete_image, quit))
        add_actions(self.menus.help, (help_default, show_info, show_shortcut))
        add_actions(self.menus.view, (
            self.auto_saving,
            self.single_class_mode,
            self.display_label_option,
            labels, advanced_mode, None,
            hide_all, show_all, None,
            zoom_in, zoom_out, zoom_org, None,
            fit_window, fit_width))

        self.menus.file.aboutToShow.connect(self.update_file_menu)

        # Custom context menu for the canvas widget:
        add_actions(self.canvas.menus[0], self.actions.beginnerContext)
        add_actions(self.canvas.menus[1], (
            action('&Copy here', self.copy_shape),
            action('&Move here', self.move_shape)))

        self.tools = self.toolbar('Tools')
        self.actions.beginner = (
            open, open_dir, change_save_dir, open_next_image, open_prev_image, verify, question, save, save_format, None, create, copy, delete, None,
            zoom_in, zoom, zoom_out, fit_window, fit_width)

        self.actions.advanced = (
            open, open_dir, change_save_dir, open_next_image, open_prev_image, save, save_format, None,
            create_mode, edit_mode, None,
            hide_all, show_all)

        self.statusBar().showMessage('%s started.' % __appname__)
        self.statusBar().show()

        # Application state.
        self.image = QImage()
        self.file_path = ustr(default_filename)
        self.last_open_dir = None
        self.recent_files = []
        self.max_recent = 7
        self.line_color = None
        self.fill_color = None
        self.zoom_level = 100
        self.fit_window = False
        # Add Chris
        self.difficult = False

        # Fix the compatible issue for qt4 and qt5. Convert the QStringList to python list
        if settings.get(SETTING_RECENT_FILES):
            if have_qstring():
                recent_file_qstring_list = settings.get(SETTING_RECENT_FILES)
                self.recent_files = [ustr(i) for i in recent_file_qstring_list]
            else:
                self.recent_files = recent_file_qstring_list = settings.get(SETTING_RECENT_FILES)

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
            self.statusBar().showMessage('%s started. Annotation will be saved to %s' %
                                         (__appname__, self.default_save_dir))
            self.statusBar().show()
        if self.default_save_dir\
                and os.path.isdir(ustr(self.default_save_dir)):
            self.load_candidate_labels_from_dir(
                ustr(self.default_save_dir)
            )

        self.restoreState(settings.get(SETTING_WIN_STATE, QByteArray()))
        Shape.line_color = self.line_color = QColor(settings.get(SETTING_LINE_COLOR, DEFAULT_LINE_COLOR))
        Shape.fill_color = self.fill_color = QColor(settings.get(SETTING_FILL_COLOR, DEFAULT_FILL_COLOR))
        self.canvas.set_drawing_color(self.line_color)
        # Add chris
        Shape.difficult = self.difficult

        def xbool(x):
            if isinstance(x, QVariant):
                return x.toBool()
            return bool(x)

        if xbool(settings.get(SETTING_ADVANCE_MODE, False)):
            self.actions.advancedMode.setChecked(True)
            self.toggle_advanced_mode()

        # Populate the File menu dynamically.
        self.update_file_menu()

        # Since loading the file may take some time, make sure it runs in the background.
        if self.file_path and os.path.isdir(self.file_path):
            self.queue_event(partial(self.import_dir_images, self.file_path or ""))
        elif self.file_path:
            self.queue_event(partial(self.load_file, self.file_path or ""))

        # Callbacks:
        self.zoom_widget.valueChanged.connect(self.paint_canvas)

        self.populate_mode_actions()

        # Display cursor coordinates at the right of status bar
        self.label_coordinates = QLabel('')
        self.statusBar().addPermanentWidget(self.label_coordinates)
        self.canvas.coordinatesChanged.connect(
            self.label_coordinates.setText
        )

        # Open Dir if default file
        if self.file_path and os.path.isdir(self.file_path):
            self.open_dir_dialog(dir_path=self.file_path, silent=True)

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

    # Support Functions #
    def set_format(self, save_format):
        if save_format == FORMAT_PASCALVOC:
            self.actions.save_format.setText(FORMAT_PASCALVOC)
            self.actions.save_format.setIcon(new_icon("format_voc"))
            self.annotation_format = AnnotationFormat.PASCAL_VOC

        elif save_format == FORMAT_YOLO:
            self.actions.save_format.setText(FORMAT_YOLO)
            self.actions.save_format.setIcon(new_icon("format_yolo"))
            self.annotation_format = AnnotationFormat.YOLO

        elif save_format == FORMAT_CREATEML:
            self.actions.save_format.setText(FORMAT_CREATEML)
            self.actions.save_format.setIcon(new_icon("format_createml"))
            self.annotation_format = AnnotationFormat.CREATE_ML

    def change_format(self):
        if self.annotation_format == AnnotationFormat.PASCAL_VOC:
            self.set_format(FORMAT_YOLO)
        elif self.annotation_format == AnnotationFormat.YOLO:
            self.set_format(FORMAT_CREATEML)
        elif self.annotation_format == AnnotationFormat.CREATE_ML:
            self.set_format(FORMAT_PASCALVOC)
        else:
            raise ValueError('Unknown label file format.')
        self.set_dirty()

    def no_shapes(self):
        return not self.items_to_shapes

    def toggle_advanced_mode(self, value=True):
        self._beginner = not value
        self.canvas.set_editing(True)
        self.populate_mode_actions()
        self.edit_button.setVisible(not value)
        if value:
            self.actions.createMode.setEnabled(True)
            self.actions.editMode.setEnabled(False)
            self.dock.setFeatures(self.dock.features() | self.dock_features)
        else:
            self.dock.setFeatures(self.dock.features() ^ self.dock_features)

    def populate_mode_actions(self):
        if self.beginner():
            tool, menu = self.actions.beginner, self.actions.beginnerContext
        else:
            tool, menu = self.actions.advanced, self.actions.advancedContext
        self.tools.clear()
        add_actions(self.tools, tool)
        self.canvas.menus[0].clear()
        add_actions(self.canvas.menus[0], menu)
        self.menus.edit.clear()
        actions = (self.actions.create,) if self.beginner()\
            else (self.actions.createMode, self.actions.editMode)
        add_actions(self.menus.edit, actions + self.actions.editMenu)

    def set_beginner(self):
        self.tools.clear()
        add_actions(self.tools, self.actions.beginner)

    def set_advanced(self):
        self.tools.clear()
        add_actions(self.tools, self.actions.advanced)

    def set_dirty(self):
        self.dirty = True
        self.actions.save.setEnabled(True)
        if self.auto_saving.isChecked() and self.default_save_dir\
                and os.path.isdir(ustr(self.default_save_dir)):
            self.auto_save_timer.start()

    def save_dirty_annotations(self):
        if self.dirty and self.auto_saving.isChecked()\
                and self.default_save_dir\
                and os.path.isdir(ustr(self.default_save_dir)):
            self.save_file()

    def set_clean(self):
        self.auto_save_timer.stop()
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.create.setEnabled(True)

    def toggle_actions(self, value=True):
        """Enable/Disable widgets which depend on an opened image."""
        for z in self.actions.zoomActions:
            z.setEnabled(value)
        for action in self.actions.onLoadActive:
            action.setEnabled(value)

    def queue_event(self, function):
        QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        self.statusBar().showMessage(message, delay)

    def reset_state(self):
        self.items_to_shapes.clear()
        self.shapes_to_items.clear()
        self.label_list.clear()
        self.file_path = None
        self.image_data = None
        self.annotation_document = None
        self.canvas.reset_state()
        self.label_coordinates.clear()
        self.combo_box.cb.clear()
        if hasattr(self, 'file_list_widget'):
            self.update_current_file_marker()

    def current_item(self):
        current = self.label_list.currentItem()
        if current is not None and current.isSelected():
            return current
        items = self.label_list.selectedItems()
        if items:
            return items[0]
        return None

    def add_recent_file(self, file_path):
        if file_path in self.recent_files:
            self.recent_files.remove(file_path)
        elif len(self.recent_files) >= self.max_recent:
            self.recent_files.pop()
        self.recent_files.insert(0, file_path)

    def beginner(self):
        return self._beginner

    def advanced(self):
        return not self.beginner()

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
        msg = u'Name:{0} \nApp Version:{1} \n{2} '.format(__appname__, __version__, sys.version_info)
        QMessageBox.information(self, u'Information', msg)

    def show_shortcuts_dialog(self):
        self.show_tutorial_dialog(browser='default', link='https://github.com/tzutalin/labelImg#Hotkeys')

    def create_shape(self):
        assert self.beginner()
        self.canvas.set_editing(False)
        self.actions.create.setEnabled(False)

    def toggle_drawing_sensitive(self, drawing=True):
        """In the middle of drawing, toggling between modes should be disabled."""
        self.actions.editMode.setEnabled(not drawing)
        if not drawing and self.beginner():
            # Cancel creation.
            print('Cancel creation.')
            self.canvas.set_editing(True)
            self.canvas.restore_cursor()
            self.actions.create.setEnabled(True)

    def toggle_draw_mode(self, edit=True):
        self.canvas.set_editing(edit)
        self.actions.createMode.setEnabled(edit)
        self.actions.editMode.setEnabled(not edit)

    def set_create_mode(self):
        assert self.advanced()
        self.toggle_draw_mode(False)

    def set_edit_mode(self):
        assert self.advanced()
        self.toggle_draw_mode(True)
        self.label_selection_changed()

    def update_file_menu(self):
        curr_file_path = self.file_path

        def exists(filename):
            return os.path.exists(filename)
        menu = self.menus.recentFiles
        menu.clear()
        files = [f for f in self.recent_files if f !=
                 curr_file_path and exists(f)]
        for i, f in enumerate(files):
            icon = new_icon('labels')
            action = QAction(
                icon, '&%d %s' % (i + 1, QFileInfo(f).fileName()), self)
            action.triggered.connect(partial(self.load_recent, f))
            menu.addAction(action)

    def pop_label_list_menu(self, point):
        self.menus.labelList.exec_(self.label_list.mapToGlobal(point))

    def selected_file_paths(self):
        selected = {
            item.data(Qt.UserRole)
            for item in self.file_list_widget.selectedItems()
        }
        return [
            image_path
            for image_path in self.m_img_list
            if image_path in selected
        ]

    def update_file_selection_count(self):
        if not hasattr(self, 'file_selection_count_label'):
            return
        selected_count = len(self.file_list_widget.selectedItems())
        total_count = self.file_list_widget.count()
        if selected_count:
            text = '已选 %d / 共 %d' % (
                selected_count,
                total_count,
            )
        else:
            text = '共 %d 个文件' % total_count
        self.file_selection_count_label.setText(text)

    def update_current_file_marker(self):
        current_path = (
            os.path.abspath(self.file_path)
            if self.file_path
            else None
        )
        for index in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(index)
            item_path = item.data(Qt.UserRole)
            item.setData(
                CURRENT_IMAGE_ROLE,
                bool(
                    current_path
                    and item_path
                    and os.path.abspath(item_path) == current_path
                ),
            )
        self.file_list_widget.viewport().update()

    def open_selected_file(self):
        paths = self.selected_file_paths()
        if len(paths) != 1:
            return
        self.open_file_list_path(paths[0])

    def open_file_list_path(self, filename):
        filename = ustr(filename)
        if filename not in self.m_img_list:
            return
        self.cur_img_idx = self.m_img_list.index(filename)
        self.load_file(filename)

    def pop_file_list_menu(self, point):
        item = self.file_list_widget.itemAt(point)
        menu = QMenu(self.file_list_widget)
        if item is None:
            select_all = menu.addAction('全选')
            select_all.triggered.connect(
                self.file_list_widget.selectAll
            )
            select_all.setEnabled(self.file_list_widget.count() > 0)
            menu.exec_(
                self.file_list_widget.viewport().mapToGlobal(point)
            )
            return

        paths = self.selected_file_paths()
        count = len(paths)

        open_action = menu.addAction('打开')
        open_action.setEnabled(count == 1)
        open_action.triggered.connect(self.open_selected_file)

        rename_text = '重命名…' if count == 1 else '批量重命名…'
        rename_action = menu.addAction(rename_text)
        rename_action.setEnabled(count > 0)
        rename_action.triggered.connect(self.rename_selected_files)

        reveal = menu.addAction('在文件资源管理器中显示')
        reveal.setEnabled(count == 1)
        reveal.triggered.connect(self.reveal_selected_file)

        menu.addSeparator()
        review_menu = menu.addMenu('设置复核状态')
        review_enabled = (
            count > 0
            and self.annotation_format
            is AnnotationFormat.PASCAL_VOC
        )
        for title, state in (
            ('标记为已验证', 'verified'),
            ('标记为待复核', 'questioned'),
            ('清除复核状态', 'unreviewed'),
        ):
            review_action = review_menu.addAction(title)
            review_action.setEnabled(review_enabled)
            review_action.triggered.connect(
                partial(self.set_selected_review_state, state)
            )

        select_menu = menu.addMenu('选择')
        select_all = select_menu.addAction('全选')
        select_all.triggered.connect(
            self.file_list_widget.selectAll
        )
        invert = select_menu.addAction('反选')
        invert.triggered.connect(self.invert_file_selection)
        state_menu = select_menu.addMenu('按状态选择')
        for title, state in (
            ('未标注', 'unannotated'),
            ('已标注', 'annotated'),
            ('已验证', 'verified'),
            ('待复核', 'questioned'),
        ):
            action = state_menu.addAction(title)
            action.triggered.connect(
                partial(self.select_files_by_state, state)
            )
        clear_selection = select_menu.addAction('清除选择')
        clear_selection.triggered.connect(
            self.file_list_widget.clearSelection
        )

        copy_menu = menu.addMenu('复制')
        for title, representation in (
            ('文件名', 'name'),
            ('相对路径', 'relative'),
            ('完整路径', 'absolute'),
        ):
            action = copy_menu.addAction(title)
            action.triggered.connect(
                partial(
                    self.copy_selected_file_paths,
                    representation,
                )
            )

        menu.addSeparator()
        annotation_service = self.file_annotation_service()
        annotation_count = annotation_service.annotation_count(paths)
        clear_annotations = menu.addAction(
            '清除选中的 %d 个文件的全部标注…' % count
        )
        clear_annotations.setEnabled(
            annotation_count > 0
            or (
                self.file_path in paths
                and bool(self.dirty or self.canvas.shapes)
            )
        )
        clear_annotations.triggered.connect(
            self.clear_selected_file_annotations
        )

        delete_files = menu.addAction(
            '删除选中的 %d 个文件…' % count
        )
        delete_files.setEnabled(count > 0)
        delete_files.triggered.connect(self.delete_selected_files)

        menu.exec_(
            self.file_list_widget.viewport().mapToGlobal(point)
        )

    def invert_file_selection(self):
        selection_model = self.file_list_widget.selectionModel()
        for index in range(self.file_list_widget.count()):
            model_index = self.file_list_widget.model().index(index, 0)
            selection_model.select(
                model_index,
                QItemSelectionModel.Toggle
                | QItemSelectionModel.Rows,
            )

    def select_files_by_state(self, state, _checked=False):
        blocker = QSignalBlocker(self.file_list_widget)
        self.file_list_widget.clearSelection()
        for index in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(index)
            if item.data(FILE_ANNOTATION_STATE_ROLE) == state:
                item.setSelected(True)
        del blocker
        self.update_file_selection_count()
        self.file_list_widget.viewport().update()

    def copy_selected_file_paths(self, representation, _checked=False):
        values = []
        for path in self.selected_file_paths():
            if representation == 'name':
                value = os.path.basename(path)
            elif representation == 'relative':
                value = self.file_list_display_path(path)
            else:
                value = os.path.abspath(path)
            values.append(value)
        QApplication.clipboard().setText('\n'.join(values))

    def reveal_selected_file(self):
        paths = self.selected_file_paths()
        if len(paths) != 1:
            return
        path = os.path.abspath(paths[0])
        try:
            if platform.system() == 'Windows':
                subprocess.Popen(
                    ['explorer.exe', '/select,', path]
                )
            elif platform.system() == 'Darwin':
                subprocess.Popen(['open', '-R', path])
            else:
                subprocess.Popen(
                    ['xdg-open', os.path.dirname(path)]
                )
        except OSError as error:
            self.error_message(
                'Could not open file manager',
                u'<p>%s</p>' % error,
            )

    def file_annotation_state(self, image_path):
        status = self.annotation_workspace.entry(image_path).status
        if status.questioned:
            return 'questioned'
        if status.verified:
            return 'verified'
        if status.has_annotations:
            return 'annotated'
        return 'unannotated'

    def file_annotation_service(self):
        return AnnotationFileService(
            save_dir=self.default_save_dir,
        )

    def set_selected_review_state(self, state, _checked=False):
        paths = self.selected_file_paths()
        if (
            not paths
            or self.annotation_format
            is not AnnotationFormat.PASCAL_VOC
        ):
            return
        if len(paths) > 1:
            title = {
                'verified': '标记为已验证',
                'questioned': '标记为待复核',
                'unreviewed': '清除复核状态',
            }[state]
            answer = QMessageBox.question(
                self,
                title,
                '确定对选中的 %d 个文件执行“%s”吗？'
                % (len(paths), title),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        failures = []
        if self.file_path in paths and self.dirty:
            if not self.save_current_annotations_directly():
                return
        for image_path in paths:
            try:
                document = self.annotation_document_for_path(
                    image_path
                )
                document.verified = state == 'verified'
                document.questioned = state == 'questioned'
                saved = self.annotation_workspace.save(
                    document,
                    AnnotationFormat.PASCAL_VOC,
                    annotation_path=self.annotation_workspace.entry(
                        image_path
                    ).path_for(AnnotationFormat.PASCAL_VOC),
                )
                if image_path == self.file_path:
                    self.annotation_document = saved.document
                    self.canvas.verified = document.verified
                    self.canvas.questioned = document.questioned
                    self.set_clean()
                    self.paint_canvas()
            except Exception as error:
                failures.append((image_path, error))
        self.refresh_file_list_statuses()
        self.refresh_candidate_labels()
        if failures:
            self.show_file_operation_failures(
                '部分复核状态未能保存',
                failures,
            )
        else:
            self.status('Updated review state for %d file(s)' % len(paths))

    def annotation_document_for_path(self, image_path):
        if image_path == self.file_path:
            return AnnotationDocument.from_shapes(
                image_path=self.file_path,
                image_data=self.image_data,
                shapes=self.canvas.shapes,
                class_names=self.label_hist,
                verified=self.canvas.verified,
                questioned=self.canvas.questioned,
            )
        image_data = read(image_path, None)
        loaded = self.annotation_workspace.load_for_image(
            image_path,
            image_data,
        )
        if loaded is not None:
            return loaded.document
        return AnnotationDocument(
            image_path=image_path,
            image_data=image_data,
            boxes=(),
            class_names=tuple(self.label_hist),
        )

    def save_current_annotations_directly(self):
        if self.file_path is None:
            return True
        try:
            document = AnnotationDocument.from_shapes(
                image_path=self.file_path,
                image_data=self.image_data,
                shapes=self.canvas.shapes,
                class_names=self.label_hist,
                verified=self.canvas.verified,
                questioned=self.canvas.questioned,
            )
            saved = self.annotation_workspace.save(
                document,
                self.annotation_format,
                annotation_path=self.annotation_workspace.entry(
                    self.file_path
                ).path_for(self.annotation_format),
            )
            self.annotation_document = saved.document
            self.set_clean()
            self.update_file_list_item_status(self.file_path)
            return True
        except Exception as error:
            self.error_message(
                'Error saving label data',
                u'<p>%s</p>' % error,
            )
            return False

    def clear_selected_file_annotations(self):
        paths = self.selected_file_paths()
        if not paths:
            return
        count = self.file_annotation_service().annotation_count(paths)
        answer = QMessageBox.question(
            self,
            '清除全部标注',
            (
                '确定清除选中的 %d 个文件对应的 %d 个标注文件吗？'
                '\n图片文件会保留，标注将移入系统回收站。'
                '\n未保存的当前标注也会被丢弃。'
            ) % (len(paths), count),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        current_path = self.file_path
        result = self.run_file_operation(
            paths,
            '正在清除标注…',
            self.file_annotation_service().clear_annotations,
        )
        self.rescan_annotation_workspace()
        self.refresh_file_list_statuses()
        processed = set(
            result.succeeded_images + result.failed_images
        )
        if current_path in processed and os.path.isfile(current_path):
            self.load_file(current_path)
        self.report_file_operation_result(
            '清除标注',
            result,
        )

    def delete_selected_files(self):
        paths = self.selected_file_paths()
        if not paths:
            return
        answer = QMessageBox.question(
            self,
            '删除选中的文件',
            (
                '确定删除选中的 %d 个文件吗？'
                '\n图片及关联标注将移入系统回收站。'
            ) % len(paths),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.delete_file_paths(paths)

    def delete_file_paths(self, paths):
        before = list(self.m_img_list)
        old_current = self.file_path
        old_index = (
            before.index(old_current)
            if old_current in before
            else 0
        )
        result = self.run_file_operation(
            paths,
            '正在删除文件…',
            self.file_annotation_service().delete_images,
        )
        self.rebuild_file_list_after_deletion(
            before,
            old_current,
            old_index,
            result,
        )
        self.rescan_annotation_workspace()
        self.report_file_operation_result('删除文件', result)
        return result

    def run_file_operation(self, paths, title, operation):
        progress = None
        position = [0]
        if len(paths) >= 20:
            progress = QProgressDialog(
                title,
                '取消',
                0,
                len(paths),
                self,
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(400)

        def should_continue():
            if progress is None:
                return True
            progress.setValue(position[0])
            QApplication.processEvents()
            if progress.wasCanceled():
                return False
            position[0] += 1
            return True

        result = operation(paths, should_continue=should_continue)
        if progress is not None:
            progress.setValue(len(paths))
        return result

    def rebuild_file_list_after_deletion(
        self,
        before,
        old_current,
        old_index,
        result,
    ):
        succeeded = set(result.succeeded_images)
        failed = set(result.failed_images)
        self.populate_file_list(self.scan_all_images(self.dir_name))

        next_path = None
        if old_current and old_current not in succeeded:
            if old_current in self.m_img_list:
                next_path = old_current
        elif old_current:
            for candidate in before[old_index + 1:]:
                if candidate in self.m_img_list:
                    next_path = candidate
                    break
            if next_path is None:
                for candidate in reversed(before[:old_index]):
                    if candidate in self.m_img_list:
                        next_path = candidate
                        break

        if (
            next_path == old_current
            and old_current not in failed
        ):
            self.cur_img_idx = self.m_img_list.index(old_current)
            self.update_current_file_marker()
        elif next_path is not None:
            self.cur_img_idx = self.m_img_list.index(next_path)
            self.load_file(next_path)
        elif self.m_img_list:
            self.cur_img_idx = min(old_index, len(self.m_img_list) - 1)
            self.load_file(self.m_img_list[self.cur_img_idx])
        else:
            self.cur_img_idx = 0
            self.reset_state()
            self.set_clean()
            self.toggle_actions(False)
            self.canvas.setEnabled(False)
            self.actions.saveAs.setEnabled(False)
            self.update_current_file_marker()

        for index in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(index)
            if item.data(Qt.UserRole) in failed:
                item.setSelected(True)
        self.update_file_selection_count()

    def rescan_annotation_workspace(self):
        directory = self.default_save_dir or self.dir_name
        if directory and os.path.isdir(directory):
            self.annotation_workspace.scan(directory)
        self.refresh_candidate_labels()

    def report_file_operation_result(self, title, result):
        if result.failures:
            self.show_file_operation_failures(
                title + '部分失败',
                [
                    (
                        failure.path,
                        failure.reason,
                    )
                    for failure in result.failures
                ],
            )
            return
        message = '%s完成：%d 个文件' % (
            title,
            len(result.succeeded_images),
        )
        if result.canceled:
            message += '（已取消剩余操作）'
        self.status(message)

    def show_file_operation_failures(self, title, failures):
        details = '\n'.join(
            '%s: %s' % (path, error)
            for path, error in failures
        )
        QMessageBox.warning(
            self,
            title,
            '%s\n\n%s' % (title, details),
        )

    def rename_selected_files(self):
        paths = self.selected_file_paths()
        if not paths:
            return
        if len(paths) == 1:
            self.rename_single_file(paths[0])
            return
        dialog = BatchRenameDialog(
            paths,
            self.dir_name,
            save_dir=self.default_save_dir,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        self.execute_file_rename(dialog.mapping)

    def rename_single_file(self, source):
        stem, extension = os.path.splitext(os.path.basename(source))
        new_stem, accepted = QInputDialog.getText(
            self,
            '重命名',
            '新文件名（扩展名 %s 保持不变）' % extension,
            QLineEdit.Normal,
            stem,
        )
        if not accepted:
            return
        new_stem = new_stem.strip()
        target = os.path.join(
            os.path.dirname(source),
            new_stem + extension,
        )
        error = validate_base_name(new_stem, target)
        if not error:
            error = validate_rename_mapping(
                {source: target},
                self.default_save_dir,
            ).get(source, '')
        if error:
            QMessageBox.warning(self, '无法重命名', error)
            return
        if source == target:
            return
        self.execute_file_rename({source: target})

    def execute_file_rename(self, mapping):
        if self.file_path in mapping and self.dirty:
            if not self.save_current_annotations_directly():
                return
        old_current = self.file_path
        selected_before = self.selected_file_paths()
        try:
            renamed = SynchronizedRenamer(
                save_dir=self.default_save_dir,
            ).rename(mapping)
        except FileOperationError as error:
            QMessageBox.warning(
                self,
                '重命名失败',
                str(error),
            )
            return

        current_after = renamed.get(old_current, old_current)
        selected_after = {
            renamed.get(path, path)
            for path in selected_before
        }
        self.populate_file_list(self.scan_all_images(self.dir_name))
        if old_current in renamed and current_after in self.m_img_list:
            self.cur_img_idx = self.m_img_list.index(current_after)
            self.load_file(current_after)
        elif current_after in self.m_img_list:
            self.cur_img_idx = self.m_img_list.index(current_after)
            self.update_current_file_marker()
        for index in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(index)
            if item.data(Qt.UserRole) in selected_after:
                item.setSelected(True)
        self.rescan_annotation_workspace()
        self.refresh_file_list_statuses()
        self.update_file_selection_count()
        self.status('Renamed %d file(s)' % len(renamed))

    def edit_label(self):
        if not self.canvas.editing():
            return
        item = self.current_item()
        if not item:
            return
        text = self.candidate_label_dialog.choose(item.text())
        if text is not None:
            item.setText(text)
            item.setBackground(generate_color_by_text(text))
            self.set_dirty()
            self.update_combo_box()

    # Tzutalin 20160906 : Add file list and dock to move faster
    def file_item_double_clicked(self, item=None):
        if item is None:
            return
        filename = item.data(Qt.UserRole)
        if not filename:
            filename = item.text()
        filename = ustr(filename)
        if filename not in self.m_img_list:
            return
        if filename:
            self.open_file_list_path(filename)

    # Add chris
    def button_state(self, item=None):
        """ Function to handle difficult examples
        Update on each object """
        selection = self.canvas.selection_snapshot
        if (
            not self.canvas.editing()
            or not selection.capabilities.can_edit_single
        ):
            return

        shape = selection.active
        difficult = self.diffc_button.isChecked()
        if difficult != shape.difficult:
            shape.difficult = difficult
            self.set_dirty()

    # React to canvas signals.
    def shape_selection_changed(self, selected=False):
        selection = self.canvas.selection_snapshot
        blocker = QSignalBlocker(self.label_list)
        self.label_list.clearSelection()
        for shape in selection.selected:
            item = self.shapes_to_items.get(shape)
            if item is not None:
                item.setSelected(True)
        active_item = self.shapes_to_items.get(
            selection.active
        )
        if active_item is not None:
            self.label_list.setCurrentItem(
                active_item,
                QItemSelectionModel.NoUpdate,
            )
        else:
            self.label_list.setCurrentItem(None)
        del blocker
        self.update_selection_actions(selection)

    def selected_label_shapes(self):
        return [
            self.items_to_shapes[item]
            for index in range(self.label_list.count())
            for item in (self.label_list.item(index),)
            if item.isSelected() and item in self.items_to_shapes
        ]

    def update_selection_actions(self, selection=None):
        if selection is None:
            selection = self.canvas.selection_snapshot
        capabilities = selection.capabilities

        self.actions.delete.setEnabled(capabilities.can_bulk)
        self.actions.copy.setEnabled(capabilities.can_bulk)
        self.actions.copyAnnotations.setEnabled(capabilities.can_bulk)
        self.actions.edit.setEnabled(capabilities.can_edit_single)
        self.actions.shapeLineColor.setEnabled(
            capabilities.can_edit_single
        )
        self.actions.shapeFillColor.setEnabled(
            capabilities.can_edit_single
        )
        self.diffc_button.setEnabled(capabilities.can_edit_single)

        blocker = QSignalBlocker(self.diffc_button)
        if capabilities.can_edit_single:
            self.diffc_button.setChecked(
                selection.active.difficult
            )
        else:
            self.diffc_button.setChecked(False)
        del blocker

    def add_label(self, shape):
        shape.paint_label = self.display_label_option.isChecked()
        item = HashableQListWidgetItem(shape.label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        item.setBackground(generate_color_by_text(shape.label))
        self.items_to_shapes[item] = shape
        self.shapes_to_items[shape] = item
        self.label_list.addItem(item)
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)
        self.update_combo_box()

    def remove_label(self, shape):
        if shape is None:
            # print('rm empty label')
            return
        item = self.shapes_to_items.get(shape)
        if item is None:
            return
        self.label_list.takeItem(self.label_list.row(item))
        del self.shapes_to_items[shape]
        del self.items_to_shapes[item]
        self.update_combo_box()

    def shape_from_annotation(self, annotation_shape):
        label, points, line_color, fill_color, difficult = annotation_shape
        shape = Shape(label=label)
        for x, y in points:
            # Ensure the labels are within the bounds of the image. If not, fix them.
            x, y, snapped = self.canvas.snap_point_to_canvas(x, y)
            if snapped:
                self.set_dirty()
            shape.add_point(QPointF(x, y))
        shape.difficult = difficult
        shape.close()

        if line_color:
            shape.line_color = QColor(*line_color)
        else:
            shape.line_color = generate_color_by_text(label)

        if fill_color:
            shape.fill_color = QColor(*fill_color)
        else:
            shape.fill_color = generate_color_by_text(label)
        return shape

    def load_labels(self, shapes):
        s = []
        for annotation_shape in shapes:
            shape = self.shape_from_annotation(annotation_shape)
            s.append(shape)
            self.add_label(shape)
        self.update_combo_box()
        self.canvas.load_shapes(s)

    def load_annotation_document(self, document):
        shapes, snapped = document.create_shapes(
            self.canvas.snap_point_to_canvas,
            generate_color_by_text,
        )
        for shape in shapes:
            self.add_label(shape)
        self.update_combo_box()
        self.canvas.load_shapes(shapes)
        self.annotation_document = document
        self.canvas.verified = document.verified
        self.canvas.questioned = document.questioned
        if snapped:
            self.set_dirty()

    def update_combo_box(self):
        # Get the unique labels and add them to the Combobox.
        items_text_list = [str(self.label_list.item(i).text()) for i in range(self.label_list.count())]

        unique_text_list = list(set(items_text_list))
        # Add a null row for showing all the labels
        unique_text_list.append("")
        unique_text_list.sort()

        self.combo_box.update_items(unique_text_list)

    def save_labels(self, annotation_file_path):
        annotation_file_path = ustr(annotation_file_path)
        document = AnnotationDocument.from_shapes(
            image_path=self.file_path,
            image_data=self.image_data,
            shapes=self.canvas.shapes,
            class_names=self.label_hist,
            verified=self.canvas.verified,
            questioned=self.canvas.questioned,
        )
        try:
            saved = self.annotation_workspace.save(
                document,
                self.annotation_format,
                annotation_path=annotation_file_path,
            )
            self.annotation_document = saved.document
            if saved.document is not None:
                print(
                    'Image:{0} -> Annotation:{1}'.format(
                        self.file_path,
                        saved.annotation_path,
                    )
                )
            return saved
        except AnnotationDocumentError as e:
            self.error_message(u'Error saving label data', u'<b>%s</b>' % e)
            return None

    def copy_selected_shape(self):
        copied_shapes = self.canvas.copy_selected_shapes()
        if not copied_shapes:
            return
        for shape in copied_shapes:
            self.add_label(shape)
        self.shape_selection_changed(True)
        self.set_dirty()
        self.status('Duplicated %d label(s)' % len(copied_shapes))

    def combo_selection_changed(self, index):
        text = self.combo_box.cb.itemText(index)
        for i in range(self.label_list.count()):
            if text == "":
                self.label_list.item(i).setCheckState(2)
            elif text != self.label_list.item(i).text():
                self.label_list.item(i).setCheckState(0)
            else:
                self.label_list.item(i).setCheckState(2)

    def label_selection_changed(self):
        shapes = self.selected_label_shapes()
        current_item = self.label_list.currentItem()
        active_shape = None
        if (
            current_item is not None
            and current_item.isSelected()
        ):
            active_shape = self.items_to_shapes.get(current_item)

        self.canvas.set_selected_shapes(
            shapes,
            active_shape=active_shape,
        )
        self.update_selection_actions()

    def label_item_changed(self, item):
        shape = self.items_to_shapes[item]
        label = item.text()
        if label != shape.label:
            shape.label = item.text()
            shape.line_color = generate_color_by_text(shape.label)
            self.set_dirty()
        else:  # User probably changed item visibility
            self.canvas.set_shape_visible(shape, item.checkState() == Qt.Checked)

    # Callback functions:
    def new_shape(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        if not self.use_default_label_checkbox.isChecked() or not self.default_label_text_line.text():
            # Sync single class mode from PR#106
            if self.single_class_mode.isChecked() and self.lastLabel:
                text = self.lastLabel
            else:
                text = self.candidate_label_dialog.choose(
                    text=self.prev_label_text
                )
                self.lastLabel = text
        else:
            text = self.default_label_text_line.text()

        # Add Chris
        self.diffc_button.setChecked(False)
        if text is not None:
            self.prev_label_text = text
            generate_color = generate_color_by_text(text)
            shape = self.canvas.set_last_label(text, generate_color, generate_color)
            self.add_label(shape)
            if self.beginner():  # Switch to edit mode.
                self.canvas.set_editing(True)
                self.actions.create.setEnabled(True)
            else:
                self.actions.editMode.setEnabled(True)
            self.set_dirty()

            if text not in self.label_hist:
                self.label_hist.append(text)
        else:
            # self.canvas.undoLastLine()
            self.canvas.reset_all_lines()

    def scroll_request(self, delta, orientation):
        units = - delta / (8 * 15)
        bar = self.scroll_bars[orientation]
        bar.setValue(int(round(bar.value() + bar.singleStep() * units)))

    def pan_request(self, delta_x, delta_y):
        horizontal = self.scroll_bars[Qt.Horizontal]
        vertical = self.scroll_bars[Qt.Vertical]
        horizontal.setValue(horizontal.value() - delta_x)
        vertical.setValue(vertical.value() - delta_y)

    def set_zoom(self, value):
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.MANUAL_ZOOM
        self.zoom_widget.setValue(int(round(value)))

    def add_zoom(self, increment=10):
        self.set_zoom(self.zoom_widget.value() + increment)

    def zoom_request(self, delta):
        # get the current scrollbar positions
        # calculate the percentages ~ coordinates
        h_bar = self.scroll_bars[Qt.Horizontal]
        v_bar = self.scroll_bars[Qt.Vertical]

        # get the current maximum, to know the difference after zooming
        h_bar_max = h_bar.maximum()
        v_bar_max = v_bar.maximum()

        # get the cursor position and canvas size
        # calculate the desired movement from 0 to 1
        # where 0 = move left
        #       1 = move right
        # up and down analogous
        cursor = QCursor()
        pos = cursor.pos()
        relative_pos = QWidget.mapFromGlobal(self, pos)

        cursor_x = relative_pos.x()
        cursor_y = relative_pos.y()

        w = self.scroll_area.width()
        h = self.scroll_area.height()

        # the scaling from 0 to 1 has some padding
        # you don't have to hit the very leftmost pixel for a maximum-left movement
        margin = 0.1
        move_x = (cursor_x - margin * w) / (w - 2 * margin * w)
        move_y = (cursor_y - margin * h) / (h - 2 * margin * h)

        # clamp the values from 0 to 1
        move_x = min(max(move_x, 0), 1)
        move_y = min(max(move_y, 0), 1)

        # zoom in
        units = delta / (8 * 15)
        scale = 10
        self.add_zoom(scale * units)

        # get the difference in scrollbar values
        # this is how far we can move
        d_h_bar_max = h_bar.maximum() - h_bar_max
        d_v_bar_max = v_bar.maximum() - v_bar_max

        # get the new scrollbar values
        new_h_bar_value = h_bar.value() + move_x * d_h_bar_max
        new_v_bar_value = v_bar.value() + move_y * d_v_bar_max

        h_bar.setValue(int(round(new_h_bar_value)))
        v_bar.setValue(int(round(new_v_bar_value)))

    def set_fit_window(self, value=True):
        if value:
            self.actions.fitWidth.setChecked(False)
        self.zoom_mode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjust_scale()

    def set_fit_width(self, value=True):
        if value:
            self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjust_scale()

    def toggle_polygons(self, value):
        for item, shape in self.items_to_shapes.items():
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)

    def load_file(self, file_path=None):
        """Load the specified file, or the last opened file if None."""
        self.reset_state()
        self.canvas.setEnabled(False)
        if file_path is None:
            file_path = self.settings.get(SETTING_FILENAME)

        # Make sure that filePath is a regular python string, rather than QString
        file_path = ustr(file_path)

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
            unicode_file_path = AnnotationDocument.image_path_hint(
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
                    u'Error opening annotation document',
                    u'<p>Could not locate its image.</p>',
                )
                return False

        # Tzutalin 20160906 : Add file list and dock to move faster
        # Keep file selection independent from the image being opened.
        if unicode_file_path and self.file_list_widget.count() > 0:
            if unicode_file_path not in self.m_img_list:
                self.file_list_widget.clear()
                self.m_img_list.clear()

        if unicode_file_path and os.path.exists(unicode_file_path):
            # Load image data first and retain it for annotation saving.
            self.image_data = read(unicode_file_path, None)
            self.annotation_document = None
            self.canvas.verified = False
            self.canvas.questioned = False

            if isinstance(self.image_data, QImage):
                image = self.image_data
            else:
                image = QImage.fromData(self.image_data)
            if image.isNull():
                self.error_message(u'Error opening file',
                                   u"<p>Make sure <i>%s</i> is a valid image file." % unicode_file_path)
                self.status("Error reading %s" % unicode_file_path)
                return False
            self.status("Loaded %s" % os.path.basename(unicode_file_path))
            self.image = image
            self.file_path = unicode_file_path
            self.update_current_file_marker()
            self.canvas.load_pixmap(QPixmap.fromImage(image))
            if annotation_path is not None:
                try:
                    loaded = self.annotation_workspace.load(
                        annotation_path,
                        self.file_path,
                        self.image_data,
                    )
                except AnnotationDocumentError as error:
                    self.error_message(
                        u'Error opening annotation document',
                        u'<b>%s</b>' % error,
                    )
                    return False
                self.set_format(
                    document_format_name(loaded.annotation_format)
                )
                self.load_annotation_document(loaded.document)
            self.set_clean()
            self.canvas.setEnabled(True)
            self.adjust_scale(initial=True)
            self.paint_canvas()
            self.add_recent_file(self.file_path)
            self.toggle_actions(True)
            if annotation_path is None:
                self.show_bounding_box_from_annotation_file(
                    unicode_file_path
                )

            counter = self.counter_str()
            self.setWindowTitle(__appname__ + ' ' + file_path + ' ' + counter)

            self.canvas.setFocus(True)
            return True
        return False

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
            self.status("Error reading %s" % error)
            return False
        if loaded is None:
            return False
        self.set_format(document_format_name(loaded.annotation_format))
        self.load_annotation_document(loaded.document)
        return True

    def resizeEvent(self, event):
        if self.canvas and not self.image.isNull()\
           and self.zoom_mode != self.MANUAL_ZOOM:
            self.adjust_scale()
        super(MainWindow, self).resizeEvent(event)

    def paint_canvas(self):
        assert not self.image.isNull(), "cannot paint null image"
        self.canvas.scale = 0.01 * self.zoom_widget.value()
        self.canvas.label_font_size = int(0.02 * max(self.image.width(), self.image.height()))
        self.canvas.adjustSize()
        self.canvas.update()

    def adjust_scale(self, initial=False):
        value = self.scalers[self.FIT_WINDOW if initial else self.zoom_mode]()
        self.zoom_widget.setValue(int(100 * value))

    def scale_fit_window(self):
        """Figure out the size of the pixmap in order to fit the main widget."""
        e = 2.0  # So that no scrollbars are generated.
        w1 = self.centralWidget().width() - e
        h1 = self.centralWidget().height() - e
        a1 = w1 / h1
        # Calculate a new scale value based on the pixmap's aspect ratio.
        w2 = self.canvas.pixmap.width() - 0.0
        h2 = self.canvas.pixmap.height() - 0.0
        a2 = w2 / h2
        return w1 / w2 if a2 >= a1 else h1 / h2

    def scale_fit_width(self):
        # The epsilon does not seem to work too well here.
        w = self.centralWidget().width() - 2.0
        return w / self.canvas.pixmap.width()

    def closeEvent(self, event):
        if not self.may_continue():
            event.ignore()
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
        settings[SETTING_ADVANCE_MODE] = not self._beginner
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
        settings.save()

    def load_recent(self, filename):
        if self.may_continue():
            self.load_file(filename)

    def scan_all_images(self, folder_path):
        extensions = ['.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        images = []

        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(tuple(extensions)):
                    relative_path = os.path.join(root, file)
                    path = ustr(os.path.abspath(relative_path))
                    images.append(path)
        images.sort(key=cmp_to_key(compare_image_paths))
        return images

    def annotation_path_for_image(self, image_path):
        return self.annotation_workspace.entry(image_path).path_for(
            AnnotationFormat.PASCAL_VOC
        )

    def annotation_paths_for_image(self, image_path):
        return list(self.annotation_workspace.entry(image_path).paths)

    def file_list_display_path(self, image_path):
        if not self.dir_name:
            return os.path.basename(image_path)

        image_path = os.path.abspath(image_path)
        display_root = os.path.abspath(self.dir_name)
        try:
            relative_path = os.path.relpath(image_path, display_root)
        except ValueError:
            return os.path.basename(image_path)

        if (
            relative_path == os.pardir
            or relative_path.startswith(os.pardir + os.sep)
        ):
            return os.path.basename(image_path)
        return relative_path

    def file_list_item_text(self, image_path):
        display_path = self.file_list_display_path(image_path)
        status = self.annotation_workspace.entry(image_path).status
        if status.questioned:
            return display_path + '  ' + FILE_LIST_QUESTIONED_MARK
        if status.verified:
            return display_path + '  ' + FILE_LIST_VERIFIED_MARK
        if status.has_annotations:
            return display_path + '  ' + FILE_LIST_ANNOTATED_MARK
        return display_path

    def update_file_list_item_status(self, image_path):
        if not image_path or image_path not in self.m_img_list:
            return
        index = self.m_img_list.index(image_path)
        item = self.file_list_widget.item(index)
        if item is None:
            return
        item.setData(Qt.UserRole, image_path)
        item.setData(
            FILE_ANNOTATION_STATE_ROLE,
            self.file_annotation_state(image_path),
        )
        item.setText(self.file_list_item_text(image_path))
        item.setToolTip(image_path)

    def refresh_file_list_statuses(self):
        for image_path in self.m_img_list:
            self.update_file_list_item_status(image_path)

    def refresh_candidate_labels(self):
        candidate_labels = list(
            self.annotation_workspace.candidate_labels
        )
        if candidate_labels == self.candidate_labels:
            return False

        self.candidate_labels[:] = candidate_labels
        self.candidate_label_dialog.set_candidate_labels(
            self.candidate_labels
        )
        return True

    def load_candidate_labels_from_dir(self, dir_path):
        candidate_labels = self.annotation_workspace.scan(dir_path)
        for label in candidate_labels:
            if label in self.label_hist:
                continue
            self.label_hist.append(label)

        self.refresh_candidate_labels()
        return len(candidate_labels)

    def change_save_dir_dialog(self, _value=False):
        if self.default_save_dir is not None:
            path = ustr(self.default_save_dir)
        else:
            path = '.'

        dir_path = ustr(QFileDialog.getExistingDirectory(self,
                                                         '%s - Save annotations to the directory' % __appname__, path,  QFileDialog.ShowDirsOnly
                                                         | QFileDialog.DontResolveSymlinks))

        if dir_path is not None and len(dir_path) > 1:
            self.default_save_dir = dir_path
            self.load_candidate_labels_from_dir(dir_path)
            self.refresh_file_list_statuses()

        self.statusBar().showMessage('%s . Annotation will be saved to %s' %
                                     ('Change saved folder', self.default_save_dir))
        self.statusBar().show()

    def open_annotation_dialog(self, _value=False):
        if self.file_path is None:
            self.statusBar().showMessage('Please select image first')
            self.statusBar().show()
            return

        path = os.path.dirname(ustr(self.file_path))\
            if self.file_path else '.'
        filters = "Open Annotation file (%s)" % ' '.join(
            '*%s' % annotation_format.extension
            for annotation_format in AnnotationFormat
        )
        filename = ustr(
            QFileDialog.getOpenFileName(
                self,
                '%s - Choose an annotation file' % __appname__,
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
                                                                    '%s - Open Directory' % __appname__, default_open_dir_path,
                                                                    QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks))
        else:
            target_dir_path = ustr(default_open_dir_path)
        self.last_open_dir = target_dir_path
        self.import_dir_images(target_dir_path)

    def import_dir_images(self, dir_path, initial_index=0):
        if not self.may_continue() or not dir_path:
            return

        self.last_open_dir = dir_path
        self.dir_name = dir_path
        self.file_path = None
        self.populate_file_list(self.scan_all_images(dir_path))

        if self.img_count:
            self.cur_img_idx = min(max(initial_index, 0), self.img_count - 1)
            self.load_file(self.m_img_list[self.cur_img_idx])
        else:
            self.cur_img_idx = 0
            self.reset_state()
            self.set_clean()
            self.toggle_actions(False)
            self.canvas.setEnabled(False)
            self.actions.saveAs.setEnabled(False)

    def populate_file_list(self, image_paths):
        blocker = QSignalBlocker(self.file_list_widget)
        self.file_list_widget.clear()
        self.m_img_list = list(image_paths)
        self.img_count = len(self.m_img_list)
        for image_path in self.m_img_list:
            item = QListWidgetItem(
                self.file_list_item_text(image_path)
            )
            item.setData(Qt.UserRole, image_path)
            item.setData(
                FILE_ANNOTATION_STATE_ROLE,
                self.file_annotation_state(image_path),
            )
            item.setData(CURRENT_IMAGE_ROLE, False)
            item.setToolTip(image_path)
            self.file_list_widget.addItem(item)
        del blocker
        self.update_file_selection_count()
        self.update_current_file_marker()

    def verify_image(self, _value=False):
        self.toggle_image_status('toggle_verified')

    def question_image(self, _value=False):
        self.toggle_image_status('toggle_questioned')

    def toggle_image_status(self, toggle_method):
        if self.file_path is None:
            return
        document = AnnotationDocument.from_shapes(
            image_path=self.file_path,
            image_data=self.image_data,
            shapes=self.canvas.shapes,
            class_names=self.label_hist,
            verified=self.canvas.verified,
            questioned=self.canvas.questioned,
        )
        getattr(document, toggle_method)()
        try:
            saved = self.annotation_workspace.save(
                document,
                self.annotation_format,
                annotation_path=self.annotation_workspace.entry(
                    self.file_path
                ).path_for(self.annotation_format),
            )
        except Exception as error:
            self.error_message(
                'Error saving label data',
                u'<p>%s</p>' % error,
            )
            return
        self.annotation_document = saved.document
        self.canvas.verified = document.verified
        self.canvas.questioned = document.questioned
        self.paint_canvas()
        self.set_clean()
        self.update_file_list_item_status(self.file_path)

    def open_prev_image(self, _value=False):
        # Proceeding prev image without dialog if having any label
        if self.auto_saving.isChecked():
            if self.default_save_dir is not None:
                if self.dirty is True:
                    self.save_file()
            else:
                self.change_save_dir_dialog()
                return

        if not self.may_continue():
            return

        if self.img_count <= 0:
            return

        if self.file_path is None:
            return

        if self.cur_img_idx - 1 >= 0:
            self.cur_img_idx -= 1
            filename = self.m_img_list[self.cur_img_idx]
            if filename:
                self.load_file(filename)

    def open_next_image(self, _value=False):
        # Proceeding prev image without dialog if having any label
        if self.auto_saving.isChecked():
            if self.default_save_dir is not None:
                if self.dirty is True:
                    self.save_file()
            else:
                self.change_save_dir_dialog()
                return

        if not self.may_continue():
            return

        if self.img_count <= 0:
            return

        filename = None
        if self.file_path is None:
            filename = self.m_img_list[0]
            self.cur_img_idx = 0
        else:
            if self.cur_img_idx + 1 < self.img_count:
                self.cur_img_idx += 1
                filename = self.m_img_list[self.cur_img_idx]

        if filename:
            self.load_file(filename)

    def open_file(self, _value=False):
        if not self.may_continue():
            return
        path = os.path.dirname(ustr(self.file_path)) if self.file_path else '.'
        formats = ['*.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        filters = "Image & Annotation files (%s)" % ' '.join(
            formats
            + [
                '*%s' % annotation_format.extension
                for annotation_format in AnnotationFormat
            ]
        )
        filename = QFileDialog.getOpenFileName(self, '%s - Choose Image or Label file' % __appname__, path, filters)
        if filename:
            if isinstance(filename, (tuple, list)):
                filename = filename[0]
            self.cur_img_idx = 0
            self.img_count = 1
            self.load_file(filename)

    def save_file(self, _value=False):
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
            self._save_file(saved_path if self.annotation_document
                            else self.save_file_dialog(remove_ext=False))

    def save_file_as(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        self._save_file(self.save_file_dialog())

    def save_file_dialog(self, remove_ext=True):
        caption = '%s - Choose File' % __appname__
        filters = 'File (*%s)' % self.annotation_format.extension
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
        saved = (
            self.save_labels(annotation_file_path)
            if annotation_file_path
            else None
        )
        if saved:
            self.refresh_candidate_labels()
            self.set_clean()
            self.update_file_list_item_status(self.file_path)
            if saved.removed:
                self.statusBar().showMessage(
                    'Removed empty annotation file %s'
                    % saved.annotation_path
                )
                self.statusBar().show()
            elif saved.document is not None:
                self.statusBar().showMessage(
                    'Saved to  %s' % saved.annotation_path
                )
                self.statusBar().show()

    def close_file(self, _value=False):
        if not self.may_continue():
            return
        self.reset_state()
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

    def may_continue(self):
        if not self.dirty:
            return True
        else:
            discard_changes = self.discard_changes_dialog()
            if discard_changes == QMessageBox.No:
                return True
            elif discard_changes == QMessageBox.Yes:
                self.save_file()
                return True
            else:
                return False

    def discard_changes_dialog(self):
        yes, no, cancel = QMessageBox.Yes, QMessageBox.No, QMessageBox.Cancel
        msg = u'You have unsaved changes, would you like to save them and proceed?\nClick "No" to undo all changes.'
        return QMessageBox.warning(self, u'Attention', msg, yes | no | cancel)

    def error_message(self, title, message):
        return QMessageBox.critical(self, title,
                                    '<p><b>%s</b></p>%s' % (title, message))

    def current_path(self):
        return os.path.dirname(self.file_path) if self.file_path else '.'

    def choose_color1(self):
        color = self.color_dialog.getColor(self.line_color, u'Choose line color',
                                           default=DEFAULT_LINE_COLOR)
        if color:
            self.line_color = color
            Shape.line_color = color
            self.canvas.set_drawing_color(color)
            self.canvas.update()
            self.set_dirty()

    def delete_selected_shape(self):
        shapes = self.canvas.delete_selected()
        if not shapes:
            return
        for shape in shapes:
            self.remove_label(shape)
        self.set_dirty()
        self.status('Deleted %d label(s)' % len(shapes))
        if self.no_shapes():
            for action in self.actions.onShapesPresent:
                action.setEnabled(False)

    def choose_shape_line_color(self):
        selection = self.canvas.selection_snapshot
        if not selection.capabilities.can_edit_single:
            return
        color = self.color_dialog.getColor(self.line_color, u'Choose Line Color',
                                           default=DEFAULT_LINE_COLOR)
        if color:
            selection.active.line_color = color
            self.canvas.update()
            self.set_dirty()

    def choose_shape_fill_color(self):
        selection = self.canvas.selection_snapshot
        if not selection.capabilities.can_edit_single:
            return
        color = self.color_dialog.getColor(self.fill_color, u'Choose Fill Color',
                                           default=DEFAULT_FILL_COLOR)
        if color:
            selection.active.fill_color = color
            self.canvas.update()
            self.set_dirty()

    def copy_shape(self):
        self.canvas.end_move(copy=True)
        self.add_label(self.canvas.selected_shape)
        self.shape_selection_changed(True)
        self.set_dirty()

    def move_shape(self):
        self.canvas.end_move(copy=False)
        self.set_dirty()

    def load_predefined_classes(self, predef_classes_file):
        if os.path.exists(predef_classes_file) is True:
            with open(predef_classes_file, 'r', encoding='utf8') as f:
                for line in f:
                    line = line.strip()
                    if self.label_hist is None:
                        self.label_hist = [line]
                    else:
                        self.label_hist.append(line)

    def load_annotation_by_filename(self, annotation_path):
        if self.file_path is None:
            return False
        if not os.path.isfile(annotation_path):
            return False

        try:
            loaded = self.annotation_workspace.load(
                annotation_path,
                self.file_path,
                self.image_data,
            )
        except AnnotationDocumentError as error:
            self.error_message(
                u'Error opening annotation document',
                u'<b>%s</b>' % error,
            )
            return False

        self.clear_current_labels()
        self.set_format(document_format_name(loaded.annotation_format))
        self.load_annotation_document(loaded.document)
        return True

    def format_shape_for_clipboard(self, shape):
        points = [(p.x(), p.y()) for p in shape.points]
        line_color = shape.line_color.getRgb() if shape.line_color else None
        fill_color = shape.fill_color.getRgb() if shape.fill_color else None
        return shape.label, points, line_color, fill_color, shape.difficult

    def clear_current_labels(self):
        self.items_to_shapes.clear()
        self.shapes_to_items.clear()
        self.label_list.clear()
        self.combo_box.cb.clear()
        self.canvas.load_shapes([])

    def copy_current_bounding_boxes(self):
        selected_shapes = list(self.canvas.selected_shapes)
        if not selected_shapes:
            self.status('No selected labels to copy')
            return

        self.annotation_clipboard = [
            self.format_shape_for_clipboard(shape)
            for shape in selected_shapes
        ]
        self.status('Copied %d label(s)' % len(self.annotation_clipboard))

    def paste_copied_bounding_boxes(self):
        if not self.annotation_clipboard:
            self.status('No copied labels to paste')
            return
        if self.file_path is None:
            return

        pasted_shapes = [
            self.shape_from_annotation(annotation_shape)
            for annotation_shape in self.annotation_clipboard
        ]
        self.canvas.shapes.extend(pasted_shapes)
        for shape in pasted_shapes:
            self.add_label(shape)
        self.canvas.set_selected_shapes(
            pasted_shapes,
            active_shape=pasted_shapes[-1],
        )
        self.shape_selection_changed(True)
        self.set_dirty()

        self.canvas.setFocus(True)
        self.status('Pasted %d label(s)' % len(pasted_shapes))

    def copy_previous_bounding_boxes(self):
        current_index = self.m_img_list.index(self.file_path)
        if current_index - 1 >= 0:
            prev_file_path = self.m_img_list[current_index - 1]
            self.show_bounding_box_from_annotation_file(prev_file_path)
            self.save_file()

    def toggle_paint_labels_option(self):
        for shape in self.canvas.shapes:
            shape.paint_label = self.display_label_option.isChecked()

    def toggle_draw_square(self):
        self.canvas.set_drawing_shape_to_square(self.draw_squares_option.isChecked())

def inverted(color):
    return QColor(*[255 - v for v in color.getRgb()])


def read(filename, default=None):
    try:
        reader = QImageReader(filename)
        reader.setAutoTransform(True)
        return reader.read()
    except:
        return default


def get_main_app(argv=[]):
    """
    Standard boilerplate Qt application code.
    Do everything but app.exec_() -- so that we can test the application in one thread
    """
    app = QApplication(argv)
    app.setApplicationName(__appname__)
    app.setWindowIcon(new_icon("app"))
    # Tzutalin 201705+: Accept extra agruments to change predefined class file
    argparser = argparse.ArgumentParser()
    argparser.add_argument("image_dir", nargs="?")
    argparser.add_argument("class_file",
                           default=os.path.join(os.path.dirname(__file__), "data", "predefined_classes.txt"),
                           nargs="?")
    argparser.add_argument("save_dir", nargs="?")
    args = argparser.parse_args(argv[1:])

    args.image_dir = args.image_dir and os.path.normpath(args.image_dir)
    args.class_file = args.class_file and os.path.normpath(args.class_file)
    args.save_dir = args.save_dir and os.path.normpath(args.save_dir)

    # Usage: labelImg image classFile saveDir
    win = MainWindow(args.image_dir,
                     args.class_file,
                     args.save_dir)
    win.show()
    return app, win


def main():
    """construct main app and run it"""
    app, _win = get_main_app(sys.argv)
    return app.exec_()

if __name__ == '__main__':
    sys.exit(main())
