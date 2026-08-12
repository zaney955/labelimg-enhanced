"""Shared construction and presentation helpers for Qt actions."""

import re

from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import QAction, QMenu, QPushButton

from labelimg.localization.runtime import tr


def new_icon(icon):
    return QIcon(":/" + icon)


def new_button(text, icon=None, slot=None):
    button = QPushButton(text)
    if icon is not None:
        button.setIcon(new_icon(icon))
    if slot is not None:
        button.clicked.connect(slot)
    return button


def plain_action_text(text):
    text = str(text or "")
    label, _separator, _manual_shortcut = text.partition("\t")
    escaped_ampersand = "\0"
    label = label.replace("&&", escaped_ampersand)
    label = label.replace("&", "").replace(escaped_ampersand, "&")
    label = re.sub(r"(?:\([A-Za-z]\)|（[A-Za-z]）)$", "", label)
    return label.strip()


def format_action_tooltip(text, shortcuts=()):
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
    label = plain_action_text(text)
    if not shortcut_texts:
        return label
    return tr(
        "action.tooltipWithShortcut",
        action=label,
        shortcut=" / ".join(shortcut_texts),
    )


def set_action_copy(action, text=None, tip=None):
    if text is not None:
        action.setText(text)
    action.setToolTip(format_action_tooltip(action.text(), action.shortcuts()))
    action.setStatusTip(tip if tip is not None else plain_action_text(action.text()))


def new_action(
    parent,
    text,
    slot=None,
    shortcut=None,
    icon=None,
    tip=None,
    checkable=False,
    enabled=True,
):
    action = QAction(text, parent)
    if icon is not None:
        action.setIcon(new_icon(icon))
    if shortcut is not None:
        if isinstance(shortcut, (list, tuple)):
            action.setShortcuts(shortcut)
        else:
            action.setShortcut(shortcut)
    set_action_copy(action, tip=tip)
    if slot is not None:
        action.triggered.connect(slot)
    if checkable:
        action.setCheckable(True)
    action.setEnabled(enabled)
    return action


def add_actions(widget, actions):
    for action in actions:
        if action is None:
            widget.addSeparator()
        elif isinstance(action, QMenu):
            widget.addMenu(action)
        else:
            widget.addAction(action)


def format_shortcut(text):
    modifier, key = text.split("+", 1)
    return "<b>%s</b>+<b>%s</b>" % (modifier, key)
