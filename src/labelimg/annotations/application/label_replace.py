"""Preview and recover exact label replacements across active documents.

YOLO vocabularies stay append-only: replacing boxes never renumbers unrelated
classes, including annotations outside the chosen target set.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
import os
import tempfile

from labelimg.annotations.domain.model import AnnotationBox, AnnotationFormat
from labelimg.annotations.infrastructure.document import AnnotationDocument
from labelimg.annotations.infrastructure.storage import (
    AnnotationStorageConflict, fingerprint_path,
)
from labelimg.annotations.application.yolo_vocabulary import plan_yolo_vocabulary, shared_yolo_classes_path
from labelimg.platform.recovery import RecoveryConflict, RecoveryError


@dataclass(frozen=True)
class LabelReplacementItem:
    image_path: str
    target: str
    annotation_format: AnnotationFormat
    before: object
    after: object
    view: object = None

    @property
    def count(self):
        return sum(a.label != b.label for a, b in zip(self.before.boxes, self.after.boxes))


@dataclass(frozen=True)
class LabelReplacementPlan:
    old_label: str
    new_label: str
    items: tuple
    fingerprints: tuple
    merges: bool = False

    @property
    def box_count(self):
        return sum(item.count for item in self.items)


@dataclass(frozen=True)
class LabelReplacementRecovery:
    plan: LabelReplacementPlan
    original_contents: tuple
    result_fingerprints: tuple


@dataclass(frozen=True)
class LabelReplacementUpdate:
    image_path: str
    document: object
    snapshot: object = None


@dataclass(frozen=True)
class LabelReplacementResult:
    updates: tuple
    recovery: object = None


class LabelReplacementConflict(RecoveryConflict):
    def __init__(self, reason, image_path=''):
        self.reason = reason
        self.image_path = image_path
        super().__init__('Label replacement conflict (%s): %s' % (reason, image_path))


class LabelReplacementTransaction:
    def __init__(self, workspace, editing, persistence, *, image_data_for):
        self._workspace = workspace
        self._editing = editing
        self._persistence = persistence
        self._image_data_for = image_data_for

    def replace_workspace(self, workspace):
        self._workspace = workspace

    def preview(self, image_paths, old_label, new_label, default_format, progress=None):
        old_label, new_label = old_label.strip(), new_label.strip()
        if not old_label or not new_label or old_label == new_label:
            raise ValueError("Choose two different, nonempty labels")
        if any(char in new_label for char in "\r\n\x00"):
            raise ValueError("Label names cannot contain line breaks or null characters")
        items, fingerprints = [], {}
        merges = False
        paths = tuple(dict.fromkeys(map(str, image_paths)))
        for index, image_path in enumerate(paths):
            if progress is not None:
                progress(index, len(paths))
            view = None
            image_fingerprint = fingerprint_path(image_path)
            choices = self._workspace.refresh_document_choices(image_path)
            observed = {
                path: fingerprint_path(path)
                for choice in choices
                for path in self._workspace.resources_for(choice.annotation_format, choice.annotation_path)
            }
            if self._editing.has_image(image_path):
                view = self._editing.view_image(image_path, touch=False)
                self._persistence.verify_snapshot(view.snapshot)
                self._persistence.verify_baseline(view)
                document = AnnotationDocument(
                    image_path=image_path,
                    image_data=self._image_data_for(image_path),
                    boxes=tuple(AnnotationBox(box.label, box.points, box.difficult)
                                for box in view.snapshot.boxes),
                    class_names=self._workspace.yolo_vocabulary,
                    verified=view.snapshot.verified,
                    questioned=view.snapshot.questioned,
                )
                target = view.current_target
                # Preserve the complete CreateML record reference, including
                # subdirectories when equal basenames share one collection.
                if target and target.lower().endswith('.json') and os.path.isfile(target):
                    stored = self._workspace.load(target, image_path, document.image_data).document
                    document = replace(document, create_ml_record_name=stored.create_ml_record_name)
            else:
                if not choices:
                    continue
                loaded = self._workspace.load_for_image(image_path, self._image_data_for(image_path))
                if loaded is None:
                    continue
                document, target = loaded.document, loaded.annotation_path
            self._verify_fingerprints((*observed.items(), (image_path, image_fingerprint)))
            for path, fingerprint in observed.items():
                fingerprints.setdefault(path, fingerprint)
            fingerprints.setdefault(image_path, image_fingerprint)
            merges |= any(box.label == new_label for box in document.boxes)
            if not any(box.label == old_label for box in document.boxes):
                continue
            # Recovery retains annotation values, not compressed image bytes
            # for the entire dataset. Writers read verified images on demand.
            document = replace(document, image_data=None)
            target = target or self._workspace.entry(image_path).path_for(default_format)
            annotation_format = AnnotationFormat.from_path(target)
            resources = self._workspace.resources_for(annotation_format, target)
            # Fingerprint before the preview is presented. Recheck before any
            # write, including all consulted class mapping sources.
            for path in resources:
                fingerprints.setdefault(path, fingerprint_path(path))
            if annotation_format is AnnotationFormat.YOLO:
                vocabulary = plan_yolo_vocabulary(
                    target, save_dir=self._workspace.save_dir, image_dir=self._workspace.image_dir,
                    reserved=(*self._workspace.yolo_vocabulary, *document.class_names),
                    labels=(*(box.label for box in document.boxes), new_label),
                )
                for path, fingerprint in vocabulary.fingerprints:
                    fingerprints.setdefault(path, fingerprint)
            after = replace(document, boxes=tuple(
                replace(box, label=new_label) if box.label == old_label else box
                for box in document.boxes
            ))
            items.append(LabelReplacementItem(image_path, target, annotation_format, document, after, view))
        if progress is not None:
            progress(len(paths), len(paths))
        return LabelReplacementPlan(old_label, new_label, tuple(items), tuple(fingerprints.items()), merges)

    def apply(self, plan):
        self._ensure_idle()
        if not plan.items:
            return LabelReplacementResult(())
        resources = tuple(path for path, _fingerprint in plan.fingerprints)
        with self._workspace.storage_coordinator.lease(resources):
            self._verify_fingerprints(plan.fingerprints)
            for item in plan.items:
                if self._editing.has_image(item.image_path):
                    current = self._editing.view_image(item.image_path, touch=False)
                    if item.view is None or current != item.view:
                        raise LabelReplacementConflict('previewChanged', item.image_path)
                    self._persistence.verify_snapshot(current.snapshot)
                    self._persistence.verify_baseline(current)
            writable = {item.target for item in plan.items}
            for item in plan.items:
                if item.annotation_format is AnnotationFormat.YOLO:
                    writable.add(os.path.join(os.path.dirname(item.target), 'classes.txt'))
                    writable.add(shared_yolo_classes_path(item.target, self._workspace.save_dir, self._workspace.image_dir))
            before = tuple((path, self._read_bytes(path)) for path in resources if path in writable)
            try:
                self._write(plan.items)
            except Exception:
                self._restore(before, plan.fingerprints)
                self._refresh(plan.items)
                raise
            fingerprints = tuple((path, fingerprint_path(path)) for path in resources)
            self._persistence.propagate_resource_fingerprints(fingerprints)
            updates = []
            for item in plan.items:
                snapshot = None
                if item.view is not None:
                    snapshot = replace(item.view.snapshot, boxes=tuple(
                        replace(box, label=plan.new_label) if box.label == plan.old_label else box
                        for box in item.view.snapshot.boxes
                    ))
                    self._persistence.release(item.view)
                    self._editing.rebase_image(item.image_path, snapshot, self._baseline(item.target))
                updates.append(LabelReplacementUpdate(item.image_path, item.after, snapshot))
            changed = tuple((path, content) for path, content in before if self._read_bytes(path) != content)
            changed_paths = {path for path, _content in changed}
            return LabelReplacementResult(tuple(updates), LabelReplacementRecovery(
                plan, changed, tuple((path, value) for path, value in fingerprints if path in changed_paths),
            ))

    def recover(self, record):
        self._ensure_idle()
        resources = tuple(path for path, _fingerprint in record.result_fingerprints)
        with self._workspace.storage_coordinator.lease(resources):
            self._verify_fingerprints(record.result_fingerprints)
            prior_fingerprints = dict(record.plan.fingerprints)
            self._verify_fingerprints(tuple(
                (item.image_path, prior_fingerprints[item.image_path]) for item in record.plan.items
            ))
            for item in record.plan.items:
                if self._editing.has_image(item.image_path):
                    view = self._editing.view_image(item.image_path, touch=False)
                    if view.dirty:
                        raise LabelReplacementConflict('unsaved', item.image_path)
                    if (
                        view.current_target != item.target
                        or len(view.snapshot.boxes) != len(item.after.boxes)
                        or tuple(box.label for box in view.snapshot.boxes) != tuple(box.label for box in item.after.boxes)
                    ):
                        raise LabelReplacementConflict('targetChanged', item.image_path)
                    self._persistence.verify_snapshot(view.snapshot)
            # Later unsaved edits in a sibling of a shared collection/class
            # mapping also block whole-resource recovery.
            shared = {os.path.normcase(path) for path in resources}
            for view in self._editing.dirty_views():
                if shared.intersection(self._persistence.resource_keys_for(view)):
                    raise LabelReplacementConflict('sharedUnsaved', view.image_key)
            after = tuple((path, self._read_bytes(path)) for path in resources)
            try:
                self._restore(record.original_contents, record.plan.fingerprints)
            except Exception:
                self._restore(after, record.result_fingerprints)
                self._refresh(record.plan.items)
                raise
            updates = []
            for item in record.plan.items:
                snapshot = None
                if self._editing.has_image(item.image_path):
                    current = self._editing.view_image(item.image_path, touch=False)
                    self._persistence.release(current)
                    if item.view is not None:
                        snapshot = item.view.snapshot
                        baseline = self._baseline(item.target) if not item.view.dirty else item.view.saved_baseline
                    else:
                        snapshot = replace(current.snapshot, boxes=tuple(
                            replace(box, label=prior.label)
                            for box, prior in zip(current.snapshot.boxes, item.before.boxes)
                        ))
                        baseline = self._baseline(item.target)
                    restored = self._editing.rebase_image(item.image_path, snapshot, baseline)
                    if item.view is not None and item.view.dirty:
                        if item.view.current_target is not None:
                            restored = self._editing.set_target(item.image_path, item.view.current_target)
                        self._persistence.track(restored)
                updates.append(LabelReplacementUpdate(item.image_path, item.before, snapshot))
            self._refresh(record.plan.items)
            return LabelReplacementResult(tuple(updates))

    def _ensure_idle(self):
        if self._editing.pending or self._editing.edit_open:
            raise LabelReplacementConflict('busy')

    def _write(self, items):
        collections = defaultdict(list)
        for item in items:
            if item.annotation_format is AnnotationFormat.CREATE_ML:
                collections[item.target].append(item.after)
            else:
                self._workspace.save(item.after, item.annotation_format, annotation_path=item.target)
        for target, documents in collections.items():
            self._workspace.save_createml_batch(tuple((0, document) for document in documents), target)

    def _baseline(self, target):
        resources = self._workspace.resources_for(AnnotationFormat.from_path(target), target)
        return target, tuple((path, fingerprint_path(path)) for path in resources)

    def _refresh(self, items):
        resources = set()
        for item in items:
            resources.update(self._workspace.resources_for(item.annotation_format, item.target))
        self._workspace.accept_resource_fingerprints(resources)
        self._persistence.propagate_resource_fingerprints(tuple((path, fingerprint_path(path)) for path in resources))
        directory = self._workspace.save_dir or self._workspace.image_dir
        if directory:
            self._workspace.scan(directory)
        for view in self._editing.dirty_views():
            if view.current_target:
                self._workspace.record_document(view.image_key, view.current_target, (box.label for box in view.snapshot.boxes))

    @staticmethod
    def _verify_fingerprints(fingerprints):
        mismatches = tuple((path, expected, actual)
                           for path, expected in fingerprints
                           for actual in (fingerprint_path(path),) if actual != expected)
        if mismatches:
            raise AnnotationStorageConflict(mismatches)

    @staticmethod
    def _read_bytes(path):
        try:
            with open(path, 'rb') as source:
                return source.read()
        except FileNotFoundError:
            return None

    @staticmethod
    def _restore(contents, fingerprints=()):
        expected = dict(fingerprints)
        errors = []
        for path, content in contents:
            try:
                if content is None:
                    if os.path.exists(path):
                        os.remove(path)
                    continue
                descriptor, staged = tempfile.mkstemp(prefix='.labelimg-relabel-', dir=os.path.dirname(path))
                try:
                    with os.fdopen(descriptor, 'wb') as output:
                        output.write(content)
                    os.replace(staged, path)
                    prior = expected.get(path)
                    if prior is not None and prior.exists:
                        os.utime(path, ns=(os.stat(path).st_atime_ns, prior.modified_ns))
                finally:
                    if os.path.exists(staged):
                        os.remove(staged)
            except Exception as error:
                errors.append("%s: %s" % (path, error))
        if errors:
            raise RecoveryError("Label replacement rollback failed: %s" % "; ".join(errors))
