import os
import json
import shutil
import tempfile
import unittest

from labelimg.annotation_storage import fingerprint_path
from labelimg.file_operation_transaction import FileOperationTransaction
from labelimg.file_recovery import (
    FileRecoveryCenter,
    RecoveryOperation,
    RecoveryStatus,
    TrashIdentity,
)
from labelimg.image_tools.recoverable_replacement import (
    PreparedImageReplacement,
)


class FakeTrash:
    def __init__(self, directory):
        self.directory = directory
        self.counter = 0

    def preflight(self, _paths):
        return None

    def move(self, path):
        self.counter += 1
        token = os.path.join(self.directory, str(self.counter))
        shutil.move(path, token)
        return TrashIdentity("path", token, path)

    @staticmethod
    def exists(identity):
        return os.path.exists(identity.token)

    @staticmethod
    def restore(identity, destination):
        shutil.move(identity.token, destination)


class ImageProcessingFileTransactionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = self.temporary.name
        trash_directory = os.path.join(self.root, "trash")
        os.makedirs(trash_directory)
        self.trash = FakeTrash(trash_directory)
        self.center = FileRecoveryCenter()
        self.transaction = FileOperationTransaction(
            None,
            None,
            None,
            None,
            None,
            self.trash,
            recovery_center=self.center,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def create(self, name, content):
        path = os.path.join(self.root, name)
        with open(path, "wb") as target:
            target.write(content)
        return path

    @staticmethod
    def read(path):
        with open(path, "rb") as source:
            return source.read()

    def test_commit_records_image_processing_and_subset_recovery(self):
        first = self.create("first.jpg", b"first-original")
        second = self.create("second.jpg", b"second-original")
        replacements = (
            PreparedImageReplacement(
                first,
                fingerprint_path(first),
                b"first-processed",
            ),
            PreparedImageReplacement(
                second,
                fingerprint_path(second),
                b"second-processed",
            ),
        )

        outcome = self.transaction.execute_image_processing(replacements)

        self.assertEqual(outcome.operation, RecoveryOperation.IMAGE_PROCESSING)
        self.assertEqual(outcome.recovery_entry.target_count, 2)
        self.assertEqual(self.read(first), b"first-processed")
        self.assertEqual(self.read(second), b"second-processed")

        recovery = self.transaction.recover(
            outcome.recovery_entry.entry_id,
            selected_paths=(first,),
        )

        self.assertEqual(recovery.restored_paths, (first,))
        self.assertEqual(self.read(first), b"first-original")
        self.assertEqual(self.read(second), b"second-processed")
        self.assertEqual(outcome.recovery_entry.target_count, 1)
        self.assertEqual(
            outcome.recovery_entry.status,
            RecoveryStatus.RECOVERABLE,
        )

        self.transaction.recover(outcome.recovery_entry.entry_id)
        self.assertEqual(self.read(second), b"second-original")
        self.assertEqual(
            outcome.recovery_entry.status,
            RecoveryStatus.RESTORED,
        )

    def test_replacing_trash_adapter_updates_image_processing_transaction(self):
        replacement_trash_directory = os.path.join(self.root, "trash-2")
        os.makedirs(replacement_trash_directory)
        replacement_trash = FakeTrash(replacement_trash_directory)
        self.transaction.replace_trash_adapter(replacement_trash)
        path = self.create("image.jpg", b"original")

        self.transaction.execute_image_processing((
            PreparedImageReplacement(
                path,
                fingerprint_path(path),
                b"processed",
            ),
        ))

        self.assertEqual(replacement_trash.counter, 1)
        self.assertEqual(self.trash.counter, 0)

    def test_geometry_processing_recovers_image_and_annotation_as_one_group(self):
        image = self.create("image.png", b"image-original")
        annotation = self.create("image.xml", b"annotation-original")
        outcome = self.transaction.execute_grouped_image_processing(
            image,
            (
                PreparedImageReplacement(
                    image,
                    fingerprint_path(image),
                    b"image-cropped",
                ),
                PreparedImageReplacement(
                    annotation,
                    fingerprint_path(annotation),
                    b"annotation-cropped",
                ),
            ),
        )

        self.assertEqual(outcome.recovery_entry.target_count, 1)
        self.assertEqual(
            outcome.recovery_entry.payload[0].image_path,
            image,
        )
        recovery = self.transaction.recover(
            outcome.recovery_entry.entry_id,
            selected_paths=(image,),
        )

        self.assertEqual(self.read(image), b"image-original")
        self.assertEqual(self.read(annotation), b"annotation-original")
        self.assertEqual(recovery.reload_images, (image,))
        self.assertEqual(
            set(recovery.restored_paths),
            {image, annotation},
        )

    def test_shared_create_ml_recovery_preserves_unrelated_later_changes(self):
        image = self.create("first.png", b"image-original")
        annotation = self.create(
            "annotations.json",
            json.dumps([
                {"image": "first.png", "annotations": [{"label": "old"}]},
                {"image": "second.png", "annotations": []},
            ]).encode("utf8"),
        )
        processed = json.dumps([
            {"image": "first.png", "annotations": [{"label": "cropped"}]},
            {"image": "second.png", "annotations": []},
        ]).encode("utf8")
        outcome = self.transaction.execute_grouped_image_processing(
            image,
            (
                PreparedImageReplacement(
                    image, fingerprint_path(image), b"image-cropped"
                ),
                PreparedImageReplacement(
                    annotation, fingerprint_path(annotation), processed
                ),
            ),
            mergeable_create_ml_paths=(annotation,),
        )
        with open(annotation, "w", encoding="utf8") as output:
            json.dump([
                {"image": "first.png", "annotations": [{"label": "cropped"}]},
                {"image": "second.png", "annotations": [{"label": "later"}]},
            ], output)

        self.transaction.recover(
            outcome.recovery_entry.entry_id,
            selected_paths=(image,),
        )

        with open(annotation, "r", encoding="utf8") as source:
            restored = json.load(source)
        self.assertEqual(restored[0]["annotations"], [{"label": "old"}])
        self.assertEqual(restored[1]["annotations"], [{"label": "later"}])

    def test_batch_merges_shared_create_ml_and_recovers_records_independently(self):
        first = self.create("first.png", b"first-original")
        second = self.create("second.png", b"second-original")
        original_records = [
            {"image": "first.png", "annotations": [{"label": "old-1"}]},
            {"image": "second.png", "annotations": [{"label": "old-2"}]},
        ]
        annotation = self.create(
            "annotations.json", json.dumps(original_records).encode("utf8")
        )

        def changed(index, label):
            records = json.loads(json.dumps(original_records))
            records[index]["annotations"] = [{"label": label}]
            return json.dumps(records).encode("utf8")

        fingerprint = fingerprint_path(annotation)
        outcome = self.transaction.execute_grouped_image_processing_batch((
            (
                first,
                (
                    PreparedImageReplacement(
                        first, fingerprint_path(first), b"first-processed"
                    ),
                    PreparedImageReplacement(
                        annotation, fingerprint, changed(0, "new-1")
                    ),
                ),
                (annotation,),
            ),
            (
                second,
                (
                    PreparedImageReplacement(
                        second, fingerprint_path(second), b"second-processed"
                    ),
                    PreparedImageReplacement(
                        annotation, fingerprint, changed(1, "new-2")
                    ),
                ),
                (annotation,),
            ),
        ))

        with open(annotation, "r", encoding="utf8") as source:
            processed = json.load(source)
        self.assertEqual(processed[0]["annotations"], [{"label": "new-1"}])
        self.assertEqual(processed[1]["annotations"], [{"label": "new-2"}])

        self.transaction.recover(
            outcome.recovery_entry.entry_id,
            selected_paths=(first,),
        )
        with open(annotation, "r", encoding="utf8") as source:
            partly_restored = json.load(source)
        self.assertEqual(partly_restored[0]["annotations"], [{"label": "old-1"}])
        self.assertEqual(partly_restored[1]["annotations"], [{"label": "new-2"}])

        self.transaction.recover(outcome.recovery_entry.entry_id)
        with open(annotation, "r", encoding="utf8") as source:
            restored = json.load(source)
        self.assertEqual(restored, original_records)


if __name__ == "__main__":
    unittest.main()
