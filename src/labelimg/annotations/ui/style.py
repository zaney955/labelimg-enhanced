"""Annotation label colors and input validation."""

import hashlib

from PyQt5.QtCore import QRegExp
from PyQt5.QtGui import QColor, QRegExpValidator


def label_validator():
    return QRegExpValidator(QRegExp(r"^[^ \t].+"), None)


def generate_color_by_text(text):
    hash_code = int(hashlib.sha256(str(text).encode("utf-8")).hexdigest(), 16)
    red = int((hash_code / 255) % 255)
    green = int((hash_code / 65025) % 255)
    blue = int((hash_code / 16581375) % 255)
    return QColor(red, green, blue, 100)


def label_display_color(text):
    color = generate_color_by_text(text)
    color.setAlpha(255)
    return color


class LabelColorPalette:
    """Session-only exact-label color overrides for one annotation workspace."""

    def __init__(self):
        self._overrides = {}

    def color(self, label):
        label = str(label)
        color = self._overrides.get(label)
        return QColor(color) if color is not None else label_display_color(label)

    def automatic_color(self, label):
        return label_display_color(str(label))

    def override(self, label):
        color = self._overrides.get(str(label))
        return QColor(color) if color is not None else None

    def set_color(self, label, color):
        label = str(label)
        if not label:
            raise ValueError("label must not be empty")
        color = QColor(color)
        if not color.isValid():
            raise ValueError("color must be valid")
        color.setAlpha(255)
        changed = self._overrides.get(label) != color
        self._overrides[label] = color
        return changed

    def restore(self, label):
        return self._overrides.pop(str(label), None) is not None

    def clear(self):
        changed = bool(self._overrides)
        self._overrides.clear()
        return changed

    def replace(self, overrides):
        replacement = {}
        for label, color in dict(overrides).items():
            label = str(label)
            color = QColor(color)
            if not label or not color.isValid():
                raise ValueError("palette entries require a label and color")
            color.setAlpha(255)
            replacement[label] = color
        changed = replacement != self._overrides
        self._overrides = replacement
        return changed

    @property
    def labels(self):
        return tuple(self._overrides)

    def snapshot(self):
        return {
            label: QColor(color)
            for label, color in self._overrides.items()
        }


def trimmed(text):
    return text.strip()
