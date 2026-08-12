"""Runtime localization for the two supported LabelImg interface languages."""

import locale
import os
import re

try:
    from PyQt5.QtCore import (
        QObject,
        pyqtSignal,
    )
except ImportError:  # pragma: no cover - retained for the legacy Qt4 import path
    from PyQt4.QtCore import (
        QObject,
        pyqtSignal,
    )

from labelimg.localization.catalogs import CATALOGS


ENGLISH = "en"
SIMPLIFIED_CHINESE = "zh_CN"
SUPPORTED_LANGUAGES = (SIMPLIFIED_CHINESE, ENGLISH)
LANGUAGE_NAMES = {
    SIMPLIFIED_CHINESE: "简体中文",
    ENGLISH: "English",
}


def normalize_language(language):
    """Map a locale or saved preference to one supported application language."""
    if language is None:
        return ENGLISH
    primary = str(language).strip().replace("-", "_").split("_", 1)[0]
    return SIMPLIFIED_CHINESE if primary.casefold() == "zh" else ENGLISH


def system_language():
    """Resolve the first-launch language; every Chinese locale maps to zh_CN."""
    try:
        detected = locale.getlocale()[0]
    except (TypeError, ValueError):
        detected = None
    if not detected:
        detected = os.environ.get("LC_ALL") or os.environ.get("LANG")
    return normalize_language(detected)


class _LanguageState(QObject):
    changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._language = system_language()

    @property
    def language(self):
        return self._language

    def set_language(self, language):
        language = normalize_language(language)
        if language == self._language:
            return False
        self._language = language
        self.changed.emit(language)
        return True


_STATE = _LanguageState()
language_changed = _STATE.changed
def current_language():
    return _STATE.language


def set_language(language):
    return _STATE.set_language(language)


def tr(message_id, **values):
    """Translate one stable message id, falling back safely to English."""
    english = CATALOGS[ENGLISH]
    if message_id not in english:
        raise KeyError("Unknown translation id: %s" % message_id)
    template = CATALOGS.get(current_language(), english).get(
        message_id,
        english[message_id],
    )
    return template.format(**values) if values else template


def catalog_keys(language):
    return frozenset(CATALOGS[normalize_language(language)])


def localize_dialog_buttons(button_box):
    """Set application-owned QDialogButtonBox labels explicitly."""
    try:
        from PyQt5.QtWidgets import QDialogButtonBox
    except ImportError:  # pragma: no cover
        from PyQt4.QtGui import QDialogButtonBox
    messages = {
        QDialogButtonBox.Ok: "standard.ok",
        QDialogButtonBox.Cancel: "standard.cancel",
        QDialogButtonBox.Close: "standard.close",
        QDialogButtonBox.Save: "standard.save",
        QDialogButtonBox.Discard: "standard.discard",
        QDialogButtonBox.Open: "standard.open",
        QDialogButtonBox.Apply: "standard.apply",
        QDialogButtonBox.Reset: "standard.reset",
        QDialogButtonBox.RestoreDefaults: "standard.restoreDefaults",
        QDialogButtonBox.Yes: "standard.yes",
        QDialogButtonBox.No: "standard.no",
    }
    for standard_button, message_id in messages.items():
        button = button_box.button(standard_button)
        if button is not None:
            button.setText(tr(message_id))


def localize_message_box_buttons(message_box):
    """Set labels on the standard buttons currently owned by a QMessageBox."""
    try:
        from PyQt5.QtWidgets import QMessageBox
    except ImportError:  # pragma: no cover
        from PyQt4.QtGui import QMessageBox
    messages = {
        QMessageBox.Ok: "standard.ok",
        QMessageBox.Cancel: "standard.cancel",
        QMessageBox.Close: "standard.close",
        QMessageBox.Save: "standard.save",
        QMessageBox.Discard: "standard.discard",
        QMessageBox.Open: "standard.open",
        QMessageBox.Apply: "standard.apply",
        QMessageBox.Reset: "standard.reset",
        QMessageBox.RestoreDefaults: "standard.restoreDefaults",
        QMessageBox.Yes: "standard.yes",
        QMessageBox.No: "standard.no",
    }
    for standard_button, message_id in messages.items():
        button = message_box.button(standard_button)
        if button is not None:
            button.setText(tr(message_id))


def _show_message(icon, parent, title, text, buttons=None, default_button=None):
    try:
        from PyQt5.QtWidgets import QMessageBox
    except ImportError:  # pragma: no cover
        from PyQt4.QtGui import QMessageBox
    if buttons is None:
        buttons = QMessageBox.Ok
    box = QMessageBox(icon, title, text, QMessageBox.NoButton, parent)
    box.setStandardButtons(buttons)
    if default_button is not None:
        box.setDefaultButton(default_button)
    localize_message_box_buttons(box)
    box.exec_()
    return box.standardButton(box.clickedButton())


def information(parent, title, text, buttons=None, default_button=None):
    from PyQt5.QtWidgets import QMessageBox
    return _show_message(
        QMessageBox.Information, parent, title, text, buttons, default_button
    )


def question(parent, title, text, buttons=None, default_button=None):
    from PyQt5.QtWidgets import QMessageBox
    if buttons is None:
        buttons = QMessageBox.Yes | QMessageBox.No
    return _show_message(
        QMessageBox.Question, parent, title, text, buttons, default_button
    )


def warning(parent, title, text, buttons=None, default_button=None):
    from PyQt5.QtWidgets import QMessageBox
    return _show_message(
        QMessageBox.Warning, parent, title, text, buttons, default_button
    )


def critical(parent, title, text, buttons=None, default_button=None):
    from PyQt5.QtWidgets import QMessageBox
    return _show_message(
        QMessageBox.Critical, parent, title, text, buttons, default_button
    )


_HISTORY_MESSAGE_IDS = {
    "Create box": "history.create",
    "Drawing": "history.drawing",
    "Resize box": "history.resize",
    "Move box": "history.move",
    "Delete boxes": "history.delete",
    "Delete selected boxes": "history.deleteSelected",
    "Change difficult flag": "history.difficult",
    "Duplicate boxes": "history.duplicate",
    "Toggle verified": "history.verified",
    "Toggle questioned": "history.questioned",
    "Change box line color": "history.lineColor",
    "Change box fill color": "history.fillColor",
    "Copy box": "history.copy",
    "Paste boxes": "history.paste",
    "Copy previous boxes": "history.copyPrevious",
}


def translate_history_description(description):
    """Translate stable internal edit descriptions without translating labels."""
    description = " ".join(str(description or "").split())
    message_id = _HISTORY_MESSAGE_IDS.get(description)
    if message_id:
        return tr(message_id)
    match = re.fullmatch(r"Delete label group: (.*)", description)
    if match:
        return tr("history.deleteGroup", label=match.group(1))
    match = re.fullmatch(r"(?:Change label|Rename label group): (.*) → (.*)", description)
    if match:
        return tr(
            "history.changeLabel"
            if description.startswith("Change label")
            else "history.renameGroup",
            old=match.group(1),
            new=match.group(2),
        )
    return description
