"""One live application zoom, independent of image/canvas transforms."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import weakref

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtWidgets import (
    QAction, QApplication, QBoxLayout, QDialog, QDockWidget, QGridLayout, QFormLayout,
    QMainWindow, QWidget,
)

from labelimg.localization.runtime import language_changed, tr
from labelimg.platform.settings_keys import SETTING_UI_SCALE
from labelimg.ui.actions import set_action_copy
from labelimg.ui import metrics


_UNLIMITED = 16777215


@dataclass
class _WidgetMetrics:
    """Explicit geometry at 100%; QSS and content-derived sizes stay separate."""

    minimum: QSize
    maximum: QSize
    icon: QSize | None
    applied: bool = False


class UiMetrics:
    """Bind existing Qt geometry declarations to the shared design baseline.

    Qt's layout engine still computes positions and flexible sizes. We adapt
    declarations (constraints, margins, spacing, icons and spacers), never
    multiply current widget rectangles. Dynamic/custom components use dp().
    """

    def __init__(self):
        self.widgets = weakref.WeakKeyDictionary()
        self.layouts = weakref.WeakKeyDictionary()

    def register(self, widget, *, finish=False):
        existing = self.widgets.get(widget)
        if (existing is not None and (existing.applied or not finish)) or widget.property("uiScaleGeometryExcluded"):
            return
        icon = widget.iconSize() if hasattr(widget, "iconSize") else None
        minimum = widget.minimumSize()
        maximum = widget.maximumSize()
        # Qt's stylesheet engine writes computed constraints back to QWidget.
        # They already include zoom and must remain owned by the QSS template.
        for axis in ("w", "h"):
            if widget.property("_q_stylesheet_min" + axis) is not None and (
                maximum.width() if axis == "w" else maximum.height()
            ) == _UNLIMITED:
                (minimum.setWidth if axis == "w" else minimum.setHeight)(0)
        if isinstance(widget, QDockWidget):
            minimum.setHeight(0)  # QMainWindow derives this from dock contents.
        self.widgets[widget] = _WidgetMetrics(
            minimum, maximum, icon,
        )
        self.register_layout(widget.layout())

    def register_layout(self, layout):
        if layout is None:
            return
        # Native QMainWindow/toolbar/dock layouts rebuild private layout items.
        # Only bind declarations owned by our public layout classes.
        if not isinstance(layout, (QBoxLayout, QGridLayout, QFormLayout)) and not type(layout).__module__.startswith('labelimg.'):
            return
        if layout not in self.layouts:
            margins = layout.contentsMargins()
            grid = isinstance(layout, (QGridLayout, QFormLayout))
            spacing = (layout.horizontalSpacing(), layout.verticalSpacing()) if grid else (layout.spacing(),)
            spacers = []
            for index in range(layout.count()):
                spacer = layout.itemAt(index).spacerItem()
                if spacer is not None:
                    spacers.append((index, spacer.sizeHint(), spacer.sizePolicy()))
            self.layouts[layout] = (
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                spacing, spacers,
            )
        for index in range(layout.count()):
            self.register_layout(layout.itemAt(index).layout())

    def apply_widget(self, widget):
        state = self.widgets.get(widget)
        if state is None or sip.isdeleted(widget):
            return
        # QSS controls its own minimums; zero/default constraints must not erase
        # style-computed geometry. Fixed lengths have both non-default bounds.
        if not isinstance(widget, QMainWindow) and not widget.property("uiScaleDynamicGeometry"):
            for axis, minimum, maximum in (
                ("Width", state.minimum.width(), state.maximum.width()),
                ("Height", state.minimum.height(), state.maximum.height()),
            ):
                if minimum:
                    getattr(widget, "setMinimum" + axis)(metrics.dp(minimum))
                if maximum < _UNLIMITED:
                    getattr(widget, "setMaximum" + axis)(metrics.dp(maximum))
        if state.icon is not None:
            widget.setIconSize(metrics.scaled_size(state.icon))
        state.applied = True
        widget.updateGeometry()
        widget.update()

    def apply_layouts(self):
        for layout, (margins, spacing, spacers) in list(self.layouts.items()):
            if sip.isdeleted(layout):
                continue
            layout.setContentsMargins(*(metrics.dp(v) for v in margins))
            if len(spacing) == 2:
                layout.setHorizontalSpacing(metrics.dp(spacing[0]) if spacing[0] >= 0 else -1)
                layout.setVerticalSpacing(metrics.dp(spacing[1]) if spacing[1] >= 0 else -1)
            elif spacing[0] >= 0:
                layout.setSpacing(metrics.dp(spacing[0]))
            # QSpacerItem is not a QObject; retaining its wrapper across native
            # layout rebuilds leaves a dangling C++ pointer. Resolve live items.
            for index, size, policy in spacers:
                item = layout.itemAt(index)
                spacer = item.spacerItem() if item is not None else None
                if spacer is not None:
                    spacer.changeSize(metrics.dp(size.width()), metrics.dp(size.height()),
                                      policy.horizontalPolicy(), policy.verticalPolicy())
            layout.invalidate()


class UiScaleController(QObject):
    """Application-scoped preference and commands, available in modal editors."""

    aboutToChange = pyqtSignal()
    changed = pyqtSignal(int)

    def __init__(self, app):
        super().__init__(app)
        # QApplication owns this QObject and app.ui_scale. A strong back-link
        # defers native Qt/style destruction until cyclic GC or interpreter
        # shutdown, where saved system-theme launches can crash in Qt teardown.
        self.app = weakref.proxy(app)
        self.settings = None
        self.owner = None
        self.metrics = UiMetrics()
        self.applying = False
        self._pending = {}
        self.prepare_timer = QTimer(self)
        self.prepare_timer.setSingleShot(True)
        self.prepare_timer.timeout.connect(self._prepare_pending)
        self._requested_percent = None
        self.command_timer = QTimer(self)
        self.command_timer.setSingleShot(True)
        self.command_timer.timeout.connect(self._apply_queued_command)
        self._actions = []
        self.base_font = QFont(app.font())
        self.app.installEventFilter(self)
        language_changed.connect(self.retranslate_ui)

    @property
    def percent(self):
        return metrics.current_percent()

    def attach(self, window, settings):
        self.owner = weakref.ref(window)
        self.settings = settings
        window.destroyed.connect(self._owner_destroyed)
        window.ui_scale = self
        self._actions = []
        for name, key, shortcut, callback, artwork in (
            ("uiZoomIn", "uiScale.in", "Ctrl+=", self.zoom_in, "ui-zoom-in"),
            ("uiZoomOut", "uiScale.out", "Ctrl+-", self.zoom_out, "ui-zoom-out"),
            ("uiZoomReset", "uiScale.reset", "Ctrl+0", self.reset, "ui-zoom-reset"),
        ):
            from labelimg.ui.icons import icon
            action = QAction(icon(artwork), "", window)
            action.setShortcuts([QKeySequence(shortcut)] + ([QKeySequence("Ctrl++")] if name == "uiZoomIn" else []))
            action.setShortcutContext(Qt.ApplicationShortcut)
            action.triggered.connect(callback)
            window.addAction(action)
            setattr(window.actions, name, action)
            # The window owns its commands. An application-lived controller
            # must not keep their Python wrappers alive past window teardown.
            self._actions.append((weakref.ref(action), key))
        self.retranslate_ui()
        self.register_tree(window)
        changed = self.set_percent(settings.get(SETTING_UI_SCALE, 100), persist=False)
        if not changed:
            for widget in (window, *window.findChildren(QWidget)):
                self.metrics.apply_widget(widget)
            self.metrics.apply_layouts()
        self._sync_actions()

    def _owner_destroyed(self):
        owner = self.owner() if self.owner is not None else None
        if owner is None or sip.isdeleted(owner):
            self._actions = []
            self.settings = None

    def register_tree(self, widget):
        self.metrics.register(widget)
        for child in widget.findChildren(QWidget):
            self.metrics.register(child)

    def set_percent(self, percent, *, persist=True):
        self.command_timer.stop()
        self._requested_percent = None
        if isinstance(percent, bool):
            percent = 100
        try:
            percent = int(percent)
        except (ValueError, TypeError, OverflowError):
            percent = 100
        percent = min(metrics.ZOOM_LEVELS, key=lambda value: abs(value - percent))
        if percent == self.percent:
            return False
        self.aboutToChange.emit()
        old = self.percent
        docks = [(w, w.size()) for w in self.app.allWidgets() if isinstance(w, QDockWidget) and w.isVisible() and not w.isFloating()]
        dialogs = [(w, w.size()) for w in self.app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]
        for widget in self.app.allWidgets():
            self.metrics.register(widget)
        self.applying = True
        try:
            metrics._set_percent(percent)
            from labelimg.ui.theme import refresh_theme_styles
            font = QFont(self.base_font)
            if font.pixelSize() > 0:
                font.setPixelSize(metrics.dp(self.base_font.pixelSize()))
            else:
                font.setPointSizeF(self.base_font.pointSizeF() * percent / 100.0)
            self.app.setFont(font)
            refresh_theme_styles()
            for widget in list(self.metrics.widgets):
                self.metrics.apply_widget(widget)
            self.metrics.apply_layouts()
            windows = {dock.window() for dock, _size in docks}
            for window in windows:
                if not isinstance(window, QMainWindow):
                    continue
                for orientation in (Qt.Horizontal, Qt.Vertical):
                    group = [(dock, size) for dock, size in docks if dock.window() is window]
                    sizes = [round((size.width() if orientation == Qt.Horizontal else size.height()) * percent / old) for dock, size in group]
                    if group:
                        window.resizeDocks([dock for dock, _size in group], sizes, orientation)
            for dialog, size in dialogs:
                self._fit_dialog(dialog, QSize(round(size.width() * percent / old), round(size.height() * percent / old)))
        finally:
            self.applying = False
        self._sync_actions()
        if persist and self.settings is not None:
            self.settings[SETTING_UI_SCALE] = percent
            self.settings.save()
        self.changed.emit(percent)
        metrics.scale_changed.emit(percent)
        return True

    def zoom_in(self):
        percent = self._requested_percent if self._requested_percent is not None else self.percent
        self.set_percent(metrics.ZOOM_LEVELS[min(bisect_right(metrics.ZOOM_LEVELS, percent), len(metrics.ZOOM_LEVELS) - 1)])

    def zoom_out(self):
        percent = self._requested_percent if self._requested_percent is not None else self.percent
        self.set_percent(metrics.ZOOM_LEVELS[max(0, bisect_left(metrics.ZOOM_LEVELS, percent) - 1)])

    def reset(self):
        self.set_percent(100)

    def _queue_repeated_command(self, index):
        percent = self._requested_percent if self._requested_percent is not None else self.percent
        if index == 0:
            percent = metrics.ZOOM_LEVELS[min(bisect_right(metrics.ZOOM_LEVELS, percent), len(metrics.ZOOM_LEVELS) - 1)]
        elif index == 1:
            percent = metrics.ZOOM_LEVELS[max(0, bisect_left(metrics.ZOOM_LEVELS, percent) - 1)]
        else:
            percent = 100
        self._requested_percent = percent
        self.command_timer.start(0)

    def _apply_queued_command(self):
        percent = self._requested_percent
        if percent is not None:
            self.set_percent(percent)

    def retranslate_ui(self, _language=None):
        for action, key in self._live_actions():
            set_action_copy(action, tr(key), tr(key + "Tip"))

    def _live_actions(self):
        actions = [(reference(), key) for reference, key in self._actions]
        return [(action, key) for action, key in actions
                if action is not None and not sip.isdeleted(action)]

    def _sync_actions(self):
        actions = self._live_actions()
        if actions:
            actions[0][0].setEnabled(self.percent < metrics.ZOOM_LEVELS[-1])
            actions[1][0].setEnabled(self.percent > metrics.ZOOM_LEVELS[0])

    def _fit_dialog(self, dialog, preferred=None):
        screen = dialog.screen()
        if screen is None:
            return
        available = screen.availableGeometry().adjusted(12, 12, -12, -12)
        baseline_width = getattr(dialog, "_ui_scale_minimum_width", None)
        minimum_width = metrics.dp(baseline_width) if baseline_width is not None else dialog.minimumWidth()
        dialog.setMinimumWidth(min(minimum_width, available.width()))
        dialog.setMinimumHeight(min(dialog.minimumHeight(), available.height()))
        baseline_size = getattr(dialog, "_ui_scale_preferred_size", None)
        size = preferred or (metrics.scaled_size(baseline_size) if baseline_size is not None else dialog.size())
        if dialog.layout() is not None:
            dialog.layout().activate()
            size.setHeight(max(size.height(), dialog.layout().totalSizeHint().height()))
        dialog.resize(min(size.width(), available.width()), min(size.height(), available.height()))
        rect = dialog.frameGeometry()
        dialog.move(min(max(rect.x(), available.left()), max(available.left(), available.right() - rect.width() + 1)),
                    min(max(rect.y(), available.top()), max(available.top(), available.bottom() - rect.height() + 1)))

    def _prepare_pending(self):
        pending, self._pending = self._pending, {}
        widgets = [ref() for ref in pending.values()]
        widgets = [widget for widget in widgets if widget is not None and not sip.isdeleted(widget)]
        for widget in widgets:
            self.metrics.register(widget, finish=True)
            self.metrics.register_layout(widget.layout())
        self.applying = True
        try:
            for widget in widgets:
                self.metrics.apply_widget(widget)
            self.metrics.apply_layouts()
            for widget in widgets:
                if isinstance(widget, QDialog) and widget.isVisible():
                    self._fit_dialog(widget)
        finally:
            self.applying = False

    def eventFilter(self, watched, event):
        if self.applying or not isinstance(watched, QWidget):
            return False
        kind = event.type()
        if kind in (QEvent.ShortcutOverride, QEvent.KeyPress) and self._actions:
            actions = self._live_actions()
            modifiers = event.modifiers() & ~Qt.KeypadModifier
            key = event.key()
            index = None
            if modifiers == Qt.ControlModifier:
                index = {Qt.Key_Equal: 0, Qt.Key_Plus: 0, Qt.Key_Minus: 1, Qt.Key_0: 2}.get(key)
            elif modifiers == (Qt.ControlModifier | Qt.ShiftModifier) and key in (Qt.Key_Plus, Qt.Key_Equal):
                index = 0
            if index is not None and index < len(actions):
                event.accept()
                if kind == QEvent.KeyPress:
                    if event.isAutoRepeat():
                        self._queue_repeated_command(index)
                    else:
                        actions[index][0].trigger()
                return True
        if kind in (QEvent.Polish, QEvent.Show) and not watched.property("uiScaleGeometryExcluded"):
            from labelimg.ui.theme import prepare_surface_scale

            self.applying = True
            try:
                prepare_surface_scale(watched, showing=kind == QEvent.Show)
            finally:
                self.applying = False
            self.metrics.register(watched, finish=kind == QEvent.Show)
            if kind == QEvent.Show:
                self.applying = True
                try:
                    self.metrics.apply_widget(watched)
                finally:
                    self.applying = False
            # A deleted wrapper's id can be reused before the timer drains.
            self._pending[id(watched)] = weakref.ref(watched)
            self.prepare_timer.start(0)
        return False


def ui_scale_controller():
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("UI scaling requires QApplication")
    if not hasattr(app, "ui_scale"):
        app.ui_scale = UiScaleController(app)
    return app.ui_scale
