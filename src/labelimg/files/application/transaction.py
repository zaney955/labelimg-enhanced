"""File-list operations and recovery through one transaction interface."""

from dataclasses import dataclass, replace
import os
import uuid

from labelimg.annotations import RenamedAnnotationSessionMigrator, fingerprint_path
from labelimg.files.application.operations import (
    AnnotationFileService,
    FileOperationError,
    SynchronizedRenamer,
)
from labelimg.files.application.recovery import (
    FileRecoveryCenter,
    FileRecoveryConflict,
    FileRecoveryError,
    RecoveryOperation,
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

    @property
    def recovery_entries(self):
        return self._recovery.entries

    def clear_recovery(self):
        self._recovery.clear()

    def annotation_count(self, image_paths):
        return self._file_service().annotation_count(image_paths)

    def associated_annotation_resources(self, image_paths):
        return self._file_service().associated_annotation_resources(
            image_paths
        )

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

    def recover(self, entry_id, selected_paths=None):
        """Recover one complete recorded operation."""
        return self._recovery.recover(entry_id, self._recover_entry)

    def replace_workspace(self, workspace):
        self._workspace = workspace

    def replace_trash_adapter(self, trash_adapter):
        self._trash = trash_adapter

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
