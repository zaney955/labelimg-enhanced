"""Qt input dialogs with the same popup spacing as application dropdowns."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QDialog, QInputDialog

from labelimg.ui.control_style import PopupItemDelegate


class InputDialog(QInputDialog):
    @staticmethod
    def getItem(parent, title, label, items, current=0, editable=True,
                flags=Qt.WindowFlags(), inputMethodHints=Qt.ImhNone):
        dialog = QInputDialog(parent, flags)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setComboBoxItems(items)
        dialog.setComboBoxEditable(editable)
        combo = dialog.findChild(QComboBox)
        combo.setItemDelegate(PopupItemDelegate(combo.view()))
        combo.setMaxVisibleItems(12)
        combo.setCurrentIndex(current)
        combo.setInputMethodHints(inputMethodHints)
        accepted = dialog.exec_() == QDialog.Accepted
        value = dialog.textValue() if accepted else ''
        dialog.deleteLater()
        return value, accepted
