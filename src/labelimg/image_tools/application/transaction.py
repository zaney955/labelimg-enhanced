"""Atomic image/annotation replacement and recovery transaction."""

from dataclasses import dataclass, replace
import json
import os

from labelimg.annotations import CreateMLRecordIdentity, fingerprint_path
from labelimg.image_tools.application.recovery import (
    ImageProcessingOperation,
    ImageProcessingRecoveryGroup,
    ImageRecoveryCenter,
    ImageRecoveryConflict,
    ImageRecoveryError,
)
from labelimg.image_tools.infrastructure.recoverable_replacement import (
    PreparedImageReplacement,
    RecoverableImageReplacementError,
    RecoverableImageReplacementTransaction,
)


class ImageProcessingTransactionError(RuntimeError):
    pass


class ImageRecoveryBlocked(ImageRecoveryConflict):
    """Unsaved annotation state blocks geometry recovery."""


@dataclass(frozen=True)
class ImageProcessingOutcome:
    operation: ImageProcessingOperation
    file_result: object = None
    recovery_entry: object = None


@dataclass(frozen=True)
class ImageRecoveryOutcome:
    entry: object
    restored_paths: tuple = ()
    reload_images: tuple = ()


class ImageProcessingTransaction:
    """Own image replacement, grouped geometry commits, and recovery."""

    def __init__(
        self,
        editing,
        scene,
        persistence,
        trash_adapter,
        *,
        recovery_center=None,
    ):
        self._editing = editing
        self._scene = scene
        self._persistence = persistence
        self._recovery = recovery_center or ImageRecoveryCenter()
        self._replacements = RecoverableImageReplacementTransaction(
            trash_adapter
        )

    @property
    def recovery_entries(self):
        return self._recovery.entries

    def clear_recovery(self):
        self._recovery.clear()

    def replace_trash_adapter(self, trash_adapter):
        self._replacements = RecoverableImageReplacementTransaction(
            trash_adapter
        )

    def execute(self, replacements, *, target_count=None):
        result = self._replacements.commit(replacements)
        entry = self._recovery.record(
            result.resources,
            target_count=target_count,
        )
        return ImageProcessingOutcome(
            ImageProcessingOperation.PROCESS,
            file_result=result,
            recovery_entry=entry,
        )

    def execute_grouped(
        self,
        image_path,
        replacements,
        *,
        mergeable_create_ml_paths=(),
    ):
        replacements = tuple(replacements)
        original_contents = tuple(
            (replacement.path, _read_bytes(replacement.path))
            for replacement in replacements
        )
        processed_contents = tuple(
            (replacement.path, replacement.content)
            for replacement in replacements
        )
        result = self._replacements.commit(replacements)
        group = ImageProcessingRecoveryGroup(
            os.path.abspath(os.fspath(image_path)),
            tuple(result.resources),
            original_contents=original_contents,
            processed_contents=processed_contents,
            mergeable_create_ml_paths=tuple(
                os.path.abspath(os.fspath(path))
                for path in mergeable_create_ml_paths
            ),
        )
        entry = self._recovery.record_groups((group,))
        return ImageProcessingOutcome(
            ImageProcessingOperation.PROCESS,
            file_result=result,
            recovery_entry=entry,
        )

    def execute_grouped_batch(self, groups):
        groups = tuple(groups)
        if not groups:
            raise ImageProcessingTransactionError(
                "an image-processing batch cannot be empty"
            )
        replacements_by_key = {}
        mergeable_keys = set()
        group_specs = []
        for image_path, replacements, mergeable_paths in groups:
            replacements = tuple(replacements)
            group_mergeable_keys = {
                _resource_key(path) for path in mergeable_paths
            }
            keys = []
            for replacement in replacements:
                key = _resource_key(replacement.path)
                prior = replacements_by_key.get(key)
                if prior is not None:
                    if (
                        prior.expected_fingerprint
                        != replacement.expected_fingerprint
                    ):
                        raise ImageProcessingTransactionError(
                            "one batch prepared conflicting fingerprints for %s"
                            % replacement.path
                        )
                    if prior.content != replacement.content:
                        if (
                            key not in group_mergeable_keys
                            or key not in mergeable_keys
                        ):
                            raise ImageProcessingTransactionError(
                                "one batch prepared conflicting replacements for %s"
                                % replacement.path
                            )
                        replacement = replace(
                            prior,
                            content=_merge_create_ml_processed_record(
                                replacement.path,
                                image_path,
                                prior.content,
                                replacement.content,
                            ),
                        )
                replacements_by_key[key] = replacement
                if key in group_mergeable_keys:
                    mergeable_keys.add(key)
                keys.append(key)
            group_specs.append((
                os.path.abspath(os.fspath(image_path)),
                tuple(keys),
                tuple(mergeable_paths),
            ))

        replacements = tuple(replacements_by_key.values())
        originals = {
            key: _read_bytes(replacement.path)
            for key, replacement in replacements_by_key.items()
        }
        result = self._replacements.commit(replacements)
        resources = {
            _resource_key(resource.original_path): resource
            for resource in result.resources
        }
        recovery_groups = tuple(
            ImageProcessingRecoveryGroup(
                image_path,
                tuple(resources[key] for key in keys),
                original_contents=tuple(
                    (replacements_by_key[key].path, originals[key])
                    for key in keys
                ),
                processed_contents=tuple(
                    (replacements_by_key[key].path, replacements_by_key[key].content)
                    for key in keys
                ),
                mergeable_create_ml_paths=tuple(
                    os.path.abspath(os.fspath(path))
                    for path in mergeable_paths
                ),
            )
            for image_path, keys, mergeable_paths in group_specs
        )
        entry = self._recovery.record_groups(recovery_groups)
        return ImageProcessingOutcome(
            ImageProcessingOperation.PROCESS,
            file_result=result,
            recovery_entry=entry,
        )

    def discard_histories(self, image_paths):
        histories = tuple(
            image_path
            for image_path in image_paths
            if self._editing is not None and self._editing.has_image(image_path)
        )
        for image_path in histories:
            self._persistence.release(
                self._editing.view_image(image_path, touch=False)
            )
        if histories:
            self._editing.remove_images(histories)
        if self._scene is not None:
            for image_path in histories:
                self._scene.forget_image(image_path)

    def recover(self, entry_id, selected_paths=None):
        entry = self._recovery.entry(entry_id)
        selected_keys = (
            None
            if selected_paths is None
            else {_resource_key(path) for path in selected_paths}
        )
        if (
            entry.payload
            and isinstance(entry.payload[0], ImageProcessingRecoveryGroup)
        ):
            groups = tuple(
                group for group in entry.payload
                if selected_keys is None
                or _resource_key(group.image_path) in selected_keys
            )
            if selected_keys is not None and len(groups) != len(selected_keys):
                raise ImageRecoveryError(
                    "the recovery selection is not part of this operation"
                )
            return self._recovery.recover_groups(
                entry_id,
                groups,
                self._recover_groups,
            )
        resources = tuple(
            resource for resource in entry.payload
            if selected_keys is None
            or _resource_key(resource.original_path) in selected_keys
        )
        if selected_keys is not None and len(resources) != len(selected_keys):
            raise ImageRecoveryError(
                "the recovery selection is not part of this operation"
            )
        return self._recovery.recover_resources(
            entry_id,
            resources,
            self._recover_resources,
        )

    def _recover_resources(self, entry, resources):
        try:
            result = self._replacements.recover(resources)
        except RecoverableImageReplacementError as error:
            if error.retry_resources:
                replacements = {
                    _resource_key(resource.original_path): resource
                    for resource in error.retry_resources
                }
                entry.payload = tuple(
                    replacements.get(
                        _resource_key(resource.original_path),
                        resource,
                    )
                    for resource in entry.payload
                )
            raise ImageRecoveryConflict(str(error)) from error
        return ImageRecoveryOutcome(
            entry,
            restored_paths=result.restored_paths,
        )

    def _recover_groups(self, entry, groups):
        self._verify_geometry_histories(groups)
        pending = {}
        source_paths = {}
        source_fingerprints = {}
        for group in groups:
            originals = {
                _resource_key(path): content
                for path, content in group.original_contents
            }
            processed = {
                _resource_key(path): content
                for path, content in group.processed_contents
            }
            mergeable = {
                _resource_key(path)
                for path in group.mergeable_create_ml_paths
            }
            for resource in group.resources:
                path = resource.original_path
                key = _resource_key(path)
                if key not in source_fingerprints:
                    source_fingerprints[key] = fingerprint_path(path)
                    source_paths[key] = path
                current_fingerprint = source_fingerprints[key]
                if key in mergeable:
                    content = _restore_create_ml_record(
                        path,
                        group.image_path,
                        originals[key],
                        processed[key],
                        pending.get(key, _read_bytes(path)),
                    )
                elif current_fingerprint == resource.post_fingerprint:
                    content = originals[key]
                else:
                    raise ImageRecoveryConflict(
                        "%s no longer matches the processed result" % path
                    )
                pending[key] = content
        replacements = tuple(
            PreparedImageReplacement(
                source_paths[key],
                source_fingerprints[key],
                content,
            )
            for key, content in pending.items()
        )
        try:
            self._replacements.commit(replacements)
        except RecoverableImageReplacementError as error:
            raise ImageRecoveryConflict(str(error)) from error
        self.discard_histories(tuple(group.image_path for group in groups))
        return ImageRecoveryOutcome(
            entry,
            restored_paths=tuple(source_paths[key] for key in pending),
            reload_images=tuple(group.image_path for group in groups),
        )

    def _verify_geometry_histories(self, groups):
        if self._editing is None:
            return
        selected = {_resource_key(group.image_path) for group in groups}
        dirty = tuple(
            view.image_key
            for view in self._editing.dirty_views()
            if _resource_key(view.image_key) in selected
        )
        if dirty:
            raise ImageRecoveryBlocked(
                "Save or discard annotation changes before recovering "
                "the image geometry: %s" % os.path.basename(dirty[0])
            )
        if (
            getattr(self._editing, "pending", False)
            or getattr(self._editing, "edit_open", False)
        ):
            active = getattr(self._editing, "image_key", None)
            if active and _resource_key(active) in selected:
                raise ImageRecoveryBlocked(
                    "Finish or cancel the current annotation operation "
                    "before recovering image geometry."
                )


def _resource_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _read_bytes(path):
    with open(path, "rb") as source:
        return source.read()


def _restore_create_ml_record(
    collection_path,
    image_path,
    original_content,
    processed_content,
    current_content,
):
    try:
        original = json.loads(original_content.decode("utf8"))
        processed = json.loads(processed_content.decode("utf8"))
        current = json.loads(current_content.decode("utf8"))
    except (UnicodeError, ValueError, TypeError) as error:
        raise ImageRecoveryConflict(
            "CreateML collection is no longer valid: %s" % collection_path
        ) from error

    def matching(payload):
        if not isinstance(payload, list):
            raise ImageRecoveryConflict(
                "CreateML collection root is no longer a list: %s"
                % collection_path
            )
        matches = [
            index for index, item in enumerate(payload)
            if isinstance(item, dict)
            and isinstance(item.get("image"), str)
            and CreateMLRecordIdentity(
                collection_path, item["image"]
            ).matches(image_path)
        ]
        if len(matches) != 1:
            raise ImageRecoveryConflict(
                "CreateML record identity changed: %s" % image_path
            )
        return matches[0]

    original_index = matching(original)
    processed_index = matching(processed)
    current_index = matching(current)
    if current[current_index] != processed[processed_index]:
        raise ImageRecoveryConflict(
            "CreateML record changed after image processing: %s" % image_path
        )
    current[current_index] = original[original_index]
    return json.dumps(current, ensure_ascii=False, indent=2).encode("utf8")


def _merge_create_ml_processed_record(
    collection_path,
    image_path,
    accumulated_content,
    next_content,
):
    try:
        accumulated = json.loads(accumulated_content.decode("utf8"))
        next_payload = json.loads(next_content.decode("utf8"))
    except (UnicodeError, ValueError, TypeError) as error:
        raise ImageProcessingTransactionError(
            "CreateML collection is not valid: %s" % collection_path
        ) from error

    def matching(payload):
        if not isinstance(payload, list):
            raise ImageProcessingTransactionError(
                "CreateML collection root is not a list: %s" % collection_path
            )
        matches = [
            index for index, item in enumerate(payload)
            if isinstance(item, dict)
            and isinstance(item.get("image"), str)
            and CreateMLRecordIdentity(
                collection_path, item["image"]
            ).matches(image_path)
        ]
        if len(matches) != 1:
            raise ImageProcessingTransactionError(
                "CreateML record identity is ambiguous: %s" % image_path
            )
        return matches[0]

    accumulated[matching(accumulated)] = next_payload[matching(next_payload)]
    return json.dumps(accumulated, ensure_ascii=False, indent=2).encode("utf8")
