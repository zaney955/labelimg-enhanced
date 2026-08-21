"""Composable, metadata-preserving pixel corrections."""

from __future__ import annotations

from dataclasses import dataclass
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
    auto_contrast: bool = False
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

    def prepare(self, path, options=None, *, retain_pixels=True):
        path = os.path.abspath(os.fspath(path))
        options = options or ImageAdjustmentOptions()
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
            original_pixels=(loaded.pixels.copy() if retain_pixels else None),
            result_pixels=(result if retain_pixels else None),
            replacement=replacement,
        )


def apply_adjustments(pixels, options):
    options = options or ImageAdjustmentOptions()
    source = np.asarray(pixels)
    result = source.copy()
    has_alpha = result.ndim == 3 and result.shape[2] == 4
    if has_alpha:
        color = result[..., :3]
    else:
        color = result

    if options.auto_contrast:
        color = _auto_contrast(color)
    if (
        options.contrast != 1.0
        or options.brightness
        or options.gamma != 1.0
    ):
        table = np.arange(256, dtype=np.float32)
        if options.contrast != 1.0 or options.brightness:
            table = np.clip(
                table * float(options.contrast)
                + float(options.brightness) * 2.55,
                0,
                255,
            ).round()
        if options.gamma != 1.0:
            table = np.array(
                [
                    round(
                        ((value / 255.0) ** (1.0 / float(options.gamma)))
                        * 255
                    )
                    for value in table
                ],
                dtype=np.uint8,
            )
        else:
            table = table.astype(np.uint8)
        color = cv2.LUT(color, table)
    if options.grayscale and color.ndim == 3:
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    if has_alpha:
        result[..., :3] = color
    else:
        result = color
    return np.ascontiguousarray(result, dtype=np.uint8)


def _auto_contrast(pixels):
    pixels = np.asarray(pixels)
    if pixels.ndim == 2:
        return _stretch_channel(pixels)
    return np.dstack(
        tuple(_stretch_channel(pixels[..., index]) for index in range(3))
    )


def _stretch_channel(channel):
    low = int(channel.min())
    high = int(channel.max())
    if high <= low:
        return channel.copy()
    table = np.clip(
        (np.arange(256, dtype=np.float32) - low)
        * (255.0 / (high - low)),
        0,
        255,
    ).round().astype(np.uint8)
    return cv2.LUT(channel, table)
