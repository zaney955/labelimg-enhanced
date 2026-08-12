"""Commit and recover image processing through one deep module."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import os
import uuid

from labelimg.annotations.domain.model import AnnotationFormat
from labelimg.annotations.infrastructure.storage import fingerprint_image, fingerprint_path
from labelimg.annotations.application.workspace import annotation_resources
from labelimg.image_tools.application.crop_annotations import prepare_crop_annotations
from labelimg.image_tools.application.crop import ImageCropProcessor
from labelimg.image_tools.application.adjustment import ImageAdjustmentProcessor
from labelimg.image_tools.application.geometry_transform import (
    ImageGeometryProcessor,
    annotation_snapshot_from_document,
)
from labelimg.image_tools.infrastructure.image_codec import ImageFileCodec


class ImageProcessingProjectionKind(Enum):
    """Observable projection required after one committed operation."""

    PIXEL_COMMIT = "pixel-commit"
    CURRENT_GEOMETRY_COMMIT = "current-geometry-commit"
    GEOMETRY_BATCH_COMMIT = "geometry-batch-commit"
    RECOVERY = "recovery"
    PROJECTION_FAILED = "projection-failed"


class ImageProcessingProjectionError(RuntimeError):
    """Committed files could not be published as one editable state."""


@dataclass(frozen=True)
class GeometryTransformChange:
    paths: tuple
    operation: object
    current_path: str | None = None
    output_size: tuple | None = None
    resize_percent: int | None = None
    preserve_current: bool = False


@dataclass(frozen=True)
class CropChange:
    path: str
    region: object


@dataclass(frozen=True)
class AdjustmentChange:
    paths: tuple
    options: object


@dataclass(frozen=True)
class PreparedPixelChange:
    replacements: tuple
    target_count: int | None = None


@dataclass(frozen=True)
class ImageProcessingImpact:
    clipped_annotations: int = 0
    removed_annotations: int = 0
    source_size: tuple | None = None
    result_size: tuple | None = None


@dataclass(frozen=True)
class ImageProcessingPlan:
    """Opaque, single-use preparation returned by ``prepare``."""

    plan_id: str
    target_paths: tuple
    changes_geometry: bool
    impact: ImageProcessingImpact
    _geometry: object | None = None
    _replacements: tuple = ()
    _current_path: str | None = None
    _preserve_current: bool = False
    _direction: str = "geometry-transform"
    _target_count: int | None = None


@dataclass(frozen=True)
class PreparedGeometryTarget:
    """One prepared image-annotation geometry state."""

    path: str
    prepared: object
    annotation_target: str | None
    annotation_preparation: object | None
    document: object | None

    @property
    def replacements(self):
        return (self.prepared.image_replacement,) + (
            tuple(self.annotation_preparation.replacements)
            if self.annotation_preparation is not None
            else ()
        )

    @property
    def mergeable_create_ml_paths(self):
        if (
            self.annotation_preparation is None
            or self.annotation_target is None
            or AnnotationFormat.from_path(self.annotation_target)
            is not AnnotationFormat.CREATE_ML
        ):
            return ()
        return (self.annotation_target,)


@dataclass(frozen=True)
class GeometryProcessingPlan:
    """A complete, write-free geometry preparation."""

    targets: tuple

    def __post_init__(self):
        targets = tuple(self.targets)
        if not targets:
            raise ValueError("a geometry-processing plan cannot be empty")
        paths = tuple(_path_key(target.path) for target in targets)
        if len(paths) != len(set(paths)):
            raise ValueError("a geometry-processing plan cannot repeat a path")
        object.__setattr__(self, "targets", targets)

    @property
    def paths(self):
        return tuple(target.path for target in self.targets)

    def target_for(self, path):
        key = _path_key(path)
        return next(
            (target for target in self.targets if _path_key(target.path) == key),
            None,
        )


@dataclass(frozen=True)
class ImageProcessingProjection:
    """Immutable facts needed by the Qt projection adapter."""

    kind: ImageProcessingProjectionKind
    paths: tuple
    outcome: object
    current_target: PreparedGeometryTarget | None = None
    snapshot: object | None = None
    direction: str | None = None
    error: Exception | None = None


class ImageProcessingSession:
    """Own committed image processing behind one intent-level interface."""

    def __init__(
        self,
        workspace,
        editing,
        persistence,
        operations,
        project,
        document_for_path,
        *,
        codec=None,
    ):
        self._workspace = workspace
        self._editing = editing
        self._persistence = persistence
        self._operations = operations
        self._project = project
        self._document_for_path = document_for_path
        self._codec = codec or ImageFileCodec()
        self._consumed_plans = set()

    @property
    def recovery_entries(self):
        return self._operations.recovery_entries

    def replace_workspace(self, workspace):
        """Continue the session against a committed workspace replacement."""
        self._workspace = workspace

    def prepare(self, change):
        """Prepare and preflight one change without modifying user files."""
        if isinstance(change, GeometryTransformChange):
            processor = ImageGeometryProcessor()

            def prepare_transform(path, snapshot, image_size):
                output_size = change.output_size
                if change.resize_percent is not None:
                    scale = change.resize_percent / 100.0
                    output_size = (
                        max(1, round(image_size[0] * scale)),
                        max(1, round(image_size[1] * scale)),
                    )
                return processor.prepare(
                    path,
                    change.operation,
                    snapshot,
                    output_size=output_size,
                )

            geometry = self._prepare_geometry(
                change.paths,
                prepare_transform,
                current_path=change.current_path,
            )
            return self._plan(
                geometry.paths,
                changes_geometry=True,
                geometry=geometry,
                current_path=change.current_path,
                preserve_current=change.preserve_current,
            )

        if isinstance(change, CropChange):
            processor = ImageCropProcessor()
            geometry = self._prepare_geometry(
                (change.path,),
                lambda path, snapshot, _image_size: processor.prepare(
                    path,
                    change.region,
                    snapshot,
                ),
                current_path=change.path,
            )
            prepared = geometry.targets[0].prepared
            return self._plan(
                geometry.paths,
                changes_geometry=True,
                impact=ImageProcessingImpact(
                    clipped_annotations=prepared.clipped_count,
                    removed_annotations=prepared.removed_count,
                    result_size=prepared.snapshot.image_size,
                ),
                geometry=geometry,
                current_path=change.path,
                preserve_current=True,
                direction="crop",
            )

        if isinstance(change, AdjustmentChange):
            processor = ImageAdjustmentProcessor()
            prepared = tuple(
                processor.prepare(path, change.options)
                for path in change.paths
            )
            replacements = tuple(
                result.replacement
                for result in prepared
                if result.replacement is not None
            )
            if not replacements:
                return None
            return self._plan(
                tuple(item.path for item in replacements),
                changes_geometry=False,
                replacements=replacements,
                target_count=len(replacements),
            )

        if isinstance(change, PreparedPixelChange):
            replacements = tuple(change.replacements)
            if not replacements:
                return None
            return self._plan(
                tuple(item.path for item in replacements),
                changes_geometry=False,
                replacements=replacements,
                target_count=change.target_count,
            )

        raise TypeError(
            "unsupported image-processing change: %s" % type(change).__name__
        )

    def commit(self, plan):
        """Commit one prepared plan exactly once and publish live state."""
        if plan is None:
            return None
        if not isinstance(plan, ImageProcessingPlan):
            raise TypeError("commit requires an ImageProcessingPlan")
        if plan.plan_id in self._consumed_plans:
            raise ValueError("an image-processing plan can be committed once")
        self._consumed_plans.add(plan.plan_id)
        if plan.changes_geometry:
            return self._commit_geometry(
                plan._geometry,
                current_path=plan._current_path,
                preserve_current=plan._preserve_current,
                direction=plan._direction,
            )
        return self._commit_pixel(
            plan._replacements,
            target_count=plan._target_count,
        )

    def _prepare_geometry(self, paths, prepare, *, current_path=None):
        """Prepare every image and matching annotation resource without writes.

        ``prepare`` is the internal tool adapter. Crop and general geometry
        transforms are the two existing adapters at this seam.
        """
        current_key = _path_key(current_path) if current_path else None
        targets = []
        for requested_path in paths:
            path = os.path.abspath(os.fspath(requested_path))
            document = self._document_for_path(path)
            loaded_image = self._codec.load(path)
            if current_key == _path_key(path) and self._editing.view is not None:
                snapshot = self._editing.view.snapshot
                annotation_target = self._editing.view.current_target
            else:
                snapshot = annotation_snapshot_from_document(
                    document,
                    loaded_image.size,
                )
                annotation_target = self._workspace.active_document_path(path)

            prepared = prepare(path, snapshot, loaded_image.size)
            annotation_preparation = None
            if annotation_target and os.path.isfile(annotation_target):
                annotation_preparation = prepare_crop_annotations(
                    prepared.snapshot,
                    prepared.image_replacement.content,
                    annotation_target,
                    class_names=(
                        self._workspace.yolo_vocabulary
                        or document.class_names
                    ),
                    create_ml_record_name=document.create_ml_record_name,
                )
            targets.append(PreparedGeometryTarget(
                path=path,
                prepared=prepared,
                annotation_target=annotation_target,
                annotation_preparation=annotation_preparation,
                document=document,
            ))
        return GeometryProcessingPlan(tuple(targets))

    def _commit_pixel(self, replacements, *, target_count=None):
        """Commit pixel-only replacements and project every changed path."""
        replacements = tuple(replacements)
        outcome = self._operations.execute_image_processing(
            replacements,
            target_count=target_count,
        )
        paths = tuple(
            os.path.abspath(os.fspath(resource.original_path))
            for resource in outcome.file_result.resources
        )
        self._project_and_finalize(ImageProcessingProjection(
            ImageProcessingProjectionKind.PIXEL_COMMIT,
            paths,
            outcome,
        ))
        return outcome

    def _commit_geometry(
        self,
        plan,
        *,
        current_path=None,
        preserve_current=False,
        direction="geometry-transform",
    ):
        """Commit one complete geometry plan and synchronize retained state."""
        if not isinstance(plan, GeometryProcessingPlan):
            plan = GeometryProcessingPlan(tuple(plan))
        current_target = (
            plan.target_for(current_path) if current_path is not None else None
        )
        preserve_current = bool(preserve_current and current_target is not None)

        if preserve_current and len(plan.targets) == 1:
            target = current_target
            outcome = self._operations.execute_grouped_image_processing(
                target.path,
                target.replacements,
                mergeable_create_ml_paths=(
                    target.mergeable_create_ml_paths
                ),
            )
            projected = replace(
                target.prepared.snapshot,
                image_fingerprint=fingerprint_image(
                    target.path,
                    target.prepared.snapshot.image_size,
                ),
            )
            projection = ImageProcessingProjection(
                ImageProcessingProjectionKind.CURRENT_GEOMETRY_COMMIT,
                plan.paths,
                outcome,
                current_target=target,
                snapshot=projected,
                direction=direction,
            )
            try:
                finalize = self._project(projection)
                baseline = _annotation_baseline(target.annotation_target)
                self._editing.rebase_image(
                    target.path,
                    projected,
                    baseline=baseline,
                )
                self._editing.select_image(target.path)
                if baseline is not None:
                    self._persistence.propagate_resource_fingerprints(
                        baseline[1]
                    )
                if callable(finalize):
                    finalize()
            except Exception as error:
                self._projection_failed(projection, error)
            return outcome

        groups = tuple(
            (
                target.path,
                target.replacements,
                target.mergeable_create_ml_paths,
            )
            for target in plan.targets
        )
        outcome = self._operations.execute_grouped_image_processing_batch(
            groups
        )
        self._operations.discard_image_histories(plan.paths)
        self._project_and_finalize(ImageProcessingProjection(
            ImageProcessingProjectionKind.GEOMETRY_BATCH_COMMIT,
            plan.paths,
            outcome,
            current_target=current_target,
            direction=direction,
        ))
        return outcome

    def recover(self, entry_id, selected_paths=None):
        """Recover committed image processing through the same projection seam."""
        outcome = self._operations.recover(
            entry_id,
            selected_paths=selected_paths,
        )
        paths = tuple(
            os.path.abspath(os.fspath(path))
            for path in outcome.restored_paths
        )
        self._project_and_finalize(ImageProcessingProjection(
            ImageProcessingProjectionKind.RECOVERY,
            paths,
            outcome,
        ))
        return outcome

    def _project_and_finalize(self, request):
        try:
            finalize = self._project(request)
            if callable(finalize):
                finalize()
        except Exception as error:
            self._projection_failed(request, error)

    def _projection_failed(self, request, error):
        try:
            self._project(ImageProcessingProjection(
                ImageProcessingProjectionKind.PROJECTION_FAILED,
                request.paths,
                request.outcome,
                current_target=request.current_target,
                snapshot=request.snapshot,
                direction=request.direction,
                error=error,
            ))
        except Exception:
            pass
        raise ImageProcessingProjectionError(
            "committed image processing could not establish one editable "
            "image-annotation state: %s" % error
        ) from error

    @staticmethod
    def _plan(
        target_paths,
        *,
        changes_geometry,
        impact=None,
        geometry=None,
        replacements=(),
        current_path=None,
        preserve_current=False,
        direction="geometry-transform",
        target_count=None,
    ):
        return ImageProcessingPlan(
            plan_id=uuid.uuid4().hex,
            target_paths=tuple(
                os.path.abspath(os.fspath(path)) for path in target_paths
            ),
            changes_geometry=bool(changes_geometry),
            impact=impact or ImageProcessingImpact(),
            _geometry=geometry,
            _replacements=tuple(replacements),
            _current_path=current_path,
            _preserve_current=bool(preserve_current),
            _direction=direction,
            _target_count=target_count,
        )


def _annotation_baseline(annotation_target):
    if not annotation_target:
        return None
    annotation_target = os.path.abspath(os.fspath(annotation_target))
    annotation_format = AnnotationFormat.from_path(annotation_target)
    return (
        annotation_target,
        tuple(
            (resource, fingerprint_path(resource))
            for resource in annotation_resources(
                annotation_format,
                annotation_target,
            )
        ),
    )


def _path_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))
