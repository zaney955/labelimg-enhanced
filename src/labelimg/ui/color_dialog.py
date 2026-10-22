"""Compact color entry, with the full Qt picker available on demand."""

import re
from PyQt5.QtCore import QSignalBlocker, QSize
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QColorDialog, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QToolButton, QVBoxLayout,
)
from labelimg.localization.runtime import language_changed, localize_dialog_buttons, tr
from labelimg.localization.qt_controls import install_qt_control_translations
from labelimg.ui.presentation import present_dialog, present_surface, role, section


class ColorDialog(QDialog):
    # Selectable color data, independent of application chrome.
    SWATCHES = ('#C84B4B', '#D57936', '#C6A831', '#59954E', '#318F8B', '#3878C8',
                '#7054AE', '#AE5389', '#FFFFFF', '#AAAAAA', '#555555', '#000000')

    def __init__(self, parent=None, show_alpha=False):
        super().__init__(parent)
        install_qt_control_translations()
        self._show_alpha = bool(show_alpha)
        self._color = QColor(self.SWATCHES[0])
        self.default = None
        layout = QVBoxLayout(self)
        palette = QGridLayout()
        self.swatches = []
        for index, value in enumerate(self.SWATCHES):
            button = QToolButton()
            button.setFixedSize(44, 36)
            button.setCheckable(True)
            button.setAccessibleName(value)
            button.setToolTip(value)
            button.setIcon(self._swatch_icon(QColor(value)))
            button.setIconSize(QSize(26, 22))
            button.clicked.connect(lambda _checked, value=value: self.setCurrentColor(QColor(value)))
            palette.addWidget(button, index // 6, index % 6)
            self.swatches.append(button)
        layout.addWidget(section('colorPicker.palette', palette))
        form = QFormLayout()
        self.current_label = QLabel()
        self.preview = QLabel()
        form.addRow(self.current_label, self.preview)
        self.hex_label = QLabel()
        self.hex_edit = QLineEdit()
        self.hex_label.setBuddy(self.hex_edit)
        self.hex_edit.textChanged.connect(self._edit_hex)
        form.addRow(self.hex_label, self.hex_edit)
        layout.addLayout(form)
        self.error = role(QLabel(), 'supporting')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.more = QPushButton()
        self.more.clicked.connect(self._more_colors)
        layout.addWidget(self.more)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        self.bb.clicked.connect(self.check_restore)
        self.bb.button(QDialogButtonBox.RestoreDefaults).setEnabled(False)
        layout.addWidget(self.bb)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        self.setCurrentColor(self._color)
        present_dialog(self, primary=self.bb.button(QDialogButtonBox.Ok), minimum_width=380, icon='color')

    @staticmethod
    def _swatch_icon(color):
        pixmap = QPixmap(26, 22)
        pixmap.fill(color)
        return QIcon(pixmap)

    def retranslate_ui(self, _language=None):
        self.setWindowTitle(tr('colorPicker.title'))
        self.current_label.setText(tr('colorPicker.current'))
        self.hex_label.setText(tr('colorPicker.hex'))
        self.hex_edit.setAccessibleName(tr('colorPicker.hex'))
        self.hex_edit.setPlaceholderText('#AARRGGBB' if self._show_alpha else '#RRGGBB')
        self.more.setText(tr('colorPicker.more'))
        self.error.setText(tr('colorPicker.invalid'))
        localize_dialog_buttons(self.bb)

    def testOption(self, option):
        return self._show_alpha if option == QColorDialog.ShowAlphaChannel else option == QColorDialog.DontUseNativeDialog

    def currentColor(self):
        return QColor(self._color)

    def setCurrentColor(self, color):
        color = QColor(color)
        if not color.isValid():
            return
        if not self._show_alpha:
            color.setAlpha(255)
        self._color = color
        with QSignalBlocker(self.hex_edit):
            self.hex_edit.setText(color.name(QColor.HexArgb if self._show_alpha else QColor.HexRgb).upper())
        self._refresh_color()

    def _refresh_color(self):
        self.preview.setPixmap(self._swatch_icon(self._color).pixmap(26, 22))
        self.preview.setAccessibleName(self.hex_edit.text())
        for value, button in zip(self.SWATCHES, self.swatches):
            button.setChecked(QColor(value) == self._color)
        self.error.hide()
        self.bb.button(QDialogButtonBox.Ok).setEnabled(True)

    def _edit_hex(self, value):
        pattern = r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?' if self._show_alpha else r'#[0-9a-fA-F]{6}'
        valid = bool(re.fullmatch(pattern, value))
        if valid:
            self._color = QColor(value)
            self._refresh_color()
        else:
            self.error.show()
            self.bb.button(QDialogButtonBox.Ok).setEnabled(False)

    def create_advanced_picker(self):
        picker = QColorDialog(self.currentColor(), self)
        picker.setOption(QColorDialog.DontUseNativeDialog)
        picker.setOption(QColorDialog.ShowAlphaChannel, self._show_alpha)
        picker.setWindowTitle(self.windowTitle())
        present_surface(picker)
        return picker

    def _more_colors(self):
        picker = self.create_advanced_picker()
        if picker.exec_():
            self.setCurrentColor(picker.currentColor())
        picker.deleteLater()

    def getColor(self, value=None, title=None, default=None):
        self.default = default
        self.bb.button(QDialogButtonBox.RestoreDefaults).setEnabled(default is not None)
        self.retranslate_ui()
        if title:
            self.setWindowTitle(title)
        self.setCurrentColor(value if value is not None else self._color)
        return self.currentColor() if self.exec_() else None

    def check_restore(self, button):
        if self.bb.buttonRole(button) == QDialogButtonBox.ResetRole and self.default is not None:
            self.setCurrentColor(self.default)
