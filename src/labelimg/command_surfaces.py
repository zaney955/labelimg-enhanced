"""Stable, task-oriented command surfaces for the main window."""

try:
    from PyQt5.QtCore import Qt, QSize, pyqtSignal
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
    from PyQt4.QtCore import Qt, QSize, pyqtSignal
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

from labelimg.annotation_document import AnnotationFormat
from labelimg.i18n import language_changed, tr
from labelimg.utils import format_action_tooltip, new_icon


BUTTON_SIZE = QSize(44, 44)
ICON_SIZE = QSize(24, 24)


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
    """A fixed left rail containing only persistent Canvas tools."""

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


class ReviewControl(QFrame):
    stateRequested = pyqtSignal(str)

    STATES = (
        ("unreviewed", "review.unreviewed", "review-unreviewed", None),
        (
            "questioned", "review.questioned", "review-questioned",
            "Ctrl+Space",
        ),
        ("verified", "review.verified", "review-verified", "Space"),
    )

    def __init__(self, parent=None):
        super(ReviewControl, self).__init__(parent)
        self.setObjectName("currentImageReviewControl")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.group = QActionGroup(self)
        self.group.setExclusive(True)
        self.actions = {}
        self.buttons = {}
        for state, message_id, icon_name, _shortcut in self.STATES:
            action = QAction(new_icon(icon_name), "", self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, value=state:
                self.stateRequested.emit(value) if checked else None
            )
            self.group.addAction(action)
            button = _tool_button(action)
            button.setFixedSize(98, 36)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setObjectName("review_%s" % state)
            layout.addWidget(button)
            self.actions[state] = action
            self.buttons[state] = button
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        self.set_state("unreviewed")

    def retranslate_ui(self, _language=None):
        for state, message_id, _icon_name, shortcut in self.STATES:
            title = tr(message_id)
            tooltip = format_action_tooltip(
                title,
                (shortcut,) if shortcut else (),
            )
            action = self.actions[state]
            action.setText(title)
            action.setToolTip(tooltip)
            button = self.buttons[state]
            button.setToolTip(tooltip)
            button.setAccessibleName(title)
            button.setAccessibleDescription(tooltip)

    def set_state(self, state):
        action = self.actions.get(state, self.actions["unreviewed"])
        action.setChecked(True)

    def set_compact(self, compact):
        for button in self.buttons.values():
            button.setFixedSize(44 if compact else 98, 36)
            button.setToolButtonStyle(
                Qt.ToolButtonIconOnly if compact
                else Qt.ToolButtonTextBesideIcon
            )

    def setEnabled(self, enabled):
        super(ReviewControl, self).setEnabled(enabled)
        for action in self.actions.values():
            action.setEnabled(enabled)


class FormatSelector(QToolButton):
    formatRequested = pyqtSignal(object)

    FORMATS = (
        (AnnotationFormat.PASCAL_VOC, "Pascal VOC", "format-voc"),
        (AnnotationFormat.YOLO, "YOLO", "format-yolo"),
        (AnnotationFormat.CREATE_ML, "CreateML", "format-createml"),
    )

    def __init__(self, annotation_format, parent=None):
        super(FormatSelector, self).__init__(parent)
        self.setObjectName("annotationFormatSelector")
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIconSize(ICON_SIZE)
        self.setPopupMode(QToolButton.InstantPopup)
        self.setFixedWidth(132)
        self.setFixedHeight(36)
        self.menu = QMenu(self)
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
        self.setToolTip(tip)
        self.setAccessibleName(tr("format.selector"))
        self.setAccessibleDescription(tip)

    def set_format(self, annotation_format):
        action = self.actions[annotation_format]
        action.setChecked(True)
        self.setText(action.text())
        self.setIcon(action.icon())

    def set_compact(self, compact):
        self.setFixedWidth(44 if compact else 132)
        self.setToolButtonStyle(
            Qt.ToolButtonIconOnly if compact
            else Qt.ToolButtonTextBesideIcon
        )


class TopCommandBar(QToolBar):
    """Stable primary commands with deterministic responsive collapse."""

    def __init__(self, open_action, previous_action, next_action,
                 review_control, rotate_action, flip_action,
                 format_selector, auto_save_action, save_action, parent=None):
        super(TopCommandBar, self).__init__(parent)
        self.setObjectName("topCommandBar")
        self.setMovable(False)
        self.setFloatable(False)
        self.setAllowedAreas(Qt.TopToolBarArea)
        self.setIconSize(ICON_SIZE)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.toggleViewAction().setVisible(False)

        self.open_button = _tool_button(open_action, getattr(
            open_action, "_toolbar_menu", None
        ))
        self.open_button.setFixedHeight(44)
        self.open_button.setMinimumWidth(44)
        self.open_button.setMaximumWidth(156)
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
        self.addWidget(self.counter_label)
        self.next_button = _tool_button(next_action)
        self.next_button.setObjectName("nextImageButton")
        self.addWidget(self.next_button)
        self.addSeparator()

        self.review_control = review_control
        self.addWidget(review_control)
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

    def set_counter(self, current, total):
        self.counter_label.setText("%d / %d" % (current, total))
        self.counter_label.setAccessibleName(
            tr("navigation.counter", current=current, total=total)
        )

    def resizeEvent(self, event):
        super(TopCommandBar, self).resizeEvent(event)
        self.update_responsive_layout(self.width())

    def update_responsive_layout(self, available_width):
        collapsed = available_width < 1020
        self.rotate_widget_action.setVisible(not collapsed)
        self.flip_widget_action.setVisible(not collapsed)
        self.image_quick_widget_action.setVisible(collapsed)
        self.review_control.set_compact(collapsed)
        self.format_selector.set_compact(collapsed)
        compact_open = available_width < 820
        self.open_button.setToolButtonStyle(
            Qt.ToolButtonIconOnly if compact_open
            else Qt.ToolButtonTextBesideIcon
        )
        self.open_button.setFixedWidth(
            44 if compact_open else 156
        )


class ZoomControl(QFrame):
    valueChanged = pyqtSignal(int)

    def __init__(self, value=100, parent=None):
        super(ZoomControl, self).__init__(parent)
        self.setObjectName("zoomControl")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.minus = QToolButton()
        self.plus = QToolButton()
        for button in (self.minus, self.plus):
            button.setAutoRaise(True)
            button.setFixedSize(28, 24)
        self.minus.setText("−")
        self.plus.setText("+")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 500)
        self.slider.setFixedWidth(112)
        self.value_button = QToolButton()
        self.value_button.setAutoRaise(True)
        self.value_button.setPopupMode(QToolButton.InstantPopup)
        self.value_button.setMinimumWidth(58)
        self.menu = QMenu(self.value_button)
        self.value_button.setMenu(self.menu)
        layout.addWidget(self.minus)
        layout.addWidget(self.slider)
        layout.addWidget(self.plus)
        layout.addWidget(self.value_button)
        self.minus.clicked.connect(lambda: self.setValue(self.value() - 10))
        self.plus.clicked.connect(lambda: self.setValue(self.value() + 10))
        self.slider.valueChanged.connect(self._value_changed)
        self.setValue(value)
        language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def _value_changed(self, value):
        self.value_button.setText("%d%%" % value)
        self.valueChanged.emit(value)

    def value(self):
        return self.slider.value()

    def setValue(self, value):
        self.slider.setValue(max(1, min(500, int(round(value)))))

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
            tr("zoom.inShort"), ("Ctrl++",)
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
