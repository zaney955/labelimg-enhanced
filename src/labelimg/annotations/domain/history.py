"""Bounded, Qt-free Undo and Redo state for annotation documents.

The module stores immutable document snapshots and exposes two-phase history
steps.  A caller prepares a step, projects its target, and commits the cursor
only after projection succeeds.
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class AnnotationBoxState:
    session_id: int
    label: str
    points: tuple
    line_rgba: tuple | None = None
    fill_rgba: tuple | None = None
    difficult: bool = False


@dataclass(frozen=True)
class AnnotationSnapshot:
    image_key: str
    image_size: tuple
    boxes: tuple = ()
    verified: bool = False
    questioned: bool = False
    image_fingerprint: object = None


@dataclass(frozen=True)
class SavedBaseline:
    revision_id: int
    target: object
    fingerprint: object


@dataclass(frozen=True)
class HistoryTransition:
    source_revision_id: int
    destination_revision_id: int
    source_snapshot: AnnotationSnapshot
    destination_snapshot: AnnotationSnapshot
    description: str
    affected_ids: tuple
    old_label: str | None = None
    new_label: str | None = None
    estimated_bytes: int = 0

    @property
    def affected_count(self):
        return len(self.affected_ids)


@dataclass(frozen=True)
class HistoryView:
    image_key: str
    snapshot: AnnotationSnapshot
    revision_id: int
    saved_baseline: SavedBaseline | None
    current_target: object
    can_undo: bool
    can_redo: bool
    undo_transition: HistoryTransition | None
    redo_transition: HistoryTransition | None
    undo_boundary_evicted: bool = False
    redo_boundary_evicted: bool = False

    @property
    def dirty(self):
        return (
            self.saved_baseline is None
            or self.revision_id != self.saved_baseline.revision_id
            or self.current_target != self.saved_baseline.target
        )


@dataclass(frozen=True)
class _EditToken:
    image_key: str
    before: AnnotationSnapshot
    description: str
    old_label: str | None
    new_label: str | None
    nonce: int


@dataclass(frozen=True)
class HistoryStep:
    image_key: str
    direction: str
    source_snapshot: AnnotationSnapshot
    target_snapshot: AnnotationSnapshot
    transition: HistoryTransition
    source_cursor: int
    target_cursor: int
    nonce: int


class AnnotationHistoryError(RuntimeError):
    pass


class UnknownImageHistory(AnnotationHistoryError):
    pass


class HistoryBusy(AnnotationHistoryError):
    pass


class HistoryUnavailable(AnnotationHistoryError):
    pass


@dataclass
class _ImageHistory:
    initial_snapshot: AnnotationSnapshot
    initial_revision_id: int
    transitions: list
    cursor: int
    baseline: SavedBaseline | None
    current_target: object = None
    open_token: object = None
    undo_boundary_evicted: bool = False
    redo_boundary_evicted: bool = False
    access_serial: int = 0

    @property
    def snapshot(self):
        if self.cursor:
            return self.transitions[self.cursor - 1].destination_snapshot
        return self.initial_snapshot

    @property
    def revision_id(self):
        if self.cursor:
            return self.transitions[self.cursor - 1].destination_revision_id
        return self.initial_revision_id


class AnnotationHistory:
    """Own independent, bounded annotation histories for one workspace."""

    def __init__(self, max_transitions_per_image=100, soft_byte_limit=256 << 20):
        if max_transitions_per_image < 1:
            raise ValueError("max_transitions_per_image must be positive")
        if soft_byte_limit < 1:
            raise ValueError("soft_byte_limit must be positive")
        self._max_transitions_per_image = max_transitions_per_image
        self._soft_byte_limit = soft_byte_limit
        self._images = {}
        self._next_revision_id = 1
        self._next_nonce = 1
        self._access_serial = 0

    def open_image(self, image_key, snapshot, saved_baseline=None):
        image_key = _normalise_key(image_key)
        _validate_snapshot(image_key, snapshot)
        if image_key in self._images:
            return self.view(image_key)
        revision_id = self._allocate_revision()
        baseline = _coerce_baseline(saved_baseline, revision_id)
        self._images[image_key] = _ImageHistory(
            initial_snapshot=snapshot,
            initial_revision_id=revision_id,
            transitions=[],
            cursor=0,
            baseline=baseline,
            current_target=baseline.target if baseline is not None else None,
        )
        self._touch(self._images[image_key])
        return self.view(image_key)

    def has_image(self, image_key):
        return _normalise_key(image_key) in self._images

    @property
    def image_keys(self):
        return tuple(self._images)

    def begin_edit(
        self,
        image_key,
        before,
        description,
        old_label=None,
        new_label=None,
    ):
        state = self._state(image_key)
        self._ensure_idle(state)
        if before != state.snapshot:
            raise AnnotationHistoryError(
                "edit source does not match the current history snapshot"
            )
        token = _EditToken(
            image_key=_normalise_key(image_key),
            before=before,
            description=str(description),
            old_label=old_label,
            new_label=new_label,
            nonce=self._allocate_nonce(),
        )
        state.open_token = token
        self._touch(state)
        return token

    def commit_edit(self, token, after, affected_ids=()):
        state = self._state(token.image_key)
        self._require_token(state, token)
        _validate_snapshot(token.image_key, after)
        if after == token.before:
            state.open_token = None
            return None

        transition = HistoryTransition(
            source_revision_id=state.revision_id,
            destination_revision_id=self._allocate_revision(),
            source_snapshot=token.before,
            destination_snapshot=after,
            description=token.description,
            affected_ids=tuple(dict.fromkeys(affected_ids)),
            old_label=token.old_label,
            new_label=token.new_label,
            estimated_bytes=_estimate_transition_bytes(token.before, after),
        )
        # Build the replacement branch before mutating the live history.  An
        # allocation failure must leave the edit token and prior branch intact
        # so the controller can restore the projected Canvas and cancel.
        transitions = state.transitions[: state.cursor] + [transition]
        state.transitions = transitions
        state.cursor += 1
        state.open_token = None
        state.redo_boundary_evicted = False
        self._trim_per_image(state)
        try:
            self._trim_workspace(active_key=token.image_key)
        except MemoryError:
            # Retention is a soft workspace target.  Once the transition is
            # recorded, a best-effort accounting allocation must not turn a
            # successful edit into an apparent commit failure.
            pass
        self._touch(state)
        return transition

    def cancel_edit(self, token):
        state = self._state(token.image_key)
        self._require_token(state, token)
        state.open_token = None
        self._touch(state)
        return state.snapshot

    def prepare_undo(self, image_key):
        state = self._state(image_key)
        self._ensure_idle(state)
        if state.cursor == 0:
            raise HistoryUnavailable("Undo is unavailable")
        transition = state.transitions[state.cursor - 1]
        step = HistoryStep(
            image_key=_normalise_key(image_key),
            direction="undo",
            source_snapshot=state.snapshot,
            target_snapshot=transition.source_snapshot,
            transition=transition,
            source_cursor=state.cursor,
            target_cursor=state.cursor - 1,
            nonce=self._allocate_nonce(),
        )
        state.open_token = step
        self._touch(state)
        return step

    def prepare_redo(self, image_key):
        state = self._state(image_key)
        self._ensure_idle(state)
        if state.cursor >= len(state.transitions):
            raise HistoryUnavailable("Redo is unavailable")
        transition = state.transitions[state.cursor]
        step = HistoryStep(
            image_key=_normalise_key(image_key),
            direction="redo",
            source_snapshot=state.snapshot,
            target_snapshot=transition.destination_snapshot,
            transition=transition,
            source_cursor=state.cursor,
            target_cursor=state.cursor + 1,
            nonce=self._allocate_nonce(),
        )
        state.open_token = step
        self._touch(state)
        return step

    def commit_step(self, step_token):
        state = self._state(step_token.image_key)
        self._require_token(state, step_token)
        if state.cursor != step_token.source_cursor:
            raise AnnotationHistoryError("history cursor changed during step")
        state.cursor = step_token.target_cursor
        state.open_token = None
        self._touch(state)
        return self.view(step_token.image_key)

    def abort_step(self, step_token):
        state = self._state(step_token.image_key)
        self._require_token(state, step_token)
        state.open_token = None
        self._touch(state)
        return self.view(step_token.image_key)

    def mark_saved(self, image_key, revision_id, target, fingerprint):
        """Acknowledge the immutable revision actually written to a target."""
        state = self._state(image_key)
        if state.open_token is not None:
            raise HistoryBusy("cannot move saved baseline during a history step")
        if not isinstance(revision_id, int) or revision_id < 1:
            raise ValueError("revision_id must be a positive integer")
        state.baseline = SavedBaseline(revision_id, target, fingerprint)
        self._touch(state)
        return self.view(image_key)

    def update_baseline_fingerprint(self, image_key, fingerprint):
        """Refresh a baseline changed by a coordinated file transaction."""
        state = self._state(image_key)
        self._ensure_idle(state)
        if state.baseline is None:
            return self.view(image_key)
        state.baseline = replace(
            state.baseline, fingerprint=fingerprint
        )
        self._touch(state)
        return self.view(image_key)

    def set_target(self, image_key, target):
        state = self._state(image_key)
        self._ensure_idle(state)
        state.current_target = target
        self._touch(state)
        return self.view(image_key)

    def rebase(self, image_key, snapshot, baseline):
        """Replace one image with a fresh externally established baseline."""
        image_key = _normalise_key(image_key)
        state = self._state(image_key)
        self._ensure_idle(state)
        _validate_snapshot(image_key, snapshot)
        revision_id = self._allocate_revision()
        state.initial_snapshot = snapshot
        state.initial_revision_id = revision_id
        state.transitions.clear()
        state.cursor = 0
        state.baseline = _coerce_baseline(baseline, revision_id)
        state.current_target = (
            state.baseline.target
            if state.baseline is not None
            else None
        )
        state.undo_boundary_evicted = False
        state.redo_boundary_evicted = False
        self._touch(state)
        return self.view(image_key)

    def rewrite_review_state(
        self,
        image_key,
        expected,
        replacement,
        fingerprint,
    ):
        """Apply a recovered file-level review change without losing box history."""
        state = self._state(image_key)
        self._ensure_idle(state)

        def rewritten(snapshot):
            actual = (snapshot.verified, snapshot.questioned)
            if actual != tuple(expected):
                raise AnnotationHistoryError(
                    "review state changed again in annotation history"
                )
            return replace(
                snapshot,
                verified=bool(replacement[0]),
                questioned=bool(replacement[1]),
            )

        initial = rewritten(state.initial_snapshot)
        transitions = [
            replace(
                transition,
                source_snapshot=rewritten(
                    transition.source_snapshot
                ),
                destination_snapshot=rewritten(
                    transition.destination_snapshot
                ),
            )
            for transition in state.transitions
        ]
        state.initial_snapshot = initial
        state.transitions = transitions
        if state.baseline is not None:
            state.baseline = replace(
                state.baseline,
                fingerprint=fingerprint,
            )
        self._touch(state)
        return self.view(image_key)

    def migrate_images(
        self,
        path_mapping,
        target_mapping=None,
        fingerprint_mapping=None,
    ):
        """Move complete histories to new image keys transactionally."""
        mapping = {
            _normalise_key(source): _normalise_key(destination)
            for source, destination in path_mapping.items()
        }
        if len(set(mapping.values())) != len(mapping):
            raise AnnotationHistoryError("history destinations must be unique")
        for source in mapping:
            state = self._state(source)
            self._ensure_idle(state)
        occupied = set(self._images).difference(mapping)
        collisions = occupied.intersection(mapping.values())
        if collisions:
            raise AnnotationHistoryError(
                "history destination already exists: %s"
                % sorted(collisions)[0]
            )
        target_mapping = {
            _normalise_key(source): destination
            for source, destination in (target_mapping or {}).items()
        }
        fingerprint_mapping = {
            _normalise_key(source): fingerprint
            for source, fingerprint in (
                fingerprint_mapping or {}
            ).items()
        }

        migrated = {}
        for source, destination in mapping.items():
            state = self._images[source]
            state.initial_snapshot = _snapshot_with_key(
                state.initial_snapshot,
                destination,
            )
            state.transitions = [
                replace(
                    transition,
                    source_snapshot=_snapshot_with_key(
                        transition.source_snapshot,
                        destination,
                    ),
                    destination_snapshot=_snapshot_with_key(
                        transition.destination_snapshot,
                        destination,
                    ),
                )
                for transition in state.transitions
            ]
            if source in target_mapping:
                new_target = target_mapping[source]
                state.current_target = new_target
                if state.baseline is not None:
                    state.baseline = replace(
                        state.baseline,
                        target=new_target,
                        fingerprint=fingerprint_mapping.get(
                            source,
                            state.baseline.fingerprint,
                        ),
                    )
            migrated[destination] = state
        for source in mapping:
            del self._images[source]
        self._images.update(migrated)
        return tuple(mapping.values())

    def remove_images(self, image_keys):
        keys = tuple(_normalise_key(key) for key in image_keys)
        for key in keys:
            state = self._state(key)
            self._ensure_idle(state)
        for key in keys:
            del self._images[key]
        return keys

    def clear_workspace(self):
        for state in self._images.values():
            self._ensure_idle(state)
        self._images.clear()

    def view(self, image_key):
        return self._view(image_key, touch=True)

    def peek(self, image_key):
        """Inspect history without changing retention LRU order."""
        return self._view(image_key, touch=False)

    def _view(self, image_key, touch):
        image_key = _normalise_key(image_key)
        state = self._state(image_key)
        if touch:
            self._touch(state)
        undo_transition = (
            state.transitions[state.cursor - 1] if state.cursor else None
        )
        redo_transition = (
            state.transitions[state.cursor]
            if state.cursor < len(state.transitions)
            else None
        )
        return HistoryView(
            image_key=image_key,
            snapshot=state.snapshot,
            revision_id=state.revision_id,
            saved_baseline=state.baseline,
            current_target=state.current_target,
            can_undo=undo_transition is not None,
            can_redo=redo_transition is not None,
            undo_transition=undo_transition,
            redo_transition=redo_transition,
            undo_boundary_evicted=state.undo_boundary_evicted,
            redo_boundary_evicted=state.redo_boundary_evicted,
        )

    def _state(self, image_key):
        image_key = _normalise_key(image_key)
        try:
            return self._images[image_key]
        except KeyError as error:
            raise UnknownImageHistory(image_key) from error

    @staticmethod
    def _ensure_idle(state):
        if state.open_token is not None:
            raise HistoryBusy("another history operation is already open")

    @staticmethod
    def _require_token(state, token):
        if state.open_token is not token:
            raise AnnotationHistoryError("stale or foreign history token")

    def _allocate_revision(self):
        revision_id = self._next_revision_id
        self._next_revision_id += 1
        return revision_id

    def _allocate_nonce(self):
        nonce = self._next_nonce
        self._next_nonce += 1
        return nonce

    def _touch(self, state):
        self._access_serial += 1
        state.access_serial = self._access_serial

    def _trim_per_image(self, state):
        excess = len(state.transitions) - self._max_transitions_per_image
        if excess <= 0:
            return
        if state.cursor < excess:
            return
        first_retained = state.transitions[excess - 1]
        state.initial_snapshot = first_retained.destination_snapshot
        state.initial_revision_id = first_retained.destination_revision_id
        del state.transitions[:excess]
        state.cursor -= excess
        state.undo_boundary_evicted = True

    def _trim_workspace(self, active_key):
        while self._estimated_bytes() > self._soft_byte_limit:
            candidates = sorted(
                (
                    (state.access_serial, key, state)
                    for key, state in self._images.items()
                    if state.transitions and key != active_key
                ),
                key=lambda item: item[0],
            )
            if not candidates:
                state = self._images[active_key]
                if len(state.transitions) <= 1:
                    break
            else:
                _, _key, state = candidates[0]
            if not self._trim_one_edge(state):
                break

    @staticmethod
    def _trim_one_edge(state):
        if not state.transitions:
            return False
        if state.cursor:
            first = state.transitions.pop(0)
            state.initial_snapshot = first.destination_snapshot
            state.initial_revision_id = first.destination_revision_id
            state.cursor -= 1
            state.undo_boundary_evicted = True
            return True
        state.transitions.pop()
        state.redo_boundary_evicted = True
        return True

    def _estimated_bytes(self):
        snapshots = {}
        boxes = {}
        transition_count = 0
        for state in self._images.values():
            retained = [state.initial_snapshot]
            for transition in state.transitions:
                transition_count += 1
                retained.extend(
                    (
                        transition.source_snapshot,
                        transition.destination_snapshot,
                    )
                )
            for snapshot in retained:
                snapshots[id(snapshot)] = snapshot
                for box in snapshot.boxes:
                    boxes[id(box)] = box
        point_count = sum(len(box.points) for box in boxes.values())
        label_bytes = sum(
            len(box.label.encode("utf8")) for box in boxes.values()
        )
        snapshot_tuple_bytes = sum(
            112 + 8 * len(snapshot.boxes)
            for snapshot in snapshots.values()
        )
        return (
            160 * len(boxes)
            + 32 * point_count
            + label_bytes
            + snapshot_tuple_bytes
            + 192 * transition_count
        )


def _normalise_key(image_key):
    return str(image_key)


def _validate_snapshot(image_key, snapshot):
    if not isinstance(snapshot, AnnotationSnapshot):
        raise TypeError("snapshot must be an AnnotationSnapshot")
    if snapshot.image_key != _normalise_key(image_key):
        raise ValueError("snapshot image_key does not match history image")
    ids = [box.session_id for box in snapshot.boxes]
    if len(ids) != len(set(ids)):
        raise ValueError("snapshot session identities must be unique")


def _coerce_baseline(value, revision_id):
    if value is None:
        return None
    if isinstance(value, SavedBaseline):
        return value
    if isinstance(value, tuple) and len(value) == 2:
        return SavedBaseline(revision_id, value[0], value[1])
    raise TypeError("saved_baseline must be SavedBaseline, pair, or None")


def _snapshot_with_key(snapshot, image_key):
    if snapshot.image_key == image_key:
        return snapshot
    return replace(snapshot, image_key=image_key)


def _estimate_transition_bytes(before, after):
    unique_boxes = {id(box): box for box in before.boxes + after.boxes}
    points = sum(len(box.points) for box in unique_boxes.values())
    labels = sum(len(box.label.encode("utf8")) for box in unique_boxes.values())
    return 256 + 160 * len(unique_boxes) + 32 * points + labels
