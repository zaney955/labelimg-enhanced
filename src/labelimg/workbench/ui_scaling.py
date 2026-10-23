"""Workbench projections of application zoom; no image-scale state is stored."""

from PyQt5.QtCore import QEvent, QObject, QTimer
from PyQt5.QtWidgets import QActionGroup

from labelimg.localization.runtime import language_changed, tr
from labelimg.ui.metrics import ZOOM_LEVELS
from labelimg.ui.menu import Menu
from labelimg.ui.icons import icon



def install_scale_commands(window):
    window._ui_scale_binding = _WorkbenchScaleBinding(window)


class _WorkbenchScaleBinding(QObject):
    """Qt owns these connections and timers together with their window."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.controller = window.ui_scale
        self.anchor = None
        self.settle_timer = QTimer(self)
        self.settle_timer.setSingleShot(True)
        self.settle_timer.timeout.connect(self._settle)
        self._settled_size = None
        self._restored_size = None
        window.scroll_area.viewport().installEventFilter(self)
        menu = window.menus.view
        first_canvas = window.actions.zoomIn
        for action in (window.actions.uiZoomIn, window.actions.uiZoomOut, window.actions.uiZoomReset):
            menu.insertAction(first_canvas, action)
        self.levels = Menu(menu)
        self.levels.setIcon(icon('ui-zoom'))
        window.menus.uiScale = self.levels
        group = QActionGroup(self.levels)
        group.setExclusive(True)
        self.actions = {}
        for level in ZOOM_LEVELS:
            action = self.levels.addAction(icon('ui-zoom'), f"{level}%")
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, value=level: self.controller.set_percent(value))
            self.actions[level] = action
        menu.insertMenu(first_canvas, self.levels)
        menu.insertSeparator(first_canvas)
        self.controller.aboutToChange.connect(self.before_change)
        self.controller.changed.connect(self.changed)
        language_changed.connect(self.project)
        self.project()

    def project(self, _language=None):
        self.levels.setTitle(tr("uiScale.menu", percent=self.controller.percent))
        self.actions[self.controller.percent].setChecked(True)

    def before_change(self):
        window = self.window
        window._ui_scale_reflowing = True
        if not window.image.isNull() and window.zoom_mode == window.MANUAL_ZOOM:
            if not self.settle_timer.isActive():
                anchor = window._capture_zoom_anchor()
                self.anchor = anchor[0] if anchor else None
            # A scrollbar/layout resize queued before this command must not
            # restore an older center after the scale transaction settles.
            window._pending_manual_resize_anchor = None
            window._ignore_zoom_viewport_resize = True

    def changed(self, percent):
        self.project()
        self.window.status(tr("uiScale.changed", percent=percent))
        self._settled_size = None
        self._restored_size = None
        self.settle_timer.start(0)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize and getattr(self.window, '_ui_scale_reflowing', False):
            self._settled_size = None
            self.settle_timer.start(0)
        return False

    def _settle(self):
        size = self.window.scroll_area.viewport().size()
        if self._settled_size != size:
            self._settled_size = size
            self.settle_timer.start(0)
            return
        if self._restored_size != size:
            # Restoring/refitting can change scrollbar visibility and hence the
            # viewport again. Keep the transaction until that layout also rests.
            self._restored_size = size
            self.finish()
            self._settled_size = None
            self.settle_timer.start(0)
            return
        self.window._ignore_zoom_viewport_resize = False
        self.window._ui_scale_reflowing = False
        self.anchor = None

    def finish(self):
        window = self.window
        window._pending_manual_resize_anchor = None
        if window.image.isNull():
            return
        if window.zoom_mode == window.MANUAL_ZOOM:
            if self.anchor is not None:
                window._restore_manual_resize_anchor(self.anchor)
        else:
            window.adjust_scale(recenter=True)
