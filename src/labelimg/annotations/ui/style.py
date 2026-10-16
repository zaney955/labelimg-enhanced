"""Annotation label colors and input validation."""

import re

from PyQt5.QtCore import QRegExp
from PyQt5.QtGui import QColor, QRegExpValidator

from labelimg.annotations.ui.color_algorithms import (
    ALGORITHMS, FIXED, MAXIMIN, SessionColorAllocator, fixed_label_rgb,
)

LABEL_INDICATOR_FILL_ALPHA = 48


def natural_label_key(text):
    parts = []
    for part in re.split(r"(\d+)", str(text).casefold()):
        parts.append((0, int(part), len(part)) if part.isdigit() else (1, part))
    return tuple(parts), str(text)


def label_validator():
    return QRegExpValidator(QRegExp(r"^[^ \t].+"), None)


def generate_color_by_text(text):
    return QColor(*fixed_label_rgb(str(text)), 100)


def label_display_color(text):
    color = generate_color_by_text(text)
    color.setAlpha(255)
    return color


class LabelColorPalette:
    """Session-only exact-label color overrides for one annotation workspace."""

    def __init__(self, algorithm=FIXED):
        self._overrides = {}
        self._allocator = SessionColorAllocator()
        self._algorithm = algorithm if algorithm in ALGORITHMS else FIXED

    @property
    def algorithm(self):
        return self._algorithm

    def set_algorithm(self, algorithm):
        if algorithm not in ALGORITHMS:
            raise ValueError("unknown label color algorithm")
        changed = self._algorithm != algorithm
        self._algorithm = algorithm
        return changed

    def color(self, label):
        label = str(label)
        color = self._overrides.get(label)
        return QColor(color) if color is not None else self.automatic_color(label)

    def automatic_color(self, label):
        if self._algorithm == MAXIMIN:
            rgb = self._allocator.color(str(label), {
                name: color.getRgb()[:3] for name, color in self._overrides.items()
            })
            return QColor(*rgb)
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
        if changed:
            self._allocator.invalidate()
        return changed

    def restore(self, label):
        changed = self._overrides.pop(str(label), None) is not None
        if changed:
            self._allocator.invalidate()
        return changed

    def clear(self):
        changed = bool(self._overrides)
        self._overrides.clear()
        return self._allocator.clear() or changed

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
        if changed:
            self._allocator.invalidate()
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
