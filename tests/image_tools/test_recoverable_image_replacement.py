import os
import shutil
import tempfile
import unittest

from labelimg.annotations.infrastructure.storage import fingerprint_path
from labelimg.files.application.recovery import TrashIdentity
from labelimg.image_tools.infrastructure.recoverable_replacement import (
    PreparedImageReplacement,
    RecoverableImageReplacementError,
    RecoverableImageReplacementTransaction,
)


class FakeTrash:
    def __init__(self, directory):
        self.directory = directory
        self.items = {}
        self.counter = 0
        self.preflighted = []

    def preflight(self, paths):
        self.preflighted.append(tuple(paths))

    def move(self, path):
        self.counter += 1
        token = os.path.join(self.directory, str(self.counter))
        shutil.move(path, token)
        identity = TrashIdentity("path", token, path, actionable=True)
        self.items[token] = identity
        return identity

    def exists(self, identity):
        return os.path.exists(identity.token)

    def restore(self, identity, destination):
        shutil.move(identity.token, destination)


class FailSecondMoveTrash(FakeTrash):
    def move(self, path):
        if self.counter == 1:
            raise RuntimeError("second trash move failed")
        return super().move(path)


class FailSecondRestoreOnceTrash(FakeTrash):
    def __init__(self, directory):
        super().__init__(directory)
        self.restore_calls = 0
        self.failed = False

    def restore(self, identity, destination):
        self.restore_calls += 1
        if self.restore_calls == 2 and not self.failed:
            self.failed = True
            raise RuntimeError("second restore failed")
        return super().restore(identity, destination)


class RecoverableImageReplacementTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = self.temporary.name
        self.trash_directory = os.path.join(self.root, "trash")
        os.makedirs(self.trash_directory)

    def tearDown(self):
        self.temporary.cleanup()

    def source(self, name, content):
        path = os.path.join(self.root, name)
        with open(path, "wb") as target:
            target.write(content)
        return path

    @staticmethod
    def read(path):
        with open(path, "rb") as source:
            return source.read()

    def replacements(self):
        first = self.source("first.jpg", b"first-original")
        second = self.source("second.jpg", b"second-original")
        return (
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

    def test_commits_every_replacement_and_returns_recoverable_originals(self):
        trash = FakeTrash(self.trash_directory)
        replacements = self.replacements()
        transaction = RecoverableImageReplacementTransaction(trash)

        result = transaction.commit(replacements)

        self.assertEqual(trash.preflighted, [tuple(item.path for item in replacements)])
        self.assertEqual(self.read(replacements[0].path), b"first-processed")
        self.assertEqual(self.read(replacements[1].path), b"second-processed")
        self.assertEqual(len(result.resources), 2)
        for resource in result.resources:
            self.assertTrue(resource.identity.actionable)
            self.assertTrue(trash.exists(resource.identity))
            self.assertEqual(
                resource.post_fingerprint,
                fingerprint_path(resource.original_path),
            )

    def test_failed_commit_restores_every_original_and_removes_staged_files(self):
        trash = FailSecondMoveTrash(self.trash_directory)
        replacements = self.replacements()
        transaction = RecoverableImageReplacementTransaction(trash)

        with self.assertRaises(RecoverableImageReplacementError):
            transaction.commit(replacements)

        self.assertEqual(self.read(replacements[0].path), b"first-original")
        self.assertEqual(self.read(replacements[1].path), b"second-original")
        leftovers = [
            name
            for name in os.listdir(self.root)
            if ".labelimg-image-" in name
        ]
        self.assertEqual(leftovers, [])

    def test_recovers_only_the_explicit_subset(self):
        trash = FakeTrash(self.trash_directory)
        replacements = self.replacements()
        transaction = RecoverableImageReplacementTransaction(trash)
        committed = transaction.commit(replacements)

        recovered = transaction.recover((committed.resources[0],))

        self.assertEqual(recovered.restored_paths, (replacements[0].path,))
        self.assertEqual(self.read(replacements[0].path), b"first-original")
        self.assertEqual(self.read(replacements[1].path), b"second-processed")
        self.assertTrue(trash.exists(committed.resources[1].identity))

    def test_external_change_blocks_recovery_without_touching_any_target(self):
        trash = FakeTrash(self.trash_directory)
        replacements = self.replacements()
        transaction = RecoverableImageReplacementTransaction(trash)
        committed = transaction.commit(replacements)
        with open(replacements[1].path, "wb") as target:
            target.write(b"external-change")

        with self.assertRaisesRegex(
            RecoverableImageReplacementError,
            "no longer matches",
        ):
            transaction.recover(committed.resources)

        self.assertEqual(self.read(replacements[0].path), b"first-processed")
        self.assertEqual(self.read(replacements[1].path), b"external-change")

    def test_failed_recovery_rolls_back_processed_files_and_can_retry(self):
        trash = FailSecondRestoreOnceTrash(self.trash_directory)
        replacements = self.replacements()
        transaction = RecoverableImageReplacementTransaction(trash)
        committed = transaction.commit(replacements)

        with self.assertRaises(RecoverableImageReplacementError) as failure:
            transaction.recover(committed.resources)

        retry_resources = failure.exception.retry_resources
        self.assertEqual(len(retry_resources), 2)
        self.assertEqual(self.read(replacements[0].path), b"first-processed")
        self.assertEqual(self.read(replacements[1].path), b"second-processed")

        recovered = transaction.recover(retry_resources)
        self.assertEqual(
            set(recovered.restored_paths),
            {replacements[0].path, replacements[1].path},
        )
        self.assertEqual(self.read(replacements[0].path), b"first-original")
        self.assertEqual(self.read(replacements[1].path), b"second-original")


if __name__ == "__main__":
    unittest.main()
