"""Qt-free and codec-free image crop geometry."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True)
class CropRegion:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height

    @property
    def size(self):
        return self.width, self.height

    def validate(self, image_size):
        image_width, image_height = image_size
        if self.width < 1 or self.height < 1:
            raise ValueError("crop region must be at least 1 by 1 pixel")
        if self.x < 0 or self.y < 0:
            raise ValueError("crop region must start inside the image")
        if self.right > image_width or self.bottom > image_height:
            raise ValueError("crop region must remain inside the image")
        return self

    def is_full_image(self, image_size):
        return (
            self.x == 0
            and self.y == 0
            and self.size == tuple(image_size)
        )


@dataclass(frozen=True)
class CropAnnotationResult:
    boxes: tuple
    clipped_count: int
    removed_count: int
    retained_ids: tuple


def crop_pixels(pixels, region):
    pixels = np.asarray(pixels)
    region.validate((pixels.shape[1], pixels.shape[0]))
    return np.ascontiguousarray(
        pixels[region.y:region.bottom, region.x:region.right]
    )


def transform_annotation_boxes(boxes, region):
    transformed = []
    retained_ids = []
    clipped = 0
    removed = 0
    for box in boxes:
        x_values = [point[0] for point in box.points]
        y_values = [point[1] for point in box.points]
        left = max(min(x_values), region.x)
        top = max(min(y_values), region.y)
        right = min(max(x_values), region.right)
        bottom = min(max(y_values), region.bottom)
        if right <= left or bottom <= top:
            removed += 1
            continue
        original_bounds = (
            min(x_values),
            min(y_values),
            max(x_values),
            max(y_values),
        )
        if (left, top, right, bottom) != original_bounds:
            clipped += 1
        points = (
            (left - region.x, top - region.y),
            (right - region.x, top - region.y),
            (right - region.x, bottom - region.y),
            (left - region.x, bottom - region.y),
        )
        transformed.append(replace(box, points=points))
        session_id = getattr(box, "session_id", None)
        if session_id is not None:
            retained_ids.append(session_id)
    return CropAnnotationResult(
        boxes=tuple(transformed),
        clipped_count=clipped,
        removed_count=removed,
        retained_ids=tuple(retained_ids),
    )
