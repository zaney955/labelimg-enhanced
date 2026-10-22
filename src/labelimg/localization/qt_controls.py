"""Translate Qt-owned color controls alongside application-owned UI text."""

from PyQt5.QtCore import QTranslator
from PyQt5.QtWidgets import QApplication

from labelimg.localization.runtime import (
    SIMPLIFIED_CHINESE,
    current_language,
    language_changed,
    tr,
)

_COLOR_MESSAGES = {
    "Select Color": "qtColor.title",
    "&Basic colors": "qtColor.basic",
    "&Custom colors": "qtColor.custom",
    "&Pick Screen Color": "qtColor.pick",
    "&Add to Custom Colors": "qtColor.add",
    "Hu&e:": "qtColor.hue",
    "&Sat:": "qtColor.saturation",
    "&Val:": "qtColor.value",
    "&Red:": "qtColor.red",
    "&Green:": "qtColor.green",
    "Bl&ue:": "qtColor.blue",
    "A&lpha channel:": "qtColor.alpha",
    "&HTML:": "qtColor.html",
}
_STANDARD_MESSAGES = {
    "OK": "standard.ok",
    "Cancel": "standard.cancel",
    "Close": "standard.close",
    "Save": "standard.save",
    "Discard": "standard.discard",
    "Open": "standard.open",
    "Apply": "standard.apply",
    "Reset": "standard.reset",
    "Restore Defaults": "standard.restoreDefaults",
    "Yes": "standard.yes",
    "No": "standard.no",
}


class _QtControlsTranslator(QTranslator):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        language_changed.connect(self.refresh)

    def isEmpty(self):
        return False

    def translate(self, context, source, disambiguation=None, n=-1):
        if current_language() != SIMPLIFIED_CHINESE:
            return None
        messages = (
            _COLOR_MESSAGES
            if context == "QColorDialog"
            else (
                _STANDARD_MESSAGES
                if context in ("QPlatformTheme", "QDialogButtonBox", "QMessageBox")
                else {}
            )
        )
        message = messages.get(source)
        return tr(message) if message is not None else None

    def refresh(self, _language=None):
        self.app.removeTranslator(self)
        self.app.installTranslator(self)


def install_qt_control_translations():
    app = QApplication.instance()
    if app is not None and not hasattr(app, "_labelimg_qt_controls_translator"):
        translator = _QtControlsTranslator(app)
        app._labelimg_qt_controls_translator = translator
        app.installTranslator(translator)
