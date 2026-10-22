"""Bounded processing pixels shared by current-image tool previews."""
from dataclasses import dataclass
import math

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage


@dataclass(frozen=True)
class ImagePreview:
    pixels: np.ndarray
    source_size: tuple[int, int]

    @property
    def size(self):
        return self.source_size


def preview_from_qimage(image, *, max_pixels):
    source_size = (image.width(), image.height())
    working = QImage(image)
    pixel_count = image.width() * image.height()
    if pixel_count > max_pixels:
        ratio = math.sqrt(max_pixels / float(pixel_count))
        working = image.scaled(
            max(1, int(image.width() * ratio)),
            max(1, int(image.height() * ratio)),
            Qt.KeepAspectRatio, Qt.FastTransformation)
    rgba = working.convertToFormat(QImage.Format_RGBA8888)
    pointer = rgba.bits()
    pointer.setsize(rgba.byteCount())
    rows = np.frombuffer(pointer, dtype=np.uint8).reshape(
        rgba.height(), rgba.bytesPerLine())
    pixels = rows[:, :rgba.width() * 4].reshape(rgba.height(), rgba.width(), 4)
    return ImagePreview(cv2.cvtColor(pixels, cv2.COLOR_RGBA2BGRA), source_size)
