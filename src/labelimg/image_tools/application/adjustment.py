"""Composable, metadata-preserving pixel corrections."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
import os

import cv2
import numpy as np

from labelimg.annotations import fingerprint_path
from labelimg.image_tools.infrastructure.image_codec import ImageFileCodec
from labelimg.image_tools.infrastructure.recoverable_replacement import (
    PreparedImageReplacement,
)


@dataclass(frozen=True)
class ImageAdjustmentOptions:
    brightness: int = 0
    contrast: float = 1.0
    gamma: float = 1.0
    grayscale: bool = False

    def __post_init__(self):
        if not -100 <= int(self.brightness) <= 100:
            raise ValueError("brightness must be between -100 and 100")
        if not 0.1 <= float(self.contrast) <= 3.0:
            raise ValueError("contrast must be between 0.1 and 3.0")
        if not 0.1 <= float(self.gamma) <= 5.0:
            raise ValueError("gamma must be between 0.1 and 5.0")


@dataclass(frozen=True)
class PreparedImageAdjustment:
    path: str
    options: ImageAdjustmentOptions
    original_pixels: np.ndarray | None
    result_pixels: np.ndarray | None
    replacement: PreparedImageReplacement | None

    @property
    def changed(self):
        return self.replacement is not None


class ImageAdjustmentProcessor:
    def __init__(self, codec=None):
        self._codec = codec or ImageFileCodec()

    def prepare(
        self,
        path,
        options=None,
        *,
        retain_pixels=True,
        retain_original_pixels=None,
    ):
        path = os.path.abspath(os.fspath(path))
        options = options or ImageAdjustmentOptions()
        retain_original_pixels = (
            retain_pixels
            if retain_original_pixels is None
            else bool(retain_original_pixels)
        )
        expected = fingerprint_path(path)
        loaded = self._codec.load(path)
        result = apply_adjustments(loaded.pixels, options)
        replacement = None
        if not np.array_equal(result, loaded.pixels):
            content = self._codec.encode(loaded, result)
            if fingerprint_path(path) != expected:
                raise ValueError("the image changed while adjustments were prepared")
            replacement = PreparedImageReplacement(path, expected, content)
        return PreparedImageAdjustment(
            path=path,
            options=options,
            original_pixels=(
                loaded.pixels.copy() if retain_original_pixels else None
            ),
            result_pixels=(result if retain_pixels else None),
            replacement=replacement,
        )


def apply_adjustments(pixels, options):
    options = options or ImageAdjustmentOptions()
    source = np.asarray(pixels)
    has_alpha = source.ndim == 3 and source.shape[2] == 4
    if has_alpha:
        color = source[..., :3]
    else:
        color = source

    has_lookup = (
        options.contrast != 1.0
        or options.brightness
        or options.gamma != 1.0
    )
    if has_lookup:
        table = _adjustment_lut(
            int(options.brightness),
            float(options.contrast),
            float(options.gamma),
        )
        if has_alpha and not options.grayscale:
            rgba_table = _rgba_adjustment_lut(
                int(options.brightness),
                float(options.contrast),
                float(options.gamma),
            )
            return np.ascontiguousarray(cv2.LUT(source, rgba_table))
        color = cv2.LUT(color, table)
    if options.grayscale and color.ndim == 3:
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    if has_alpha:
        result = np.empty_like(source)
        result[..., :3] = color
        result[..., 3] = source[..., 3]
        return np.ascontiguousarray(result, dtype=np.uint8)
    if color is source:
        return np.ascontiguousarray(source.copy(), dtype=np.uint8)
    return np.ascontiguousarray(color, dtype=np.uint8)


def suggest_auto_adjustment(pixels):
    """Suggest visible brightness, contrast, and Gamma control values.

    Statistics come from luminance so every color channel receives the same
    correction curve. Fully transparent pixels are excluded because their RGB
    bytes are not visible. The suggestion is intentionally quantized to the
    ranges and steps exposed by the adjustment dialog.
    """
    source = np.asarray(pixels)
    samples = _visible_luminance_samples(source)
    if not samples.size:
        return ImageAdjustmentOptions()

    low, median, high = np.percentile(samples, (1.0, 50.0, 99.0))
    if high - low < 8.0:
        brightness = _clamp(round((127.5 - median) / 2.55), -100, 100)
        return ImageAdjustmentOptions(brightness=brightness)

    contrast = _quantize(
        _clamp(245.0 / (high - low), 0.1, 3.0),
        step=0.1,
    )
    brightness = _clamp(
        round((5.0 - contrast * low) / 2.55),
        -100,
        100,
    )
    mapped_median = np.clip(
        median * contrast + brightness * 2.55,
        0.0,
        255.0,
    ) / 255.0
    if 0.0 < mapped_median < 1.0:
        gamma = math.log(mapped_median) / math.log(0.5)
        gamma = _quantize(_clamp(gamma, 0.1, 5.0), step=0.1)
    else:
        gamma = 1.0
    return ImageAdjustmentOptions(
        brightness=brightness,
        contrast=contrast,
        gamma=gamma,
    )


def _visible_luminance_samples(source):
    if source.ndim == 2:
        luminance = source
        visible = None
    elif source.ndim == 3 and source.shape[2] == 1:
        luminance = source[..., 0]
        visible = None
    elif source.ndim == 3 and source.shape[2] in (3, 4):
        luminance = cv2.cvtColor(source[..., :3], cv2.COLOR_BGR2GRAY)
        visible = source[..., 3] > 0 if source.shape[2] == 4 else None
    else:
        raise ValueError("pixels must be grayscale, BGR, or BGRA")
    if visible is not None:
        luminance = luminance[visible]
    return np.asarray(luminance, dtype=np.float32).reshape(-1)


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _quantize(value, *, step):
    return round(value / step) * step


@lru_cache(maxsize=256)
def _adjustment_lut(brightness, contrast, gamma):
    table = np.arange(256, dtype=np.float32)
    if contrast != 1.0 or brightness:
        table = np.clip(
            table * contrast + brightness * 2.55,
            0,
            255,
        ).round()
    if gamma != 1.0:
        table = np.rint(
            np.power(table / 255.0, 1.0 / gamma) * 255.0
        )
    return table.astype(np.uint8)


@lru_cache(maxsize=256)
def _rgba_adjustment_lut(brightness, contrast, gamma):
    color = _adjustment_lut(brightness, contrast, gamma)
    table = np.empty((256, 1, 4), dtype=np.uint8)
    table[:, 0, :3] = color[:, None]
    table[:, 0, 3] = np.arange(256, dtype=np.uint8)
    return table
