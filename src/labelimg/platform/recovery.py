"""Feature-neutral identities and statuses for recoverable resources."""

from dataclasses import dataclass
from enum import Enum



@dataclass(frozen=True)
class ResourceFingerprint:
    exists: bool
    size: int = 0
    modified_ns: int = 0
    sha256: str = ""


MISSING_FINGERPRINT = ResourceFingerprint(False)


class RecoveryStatus(Enum):
    RECOVERABLE = "recoverable"
    CONFLICT = "conflict"
    MANUAL_TRASH = "manual trash"
    RESTORED = "restored"
    UNAVAILABLE = "unavailable"


class RecoveryError(RuntimeError):
    pass


class RecoveryConflict(RecoveryError):
    pass


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
