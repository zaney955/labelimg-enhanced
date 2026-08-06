"""Explicit subset selection for committed image-processing recovery."""

from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from labelimg.i18n import localize_dialog_buttons, tr


class ImageRecoverySelectionDialog(QDialog):
    """Choose an atomic recovery subset without consuming the remainder."""

    def __init__(self, resources, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("imageTools.recovery.title"))
        self._resources = tuple(resources)

        layout = QVBoxLayout(self)
        instructions = QLabel(
            tr("imageTools.recovery.instructions"),
            self,
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.list_widget = QListWidget(self)
        for resource in self._resources:
            path = os.path.abspath(resource.original_path)
            item = QListWidgetItem(os.path.basename(path), self.list_widget)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
        layout.addWidget(self.list_widget)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel, self)
        self.restore_button = self.buttons.addButton(
            tr("recovery.recover"),
            QDialogButtonBox.AcceptRole,
        )
        localize_dialog_buttons(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.list_widget.itemChanged.connect(self._update_restore_button)
        layout.addWidget(self.buttons)
        self._update_restore_button()
        self.resize(520, 340)

    @property
    def selected_paths(self):
        return tuple(
            self.list_widget.item(row).data(Qt.UserRole)
            for row in range(self.list_widget.count())
            if self.list_widget.item(row).checkState() == Qt.Checked
        )

    def _update_restore_button(self, *_args):
        self.restore_button.setEnabled(bool(self.selected_paths))

