
from labelimg.ui.presentation import present_dialog, role
from labelimg.ui.theme import theme_changed
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
)

from labelimg.annotations.ui.candidate_label_dialog import contrast_text_color
from labelimg.localization.runtime import (
    language_changed,
    localize_dialog_buttons,
    localize_message_box_buttons,
    tr,
)


def _label_sort_key(label):
    return str(label).casefold(), str(label)


class _ColorSwatchDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # The selection belongs to the row; this cell previews user data.
        preview = QStyleOptionViewItem(option)
        preview.state &= ~QStyle.State_Selected
        super().paint(painter, preview, index)


class LabelColorPaletteDialog(QDialog):
    """Stage category-color changes for one workspace session."""

    def __init__(self, labels, palette, color_dialog, parent=None):
        super().__init__(parent)
        self._palette = palette
        self._color_dialog = color_dialog
        self._overrides = palette.snapshot()
        self._labels = tuple(sorted(
            set(str(label) for label in labels if str(label))
            | set(self._overrides),
            key=_label_sort_key,
        ))

        self.description = QLabel()
        self.description.setWordWrap(True)
        role(self.description, "supporting")
        self.search = QLineEdit(self)
        self.search.textChanged.connect(self._filter_rows)
        self.table = QTableWidget(0, 3, self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setItemDelegateForColumn(1, _ColorSwatchDelegate(self.table))
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.table.itemDoubleClicked.connect(
            lambda _item: self.choose_selected_color()
        )

        self.choose_button = QPushButton()
        self.restore_button = QPushButton()
        self.restore_all_button = QPushButton()
        self.choose_button.clicked.connect(self.choose_selected_color)
        self.restore_button.clicked.connect(self.restore_selected_color)
        self.restore_all_button.clicked.connect(self.restore_all_colors)

        action_layout = QHBoxLayout()
        action_layout.addWidget(self.choose_button)
        action_layout.addWidget(self.restore_button)
        action_layout.addStretch(1)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.table, 1)
        layout.addLayout(action_layout)
        footer = QHBoxLayout()
        footer.addWidget(self.restore_all_button)
        footer.addWidget(self.description, 1)
        footer.addWidget(self.button_box)
        layout.addLayout(footer)

        self.table.itemSelectionChanged.connect(self._sync_buttons)
        language_changed.connect(self.retranslate_ui)
        theme_changed.connect(self._theme_changed)
        self.retranslate_ui()
        self._rebuild_rows()
        if self.table.rowCount():
            self.table.selectRow(0)
        self.resize(760, 480)
        present_dialog(self, primary=self.button_box.button(QDialogButtonBox.Save), scroll=True, icon="color")

    @property
    def overrides(self):
        return {
            label: QColor(color)
            for label, color in self._overrides.items()
        }

    def retranslate_ui(self, _language=None):
        self.setWindowTitle(tr("labelColor.manageTitle"))
        self.description.setText(tr("ui.palette.session"))
        self.description.setToolTip(tr("labelColor.manageDescription"))
        self.search.setPlaceholderText(tr("ui.palette.search"))
        self.search.setAccessibleName(tr("ui.palette.search"))
        self.table.setHorizontalHeaderLabels((
            tr("labelColor.labelColumn"),
            tr("labelColor.colorColumn"),
            tr("labelColor.sourceColumn"),
        ))
        self.choose_button.setText(tr("ui.palette.choose"))
        self.restore_button.setText(tr("ui.palette.restore"))
        self.restore_all_button.setText(tr("ui.palette.restoreAll"))
        localize_dialog_buttons(self.button_box)
        self._rebuild_rows()

    def _filter_rows(self, *_args):
        query = self.search.text().strip().casefold()
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, query not in self.table.item(row, 0).text().casefold())
        if self.table.currentRow() >= 0 and self.table.isRowHidden(self.table.currentRow()):
            self.table.setCurrentCell(-1, -1)
        self._sync_buttons()

    def selected_label(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return None if item is None else item.data(Qt.UserRole)

    def choose_selected_color(self):
        label = self.selected_label()
        if label is None:
            return
        automatic = self._palette.automatic_color(label)
        current = self._overrides.get(label, automatic)
        color = self._color_dialog.getColor(
            current,
            tr("labelColor.chooseTitle", label=label),
            default=automatic,
        )
        if color is None:
            return
        color = QColor(color)
        color.setAlpha(255)
        if color == automatic:
            self._overrides.pop(label, None)
        else:
            self._overrides[label] = color
        self._rebuild_rows(select_label=label)

    def restore_selected_color(self):
        label = self.selected_label()
        if label is None or label not in self._overrides:
            return
        self._overrides.pop(label, None)
        self._rebuild_rows(select_label=label)

    def restore_all_colors(self):
        count = len(self._overrides)
        if not count:
            return
        message = QMessageBox(
            QMessageBox.Question,
            tr("labelColor.restoreAllTitle"),
            tr("labelColor.restoreAllConfirm", count=count),
            QMessageBox.Yes | QMessageBox.Cancel,
            self,
        )
        localize_message_box_buttons(message)
        if message.exec_() != QMessageBox.Yes:
            return
        self._overrides.clear()
        self._rebuild_rows(select_label=self.selected_label())

    def _theme_changed(self, _identifier):
        self._rebuild_rows()

    def _rebuild_rows(self, select_label=None):
        if not hasattr(self, "table"):
            return
        if select_label is None:
            select_label = self.selected_label()
        self.table.setRowCount(len(self._labels))
        base = self.table.palette().base().color()
        for row, label in enumerate(self._labels):
            label_item = QTableWidgetItem(label)
            label_item.setData(Qt.UserRole, label)
            self.table.setItem(row, 0, label_item)

            color = QColor(
                self._overrides.get(label, self._palette.automatic_color(label))
            )
            color_item = QTableWidgetItem(color.name().upper())
            color_item.setTextAlignment(Qt.AlignCenter)
            swatch = QPixmap(20, 12)
            swatch.fill(color)
            color_item.setIcon(QIcon(swatch))
            color_item.setBackground(color)
            color_item.setForeground(contrast_text_color(color, base))
            self.table.setItem(row, 1, color_item)

            source_item = QTableWidgetItem(
                tr("labelColor.custom")
                if label in self._overrides
                else tr("labelColor.automatic")
            )
            source_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, source_item)
            if label == select_label:
                self.table.selectRow(row)
        self._filter_rows()

    def _sync_buttons(self):
        label = self.selected_label()
        self.choose_button.setEnabled(label is not None)
        self.restore_button.setEnabled(
            label is not None and label in self._overrides
        )
        self.restore_all_button.setEnabled(bool(self._overrides))
