"""Session-only recovery for cross-file operations."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import os
import tempfile
import uuid

from labelimg.annotation_storage import (
    MISSING_FINGERPRINT,
    ResourceFingerprint,
    fingerprint_path,
)


class RecoveryStatus(Enum):
    RECOVERABLE = "recoverable"
    CONFLICT = "conflict"
    MANUAL_TRASH = "manual trash"
    RESTORED = "restored"
    UNAVAILABLE = "unavailable"


class RecoveryOperation(str, Enum):
    DELETE = "delete"
    CLEAR = "clear"
    RENAME = "rename"
    REVIEW = "review"

    def __str__(self):
        return self.value


@dataclass(frozen=True)
class TrashIdentity:
    backend: str
    token: object
    original_path: str
    actionable: bool = True


@dataclass(frozen=True)
class TrashedResource:
    original_path: str
    identity: TrashIdentity
    post_fingerprint: ResourceFingerprint = MISSING_FINGERPRINT


@dataclass(frozen=True)
class ReviewRecoveryRecord:
    image_path: str
    prior_verified: bool
    prior_questioned: bool
    result_verified: bool
    result_questioned: bool


@dataclass
class FileRecoveryEntry:
    entry_id: str
    operation: str
    created_at: datetime
    target_count: int
    payload: object
    status: RecoveryStatus
    detail: str = ""

    @property
    def recoverable(self):
        return self.status in (
            RecoveryStatus.RECOVERABLE,
            RecoveryStatus.CONFLICT,
        )


class FileRecoveryError(RuntimeError):
    pass


class FileRecoveryConflict(FileRecoveryError):
    pass


class FileRecoveryCenter:
    """Retain and execute the newest 20 whole-operation recoveries."""

    def __init__(self, capacity=20):
        self.capacity = capacity
        self._entries = []

    @property
    def entries(self):
        return tuple(self._entries)

    def clear(self):
        self._entries.clear()

    def record_trash_operation(self, operation, resources, target_count):
        resources = tuple(resources)
        if not resources:
            return None
        actionable = all(
            resource.identity.actionable for resource in resources
        )
        entry = FileRecoveryEntry(
            entry_id=uuid.uuid4().hex,
            operation=RecoveryOperation(operation),
            created_at=datetime.now(timezone.utc),
            target_count=int(target_count),
            payload=resources,
            status=(
                RecoveryStatus.RECOVERABLE
                if actionable
                else RecoveryStatus.MANUAL_TRASH
            ),
            detail=(
                ""
                if actionable
                else "The system trash did not return a restorable identity."
            ),
        )
        self._prepend(entry)
        return entry

    def record_rename(self, mapping):
        entry = FileRecoveryEntry(
            entry_id=uuid.uuid4().hex,
            operation=RecoveryOperation.RENAME,
            created_at=datetime.now(timezone.utc),
            target_count=len(mapping),
            payload=tuple(mapping.items()),
            status=RecoveryStatus.RECOVERABLE,
        )
        self._prepend(entry)
        return entry

    def record_review(self, changes):
        entry = FileRecoveryEntry(
            entry_id=uuid.uuid4().hex,
            operation=RecoveryOperation.REVIEW,
            created_at=datetime.now(timezone.utc),
            target_count=len(changes),
            payload=tuple(changes),
            status=RecoveryStatus.RECOVERABLE,
        )
        self._prepend(entry)
        return entry

    def recover(self, entry_id, trash_adapter=None, context=None):
        entry = self._entry(entry_id)
        if not entry.recoverable:
            raise FileRecoveryError(
                "file operation is not currently recoverable"
            )
        try:
            if entry.operation in (
                RecoveryOperation.DELETE,
                RecoveryOperation.CLEAR,
            ):
                if trash_adapter is None:
                    raise FileRecoveryError("trash adapter is required")
                self._recover_trashed(entry, trash_adapter)
            elif entry.operation is RecoveryOperation.RENAME:
                if context is None:
                    raise FileRecoveryError("recovery context is required")
                context.recover_rename(dict(entry.payload))
            elif entry.operation is RecoveryOperation.REVIEW:
                if context is None:
                    raise FileRecoveryError("recovery context is required")
                context.recover_review(entry.payload)
            else:
                raise FileRecoveryError(
                    "unsupported recovery operation: %s"
                    % entry.operation
                )
        except FileRecoveryError as error:
            entry.status = RecoveryStatus.CONFLICT
            entry.detail = str(error)
            raise
        entry.status = RecoveryStatus.RESTORED
        entry.detail = "Recovered successfully"
        return entry

    def _recover_trashed(self, entry, adapter):
        resources = entry.payload
        conflicts = []
        for resource in resources:
            actual = fingerprint_path(resource.original_path)
            if actual != resource.post_fingerprint:
                conflicts.append(
                    "%s no longer matches the operation result"
                    % resource.original_path
                )
            if not adapter.exists(resource.identity):
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
                    backup = _recovery_temp_path(resource.original_path)
                    os.replace(resource.original_path, backup)
                    backups[resource.original_path] = backup
                adapter.restore(
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
                    ] = adapter.move(resource.original_path)
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
            for original, backup in backups.items():
                try:
                    if os.path.exists(backup):
                        os.replace(backup, original)
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
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
                    "recovery and rollback failed: %s"
                    % rollback_errors[0]
                ) from error
            raise FileRecoveryError(str(error)) from error
        else:
            for backup in backups.values():
                if os.path.exists(backup):
                    os.remove(backup)

    def _entry(self, entry_id):
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        raise FileRecoveryError("unknown recovery entry")

    def _prepend(self, entry):
        self._entries.insert(0, entry)
        del self._entries[self.capacity :]


def _recovery_temp_path(path):
    directory = os.path.dirname(os.path.abspath(path))
    return os.path.join(
        directory,
        ".labelimg-recovery-%s.tmp" % uuid.uuid4().hex,
    )
