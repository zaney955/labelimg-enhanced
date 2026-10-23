"""A shared, immediately persisted interface zoom setting."""

from PyQt5.QtCore import QSignalBlocker
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from labelimg.localization.runtime import language_changed, tr
from labelimg.ui.control_style import ComboBox
from labelimg.ui.metrics import ZOOM_LEVELS


class UiScaleControl(QWidget):
    """One setting surface sharing commands/state with View and the keyboard."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("uiScaleControl")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.caption = QLabel()
        self.combo = ComboBox()
        self.combo.setObjectName("uiScalePercentage")
        for level in ZOOM_LEVELS:
            self.combo.addItem(f"{level}%", level)
        self.caption.setBuddy(self.combo)
        self.reset_button = QPushButton()
        self.reset_button.clicked.connect(controller.reset)
        row.addWidget(self.caption)
        row.addWidget(self.combo)
        row.addWidget(self.reset_button)
        row.addStretch(1)
        self.combo.currentIndexChanged.connect(self._selected)
        controller.changed.connect(self.project)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        self.project()

    def _selected(self, index):
        self.controller.set_percent(self.combo.itemData(index))

    def project(self, _percent=None):
        with QSignalBlocker(self.combo):
            self.combo.setCurrentIndex(self.combo.findData(self.controller.percent))

    def retranslate_ui(self, _language=None):
        self.caption.setText(tr("uiScale.label"))
        self.combo.setAccessibleName(tr("uiScale.label"))
        self.combo.setToolTip(tr("uiScale.description"))
        self.reset_button.setText(tr("uiScale.default"))

