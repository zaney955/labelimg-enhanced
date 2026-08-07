"""Session-only recovery for cross-file operations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import os
import uuid

from labelimg.annotation_storage import (
    MISSING_FINGERPRINT,
    ResourceFingerprint,
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
    IMAGE_PROCESSING = "imageProcessing"

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
class ImageProcessingRecoveryGroup:
    """One image and every physical resource that must recover with it."""

    image_path: str
    resources: tuple[TrashedResource, ...]
    original_contents: tuple = ()
    processed_contents: tuple = ()
    mergeable_create_ml_paths: tuple = ()

    @property
    def original_path(self):
        """Compatibility projection used by the image selection dialog."""
        return self.image_path


@dataclass(frozen=True)
class ReviewRecoveryRecord:
    image_path: str
    prior_verified: bool
    prior_questioned: bool
    result_verified: bool
    result_questioned: bool
    annotation_path: str | None = None


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
    """Retain the newest 20 entries and own recovery status transitions."""

    def __init__(self, capacity=20):
        self.capacity = capacity
        self._entries = []

    @property
    def entries(self):
        return tuple(self._entries)

    def entry(self, entry_id):
        return self._entry(entry_id)

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

    def record_image_processing(self, resources, *, target_count=None):
        resources = tuple(resources)
        return self.record_trash_operation(
            RecoveryOperation.IMAGE_PROCESSING,
            resources,
            target_count=(
                len(resources) if target_count is None else int(target_count)
            ),
        )

    def record_grouped_image_processing(self, groups):
        groups = tuple(groups)
        resources = tuple(
            resource for group in groups for resource in group.resources
        )
        if not groups or not resources:
            return None
        actionable = all(
            resource.identity.actionable for resource in resources
        )
        entry = FileRecoveryEntry(
            entry_id=uuid.uuid4().hex,
            operation=RecoveryOperation.IMAGE_PROCESSING,
            created_at=datetime.now(timezone.utc),
            target_count=len(groups),
            payload=groups,
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

    def recover_image_groups(self, entry_id, groups, executor):
        """Recover complete image/resource groups and retain other groups."""
        entry = self._entry(entry_id)
        if entry.operation is not RecoveryOperation.IMAGE_PROCESSING:
            raise FileRecoveryError(
                "group recovery is available only for image processing"
            )
        if not entry.recoverable:
            raise FileRecoveryError(
                "file operation is not currently recoverable"
            )
        groups = tuple(groups)
        if not groups:
            raise FileRecoveryError(
                "at least one processed image must be selected"
            )
        payload_by_path = {
            _resource_key(group.image_path): group
            for group in entry.payload
        }
        selected_keys = tuple(dict.fromkeys(
            _resource_key(group.image_path) for group in groups
        ))
        if any(key not in payload_by_path for key in selected_keys):
            raise FileRecoveryError(
                "the recovery selection is not part of this operation"
            )
        selected = tuple(payload_by_path[key] for key in selected_keys)
        try:
            result = executor(entry, selected)
        except FileRecoveryError as error:
            entry.status = RecoveryStatus.CONFLICT
            entry.detail = str(error)
            raise
        selected_key_set = set(selected_keys)
        remaining = tuple(
            group for group in entry.payload
            if _resource_key(group.image_path) not in selected_key_set
        )
        entry.payload = remaining
        entry.target_count = len(remaining)
        if remaining:
            entry.status = RecoveryStatus.RECOVERABLE
            entry.detail = (
                "Recovered %d image(s); %d image(s) remain recoverable."
                % (len(selected), len(remaining))
            )
        else:
            entry.status = RecoveryStatus.RESTORED
            entry.detail = "Recovered successfully"
        return result

    def recover(self, entry_id, executor):
        """Run one recovery implementation and own its status transition."""
        entry = self._entry(entry_id)
        if not entry.recoverable:
            raise FileRecoveryError(
                "file operation is not currently recoverable"
            )
        try:
            result = executor(entry)
        except FileRecoveryError as error:
            entry.status = RecoveryStatus.CONFLICT
            entry.detail = str(error)
            raise
        entry.status = RecoveryStatus.RESTORED
        if not entry.detail:
            entry.detail = "Recovered successfully"
        return result

    def recover_subset(self, entry_id, resources, executor):
        """Recover an explicit atomic subset and retain the remainder."""
        entry = self._entry(entry_id)
        if entry.operation is not RecoveryOperation.IMAGE_PROCESSING:
            raise FileRecoveryError(
                "subset recovery is available only for image processing"
            )
        if not entry.recoverable:
            raise FileRecoveryError(
                "file operation is not currently recoverable"
            )
        resources = tuple(resources)
        if not resources:
            raise FileRecoveryError(
                "at least one processed image must be selected"
            )
        payload_by_path = {
            _resource_key(resource.original_path): resource
            for resource in entry.payload
        }
        selected_keys = tuple(
            dict.fromkeys(
                _resource_key(resource.original_path)
                for resource in resources
            )
        )
        if any(key not in payload_by_path for key in selected_keys):
            raise FileRecoveryError(
                "the recovery selection is not part of this operation"
            )
        selected = tuple(payload_by_path[key] for key in selected_keys)
        try:
            result = executor(entry, selected)
        except FileRecoveryError as error:
            entry.status = RecoveryStatus.CONFLICT
            entry.detail = str(error)
            raise
        selected_key_set = set(selected_keys)
        remaining = tuple(
            resource
            for resource in entry.payload
            if _resource_key(resource.original_path) not in selected_key_set
        )
        entry.payload = remaining
        entry.target_count = len(remaining)
        if remaining:
            entry.status = RecoveryStatus.RECOVERABLE
            entry.detail = (
                "Recovered %d image(s); %d image(s) remain recoverable."
                % (len(selected), len(remaining))
            )
        else:
            entry.status = RecoveryStatus.RESTORED
            entry.detail = "Recovered successfully"
        return result

    def _entry(self, entry_id):
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        raise FileRecoveryError("unknown recovery entry")

    def _prepend(self, entry):
        self._entries.insert(0, entry)
        del self._entries[self.capacity :]


def _resource_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))
