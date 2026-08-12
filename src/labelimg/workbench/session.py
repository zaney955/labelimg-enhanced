"""Qt-free ownership of the active workbench image session."""

from dataclasses import dataclass
from enum import Enum
import os


class TransitionBlocker(str, Enum):
    ANNOTATION_EDIT = "annotation_edit"
    IMAGE_CROP = "image_crop"
    EXTERNAL_CONFLICT = "external_conflict"


@dataclass(frozen=True)
class TransitionReadiness:
    allowed: bool
    blockers: tuple = ()


class WorkbenchSession:
    """Own the current image identity and explicit transition blockers."""

    def __init__(self, image_path=None):
        self._image_path = self._normalise(image_path)
        self._blockers = set()

    @property
    def image_path(self):
        return self._image_path

    def activate(self, image_path):
        readiness = self.transition_readiness()
        if not readiness.allowed:
            raise RuntimeError(
                "cannot activate another image while a transition is blocked"
            )
        self._image_path = self._normalise(image_path)
        return self._image_path

    def clear(self):
        readiness = self.transition_readiness()
        if not readiness.allowed:
            raise RuntimeError(
                "cannot clear the image while a transition is blocked"
            )
        self._image_path = None

    def replace_active(self, image_path):
        """Project an already-authorized navigation result."""
        self._image_path = self._normalise(image_path)

    def set_blocked(self, blocker, blocked=True):
        blocker = TransitionBlocker(blocker)
        if blocked:
            self._blockers.add(blocker)
        else:
            self._blockers.discard(blocker)

    def transition_readiness(self):
        blockers = tuple(sorted(self._blockers, key=lambda value: value.value))
        return TransitionReadiness(not blockers, blockers)

    @staticmethod
    def _normalise(image_path):
        return None if not image_path else os.path.abspath(os.fspath(image_path))
