"""Qt-free ownership of the active workbench image session."""

from dataclasses import dataclass
from enum import Enum
import os
import uuid


class TransitionBlocker(str, Enum):
    ANNOTATION_EDIT = "annotation_edit"
    IMAGE_CROP = "image_crop"
    EXTERNAL_CONFLICT = "external_conflict"


@dataclass(frozen=True)
class TransitionReadiness:
    allowed: bool
    blockers: tuple = ()


class TransitionRequirement(str, Enum):
    RESOLVE_CROP = "resolve_crop"
    FINISH_ANNOTATION_EDIT = "finish_annotation_edit"
    RESOLVE_EXTERNAL_CONFLICTS = "resolve_external_conflicts"
    RESOLVE_DIRTY_ANNOTATIONS = "resolve_dirty_annotations"


@dataclass(frozen=True)
class TransitionFacts:
    crop_active: bool = False
    annotation_edit_open: bool = False
    external_conflicts: tuple = ()
    dirty_images: tuple = ()

    def __post_init__(self):
        object.__setattr__(
            self, "external_conflicts", tuple(self.external_conflicts or ())
        )
        object.__setattr__(
            self,
            "dirty_images",
            tuple(
                os.path.abspath(os.fspath(path))
                for path in (self.dirty_images or ())
            ),
        )


@dataclass(frozen=True)
class TransitionPlan:
    revision: int
    source: str | None
    target: str | None
    requirements: tuple

    @property
    def ready(self):
        return not self.requirements


@dataclass(frozen=True)
class TransitionTicket:
    token: str
    revision: int
    source: str | None
    target: str | None


class WorkbenchSession:
    """Own the current image identity and explicit transition blockers."""

    def __init__(self, image_path=None):
        self._image_path = self._normalise(image_path)
        self._blockers = set()
        self._revision = 0
        self._authorized_token = None

    @property
    def image_path(self):
        return self._image_path

    def activate(self, image_path):
        readiness = self.transition_readiness()
        if not readiness.allowed:
            raise RuntimeError(
                "cannot activate another image while a transition is blocked"
            )
        plan = self.plan_transition(image_path, TransitionFacts())
        ticket = self.authorize_transition(plan, TransitionFacts())
        return self.commit_transition(ticket)

    def clear(self):
        readiness = self.transition_readiness()
        if not readiness.allowed:
            raise RuntimeError(
                "cannot clear the image while a transition is blocked"
            )
        plan = self.plan_transition(None, TransitionFacts())
        ticket = self.authorize_transition(plan, TransitionFacts())
        self.commit_transition(ticket)

    def plan_transition(self, target, facts):
        if not isinstance(facts, TransitionFacts):
            raise TypeError("transition planning requires TransitionFacts")
        requirements = []
        if facts.crop_active or TransitionBlocker.IMAGE_CROP in self._blockers:
            requirements.append(TransitionRequirement.RESOLVE_CROP)
        if (
            facts.annotation_edit_open
            or TransitionBlocker.ANNOTATION_EDIT in self._blockers
        ):
            requirements.append(TransitionRequirement.FINISH_ANNOTATION_EDIT)
        if (
            facts.external_conflicts
            or TransitionBlocker.EXTERNAL_CONFLICT in self._blockers
        ):
            requirements.append(
                TransitionRequirement.RESOLVE_EXTERNAL_CONFLICTS
            )
        if facts.dirty_images:
            requirements.append(
                TransitionRequirement.RESOLVE_DIRTY_ANNOTATIONS
            )
        return TransitionPlan(
            self._revision,
            self._image_path,
            self._normalise(target),
            tuple(requirements),
        )

    def authorize_transition(self, plan, facts):
        if not isinstance(plan, TransitionPlan):
            raise TypeError("transition authorization requires a plan")
        if plan.revision != self._revision or plan.source != self._image_path:
            raise RuntimeError("transition plan is stale")
        current = self.plan_transition(plan.target, facts)
        if current.requirements:
            raise RuntimeError("transition requirements are unresolved")
        token = uuid.uuid4().hex
        self._authorized_token = token
        return TransitionTicket(
            token,
            self._revision,
            self._image_path,
            plan.target,
        )

    def commit_transition(self, ticket):
        if not isinstance(ticket, TransitionTicket):
            raise TypeError("transition commit requires a ticket")
        if (
            ticket.token != self._authorized_token
            or ticket.revision != self._revision
            or ticket.source != self._image_path
        ):
            raise RuntimeError("transition ticket is stale or already consumed")
        self._image_path = ticket.target
        self._revision += 1
        self._authorized_token = None
        return self._image_path

    def cancel_transition(self, ticket):
        if (
            isinstance(ticket, TransitionTicket)
            and ticket.token == self._authorized_token
        ):
            self._authorized_token = None

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
