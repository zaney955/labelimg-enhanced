"""Atomic in-place image replacement with recoverable originals."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
import tempfile
import uuid

from labelimg.annotation_storage import fingerprint_path
from labelimg.file_recovery import TrashedResource


@dataclass(frozen=True)
class PreparedImageReplacement:
    path: str
    expected_fingerprint: object
    content: bytes

    def __post_init__(self):
        object.__setattr__(
            self,
            "path",
            os.path.abspath(os.fspath(self.path)),
        )
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError("replacement content must be non-empty bytes")


@dataclass(frozen=True)
class ImageReplacementCommit:
    resources: tuple[TrashedResource, ...]


@dataclass(frozen=True)
class ImageReplacementRecovery:
    restored_paths: tuple[str, ...]


class RecoverableImageReplacementError(RuntimeError):
    def __init__(self, message, *, retry_resources=()):
        super().__init__(message)
        self.retry_resources = tuple(retry_resources)


class RecoverableImageReplacementTransaction:
    """Hide staging, trash identities, rollback, and recovery conflicts."""

    def __init__(self, trash_adapter):
        self._trash = trash_adapter

    def commit(self, replacements):
        replacements = tuple(replacements)
        self._validate_replacements(replacements)
        paths = tuple(item.path for item in replacements)
        preflight = getattr(self._trash, "preflight", None)
        if preflight is None:
            raise RecoverableImageReplacementError(
                "the trash adapter cannot guarantee recoverable replacement"
            )
        try:
            preflight(paths)
        except Exception as error:
            raise RecoverableImageReplacementError(str(error)) from error
        self._verify_source_fingerprints(replacements)

        staged = {}
        moved = []
        installed_backups = []
        try:
            for item in replacements:
                staged[item.path] = _write_staged_content(
                    item.path,
                    item.content,
                )
            self._verify_source_fingerprints(replacements)
            for item in replacements:
                identity = self._trash.move(item.path)
                if (
                    identity is None
                    or not getattr(identity, "actionable", False)
                    or not self._trash.exists(identity)
                ):
                    raise RecoverableImageReplacementError(
                        "the system trash did not return a recoverable original"
                    )
                moved.append((item.path, identity))
            for item in replacements:
                os.replace(staged.pop(item.path), item.path)
        except Exception as error:
            rollback_errors = []
            for path, _identity in moved:
                if os.path.exists(path):
                    backup = _temporary_peer_path(path, "failed-result")
                    try:
                        os.replace(path, backup)
                        installed_backups.append(backup)
                    except Exception as rollback_error:
                        rollback_errors.append(rollback_error)
            for path, identity in reversed(moved):
                try:
                    if not os.path.exists(path):
                        self._trash.restore(identity, path)
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
            if rollback_errors:
                raise RecoverableImageReplacementError(
                    "image replacement and rollback failed: %s"
                    % rollback_errors[0]
                ) from error
            raise RecoverableImageReplacementError(str(error)) from error
        finally:
            for temporary in tuple(staged.values()) + tuple(installed_backups):
                try:
                    if os.path.exists(temporary):
                        os.remove(temporary)
                except OSError:
                    pass

        resources = tuple(
            TrashedResource(
                original_path=path,
                identity=identity,
                post_fingerprint=fingerprint_path(path),
            )
            for path, identity in moved
        )
        return ImageReplacementCommit(resources)

    def recover(self, resources):
        resources = tuple(resources)
        if not resources:
            raise RecoverableImageReplacementError(
                "at least one processed image must be selected"
            )
        self._validate_recovery_resources(resources)

        backups = {}
        restored = []
        retry_resources = resources
        try:
            for resource in resources:
                backup = _temporary_peer_path(
                    resource.original_path,
                    "processed-backup",
                )
                os.replace(resource.original_path, backup)
                backups[resource.original_path] = backup
            for resource in resources:
                self._trash.restore(
                    resource.identity,
                    resource.original_path,
                )
                restored.append(resource)
        except Exception as error:
            rollback_errors = []
            replacement_identities = {}
            for resource in reversed(restored):
                try:
                    replacement_identities[
                        resource.original_path
                    ] = self._trash.move(resource.original_path)
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
            for path, backup in backups.items():
                try:
                    if os.path.exists(backup):
                        os.replace(backup, path)
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
            retry_resources = tuple(
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
                raise RecoverableImageReplacementError(
                    "image recovery and rollback failed: %s"
                    % rollback_errors[0],
                    retry_resources=retry_resources,
                ) from error
            raise RecoverableImageReplacementError(
                str(error),
                retry_resources=retry_resources,
            ) from error
        else:
            for backup in backups.values():
                try:
                    if os.path.exists(backup):
                        os.remove(backup)
                except OSError:
                    pass
        return ImageReplacementRecovery(
            tuple(resource.original_path for resource in resources)
        )

    @staticmethod
    def _validate_replacements(replacements):
        if not replacements:
            raise RecoverableImageReplacementError(
                "at least one prepared image is required"
            )
        paths = [os.path.normcase(item.path) for item in replacements]
        if len(set(paths)) != len(paths):
            raise RecoverableImageReplacementError(
                "an image can appear only once in a replacement batch"
            )

    @staticmethod
    def _verify_source_fingerprints(replacements):
        conflicts = [
            item.path
            for item in replacements
            if fingerprint_path(item.path) != item.expected_fingerprint
        ]
        if conflicts:
            raise RecoverableImageReplacementError(
                "%s no longer matches the prepared source"
                % conflicts[0]
            )

    def _validate_recovery_resources(self, resources):
        paths = [
            os.path.normcase(os.path.abspath(resource.original_path))
            for resource in resources
        ]
        if len(set(paths)) != len(paths):
            raise RecoverableImageReplacementError(
                "an image can appear only once in a recovery selection"
            )
        conflicts = []
        for resource in resources:
            if (
                fingerprint_path(resource.original_path)
                != resource.post_fingerprint
            ):
                conflicts.append(
                    "%s no longer matches the processed result"
                    % resource.original_path
                )
            if not self._trash.exists(resource.identity):
                conflicts.append(
                    "%s is no longer available in trash"
                    % resource.original_path
                )
        if conflicts:
            raise RecoverableImageReplacementError("; ".join(conflicts))


def _write_staged_content(path, content):
    descriptor, temporary = tempfile.mkstemp(
        prefix=".%s.labelimg-image-" % os.path.basename(path),
        suffix=os.path.splitext(path)[1],
        dir=os.path.dirname(os.path.abspath(path)),
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return temporary


def _temporary_peer_path(path, purpose):
    directory = os.path.dirname(os.path.abspath(path))
    basename = os.path.basename(path)
    while True:
        candidate = os.path.join(
            directory,
            ".%s.labelimg-image-%s-%s"
            % (basename, purpose, uuid.uuid4().hex),
        )
        if not os.path.lexists(candidate):
            return candidate
