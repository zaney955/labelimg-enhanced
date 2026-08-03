"""Revision-bound annotation saves and external resource conflicts.

The module coordinates immutable history revisions with annotation workspace
writes.  Qt presentation remains outside this seam.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
import os

from labelimg.annotation_document import (
    AnnotationBox,
    AnnotationDocument,
    AnnotationDocumentError,
    AnnotationFormat,
)
from labelimg.annotation_storage import (
    AnnotationStorageConflict,
    fingerprint_image,
    fingerprint_path,
)
from labelimg.annotation_workspace import annotation_resources


@dataclass
class ExternalAnnotationConflict:
    resource: str
    error: object
    image_keys: set = field(default_factory=set)
    affected_count: int = 1


@dataclass(frozen=True)
class SavedRevision:
    image_key: str
    workspace_save: object
    still_dirty: bool


@dataclass(frozen=True)
class PersistenceFailure:
    image_keys: tuple
    error: Exception


@dataclass(frozen=True)
class SaveOutcome:
    saved: tuple = ()
    failure: PersistenceFailure | None = None
    conflicts: tuple = ()

    @property
    def ok(self):
        return self.failure is None

    @property
    def saved_by_image(self):
        return {
            receipt.image_key: receipt.workspace_save
            for receipt in self.saved
        }


class AnnotationSaveCoordinator:
    """Own saved-baseline acknowledgement and resource conflict state."""

    def __init__(
        self,
        workspace,
        editing,
        *,
        image_data_for=None,
        image_keys=None,
    ):
        self._workspace = workspace
        self._editing = editing
        self._image_data_for = image_data_for or _read_image_data
        self._image_keys = image_keys or (lambda: ())
        self._conflicts = {}

    @property
    def conflicts(self):
        return MappingProxyType(self._conflicts)

    def replace_workspace(self, workspace):
        if self._conflicts:
            raise RuntimeError(
                "resolve annotation conflicts before replacing workspace"
            )
        self._workspace = workspace

    def replace_conflicts(self, conflicts):
        replacement = {
            _resource_key(resource): conflict
            for resource, conflict in conflicts.items()
        }
        previous = set(self._conflicts)
        current = set(replacement)
        for resource in previous - current:
            self._workspace.release_resource(
                resource, owner=("conflict", resource)
            )
        for resource in current - previous:
            if resource.lower().endswith(".json"):
                self._workspace.hold_resource(
                    resource, owner=("conflict", resource)
                )
        self._conflicts = replacement

    def has_conflict(self, image_key):
        image_key = str(image_key)
        return any(
            image_key in conflict.image_keys
            for conflict in self._conflicts.values()
        )

    def save(
        self,
        image_key,
        default_format,
        *,
        target=None,
    ):
        targets = {str(image_key): target} if target is not None else None
        return self.save_many(
            (str(image_key),),
            default_format,
            target_overrides=targets,
        )

    def save_many(
        self,
        image_keys,
        default_format,
        *,
        target_overrides=None,
    ):
        target_overrides = {
            str(image_key): os.fspath(target)
            for image_key, target in (target_overrides or {}).items()
        }
        views = []
        for image_key in tuple(dict.fromkeys(map(str, image_keys))):
            view = self._editing.view_image(image_key, touch=False)
            override = target_overrides.get(image_key)
            if override is not None:
                override = _target_with_format(override, default_format)
                if view.current_target != override:
                    view = self._editing.set_target(image_key, override)
            views.append(view)

        ordinary = []
        create_ml_groups = defaultdict(list)
        for view in views:
            target, annotation_format = self._target_for(
                view, default_format
            )
            item = (view, target, annotation_format)
            if annotation_format is AnnotationFormat.CREATE_ML:
                create_ml_groups[_resource_key(target)].append(item)
            else:
                ordinary.append(item)

        saved = []
        for item in ordinary:
            outcome = self._save_one(item)
            saved.extend(outcome.saved)
            if not outcome.ok:
                return SaveOutcome(
                    saved=tuple(saved),
                    failure=outcome.failure,
                    conflicts=outcome.conflicts,
                )

        for group in create_ml_groups.values():
            outcome = self._save_create_ml_group(group)
            saved.extend(outcome.saved)
            if not outcome.ok:
                return SaveOutcome(
                    saved=tuple(saved),
                    failure=outcome.failure,
                    conflicts=outcome.conflicts,
                )
        return SaveOutcome(saved=tuple(saved))

    def overwrite_conflict(self, resource, default_format):
        conflict = self._conflicts[_resource_key(resource)]
        if any(
            _resource_key(image_key) == _resource_key(conflict.resource)
            for image_key in conflict.image_keys
        ):
            return SaveOutcome(
                failure=PersistenceFailure(
                    tuple(conflict.image_keys),
                    AnnotationStorageConflict(
                        ((conflict.resource, None, None),)
                    ),
                )
            )

        affected_views = tuple(
            self._editing.view_image(image_key, touch=False)
            for image_key in conflict.image_keys
            if self._editing.has_image(image_key)
        )
        self._workspace.accept_resource_fingerprints((conflict.resource,))
        self.propagate_resource_fingerprints(
            ((conflict.resource, fingerprint_path(conflict.resource)),)
        )
        dirty_keys = tuple(
            view.image_key for view in affected_views if view.dirty
        )
        outcome = self.save_many(dirty_keys, default_format)
        if not outcome.ok:
            return outcome
        for view in affected_views:
            refreshed = self._editing.view_image(
                view.image_key, touch=False
            )
            if refreshed.dirty:
                continue
            fingerprints = tuple(
                (path, fingerprint_path(path))
                for path in self.resource_keys_for(refreshed)
            )
            self._editing.mark_image_saved(
                refreshed.image_key,
                refreshed.revision_id,
                refreshed.current_target,
                fingerprints,
            )
        self.clear_conflicts((conflict.resource,))
        return outcome

    def baseline_is_current(self, baseline):
        return not self.baseline_mismatches(baseline)

    @staticmethod
    def baseline_mismatches(baseline):
        if isinstance(baseline.fingerprint, tuple):
            return tuple(
                (path, expected, actual)
                for path, expected in baseline.fingerprint
                for actual in (fingerprint_path(path),)
                if actual != expected
            )
        if baseline.target is None:
            return (
                ("", baseline.fingerprint, fingerprint_path("")),
            )
        actual = fingerprint_path(baseline.target)
        return (
            ()
            if actual == baseline.fingerprint
            else ((baseline.target, baseline.fingerprint, actual),)
        )

    def verify_baseline(self, view):
        baseline = view.saved_baseline
        if baseline is None:
            return
        mismatches = self.baseline_mismatches(baseline)
        if mismatches:
            raise AnnotationStorageConflict(mismatches)

    def resource_keys_for(self, view):
        target = view.current_target
        if not target:
            return ()
        try:
            annotation_format = AnnotationFormat.from_path(target)
        except AnnotationDocumentError:
            return ()
        return tuple(
            _resource_key(path)
            for path in annotation_resources(annotation_format, target)
        )

    def track(self, view):
        operation = (
            self._workspace.hold_resource
            if view.dirty
            else self._workspace.release_resource
        )
        for resource in self.resource_keys_for(view):
            operation(resource, owner=("history", view.image_key))

    def release(self, view):
        for resource in self.resource_keys_for(view):
            self._workspace.release_resource(
                resource, owner=("history", view.image_key)
            )

    def propagate_resource_fingerprints(self, fingerprints):
        current = {
            _resource_key(path): fingerprint
            for path, fingerprint in fingerprints
        }
        if not current:
            return
        for image_key in self._editing.image_keys:
            view = self._editing.view_image(image_key, touch=False)
            baseline = view.saved_baseline
            if baseline is None or not view.current_target:
                continue
            try:
                annotation_format = AnnotationFormat.from_path(
                    view.current_target
                )
            except AnnotationDocumentError:
                continue
            resources = annotation_resources(
                annotation_format, view.current_target
            )
            if not any(
                _resource_key(resource) in current
                for resource in resources
            ):
                continue
            if isinstance(baseline.fingerprint, tuple):
                old = {
                    _resource_key(path): value
                    for path, value in baseline.fingerprint
                }
                refreshed = tuple(
                    (
                        resource,
                        current.get(
                            _resource_key(resource),
                            old.get(
                                _resource_key(resource),
                                fingerprint_path(resource),
                            ),
                        ),
                    )
                    for resource in resources
                )
            else:
                target_key = _resource_key(view.current_target)
                if target_key not in current:
                    continue
                refreshed = current[target_key]
            self._editing.update_baseline_fingerprint(
                image_key, refreshed
            )

    def register_conflict(self, error, image_key):
        mismatch_resources = tuple(
            _resource_key(path)
            for path, _expected, _actual in error.mismatches
        )
        dependent = {str(image_key)}
        for candidate in self._editing.image_keys:
            view = self._editing.view_image(candidate, touch=False)
            if set(mismatch_resources).intersection(
                self.resource_keys_for(view)
            ):
                dependent.add(candidate)
        for resource in mismatch_resources:
            conflict = self._conflicts.get(resource)
            if conflict is None:
                conflict = ExternalAnnotationConflict(resource, error)
                self._conflicts[resource] = conflict
            conflict.error = error
            conflict.image_keys.update(dependent)
            if resource.lower().endswith(".json"):
                conflict.image_keys.update(
                    self._workspace.create_ml_image_keys(
                        resource,
                        self._image_keys(),
                    )
                )
                self._workspace.hold_resource(
                    resource, owner=("conflict", resource)
                )
            conflict.affected_count = max(
                conflict.affected_count,
                len(conflict.image_keys),
                (
                    self._workspace.create_ml_image_count(resource)
                    if resource.lower().endswith(".json")
                    else 1
                ),
            )
        return mismatch_resources

    def clear_conflicts(self, resources=None):
        resources = (
            tuple(self._conflicts)
            if resources is None
            else tuple(resources)
        )
        for resource in resources:
            key = _resource_key(resource)
            self._workspace.release_resource(
                key, owner=("conflict", key)
            )
            self._conflicts.pop(key, None)

    def _save_one(self, item):
        view, target, annotation_format = item
        try:
            self.verify_snapshot(view.snapshot)
            self.verify_baseline(view)
            document = self._document_from_snapshot(view.snapshot)
            workspace_save = self._workspace.save(
                document,
                annotation_format,
                annotation_path=target,
                revision_id=view.revision_id,
            )
        except AnnotationStorageConflict as error:
            self.register_conflict(error, view.image_key)
            return SaveOutcome(
                failure=PersistenceFailure((view.image_key,), error),
                conflicts=tuple(self._conflicts.values()),
            )
        except Exception as error:
            return SaveOutcome(
                failure=PersistenceFailure((view.image_key,), error)
            )
        return self._acknowledge(((view, workspace_save),))

    def _save_create_ml_group(self, group):
        views = tuple(item[0] for item in group)
        target = group[0][1]
        try:
            for view in views:
                self.verify_snapshot(view.snapshot)
                self.verify_baseline(view)
            saves = self._workspace.save_createml_batch(
                tuple(
                    (
                        view.revision_id,
                        self._document_from_snapshot(view.snapshot),
                    )
                    for view in views
                ),
                target,
            )
        except AnnotationStorageConflict as error:
            for view in views:
                self.register_conflict(error, view.image_key)
            return SaveOutcome(
                failure=PersistenceFailure(
                    tuple(view.image_key for view in views), error
                ),
                conflicts=tuple(self._conflicts.values()),
            )
        except Exception as error:
            return SaveOutcome(
                failure=PersistenceFailure(
                    tuple(view.image_key for view in views), error
                )
            )
        return self._acknowledge(tuple(zip(views, saves)))

    def _acknowledge(self, pairs):
        receipts = []
        fingerprints = None
        for view, workspace_save in pairs:
            self._editing.mark_image_saved(
                view.image_key,
                workspace_save.revision_id,
                workspace_save.annotation_path,
                tuple(workspace_save.fingerprints),
            )
            self.release(view)
            current = self._editing.view_image(
                view.image_key, touch=False
            )
            receipts.append(
                SavedRevision(
                    view.image_key,
                    workspace_save,
                    current.dirty,
                )
            )
            fingerprints = workspace_save.fingerprints
        if fingerprints is not None:
            self.propagate_resource_fingerprints(fingerprints)
        return SaveOutcome(saved=tuple(receipts))

    def _target_for(self, view, default_format):
        target = view.current_target
        if not target:
            target = self._workspace.entry(view.image_key).path_for(
                default_format
            )
        return target, AnnotationFormat.from_path(target)

    def verify_snapshot(self, snapshot):
        expected = snapshot.image_fingerprint
        if expected is None:
            return
        actual = fingerprint_image(snapshot.image_key, snapshot.image_size)
        if actual != expected:
            raise AnnotationStorageConflict(
                ((snapshot.image_key, expected, actual),)
            )

    def _document_from_snapshot(self, snapshot):
        return AnnotationDocument(
            image_path=snapshot.image_key,
            image_data=self._image_data_for(snapshot.image_key),
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
            class_names=self._workspace.yolo_vocabulary,
            verified=snapshot.verified,
            questioned=snapshot.questioned,
        )


def _read_image_data(image_key):
    with open(image_key, "rb") as image_file:
        return image_file.read()


def _target_with_format(target, annotation_format):
    target = os.path.abspath(os.fspath(target))
    if not target.lower().endswith(annotation_format.extension):
        target += annotation_format.extension
    return target


def _resource_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))
