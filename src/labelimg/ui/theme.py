"""Semantic application chrome colors, independent of image/category colors."""

from collections.abc import Mapping
from dataclasses import dataclass
import re
import weakref
from string import Template
from types import MappingProxyType

from PyQt5 import sip
from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPalette
from labelimg.ui.typography import FONT_TOKENS
from labelimg.ui.metrics import current_percent, scale_stylesheet

_style_scales = weakref.WeakKeyDictionary()
_surface_polish_scales = weakref.WeakKeyDictionary()

_LIGHT_COLORS = {
    "surface": "#FFFFFF",
    "workspace_gutter": "#EBEEF3",
    "panel_header": "#F5F6F9",
    "panel_border": "#C4CBD5",
    "background": "#F5F6F9",
    "border": "#D7DEE8",
    "divider": "#E2E7EF",
    "text": "#253047",
    "muted": "#68758A",
    "hover_overlay": "#929292",
    "shadow": "#000000",
    "scrim": "#000000",
    "accent": "#756B9E",
    "accent_hover": "#665B8E",
    "on_accent": "#FFFFFF",
    "selected": "#DFDAE8",
    "selection_background": "#DFDAE8",
    "selection_border": "#C5BFD6",
    "selection_foreground": "#253047",
    "accent_border": "#D6CFE6",
    "disabled_text": "#929AA6",
    "disabled_background": "#F0F2F6",
    "danger": "#A65F5F",
    "danger_border": "#DDBDBD",
    "warning": "#9A7640",
    # Image wells remain neutral and dark; sampled/image pixels are never tinted.
    "preview_background": "#202428",
    "preview_border": "#68758A",
    "canvas_verified": "#DFEADF",
    "canvas_questioned": "#F0E6D4",
    "review_verified_foreground": "#176B37",
    "review_questioned_foreground": "#885100",
    "icon_file": "#5677A6",
    "icon_file_tint": "#DCE6F2",
    "icon_image": "#4F8582",
    "icon_image_tint": "#DCEBE8",
    "icon_success": "#5F8468",
    "icon_success_tint": "#DFEADF",
    "icon_view": "#64788F",
    "icon_view_tint": "#E2E8EE",
    "icon_preference": "#7B6F94",
    "icon_preference_tint": "#E8E2EE",
    "icon_annotation_tint": "#E6E2F0",
    "icon_warning_tint": "#F0E6D4",
    "icon_danger_tint": "#F1DEDE",
    "icon_structure": "#455468",
}


@dataclass(frozen=True)
class Theme:
    identifier: str
    name_en: str
    name_zh: str
    colors: Mapping

    def __post_init__(self):
        if not self.identifier or not self.name_en or not self.name_zh:
            raise ValueError("A theme needs an identifier and bilingual names")
        values = dict(self.colors)
        if values.keys() != _LIGHT_COLORS.keys():
            raise ValueError(
                "Theme colors must define every semantic role exactly once"
            )
        if any(
            not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value)
            for value in values.values()
        ):
            raise ValueError("Theme colors must be six-digit RGB hex values")
        object.__setattr__(self, "colors", MappingProxyType(values))

    def with_overrides(self, identifier, *, name_en, name_zh, **colors):
        return Theme(identifier, name_en, name_zh, {**self.colors, **colors})


LIGHT_THEME = Theme("light-plum", "Light · Plum", "浅色 · 紫灰", _LIGHT_COLORS)
_themes = {LIGHT_THEME.identifier: LIGHT_THEME}
_current_theme = LIGHT_THEME
_applying_theme = False


class _ThemeEvents(QObject):
    changed = pyqtSignal(str)


_events = _ThemeEvents()
theme_changed = _events.changed


def available_themes():
    return tuple(_themes.values())


def register_theme(theme):
    if not isinstance(theme, Theme):
        raise TypeError("register_theme requires a Theme")
    if theme.identifier in _themes:
        raise ValueError("Theme identifier is already registered")
    _themes[theme.identifier] = theme


def current_theme():
    return _current_theme


class _CurrentColors(Mapping):
    def __getitem__(self, key):
        return _current_theme.colors[key]

    def __iter__(self):
        return iter(_current_theme.colors)

    def __len__(self):
        return len(_current_theme.colors)


# Retain one read-only lookup object, including for modules imported before a switch.
COLORS = _CurrentColors()


class ThemeStyle(str):
    """QSS text that retains its semantic source when composed with other QSS."""

    def __new__(cls, template):
        template = template.template if isinstance(template, ThemeStyle) else template
        instance = super().__new__(cls, scale_stylesheet(Template(template).substitute({**COLORS, **FONT_TOKENS})))
        instance.template = template
        return instance

    def __add__(self, other):
        return ThemeStyle(self.template + _style_template(other))

    def __radd__(self, other):
        return ThemeStyle(_style_template(other) + self.template)


def _style_template(style):
    return style.template if isinstance(style, ThemeStyle) else str(style)


def theme_style(stylesheet):
    """Resolve semantic tokens in QSS; unknown names fail instead of drifting."""
    return ThemeStyle(stylesheet)


def apply_theme_style(widget, stylesheet):
    """Bind QSS to a widget/application so existing windows can change theme."""
    template = _style_template(stylesheet)
    if widget.property("labelimgThemeStyle") != template:
        widget.setProperty("labelimgThemeStyle", template)
    resolved = str(theme_style(template))
    if "url(:/" in resolved:
        from labelimg.ui.icons import themed_icon_path

        resolved = re.sub(
            r"url\(:/([\w-]+)\)",
            lambda match: 'url("' + themed_icon_path(match[1]) + '")',
            resolved,
        )
    if widget.styleSheet() != resolved:
        widget.setStyleSheet(resolved)
    _style_scales[widget] = current_percent()


def widget_theme_style(widget):
    """Get a bound style without flattening its theme tokens during composition."""
    template = widget.property("labelimgThemeStyle")
    return theme_style(template if template is not None else widget.styleSheet())


def _style_surfaces(app):
    surfaces = (app, *app.allWidgets())
    # Qt 5 can retain a constructor-time QSS palette on unpolished native
    # toolbar/status controls. Polish the old rules before invalidating them,
    # so changing theme/zoom before first show follows the same path as live UI.
    for widget in surfaces:
        if widget is not app and not sip.isdeleted(widget):
            widget.ensurePolished()
    return surfaces


def refresh_theme_styles():
    """Resize visible regions; hidden windows catch up before they are shown."""
    from PyQt5.QtWidgets import QApplication, QWidget

    app = QApplication.instance()
    if app is None:
        return
    # The application sheet is a fallback. Rebinding it repolishes every hidden
    # editor and popup as well. Each visible window/region owns its scaled rules.
    for widget in app.allWidgets():
        if sip.isdeleted(widget) or not QWidget.isVisible(widget):
            continue
        template = widget.property("labelimgThemeStyle")
        if template is not None:
            apply_theme_style(widget, template)


def prepare_surface_scale(widget, *, showing=False):
    """Bring a newly visible subtree up to date before native layout/painting."""
    from PyQt5.QtWidgets import QDialog, QFileDialog, QMenu, QWidget

    # Labels/frames can be temporarily parentless during construction. They
    # must inherit their eventual region rather than acquire a local full sheet.
    owns_surface = isinstance(widget, (QDialog, QMenu)) or widget.windowType() == Qt.ToolTip
    if owns_surface and not widget.property("labelimgSurfaceRoot"):
        if isinstance(widget, QFileDialog) and not widget.testOption(QFileDialog.DontUseNativeDialog):
            return
        from labelimg.ui.presentation import SURFACE_STYLE

        apply_theme_style(widget, SURFACE_STYLE + "\n" + widget_theme_style(widget))
        widget.setProperty("labelimgSurfaceRoot", True)
    window = QWidget.window(widget)
    for surface in (widget, *widget.findChildren(QWidget)):
        if QWidget.window(surface) is not window or _style_scales.get(surface) == current_percent():
            continue
        template = surface.property("labelimgThemeStyle")
        if template is not None:
            surface.ensurePolished()
            apply_theme_style(surface, template)
    if (showing and widget.property("labelimgSurfaceRoot")
            and _surface_polish_scales.get(widget) != current_percent()):
        # Native button-box buttons can retain the application's fallback font
        # when they were constructed before their dialog's regional sheet.
        # Refresh once before showing, never on the shortcut's hot path.
        for surface in (widget, *widget.findChildren(QWidget)):
            if QWidget.window(surface) is window:
                style = surface.style()
                style.unpolish(surface)
                style.polish(surface)
        _surface_polish_scales[widget] = current_percent()


def apply_theme_palette(widget):
    palette = widget.palette()
    roles = {
        QPalette.Window: "background",
        QPalette.Base: "surface",
        QPalette.AlternateBase: "background",
        QPalette.Button: "surface",
        QPalette.Text: "text",
        QPalette.PlaceholderText: "muted",
        QPalette.WindowText: "text",
        QPalette.ButtonText: "text",
        QPalette.Light: "surface",
        QPalette.Midlight: "divider",
        QPalette.Mid: "muted",
        QPalette.Dark: "muted",
        QPalette.Shadow: "text",
        QPalette.Highlight: "selection_background",
        QPalette.HighlightedText: "selection_foreground",
        QPalette.Link: "accent",
        QPalette.LinkVisited: "accent_hover",
        QPalette.ToolTipBase: "surface",
        QPalette.ToolTipText: "text",
    }
    for channel, token in roles.items():
        palette.setColor(channel, QColor(COLORS[token]))
    for channel in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, channel, QColor(COLORS["disabled_text"]))
    for channel in (QPalette.Button, QPalette.Window):
        palette.setColor(
            QPalette.Disabled, channel, QColor(COLORS["disabled_background"])
        )
    widget.setPalette(palette)
    widget.setProperty("labelimgThemePalette", True)


def set_theme(identifier):
    """Switch registered presentation roles; never alter documents or settings."""
    global _current_theme, _applying_theme
    theme = _themes[identifier]  # Reject unknown IDs before changing anything.
    if theme is _current_theme:
        return
    _current_theme = theme
    from PyQt5.QtWidgets import QApplication

    _applying_theme = True
    try:
        app = QApplication.instance()
        if app is not None:
            surfaces = _style_surfaces(app)
            for widget in surfaces:
                if sip.isdeleted(widget):
                    continue
                if widget.property("labelimgThemePalette"):
                    apply_theme_palette(widget)
            # Invalidate inherited QSS caches before rebinding any styled root.
            for widget in surfaces:
                if (
                    not sip.isdeleted(widget)
                    and widget.property("labelimgThemeStyle") is not None
                ):
                    widget.setStyleSheet("")
            for widget in surfaces:
                if sip.isdeleted(widget):
                    continue
                template = widget.property("labelimgThemeStyle")
                if template is not None:
                    apply_theme_style(widget, theme_style(template))
            for widget in surfaces:
                if widget is not app and not sip.isdeleted(widget):
                    widget.update()
        theme_changed.emit(identifier)
    finally:
        _applying_theme = False


def appearance_theme(mode, accent_id):
    """Resolve a complete palette for one independent mode/accent combination."""
    from labelimg.ui.theme_palettes import appearance_colors, available_accents

    identifier = "appearance-" + mode + "-" + accent_id
    if identifier not in _themes:
        preset = next(
            (a for a in available_accents() if a.identifier == accent_id), None
        )
        if preset is None:
            raise KeyError(accent_id)
        colors = appearance_colors(LIGHT_THEME.colors, mode, accent_id)
        register_theme(
            Theme(
                identifier,
                mode.title() + " · " + preset.name_en,
                ("深色" if mode == "dark" else "浅色") + " · " + preset.name_zh,
                colors,
            )
        )
    return _themes[identifier]


def is_applying_theme():
    return _applying_theme
