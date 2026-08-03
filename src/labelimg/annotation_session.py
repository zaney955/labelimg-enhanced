"""Cross-image annotation session identity migrations."""

import os

from labelimg.annotation_document import (
    AnnotationDocumentError,
    AnnotationFormat,
)
from labelimg.annotation_storage import fingerprint_path
from labelimg.annotation_workspace import annotation_resources


class RenamedAnnotationSessionMigrator:
    """Move retained histories, baselines, resources, and conflicts together."""

    def __init__(
        self,
        workspace,
        editing,
        scene,
        release_history_resources,
        hold_history_resources,
    ):
        self._workspace = workspace
        self._editing = editing
        self._scene = scene
        self._release = release_history_resources
        self._hold = hold_history_resources

    def migrate(
        self,
        renamed,
        transaction_fingerprints=None,
        transaction_contents=None,
        conflicts=None,
    ):
        transaction_fingerprints = transaction_fingerprints or {}
        transaction_contents = transaction_contents or {}
        self._workspace.apply_transaction_resources(
            transaction_fingerprints,
            transaction_contents,
        )

        def transaction_fingerprint(path):
            key = self._resource_key(path)
            if key in transaction_fingerprints:
                return transaction_fingerprints[key]
            return fingerprint_path(path)

        history_mapping = {
            source: destination
            for source, destination in renamed.items()
            if self._editing.has_image(source)
        }
        target_mapping = {}
        fingerprint_mapping = {}
        resource_mapping = {}
        dirty_migrated = []
        for source, destination in history_mapping.items():
            view = self._editing.view_image(source, touch=False)
            if view.dirty:
                dirty_migrated.append((source, destination, view))
            old_target = view.current_target
            if not old_target:
                continue
            annotation_format = AnnotationFormat.from_path(old_target)
            new_target = self._renamed_target(
                source,
                destination,
                old_target,
                annotation_format,
            )
            target_mapping[source] = new_target
            if view.saved_baseline is not None:
                new_resources = annotation_resources(
                    annotation_format, new_target
                )
                fingerprint_mapping[source] = (
                    tuple(
                        (
                            resource,
                            transaction_fingerprint(resource),
                        )
                        for resource in new_resources
                    )
                    if isinstance(view.saved_baseline.fingerprint, tuple)
                    else transaction_fingerprint(new_target)
                )
            for old_resource, new_resource in zip(
                annotation_resources(annotation_format, old_target),
                annotation_resources(annotation_format, new_target),
            ):
                resource_mapping[
                    self._resource_key(old_resource)
                ] = self._resource_key(new_resource)

        self._migrate_histories(
            history_mapping,
            target_mapping,
            fingerprint_mapping,
            dirty_migrated,
        )
        self._refresh_shared_baselines(
            history_mapping,
            transaction_fingerprints,
            transaction_fingerprint,
        )
        return self._migrate_conflicts(
            conflicts or {}, renamed, resource_mapping
        )

    def _migrate_histories(
        self,
        history_mapping,
        target_mapping,
        fingerprint_mapping,
        dirty_migrated,
    ):
        if not history_mapping:
            return
        for _source, _destination, view in dirty_migrated:
            self._release(view)
        try:
            self._editing.migrate_images(
                history_mapping,
                target_mapping=target_mapping,
                fingerprint_mapping=fingerprint_mapping,
            )
            self._workspace.migrate_images(
                history_mapping, target_mapping=target_mapping
            )
        except Exception:
            for _source, _destination, view in dirty_migrated:
                self._hold(view)
            raise
        for _source, destination, _view in dirty_migrated:
            self._hold(
                self._editing.view_image(destination, touch=False)
            )
        for source in history_mapping:
            self._scene.forget_image(source)

    def _refresh_shared_baselines(
        self,
        history_mapping,
        transaction_fingerprints,
        transaction_fingerprint,
    ):
        for image_key in self._editing.image_keys:
            if image_key in history_mapping.values():
                continue
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
                self._resource_key(resource)
                in transaction_fingerprints
                for resource in resources
            ):
                continue
            fingerprint = (
                tuple(
                    (
                        resource,
                        transaction_fingerprint(resource),
                    )
                    for resource in resources
                )
                if isinstance(baseline.fingerprint, tuple)
                else transaction_fingerprint(view.current_target)
            )
            self._editing.update_baseline_fingerprint(
                image_key, fingerprint
            )

    @staticmethod
    def _migrate_conflicts(conflicts, renamed, resource_mapping):
        migrated = {}
        for resource, conflict in conflicts.items():
            new_resource = resource_mapping.get(resource, resource)
            conflict.resource = new_resource
            conflict.image_keys = {
                renamed.get(image_key, image_key)
                for image_key in conflict.image_keys
            }
            migrated[new_resource] = conflict
        return migrated

    @staticmethod
    def _renamed_target(
        source, destination, old_target, annotation_format
    ):
        exact_create_ml = (
            annotation_format is AnnotationFormat.CREATE_ML
            and os.path.splitext(os.path.basename(old_target))[0].casefold()
            == os.path.splitext(os.path.basename(source))[0].casefold()
        )
        if (
            annotation_format is AnnotationFormat.CREATE_ML
            and not exact_create_ml
        ):
            return old_target
        return os.path.join(
            os.path.dirname(old_target),
            os.path.splitext(os.path.basename(destination))[0]
            + annotation_format.extension,
        )

    @staticmethod
    def _resource_key(path):
        return os.path.normcase(os.path.abspath(os.fspath(path)))
