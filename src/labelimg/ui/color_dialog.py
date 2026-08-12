from PyQt5.QtWidgets import QColorDialog, QDialogButtonBox

BB = QDialogButtonBox

from labelimg.localization.runtime import localize_dialog_buttons


class ColorDialog(QColorDialog):

    def __init__(self, parent=None):
        super(ColorDialog, self).__init__(parent)
        self.setOption(QColorDialog.ShowAlphaChannel)
        # The Mac native dialog does not support our restore button.
        self.setOption(QColorDialog.DontUseNativeDialog)
        # Add a restore defaults button.
        # The default is set at invocation time, so that it
        # works across dialogs for different elements.
        self.default = None
        self.bb = self.layout().itemAt(1).widget()
        self.bb.addButton(BB.RestoreDefaults)
        localize_dialog_buttons(self.bb)
        self.bb.clicked.connect(self.check_restore)

    def getColor(self, value=None, title=None, default=None):
        localize_dialog_buttons(self.bb)
        self.default = default
        if title:
            self.setWindowTitle(title)
        if value:
            self.setCurrentColor(value)
        return self.currentColor() if self.exec_() else None

    def check_restore(self, button):
        if self.bb.buttonRole(button) & BB.ResetRole and self.default:
            self.setCurrentColor(self.default)
