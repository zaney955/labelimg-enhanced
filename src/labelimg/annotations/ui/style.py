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


def trimmed(text):
    return text.strip()
