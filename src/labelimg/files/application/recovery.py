"""Session-only recovery for cross-file operations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import uuid

from labelimg.platform.recovery import (
    RecoveryConflict,
    RecoveryError,
    RecoveryStatus,
    TrashIdentity,
    TrashedResource,
)


class RecoveryOperation(str, Enum):
    DELETE = "delete"
    CLEAR = "clear"
    RENAME = "rename"
    REVIEW = "review"

    def __str__(self):
        return self.value


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


FileRecoveryError = RecoveryError
FileRecoveryConflict = RecoveryConflict


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

    def _entry(self, entry_id):
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        raise FileRecoveryError("unknown recovery entry")

    def _prepend(self, entry):
        self._entries.insert(0, entry)
        del self._entries[self.capacity :]
