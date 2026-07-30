"""Selection set state and transitions.

This module deliberately has no Qt dependency. Canvas interaction translates
geometry into intents, while Qt widgets project the resulting snapshot.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionCapabilities:
    can_bulk: bool
    can_edit_single: bool


@dataclass(frozen=True)
class SelectionSnapshot:
    boxes: tuple
    selected: tuple
    active: object
    capabilities: SelectionCapabilities
    revision: int


class InvalidSelectionIntent(ValueError):
    pass


def _identity_tuple(items):
    return tuple(id(item) for item in items)


class SelectionSet:
    """Own the canonical Selection set and overlap-cycle state."""

    def __init__(self):
        self._snapshot = SelectionSnapshot(
            boxes=(),
            selected=(),
            active=None,
            capabilities=SelectionCapabilities(
                can_bulk=False,
                can_edit_single=False,
            ),
            revision=0,
        )
        self._overlap_candidates = ()
        self._overlap_index = -1

    @property
    def snapshot(self):
        return self._snapshot

    def set_scene(self, boxes, selected=None, active=None):
        """Replace scene boxes while preserving surviving selection by default."""
        boxes = tuple(boxes)
        self._validate_unique(boxes, "scene boxes")
        box_ids = set(_identity_tuple(boxes))

        if selected is None:
            requested = tuple(
                box
                for box in self._snapshot.selected
                if id(box) in box_ids
            )
            requested_active = (
                self._snapshot.active
                if id(self._snapshot.active) in box_ids
                else None
            )
        else:
            requested = tuple(selected)
            self._validate_known(requested, box_ids, "selected boxes")
            requested_active = active

        selected = self._ordered_subset(boxes, requested)
        active = self._normalise_active(selected, requested_active)
        self._reset_overlap_cycle()
        return self._commit(boxes, selected, active)

    def replace(self, candidates, active=None):
        """Replace the selection, normalised to the current scene order."""
        candidates = self._validated_candidates(candidates)
        self._reset_overlap_cycle()
        selected = self._ordered_subset(
            self._snapshot.boxes,
            candidates,
        )
        active = self._normalise_active(selected, active)
        return self._commit(self._snapshot.boxes, selected, active)

    def toggle(self, candidate, active=None):
        """Toggle one scene box without exposing transition details."""
        candidates = self._validated_candidates((candidate,))
        self._reset_overlap_cycle()
        selected_ids = set(_identity_tuple(self._snapshot.selected))
        if id(candidate) in selected_ids:
            requested = tuple(
                box
                for box in self._snapshot.selected
                if box is not candidate
            )
        else:
            requested = self._snapshot.selected + candidates
        selected = self._ordered_subset(self._snapshot.boxes, requested)
        active = self._normalise_active(
            selected,
            candidate if active is None else active,
        )
        return self._commit(self._snapshot.boxes, selected, active)

    def cycle(self, candidates):
        """Select one overlapping candidate, advancing on repeated calls."""
        candidates = self._validated_candidates(candidates)
        if not candidates:
            self._reset_overlap_cycle()
            return self._snapshot
        if _identity_tuple(candidates) == _identity_tuple(
            self._overlap_candidates
        ):
            self._overlap_index = (
                self._overlap_index + 1
            ) % len(candidates)
        else:
            self._overlap_candidates = candidates
            self._overlap_index = 0
        active = candidates[self._overlap_index]
        return self._commit(self._snapshot.boxes, (active,), active)

    def reset_cycle(self):
        """Forget overlap-cycle position without changing selection."""
        self._reset_overlap_cycle()
        return self._snapshot

    def _validated_candidates(self, candidates):
        boxes = self._snapshot.boxes
        box_ids = set(_identity_tuple(boxes))
        candidates = tuple(candidates)
        self._validate_unique(candidates, "selection candidates")
        self._validate_known(candidates, box_ids, "selection candidates")
        return candidates

    def _commit(self, boxes, selected, active):
        before = self._snapshot
        changed = (
            _identity_tuple(boxes) != _identity_tuple(before.boxes)
            or _identity_tuple(selected) != _identity_tuple(before.selected)
            or active is not before.active
        )
        if not changed:
            return before

        count = len(selected)
        self._snapshot = SelectionSnapshot(
            boxes=boxes,
            selected=selected,
            active=active,
            capabilities=SelectionCapabilities(
                can_bulk=count > 0,
                can_edit_single=count == 1,
            ),
            revision=before.revision + 1,
        )
        return self._snapshot

    def _reset_overlap_cycle(self):
        self._overlap_candidates = ()
        self._overlap_index = -1

    @staticmethod
    def _validate_unique(items, description):
        if len(_identity_tuple(items)) != len(set(_identity_tuple(items))):
            raise InvalidSelectionIntent(
                "%s must not contain duplicates" % description
            )

    @staticmethod
    def _validate_known(items, known_ids, description):
        unknown = [item for item in items if id(item) not in known_ids]
        if unknown:
            raise InvalidSelectionIntent(
                "%s must belong to the current scene" % description
            )

    @staticmethod
    def _ordered_subset(boxes, requested):
        requested_ids = set(_identity_tuple(requested))
        return tuple(box for box in boxes if id(box) in requested_ids)

    @staticmethod
    def _normalise_active(selected, active):
        if active is not None and any(box is active for box in selected):
            return active
        return selected[-1] if selected else None
