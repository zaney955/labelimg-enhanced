"""Shared vector artwork for commands, delegates and Qt control chrome."""

from functools import lru_cache

from PyQt5 import sip
from PyQt5.QtCore import QFile, QIODevice, QLineF, QRectF, QTemporaryDir, Qt
from PyQt5.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QAbstractButton,
    QWidget,
    QApplication,
    QLabel,
    QProxyStyle,
    QStyle,
    QStyleOption,
    QStyleOptionComboBox,
    QStyleOptionSpinBox,
)

import labelimg.ui.generated_resources  # noqa: F401 - register icons for standalone widgets
from labelimg.ui.theme import COLORS, LIGHT_THEME, current_theme, theme_changed
from labelimg.ui.metrics import dp, sp

_ICON_ROLES = (
    "accent",
    "icon_annotation_tint",
    "icon_file",
    "icon_file_tint",
    "icon_image",
    "icon_image_tint",
    "icon_success",
    "icon_success_tint",
    "icon_view",
    "icon_view_tint",
    "icon_preference",
    "icon_preference_tint",
    "warning",
    "icon_warning_tint",
    "danger",
    "icon_danger_tint",
    "icon_structure",
)


@lru_cache(maxsize=256)
def _source_svg(name):
    source = QFile(":/" + name)
    if not source.open(QIODevice.ReadOnly):
        return None
    artwork = bytes(source.readAll())
    source.close()
    return artwork


@lru_cache(maxsize=512)
def _themed_svg(name, theme_id):
    artwork = _source_svg(name)
    if artwork is None or name == "app":
        return artwork
    replacements = {
        LIGHT_THEME.colors[role].lower().encode(): COLORS[role].encode()
        for role in _ICON_ROLES
    }
    import re

    return re.sub(
        rb"#[0-9a-fA-F]{6}", lambda m: replacements.get(m[0].lower(), m[0]), artwork
    )


@lru_cache(maxsize=512)
def _themed_icon_path(name, theme_id, cache_directory):
    artwork = _themed_svg(name, theme_id)
    if artwork is None or artwork == _source_svg(name):
        return ":/" + name
    from hashlib import sha256
    from pathlib import Path

    path = Path(cache_directory) / (
        sha256((theme_id + "/" + name).encode()).hexdigest() + ".svg"
    )
    path.write_bytes(artwork)
    return path.as_posix()


@lru_cache(maxsize=512)
def _native_icon(name, theme_id, cache_directory):
    if _source_svg(name) is None:
        return QIcon()
    result = QIcon(_themed_icon_path(name, theme_id, cache_directory))
    _icon_names[result.cacheKey()] = name
    return result


_icon_names = {}


def _clear_native_icon_caches(*_args):
    """Release Qt icon engines before QApplication/plugin teardown."""
    _native_icon.cache_clear()
    outline_icon.cache_clear()
    _icon_names.clear()


def _icon_cache_directory():
    app = QApplication.instance()
    if not hasattr(app, "_labelimg_icon_directory"):
        app._labelimg_icon_directory = QTemporaryDir()
        if not app._labelimg_icon_directory.isValid():
            raise OSError("Cannot create temporary SVG icon cache")
    return app._labelimg_icon_directory.path()


def themed_icon_path(name):
    """Share semantic SVG artwork with QSS image-based control affordances."""
    if QApplication.instance() is None:
        return ":/" + name
    return _themed_icon_path(name, current_theme().identifier, _icon_cache_directory())


def icon(name):
    # Native Qt SVG engines remain safe during QApplication/interpreter teardown.
    if QApplication.instance() is None:
        result = QIcon(":/" + name)
        _icon_names[result.cacheKey()] = name
        return result
    return _native_icon(name, current_theme().identifier, _icon_cache_directory())


@lru_cache(maxsize=256)
def outline_icon(name, color):
    """Render existing SVG geometry as a native, single-color outline icon."""
    from hashlib import sha256
    from pathlib import Path
    import re

    artwork = _source_svg(name)
    if artwork is None:
        return QIcon()
    artwork = re.sub(rb'stroke="#[0-9a-fA-F]{6}"', b'stroke="' + color.encode() + b'"', artwork)
    artwork = re.sub(rb'fill="#[0-9a-fA-F]{6}"', b'fill="none"', artwork)
    path = Path(_icon_cache_directory()) / (sha256(artwork).hexdigest() + ".svg")
    path.write_bytes(artwork)
    return QIcon(path.as_posix())


def _refresh_command_icons(_identifier):
    app = QApplication.instance()
    if app is None:
        return
    seen_actions = set()

    def refresh(value, setter):
        name = _icon_names.get(value.cacheKey())
        if name is not None:
            setter(icon(name))

    for widget in app.allWidgets():
        if sip.isdeleted(widget):
            continue
        for action in QWidget.actions(widget):
            if id(action) not in seen_actions:
                seen_actions.add(id(action))
                refresh(action.icon(), action.setIcon)
        if isinstance(widget, QAbstractButton):
            refresh(widget.icon(), widget.setIcon)
        if widget.isWindow():
            refresh(widget.windowIcon(), widget.setWindowIcon)
    refresh(app.windowIcon(), app.setWindowIcon)


theme_changed.connect(_refresh_command_icons)


def paint_icon(painter, rect, name, *, enabled=True, size=18):
    """Center an SVG in logical pixels; QIcon handles the paint device's DPR."""
    rect = QRectF(rect)
    side = min(sp(size), rect.width(), rect.height())
    target = QRectF(0, 0, side, side)
    target.moveCenter(rect.center())
    icon(name).paint(
        painter,
        target.toAlignedRect(),
        Qt.AlignCenter,
        QIcon.Normal if enabled else QIcon.Disabled,
    )


class IconLabel(QLabel):
    """A decorative icon that repaints from SVG at the screen's current scale."""

    def __init__(self, name, parent=None, size=18):
        super().__init__(parent)
        self._icon_name = name
        self._icon_size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        painter = QPainter(self)
        paint_icon(
            painter,
            self.rect(),
            self._icon_name,
            enabled=self.isEnabled(),
            size=self._icon_size,
        )


class IconStyle(QProxyStyle):
    """Keep native control behavior while sharing the application's glyphs."""

    def pixelMetric(self, metric, option=None, widget=None):
        value = super().pixelMetric(metric, option, widget)
        # Text/content sizes already carry their scaled font. Only native chrome
        # lengths are adapted here; QSS and explicit icon sizes have other owners.
        if metric in (
            QStyle.PM_IndicatorWidth, QStyle.PM_IndicatorHeight,
            QStyle.PM_ExclusiveIndicatorWidth, QStyle.PM_ExclusiveIndicatorHeight,
            QStyle.PM_ScrollBarExtent, QStyle.PM_ScrollBarSliderMin,
            QStyle.PM_SplitterWidth, QStyle.PM_DockWidgetSeparatorExtent,
            QStyle.PM_SliderThickness, QStyle.PM_SliderLength,
            QStyle.PM_SmallIconSize,
        ):
            return dp(value)
        return value

    ARROWS = {
        QStyle.PE_IndicatorArrowDown: "chevron-down",
        QStyle.PE_IndicatorArrowUp: "chevron-up",
        QStyle.PE_IndicatorArrowLeft: "chevron-left",
        QStyle.PE_IndicatorArrowRight: "chevron-right",
        QStyle.PE_IndicatorSpinDown: "chevron-down",
        QStyle.PE_IndicatorSpinUp: "chevron-up",
        QStyle.PE_IndicatorSpinPlus: "plus",
        QStyle.PE_IndicatorSpinMinus: "minus",
    }
    STANDARD_ICONS = {
        QStyle.SP_LineEditClearButton: "clear",
        QStyle.SP_DockWidgetCloseButton: "close",
        QStyle.SP_TitleBarCloseButton: "close",
        QStyle.SP_ToolBarHorizontalExtensionButton: "chevron-right",
        QStyle.SP_ToolBarVerticalExtensionButton: "chevron-down",
        QStyle.SP_MessageBoxInformation: "about",
        QStyle.SP_MessageBoxQuestion: "help",
        QStyle.SP_MessageBoxWarning: "status-warning",
        QStyle.SP_MessageBoxCritical: "status-conflict",
        QStyle.SP_DialogOkButton: "done",
        QStyle.SP_DialogCancelButton: "close",
        QStyle.SP_DialogApplyButton: "done",
        QStyle.SP_DialogResetButton: "reset",
        QStyle.SP_DialogSaveButton: "save",
        QStyle.SP_DialogOpenButton: "open-file",
        QStyle.SP_DialogCloseButton: "close",
        QStyle.SP_DialogHelpButton: "help",
    }

    def standardIcon(self, standard_icon, option=None, widget=None):
        name = self.STANDARD_ICONS.get(standard_icon)
        return (
            icon(name) if name else super().standardIcon(standard_icon, option, widget)
        )

    def standardPixmap(self, standard_pixmap, option=None, widget=None):
        name = self.STANDARD_ICONS.get(standard_pixmap)
        if name:
            mode = (
                QIcon.Normal
                if option is None or option.state & QStyle.State_Enabled
                else QIcon.Disabled
            )
            return icon(name).pixmap(dp(24), dp(24), mode)
        return super().standardPixmap(standard_pixmap, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_IndicatorDockWidgetResizeHandle:
            token = (
                "accent_border"
                if option.state & QStyle.State_MouseOver
                else "workspace_gutter"
            )
            painter.fillRect(option.rect, QColor(COLORS[token]))
            return
        if element in (
            QStyle.PE_IndicatorCheckBox,
            QStyle.PE_IndicatorItemViewItemCheck,
            QStyle.PE_IndicatorRadioButton,
        ):
            self._draw_choice(element, option, painter)
            return
        name = self.ARROWS.get(element)
        if (
            element == QStyle.PE_IndicatorBranch
            and option.state & QStyle.State_Children
        ):
            name = (
                "chevron-down" if option.state & QStyle.State_Open else "chevron-right"
            )
        if element == QStyle.PE_IndicatorHeaderArrow:
            name = (
                "sort-ascending"
                if option.sortIndicator == option.SortDown
                else "sort-descending"
            )
        if name:
            target = QRectF(0, 0, dp(16), dp(16))
            target.moveCenter(QRectF(option.rect).center())
            paint_icon(
                painter,
                target,
                name,
                enabled=bool(option.state & QStyle.State_Enabled),
                size=16,
            )
            return
        super().drawPrimitive(element, option, painter, widget)

    @staticmethod
    def _draw_choice(element, option, painter):
        """Theme native check/radio states without changing their hit targets."""
        enabled = bool(option.state & QStyle.State_Enabled)
        selected = bool(option.state & (QStyle.State_On | QStyle.State_NoChange))
        focused = bool(option.state & (QStyle.State_HasFocus | QStyle.State_MouseOver))
        rect = QRectF(
            0, 0, min(dp(14), option.rect.width() - dp(2)), min(dp(14), option.rect.height() - dp(2))
        )
        rect.moveCenter(QRectF(option.rect).center())
        edge = "accent" if enabled and (selected or focused) else "border"
        fill = (
            ("accent" if selected else "surface") if enabled else "disabled_background"
        )
        ink = "on_accent" if enabled else "disabled_text"
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(COLORS[edge]), sp(1.2)))
        painter.setBrush(QColor(COLORS[fill]))
        if element == QStyle.PE_IndicatorRadioButton:
            painter.drawEllipse(rect)
            if selected:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(COLORS[ink]))
                painter.drawEllipse(rect.adjusted(sp(4), sp(4), -sp(4), -sp(4)))
        else:
            painter.drawRoundedRect(rect, sp(3), sp(3))
            painter.setPen(
                QPen(QColor(COLORS[ink]), sp(1.8), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            )
            if option.state & QStyle.State_NoChange:
                painter.drawLine(
                    QLineF(
                        rect.left() + sp(4),
                        rect.center().y(),
                        rect.right() - sp(4),
                        rect.center().y(),
                    )
                )
            elif selected:
                path = QPainterPath()
                path.moveTo(rect.left() + sp(3), rect.center().y())
                path.lineTo(rect.left() + sp(6), rect.bottom() - sp(4))
                path.lineTo(rect.right() - sp(3), rect.top() + sp(4))
                painter.drawPath(path)
        painter.restore()

    def drawComplexControl(self, control, option, painter, widget=None):
        # Windows' themed combo/spin controls draw their arrows directly, bypassing
        # drawPrimitive. Let the base style draw the frame and share only the glyphs.
        if control == QStyle.CC_ComboBox:
            frame = QStyleOptionComboBox(option)
            frame.subControls &= ~QStyle.SC_ComboBoxArrow
            super().drawComplexControl(control, frame, painter, widget)
            if option.subControls & QStyle.SC_ComboBoxArrow:
                arrow = QStyleOption()
                arrow.rect = self.subControlRect(
                    control, option, QStyle.SC_ComboBoxArrow, widget
                )
                arrow.state = option.state
                self.drawPrimitive(QStyle.PE_IndicatorArrowDown, arrow, painter, widget)
            return
        if (
            control == QStyle.CC_SpinBox
            and option.buttonSymbols != QAbstractSpinBox.NoButtons
        ):
            frame = QStyleOptionSpinBox(option)
            frame.subControls &= ~(QStyle.SC_SpinBoxUp | QStyle.SC_SpinBoxDown)
            super().drawComplexControl(control, frame, painter, widget)
            for subcontrol, step, arrow_kind, plus_minus in (
                (
                    QStyle.SC_SpinBoxUp,
                    QAbstractSpinBox.StepUpEnabled,
                    QStyle.PE_IndicatorSpinUp,
                    QStyle.PE_IndicatorSpinPlus,
                ),
                (
                    QStyle.SC_SpinBoxDown,
                    QAbstractSpinBox.StepDownEnabled,
                    QStyle.PE_IndicatorSpinDown,
                    QStyle.PE_IndicatorSpinMinus,
                ),
            ):
                if option.subControls & subcontrol:
                    arrow = QStyleOption()
                    arrow.rect = self.subControlRect(
                        control, option, subcontrol, widget
                    )
                    arrow.state = option.state
                    if not option.stepEnabled & step:
                        arrow.state &= ~QStyle.State_Enabled
                    primitive = (
                        plus_minus
                        if option.buttonSymbols == QAbstractSpinBox.PlusMinus
                        else arrow_kind
                    )
                    self.drawPrimitive(primitive, arrow, painter, widget)
            return
        super().drawComplexControl(control, option, painter, widget)


def install_icon_style():
    app = QApplication.instance()
    if app is None or app.property("labelimgIconStyle"):
        return
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # Construct by name so Qt never transfers ownership of the existing style.
    app.setStyle(IconStyle(app.style().objectName()))
    app.aboutToQuit.connect(_clear_native_icon_caches)
    app.destroyed.connect(_clear_native_icon_caches)
    app.setProperty("labelimgIconStyle", True)
