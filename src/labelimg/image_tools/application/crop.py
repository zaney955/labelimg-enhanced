"""Prepare crop image bytes and transformed annotation snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace

from labelimg.annotations.infrastructure.storage import fingerprint_path
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
        loaded = self._codec.load(path)
        region.validate(loaded.size)
        if region.is_full_image(loaded.size):
            raise ValueError("crop region must change the image bounds")
        pixels = crop_pixels(loaded.pixels, region)
        annotation_result = transform_annotation_boxes(
            snapshot.boxes,
            region,
        )
        transformed_snapshot = replace(
            snapshot,
            image_size=region.size,
            boxes=annotation_result.boxes,
        )
        content = self._codec.encode(
            loaded,
            pixels,
            output_size=region.size,
        )
        return PreparedCrop(
            path=loaded.path,
            region=region,
            image_replacement=PreparedImageReplacement(
                path=loaded.path,
                expected_fingerprint=fingerprint_path(loaded.path),
                content=content,
            ),
            snapshot=transformed_snapshot,
            clipped_count=annotation_result.clipped_count,
            removed_count=annotation_result.removed_count,
        )
