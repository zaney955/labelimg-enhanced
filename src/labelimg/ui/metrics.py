"""Application-chrome dimensions in logical pixels; image geometry is excluded.

All conversions start from immutable 100% values. Qt alone maps the resulting
logical pixels to device pixels. ``Metric`` also keeps custom painting and hit
testing on the same scale without rewriting annotation coordinates.
"""

import math
import re

from PyQt5.QtCore import QObject, QSize, pyqtSignal


ZOOM_LEVELS = (75, 80, 90, 100, 110, 125, 150, 175, 200)
_percent = 100


class _ScaleEvents(QObject):
    changed = pyqtSignal(int)


_events = _ScaleEvents()
scale_changed = _events.changed


def current_percent():
    return _percent


def sp(value):
    """Scale a floating-point font/painting length, never a data coordinate."""
    return float(value) * _percent / 100.0


def dp(value):
    """Round a logical layout length deterministically, preserving its sign."""
    scaled = sp(value)
    return int(math.copysign(math.floor(abs(scaled) + 0.5), scaled))


def scaled_size(width, height=None):
    if isinstance(width, QSize):
        width, height = width.width(), width.height()
    return QSize(dp(width), dp(height))


class Metric:
    """An immutable design length exposed at the current application scale."""

    def __init__(self, base):
        self.base = base

    def __get__(self, instance, owner=None):
        return sp(self.base) if isinstance(self.base, float) else dp(self.base)


def scale_stylesheet(stylesheet):
    """Resolve only CSS pixel lengths, from the retained unscaled template."""
    if _percent == 100:
        return stylesheet
    return re.sub(
        r"(-?\d+(?:\.\d+)?)px\b",
        # Qt 5's font-size grammar accepts integer px only. Fractional font
        # declarations silently fall back to the inherited point-sized font.
        lambda match: str(dp(float(match[1]))) + "px",
        stylesheet,
    )


def _set_percent(percent):
    global _percent
    _percent = percent
