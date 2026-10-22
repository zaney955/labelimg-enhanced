"""Current-image review commands integrated into a translucent viewport ribbon."""

from PyQt5.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QLinearGradient, QPainter
from PyQt5.QtWidgets import QAction, QActionGroup, QFrame, QHBoxLayout, QToolButton

from labelimg.localization.runtime import language_changed, tr
from labelimg.ui.actions import format_action_tooltip
from labelimg.ui.icons import outline_icon
from labelimg.ui.theme import COLORS, apply_theme_style, theme_changed, theme_style
from labelimg.ui.theme_palettes import blend, luminance, readable


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
        # Complete the readability scrim before the first command. Its soft
        # transition and the full-width tint form one material, without a card.
        end = max(1, self.width() - self.controls.width() - 11)
        start = max(0, end - 275)
        gradient = QLinearGradient(start, 0, max(start + 1, end), 0)
        surface = QColor(COLORS["surface"])
        for stop, alpha in ((0, 0), (.30, 12), (.70, 196), (1, 246)):
            color = QColor(surface)
            color.setAlpha(alpha)
            gradient.setColorAt(stop, color)
        painter.fillRect(self.rect(), gradient)
        painter.fillRect(self.rect(), self.controls.ribbon_color)


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
        self.destroyed.connect(self.ribbon.deleteLater)
        viewport.installEventFilter(self)
        language_changed.connect(self.retranslate_ui)
        theme_changed.connect(self._refresh)
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
        self.setVisible(enabled)
        self.ribbon.setVisible(enabled)
        self._position()

    def _foregrounds(self):
        # Readability must hold over arbitrary bright/dark source pixels below
        # the translucent surface, not just over the nominal theme background.
        surface = COLORS["surface"]
        tint = self.ribbon_color
        backgrounds = tuple(
            blend(tint.name(), blend(surface, base, 246 / 255), tint.alphaF())
            for base in ("#000000", "#FFFFFF")
        )
        active = readable(
            tint.name() if tint.alpha() else COLORS["text"], backgrounds, 4.6
        )
        return active, readable(COLORS["muted"], backgrounds, 4.6)

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
                        font-weight: 600;
                    }
                    QToolButton:hover { background: ${selected}; }
                    QToolButton:pressed { background: ${divider}; }
                    QToolButton:focus { border-color: %s; }
                """ % (color, muted)))
            self._position()
            self.ribbon.update()
        finally:
            self._refreshing = False

    def _position(self):
        viewport = self.parentWidget()
        # All labels remain present. Their measured widths depend only on
        # language/font/available space, never on the selected review state.
        hints = [button.sizeHint() for button in self.buttons.values()]
        widths = [max(74, hint.width()) for hint in hints]
        available = max(102, viewport.width() - 10)
        if sum(widths) > available:
            total = sum(widths)
            widths = [max(34, int(available * width / total)) for width in widths]
        height = max(36, *(hint.height() for hint in hints))
        self.setFixedSize(sum(widths) + 10, height)
        for button, width in zip(self.buttons.values(), widths):
            button.setFixedSize(width, height)
        self._row.activate()
        self.move(max(0, viewport.width() - self.width()), 0)
        self.ribbon.setGeometry(0, 0, viewport.width(), height)
        self.ribbon.raise_()
        self.raise_()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() in (QEvent.Resize, QEvent.Show):
            self._position()
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange and hasattr(self, "ribbon"):
            self._refresh()
