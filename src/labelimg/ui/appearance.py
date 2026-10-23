"""Persisted appearance preferences and one combined settings surface."""

from __future__ import annotations
import sys
from PyQt5.QtCore import QObject, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QBoxLayout,
    QAbstractButton,
    QFrame,
    QLabel,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)
from labelimg.localization.runtime import (
    SIMPLIFIED_CHINESE,
    current_language,
    language_changed,
    localize_dialog_buttons,
    tr,
)
from labelimg.platform.settings_keys import SETTING_COLOR_MODE, SETTING_ACCENT_COLOR
from labelimg.ui.presentation import present_dialog, role
from labelimg.ui.theme import (
    COLORS,
    apply_theme_style,
    theme_style,
    appearance_theme,
    is_applying_theme,
    set_theme,
    theme_changed,
)
from labelimg.ui.theme_palettes import available_accents, luminance
from labelimg.ui.icons import icon, outline_icon
from labelimg.ui.metrics import dp, sp

COLOR_MODES = ("system", "light", "dark")


def system_color_mode():
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                return (
                    "light"
                    if winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
                    else "dark"
                )
        except OSError:
            pass
    app = QApplication.instance()
    return (
        app.property("labelimgSystemColorMode") or "light"
        if app is not None
        else "light"
    )


class AppearanceController(QObject):
    preferencesChanged = pyqtSignal()

    def __init__(self, settings, parent=None, system_probe=None):
        super().__init__(parent)
        self.settings = settings
        self.system_probe = system_probe or system_color_mode
        self.mode = "light"
        self.accent = "plum"
        self.effective_mode = "light"
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh_system)
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._system_palette_changed)
        mode = settings.get(SETTING_COLOR_MODE, "light")
        accent = settings.get(SETTING_ACCENT_COLOR, "plum")
        self.apply_preferences(
            mode if mode in COLOR_MODES else "light",
            accent if accent in {a.identifier for a in available_accents()} else "plum",
        )

    def apply_preferences(self, mode, accent, *, persist=False):
        if mode not in COLOR_MODES:
            raise ValueError("Unknown color mode")
        if accent not in {a.identifier for a in available_accents()}:
            raise ValueError("Unknown accent preset")
        effective = self.system_probe() if mode == "system" else mode
        if effective not in ("light", "dark"):
            effective = "light"
        theme = appearance_theme(effective, accent)
        self.mode, self.accent, self.effective_mode = mode, accent, effective
        set_theme(theme.identifier)
        if mode == "system":
            self.timer.start()
        else:
            self.timer.stop()
        if persist:
            self.settings[SETTING_COLOR_MODE] = mode
            self.settings[SETTING_ACCENT_COLOR] = accent
            self.settings.save()
        self.preferencesChanged.emit()

    def refresh_system(self):
        if self.mode == "system":
            mode = self.system_probe()
            if mode in ("light", "dark") and mode != self.effective_mode:
                self.apply_preferences("system", self.accent)

    def _system_palette_changed(self, palette):
        if is_applying_theme():
            return
        app = QApplication.instance()
        if app is not None:
            app.setProperty(
                "labelimgSystemColorMode",
                (
                    "dark"
                    if luminance(palette.window().color().name()) < 0.45
                    else "light"
                ),
            )
        self.refresh_system()


class AccentButton(QAbstractButton):
    """A named color swatch with an explicit selection ring and keyboard focus."""

    def __init__(self, preset, controller):
        super().__init__()
        self.preset = preset
        self.controller = controller
        self.setCheckable(True)
        self.setProperty("accentId", preset.identifier)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(72)

    def sizeHint(self):
        return QSize(
            max(dp(56), self.fontMetrics().horizontalAdvance(self.text()) + dp(12)), dp(72)
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.underMouse() or self.hasFocus():
            painter.setPen(
                QPen(QColor(COLORS["accent"]) if self.hasFocus() else Qt.transparent, 1)
            )
            painter.setBrush(QColor(COLORS["background"]))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)
        colors = appearance_theme(
            self.controller.effective_mode, self.preset.identifier
        ).colors
        circle = QRectF((self.width() - sp(28)) / 2, sp(8), sp(28), sp(28))
        painter.setBrush(QColor(colors["accent"]))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(circle)
        if self.isChecked():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(colors["accent"]), sp(1.6)))
            painter.drawEllipse(circle.adjusted(-sp(4), -sp(4), sp(4), sp(4)))
            path = QPainterPath()
            path.moveTo(circle.left() + sp(8), circle.top() + sp(14))
            path.lineTo(circle.left() + sp(12), circle.top() + sp(18))
            path.lineTo(circle.left() + sp(20), circle.top() + sp(10))
            painter.setPen(
                QPen(
                    QColor(colors["on_accent"]),
                    sp(2),
                    Qt.SolidLine,
                    Qt.RoundCap,
                    Qt.RoundJoin,
                )
            )
            painter.drawPath(path)
        painter.setPen(QColor(COLORS["text"] if self.isChecked() else COLORS["muted"]))
        painter.drawText(
            self.rect().adjusted(0, dp(43), 0, 0),
            Qt.AlignHCenter | Qt.AlignTop,
            self.text(),
        )


class ModeButton(QToolButton):
    """A check identifies the saved choice; a dotted outline is keyboard focus."""

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isChecked():
            painter = QPainter(self)
            outline_icon('done', COLORS['selection_foreground']).paint(
                painter, QRect(self.width() - dp(24), (self.height() - dp(16)) // 2, dp(16), dp(16)))


class AppearanceDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.original = (controller.mode, controller.accent)
        self._completed = False
        self.setWindowTitle(tr("appearance.title"))
        root = QVBoxLayout(self)
        self.mode_caption = role(QLabel(), "sectionTitle")
        root.addWidget(self.mode_caption)
        mode_bar = QFrame()
        mode_bar.setObjectName("appearanceModeBar")
        modes = QHBoxLayout(mode_bar)
        self.mode_layout = modes
        modes.setContentsMargins(4, 4, 4, 4)
        modes.setSpacing(4)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for mode in COLOR_MODES:
            button = ModeButton()
            button.setProperty("uiRole", "appearanceMode")
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setIcon(icon("mode-" + mode))
            button.setIconSize(QSize(20, 20))
            button.setProperty("colorMode", mode)
            button.setMinimumHeight(38)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.mode_group.addButton(button)
            self.mode_buttons[mode] = button
            modes.addWidget(button)
        root.addWidget(mode_bar)
        root.addSpacing(6)
        self.accent_caption = role(QLabel(), "sectionTitle")
        root.addWidget(self.accent_caption)
        accents = QGridLayout()
        self.accent_layout = accents
        accents.setHorizontalSpacing(4)
        accents.setVerticalSpacing(8)
        self.accent_group = QButtonGroup(self)
        self.accent_buttons = {}
        for index, preset in enumerate(available_accents()):
            button = AccentButton(preset, controller)
            self.accent_group.addButton(button)
            self.accent_buttons[preset.identifier] = button
            accents.addWidget(button, index // 8, index % 8)
        root.addLayout(accents)
        from labelimg.ui.scale_control import UiScaleControl
        app = QApplication.instance()
        if app is not None and hasattr(app, "ui_scale"):
            self.scale_control = UiScaleControl(app.ui_scale)
            root.addWidget(self.scale_control)
        root.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        self.buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            lambda: self.controller.apply_preferences('light', 'plum')
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.mode_group.buttonClicked.connect(self._mode_clicked)
        self.accent_group.buttonClicked.connect(self._accent_clicked)
        self.controller.preferencesChanged.connect(self._project)
        theme_changed.connect(self._theme_changed)
        language_changed.connect(self.retranslate_ui)
        apply_theme_style(
            self,
            theme_style("""
            QFrame#appearanceModeBar { background: ${background}; border: 1px solid ${divider}; border-radius: 7px; }
            QToolButton[uiRole="appearanceMode"] { background: transparent; color: ${muted};
                border: 1px solid transparent; padding: 0 28px 0 8px; }
            QToolButton[uiRole="appearanceMode"]:hover { background: ${surface}; }
            QToolButton[uiRole="appearanceMode"]:checked { background: ${selected};
                color: ${selection_foreground}; border-color: ${accent_border}; }
            QToolButton[uiRole="appearanceMode"]:focus { border-color: ${accent}; border-style: dotted; }
        """),
        )
        self.resize(600, 330)
        present_dialog(
            self,
            primary=self.buttons.button(QDialogButtonBox.Save),
            minimum_width=580,
            icon="appearance",
        )
        self.retranslate_ui()
        self._project()
        self.buttons.button(QDialogButtonBox.Save).setFocus(Qt.OtherFocusReason)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "accent_buttons") or not self.accent_buttons:
            return
        available = max(1, self.width() - dp(72))
        width = max(button.sizeHint().width() for button in self.accent_buttons.values())
        fitting = max(1, min(8, available // max(1, width + dp(4))))
        columns = next(value for value in (8, 4, 2, 1) if value <= fitting)
        for index, button in enumerate(self.accent_buttons.values()):
            self.accent_layout.addWidget(button, index // columns, index % columns)
        total = sum(button.sizeHint().width() for button in self.mode_buttons.values()) + dp(24)
        self.mode_layout.setDirection(QBoxLayout.TopToBottom if total > available else QBoxLayout.LeftToRight)

    def _mode_clicked(self, button):
        self.controller.apply_preferences(
            button.property("colorMode"), self.controller.accent
        )

    def _accent_clicked(self, button):
        self.controller.apply_preferences(
            self.controller.mode, button.property("accentId")
        )

    def _project(self):
        self.mode_buttons[self.controller.mode].setChecked(True)
        self.accent_buttons[self.controller.accent].setChecked(True)
        self._refresh_swatches()

    def _theme_changed(self, _identifier):
        self._refresh_swatches()

    def _refresh_swatches(self):
        for button in self.accent_buttons.values():
            button.update()

    def retranslate_ui(self, _language=None):
        self.setWindowTitle(tr("appearance.title"))
        for mode, button in self.mode_buttons.items():
            button.setText(tr("appearance." + mode))
            button.setAccessibleName(button.text())
        for preset in available_accents():
            button = self.accent_buttons[preset.identifier]
            button.setText(
                preset.name_zh
                if current_language() == SIMPLIFIED_CHINESE
                else preset.name_en
            )
            button.setAccessibleName(button.text())
        self.mode_caption.setText(tr("appearance.mode"))
        self.accent_caption.setText(tr("appearance.accent"))
        localize_dialog_buttons(self.buttons)

    def done(self, result):
        if not self._completed:
            self._completed = True
            if result == QDialog.Accepted:
                self.controller.apply_preferences(
                    self.controller.mode, self.controller.accent, persist=True
                )
            else:
                self.controller.apply_preferences(*self.original)
        super().done(result)


def show_appearance(controller, parent):
    dialog = AppearanceDialog(controller, parent)
    dialog.exec_()
