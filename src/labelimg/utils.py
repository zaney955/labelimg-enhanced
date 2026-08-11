from math import sqrt
from labelimg.ustr import ustr
import hashlib
import re
import sys

try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
    QT5 = True
except ImportError:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *
    QT5 = False


def new_icon(icon):
    return QIcon(':/' + icon)


def new_button(text, icon=None, slot=None):
    b = QPushButton(text)
    if icon is not None:
        b.setIcon(new_icon(icon))
    if slot is not None:
        b.clicked.connect(slot)
    return b


def _plain_action_text(text):
    """Return an action label without menu-only shortcut decoration."""
    text = str(text or "")
    label, _separator, _manual_shortcut = text.partition("\t")
    escaped_ampersand = "\0"
    label = label.replace("&&", escaped_ampersand)
    label = label.replace("&", "").replace(escaped_ampersand, "&")
    label = re.sub(r"(?:\([A-Za-z]\)|（[A-Za-z]）)$", "", label)
    return label.strip()


def format_action_tooltip(text, shortcuts=()):
    """Build a concise localized tooltip from an action label and shortcuts."""
    _label, separator, manual_shortcut = str(text or "").partition("\t")
    if isinstance(shortcuts, (str, QKeySequence)):
        shortcuts = (shortcuts,)
    shortcut_texts = []
    for shortcut in shortcuts or ():
        shortcut_text = (
            shortcut.toString()
            if isinstance(shortcut, QKeySequence)
            else str(shortcut)
        ).strip()
        if shortcut_text and shortcut_text not in shortcut_texts:
            shortcut_texts.append(shortcut_text)
    if not shortcut_texts and separator and manual_shortcut.strip():
        shortcut_texts.append(manual_shortcut.strip())
    label = _plain_action_text(text)
    if not shortcut_texts:
        return label
    from labelimg.i18n import tr
    return tr(
        "action.tooltipWithShortcut",
        action=label,
        shortcut=" / ".join(shortcut_texts),
    )


def set_action_copy(action, text=None, tip=None):
    """Keep command, tooltip, and status explanation in distinct roles."""
    if text is not None:
        action.setText(text)
    action.setToolTip(
        format_action_tooltip(action.text(), action.shortcuts())
    )
    action.setStatusTip(
        tip if tip is not None else _plain_action_text(action.text())
    )


def new_action(parent, text, slot=None, shortcut=None, icon=None,
               tip=None, checkable=False, enabled=True):
    """Create a new action and assign callbacks, shortcuts, etc."""
    a = QAction(text, parent)
    if icon is not None:
        a.setIcon(new_icon(icon))
    if shortcut is not None:
        if isinstance(shortcut, (list, tuple)):
            a.setShortcuts(shortcut)
        else:
            a.setShortcut(shortcut)
    set_action_copy(a, tip=tip)
    if slot is not None:
        a.triggered.connect(slot)
    if checkable:
        a.setCheckable(True)
    a.setEnabled(enabled)
    return a


def add_actions(widget, actions):
    for action in actions:
        if action is None:
            widget.addSeparator()
        elif isinstance(action, QMenu):
            widget.addMenu(action)
        else:
            widget.addAction(action)


def label_validator():
    return QRegExpValidator(QRegExp(r'^[^ \t].+'), None)


class Struct(object):

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def distance(p):
    return sqrt(p.x() * p.x() + p.y() * p.y())


def format_shortcut(text):
    mod, key = text.split('+', 1)
    return '<b>%s</b>+<b>%s</b>' % (mod, key)


def generate_color_by_text(text):
    s = ustr(text)
    hash_code = int(hashlib.sha256(s.encode('utf-8')).hexdigest(), 16)
    r = int((hash_code / 255) % 255)
    g = int((hash_code / 65025) % 255)
    b = int((hash_code / 16581375) % 255)
    return QColor(r, g, b, 100)


def label_display_color(text):
    color = generate_color_by_text(text)
    color.setAlpha(255)
    return color


def have_qstring():
    """p3/qt5 get rid of QString wrapper as py3 has native unicode str type"""
    return not (sys.version_info.major >= 3 or QT_VERSION_STR.startswith('5.'))


def util_qt_strlistclass():
    return QStringList if have_qstring() else list


def natural_sort(list, key=lambda s:s):
    """
    Sort the list into natural alphanumeric order.
    """
    def get_alphanum_key_func(key):
        convert = lambda text: int(text) if text.isdigit() else text
        return lambda s: [convert(c) for c in re.split('([0-9]+)', key(s))]
    sort_key = get_alphanum_key_func(key)
    list.sort(key=sort_key)


# QT4 has a trimmed method, in QT5 this is called strip
if QT5:
    def trimmed(text):
        return text.strip()
else:
    def trimmed(text):
        return text.trimmed()
