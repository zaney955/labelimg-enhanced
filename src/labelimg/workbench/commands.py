"""Stable, task-oriented command surfaces for the main window."""

import math
from labelimg.ui.presentation import MenuButton

try:
    from PyQt5.QtCore import QEvent, QSignalBlocker, Qt, QSize, pyqtSignal
    from PyQt5.QtWidgets import (
        QAction,
        QActionGroup,
        QFrame,
        QHBoxLayout,
        QLabel,
        QMenu,
        QSizePolicy,
        QSlider,
        QToolBar,
        QToolButton,
        QWidget,
        QWidgetAction,
    )
except ImportError:  # pragma: no cover - legacy Qt4 compatibility
    from PyQt4.QtCore import QEvent, QSignalBlocker, Qt, QSize, pyqtSignal
    from PyQt4.QtGui import (
        QAction,
        QActionGroup,
        QFrame,
        QHBoxLayout,
        QLabel,
        QMenu,
        QSizePolicy,
        QSlider,
        QToolBar,
        QToolButton,
        QWidget,
        QWidgetAction,
    )

from labelimg.annotations.domain.model import AnnotationFormat
from labelimg.localization.runtime import language_changed, tr
from labelimg.ui.actions import format_action_tooltip, new_icon


BUTTON_SIZE = QSize(44, 44)
ICON_SIZE = QSize(24, 24)


def _set_text_button_compact(button, compact):
    """Size a command button for its current text, font, and Qt style."""
    button.setToolButtonStyle(
        Qt.ToolButtonIconOnly if compact
        else Qt.ToolButtonTextBesideIcon
    )
    if compact:
        button.setFixedSize(BUTTON_SIZE)
        return
    hint = button.sizeHint()
    button.setFixedSize(
        max(BUTTON_SIZE.width(), hint.width()),
        max(BUTTON_SIZE.height(), hint.height()),
    )


def _sync_button_accessibility(button):
    action = button.defaultAction()
    if action is None:
        return
    button.setToolTip(action.toolTip())
    button.setAccessibleName(action.text().replace("&", ""))
    button.setAccessibleDescription(action.toolTip())


def _tool_button(action=None, menu=None, text_beside=False):
    button = QToolButton()
    button.setAutoRaise(True)
    button.setFixedSize(BUTTON_SIZE)
    button.setIconSize(ICON_SIZE)
    if action is not None:
        button.setDefaultAction(action)
        _sync_button_accessibility(button)
    if menu is not None:
        button.setMenu(menu)
        button.setPopupMode(QToolButton.MenuButtonPopup)
    button.setToolButtonStyle(
        Qt.ToolButtonTextBesideIcon if text_beside
        else Qt.ToolButtonIconOnly
    )
    return button


class CanvasToolRail(QToolBar):
    """A fixed left rail containing only direct Canvas modes."""

    def __init__(self, select_action, create_action, pan_action, crop_action,
                 parent=None):
        super(CanvasToolRail, self).__init__(parent)
        self.setObjectName("canvasToolRail")
        self.setAllowedAreas(Qt.LeftToolBarArea)
        self.setMovable(False)
        self.setFloatable(False)
        self.setOrientation(Qt.Vertical)
        self.setIconSize(ICON_SIZE)
        self.setFixedWidth(52)
        self.setContentsMargins(4, 4, 4, 4)
        self.layout().setContentsMargins(4, 4, 4, 4)
        self.layout().setSpacing(0)
        self.toggleViewAction().setVisible(False)

        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.buttons = {}
        for name, action in (
            ("select", select_action),
            ("create", create_action),
            ("pan", pan_action),
        ):
            action.setCheckable(True)
            self.tool_group.addAction(action)
            button = _tool_button(action)
            button.setObjectName("canvasTool_%s" % name)
            self.addWidget(button)
            self.buttons[name] = button
        self.addSeparator()
        crop_action.setCheckable(True)
        self.tool_group.addAction(crop_action)
        crop_button = _tool_button(crop_action)
        crop_button.setObjectName("canvasTool_crop")
        self.addWidget(crop_button)
        self.buttons["crop"] = crop_button
        select_action.setChecked(True)
        language_changed.connect(self.retranslate_ui)

    def retranslate_ui(self, _language=None):
        for button in self.buttons.values():
            _sync_button_accessibility(button)

    def sizeHint(self):
        hint = super(CanvasToolRail, self).sizeHint()
        hint.setWidth(52)
        return hint


class FormatSelector(MenuButton):
    formatRequested = pyqtSignal(object)

    FORMATS = (
        (AnnotationFormat.PASCAL_VOC, "Pascal VOC", "format-voc"),
        (AnnotationFormat.YOLO, "YOLO", "format-yolo"),
        (AnnotationFormat.CREATE_ML, "CreateML", "format-createml"),
    )

    def __init__(self, annotation_format, parent=None):
        super(FormatSelector, self).__init__(parent)
        self.setObjectName("annotationFormatSelector")
        self._compact = False
        self.setAutoRaise(True)
        self.setIconSize(ICON_SIZE)
        self.setPopupMode(QToolButton.InstantPopup)
        self.menu = QMenu(self)
        self.menu.setIcon(new_icon("file"))
        self.group = QActionGroup(self.menu)
        self.group.setExclusive(True)
        self.actions = {}
        for value, title, icon_name in self.FORMATS:
            action = self.menu.addAction(new_icon(icon_name), title)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, fmt=value:
                self.formatRequested.emit(fmt) if checked else None
            )
            self.group.addAction(action)
            self.actions[value] = action
        self.setMenu(self.menu)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        self.set_format(annotation_format)

    def retranslate_ui(self, _language=None):
        tip = tr("format.selectorTip")
        self.menu.setTitle(tr("format.selector"))
        self.setToolTip(tip)
        self.setAccessibleName(tr("format.selector"))
        self.setAccessibleDescription(tip)

    def set_format(self, annotation_format):
        action = self.actions[annotation_format]
        action.setChecked(True)
        self.setText(action.text())
        self.setIcon(action.icon())
        self.set_compact(self._compact)

    def set_compact(self, compact):
        self._compact = bool(compact)
        _set_text_button_compact(self, self._compact)
        self.updateGeometry()


class TopCommandBar(QToolBar):
    """Stable primary commands with deterministic responsive collapse."""

    def __init__(self, open_action, previous_action, next_action,
                 rotate_action, flip_action,
                 format_selector, auto_save_action, save_action, parent=None):
        super(TopCommandBar, self).__init__(parent)
        self.setObjectName("topCommandBar")
        self.setMovable(False)
        self.setFloatable(False)
        self.setAllowedAreas(Qt.TopToolBarArea)
        self.setIconSize(ICON_SIZE)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.toggleViewAction().setVisible(False)
        self._last_available_width = None

        self.open_button = _tool_button(open_action, getattr(
            open_action, "_toolbar_menu", None
        ))
        self.open_button.setObjectName("openWorkspaceButton")
        self.addWidget(self.open_button)
        self.addSeparator()

        self.previous_button = _tool_button(previous_action)
        self.previous_button.setObjectName("previousImageButton")
        self.addWidget(self.previous_button)
        self.counter_label = QLabel("0 / 0")
        self.counter_label.setObjectName("imageCounter")
        self.counter_label.setAlignment(Qt.AlignCenter)
        self.counter_label.setMinimumWidth(62)
        self.counter_label.setFixedHeight(BUTTON_SIZE.height())
        self.addWidget(self.counter_label)
        self.next_button = _tool_button(next_action)
        self.next_button.setObjectName("nextImageButton")
        self.addWidget(self.next_button)
        self.addSeparator()

        self.rotate_button = _tool_button(
            rotate_action, getattr(rotate_action, "_toolbar_menu", None)
        )
        self.flip_button = _tool_button(
            flip_action, getattr(flip_action, "_toolbar_menu", None)
        )
        self.rotate_button.setObjectName("rotateQuickButton")
        self.flip_button.setObjectName("flipQuickButton")
        self.rotate_widget_action = self.addWidget(self.rotate_button)
        self.flip_widget_action = self.addWidget(self.flip_button)

        self.image_menu = QMenu(self)
        self.image_menu.addAction(rotate_action)
        self.image_menu.addActions(rotate_action._toolbar_menu.actions())
        self.image_menu.addSeparator()
        self.image_menu.addAction(flip_action)
        self.image_menu.addActions(flip_action._toolbar_menu.actions())
        self.image_quick_button = _tool_button(menu=self.image_menu)
        self.image_quick_button.setObjectName("imageQuickActionsButton")
        self.image_quick_button.setIcon(new_icon("image-actions"))
        self.image_quick_button.setPopupMode(QToolButton.InstantPopup)
        self.image_quick_widget_action = self.addWidget(
            self.image_quick_button
        )
        self.image_quick_widget_action.setVisible(False)
        self.addSeparator()

        self.format_selector = format_selector
        self.addWidget(format_selector)
        self.auto_save_button = _tool_button(auto_save_action)
        self.auto_save_button.setObjectName("autoSaveButton")
        self.addWidget(self.auto_save_button)
        self.save_button = _tool_button(save_action)
        self.save_button.setObjectName("saveButton")
        self.addWidget(self.save_button)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def retranslate_ui(self, _language=None):
        for button in (
            self.open_button,
            self.previous_button,
            self.next_button,
            self.rotate_button,
            self.flip_button,
            self.auto_save_button,
            self.save_button,
        ):
            _sync_button_accessibility(button)
        title = tr("image.quickActions")
        self.image_quick_button.setToolTip(title)
        self.image_quick_button.setAccessibleName(title)
        self.image_quick_button.setAccessibleDescription(title)
        self.update_responsive_layout(
            self.width()
            if self._last_available_width is None
            else self._last_available_width
        )

    def set_counter(self, current, total):
        self.counter_label.setText("%d / %d" % (current, total))
        self.counter_label.setAccessibleName(
            tr("navigation.counter", current=current, total=total)
        )

    def resizeEvent(self, event):
        super(TopCommandBar, self).resizeEvent(event)
        self.update_responsive_layout(self.width())

    def update_responsive_layout(self, available_width):
        self._last_available_width = max(0, int(available_width))

        layouts = (
            (False, False, False),
            (True, False, False),
            (True, True, False),
            (True, True, True),
        )
        for quick_actions_compact, open_compact, context_compact in layouts:
            self._apply_responsive_state(
                quick_actions_compact,
                open_compact,
                context_compact,
            )
            if self.sizeHint().width() <= self._last_available_width:
                break

    def _apply_responsive_state(
        self,
        quick_actions_compact,
        open_compact,
        context_compact,
    ):
        self.rotate_widget_action.setVisible(not quick_actions_compact)
        self.flip_widget_action.setVisible(not quick_actions_compact)
        self.image_quick_widget_action.setVisible(quick_actions_compact)
        _set_text_button_compact(self.open_button, open_compact)
        self.format_selector.set_compact(context_compact)
        self.layout().invalidate()


class ZoomControl(QFrame):
    valueChanged = pyqtSignal(float)
    zoomStepRequested = pyqtSignal(float)

    SLIDER_STEPS = 10000
    DEFAULT_MINIMUM = 1.0
    DEFAULT_MAXIMUM = 600.0
    INCREMENT_FACTOR = 1.10

    def __init__(self, value=100, parent=None):
        super(ZoomControl, self).__init__(parent)
        self.setObjectName("zoomControl")
        self._minimum = self.DEFAULT_MINIMUM
        self._maximum = self.DEFAULT_MAXIMUM
        self._value = float(value)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.minus = QToolButton()
        self.plus = QToolButton()
        for button in (self.minus, self.plus):
            button.setAutoRaise(True)
            button.setFixedSize(28, 24)
        self.minus.setIcon(new_icon("minus"))
        self.plus.setIcon(new_icon("plus"))
        for button in (self.minus, self.plus):
            button.setIconSize(QSize(18, 18))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.SLIDER_STEPS)
        self._compact = False
        self.slider.setFixedWidth(112)
        self.value_button = MenuButton()
        self.value_button.setAutoRaise(True)
        self.value_button.setPopupMode(QToolButton.InstantPopup)
        self.value_button.setMinimumWidth(58)
        self.menu = QMenu(self.value_button)
        self.value_button.setMenu(self.menu)
        self._update_value_button_width()
        layout.addWidget(self.minus)
        layout.addWidget(self.slider)
        layout.addWidget(self.plus)
        layout.addWidget(self.value_button)
        self.minus.clicked.connect(lambda: self.zoomStepRequested.emit(-1.0))
        self.plus.clicked.connect(lambda: self.zoomStepRequested.emit(1.0))
        self.slider.valueChanged.connect(self._slider_value_changed)
        for widget in (
            self.minus,
            self.slider,
            self.plus,
            self.value_button,
        ):
            widget.installEventFilter(self)
        self._update_slider_steps()
        self.setValue(value)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def set_compact(self, compact):
        compact = bool(compact)
        self.set_slider_width(80 if compact else 112)

    def set_slider_width(self, width):
        width = max(64, min(112, int(width)))
        if width == self.slider.width():
            return
        self._compact = width < 112
        self.slider.setFixedWidth(width)
        self.updateGeometry()

    @staticmethod
    def format_value(value):
        number = ("%.2f" % float(value)).rstrip("0").rstrip(".")
        return number + "%"

    def _slider_value_changed(self, position):
        value = self._value_for_slider_position(position)
        if math.isclose(value, self._value, rel_tol=1e-12, abs_tol=1e-12):
            return
        self._value = value
        self.value_button.setText(self.format_value(value))
        self.valueChanged.emit(value)

    def value(self):
        return self._value

    def setValue(self, value):
        value = min(max(float(value), self._minimum), self._maximum)
        changed = not math.isclose(
            value,
            self._value,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        self._value = value
        blocker = QSignalBlocker(self.slider)
        self.slider.setValue(self._slider_position_for_value(value))
        del blocker
        self.value_button.setText(self.format_value(value))
        if changed:
            self.valueChanged.emit(value)
        return changed

    def setMinimumValue(self, value):
        return self.setRangeValues(value, self._maximum)

    def setMaximumValue(self, value):
        return self.setRangeValues(self._minimum, value)

    def setRangeValues(self, minimum, maximum):
        minimum = max(float(minimum), 1e-12)
        maximum = max(float(maximum), minimum)
        self._minimum = minimum
        self._maximum = maximum
        self._update_slider_steps()
        self._update_value_button_width()
        return self.setValue(self._value)

    def minimumValue(self):
        return self._minimum

    def maximumValue(self):
        return self._maximum

    def _update_value_button_width(self):
        current_text = self.value_button.text()
        self.value_button.setMinimumWidth(58)
        self.value_button.setMaximumWidth(16777215)
        self.value_button.setText("%.2f%%" % self._maximum)
        width = max(58, self.value_button.sizeHint().width())
        self.value_button.setFixedWidth(width)
        self.value_button.setText(current_text)

    def _slider_position_for_value(self, value):
        if self._maximum <= self._minimum:
            return 0
        ratio = math.log(float(value) / self._minimum) / math.log(
            self._maximum / self._minimum
        )
        return int(round(min(max(ratio, 0.0), 1.0) * self.SLIDER_STEPS))

    def _value_for_slider_position(self, position):
        if self._maximum <= self._minimum:
            return self._minimum
        ratio = float(position) / self.SLIDER_STEPS
        return self._minimum * math.pow(
            self._maximum / self._minimum,
            ratio,
        )

    def _update_slider_steps(self):
        if self._maximum <= self._minimum:
            step = 1
        else:
            step = round(
                self.SLIDER_STEPS
                * math.log(self.INCREMENT_FACTOR)
                / math.log(self._maximum / self._minimum)
            )
        self.slider.setSingleStep(max(1, int(step)))
        self.slider.setPageStep(max(1, int(step) * 4))

    @staticmethod
    def _wheel_units(event):
        pixel_delta = event.pixelDelta()
        delta = pixel_delta.y() if not pixel_delta.isNull() else 0
        if not delta:
            delta = event.angleDelta().y()
        return float(delta) / 120.0

    def _handle_wheel(self, event):
        units = self._wheel_units(event)
        if not units:
            return False
        self.zoomStepRequested.emit(units)
        event.accept()
        return True

    def wheelEvent(self, event):
        if not self._handle_wheel(event):
            super().wheelEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel and self._handle_wheel(event):
            return True
        return super().eventFilter(watched, event)

    def set_zoom_actions(self, actual, fit_window, fit_width):
        self.menu.clear()
        self.menu.addAction(actual)
        self.menu.addAction(fit_window)
        self.menu.addAction(fit_width)

    def retranslate_ui(self, _language=None):
        title = tr("zoom.level")
        self.setToolTip(title)
        self.setAccessibleName(title)
        self.slider.setAccessibleName(title)
        self.minus.setToolTip(format_action_tooltip(
            tr("zoom.outShort"), ("Ctrl+-",)
        ))
        self.plus.setToolTip(format_action_tooltip(
            tr("zoom.inShort"), ("Ctrl+=",)
        ))
        self.value_button.setToolTip(tr("zoom.presets"))
        self.minus.setAccessibleName(tr("zoom.outShort"))
        self.plus.setAccessibleName(tr("zoom.inShort"))
        self.value_button.setAccessibleName(tr("zoom.presets"))
        self.minus.setAccessibleDescription(self.minus.toolTip())
        self.plus.setAccessibleDescription(self.plus.toolTip())
        self.value_button.setAccessibleDescription(
            self.value_button.toolTip()
        )
