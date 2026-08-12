"""Prepare geometry-changing image and annotation replacements."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import os

import cv2
import numpy as np

from labelimg.annotations import (
    AnnotationBoxState,
    AnnotationSnapshot,
    fingerprint_image,
    fingerprint_path,
)
from labelimg.image_tools.infrastructure.image_codec import ImageFileCodec
from labelimg.image_tools.infrastructure.recoverable_replacement import (
    PreparedImageReplacement,
)


class GeometryOperation(Enum):
    ROTATE_CLOCKWISE = "rotate-clockwise"
    ROTATE_COUNTERCLOCKWISE = "rotate-counterclockwise"
    ROTATE_180 = "rotate-180"
    FLIP_HORIZONTAL = "flip-horizontal"
    FLIP_VERTICAL = "flip-vertical"
    RESIZE = "resize"


@dataclass(frozen=True)
class PreparedGeometryTransform:
    path: str
    operation: GeometryOperation
    image_replacement: PreparedImageReplacement
    snapshot: object
    original_pixels: np.ndarray
    result_pixels: np.ndarray


class ImageGeometryProcessor:
    """Transform one image and its immutable annotation snapshot together."""

    def __init__(self, codec=None):
        self._codec = codec or ImageFileCodec()

    def prepare(self, path, operation, snapshot, *, output_size=None):
        operation = GeometryOperation(operation)
        loaded = self._codec.load(path)
        if tuple(snapshot.image_size) != tuple(loaded.size):
            raise ValueError(
                "annotation dimensions do not match the image dimensions"
            )
        expected = fingerprint_path(loaded.path)
        result_pixels, result_size = transform_pixels(
            loaded.pixels,
            operation,
            output_size=output_size,
        )
        boxes = transform_annotation_boxes(
            snapshot.boxes,
            loaded.size,
            operation,
            result_size,
        )
        content = self._codec.encode(
            loaded,
            result_pixels,
            output_size=result_size,
        )
        if fingerprint_path(loaded.path) != expected:
            raise ValueError("the image changed while its transform was prepared")
        return PreparedGeometryTransform(
            path=loaded.path,
            operation=operation,
            image_replacement=PreparedImageReplacement(
                path=loaded.path,
                expected_fingerprint=expected,
                content=content,
            ),
            snapshot=replace(
                snapshot,
                image_size=result_size,
                boxes=boxes,
            ),
            original_pixels=loaded.pixels.copy(),
            result_pixels=result_pixels,
        )


def annotation_snapshot_from_document(document, image_size):
    """Build a geometry-ready immutable snapshot from a stored document."""
    return AnnotationSnapshot(
        image_key=os.fspath(document.image_path),
        image_size=tuple(image_size),
        boxes=tuple(
            AnnotationBoxState(
                session_id=index,
                label=box.label,
                points=tuple(tuple(point) for point in box.points),
                line_rgba=box.line_color,
                fill_rgba=box.fill_color,
                difficult=box.difficult,
            )
            for index, box in enumerate(document.boxes, 1)
        ),
        verified=bool(document.verified),
        questioned=bool(document.questioned),
        image_fingerprint=fingerprint_image(document.image_path, image_size),
    )


def transform_pixels(pixels, operation, *, output_size=None):
    pixels = np.asarray(pixels)
    operation = GeometryOperation(operation)
    height, width = pixels.shape[:2]
    if operation is GeometryOperation.ROTATE_CLOCKWISE:
        return np.ascontiguousarray(np.rot90(pixels, 3)), (height, width)
    if operation is GeometryOperation.ROTATE_COUNTERCLOCKWISE:
        return np.ascontiguousarray(np.rot90(pixels, 1)), (height, width)
    if operation is GeometryOperation.ROTATE_180:
        return np.ascontiguousarray(np.rot90(pixels, 2)), (width, height)
    if operation is GeometryOperation.FLIP_HORIZONTAL:
        return np.ascontiguousarray(np.flip(pixels, axis=1)), (width, height)
    if operation is GeometryOperation.FLIP_VERTICAL:
        return np.ascontiguousarray(np.flip(pixels, axis=0)), (width, height)
    if output_size is None:
        raise ValueError("resize requires an output size")
    output_width, output_height = (int(value) for value in output_size)
    if output_width < 1 or output_height < 1:
        raise ValueError("resize dimensions must be positive")
    aspect_error = abs(
        output_width * height - output_height * width
    )
    rounding_tolerance = (width + height) / 2.0
    if aspect_error > rounding_tolerance:
        raise ValueError("resize must preserve the source aspect ratio")
    interpolation = (
        cv2.INTER_AREA
        if output_width < width or output_height < height
        else cv2.INTER_CUBIC
    )
    resized = cv2.resize(
        pixels,
        (output_width, output_height),
        interpolation=interpolation,
    )
    return np.ascontiguousarray(resized), (output_width, output_height)


def transform_annotation_boxes(
    boxes,
    source_size,
    operation,
    output_size,
):
    operation = GeometryOperation(operation)
    source_width, source_height = source_size
    output_width, output_height = output_size
    transformed = []
    for box in boxes:
        points = tuple(
            _transform_point(
                point,
                source_width,
                source_height,
                operation,
                output_width,
                output_height,
            )
            for point in box.points
        )
        left = min(point[0] for point in points)
        top = min(point[1] for point in points)
        right = max(point[0] for point in points)
        bottom = max(point[1] for point in points)
        transformed.append(
            replace(
                box,
                points=(
                    (left, top),
                    (right, top),
                    (right, bottom),
                    (left, bottom),
                ),
            )
        )
    return tuple(transformed)


def _transform_point(
    point,
    width,
    height,
    operation,
    output_width,
    output_height,
):
    x, y = point
    if operation is GeometryOperation.ROTATE_CLOCKWISE:
        return height - y, x
    if operation is GeometryOperation.ROTATE_COUNTERCLOCKWISE:
        return y, width - x
    if operation is GeometryOperation.ROTATE_180:
        return width - x, height - y
    if operation is GeometryOperation.FLIP_HORIZONTAL:
        return width - x, y
    if operation is GeometryOperation.FLIP_VERTICAL:
        return x, height - y
    return (
        x * output_width / width,
        y * output_height / height,
    )
