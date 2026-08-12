"""Prepare annotation resources that accompany a geometry-changing crop."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import tempfile

from labelimg.annotations.domain.model import (
    AnnotationBox,
    AnnotationDocument,
    AnnotationFormat,
)
from labelimg.annotations.infrastructure.storage import fingerprint_path
from labelimg.annotations.infrastructure.document import save_document
from labelimg.annotations.application.workspace import annotation_resources
from labelimg.image_tools.infrastructure.recoverable_replacement import (
    PreparedImageReplacement,
)


@dataclass(frozen=True)
class PreparedCropAnnotations:
    document: AnnotationDocument
    replacements: tuple[PreparedImageReplacement, ...]


def prepare_crop_annotations(
    snapshot,
    image_content,
    annotation_target,
    *,
    class_names=(),
    create_ml_record_name=None,
):
    """Serialize one transformed snapshot without touching live resources."""
    target = os.path.abspath(os.fspath(annotation_target))
    annotation_format = AnnotationFormat.from_path(target)
    document = AnnotationDocument(
        image_path=snapshot.image_key,
        image_data=image_content,
        boxes=tuple(
            AnnotationBox(
                label=box.label,
                points=box.points,
                line_color=box.line_rgba,
                fill_color=box.fill_rgba,
                difficult=box.difficult,
            )
            for box in snapshot.boxes
        ),
        class_names=tuple(class_names),
        verified=snapshot.verified,
        questioned=snapshot.questioned,
        create_ml_record_name=create_ml_record_name,
    )

    with tempfile.TemporaryDirectory(prefix="labelimg-crop-") as directory:
        staged_target = os.path.join(directory, os.path.basename(target))
        if (
            annotation_format is AnnotationFormat.CREATE_ML
            and os.path.isfile(target)
        ):
            shutil.copyfile(target, staged_target)
        save_document(document, staged_target, annotation_format)
        staged_resources = annotation_resources(
            annotation_format,
            staged_target,
        )
        live_resources = annotation_resources(annotation_format, target)
        replacements = []
        for live_path, staged_path in zip(live_resources, staged_resources):
            if not os.path.isfile(staged_path):
                continue
            with open(staged_path, "rb") as source:
                content = source.read()
            existing = None
            if os.path.isfile(live_path):
                with open(live_path, "rb") as source:
                    existing = source.read()
            if content == existing:
                continue
            if existing is None:
                raise ValueError(
                    "crop cannot create a new annotation resource; "
                    "save annotations before cropping: %s" % live_path
                )
            replacements.append(PreparedImageReplacement(
                path=live_path,
                expected_fingerprint=fingerprint_path(live_path),
                content=content,
            ))
    return PreparedCropAnnotations(document, tuple(replacements))
