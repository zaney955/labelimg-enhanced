import os
import shutil
import tempfile
import unittest

from labelimg.annotation_storage import MISSING_FINGERPRINT
from labelimg.file_recovery import (
    FileRecoveryCenter,
    FileRecoveryConflict,
    RecoveryStatus,
    TrashIdentity,
    TrashedResource,
)


class FakeTrashAdapter:
    def __init__(self, directory):
        self.directory = directory
        self.tokens = {}

    def move(self, path):
        token = str(len(self.tokens) + 1)
        destination = os.path.join(self.directory, token)
        shutil.move(path, destination)
        identity = TrashIdentity("fake", token, path)
        self.tokens[token] = destination
        return identity

    def exists(self, identity):
        return os.path.exists(self.tokens.get(identity.token, ""))

    def restore(self, identity, destination):
        shutil.move(self.tokens[identity.token], destination)


class FailSecondRestoreOnce(FakeTrashAdapter):
    def __init__(self, directory):
        super().__init__(directory)
        self.restore_calls = 0

    def restore(self, identity, destination):
        self.restore_calls += 1
        if self.restore_calls == 2:
            raise RuntimeError("restore failed once")
        super().restore(identity, destination)


class FileRecoveryCenterTest(unittest.TestCase):
    def test_delete_recovery_is_strict_and_cannot_run_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            trash_dir = os.path.join(directory, "trash")
            os.makedirs(trash_dir)
            path = os.path.join(directory, "image.png")
            with open(path, "wb") as image:
                image.write(b"image")
            trash = FakeTrashAdapter(trash_dir)
            identity = trash.move(path)
            center = FileRecoveryCenter()
            entry = center.record_trash_operation(
                "delete",
                (
                    TrashedResource(
                        path,
                        identity,
                        MISSING_FINGERPRINT,
                    ),
                ),
                target_count=1,
            )

            center.recover(entry.entry_id, trash_adapter=trash)

            self.assertTrue(os.path.isfile(path))
            self.assertEqual(entry.status, RecoveryStatus.RESTORED)
            with self.assertRaises(Exception):
                center.recover(entry.entry_id, trash_adapter=trash)

    def test_collision_blocks_the_whole_entry_before_any_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            trash_dir = os.path.join(directory, "trash")
            os.makedirs(trash_dir)
            paths = [
                os.path.join(directory, name)
                for name in ("a.png", "b.png")
            ]
            trash = FakeTrashAdapter(trash_dir)
            resources = []
            for path in paths:
                with open(path, "wb") as image:
                    image.write(path.encode())
                identity = trash.move(path)
                resources.append(
                    TrashedResource(path, identity)
                )
            with open(paths[1], "wb") as collision:
                collision.write(b"new")
            center = FileRecoveryCenter()
            entry = center.record_trash_operation(
                "delete",
                resources,
                target_count=2,
            )

            with self.assertRaises(FileRecoveryConflict):
                center.recover(entry.entry_id, trash_adapter=trash)

            self.assertFalse(os.path.exists(paths[0]))
            self.assertEqual(entry.status, RecoveryStatus.CONFLICT)

            os.remove(paths[1])
            center.recover(entry.entry_id, trash_adapter=trash)
            self.assertTrue(all(os.path.isfile(path) for path in paths))
            self.assertEqual(entry.status, RecoveryStatus.RESTORED)

    def test_only_the_newest_twenty_entries_are_retained(self):
        center = FileRecoveryCenter()
        for index in range(21):
            center.record_rename({str(index): str(index + 1)})

        self.assertEqual(len(center.entries), 20)
        self.assertEqual(center.entries[0].payload, (("20", "21"),))
        self.assertEqual(center.entries[-1].payload, (("1", "2"),))

    def test_failed_recovery_rolls_back_with_retryable_new_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            trash_dir = os.path.join(directory, "trash")
            os.makedirs(trash_dir)
            trash = FailSecondRestoreOnce(trash_dir)
            resources = []
            paths = [
                os.path.join(directory, name)
                for name in ("a.png", "b.png")
            ]
            for path in paths:
                with open(path, "wb") as output:
                    output.write(path.encode())
                resources.append(
                    TrashedResource(path, trash.move(path))
                )
            center = FileRecoveryCenter()
            entry = center.record_trash_operation(
                "delete", resources, target_count=2
            )

            with self.assertRaises(Exception):
                center.recover(entry.entry_id, trash_adapter=trash)
            self.assertFalse(any(os.path.exists(path) for path in paths))

            center.recover(entry.entry_id, trash_adapter=trash)
            self.assertTrue(all(os.path.isfile(path) for path in paths))


if __name__ == "__main__":
    unittest.main()
