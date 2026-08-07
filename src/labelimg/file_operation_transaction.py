"""File-list operations and recovery through one transaction interface."""

from dataclasses import dataclass, replace
import json
import os
import uuid

from labelimg.annotation_session import RenamedAnnotationSessionMigrator
from labelimg.create_ml_collection import CreateMLRecordIdentity
from labelimg.annotation_storage import fingerprint_path
from labelimg.file_operations import (
    AnnotationFileService,
    FileOperationError,
    SynchronizedRenamer,
)
from labelimg.file_recovery import (
    FileRecoveryCenter,
    FileRecoveryConflict,
    FileRecoveryError,
    ImageProcessingRecoveryGroup,
    RecoveryOperation,
)
from labelimg.image_tools.recoverable_replacement import (
    PreparedImageReplacement,
    RecoverableImageReplacementError,
    RecoverableImageReplacementTransaction,
)


class FileOperationBlocked(FileOperationError):
    """A session invariant blocks a requested file operation."""


class FileRecoveryBlocked(FileRecoveryConflict):
    """Unsaved session state blocks an otherwise valid recovery."""


@dataclass(frozen=True)
class FileOperationOutcome:
    """Result of one forward file-list transaction."""

    operation: RecoveryOperation
    file_result: object = None
    renamed: tuple = ()
    recovery_entry: object = None


@dataclass(frozen=True)
class FileRecoveryOutcome:
    """Result needed to project a recovered operation into the UI."""

    entry: object
    restored_paths: tuple = ()
    renamed: tuple = ()
    review_result: object = None
    reload_images: tuple = ()


class FileOperationTransaction:
    """Execute and recover file-list operations with session consistency."""

    def __init__(
        self,
        workspace,
        editing,
        scene,
        persistence,
        review_transaction,
        trash_adapter,
        *,
        recovery_center=None,
    ):
        self._workspace = workspace
        self._editing = editing
        self._scene = scene
        self._persistence = persistence
        self._review_transaction = review_transaction
        self._trash = trash_adapter
        self._recovery = recovery_center or FileRecoveryCenter()
        self._image_replacements = RecoverableImageReplacementTransaction(
            trash_adapter
        )

    @property
    def recovery_entries(self):
        return self._recovery.entries

    def clear_recovery(self):
        self._recovery.clear()

    def annotation_count(self, image_paths):
        return self._file_service().annotation_count(image_paths)

    def execute(self, operation, targets, should_continue=None):
        """Execute clear, delete, or rename and record its recovery."""
        operation = RecoveryOperation(operation)
        if operation in (
            RecoveryOperation.CLEAR,
            RecoveryOperation.DELETE,
        ):
            return self._execute_trash_operation(
                operation,
                targets,
                should_continue,
            )
        if operation is RecoveryOperation.RENAME:
            return self._execute_rename(targets)
        raise FileOperationError(
            "unsupported forward file operation: %s" % operation
        )

    def record_review(self, changes):
        return self._recovery.record_review(changes)

    def execute_image_processing(self, replacements, *, target_count=None):
        """Atomically install prepared images and record their originals."""
        result = self._image_replacements.commit(replacements)
        entry = self._recovery.record_image_processing(
            result.resources,
            target_count=target_count,
        )
        return FileOperationOutcome(
            RecoveryOperation.IMAGE_PROCESSING,
            file_result=result,
            recovery_entry=entry,
        )

    def execute_grouped_image_processing(
        self,
        image_path,
        replacements,
        *,
        mergeable_create_ml_paths=(),
    ):
        """Commit one image and its annotation resources as one unit."""
        replacements = tuple(replacements)
        original_contents = tuple(
            (replacement.path, _read_bytes(replacement.path))
            for replacement in replacements
        )
        processed_contents = tuple(
            (replacement.path, replacement.content)
            for replacement in replacements
        )
        result = self._image_replacements.commit(replacements)
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
        entry = self._recovery.record_grouped_image_processing((group,))
        return FileOperationOutcome(
            RecoveryOperation.IMAGE_PROCESSING,
            file_result=result,
            recovery_entry=entry,
        )

    def execute_grouped_image_processing_batch(self, groups):
        """Commit multiple image/annotation groups in one atomic batch."""
        groups = tuple(groups)
        if not groups:
            raise FileOperationError("an image-processing batch cannot be empty")
        replacements_by_key = {}
        mergeable_keys = set()
        group_specs = []
        for image_path, replacements, mergeable_paths in groups:
            replacements = tuple(replacements)
            group_mergeable_keys = {
                self._resource_key(path) for path in mergeable_paths
            }
            keys = []
            for replacement in replacements:
                key = self._resource_key(replacement.path)
                prior = replacements_by_key.get(key)
                if prior is not None:
                    if (
                        prior.expected_fingerprint
                        != replacement.expected_fingerprint
                    ):
                        raise FileOperationError(
                            "one batch prepared conflicting fingerprints for %s"
                            % replacement.path
                        )
                    if prior.content != replacement.content:
                        if (
                            key not in group_mergeable_keys
                            or key not in mergeable_keys
                        ):
                            raise FileOperationError(
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
        result = self._image_replacements.commit(replacements)
        resources = {
            self._resource_key(resource.original_path): resource
            for resource in result.resources
        }
        recovery_groups = []
        for image_path, keys, mergeable_paths in group_specs:
            recovery_groups.append(ImageProcessingRecoveryGroup(
                image_path,
                tuple(resources[key] for key in keys),
                original_contents=tuple(
                    (replacements_by_key[key].path, originals[key])
                    for key in keys
                ),
                processed_contents=tuple(
                    (
                        replacements_by_key[key].path,
                        replacements_by_key[key].content,
                    )
                    for key in keys
                ),
                mergeable_create_ml_paths=tuple(
                    os.path.abspath(os.fspath(path))
                    for path in mergeable_paths
                ),
            ))
        entry = self._recovery.record_grouped_image_processing(
            tuple(recovery_groups)
        )
        return FileOperationOutcome(
            RecoveryOperation.IMAGE_PROCESSING,
            file_result=result,
            recovery_entry=entry,
        )

    def recover(self, entry_id, selected_paths=None):
        """Recover one complete recorded operation."""
        entry = self._recovery.entry(entry_id)
        if entry.operation is RecoveryOperation.IMAGE_PROCESSING:
            if (
                entry.payload
                and isinstance(
                    entry.payload[0], ImageProcessingRecoveryGroup
                )
            ):
                selected_keys = (
                    None
                    if selected_paths is None
                    else {
                        self._resource_key(path)
                        for path in selected_paths
                    }
                )
                groups = tuple(
                    group for group in entry.payload
                    if selected_keys is None
                    or self._resource_key(group.image_path)
                    in selected_keys
                )
                if (
                    selected_keys is not None
                    and len(groups) != len(selected_keys)
                ):
                    raise FileRecoveryError(
                        "the recovery selection is not part of this operation"
                    )
                return self._recovery.recover_image_groups(
                    entry_id,
                    groups,
                    self._recover_grouped_image_processing,
                )
            selected_keys = (
                None
                if selected_paths is None
                else {
                    self._resource_key(path)
                    for path in selected_paths
                }
            )
            resources = tuple(
                resource
                for resource in entry.payload
                if selected_keys is None
                or self._resource_key(resource.original_path)
                in selected_keys
            )
            if (
                selected_keys is not None
                and len(resources) != len(selected_keys)
            ):
                raise FileRecoveryError(
                    "the recovery selection is not part of this operation"
                )
            return self._recovery.recover_subset(
                entry_id,
                resources,
                self._recover_image_processing,
            )
        return self._recovery.recover(entry_id, self._recover_entry)

    def replace_workspace(self, workspace):
        self._workspace = workspace

    def replace_trash_adapter(self, trash_adapter):
        self._trash = trash_adapter
        self._image_replacements = RecoverableImageReplacementTransaction(
            trash_adapter
        )

    def _file_service(self):
        return AnnotationFileService(
            save_dir=self._workspace.save_dir,
            trash=self._trash,
            storage_coordinator=self._workspace.storage_coordinator,
        )

    def _execute_trash_operation(
        self,
        operation,
        image_paths,
        should_continue,
    ):
        file_service = self._file_service()
        execute = (
            file_service.clear_annotations
            if operation is RecoveryOperation.CLEAR
            else file_service.delete_images
        )
        result = execute(
            image_paths,
            should_continue=should_continue,
        )
        entry = self._recovery.record_trash_operation(
            operation,
            result.trashed_resources,
            target_count=len(result.succeeded_images),
        )
        self._discard_histories(result.succeeded_images)
        return FileOperationOutcome(
            operation,
            file_result=result,
            recovery_entry=entry,
        )

    def _discard_histories(self, image_paths):
        histories = tuple(
            image_path
            for image_path in image_paths
            if self._editing.has_image(image_path)
        )
        for image_path in histories:
            self._persistence.release(
                self._editing.view_image(image_path, touch=False)
            )
        if histories:
            self._editing.remove_images(histories)
        for image_path in histories:
            self._scene.forget_image(image_path)

    def _execute_rename(self, mapping):
        if self._persistence.conflicts:
            raise FileOperationBlocked(
                "Resolve annotation resource conflicts before renaming files."
            )
        renamer = self._renamer()
        renamed = renamer.rename(mapping)
        self._migrate_renamed_session(
            renamed,
            renamer.last_fingerprints,
            renamer.last_resource_bytes,
        )
        entry = (
            self._recovery.record_rename(renamed) if renamed else None
        )
        return FileOperationOutcome(
            RecoveryOperation.RENAME,
            renamed=tuple(renamed.items()),
            recovery_entry=entry,
        )

    def _renamer(self):
        return SynchronizedRenamer(
            save_dir=self._workspace.save_dir,
            storage_coordinator=self._workspace.storage_coordinator,
        )

    def _migrate_renamed_session(
        self,
        renamed,
        transaction_fingerprints=None,
        transaction_contents=None,
    ):
        migrated_conflicts = RenamedAnnotationSessionMigrator(
            self._workspace,
            self._editing,
            self._scene,
            self._persistence.release,
            self._persistence.track,
        ).migrate(
            renamed,
            transaction_fingerprints,
            transaction_contents,
            self._persistence.conflicts,
        )
        self._persistence.replace_conflicts(migrated_conflicts)

    def _recover_entry(self, entry):
        if entry.operation in (
            RecoveryOperation.DELETE,
            RecoveryOperation.CLEAR,
        ):
            return self._recover_trashed(entry)
        if entry.operation is RecoveryOperation.RENAME:
            return self._recover_rename(entry)
        if entry.operation is RecoveryOperation.REVIEW:
            return self._recover_review(entry)
        raise FileRecoveryError(
            "unsupported recovery operation: %s" % entry.operation
        )

    def _recover_image_processing(self, entry, resources):
        try:
            result = self._image_replacements.recover(resources)
        except RecoverableImageReplacementError as error:
            if error.retry_resources:
                replacements = {
                    self._resource_key(resource.original_path): resource
                    for resource in error.retry_resources
                }
                entry.payload = tuple(
                    replacements.get(
                        self._resource_key(resource.original_path),
                        resource,
                    )
                    for resource in entry.payload
                )
            raise FileRecoveryConflict(str(error)) from error
        return FileRecoveryOutcome(
            entry,
            restored_paths=result.restored_paths,
        )

    def _recover_grouped_image_processing(self, entry, groups):
        self._verify_geometry_recovery_histories(groups)
        pending = {}
        source_paths = {}
        source_fingerprints = {}
        for group in groups:
            originals = {
                self._resource_key(path): content
                for path, content in group.original_contents
            }
            processed = {
                self._resource_key(path): content
                for path, content in group.processed_contents
            }
            mergeable = {
                self._resource_key(path)
                for path in group.mergeable_create_ml_paths
            }
            for resource in group.resources:
                path = resource.original_path
                key = self._resource_key(path)
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
                    raise FileRecoveryConflict(
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
            self._image_replacements.commit(replacements)
        except RecoverableImageReplacementError as error:
            raise FileRecoveryConflict(str(error)) from error
        # A geometry-changing recovery establishes a different image
        # coordinate space. Retaining the cropped annotation history would
        # leave its snapshot dimensions incompatible with the restored
        # Canvas, so every recovered image must be opened from disk again as
        # a fresh baseline.
        if self._editing is not None:
            self._discard_histories(
                tuple(group.image_path for group in groups)
            )
        return FileRecoveryOutcome(
            entry,
            restored_paths=tuple(
                source_paths[key] for key in pending
            ),
            reload_images=tuple(group.image_path for group in groups),
        )

    def _verify_geometry_recovery_histories(self, groups):
        if self._editing is None:
            return
        selected = {
            self._resource_key(group.image_path) for group in groups
        }
        dirty = tuple(
            view.image_key
            for view in self._editing.dirty_views()
            if self._resource_key(view.image_key) in selected
        )
        if dirty:
            raise FileRecoveryBlocked(
                "Save or discard annotation changes before recovering "
                "the image geometry: %s" % os.path.basename(dirty[0])
            )
        if (
            getattr(self._editing, "pending", False)
            or getattr(self._editing, "edit_open", False)
        ):
            active = getattr(self._editing, "image_key", None)
            if active and self._resource_key(active) in selected:
                raise FileRecoveryBlocked(
                    "Finish or cancel the current annotation operation "
                    "before recovering image geometry."
                )

    def _recover_trashed(self, entry):
        if entry.operation is RecoveryOperation.CLEAR:
            self._verify_clear_recovery_histories(entry)
        resources = tuple(entry.payload)
        paths = tuple(resource.original_path for resource in resources)
        with self._workspace.storage_coordinator.lease(paths):
            self._restore_trashed(entry)
        return FileRecoveryOutcome(entry, restored_paths=paths)

    def _verify_clear_recovery_histories(self, entry):
        recovery_resources = {
            self._resource_key(resource.original_path)
            for resource in entry.payload
        }
        blocking_images = []
        for view in self._editing.dirty_views():
            if recovery_resources.intersection(
                self._persistence.resource_keys_for(view)
            ):
                blocking_images.append(view.image_key)
        if blocking_images:
            raise FileRecoveryBlocked(
                "Unsaved annotation content exists for %d target "
                "image(s), including %s."
                % (
                    len(blocking_images),
                    os.path.basename(blocking_images[0]),
                )
            )

    def _restore_trashed(self, entry):
        resources = tuple(entry.payload)
        conflicts = []
        for resource in resources:
            actual = fingerprint_path(resource.original_path)
            if actual != resource.post_fingerprint:
                conflicts.append(
                    "%s no longer matches the operation result"
                    % resource.original_path
                )
            if not self._trash.exists(resource.identity):
                conflicts.append(
                    "%s is no longer available in trash"
                    % resource.original_path
                )
        if conflicts:
            raise FileRecoveryConflict("; ".join(conflicts))

        backups = {}
        restored = []
        try:
            for resource in resources:
                if resource.post_fingerprint.exists:
                    backup = self._recovery_temp_path(
                        resource.original_path
                    )
                    os.replace(resource.original_path, backup)
                    backups[resource.original_path] = backup
                self._trash.restore(
                    resource.identity,
                    resource.original_path,
                )
                restored.append(resource)
        except Exception as error:
            self._rollback_restored(entry, resources, restored, backups, error)
        else:
            cleanup_errors = []
            for backup in backups.values():
                try:
                    if os.path.exists(backup):
                        os.remove(backup)
                except OSError as error:
                    cleanup_errors.append(str(error))
            if cleanup_errors:
                entry.detail = (
                    "Recovered successfully; a temporary backup could not "
                    "be removed: %s" % cleanup_errors[0]
                )

    def _rollback_restored(
        self,
        entry,
        resources,
        restored,
        backups,
        recovery_error,
    ):
        rollback_errors = []
        replacement_identities = {}
        for resource in reversed(restored):
            try:
                replacement_identities[
                    resource.original_path
                ] = self._trash.move(resource.original_path)
            except Exception as error:
                rollback_errors.append(error)
        for original, backup in backups.items():
            try:
                if os.path.exists(backup):
                    os.replace(backup, original)
            except Exception as error:
                rollback_errors.append(error)
        if not rollback_errors and replacement_identities:
            entry.payload = tuple(
                replace(
                    resource,
                    identity=replacement_identities.get(
                        resource.original_path,
                        resource.identity,
                    ),
                )
                for resource in resources
            )
        if rollback_errors:
            raise FileRecoveryError(
                "recovery and rollback failed: %s" % rollback_errors[0]
            ) from recovery_error
        raise FileRecoveryError(str(recovery_error)) from recovery_error

    def _recover_rename(self, entry):
        if self._persistence.conflicts:
            raise FileRecoveryConflict(
                "Resolve annotation conflicts before recovering a rename."
            )
        inverse = {
            destination: source for source, destination in entry.payload
        }
        try:
            renamer = self._renamer()
            renamed = renamer.rename(inverse)
            self._migrate_renamed_session(
                renamed,
                renamer.last_fingerprints,
                renamer.last_resource_bytes,
            )
        except FileRecoveryError:
            raise
        except Exception as error:
            raise FileRecoveryError(str(error)) from error
        return FileRecoveryOutcome(
            entry,
            renamed=tuple(renamed.items()),
        )

    def _recover_review(self, entry):
        try:
            result = self._review_transaction.recover(entry.payload)
        except Exception as error:
            self._rescan_review_workspace(entry.payload)
            if isinstance(error, FileRecoveryError):
                raise
            raise FileRecoveryError(str(error)) from error
        return FileRecoveryOutcome(entry, review_result=result)

    def _rescan_review_workspace(self, changes):
        changes = tuple(changes)
        directory = self._workspace.save_dir
        if directory is None and changes:
            directory = os.path.dirname(changes[0].image_path)
        if directory and os.path.isdir(directory):
            self._workspace.scan(directory)

    @staticmethod
    def _resource_key(path):
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _recovery_temp_path(path):
        directory = os.path.dirname(os.path.abspath(path))
        return os.path.join(
            directory,
            ".labelimg-recovery-%s.tmp" % uuid.uuid4().hex,
        )


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
    """Restore one record while retaining unrelated later collection edits."""
    try:
        original = json.loads(original_content.decode("utf8"))
        processed = json.loads(processed_content.decode("utf8"))
        current = json.loads(current_content.decode("utf8"))
    except (UnicodeError, ValueError, TypeError) as error:
        raise FileRecoveryConflict(
            "CreateML collection is no longer valid: %s" % collection_path
        ) from error

    def matching(payload):
        if not isinstance(payload, list):
            raise FileRecoveryConflict(
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
            raise FileRecoveryConflict(
                "CreateML record identity changed: %s" % image_path
            )
        return matches[0]

    original_index = matching(original)
    processed_index = matching(processed)
    current_index = matching(current)
    if current[current_index] != processed[processed_index]:
        raise FileRecoveryConflict(
            "CreateML record changed after image processing: %s"
            % image_path
        )
    current[current_index] = original[original_index]
    return json.dumps(
        current,
        ensure_ascii=False,
        indent=2,
    ).encode("utf8")


def _merge_create_ml_processed_record(
    collection_path,
    image_path,
    accumulated_content,
    next_content,
):
    """Merge one prepared record into the batch's accumulated collection."""
    try:
        accumulated = json.loads(accumulated_content.decode("utf8"))
        next_payload = json.loads(next_content.decode("utf8"))
    except (UnicodeError, ValueError, TypeError) as error:
        raise FileOperationError(
            "CreateML collection is not valid: %s" % collection_path
        ) from error

    def matching(payload):
        if not isinstance(payload, list):
            raise FileOperationError(
                "CreateML collection root is not a list: %s"
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
            raise FileOperationError(
                "CreateML record identity is ambiguous: %s" % image_path
            )
        return matches[0]

    accumulated[matching(accumulated)] = next_payload[matching(next_payload)]
    return json.dumps(
        accumulated,
        ensure_ascii=False,
        indent=2,
    ).encode("utf8")
