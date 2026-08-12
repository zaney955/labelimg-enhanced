"""Session-only recovery ledger owned by image processing."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import os
import uuid

from labelimg.platform.recovery import RecoveryStatus, TrashedResource


class ImageProcessingOperation(str, Enum):
    PROCESS = "imageProcessing"

    def __str__(self):
        return self.value


@dataclass(frozen=True)
class ImageProcessingRecoveryGroup:
    """One image and every physical resource that recovers with it."""

    image_path: str
    resources: tuple[TrashedResource, ...]
    original_contents: tuple = ()
    processed_contents: tuple = ()
    mergeable_create_ml_paths: tuple = ()

    @property
    def original_path(self):
        return self.image_path


@dataclass
class ImageRecoveryEntry:
    entry_id: str
    operation: ImageProcessingOperation
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


class ImageRecoveryError(RuntimeError):
    pass


class ImageRecoveryConflict(ImageRecoveryError):
    pass


class ImageRecoveryCenter:
    """Own image-processing recovery entries and subset transitions."""

    def __init__(self, capacity=20):
        self.capacity = capacity
        self._entries = []

    @property
    def entries(self):
        return tuple(self._entries)

    def entry(self, entry_id):
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        raise ImageRecoveryError("unknown image-processing recovery entry")

    def clear(self):
        self._entries.clear()

    def record(self, resources, *, target_count=None):
        resources = tuple(resources)
        return self._record_payload(
            resources,
            len(resources) if target_count is None else int(target_count),
            resources,
        )

    def record_groups(self, groups):
        groups = tuple(groups)
        resources = tuple(
            resource for group in groups for resource in group.resources
        )
        return self._record_payload(groups, len(groups), resources)

    def _record_payload(self, payload, target_count, resources):
        resources = tuple(resources)
        if not payload or not resources:
            return None
        actionable = all(
            resource.identity.actionable for resource in resources
        )
        entry = ImageRecoveryEntry(
            entry_id=uuid.uuid4().hex,
            operation=ImageProcessingOperation.PROCESS,
            created_at=datetime.now(timezone.utc),
            target_count=target_count,
            payload=tuple(payload),
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
        self._entries.insert(0, entry)
        del self._entries[self.capacity :]
        return entry

    def recover_groups(self, entry_id, groups, executor):
        return self._recover_subset(
            entry_id,
            groups,
            key=lambda group: group.image_path,
            executor=executor,
            item_name="processed image",
        )

    def recover_resources(self, entry_id, resources, executor):
        return self._recover_subset(
            entry_id,
            resources,
            key=lambda resource: resource.original_path,
            executor=executor,
            item_name="processed image",
        )

    def _recover_subset(self, entry_id, selected, *, key, executor, item_name):
        entry = self.entry(entry_id)
        if not entry.recoverable:
            raise ImageRecoveryError(
                "image-processing operation is not currently recoverable"
            )
        selected = tuple(selected)
        if not selected:
            raise ImageRecoveryError("at least one %s must be selected" % item_name)
        payload_by_key = {_resource_key(key(item)): item for item in entry.payload}
        selected_keys = tuple(dict.fromkeys(
            _resource_key(key(item)) for item in selected
        ))
        if any(item_key not in payload_by_key for item_key in selected_keys):
            raise ImageRecoveryError(
                "the recovery selection is not part of this operation"
            )
        selected_payload = tuple(
            payload_by_key[item_key] for item_key in selected_keys
        )
        try:
            result = executor(entry, selected_payload)
        except ImageRecoveryError as error:
            entry.status = RecoveryStatus.CONFLICT
            entry.detail = str(error)
            raise
        selected_key_set = set(selected_keys)
        remaining = tuple(
            item for item in entry.payload
            if _resource_key(key(item)) not in selected_key_set
        )
        entry.payload = remaining
        entry.target_count = len(remaining)
        if remaining:
            entry.status = RecoveryStatus.RECOVERABLE
            entry.detail = (
                "Recovered %d image(s); %d image(s) remain recoverable."
                % (len(selected_payload), len(remaining))
            )
        else:
            entry.status = RecoveryStatus.RESTORED
            entry.detail = "Recovered successfully"
        return result


def _resource_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))
