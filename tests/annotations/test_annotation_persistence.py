import os
import tempfile
import unittest
from dataclasses import replace

from labelimg.annotations.domain.model import AnnotationFormat
from labelimg.annotations.domain.history import (
    AnnotationSnapshot,
    HistoryView,
    SavedBaseline,
)
from labelimg.annotations.application.persistence import AnnotationSaveCoordinator
from labelimg.annotations.infrastructure.storage import (
    AnnotationStorageConflict,
    fingerprint_image,
    fingerprint_path,
)
from labelimg.annotations.application.workspace import WorkspaceSave, annotation_resources


class _Entry:
    def __init__(self, image_key, directory):
        self._image_key = image_key
        self._directory = directory

    def path_for(self, annotation_format):
        base = os.path.splitext(os.path.basename(self._image_key))[0]
        return os.path.join(
            self._directory, base + annotation_format.extension
        )


class _Workspace:
    def __init__(self, directory):
        self.directory = directory
        self.yolo_vocabulary = ()
        self.saved = []
        self.batches = []
        self.held = set()
        self.raise_on_save = None
        self.after_save = None

    def entry(self, image_key):
        return _Entry(image_key, self.directory)

    def save(
        self,
        document,
        annotation_format,
        annotation_path=None,
        revision_id=0,
    ):
        if self.raise_on_save is not None:
            raise self.raise_on_save
        annotation_path = os.path.abspath(annotation_path)
        self.saved.append((document.image_path, annotation_path))
        saved = WorkspaceSave(
            annotation_path,
            document,
            revision_id=revision_id,
            fingerprints=tuple(
                (path, fingerprint_path(path))
                for path in annotation_resources(
                    annotation_format, annotation_path
                )
            ),
        )
        if self.after_save is not None:
            self.after_save()
        return saved

    def save_createml_batch(self, revision_documents, annotation_path):
        revision_documents = tuple(revision_documents)
        self.batches.append(revision_documents)
        return tuple(
            WorkspaceSave(
                annotation_path,
                document,
                revision_id=revision_id,
                fingerprints=((annotation_path, fingerprint_path(annotation_path)),),
            )
            for revision_id, document in revision_documents
        )

    def hold_resource(self, resource, owner=None):
        self.held.add((resource, owner))

    def release_resource(self, resource, owner=None):
        self.held.discard((resource, owner))

    def accept_resource_fingerprints(self, _resources):
        pass

    def create_ml_image_names(self, _resource):
        return ()

    def create_ml_image_count(self, _resource):
        return 0

    def create_ml_image_keys(self, _resource, _image_keys):
        return ()


class _Editing:
    def __init__(self, views):
        self.views = {view.image_key: view for view in views}
        self.marked = []

    @property
    def image_keys(self):
        return tuple(self.views)

    def has_image(self, image_key):
        return image_key in self.views

    def view_image(self, image_key, touch=True):
        return self.views[image_key]

    def set_target(self, image_key, target):
        view = replace(self.views[image_key], current_target=target)
        self.views[image_key] = view
        return view

    def mark_image_saved(
        self, image_key, revision_id, target, fingerprint
    ):
        self.marked.append((image_key, revision_id, target, fingerprint))
        view = self.views[image_key]
        self.views[image_key] = replace(
            view,
            saved_baseline=SavedBaseline(
                revision_id, target, fingerprint
            ),
            current_target=target,
        )

    def update_baseline_fingerprint(self, image_key, fingerprint):
        view = self.views[image_key]
        self.views[image_key] = replace(
            view,
            saved_baseline=replace(
                view.saved_baseline, fingerprint=fingerprint
            ),
        )


def _view(image_key, revision_id=1, target=None, baseline=None):
    snapshot = AnnotationSnapshot(
        image_key=image_key,
        image_size=(10, 10),
        image_fingerprint=fingerprint_image(image_key, (10, 10)),
    )
    return HistoryView(
        image_key=image_key,
        snapshot=snapshot,
        revision_id=revision_id,
        saved_baseline=baseline,
        current_target=target,
        can_undo=False,
        can_redo=False,
        undo_transition=None,
        redo_transition=None,
    )


class AnnotationSaveCoordinatorTest(unittest.TestCase):
    def test_save_as_binds_and_acknowledges_the_exact_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            image = os.path.join(directory, "sample.png")
            with open(image, "wb") as output:
                output.write(b"image")
            workspace = _Workspace(directory)
            editing = _Editing((_view(image, revision_id=7),))
            session = AnnotationSaveCoordinator(workspace, editing)

            outcome = session.save(
                image,
                AnnotationFormat.PASCAL_VOC,
                target=os.path.join(directory, "chosen"),
            )

            self.assertTrue(outcome.ok)
            self.assertEqual(len(outcome.saved), 1)
            receipt = outcome.saved[0]
            self.assertEqual(receipt.image_key, image)
            self.assertFalse(receipt.still_dirty)
            self.assertEqual(
                editing.marked[0][1:3],
                (7, os.path.join(directory, "chosen.xml")),
            )

    def test_storage_conflict_is_retained_without_advancing_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            image = os.path.join(directory, "sample.png")
            target = os.path.join(directory, "sample.xml")
            with open(image, "wb") as output:
                output.write(b"image")
            workspace = _Workspace(directory)
            conflict = AnnotationStorageConflict(
                ((target, fingerprint_path(target), fingerprint_path(image)),)
            )
            workspace.raise_on_save = conflict
            editing = _Editing((_view(image, target=target),))
            session = AnnotationSaveCoordinator(workspace, editing)

            outcome = session.save(
                image, AnnotationFormat.PASCAL_VOC
            )

            self.assertFalse(outcome.ok)
            self.assertFalse(editing.marked)
            self.assertTrue(session.has_conflict(image))
            self.assertIn(
                os.path.normcase(os.path.abspath(target)),
                session.conflicts,
            )

    def test_shared_createml_revisions_are_saved_as_one_group(self):
        with tempfile.TemporaryDirectory() as directory:
            images = []
            for name in ("one.png", "two.png"):
                image = os.path.join(directory, name)
                with open(image, "wb") as output:
                    output.write(name.encode("ascii"))
                images.append(image)
            target = os.path.join(directory, "annotations.json")
            workspace = _Workspace(directory)
            editing = _Editing(
                tuple(_view(image, target=target) for image in images)
            )
            session = AnnotationSaveCoordinator(workspace, editing)

            outcome = session.save_many(
                images, AnnotationFormat.CREATE_ML
            )

            self.assertTrue(outcome.ok)
            self.assertEqual(len(workspace.batches), 1)
            self.assertEqual(len(workspace.batches[0]), 2)
            self.assertFalse(workspace.saved)

    def test_shared_resource_fingerprint_updates_peer_baselines(self):
        with tempfile.TemporaryDirectory() as directory:
            classes = os.path.join(directory, "classes.txt")
            with open(classes, "wb") as output:
                output.write(b"cat\n")
            updated = fingerprint_path(classes)
            views = []
            for name in ("one", "two"):
                image = os.path.join(directory, name + ".png")
                target = os.path.join(directory, name + ".txt")
                with open(image, "wb") as output:
                    output.write(name.encode("ascii"))
                resources = annotation_resources(
                    AnnotationFormat.YOLO, target
                )
                baseline = SavedBaseline(
                    1,
                    target,
                    tuple(
                        (resource, fingerprint_path(resource))
                        for resource in resources
                    ),
                )
                views.append(_view(image, target=target, baseline=baseline))
            editing = _Editing(tuple(views))
            session = AnnotationSaveCoordinator(
                _Workspace(directory), editing
            )

            session.propagate_resource_fingerprints(((classes, updated),))

            for view in editing.views.values():
                by_path = dict(view.saved_baseline.fingerprint)
                self.assertEqual(by_path[classes], updated)

    def test_save_acknowledges_written_revision_when_newer_edit_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            image = os.path.join(directory, "sample.png")
            with open(image, "wb") as output:
                output.write(b"image")
            workspace = _Workspace(directory)
            editing = _Editing((_view(image, revision_id=7),))
            session = AnnotationSaveCoordinator(workspace, editing)

            workspace.after_save = lambda: editing.views.__setitem__(
                image,
                replace(editing.views[image], revision_id=8),
            )
            outcome = session.save(
                image, AnnotationFormat.PASCAL_VOC
            )

            self.assertTrue(outcome.ok)
            self.assertTrue(outcome.saved[0].still_dirty)
            self.assertEqual(
                editing.views[image].saved_baseline.revision_id, 7
            )
            self.assertEqual(editing.views[image].revision_id, 8)

    def test_replacing_workspace_redirects_future_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            first_dir = os.path.join(directory, "first")
            second_dir = os.path.join(directory, "second")
            os.makedirs(first_dir)
            os.makedirs(second_dir)
            image = os.path.join(directory, "sample.png")
            with open(image, "wb") as output:
                output.write(b"image")
            first = _Workspace(first_dir)
            second = _Workspace(second_dir)
            editing = _Editing((_view(image),))
            session = AnnotationSaveCoordinator(first, editing)

            session.replace_workspace(second)
            outcome = session.save(
                image, AnnotationFormat.PASCAL_VOC
            )

            self.assertTrue(outcome.ok)
            self.assertFalse(first.saved)
            self.assertEqual(len(second.saved), 1)


if __name__ == "__main__":
    unittest.main()
