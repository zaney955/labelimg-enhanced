import os
import tempfile
import unittest

from PyQt5.QtGui import QImage

from labelimg.annotation_document import AnnotationDocument, AnnotationFormat
from labelimg.annotation_persistence import AnnotationSaveCoordinator
from labelimg.annotation_review import ReviewStateTransaction
from labelimg.annotation_workspace import AnnotationWorkspace, WorkspaceSave


class _NoEditing:
    @property
    def image_keys(self):
        return ()

    def has_image(self, _image_key):
        return False


class _Persistence:
    def __init__(self):
        self.propagated = []

    def verify_snapshot(self, _snapshot):
        pass

    def verify_baseline(self, _view):
        pass

    def propagate_resource_fingerprints(self, fingerprints):
        self.propagated.append(tuple(fingerprints))


class _Entry:
    def __init__(self, image_path, directory, shared_create_ml=None):
        self._image_path = image_path
        self._directory = directory
        self._shared_create_ml = shared_create_ml

    def path_for(self, annotation_format):
        if (
            annotation_format is AnnotationFormat.CREATE_ML
            and self._shared_create_ml is not None
        ):
            return self._shared_create_ml
        stem = os.path.splitext(os.path.basename(self._image_path))[0]
        return os.path.join(
            self._directory, stem + annotation_format.extension
        )


class _RecordingWorkspace:
    def __init__(self, directory, shared_create_ml=None, fail_images=()):
        self.directory = directory
        self.shared_create_ml = shared_create_ml
        self.fail_images = set(fail_images)
        self.yolo_vocabulary = ()
        self.saved = []
        self.batches = []

    def load_for_image(self, _image_path, _image_data):
        return None

    def entry(self, image_path):
        return _Entry(
            image_path,
            self.directory,
            shared_create_ml=self.shared_create_ml,
        )

    def save(
        self,
        document,
        _annotation_format,
        annotation_path=None,
    ):
        if document.image_path in self.fail_images:
            raise RuntimeError("review save failed")
        self.saved.append(document.image_path)
        return WorkspaceSave(
            annotation_path,
            document,
            fingerprints=((annotation_path, "saved"),),
        )

    def save_createml_batch(self, revision_documents, annotation_path):
        revision_documents = tuple(revision_documents)
        self.batches.append(revision_documents)
        return tuple(
            WorkspaceSave(
                annotation_path,
                document,
                revision_id=revision_id,
                fingerprints=((annotation_path, "saved"),),
            )
            for revision_id, document in revision_documents
        )


class ReviewStateTransactionTest(unittest.TestCase):
    def test_apply_keeps_ordinary_failures_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            first = os.path.join(directory, "first.png")
            second = os.path.join(directory, "second.png")
            workspace = _RecordingWorkspace(
                directory,
                fail_images=(second,),
            )
            transaction = ReviewStateTransaction(
                workspace,
                _NoEditing(),
                _Persistence(),
                image_data_for=lambda _path: object(),
            )

            result = transaction.apply(
                (first, second),
                "verified",
                AnnotationFormat.PASCAL_VOC,
            )

            self.assertEqual(
                tuple(update.image_path for update in result.updates),
                (first,),
            )
            self.assertEqual(result.failures[0][0], second)
            self.assertEqual(
                tuple(
                    record.image_path
                    for record in result.recovery_records
                ),
                (first,),
            )

    def test_apply_groups_one_create_ml_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            first = os.path.join(directory, "first.png")
            second = os.path.join(directory, "second.png")
            collection = os.path.join(directory, "annotations.json")
            workspace = _RecordingWorkspace(
                directory,
                shared_create_ml=collection,
            )
            transaction = ReviewStateTransaction(
                workspace,
                _NoEditing(),
                _Persistence(),
                image_data_for=lambda _path: object(),
            )

            result = transaction.apply(
                (first, second),
                "questioned",
                AnnotationFormat.CREATE_ML,
            )

            self.assertEqual(len(workspace.batches), 1)
            self.assertEqual(len(workspace.batches[0]), 2)
            self.assertEqual(len(result.updates), 2)
            self.assertTrue(
                all(
                    update.document.questioned
                    for update in result.updates
                )
            )

    def test_apply_and_recover_round_trip_empty_pascal_document(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = os.path.join(directory, "blank.png")
            image = QImage(20, 20, QImage.Format_RGB32)
            image.fill(0)
            self.assertTrue(image.save(image_path))
            workspace = AnnotationWorkspace(save_dir=directory)
            editing = _NoEditing()
            image_data_for = lambda path: QImage(path)
            persistence = AnnotationSaveCoordinator(
                workspace,
                editing,
                image_data_for=image_data_for,
            )
            transaction = ReviewStateTransaction(
                workspace,
                editing,
                persistence,
                image_data_for=image_data_for,
            )

            applied = transaction.apply(
                (image_path,),
                "verified",
                AnnotationFormat.PASCAL_VOC,
            )
            annotation_path = applied.updates[0].recovery_record.annotation_path
            self.assertTrue(os.path.exists(annotation_path))
            self.assertTrue(
                AnnotationDocument.load(
                    annotation_path,
                    image_path,
                    QImage(image_path),
                ).verified
            )

            recovered = transaction.recover(applied.recovery_records)

            self.assertEqual(len(recovered.updates), 1)
            self.assertFalse(os.path.exists(annotation_path))


if __name__ == "__main__":
    unittest.main()
