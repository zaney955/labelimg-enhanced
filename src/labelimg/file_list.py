"""File-list selection, rendering, and rename UI."""

from __future__ import annotations

import os
import re

from PyQt5.QtCore import (
    QEvent,
    QItemSelectionModel,
    QRect,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QPainter, QPalette, QPen
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from labelimg.file_operations import exact_annotation_paths


CURRENT_IMAGE_ROLE = Qt.UserRole + 1
FILE_ANNOTATION_STATE_ROLE = Qt.UserRole + 2
PRESERVED_SELECTION_APPEARANCE_ROLE = Qt.UserRole + 3
FILE_PERSISTENCE_FLAGS_ROLE = Qt.UserRole + 4

INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class FileListWidget(QListWidget):
    openRequested = pyqtSignal()
    itemOpenRequested = pyqtSignal(object)
    renameRequested = pyqtSignal()
    deleteRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._selection_before_press = ()
        self._range_anchor_row = None
        self._pending_double_click_item = None
        self._suppress_next_left_release = False
        self._preserved_selection_timer = QTimer(self)
        self._preserved_selection_timer.setSingleShot(True)
        self._preserved_selection_timer.timeout.connect(
            self._clear_preserved_selection_appearance
        )

    def _set_preserved_selection_appearance(self, paths):
        selected_paths = set(paths)
        for row in range(self.count()):
            item = self.item(row)
            item.setData(
                PRESERVED_SELECTION_APPEARANCE_ROLE,
                item.data(Qt.UserRole) in selected_paths,
            )
        self.viewport().update()

    def _clear_preserved_selection_appearance(self):
        self._preserved_selection_timer.stop()
        self._pending_double_click_item = None
        self._set_preserved_selection_appearance(())

    def _restore_selection_paths(self, paths):
        selected_paths = set(paths)
        self.clearSelection()
        for row in range(self.count()):
            item = self.item(row)
            if item.data(Qt.UserRole) in selected_paths:
                item.setSelected(True)
        self.viewport().update()

    def _clear_left_release_suppression(self):
        self._suppress_next_left_release = False

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride:
            key = event.key()
            modifiers = event.modifiers()
            handled = (
                (key == Qt.Key_A and modifiers == Qt.ControlModifier)
                or (
                    key == Qt.Key_Space
                    and modifiers in (
                        Qt.NoModifier,
                        Qt.ControlModifier,
                    )
                )
                or (
                    key in (
                        Qt.Key_Return,
                        Qt.Key_Enter,
                        Qt.Key_F2,
                    )
                    and modifiers == Qt.NoModifier
                )
                or (
                    key == Qt.Key_Delete
                    and modifiers == Qt.NoModifier
                )
            )
            if handled:
                event.accept()
                return True
        return super().event(event)

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if event.button() == Qt.RightButton:
            self._clear_preserved_selection_appearance()
            self.setFocus(Qt.MouseFocusReason)
            if item is None:
                self.clearSelection()
                self.setCurrentItem(None)
            elif not item.isSelected():
                self.clearSelection()
                item.setSelected(True)
                self._range_anchor_row = self.row(item)
                self.selectionModel().setCurrentIndex(
                    self.indexFromItem(item),
                    QItemSelectionModel.NoUpdate,
                )
            else:
                self._range_anchor_row = self.row(item)
                self.selectionModel().setCurrentIndex(
                    self.indexFromItem(item),
                    QItemSelectionModel.NoUpdate,
                )
            event.accept()
            self.viewport().update()
            return

        if event.button() == Qt.LeftButton:
            plain_click = (
                item is not None
                and event.modifiers() == Qt.NoModifier
            )
            continues_double_click = (
                plain_click
                and item is self._pending_double_click_item
                and self._preserved_selection_timer.isActive()
            )
            if plain_click and not continues_double_click:
                self._selection_before_press = tuple(
                    selected_item.data(Qt.UserRole)
                    for selected_item in self.selectedItems()
                )
                self._set_preserved_selection_appearance(
                    self._selection_before_press
                )
                self._pending_double_click_item = item
                self._preserved_selection_timer.start(
                    QApplication.doubleClickInterval()
                )
            elif not plain_click:
                self._clear_preserved_selection_appearance()
            if item is None:
                self.clearSelection()
                self.setCurrentItem(None)
                self._range_anchor_row = None
            elif event.modifiers() & Qt.ShiftModifier:
                row = self.row(item)
                anchor = (
                    self._range_anchor_row
                    if self._range_anchor_row is not None
                    else (
                        self.currentRow()
                        if self.currentRow() >= 0
                        else row
                    )
                )
                self.clearSelection()
                for selected_row in range(
                    min(anchor, row),
                    max(anchor, row) + 1,
                ):
                    self.item(selected_row).setSelected(True)
                self.selectionModel().setCurrentIndex(
                    self.indexFromItem(item),
                    QItemSelectionModel.NoUpdate,
                )
                event.accept()
                self.viewport().update()
                return
            else:
                self._range_anchor_row = self.row(item)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.LeftButton
            and self._suppress_next_left_release
        ):
            self._suppress_next_left_release = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        clicked_item = self.itemAt(event.pos())
        preserved_paths = self._selection_before_press
        self._clear_preserved_selection_appearance()
        self._suppress_next_left_release = True
        QTimer.singleShot(0, self._clear_left_release_suppression)
        super().mouseDoubleClickEvent(event)
        self._restore_selection_paths(preserved_paths)
        if clicked_item is not None and event.button() == Qt.LeftButton:
            self.itemOpenRequested.emit(clicked_item)
        QTimer.singleShot(
            0,
            lambda paths=preserved_paths: self._restore_selection_paths(
                paths
            ),
        )

    def keyPressEvent(self, event):
        self._clear_preserved_selection_appearance()
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key_A and modifiers == Qt.ControlModifier:
            self.selectAll()
            if self.currentRow() >= 0:
                self._range_anchor_row = self.currentRow()
            event.accept()
            return
        if key == Qt.Key_Space:
            if modifiers == Qt.ControlModifier:
                index = self.currentIndex()
                if index.isValid():
                    self.selectionModel().select(
                        index,
                        QItemSelectionModel.Toggle
                        | QItemSelectionModel.Rows,
                    )
            event.accept()
            return
        if (
            key in (Qt.Key_Return, Qt.Key_Enter)
            and modifiers == Qt.NoModifier
        ):
            if len(self.selectedItems()) == 1:
                self.openRequested.emit()
            event.accept()
            return
        if key == Qt.Key_F2 and modifiers == Qt.NoModifier:
            if self.selectedItems():
                self.renameRequested.emit()
            event.accept()
            return
        if key == Qt.Key_Delete and modifiers == Qt.NoModifier:
            if self.selectedItems():
                self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)
        if (
            key in (
                Qt.Key_Up,
                Qt.Key_Down,
                Qt.Key_Home,
                Qt.Key_End,
                Qt.Key_PageUp,
                Qt.Key_PageDown,
            )
            and not (modifiers & Qt.ShiftModifier)
            and self.currentRow() >= 0
        ):
            self._range_anchor_row = self.currentRow()


class FileListItemDelegate(QStyledItemDelegate):
    selection_background_alpha = 28
    hover_background_alpha = 45

    def paint(self, painter, option, index):
        paint_option = QStyleOptionViewItem(option)
        row_rect = self._row_rect(option)
        selected = (
            bool(option.state & QStyle.State_Selected)
            or bool(index.data(PRESERVED_SELECTION_APPEARANCE_ROLE))
        )
        focused = (
            option.widget is not None
            and option.widget.hasFocus()
            and bool(option.state & QStyle.State_HasFocus)
        )
        current_image = bool(index.data(CURRENT_IMAGE_ROLE))
        hovered = bool(option.state & QStyle.State_MouseOver)

        palette = (
            option.widget.palette()
            if option.widget is not None
            else option.palette
        )
        accent = palette.color(palette.Highlight)
        if selected:
            background = QColor(accent)
            background.setAlpha(self.selection_background_alpha)
            painter.fillRect(row_rect, background)
            paint_option.state &= ~QStyle.State_Selected
            paint_option.state &= ~QStyle.State_HasFocus
            paint_option.state &= ~QStyle.State_MouseOver
        elif hovered:
            background = QColor(palette.color(QPalette.Mid))
            background.setAlpha(self.hover_background_alpha)
            painter.fillRect(row_rect, background)
            paint_option.state &= ~QStyle.State_MouseOver
        if current_image:
            paint_option.font.setBold(True)

        paint_option.rect = row_rect
        super().paint(painter, paint_option, index)

        if focused:
            painter.save()
            pen = QPen(accent)
            pen.setStyle(Qt.DotLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(row_rect.adjusted(1, 1, -2, -2))
            painter.restore()

    @staticmethod
    def _row_rect(option):
        row_rect = QRect(option.rect)
        if option.widget is not None and hasattr(
            option.widget,
            "viewport",
        ):
            row_rect.setRight(
                min(
                    row_rect.right(),
                    option.widget.viewport().width() - 1,
                )
            )
        return row_rect


class BatchRenameDialog(QDialog):
    def __init__(
        self,
        image_paths,
        display_root,
        save_dir=None,
        parent=None,
    ):
        super().__init__(parent)
        self.image_paths = tuple(image_paths)
        self.display_root = display_root
        self.save_dir = save_dir
        self._mapping = {}
        self.setWindowTitle("批量重命名")
        self.resize(760, 480)

        self.prefix_edit = QLineEdit()
        self.template_edit = QLineEdit("{原名}")
        self.suffix_edit = QLineEdit()
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 999999999)
        self.start_spin.setValue(1)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 12)
        self.width_spin.setValue(4)

        form = QFormLayout()
        form.addRow("统一前缀", self.prefix_edit)
        form.addRow("名称模板", self.template_edit)
        form.addRow("统一后缀", self.suffix_edit)
        numbers = QHBoxLayout()
        numbers.addWidget(QLabel("起始序号"))
        numbers.addWidget(self.start_spin)
        numbers.addSpacing(16)
        numbers.addWidget(QLabel("编号位数"))
        numbers.addWidget(self.width_spin)
        numbers.addStretch(1)
        form.addRow("序号", numbers)

        help_label = QLabel(
            "模板支持 {原名} 和 {序号}；文件目录与扩展名保持不变。"
        )
        help_label.setWordWrap(True)

        self.preview = QTableWidget(0, 3)
        self.preview.setHorizontalHeaderLabels(
            ("原路径", "新文件名", "校验")
        )
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview.setSelectionMode(QAbstractItemView.NoSelection)
        header = self.preview.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.buttons.button(QDialogButtonBox.Ok).setText("重命名")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(help_label)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.message)
        layout.addWidget(self.buttons)

        for widget in (
            self.prefix_edit,
            self.template_edit,
            self.suffix_edit,
        ):
            widget.textChanged.connect(self.update_preview)
        self.start_spin.valueChanged.connect(self.update_preview)
        self.width_spin.valueChanged.connect(self.update_preview)
        self.update_preview()

    @property
    def mapping(self):
        return dict(self._mapping)

    def update_preview(self):
        prefix = self.prefix_edit.text()
        template = self.template_edit.text()
        suffix = self.suffix_edit.text()
        start = self.start_spin.value()
        width = self.width_spin.value()
        mapping = {}
        row_errors = {}
        self.preview.setRowCount(len(self.image_paths))

        unknown_template = _has_unknown_template_tokens(template)
        for row, source in enumerate(self.image_paths):
            stem, extension = os.path.splitext(os.path.basename(source))
            sequence = str(start + row).zfill(width)
            expanded = (
                template
                .replace("{原名}", stem)
                .replace("{序号}", sequence)
            )
            new_stem = prefix + expanded + suffix
            target = os.path.join(
                os.path.dirname(source),
                new_stem + extension,
            )
            mapping[source] = target
            error = (
                "模板包含未知占位符"
                if unknown_template
                else validate_base_name(new_stem, target)
            )
            if error:
                row_errors[row] = error
            self.preview.setItem(
                row,
                0,
                QTableWidgetItem(
                    _relative_or_absolute(source, self.display_root)
                ),
            )
            self.preview.setItem(
                row,
                1,
                QTableWidgetItem(os.path.basename(target)),
            )
            self.preview.setItem(
                row,
                2,
                QTableWidgetItem(error or "可用"),
            )

        mapping_errors = validate_rename_mapping(
            mapping,
            self.save_dir,
        )
        for row, source in enumerate(self.image_paths):
            error = mapping_errors.get(source)
            if error:
                row_errors[row] = error
                self.preview.item(row, 2).setText(error)

        changed = any(
            source != target
            for source, target in mapping.items()
        )
        valid = not row_errors and changed
        self._mapping = mapping if valid else {}
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(valid)
        if row_errors:
            self.message.setText(
                "请先解决预览中的命名冲突或非法名称。"
            )
        elif not changed:
            self.message.setText("新名称与原名称完全相同。")
        else:
            self.message.setText(
                "将按当前预览同步重命名图片及关联标注。"
            )


def validate_base_name(base_name, full_path=None):
    if not base_name:
        return "名称不能为空"
    if INVALID_FILENAME_CHARACTERS.search(base_name):
        return "名称包含非法字符"
    if base_name.endswith((" ", ".")):
        return "名称不能以空格或句点结尾"
    reserved_key = base_name.split(".", 1)[0].upper()
    if reserved_key in WINDOWS_RESERVED_NAMES:
        return "名称是 Windows 保留名称"
    if full_path is not None and os.name == "nt" and len(full_path) >= 260:
        return "完整路径过长"
    return ""


def validate_rename_mapping(mapping, save_dir=None):
    errors = {}
    target_owners = {}
    source_keys = {
        os.path.normcase(os.path.abspath(source))
        for source in mapping
    }
    annotation_source_keys = set()
    for source in mapping:
        annotation_source_keys.update(
            os.path.normcase(os.path.abspath(path))
            for path in exact_annotation_paths(source, save_dir)
            if os.path.exists(path)
        )

    for source, target in mapping.items():
        target_key = os.path.normcase(os.path.abspath(target))
        owner = target_owners.get(target_key)
        if owner is not None and owner != source:
            errors[source] = "新名称与另一选中项重复"
            errors[owner] = "新名称与另一选中项重复"
        target_owners[target_key] = source
        if os.path.exists(target) and target_key not in source_keys:
            errors[source] = "目标图片已存在"

        old_stem = os.path.splitext(os.path.basename(source))[0]
        new_stem = os.path.splitext(os.path.basename(target))[0]
        for annotation_source in exact_annotation_paths(
            source,
            save_dir,
        ):
            if not os.path.exists(annotation_source):
                continue
            annotation_target = os.path.join(
                os.path.dirname(annotation_source),
                new_stem + os.path.splitext(annotation_source)[1],
            )
            target_annotation_key = os.path.normcase(
                os.path.abspath(annotation_target)
            )
            if (
                os.path.exists(annotation_target)
                and target_annotation_key not in annotation_source_keys
            ):
                errors[source] = "关联标注目标已存在"
            if old_stem.casefold() == new_stem.casefold():
                continue
    return errors


def _has_unknown_template_tokens(template):
    stripped = (
        template
        .replace("{原名}", "")
        .replace("{序号}", "")
    )
    return "{" in stripped or "}" in stripped


def _relative_or_absolute(path, root):
    if not root:
        return path
    try:
        relative = os.path.relpath(path, root)
    except ValueError:
        return path
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return path
    return relative
