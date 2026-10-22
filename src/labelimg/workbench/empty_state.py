"""A quiet starting surface for an empty annotation workbench."""

from labelimg.ui.theme import apply_theme_style, theme_style


from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from labelimg.localization.runtime import language_changed, tr
from labelimg.ui.icons import IconLabel


class WorkbenchEmptyState(QFrame):
    def __init__(self, viewport, open_action, canvas):
        super().__init__(viewport)
        self.setObjectName("workbenchEmptyState")
        self.viewport = viewport
        self.canvas = canvas
        self.open_action = open_action
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        layout.addWidget(IconLabel("app", size=64), 0, Qt.AlignHCenter)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        self.title.setObjectName("workbenchEmptyTitle")
        layout.addWidget(self.title)
        self.formats = QLabel("Pascal VOC  ·  YOLO  ·  CreateML")
        self.formats.setAlignment(Qt.AlignCenter)
        self.formats.setObjectName("workbenchEmptyFormats")
        layout.addWidget(self.formats)
        self.open_button = QPushButton()
        self.open_button.setIcon(open_action.icon())
        self.open_button.clicked.connect(open_action.trigger)
        layout.addSpacing(4)
        layout.addWidget(self.open_button, 0, Qt.AlignHCenter)
        apply_theme_style(self, theme_style("""
            QFrame#workbenchEmptyState { background: ${background}; border: 1px solid ${border}; border-radius: 12px; }
            QLabel#workbenchEmptyTitle { color: ${text}; font-size: 15px; font-weight: 600; }
            QLabel#workbenchEmptyFormats { color: ${muted}; font-size: 11px; }
        """))
        viewport.installEventFilter(self)
        canvas.imageSizeChanged.connect(self.project)
        language_changed.connect(self.retranslate_ui)
        open_action.changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        self.project(canvas.pixmap.size())

    def retranslate_ui(self, _language=None):
        self.title.setText(tr("ui.workbench.empty"))
        self.open_button.setText(self.open_action.text().replace("&", ""))
        self.open_button.setToolTip(self.open_action.toolTip())
        self.open_button.setEnabled(self.open_action.isEnabled())
        self._position()

    def project(self, size):
        self.setVisible(size.isEmpty())
        self._position()

    def _position(self):
        self.adjustSize()
        self.move(
            max(0, (self.viewport.width() - self.width()) // 2),
            max(0, (self.viewport.height() - self.height()) // 2),
        )

    def eventFilter(self, watched, event):
        if watched is self.viewport and event.type() == QEvent.Resize:
            self._position()
        return super().eventFilter(watched, event)
