"""Current-image review commands integrated into a translucent viewport ribbon."""

from PyQt5.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QLinearGradient, QPainter
from PyQt5.QtWidgets import QAction, QActionGroup, QBoxLayout, QFrame, QHBoxLayout, QToolButton

from labelimg.localization.runtime import language_changed, tr
from labelimg.ui.actions import format_action_tooltip
from labelimg.ui.icons import outline_icon
from labelimg.ui.theme import COLORS, apply_theme_style, theme_changed, theme_style
from labelimg.ui.theme_palettes import blend, luminance, readable
from labelimg.ui.metrics import dp, scale_changed


class _ReviewRibbon(QFrame):
    """Mouse-transparent material, independently covering the viewport width."""

    def __init__(self, controls, viewport):
        super().__init__(viewport)
        self.controls = controls
        self.setObjectName("canvasReviewRibbon")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        # One shared gradient starts fading immediately across the full width,
        # including behind the transparent command buttons.
        gradient = QLinearGradient(0, 0, 0, max(1, self.height() - 1))
        tint = self.controls.ribbon_color
        surface = QColor(blend(tint.name(), COLORS['surface'], tint.alphaF()))
        for stop, alpha in ((0, 210), (1, 0)):
            color = QColor(surface)
            color.setAlpha(alpha)
            gradient.setColorAt(stop, color)
        painter.fillRect(self.rect(), gradient)


class ReviewControl(QFrame):
    """A model projection: requests use the existing guarded review use case."""

    stateRequested = pyqtSignal(str)
    STATES = (
        ("unreviewed", "review.unreviewed", "review-unreviewed", None),
        ("questioned", "review.questioned", "review-questioned", "Ctrl+Space"),
        ("verified", "review.verified", "review-verified", "Space"),
    )

    def __init__(self, viewport):
        super().__init__(viewport)
        self.setObjectName("currentImageReviewControl")
        self._state = "unreviewed"
        self._suppressed = False
        self._refreshing = False
        self.group = QActionGroup(self)
        self.group.setExclusive(True)
        self.actions = {}
        self.buttons = {}
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(3, 0, 3, 0)
        self._row.setSpacing(2)
        for state, _message, _icon, _shortcut in self.STATES:
            action = QAction(self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, value=state:
                self._request_state(value) if checked else None
            )
            self.group.addAction(action)
            button = QToolButton(self)
            button.setObjectName("review_%s" % state)
            button.setAutoRaise(True)
            button.setFocusPolicy(Qt.TabFocus)
            button.setIconSize(QSize(17, 17))
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self._row.addWidget(button)
            self.actions[state] = action
            self.buttons[state] = button
        self.ribbon = _ReviewRibbon(self, viewport)
        # Native measurement uses the selected weight even for inactive labels.
        # The invisible probe never participates in layout or receives input.
        self._size_probe = QToolButton(self)
        self._size_probe.setIconSize(QSize(17, 17))
        self._size_probe.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._size_probe.setFocusPolicy(Qt.NoFocus)
        apply_theme_style(self._size_probe, theme_style("""
            QToolButton { border: 1px solid transparent; padding: 0; font-weight: 700; }
        """))
        self._size_probe.hide()
        self.destroyed.connect(self.ribbon.deleteLater)
        viewport.installEventFilter(self)
        language_changed.connect(self.retranslate_ui)
        theme_changed.connect(self._refresh)
        scale_changed.connect(self._scale_changed)
        self.retranslate_ui()
        self.set_state("unreviewed")

    @property
    def state(self):
        return self._state

    @property
    def ribbon_color(self):
        role = {"questioned": "warning", "verified": "icon_success"}.get(self._state)
        color = QColor(COLORS[role]) if role else QColor(Qt.transparent)
        if role:
            color.setAlpha(56 if luminance(COLORS["surface"]) < .5 else 66)
        return color

    def retranslate_ui(self, _language=None):
        for state, message, _icon, shortcut in self.STATES:
            title = tr(message)
            detail = format_action_tooltip(title, (shortcut,) if shortcut else ())
            self.actions[state].setText(title)
            self.actions[state].setToolTip(detail)
            self.buttons[state].setAccessibleName(title)
            self.buttons[state].setAccessibleDescription(detail)
        self._refresh()

    def set_state(self, state):
        self._state = state if state in self.actions else "unreviewed"
        self.actions[self._state].setChecked(True)
        self._refresh()

    def _request_state(self, state):
        try:
            self.stateRequested.emit(state)
        finally:
            # A canceled or failed transaction must not leave Qt's optimistic
            # checked action disagreeing with the last document projection.
            self.actions[self._state].setChecked(True)
            self._refresh()

    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        for action in self.actions.values():
            action.setEnabled(enabled)
        self._sync_visibility()
        self._position()

    def set_suppressed(self, suppressed):
        """Temporarily hide both viewport layers without changing review state."""
        self._suppressed = bool(suppressed)
        self._sync_visibility()

    def _sync_visibility(self):
        visible = self.isEnabled() and not self._suppressed
        self.setVisible(visible)
        self.ribbon.setVisible(visible and self._state != "unreviewed")

    def _foregrounds(self):
        # Choose semantic foregrounds against the shared gradient on the theme
        # canvas. Source pixels remain visible; buttons add no local material.
        surface = COLORS["surface"]
        tint = self.ribbon_color
        material = blend(tint.name(), surface, tint.alphaF())
        opacity = 210 / 255 * (1 - self.height() / 2 / max(1, self.ribbon.height() - 1))
        background = blend(material, COLORS["background"], opacity) if tint.alpha() else COLORS["background"]
        role = {
            "verified": "review_verified_foreground",
            "questioned": "review_questioned_foreground",
        }.get(self._state, "text")
        active = readable(COLORS[role], (background,), 4.6)
        return active, readable(COLORS["muted"], (background,), 4.6)

    def _refresh(self, _identifier=None):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            active, muted = self._foregrounds()
            apply_theme_style(self, theme_style("""
                QFrame#currentImageReviewControl { background: transparent; border: none; }
            """))
            for state, _message, icon, _shortcut in self.STATES:
                selected = state == self._state
                color = active if selected else muted
                self.actions[state].setIcon(outline_icon(icon, color))
                button = self.buttons[state]
                apply_theme_style(button, theme_style("""
                    QToolButton, QToolButton:checked {
                        background: transparent; border: 1px solid transparent;
                        border-radius: 3px; padding: 0; color: %s;
                        font-weight: %s;
                    }
                    QToolButton:hover { background: ${selected}; }
                    QToolButton:pressed { background: ${divider}; }
                    QToolButton:focus { border-color: %s; }
                """ % (color, "700" if selected else "400", muted)))
            self._position()
            self._sync_visibility()
            self.ribbon.update()
        finally:
            self._refreshing = False

    def _position(self):
        viewport = self.parentWidget()
        # All labels remain present. Their measured widths depend only on
        # language/font/available space, never on the selected review state.
        self._size_probe.setIcon(self.actions["unreviewed"].icon())
        hints = []
        for action in self.actions.values():
            self._size_probe.setText(action.text())
            hints.append(self._size_probe.sizeHint())
        self.setProperty("uiScaleDynamicGeometry", True)
        widths = [max(dp(74), hint.width()) for hint in hints]
        available = max(dp(102), viewport.width() - dp(10))
        vertical = sum(widths) + dp(10) > available
        self._row.setDirection(QBoxLayout.TopToBottom if vertical else QBoxLayout.LeftToRight)
        height = max(dp(36), *(hint.height() for hint in hints))
        if vertical:
            widths = [min(max(widths), available)] * len(widths)
            group_width = widths[0] + dp(6)
            group_height = height * len(widths) + self._row.spacing() * (len(widths) - 1)
        else:
            group_width = sum(widths) + dp(10)
            group_height = height
        self.setFixedSize(group_width, group_height)
        for button, width in zip(self.buttons.values(), widths):
            button.setProperty("uiScaleDynamicGeometry", True)
            button.setFixedSize(width, height)
        self._row.activate()
        self.move(max(0, viewport.width() - self.width()), 0)
        self.ribbon.setProperty("uiScaleGeometryExcluded", True)
        self.ribbon.setGeometry(0, 0, viewport.width(), group_height + dp(44))
        self.ribbon.raise_()
        self.raise_()

    def _scale_changed(self, _percent):
        self._position()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() in (QEvent.Resize, QEvent.Show):
            self._position()
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange and hasattr(self, "ribbon"):
            self._refresh()
