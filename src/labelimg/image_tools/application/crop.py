"""Prepare crop image bytes and transformed annotation snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace

from labelimg.annotations import fingerprint_path
from labelimg.image_tools.domain.crop_geometry import (
    CropAnnotationResult,
    CropRegion,
    crop_pixels,
    transform_annotation_boxes,
)
from labelimg.image_tools.infrastructure.image_codec import ImageFileCodec
from labelimg.image_tools.infrastructure.recoverable_replacement import (
    PreparedImageReplacement,
)


@dataclass(frozen=True)
class PreparedCrop:
    path: str
    region: CropRegion
    image_replacement: PreparedImageReplacement
    snapshot: object
    clipped_count: int
    removed_count: int


class ImageCropProcessor:
    def __init__(self, codec=None):
        self._codec = codec or ImageFileCodec()

    def prepare(self, path, region, snapshot):
        expected = fingerprint_path(path)
        transformed = self._codec.transform(
            path,
            "crop",
            crop_box=(
                region.x,
                region.y,
                region.right,
                region.bottom,
            ),
        )
        region.validate(transformed.source_size)
        if region.is_full_image(transformed.source_size):
            raise ValueError("crop region must change the image bounds")
        annotation_result = transform_annotation_boxes(
            snapshot.boxes,
            region,
        )
        transformed_snapshot = replace(
            snapshot,
            image_size=region.size,
            boxes=annotation_result.boxes,
        )
        if transformed.output_size != region.size:
            raise ValueError("encoded crop dimensions do not match the region")
        if fingerprint_path(path) != expected:
            raise ValueError("the image changed while its crop was prepared")
        return PreparedCrop(
            path=transformed.path,
            region=region,
            image_replacement=PreparedImageReplacement(
                path=transformed.path,
                expected_fingerprint=expected,
                content=transformed.content,
            ),
            snapshot=transformed_snapshot,
            clipped_count=annotation_result.clipped_count,
            removed_count=annotation_result.removed_count,
        )
