"""File-list selection, rendering, and rename UI."""

from __future__ import annotations

from labelimg.ui.presentation import present_dialog, role, section, MenuButton

import os
import re

from PyQt5.QtCore import (
    QAbstractListModel,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QPointF,
    QRect,
    QRectF,
    QSignalBlocker,
    QSize,
    QSortFilterProxyModel,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QPainter, QPalette, QPen
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyleOptionToolButton,
    QStylePainter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
    QActionGroup,
)

from labelimg.files.application.operations import exact_annotation_paths
from labelimg.files.model import (
    FileListItemState,
    FileListProjection,
    FileListQuery,
    compare_relative_image_paths,
    portable_logical_compare,
    quality_finding_value,
)
from labelimg.localization.runtime import language_changed, localize_dialog_buttons, tr
from labelimg.ui.icons import icon as new_icon, paint_icon
from labelimg.ui.query_field import decorate_list_query_field


CURRENT_IMAGE_ROLE = Qt.UserRole + 1
FILE_ANNOTATION_STATE_ROLE = Qt.UserRole + 2
PRESERVED_SELECTION_APPEARANCE_ROLE = Qt.UserRole + 3
FILE_PERSISTENCE_FLAGS_ROLE = Qt.UserRole + 4
FILE_REVIEW_STATE_ROLE = Qt.UserRole + 5
FILE_QUALITY_FINDINGS_ROLE = Qt.UserRole + 6
FILE_CATEGORY_LABELS_ROLE = Qt.UserRole + 7

INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class FileListViewState(object):
    """Mutable Qt control adapter for the immutable file-list query."""

    SORT_KEYS = FileListQuery.SORT_KEYS

    def __init__(self, sort_key="name", descending=False):
        self.sort_key = (
            sort_key if sort_key in self.SORT_KEYS else "name"
        )
        self.descending = bool(descending)
        self.reset_filter()

    @property
    def filter_active(self):
        return self.query.filter_active

    @property
    def search_active(self):
        return bool(self.text_filter)

    @property
    def advanced_filter_active(self):
        return bool(
            self.annotation_filter != "all"
            or self.review_filter != "all"
            or self.alert_filter != "all"
            or self.quality_filter != "all"
            or self.category_filter
        )

    @property
    def query(self):
        return FileListQuery(
            sort_key=self.sort_key,
            descending=self.descending,
            text=self.text_filter,
            annotation=self.annotation_filter,
            review=self.review_filter,
            alert=self.alert_filter,
            quality=self.quality_filter,
            categories=self.category_filter,
            category_match=self.category_match,
        )

    def projection_query(self, include_advanced_filters=True):
        return FileListQuery(
            sort_key=self.sort_key,
            descending=self.descending,
            text=self.text_filter,
            annotation=(
                self.annotation_filter
                if include_advanced_filters else "all"
            ),
            review=(
                self.review_filter if include_advanced_filters else "all"
            ),
            alert=(
                self.alert_filter if include_advanced_filters else "all"
            ),
            quality=(
                self.quality_filter if include_advanced_filters else "all"
            ),
            categories=self.category_filter if include_advanced_filters else (),
            category_match=self.category_match,
        )

    def set_search(self, text=""):
        self.text_filter = str(text).strip()

    def set_filter(
        self,
        annotation="all",
        review="all",
        alert="all",
        quality="all",
    ):
        self.annotation_filter = annotation
        self.review_filter = review
        self.alert_filter = alert
        self.quality_filter = quality

    def reset_search(self):
        self.text_filter = ""

    def set_category_filter(self, categories=(), match="all"):
        self.category_filter = frozenset(categories)
        self.category_match = match if match in ("all", "any") else "all"

    def reset_advanced_filters(self):
        self.annotation_filter = "all"
        self.review_filter = "all"
        self.alert_filter = "all"
        self.quality_filter = "all"
        self.set_category_filter()

    def reset_filter(self):
        self.reset_search()
        self.reset_advanced_filters()

    def project(
        self,
        paths,
        root,
        annotation_state_for,
        review_state_for,
        persistence_flags_for,
        quality_findings_for=lambda _path: (),
        modified_time_for=os.path.getmtime,
        presorted=False,
        include_advanced_filters=True,
        labels_for=lambda _path: (),
    ):
        items = []
        for path in paths:
            modified_time = None
            if self.sort_key == "modified":
                try:
                    modified_time = modified_time_for(path)
                except (OSError, TypeError, ValueError):
                    pass
            items.append(FileListItemState(
                path=path,
                modified_time=modified_time,
                annotation_state=annotation_state_for(path),
                review_state=review_state_for(path),
                persistence_flags=persistence_flags_for(path),
                quality_findings=quality_findings_for(path),
                labels=labels_for(path),
            ))
        return FileListProjection.create(
            root,
            items,
            self.projection_query(include_advanced_filters),
            presorted=presorted,
        )


class FileListControlButton(QToolButton):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.active = False
        self.descending = False
        self._hovered = False
        self.setFixedSize(28, 28)
        self.setIconSize(QSize(18, 18))
        self.setIcon(new_icon("filter" if kind == "filter" else "sort-ascending"))
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_active(self, active):
        active = bool(active)
        if self.active != active:
            self.active = active
            self.update()

    def set_descending(self, descending):
        self.descending = bool(descending)
        if self.kind != "filter":
            self.setIcon(new_icon("sort-descending" if self.descending else "sort-ascending"))
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
        paint_icon(painter, self.rect(), "filter" if self.kind == "filter" else
                   ("sort-descending" if self.descending else "sort-ascending"),
                   enabled=self.isEnabled())
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


class ImageSearchLineEdit(QLineEdit):
    openFirstResultRequested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.clear()
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.openFirstResultRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _CategoryFilterChipButton(QToolButton):
    def paintEvent(self, _event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.text = self.fontMetrics().elidedText(
            self.text(), Qt.ElideRight, max(0, self.width() - 14)
        )
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.CC_ToolButton, option)


class FileListFilterPanel(QFrame):
    categoriesChanged = pyqtSignal(object, str)
    filterChanged = pyqtSignal(str, str, str, str)
    clearRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("fileListFilterPanel")
        self.setFixedWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("fileFilterTitle")
        header.addWidget(self.title_label)
        header.addStretch()
        self.close_button = QToolButton()
        self.close_button.setIcon(new_icon("clear"))
        self.close_button.setFixedSize(26, 26)
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        self.category_section = QFrame()
        self.category_section.setObjectName("fileFilterSection")
        category_layout = QVBoxLayout(self.category_section)
        category_layout.setContentsMargins(12, 10, 12, 10)
        category_layout.setSpacing(8)
        category_header = QHBoxLayout()
        self.category_title = QLabel()
        self.category_title.setObjectName("fileFilterSectionTitle")
        category_header.addWidget(self.category_title)
        category_header.addStretch()
        self.category_count = QLabel()
        self.category_count.setObjectName("fileFilterMuted")
        category_header.addWidget(self.category_count)
        self.category_reset_button = QToolButton()
        self.category_reset_button.clicked.connect(self._clear_categories)
        category_header.addWidget(self.category_reset_button)
        category_layout.addLayout(category_header)
        self.category_search = QLineEdit()
        decorate_list_query_field(self.category_search, "search")
        category_layout.addWidget(self.category_search)
        self.category_list = QListWidget()
        self.category_list.setObjectName("fileFilterCategoryList")
        self.category_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.category_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.category_list.setTextElideMode(Qt.ElideRight)
        category_layout.addWidget(self.category_list)
        self.category_empty = QLabel()
        self.category_empty.setObjectName("fileFilterMuted")
        self.category_empty.setMinimumHeight(36)
        self.category_empty.setAlignment(Qt.AlignCenter)
        self.category_empty.setWordWrap(True)
        category_layout.addWidget(self.category_empty)
        self.category_match_title = QLabel()
        self.category_match_title.setObjectName("fileFilterMuted")
        category_layout.addWidget(self.category_match_title)
        self.category_match_control = QFrame()
        self.category_match_control.setObjectName("fileFilterMatchControl")
        match_layout = QHBoxLayout(self.category_match_control)
        match_layout.setContentsMargins(3, 3, 3, 3)
        match_layout.setSpacing(3)
        self.category_all = QToolButton()
        self.category_any = QToolButton()
        self.category_match_group = QButtonGroup(self)
        for control in (self.category_all, self.category_any):
            control.setCheckable(True)
            control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.category_match_group.addButton(control)
        self.category_all.setChecked(True)
        match_layout.addWidget(self.category_all, 1)
        match_layout.addWidget(self.category_any, 1)
        category_layout.addWidget(self.category_match_control)
        self.category_match_help = QLabel()
        self.category_match_help.setObjectName("fileFilterMuted")
        self.category_match_help.setWordWrap(True)
        category_layout.addWidget(self.category_match_help)
        layout.addWidget(self.category_section)
        self._categories = frozenset()
        self._available_categories = ()
        self.category_search.textChanged.connect(self._filter_category_rows)
        self.category_list.itemChanged.connect(self._category_checked)
        self.category_all.toggled.connect(self._emit_categories)
        self.state_section = QFrame()
        self.state_section.setObjectName("fileFilterSection")
        state_layout = QVBoxLayout(self.state_section)
        state_layout.setContentsMargins(12, 10, 12, 10)
        state_layout.setSpacing(10)
        self.state_title = QLabel()
        self.state_title.setObjectName("fileFilterSectionTitle")
        state_layout.addWidget(self.state_title)
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)
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
        for index, (label, combo) in enumerate((
            (self.annotation_label, self.annotation_combo),
            (self.review_label, self.review_combo),
            (self.alert_label, self.alert_combo),
            (self.quality_label, self.quality_combo),
        )):
            label.setObjectName("fileFilterMuted")
            label.setBuddy(combo)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(4)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            form.addWidget(label, index // 2 * 2, index % 2)
            form.addWidget(combo, index // 2 * 2 + 1, index % 2)
        self.form = form
        state_layout.addLayout(form)
        layout.addWidget(self.state_section)
        divider = QFrame()
        divider.setObjectName("fileFilterDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        footer = QHBoxLayout()
        self.live_hint = QLabel()
        self.live_hint.setObjectName("fileFilterMuted")
        footer.addWidget(self.live_hint)
        footer.addStretch()
        self.clear_button = QPushButton()
        self.clear_button.setIcon(new_icon("reset"))
        footer.addWidget(self.clear_button)
        layout.addLayout(footer)
        self.annotation_combo.currentIndexChanged.connect(self._emit_filter)
        self.review_combo.currentIndexChanged.connect(self._emit_filter)
        self.alert_combo.currentIndexChanged.connect(self._emit_filter)
        self.quality_combo.currentIndexChanged.connect(self._emit_filter)
        self.clear_button.clicked.connect(self.clearRequested)
        self.setStyleSheet("""
            QFrame#fileListFilterPanel { background: palette(base); border: 1px solid #D7DEE8; border-radius: 8px; }
            QLabel#fileFilterTitle { font-size: 15px; font-weight: 600; }
            QFrame#fileFilterSection { background: palette(base); border: 1px solid #E2E7EF; border-radius: 6px; }
            QLabel#fileFilterSectionTitle { font-weight: 600; }
            QLabel#fileFilterMuted { color: #727D8D; font-size: 11px; }
            QLineEdit { min-height: 28px; padding: 0 6px 0 0; background: palette(base);
                border: 1px solid #D7DEE8; border-radius: 4px; }
            QLineEdit:focus { border-color: #756B9E; }
            QListWidget#fileFilterCategoryList { background: palette(base); border: 1px solid #E2E7EF;
                border-radius: 4px; padding: 3px 0; outline: none; }
            QListWidget#fileFilterCategoryList::item { padding: 0 6px; border: none; }
            QListWidget#fileFilterCategoryList::item:hover { background: palette(alternate-base); }
            QListWidget#fileFilterCategoryList::item:focus { background: #F2F0F8; }
            QFrame#fileFilterMatchControl { background: #F3F4F7; border: 1px solid #E2E7EF; border-radius: 5px; }
            QFrame#fileFilterMatchControl QToolButton { min-height: 26px; padding: 0 8px; border: 1px solid transparent;
                border-radius: 3px; color: #687285; }
            QFrame#fileFilterMatchControl QToolButton:checked { background: #ECEAF5; color: #645887; border-color: #D6CFE6; }
            QFrame#fileFilterMatchControl QToolButton:hover { color: #645887; }
            QFrame#fileFilterMatchControl QToolButton:focus { border-color: #756B9E; }
            QComboBox { min-height: 28px; padding: 0 8px; background: palette(base);
                border: 1px solid #D7DEE8; border-radius: 4px; color: palette(text); }
            QComboBox:focus { border-color: #756B9E; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox::down-arrow { image: url(:/chevron-down); width: 16px; height: 16px; }
            QToolButton { border: none; border-radius: 4px; padding: 3px 5px; color: #645887; }
            QToolButton:hover, QToolButton:focus { background: #ECEAF5; }
            QToolButton:disabled { color: #A0A8B4; }
            QPushButton { min-height: 28px; padding: 0 10px; border: 1px solid #D7DEE8;
                border-radius: 4px; background: palette(base); color: palette(text); }
            QPushButton:hover { background: palette(alternate-base); }
            QPushButton:focus { border-color: #756B9E; }
            QFrame#fileFilterDivider { background: #E2E7EF; border: none; }
        """)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    @staticmethod
    def _add_options(combo, options):
        for message_id, value in options:
            combo.addItem(tr(message_id), value)
            combo.setItemData(combo.count() - 1, message_id, Qt.UserRole + 1)

    def retranslate_ui(self, _language=None):
        self.title_label.setText(tr("fileFilter.title"))
        self.category_title.setText(tr("fileFilter.categories"))
        self.category_search.setPlaceholderText(tr("fileFilter.categorySearch"))
        self.category_search.setAccessibleName(tr("fileFilter.categorySearch"))
        self.category_list.setAccessibleName(tr("fileFilter.categories"))
        self.category_all.setText(tr("fileFilter.categoryAllShort"))
        self.category_any.setText(tr("fileFilter.categoryAnyShort"))
        self.category_all.setAccessibleName(tr("fileFilter.categoryAll"))
        self.category_any.setAccessibleName(tr("fileFilter.categoryAny"))
        self.category_all.setToolTip(tr("fileFilter.categoryAllHelp"))
        self.category_any.setToolTip(tr("fileFilter.categoryAnyHelp"))
        self.category_match_title.setText(tr("fileFilter.categoryMatch"))
        self.category_reset_button.setText(tr("filePanel.clear"))
        self.category_reset_button.setToolTip(tr("fileFilter.categoryClear"))
        self.category_reset_button.setAccessibleName(tr("fileFilter.categoryClear"))
        self.state_title.setText(tr("fileFilter.stateConditions"))
        self.live_hint.setText(tr("fileFilter.liveHint"))
        self.close_button.setToolTip(tr("standard.close"))
        self.close_button.setAccessibleName(tr("standard.close"))
        self._filter_category_rows()
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
            combo.setToolTip(combo.currentText())

    def _emit_filter(self, _value=None):
        for combo in (self.annotation_combo, self.review_combo, self.alert_combo, self.quality_combo):
            combo.setToolTip(combo.currentText())
        self.filterChanged.emit(
            self.annotation_combo.currentData(),
            self.review_combo.currentData(),
            self.alert_combo.currentData(),
            self.quality_combo.currentData(),
        )

    def set_available_categories(self, categories):
        categories = tuple(sorted(set(categories), key=lambda value: (value.casefold(), value)))
        if categories != self._available_categories:
            self._available_categories = categories
            self.set_categories(self._categories, "all" if self.category_all.isChecked() else "any")

    def set_categories(self, categories=(), match="all"):
        self._categories = frozenset(categories)
        blockers = [QSignalBlocker(control) for control in (
            self.category_list, self.category_all, self.category_any,
        )]
        self.category_all.setChecked(match == "all")
        self.category_any.setChecked(match == "any")
        self.category_list.clear()
        # Keep selected labels when their last box disappears, so an empty
        # result never silently broadens the user's query.
        labels = sorted(set(self._available_categories) | self._categories,
                        key=lambda value: (value.casefold(), value))
        for label in labels:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, label)
            item.setToolTip(label)
            item.setSizeHint(QSize(0, 28))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if label in self._categories else Qt.Unchecked)
            self.category_list.addItem(item)
        del blockers
        self._filter_category_rows()

    def _filter_category_rows(self, _text=None):
        query = self.category_search.text().strip().casefold()
        visible = 0
        for row in range(self.category_list.count()):
            item = self.category_list.item(row)
            matches = query in item.text().casefold()
            item.setHidden(not matches)
            visible += matches
        self.category_list.setVisible(bool(visible))
        self.category_list.setFixedHeight(min(5, max(1, visible)) * 28 + 8)
        self.category_empty.setText(tr(
            "fileFilter.categoryNoMatch" if self.category_list.count()
            else "fileFilter.categoryEmpty"
        ))
        self.category_empty.setVisible(not visible)
        self._update_category_feedback()
        if self.isVisible():
            self._fit_content()

    def _update_category_feedback(self):
        self.category_count.setText(tr("fileFilter.categorySelected", count=len(self._categories)))
        self.category_reset_button.setEnabled(bool(self._categories))
        self.category_match_help.setText(tr(
            "fileFilter.categoryAllHelp" if self.category_all.isChecked()
            else "fileFilter.categoryAnyHelp"
        ))

    def _clear_categories(self):
        self.set_categories((), "all" if self.category_all.isChecked() else "any")
        self._emit_categories()

    def _category_checked(self, _item):
        self._categories = frozenset(
            self.category_list.item(row).data(Qt.UserRole)
            for row in range(self.category_list.count())
            if self.category_list.item(row).checkState() == Qt.Checked
        )
        self._emit_categories()

    def _emit_categories(self, _checked=None):
        self._update_category_feedback()
        self.categoriesChanged.emit(
            self._categories, "all" if self.category_all.isChecked() else "any"
        )

    def set_filter(self, annotation, review, alert, quality="all"):
        blockers = [
            QSignalBlocker(self.annotation_combo),
            QSignalBlocker(self.review_combo),
            QSignalBlocker(self.alert_combo),
            QSignalBlocker(self.quality_combo),
        ]
        for combo, value in (
            (self.annotation_combo, annotation),
            (self.review_combo, review),
            (self.alert_combo, alert),
            (self.quality_combo, quality),
        ):
            index = combo.findData(value)
            combo.setCurrentIndex(max(0, index))
            combo.setToolTip(combo.currentText())
        del blockers

    def show_for(self, button):
        self.ensurePolished()
        self._fit_content()
        self.show()
        self._fit_content()
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
        self.raise_()
        self.category_search.setFocus(Qt.PopupFocusReason)

    def _fit_content(self):
        for section in (self.category_section, self.state_section):
            section.layout().invalidate()
            section.layout().activate()
        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()
        screen = self.screen()
        if screen is not None and not self.category_list.isHidden():
            overflow = self.height() - screen.availableGeometry().height() + 20
            if overflow > 0:
                self.category_list.setFixedHeight(max(36, self.category_list.height() - overflow))
                self.category_section.layout().invalidate()
                self.category_section.layout().activate()
                self.layout().invalidate()
                self.layout().activate()
                self.adjustSize()
        if screen is not None and self.isVisible():
            available = screen.availableGeometry()
            self.move(
                max(available.left(), min(self.x(), available.right() - self.width() + 1)),
                max(available.top(), min(self.y(), available.bottom() - self.height() + 1)),
            )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)


class FileListControlBar(QWidget):
    viewChanged = pyqtSignal()
    openFirstSearchResultRequested = pyqtSignal()

    SORT_LABEL_IDS = {
        "name": "fileSort.name",
        "modified": "fileSort.modified",
        "annotation": "fileSort.annotation",
        "review": "fileSort.review",
    }

    def __init__(self, sort_key="name", descending=False, parent=None):
        super().__init__(parent)
        self.state = FileListViewState(sort_key, descending)
        self._workspace_available = False
        self._index_complete = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(6)
        self.search_edit = ImageSearchLineEdit(self)
        self.search_icon_action = decorate_list_query_field(
            self.search_edit,
            "search",
        )
        self.search_edit.textChanged.connect(self._set_search)
        self.search_edit.openFirstResultRequested.connect(
            self.openFirstSearchResultRequested
        )
        search_row.addWidget(self.search_edit, 1)
        self.sort_button = MenuButton(self)
        self.sort_button.setAutoRaise(True)
        self.sort_button.setFixedHeight(28)
        self.sort_button.setIconSize(QSize(18, 18))
        self.sort_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.filter_button = FileListControlButton("filter", self)
        search_row.addWidget(self.filter_button)
        layout.addLayout(search_row)
        # Composition moves this control into the dock header.
        layout.addWidget(self.sort_button, 0, Qt.AlignRight)
        self.filter_chips = QWidget()
        self.chip_layout = QGridLayout(self.filter_chips)
        self.chip_layout.setContentsMargins(0, 0, 0, 0)
        self.chip_layout.setHorizontalSpacing(5)
        self.chip_layout.setVerticalSpacing(5)
        self.chip_layout.setColumnStretch(1, 1)
        self.chip_buttons = {}
        for key in ('annotation', 'review', 'alert', 'quality'):
            chip = QToolButton(self.filter_chips)
            chip.setObjectName('fileFilterChip')
            chip.setFixedHeight(25)
            chip.setIcon(new_icon("clear"))
            chip.setIconSize(QSize(16, 16))
            chip.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            chip.clicked.connect(lambda checked=False, field=key: self.clear_filter_field(field))
            self.chip_buttons[key] = chip
        self.category_chip = QWidget(self.filter_chips)
        category_layout = QHBoxLayout(self.category_chip)
        category_layout.setContentsMargins(0, 0, 0, 0)
        category_layout.setSpacing(0)
        self.category_chip_button = _CategoryFilterChipButton(self.category_chip)
        self.category_chip_button.setObjectName('fileFilterChip')
        self.category_chip_button.setFixedHeight(25)
        self.category_chip_button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.category_chip_button.clicked.connect(self.show_filter_panel)
        category_layout.addWidget(self.category_chip_button, 1)
        self.category_clear_button = QToolButton(self.category_chip)
        self.category_clear_button.setObjectName('fileFilterChip')
        self.category_clear_button.setFixedSize(25, 25)
        self.category_clear_button.setIcon(new_icon('clear'))
        self.category_clear_button.setIconSize(QSize(16, 16))
        self.category_clear_button.clicked.connect(lambda: self.set_category_filter())
        category_layout.addWidget(self.category_clear_button)
        self.clear_chips_button = QToolButton(self.filter_chips)
        self.clear_chips_button.setFixedHeight(25)
        self.clear_chips_button.clicked.connect(self.clear_advanced_filters)
        layout.addWidget(self.filter_chips)
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
        self.filter_panel.categoriesChanged.connect(self.set_category_filter)
        self.filter_panel.clearRequested.connect(self.clear_advanced_filters)
        self.filter_button.clicked.connect(self.show_filter_panel)
        self.set_workspace_available(False)
        self._update_sort_presentation()
        self._update_filter_presentation()
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def retranslate_ui(self, _language=None):
        self.search_edit.setPlaceholderText(tr("imageSearch.placeholder"))
        self.search_edit.setAccessibleName(tr("imageSearch.accessibleName"))
        self.search_edit.setToolTip(tr("imageSearch.tooltip"))
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
        self._workspace_available = bool(available)
        self.search_edit.setEnabled(self._workspace_available)
        self.filter_button.setEnabled(
            self._workspace_available and self._index_complete
        )
        if not self._workspace_available:
            self.filter_panel.hide()

    def set_index_complete(self, complete):
        self._index_complete = bool(complete)
        self.filter_button.setEnabled(
            self._workspace_available and self._index_complete
        )
        if not self._index_complete:
            self.filter_panel.hide()

    @property
    def index_complete(self):
        return self._index_complete

    def focus_search(self):
        if not self.search_edit.isEnabled():
            return
        self.search_edit.setFocus(Qt.ShortcutFocusReason)
        self.search_edit.selectAll()

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
        self.sort_button.setText(tr(self.SORT_LABEL_IDS[self.state.sort_key]))
        self.sort_button.setIcon(new_icon("sort-descending" if self.state.descending else "sort-ascending"))
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

    def _set_search(self, text):
        before = self.state.text_filter
        self.state.set_search(text)
        if before != self.state.text_filter:
            self.viewChanged.emit()

    def _set_filter(self, annotation, review, alert, quality="all"):
        before = (
            self.state.annotation_filter,
            self.state.review_filter,
            self.state.alert_filter,
            self.state.quality_filter,
        )
        self.state.set_filter(annotation, review, alert, quality)
        self.filter_panel.set_filter(annotation, review, alert, quality)
        after = (
            self.state.annotation_filter,
            self.state.review_filter,
            self.state.alert_filter,
            self.state.quality_filter,
        )
        self._update_filter_presentation()
        if before != after:
            self.viewChanged.emit()

    def clear_search(self, emit=True):
        changed = self.state.search_active
        blocker = QSignalBlocker(self.search_edit)
        self.search_edit.clear()
        del blocker
        self.state.reset_search()
        if changed and emit:
            self.viewChanged.emit()

    def set_category_filter(self, categories=(), match="all"):
        before = self.state.query
        self.state.set_category_filter(categories, match)
        # Checkbox changes already updated the list. Avoid rebuilding that
        # widget during its own itemChanged event.
        if (self.filter_panel._categories != self.state.category_filter
                or self.filter_panel.category_all.isChecked() != (self.state.category_match == "all")):
            self.filter_panel.set_categories(self.state.category_filter, self.state.category_match)
        self._update_filter_presentation()
        if before != self.state.query:
            self.viewChanged.emit()

    def set_available_categories(self, categories):
        self.filter_panel.set_available_categories(categories)

    def clear_advanced_filters(self, _checked=False, emit=True):
        changed = self.state.advanced_filter_active
        self.state.reset_advanced_filters()
        self.filter_panel.set_categories()
        self.filter_panel.category_search.clear()
        self.filter_panel.set_filter("all", "all", "all", "all")
        self._update_filter_presentation()
        if changed and emit:
            self.viewChanged.emit()

    def clear_all_conditions(self, _checked=False, emit=True):
        changed = self.state.filter_active
        blocker = QSignalBlocker(self.search_edit)
        self.search_edit.clear()
        del blocker
        self.state.reset_filter()
        self.filter_panel.set_categories()
        self.filter_panel.category_search.clear()
        self.filter_panel.set_filter("all", "all", "all", "all")
        self._update_filter_presentation()
        if changed and emit:
            self.viewChanged.emit()

    def clear_filters(self, _checked=False, emit=True):
        self.clear_all_conditions(_checked, emit)

    def _update_filter_presentation(self):
        self.filter_button.set_active(self.state.advanced_filter_active)
        self._update_filter_chips()
        if not self.state.advanced_filter_active:
            self.filter_button.setToolTip(tr("fileFilter.disabled"))
            return
        labels = []
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
        if self.state.category_filter:
            labels.append(self._category_summary())
        self.filter_button.setToolTip(
            tr("fileFilter.tooltip", details=" · ".join(labels))
        )

    def clear_filter_field(self, field):
        values = {key: getattr(self.state, key + '_filter') for key in self.chip_buttons}
        values[field] = 'all'
        self.filter_panel.set_filter(*(values[key] for key in self.chip_buttons))
        self._set_filter(*(values[key] for key in self.chip_buttons))

    def _update_filter_chips(self):
        combos = (self.filter_panel.annotation_combo, self.filter_panel.review_combo,
                  self.filter_panel.alert_combo, self.filter_panel.quality_combo)
        active = 0
        for (key, chip), combo in zip(self.chip_buttons.items(), combos):
            self.chip_layout.removeWidget(chip)
            value = getattr(self.state, key + '_filter')
            chip.setVisible(value != 'all')
            if value != 'all':
                index = combo.findData(value)
                caption = combo.itemText(index)
                detail = tr({'annotation': 'fileFilter.annotation', 'review': 'fileFilter.review',
                             'alert': 'fileFilter.persistence', 'quality': 'fileFilter.quality'}[key]) + ': ' + caption
                chip.setText(caption)
                chip.setToolTip(detail)
                chip.setAccessibleName(tr('filePanel.removeFilter', filter=detail))
                self.chip_layout.addWidget(chip, active // 2, active % 2, Qt.AlignLeft)
                active += 1
        self.chip_layout.removeWidget(self.category_chip)
        self.category_chip.setVisible(bool(self.state.category_filter))
        if self.state.category_filter:
            summary = self._category_summary()
            self.category_chip_button.setText(summary)
            self.category_chip_button.setToolTip(tr('fileFilter.categoryEdit', details=summary))
            self.category_chip_button.setAccessibleName(tr('fileFilter.categoryEdit', details=summary))
            self.category_clear_button.setToolTip(tr('fileFilter.categoryClear'))
            self.category_clear_button.setAccessibleName(tr('fileFilter.categoryClear'))
            self.chip_layout.addWidget(self.category_chip, (active + 1) // 2, 0, 1, 2)
            active += 1
        self.chip_layout.addWidget(self.clear_chips_button, 0, 2, Qt.AlignRight)
        self.clear_chips_button.setText(tr('filePanel.clear'))
        self.filter_chips.setVisible(active > 0)

    def _category_summary(self):
        return tr(
            'fileFilter.categoryAllSummary' if self.state.category_match == 'all'
            else 'fileFilter.categoryAnySummary',
            labels=', '.join(sorted(self.state.category_filter, key=lambda value: (value.casefold(), value))),
        )

    def show_filter_panel(self, _checked=False):
        if not self.filter_button.isEnabled():
            return
        if self.filter_panel.isVisible():
            self.filter_panel.hide()
            return
        self.filter_panel.show_for(self.filter_button)


class FileListItem:
    """Lightweight QListWidgetItem-compatible row owned by FileListWidget."""

    def __init__(self, text=""):
        self._text = str(text)
        self._tooltip = ""
        self._data = {}
        self._hidden = False
        self._selected = False
        self._widget = None
        self._row = -1

    def text(self):
        return self._text

    def setText(self, text):
        text = str(text)
        if text == self._text:
            return
        self._text = text
        self._changed((Qt.DisplayRole,))

    def toolTip(self):
        return self._tooltip

    def setToolTip(self, text):
        text = str(text)
        if text == self._tooltip:
            return
        self._tooltip = text
        self._changed((Qt.ToolTipRole,))

    def data(self, role):
        if role == Qt.DisplayRole:
            return self._text
        if role == Qt.ToolTipRole:
            return self._tooltip
        return self._data.get(role)

    def setData(self, role, value):
        if self.data(role) == value:
            return
        if role == Qt.DisplayRole:
            self._text = str(value)
        elif role == Qt.ToolTipRole:
            self._tooltip = str(value)
        else:
            self._data[role] = value
        self._changed((role,))

    def isHidden(self):
        return self._hidden

    def setHidden(self, hidden):
        hidden = bool(hidden)
        if hidden == self._hidden:
            return
        self._hidden = hidden
        if self._widget is not None:
            self._widget._item_visibility_changed(self)

    def isSelected(self):
        return self._selected

    def setSelected(self, selected):
        if self._widget is not None:
            self._widget._set_item_selected(self, bool(selected))

    def _changed(self, roles):
        if self._widget is not None:
            self._widget._item_changed(self, roles)


class _FileListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        return self.items[index.row()].data(role)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def reset_items(self, items):
        self.beginResetModel()
        self.items = list(items)
        for row, item in enumerate(self.items):
            item._row = row
        self.endResetModel()

    def append(self, item):
        row = len(self.items)
        self.beginInsertRows(QModelIndex(), row, row)
        self.items.append(item)
        item._row = row
        self.endInsertRows()

    def extend(self, items):
        items = list(items)
        if not items:
            return
        first = len(self.items)
        last = first + len(items) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        for row, item in enumerate(items, start=first):
            item._row = row
            self.items.append(item)
        self.endInsertRows()

    def take(self, row):
        if not 0 <= row < len(self.items):
            return None
        self.beginRemoveRows(QModelIndex(), row, row)
        item = self.items.pop(row)
        item._row = -1
        for current_row in range(row, len(self.items)):
            self.items[current_row]._row = current_row
        self.endRemoveRows()
        return item


class _VisibleFileListProxy(QSortFilterProxyModel):
    def filterAcceptsRow(self, source_row, source_parent):
        source = self.sourceModel()
        return (
            source is not None
            and 0 <= source_row < len(source.items)
            and not source.items[source_row].isHidden()
        )


class FileListWidget(QListView):
    openRequested = pyqtSignal()
    itemOpenRequested = pyqtSignal(object)
    renameRequested = pyqtSignal()
    deleteRequested = pyqtSignal()
    searchRequested = pyqtSignal()
    itemSelectionChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_model = _FileListModel(self)
        self._proxy_model = _VisibleFileListProxy(self)
        self._proxy_model.setSourceModel(self._source_model)
        self.setModel(self._proxy_model)
        self.selectionModel().selectionChanged.connect(
            self._selection_changed
        )
        self.setUniformItemSizes(True)
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

    def count(self):
        return len(self._source_model.items)

    def item(self, row):
        if 0 <= row < self.count():
            return self._source_model.items[row]
        return None

    def row(self, item):
        row = getattr(item, "_row", -1)
        return row if 0 <= row < self.count() and self.item(row) is item else -1

    def clear(self):
        for item in self._source_model.items:
            item._widget = None
            item._row = -1
        self._source_model.reset_items(())

    def addItem(self, item):
        if not isinstance(item, FileListItem):
            item = FileListItem(item.text() if hasattr(item, "text") else item)
        item._widget = self
        self._source_model.append(item)

    def setItems(self, items):
        for current in self._source_model.items:
            current._widget = None
        items = list(items)
        for item in items:
            item._widget = self
        self._source_model.reset_items(items)
        self._proxy_model.invalidateFilter()

    def addItems(self, items):
        items = list(items)
        for item in items:
            item._widget = self
        self._source_model.extend(items)

    def takeItem(self, row):
        item = self._source_model.take(row)
        if item is not None:
            item._widget = None
        return item

    def indexFromItem(self, item):
        row = self.row(item)
        if row < 0:
            return QModelIndex()
        return self._proxy_model.mapFromSource(
            self._source_model.index(row, 0)
        )

    def itemFromIndex(self, index):
        if not index.isValid():
            return None
        source = self._proxy_model.mapToSource(index)
        return self.item(source.row())

    def itemAt(self, point):
        return self.itemFromIndex(self.indexAt(point))

    def selectedItems(self):
        return [item for item in self._source_model.items if item._selected]

    def clearSelection(self):
        for item in self._source_model.items:
            item._selected = False
        super().clearSelection()

    def currentItem(self):
        return self.itemFromIndex(self.currentIndex())

    def setCurrentItem(self, item):
        self.setCurrentIndex(
            self.indexFromItem(item) if item is not None else QModelIndex()
        )

    def currentRow(self):
        current = self.currentItem()
        return self.row(current) if current is not None else -1

    def visualItemRect(self, item):
        return self.visualRect(self.indexFromItem(item))

    def scrollToItem(self, item, hint=QAbstractItemView.EnsureVisible):
        index = self.indexFromItem(item)
        if index.isValid():
            self.scrollTo(index, hint)

    def _item_changed(self, item, roles):
        row = self.row(item)
        if row >= 0:
            index = self._source_model.index(row, 0)
            self._source_model.dataChanged.emit(index, index, list(roles))

    def _item_visibility_changed(self, item):
        self._proxy_model.invalidateFilter()
        if not item.isHidden() and item._selected:
            self._set_item_selected(item, True)

    def _item_is_selected(self, item):
        return item._selected

    def _set_item_selected(self, item, selected):
        item._selected = selected
        index = self.indexFromItem(item)
        if not index.isValid():
            return
        self.selectionModel().select(
            index,
            QItemSelectionModel.Select if selected else QItemSelectionModel.Deselect,
        )

    def _selection_changed(self, selected, deselected):
        for index in selected.indexes():
            item = self.itemFromIndex(index)
            if item is not None:
                item._selected = True
        for index in deselected.indexes():
            item = self.itemFromIndex(index)
            if item is not None and not item.isHidden():
                item._selected = False
        self.itemSelectionChanged.emit()

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
                str(quality_finding_value(value, "explanation") or value)
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
            self.searchRequested.emit()
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
    hover_background_alpha = 18
    status_column_width = 20
    alert_column_width = 20
    status_name_gap = 6
    name_alert_gap = 4

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(32, option.fontMetrics.height() + 10))
        return size

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
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        if selected:
            background = QColor(accent)
            background.setAlpha(self.selection_background_alpha)
            painter.setPen(Qt.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(QRectF(row_rect.adjusted(1, 1, -1, -1)), 6, 6)
            paint_option.state &= ~QStyle.State_Selected
            paint_option.state &= ~QStyle.State_HasFocus
            paint_option.state &= ~QStyle.State_MouseOver
        elif hovered or current_image:
            background = QColor(palette.color(QPalette.Mid))
            background.setAlpha(24 if current_image else self.hover_background_alpha)
            painter.setPen(Qt.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(QRectF(row_rect.adjusted(1, 1, -1, -1)), 6, 6)
            paint_option.state &= ~QStyle.State_MouseOver
        if current_image:
            paint_option.font.setBold(True)
            painter.fillRect(QRect(row_rect.left() + 2, row_rect.top() + 5,
                                   3, max(0, row_rect.height() - 10)), accent)

        layout = self.row_layout(row_rect)
        paint_option.rect = layout["name"]
        paint_option.textElideMode = Qt.ElideMiddle
        super().paint(painter, paint_option, index)

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
            row_rect.left() + 6,
            row_rect.top(),
            cls.status_column_width,
            row_rect.height(),
        )
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
        review = QRect(
            quality.left() - cls.status_column_width,
            row_rect.top(),
            cls.status_column_width,
            row_rect.height(),
        )
        name_left = annotation.right() + 2 + cls.status_name_gap
        name_right = review.left() - cls.name_alert_gap - 1
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
            "name": name,
            "quality": quality,
            "alert": alert,
        }

    @classmethod
    def _paint_quality_indicator(cls, painter, column, findings):
        if not findings:
            return
        paint_icon(painter, column, "status-quality", size=16)

    @classmethod
    def highest_alert(cls, flags):
        flags = set(flags)
        for flag in ("degraded", "conflict", "ambiguous", "dirty"):
            if flag in flags:
                return flag
        return None

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
        paint_icon(painter, column, "status-annotated", size=16)

    @classmethod
    def _paint_review_indicator(cls, painter, column, state):
        if state not in ("questioned", "verified"):
            return
        paint_icon(painter, column, "review-" + state, size=16)

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
        name = "status-warning" if alert == "degraded" else "status-" + alert
        paint_icon(painter, column, name, size=16)


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
        self.resize(1000, 560)

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
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.addRow(tr("renameBatch.prefix"), self.prefix_edit)
        form.addRow(tr("renameBatch.template"), self.template_edit)
        form.addRow(tr("renameBatch.suffix"), self.suffix_edit)
        form.addRow(tr("renameBatch.start"), self.start_spin)
        form.addRow(tr("renameBatch.width"), self.width_spin)

        help_label = QLabel(
            tr("ui.rename.tokens")
        )
        help_label.setWordWrap(True)
        self.template_edit.setToolTip(tr("renameBatch.help"))

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
        parameters = section("ui.section.naming", form)
        parameters.setFixedWidth(260)
        parameters.layout().addWidget(help_label)
        parameters.layout().addStretch(1)
        body = QHBoxLayout()
        body.addWidget(parameters)
        body.addWidget(section("ui.section.preview", self.preview), 1)
        layout.addLayout(body, 1)
        role(help_label, "supporting")
        role(self.message, "supporting")
        footer = QHBoxLayout()
        footer.addWidget(self.message, 1)
        footer.addWidget(self.buttons)
        layout.addLayout(footer)

        for widget in (
            self.prefix_edit,
            self.template_edit,
            self.suffix_edit,
        ):
            widget.textChanged.connect(self.update_preview)
        self.start_spin.valueChanged.connect(self.update_preview)
        self.width_spin.valueChanged.connect(self.update_preview)
        self.update_preview()
        present_dialog(self, primary=self.buttons.button(QDialogButtonBox.Ok), scroll=True, icon="edit-label")

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
    QSortFilterProxyModel,
