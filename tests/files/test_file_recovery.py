import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from labelimg.annotations.infrastructure.storage import MISSING_FINGERPRINT, fingerprint_path
from labelimg.annotations.application.workspace import AnnotationWorkspace
from labelimg.files.application.transaction import FileOperationTransaction
from labelimg.files.application.recovery import (
    FileRecoveryCenter,
    FileRecoveryConflict,
    RecoveryStatus,
    TrashIdentity,
    TrashedResource,
)


class _Editing:
    @property
    def image_keys(self):
        return ()

    def has_image(self, _image_key):
        return False

    def dirty_views(self):
        return ()


class _Scene:
    def forget_image(self, _image_key):
        pass


class _Persistence:
    conflicts = {}

    def release(self, _view):
        pass

    def track(self, _view):
        pass

    def resource_keys_for(self, _view):
        return ()

    def replace_conflicts(self, _conflicts):
        pass


class _ReviewTransaction:
    def recover(self, _changes):
        raise AssertionError("review recovery was not expected")


def file_transaction(
    directory,
    center,
    trash,
    *,
    editing=None,
    persistence=None,
    review_transaction=None,
):
    return FileOperationTransaction(
        AnnotationWorkspace(save_dir=directory),
        editing or _Editing(),
        _Scene(),
        persistence or _Persistence(),
        review_transaction or _ReviewTransaction(),
        trash,
        recovery_center=center,
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
    def test_review_recovery_dispatches_without_a_window_context(self):
        with tempfile.TemporaryDirectory() as directory:
            trash_dir = os.path.join(directory, "trash")
            os.makedirs(trash_dir)
            center = FileRecoveryCenter()
            entry = center.record_review(("change",))

            class ReviewTransaction:
                def __init__(self):
                    self.changes = None

                def recover(self, changes):
                    self.changes = tuple(changes)
                    return "review-result"

            review = ReviewTransaction()
            transaction = file_transaction(
                directory,
                center,
                FakeTrashAdapter(trash_dir),
                review_transaction=review,
            )

            outcome = transaction.recover(entry.entry_id)

            self.assertEqual(review.changes, ("change",))
            self.assertEqual(outcome.review_result, "review-result")
            self.assertEqual(entry.status, RecoveryStatus.RESTORED)

    def test_clear_recovery_is_blocked_by_dirty_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "labels.xml")
            view = SimpleNamespace(image_key="image.png")

            class DirtyEditing(_Editing):
                def dirty_views(self):
                    return (view,)

            class DirtyPersistence(_Persistence):
                def resource_keys_for(self, _view):
                    return (os.path.normcase(os.path.abspath(path)),)

            trash_dir = os.path.join(directory, "trash")
            os.makedirs(trash_dir)
            trash = FakeTrashAdapter(trash_dir)
            center = FileRecoveryCenter()
            entry = center.record_trash_operation(
                "clear",
                (
                    TrashedResource(
                        path,
                        TrashIdentity("fake", "missing", path),
                    ),
                ),
                target_count=1,
            )
            transaction = file_transaction(
                directory,
                center,
                trash,
                editing=DirtyEditing(),
                persistence=DirtyPersistence(),
            )

            with self.assertRaisesRegex(
                FileRecoveryConflict,
                "Unsaved annotation content",
            ):
                transaction.recover(entry.entry_id)

            self.assertEqual(entry.status, RecoveryStatus.CONFLICT)

    def test_committed_recovery_ignores_backup_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            trash_dir = os.path.join(directory, "trash")
            os.makedirs(trash_dir)
            path = os.path.join(directory, "labels.xml")
            with open(path, "wb") as output:
                output.write(b"old")
            adapter = FakeTrashAdapter(trash_dir)
            identity = adapter.move(path)
            with open(path, "wb") as output:
                output.write(b"empty")
            center = FileRecoveryCenter()
            entry = center.record_trash_operation(
                "clear",
                (
                    TrashedResource(
                        path,
                        identity,
                        fingerprint_path(path),
                    ),
                ),
                1,
            )
            transaction = file_transaction(directory, center, adapter)
            real_remove = os.remove

            def fail_backup_cleanup(candidate):
                if ".labelimg-recovery-" in candidate:
                    raise PermissionError("locked backup")
                return real_remove(candidate)

            with mock.patch(
                "labelimg.files.application.transaction.os.remove",
                fail_backup_cleanup,
            ):
                transaction.recover(entry.entry_id)

            with open(path, "rb") as source:
                self.assertEqual(source.read(), b"old")
            self.assertEqual(entry.status, RecoveryStatus.RESTORED)

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
            transaction = file_transaction(directory, center, trash)

            transaction.recover(entry.entry_id)

            self.assertTrue(os.path.isfile(path))
            self.assertEqual(entry.status, RecoveryStatus.RESTORED)
            with self.assertRaises(Exception):
                transaction.recover(entry.entry_id)

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
            transaction = file_transaction(directory, center, trash)

            with self.assertRaises(FileRecoveryConflict):
                transaction.recover(entry.entry_id)

            self.assertFalse(os.path.exists(paths[0]))
            self.assertEqual(entry.status, RecoveryStatus.CONFLICT)

            os.remove(paths[1])
            transaction.recover(entry.entry_id)
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
            transaction = file_transaction(directory, center, trash)

            with self.assertRaises(Exception):
                transaction.recover(entry.entry_id)
            self.assertFalse(any(os.path.exists(path) for path in paths))

            transaction.recover(entry.entry_id)
            self.assertTrue(all(os.path.isfile(path) for path in paths))


if __name__ == "__main__":
    unittest.main()
