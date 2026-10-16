"""Image-independent label colors in sRGB, measured in OKLab.

The versioned fixed mapping is a function of exact UTF-8 label text only.
Session allocation greedily maximizes the minimum distance in a bounded pool;
it never moves an existing assignment. Neither algorithm inspects image pixels.
"""

from functools import lru_cache
import hashlib
from math import cos, radians, sin


FIXED = "fixed"
MAXIMIN = "maximin"
ALGORITHMS = (FIXED, MAXIMIN)


def _label_hash(label):
    return hashlib.sha256(b"labelimg-color-v1\0" + str(label).encode("utf-8")).digest()


def _linear_rgb(lightness, chroma, hue):
    angle = radians(hue)
    a, b = chroma * cos(angle), chroma * sin(angle)
    l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def oklch_to_rgb(lightness, chroma, hue):
    """Reduce chroma at fixed lightness/hue until inside the sRGB gamut."""
    linear = _linear_rgb(lightness, chroma, hue)
    if not all(0 <= value <= 1 for value in linear):
        low, high = 0.0, chroma
        for _ in range(24):
            middle = (low + high) / 2
            if all(0 <= value <= 1 for value in _linear_rgb(lightness, middle, hue)):
                low = middle
            else:
                high = middle
        linear = _linear_rgb(lightness, low, hue)

    def encode(value):
        value = max(0.0, min(1.0, value))
        srgb = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
        return round(srgb * 255)

    return tuple(encode(value) for value in linear)


def rgb_to_oklab(rgb):
    """Measure the final quantized sRGB color, including any gamut reduction."""
    def decode(value):
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (decode(value) for value in rgb)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    )


def distance_squared(first, second):
    return sum((a - b) ** 2 for a, b in zip(first, second))


@lru_cache(maxsize=4096)
def fixed_label_rgb(label):
    digest = _label_hash(label)
    hue = int.from_bytes(digest[:4], "big") * 360 / (1 << 32)
    lightness = 0.70 + int.from_bytes(digest[4:6], "big") * 0.12 / 65535
    chroma = 0.14 + int.from_bytes(digest[6:8], "big") * 0.06 / 65535
    return oklch_to_rgb(lightness, chroma, hue)


@lru_cache(maxsize=1)
def candidate_colors():
    # Stable order, no duplicate RGB values after gamut mapping/quantization.
    rgbs = dict.fromkeys(
        oklch_to_rgb(lightness, chroma, hue)
        for lightness in (0.68, 0.75, 0.82)
        for chroma in (0.12, 0.17, 0.22)
        for hue in range(0, 360, 5)
    )
    return tuple((rgb, rgb_to_oklab(rgb)) for rgb in rgbs)


class SessionColorAllocator:
    """Append-only assignments; overrides affect future allocations only."""

    def __init__(self):
        self._assigned = {}
        self._nearest = None

    def clear(self):
        changed = bool(self._assigned)
        self._assigned.clear()
        self.invalidate()
        return changed

    def invalidate(self):
        self._nearest = None

    def _observe(self, rgb):
        lab = rgb_to_oklab(rgb)
        self._nearest = [
            min(previous, distance_squared(candidate, lab))
            for previous, (_rgb, candidate) in zip(self._nearest, candidate_colors())
        ]

    def color(self, label, overrides):
        if label in self._assigned:
            return self._assigned[label]
        pool = candidate_colors()
        if self._nearest is None:
            self._nearest = [float("inf")] * len(pool)
            for rgb in (self._assigned | overrides).values():
                self._observe(rgb)
        # The full label breaks equal-distance ties without process-random hash().
        start = int.from_bytes(_label_hash(label)[:4], "big") % len(pool)
        index = max(
            range(len(pool)),
            key=lambda index: (self._nearest[index], -((index - start) % len(pool))),
        )
        rgb = pool[index][0]
        self._assigned[label] = rgb
        if label not in overrides:
            self._observe(rgb)
        return rgb
