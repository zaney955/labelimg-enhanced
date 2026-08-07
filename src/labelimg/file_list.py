"""File-list selection, rendering, and rename UI."""

from __future__ import annotations

import os
import re
from functools import cmp_to_key

from PyQt5.QtCore import (
    QEvent,
    QItemSelectionModel,
    QPointF,
    QRect,
    QRectF,
    QSignalBlocker,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
    QActionGroup,
)

from labelimg.file_operations import exact_annotation_paths
from labelimg.i18n import language_changed, localize_dialog_buttons, tr


CURRENT_IMAGE_ROLE = Qt.UserRole + 1
FILE_ANNOTATION_STATE_ROLE = Qt.UserRole + 2
PRESERVED_SELECTION_APPEARANCE_ROLE = Qt.UserRole + 3
FILE_PERSISTENCE_FLAGS_ROLE = Qt.UserRole + 4
FILE_REVIEW_STATE_ROLE = Qt.UserRole + 5
FILE_QUALITY_FINDINGS_ROLE = Qt.UserRole + 6

INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _quality_value(finding, field):
    if isinstance(finding, dict):
        return finding.get(field)
    if hasattr(finding, field):
        return getattr(finding, field)
    return finding if field == "code" else None


def portable_logical_compare(left_name, right_name):
    """Compare text using case-insensitive natural numeric chunks."""
    left_parts = re.split(r"(\d+)", str(left_name).casefold())
    right_parts = re.split(r"(\d+)", str(right_name).casefold())
    for left_part, right_part in zip(left_parts, right_parts):
        left_is_number = left_part.isdigit()
        right_is_number = right_part.isdigit()
        if left_is_number and right_is_number:
            left_number = int(left_part)
            right_number = int(right_part)
            if left_number != right_number:
                return (left_number > right_number) - (
                    left_number < right_number
                )
            if len(left_part) != len(right_part):
                return (len(right_part) > len(left_part)) - (
                    len(right_part) < len(left_part)
                )
        elif left_is_number != right_is_number:
            return -1 if left_is_number else 1
        elif left_part != right_part:
            return (left_part > right_part) - (
                left_part < right_part
            )
    return (len(left_parts) > len(right_parts)) - (
        len(left_parts) < len(right_parts)
    )


def _relative_path_parts(path, root):
    absolute = os.path.abspath(path)
    if root:
        try:
            relative = os.path.relpath(absolute, os.path.abspath(root))
        except ValueError:
            relative = os.path.basename(absolute)
    else:
        relative = os.path.basename(absolute)
    normalized = relative.replace("\\", "/")
    return tuple(part for part in normalized.split("/") if part)


def compare_relative_image_paths(left_path, right_path, root=None):
    """Keep relative directories grouped, then naturally order names."""
    left_parts = _relative_path_parts(left_path, root)
    right_parts = _relative_path_parts(right_path, root)
    left_dirs, left_name = left_parts[:-1], left_parts[-1:]
    right_dirs, right_name = right_parts[:-1], right_parts[-1:]
    for left_part, right_part in zip(left_dirs, right_dirs):
        comparison = portable_logical_compare(left_part, right_part)
        if comparison:
            return comparison
    if len(left_dirs) != len(right_dirs):
        return (len(left_dirs) > len(right_dirs)) - (
            len(left_dirs) < len(right_dirs)
        )
    comparison = portable_logical_compare(
        left_name[0] if left_name else "",
        right_name[0] if right_name else "",
    )
    if comparison:
        return comparison
    left_key = os.path.abspath(left_path).casefold()
    right_key = os.path.abspath(right_path).casefold()
    return (left_key > right_key) - (left_key < right_key)


class FileListViewState(object):
    SORT_KEYS = ("name", "modified", "annotation", "review")
    ANNOTATION_ORDER = {"unannotated": 0, "annotated": 1}
    REVIEW_ORDER = {"unreviewed": 0, "questioned": 1, "verified": 2}

    def __init__(self, sort_key="name", descending=False):
        self.sort_key = (
            sort_key if sort_key in self.SORT_KEYS else "name"
        )
        self.descending = bool(descending)
        self.reset_filter()

    @property
    def filter_active(self):
        return bool(
            self.text_filter
            or self.annotation_filter != "all"
            or self.review_filter != "all"
            or self.alert_filter != "all"
            or self.quality_filter != "all"
        )

    def set_filter(
        self,
        text="",
        annotation="all",
        review="all",
        alert="all",
        quality="all",
    ):
        self.text_filter = str(text).strip()
        self.annotation_filter = annotation
        self.review_filter = review
        self.alert_filter = alert
        self.quality_filter = quality

    def reset_filter(self):
        self.text_filter = ""
        self.annotation_filter = "all"
        self.review_filter = "all"
        self.alert_filter = "all"
        self.quality_filter = "all"

    def ordered_paths(
        self,
        paths,
        root,
        annotation_state_for,
        review_state_for,
        modified_time_for=os.path.getmtime,
    ):
        def path_compare(left, right):
            return compare_relative_image_paths(left, right, root)

        def primary(path):
            if self.sort_key == "annotation":
                return self.ANNOTATION_ORDER.get(
                    annotation_state_for(path), -1
                )
            if self.sort_key == "review":
                return self.REVIEW_ORDER.get(review_state_for(path), -1)
            if self.sort_key == "modified":
                try:
                    return float(modified_time_for(path))
                except (OSError, TypeError, ValueError):
                    return float("-inf")
            return 0

        def compare(left, right):
            if self.sort_key == "name":
                comparison = path_compare(left, right)
                return -comparison if self.descending else comparison
            left_primary = primary(left)
            right_primary = primary(right)
            comparison = (left_primary > right_primary) - (
                left_primary < right_primary
            )
            if comparison:
                return -comparison if self.descending else comparison
            return path_compare(left, right)

        return sorted(list(paths), key=cmp_to_key(compare))

    def matches(
        self,
        path,
        root,
        annotation_state_for,
        review_state_for,
        persistence_flags_for,
        quality_findings_for=lambda _path: (),
    ):
        if self.text_filter:
            parts = _relative_path_parts(path, root)
            display_path = "/".join(parts).casefold()
            query = self.text_filter.replace("\\", "/").casefold()
            if query not in display_path:
                return False
        if (
            self.annotation_filter != "all"
            and annotation_state_for(path) != self.annotation_filter
        ):
            return False
        if (
            self.review_filter != "all"
            and review_state_for(path) != self.review_filter
        ):
            return False
        flags = tuple(persistence_flags_for(path) or ())
        if self.alert_filter == "any" and not flags:
            return False
        if self.alert_filter == "none" and flags:
            return False
        quality = tuple(quality_findings_for(path) or ())
        if self.quality_filter == "issues" and not quality:
            return False
        if self.quality_filter == "passed" and quality:
            return False
        if self.quality_filter in ("error", "warning") and not any(
            _quality_value(item, "severity") == self.quality_filter
            for item in quality
        ):
            return False
        if self.quality_filter not in (
            "all", "issues", "passed", "error", "warning"
        ) and not any(
            _quality_value(item, "code") == self.quality_filter
            for item in quality
        ):
            return False
        return True

    def visible_paths(
        self,
        paths,
        root,
        annotation_state_for,
        review_state_for,
        persistence_flags_for,
        quality_findings_for=lambda _path: (),
    ):
        return [
            path
            for path in paths
            if self.matches(
                path,
                root,
                annotation_state_for,
                review_state_for,
                persistence_flags_for,
                quality_findings_for,
            )
        ]


class FileListControlButton(QToolButton):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.active = False
        self.descending = False
        self._hovered = False
        self.setFixedSize(28, 28)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_active(self, active):
        active = bool(active)
        if self.active != active:
            self.active = active
            self.update()

    def set_descending(self, descending):
        self.descending = bool(descending)
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        palette = self.palette()
        accent = palette.color(QPalette.Highlight)
        if self._hovered or self.isDown():
            background = QColor(
                palette.color(
                    QPalette.Highlight
                    if self.isDown()
                    else QPalette.Mid
                )
            )
            background.setAlpha(55 if self.isDown() else 45)
            painter.setPen(Qt.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        if self.active:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(accent, 1.2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        color = (
            palette.color(QPalette.Disabled, QPalette.ButtonText)
            if not self.isEnabled()
            else (
                accent
                if self.active
                else palette.color(QPalette.ButtonText)
            )
        )
        painter.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        if self.kind == "filter":
            path = QPainterPath()
            path.moveTo(7, 8)
            path.lineTo(21, 8)
            path.lineTo(16, 14)
            path.lineTo(16, 20)
            path.lineTo(12, 18)
            path.lineTo(12, 14)
            path.closeSubpath()
            painter.drawPath(path)
        else:
            painter.drawLine(7, 9, 15, 9)
            painter.drawLine(7, 14, 13, 14)
            painter.drawLine(7, 19, 11, 19)
            top, bottom = (19, 8) if self.descending else (8, 19)
            painter.drawLine(20, top, 20, bottom)
            arrow_y = bottom
            arrow_step = -3 if self.descending else 3
            painter.drawLine(20, arrow_y, 17, arrow_y - arrow_step)
            painter.drawLine(20, arrow_y, 23, arrow_y - arrow_step)
        if self.active:
            painter.setPen(Qt.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(QPointF(23, 5), 2, 2)
        if self.hasFocus():
            focus = QPen(palette.color(QPalette.Text), 1, Qt.DotLine)
            painter.setPen(focus)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(3, 3, -3, -3), 3, 3)
        painter.end()


class FileListFilterPanel(QFrame):
    filterChanged = pyqtSignal(str, str, str, str, str)
    clearRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("fileListFilterPanel")
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.title_label = QLabel()
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)
        self.text_edit = QLineEdit()
        self.text_edit.setClearButtonEnabled(True)
        layout.addWidget(self.text_edit)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.annotation_combo = QComboBox()
        self._add_options(self.annotation_combo, (
            ("common.all", "all"),
            ("state.unannotated", "unannotated"),
            ("state.annotated", "annotated"),
        ))
        self.review_combo = QComboBox()
        self._add_options(self.review_combo, (
            ("common.all", "all"),
            ("state.unreviewed", "unreviewed"),
            ("state.questioned", "questioned"),
            ("state.verified", "verified"),
        ))
        self.alert_combo = QComboBox()
        self._add_options(self.alert_combo, (
            ("common.all", "all"),
            ("fileFilter.none", "none"),
            ("fileFilter.any", "any"),
        ))
        self.quality_combo = QComboBox()
        self._add_options(self.quality_combo, (
            ("common.all", "all"),
            ("fileFilter.qualityIssues", "issues"),
            ("fileFilter.qualityPassed", "passed"),
            ("fileFilter.qualityError", "error"),
            ("fileFilter.qualityWarning", "warning"),
            ("quality.unreadable", "unreadable"),
            ("quality.lowResolution", "low_resolution"),
            ("quality.aspectAnomaly", "aspect_anomaly"),
            ("quality.blur", "blur"),
            ("quality.dark", "dark"),
            ("quality.overexposed", "overexposed"),
        ))
        self.annotation_label = QLabel()
        self.review_label = QLabel()
        self.alert_label = QLabel()
        self.quality_label = QLabel()
        form.addRow(self.annotation_label, self.annotation_combo)
        form.addRow(self.review_label, self.review_combo)
        form.addRow(self.alert_label, self.alert_combo)
        form.addRow(self.quality_label, self.quality_combo)
        self.form = form
        layout.addLayout(form)
        self.clear_button = QPushButton()
        layout.addWidget(self.clear_button)
        self.text_edit.textChanged.connect(self._emit_filter)
        self.annotation_combo.currentIndexChanged.connect(self._emit_filter)
        self.review_combo.currentIndexChanged.connect(self._emit_filter)
        self.alert_combo.currentIndexChanged.connect(self._emit_filter)
        self.quality_combo.currentIndexChanged.connect(self._emit_filter)
        self.clear_button.clicked.connect(self.clearRequested)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    @staticmethod
    def _add_options(combo, options):
        for message_id, value in options:
            combo.addItem(tr(message_id), value)
            combo.setItemData(combo.count() - 1, message_id, Qt.UserRole + 1)

    def retranslate_ui(self, _language=None):
        self.title_label.setText(tr("fileFilter.title"))
        self.text_edit.setPlaceholderText(tr("fileFilter.placeholder"))
        self.annotation_label.setText(tr("fileFilter.annotation"))
        self.review_label.setText(tr("fileFilter.review"))
        self.alert_label.setText(tr("fileFilter.persistence"))
        self.quality_label.setText(tr("fileFilter.quality"))
        self.clear_button.setText(tr("fileFilter.clearAll"))
        for combo in (
            self.annotation_combo,
            self.review_combo,
            self.alert_combo,
            self.quality_combo,
        ):
            for index in range(combo.count()):
                combo.setItemText(index, tr(combo.itemData(index, Qt.UserRole + 1)))

    def _emit_filter(self, _value=None):
        self.filterChanged.emit(
            self.text_edit.text(),
            self.annotation_combo.currentData(),
            self.review_combo.currentData(),
            self.alert_combo.currentData(),
            self.quality_combo.currentData(),
        )

    def set_filter(self, text, annotation, review, alert, quality="all"):
        blockers = [
            QSignalBlocker(self.text_edit),
            QSignalBlocker(self.annotation_combo),
            QSignalBlocker(self.review_combo),
            QSignalBlocker(self.alert_combo),
            QSignalBlocker(self.quality_combo),
        ]
        self.text_edit.setText(text)
        for combo, value in (
            (self.annotation_combo, annotation),
            (self.review_combo, review),
            (self.alert_combo, alert),
            (self.quality_combo, quality),
        ):
            index = combo.findData(value)
            combo.setCurrentIndex(max(0, index))
        del blockers

    def show_for(self, button):
        self.adjustSize()
        position = button.mapToGlobal(button.rect().bottomRight())
        x = position.x() - self.width()
        y = position.y() + 2
        screen = QApplication.screenAt(position)
        if screen is not None:
            available = screen.availableGeometry()
            x = max(
                available.left(),
                min(x, available.right() - self.width() + 1),
            )
            y = max(
                available.top(),
                min(y, available.bottom() - self.height() + 1),
            )
        self.move(x, y)
        self.show()
        self.raise_()
        self.text_edit.setFocus(Qt.PopupFocusReason)
        self.text_edit.selectAll()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)


class FileListControlBar(QWidget):
    viewChanged = pyqtSignal()

    SORT_LABEL_IDS = {
        "name": "fileSort.name",
        "modified": "fileSort.modified",
        "annotation": "fileSort.annotation",
        "review": "fileSort.review",
    }

    def __init__(self, sort_key="name", descending=False, parent=None):
        super().__init__(parent)
        self.state = FileListViewState(sort_key, descending)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        layout.addStretch(1)
        self.sort_button = FileListControlButton("sort", self)
        self.filter_button = FileListControlButton("filter", self)
        self.sort_button.installEventFilter(self)
        self.filter_button.installEventFilter(self)
        layout.addWidget(self.sort_button)
        layout.addWidget(self.filter_button)
        self.sort_menu = QMenu(self.sort_button)
        self.sort_group = QActionGroup(self.sort_menu)
        self.sort_group.setExclusive(True)
        self.sort_actions = {}
        for key in FileListViewState.SORT_KEYS:
            action = self.sort_menu.addAction("")
            action.setCheckable(True)
            action.setData(key)
            self.sort_group.addAction(action)
            action.triggered.connect(
                lambda checked=False, value=key: self._set_sort_key(value)
            )
            self.sort_actions[key] = action
        self.sort_menu.addSeparator()
        self.direction_group = QActionGroup(self.sort_menu)
        self.direction_group.setExclusive(True)
        self.ascending_action = self.sort_menu.addAction("")
        self.ascending_action.setCheckable(True)
        self.descending_action = self.sort_menu.addAction("")
        self.descending_action.setCheckable(True)
        self.direction_group.addAction(self.ascending_action)
        self.direction_group.addAction(self.descending_action)
        self.ascending_action.triggered.connect(
            lambda checked=False: self._set_descending(False)
        )
        self.descending_action.triggered.connect(
            lambda checked=False: self._set_descending(True)
        )
        self.sort_menu.addSeparator()
        self.reset_sort_action = self.sort_menu.addAction("")
        self.reset_sort_action.triggered.connect(self.reset_sort)
        self.sort_button.setMenu(self.sort_menu)
        self.sort_button.setPopupMode(QToolButton.InstantPopup)
        self.filter_panel = FileListFilterPanel(self)
        self.filter_panel.filterChanged.connect(self._set_filter)
        self.filter_panel.clearRequested.connect(self.clear_filters)
        self.filter_button.clicked.connect(self.show_filter_panel)
        self.set_workspace_available(False)
        self._update_sort_presentation()
        self._update_filter_presentation()
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def retranslate_ui(self, _language=None):
        self.sort_button.setAccessibleName(tr("fileSort.sort"))
        self.filter_button.setAccessibleName(tr("fileSort.filter"))
        for key, action in self.sort_actions.items():
            action.setText(tr(self.SORT_LABEL_IDS[key]))
        self.ascending_action.setText(tr("fileSort.ascending"))
        self.descending_action.setText(tr("fileSort.descending"))
        self.reset_sort_action.setText(tr("fileSort.reset"))
        self.filter_panel.retranslate_ui()
        self._update_sort_presentation()
        self._update_filter_presentation()

    def set_workspace_available(self, available):
        self.filter_button.setEnabled(bool(available))
        if not available:
            self.filter_panel.hide()

    def eventFilter(self, watched, event):
        if watched in (self.sort_button, self.filter_button):
            if (
                event.type() in (
                    QEvent.ShortcutOverride,
                    QEvent.KeyPress,
                )
                and event.key() == Qt.Key_F
                and event.modifiers() == Qt.ControlModifier
            ):
                event.accept()
                if event.type() == QEvent.KeyPress:
                    self.show_filter_panel()
                return True
        return super().eventFilter(watched, event)

    def _set_sort_key(self, key):
        if key == self.state.sort_key:
            self._update_sort_presentation()
            self.viewChanged.emit()
            return
        self.state.sort_key = key
        self._update_sort_presentation()
        self.viewChanged.emit()

    def _set_descending(self, descending):
        descending = bool(descending)
        if descending == self.state.descending:
            self._update_sort_presentation()
            return
        self.state.descending = descending
        self._update_sort_presentation()
        self.viewChanged.emit()

    def reset_sort(self, _checked=False):
        changed = self.state.sort_key != "name" or self.state.descending
        self.state.sort_key = "name"
        self.state.descending = False
        self._update_sort_presentation()
        if changed:
            self.viewChanged.emit()

    def _update_sort_presentation(self):
        self.sort_actions[self.state.sort_key].setChecked(True)
        self.ascending_action.setChecked(not self.state.descending)
        self.descending_action.setChecked(self.state.descending)
        self.sort_button.set_descending(self.state.descending)
        direction = tr(
            "fileSort.descending"
            if self.state.descending
            else "fileSort.ascending"
        )
        self.sort_button.setToolTip(
            tr(
                "fileSort.tooltip",
                key=tr(self.SORT_LABEL_IDS[self.state.sort_key]),
                direction=direction,
            )
        )

    def _set_filter(self, text, annotation, review, alert, quality="all"):
        before = (
            self.state.text_filter,
            self.state.annotation_filter,
            self.state.review_filter,
            self.state.alert_filter,
            self.state.quality_filter,
        )
        self.state.set_filter(text, annotation, review, alert, quality)
        after = (
            self.state.text_filter,
            self.state.annotation_filter,
            self.state.review_filter,
            self.state.alert_filter,
            self.state.quality_filter,
        )
        self._update_filter_presentation()
        if before != after:
            self.viewChanged.emit()

    def clear_filters(self, _checked=False, emit=True):
        changed = self.state.filter_active
        self.state.reset_filter()
        self.filter_panel.set_filter("", "all", "all", "all", "all")
        self._update_filter_presentation()
        if changed and emit:
            self.viewChanged.emit()

    def _update_filter_presentation(self):
        self.filter_button.set_active(self.state.filter_active)
        if not self.state.filter_active:
            self.filter_button.setToolTip(tr("fileFilter.disabled"))
            return
        labels = []
        if self.state.text_filter:
            labels.append(tr("fileFilter.pathContains", text=self.state.text_filter))
        labels.append({
            "all": "common.all",
            "unannotated": "state.unannotated",
            "annotated": "state.annotated",
        }[self.state.annotation_filter])
        labels[-1] = tr("fileFilter.annotationValue", value=tr(labels[-1]))
        labels.append({
            "all": "common.all",
            "unreviewed": "state.unreviewed",
            "questioned": "state.questioned",
            "verified": "state.verified",
        }[self.state.review_filter])
        labels[-1] = tr("fileFilter.reviewValue", value=tr(labels[-1]))
        labels.append({
            "all": "common.all",
            "none": "fileFilter.none",
            "any": "fileFilter.any",
        }[self.state.alert_filter])
        labels[-1] = tr("fileFilter.alertValue", value=tr(labels[-1]))
        labels.append({
            "all": "common.all",
            "issues": "fileFilter.qualityIssues",
            "passed": "fileFilter.qualityPassed",
            "error": "fileFilter.qualityError",
            "warning": "fileFilter.qualityWarning",
            "unreadable": "quality.unreadable",
            "low_resolution": "quality.lowResolution",
            "aspect_anomaly": "quality.aspectAnomaly",
            "blur": "quality.blur",
            "dark": "quality.dark",
            "overexposed": "quality.overexposed",
        }[self.state.quality_filter])
        labels[-1] = tr("fileFilter.qualityValue", value=tr(labels[-1]))
        self.filter_button.setToolTip(
            tr("fileFilter.tooltip", details=" · ".join(labels))
        )

    def show_filter_panel(self, _checked=False):
        if not self.filter_button.isEnabled():
            return
        if self.filter_panel.isVisible():
            self.filter_panel.hide()
            return
        self.filter_panel.show_for(self.filter_button)


class FileListWidget(QListWidget):
    openRequested = pyqtSignal()
    itemOpenRequested = pyqtSignal(object)
    renameRequested = pyqtSignal()
    deleteRequested = pyqtSignal()
    filterRequested = pyqtSignal()

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

    def visible_items(self):
        return [
            self.item(row)
            for row in range(self.count())
            if not self.item(row).isHidden()
        ]

    def select_all_visible(self):
        self.clearSelection()
        for item in self.visible_items():
            item.setSelected(True)
        self.viewport().update()

    def invert_visible_selection(self):
        selected_visible = [
            item for item in self.visible_items() if item.isSelected()
        ]
        self.clearSelection()
        for item in self.visible_items():
            if item not in selected_visible:
                item.setSelected(True)
        self.viewport().update()

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride:
            key = event.key()
            modifiers = event.modifiers()
            handled = (
                (key == Qt.Key_A and modifiers == Qt.ControlModifier)
                or (key == Qt.Key_F and modifiers == Qt.ControlModifier)
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

    def tooltip_at(self, point):
        item = self.itemAt(point)
        if item is None:
            return ""
        delegate = self.itemDelegate()
        if not isinstance(delegate, FileListItemDelegate):
            return item.toolTip()
        layout = delegate.row_layout(self.visualItemRect(item))
        if layout["annotation"].contains(point):
            return tr(
                "state.annotated"
                if item.data(FILE_ANNOTATION_STATE_ROLE) == "annotated"
                else "state.unannotated"
            )
        if layout["review"].contains(point):
            message_id = {
                "questioned": "state.questioned",
                "verified": "state.verified",
                "unreviewed": "state.unreviewed",
            }.get(item.data(FILE_REVIEW_STATE_ROLE), "state.unreviewed")
            return tr(message_id)
        if layout["alert"].contains(point):
            labels = {
                "dirty": "state.dirty",
                "conflict": "state.conflict",
                "ambiguous": "state.ambiguous",
                "degraded": "state.degraded",
            }
            return "\n".join(
                tr(labels[flag])
                for flag in item.data(FILE_PERSISTENCE_FLAGS_ROLE) or ()
                if flag in labels
            )
        if layout["quality"].contains(point):
            return "\n".join(
                str(_quality_value(value, "explanation") or value)
                for value in item.data(FILE_QUALITY_FINDINGS_ROLE) or ()
            )
        if layout["name"].contains(point):
            return str(item.data(Qt.UserRole) or item.text())
        return ""

    def viewportEvent(self, event):
        if event.type() == QEvent.ToolTip:
            tooltip = self.tooltip_at(event.pos())
            if tooltip:
                QToolTip.showText(event.globalPos(), tooltip, self.viewport())
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)

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
                    selected_item = self.item(selected_row)
                    if not selected_item.isHidden():
                        selected_item.setSelected(True)
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
            self.select_all_visible()
            if self.currentRow() >= 0:
                self._range_anchor_row = self.currentRow()
            event.accept()
            return
        if key == Qt.Key_F and modifiers == Qt.ControlModifier:
            self.filterRequested.emit()
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
    separator_alpha = 45
    status_column_width = 20
    alert_column_width = 20
    status_name_gap = 6
    name_alert_gap = 4
    icon_size = 14
    questioned_color = QColor(217, 145, 0)
    verified_color = QColor(46, 160, 67)
    error_color = QColor(200, 55, 55)

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

        layout = self.row_layout(row_rect)
        paint_option.rect = layout["name"]
        super().paint(painter, paint_option, index)

        self._paint_separator(painter, option, layout)
        self._paint_annotation_indicator(
            painter,
            option,
            layout["annotation"],
            index.data(FILE_ANNOTATION_STATE_ROLE),
        )
        self._paint_review_indicator(
            painter,
            layout["review"],
            index.data(FILE_REVIEW_STATE_ROLE),
        )
        self._paint_alert_indicator(
            painter,
            option,
            layout["alert"],
            index.data(FILE_PERSISTENCE_FLAGS_ROLE) or (),
        )
        self._paint_quality_indicator(
            painter,
            layout["quality"],
            index.data(FILE_QUALITY_FINDINGS_ROLE) or (),
        )

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

    @classmethod
    def row_layout(cls, row_rect):
        row_rect = QRect(row_rect)
        annotation = QRect(
            row_rect.left(),
            row_rect.top(),
            cls.status_column_width,
            row_rect.height(),
        )
        review = QRect(
            annotation.right() + 1,
            row_rect.top(),
            cls.status_column_width,
            row_rect.height(),
        )
        separator_x = review.right() + 1
        alert = QRect(
            row_rect.right() - cls.alert_column_width + 1,
            row_rect.top(),
            cls.alert_column_width,
            row_rect.height(),
        )
        quality = QRect(
            alert.left() - cls.alert_column_width,
            row_rect.top(),
            cls.alert_column_width,
            row_rect.height(),
        )
        name_left = separator_x + 1 + cls.status_name_gap
        name_right = quality.left() - cls.name_alert_gap - 1
        name = QRect(
            name_left,
            row_rect.top(),
            max(0, name_right - name_left + 1),
            row_rect.height(),
        )
        return {
            "row": row_rect,
            "annotation": annotation,
            "review": review,
            "separator_x": separator_x,
            "name": name,
            "quality": quality,
            "alert": alert,
        }

    @classmethod
    def _paint_quality_indicator(cls, painter, column, findings):
        if not findings:
            return
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(cls.questioned_color)
        center = column.center()
        painter.drawEllipse(center, 5, 5)
        painter.setPen(QColor("white"))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(9)
        painter.setFont(font)
        painter.drawText(column, Qt.AlignCenter, "!")
        painter.restore()

    @classmethod
    def highest_alert(cls, flags):
        flags = set(flags)
        for flag in ("degraded", "conflict", "ambiguous", "dirty"):
            if flag in flags:
                return flag
        return None

    @classmethod
    def _icon_rect(cls, column):
        return QRectF(
            column.center().x() - cls.icon_size / 2.0,
            column.center().y() - cls.icon_size / 2.0,
            cls.icon_size,
            cls.icon_size,
        )

    @classmethod
    def _paint_separator(cls, painter, option, layout):
        palette = (
            option.widget.palette()
            if option.widget is not None
            else option.palette
        )
        color = QColor(palette.color(QPalette.Mid))
        color.setAlpha(cls.separator_alpha)
        row = layout["row"]
        painter.fillRect(
            QRect(
                layout["separator_x"],
                row.top() + 4,
                1,
                max(0, row.height() - 8),
            ),
            color,
        )

    @classmethod
    def _paint_annotation_indicator(
        cls,
        painter,
        option,
        column,
        state,
    ):
        if state != "annotated":
            return
        palette = (
            option.widget.palette()
            if option.widget is not None
            else option.palette
        )
        rect = cls._icon_rect(column).adjusted(1.5, 2.0, -1.5, -2.0)
        length = 3.5
        painter.save()
        painter.setPen(QPen(
            palette.color(QPalette.Highlight),
            1.5,
            Qt.SolidLine,
            Qt.RoundCap,
            Qt.RoundJoin,
        ))
        for start, corner, end in (
            (
                QPointF(rect.left() + length, rect.top()),
                rect.topLeft(),
                QPointF(rect.left(), rect.top() + length),
            ),
            (
                QPointF(rect.right() - length, rect.top()),
                rect.topRight(),
                QPointF(rect.right(), rect.top() + length),
            ),
            (
                QPointF(rect.left(), rect.bottom() - length),
                rect.bottomLeft(),
                QPointF(rect.left() + length, rect.bottom()),
            ),
            (
                QPointF(rect.right(), rect.bottom() - length),
                rect.bottomRight(),
                QPointF(rect.right() - length, rect.bottom()),
            ),
        ):
            painter.drawLine(start, corner)
            painter.drawLine(corner, end)
        painter.restore()

    @classmethod
    def _paint_review_indicator(cls, painter, column, state):
        if state not in ("questioned", "verified"):
            return
        color = (
            cls.questioned_color
            if state == "questioned"
            else cls.verified_color
        )
        rect = cls._icon_rect(column).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(color, 1.5))
        painter.drawEllipse(rect)
        if state == "questioned":
            font = painter.font()
            font.setBold(True)
            font.setPixelSize(10)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, "?")
        else:
            path = QPainterPath()
            path.moveTo(rect.left() + 3.0, rect.center().y())
            path.lineTo(rect.center().x() - 0.5, rect.bottom() - 3.0)
            path.lineTo(rect.right() - 2.5, rect.top() + 3.0)
            painter.drawPath(path)
        painter.restore()

    @classmethod
    def _paint_alert_indicator(
        cls,
        painter,
        option,
        column,
        flags,
    ):
        alert = cls.highest_alert(flags)
        if alert is None:
            return
        palette = (
            option.widget.palette()
            if option.widget is not None
            else option.palette
        )
        rect = cls._icon_rect(column).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        if alert == "dirty":
            painter.setPen(Qt.NoPen)
            painter.setBrush(palette.color(QPalette.Highlight))
            painter.drawEllipse(rect.center(), 3.0, 3.0)
        elif alert == "ambiguous":
            painter.setPen(QPen(cls.questioned_color, 1.5, Qt.SolidLine, Qt.RoundCap))
            left = rect.left() + 1.5
            middle = rect.center().x()
            right = rect.right() - 1.5
            painter.drawLine(QPointF(left, rect.top() + 3), QPointF(middle, rect.top() + 3))
            painter.drawLine(QPointF(left, rect.bottom() - 3), QPointF(middle, rect.bottom() - 3))
            painter.drawLine(QPointF(middle, rect.top() + 3), QPointF(right, rect.center().y()))
            painter.drawLine(QPointF(middle, rect.bottom() - 3), QPointF(right, rect.center().y()))
        elif alert == "conflict":
            painter.setPen(QPen(cls.error_color, 1.5))
            painter.drawEllipse(rect)
            cls._paint_exclamation(painter, rect, cls.error_color)
        else:
            painter.setPen(QPen(cls.error_color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            triangle = QPainterPath()
            triangle.moveTo(rect.center().x(), rect.top())
            triangle.lineTo(rect.right(), rect.bottom())
            triangle.lineTo(rect.left(), rect.bottom())
            triangle.closeSubpath()
            painter.drawPath(triangle)
            cls._paint_exclamation(painter, rect, cls.error_color)
        painter.restore()

    @staticmethod
    def _paint_exclamation(painter, rect, color):
        painter.save()
        painter.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap))
        center = rect.center().x()
        painter.drawLine(
            QPointF(center, rect.top() + 3.0),
            QPointF(center, rect.center().y() + 1.0),
        )
        painter.drawPoint(QPointF(center, rect.bottom() - 2.5))
        painter.restore()


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
        self.setWindowTitle(tr("renameBatch.title"))
        self.resize(760, 480)

        self.prefix_edit = QLineEdit()
        self.template_edit = QLineEdit(tr("renameBatch.defaultTemplate"))
        self.suffix_edit = QLineEdit()
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 999999999)
        self.start_spin.setValue(1)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 12)
        self.width_spin.setValue(4)

        form = QFormLayout()
        form.addRow(tr("renameBatch.prefix"), self.prefix_edit)
        form.addRow(tr("renameBatch.template"), self.template_edit)
        form.addRow(tr("renameBatch.suffix"), self.suffix_edit)
        numbers = QHBoxLayout()
        numbers.addWidget(QLabel(tr("renameBatch.start")))
        numbers.addWidget(self.start_spin)
        numbers.addSpacing(16)
        numbers.addWidget(QLabel(tr("renameBatch.width")))
        numbers.addWidget(self.width_spin)
        numbers.addStretch(1)
        form.addRow(tr("renameBatch.sequence"), numbers)

        help_label = QLabel(
            tr("renameBatch.help")
        )
        help_label.setWordWrap(True)

        self.preview = QTableWidget(0, 3)
        self.preview.setHorizontalHeaderLabels(
            (
                tr("renameBatch.oldPath"),
                tr("renameBatch.newName"),
                tr("renameBatch.validation"),
            )
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
        localize_dialog_buttons(self.buttons)
        self.buttons.button(QDialogButtonBox.Ok).setText(tr("renameBatch.rename"))
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
                .replace("{original}", stem)
                .replace("{sequence}", sequence)
            )
            new_stem = prefix + expanded + suffix
            target = os.path.join(
                os.path.dirname(source),
                new_stem + extension,
            )
            mapping[source] = target
            error = (
                tr("renameBatch.unknownToken")
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
                QTableWidgetItem(error or tr("common.available")),
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
                tr("renameBatch.resolveErrors")
            )
        elif not changed:
            self.message.setText(tr("renameBatch.unchanged"))
        else:
            self.message.setText(
                tr("renameBatch.ready")
            )


def validate_base_name(base_name, full_path=None):
    if not base_name:
        return tr("renameError.empty")
    if INVALID_FILENAME_CHARACTERS.search(base_name):
        return tr("renameError.invalidChars")
    if base_name.endswith((" ", ".")):
        return tr("renameError.trailing")
    reserved_key = base_name.split(".", 1)[0].upper()
    if reserved_key in WINDOWS_RESERVED_NAMES:
        return tr("renameError.reserved")
    if full_path is not None and os.name == "nt" and len(full_path) >= 260:
        return tr("renameError.pathLong")
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
            errors[source] = tr("renameError.duplicate")
            errors[owner] = tr("renameError.duplicate")
        target_owners[target_key] = source
        if os.path.exists(target) and target_key not in source_keys:
            errors[source] = tr("renameError.imageExists")

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
                errors[source] = tr("renameError.annotationExists")
            if old_stem.casefold() == new_stem.casefold():
                continue
    return errors


def _has_unknown_template_tokens(template):
    stripped = (
        template
        .replace("{原名}", "")
        .replace("{序号}", "")
        .replace("{original}", "")
        .replace("{sequence}", "")
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
