import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from labelimg.annotation_storage import (
    AnnotationResource,
    AnnotationSaveRequest,
    AnnotationStorageConflict,
    AnnotationStorageCoordinator,
    _atomic_commit_staged,
    fingerprint_path,
)


class AnnotationStorageTest(unittest.TestCase):
    def test_fingerprint_detects_same_size_content_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "labels.xml")
            with open(path, "wb") as output:
                output.write(b"cat")
            before = fingerprint_path(path)
            with open(path, "wb") as output:
                output.write(b"dog")
            os.utime(
                path,
                ns=(before.modified_ns, before.modified_ns),
            )

            after = fingerprint_path(path)

        self.assertEqual(after.size, before.size)
        self.assertEqual(after.modified_ns, before.modified_ns)
        self.assertNotEqual(after.sha256, before.sha256)

    def test_conflict_is_reported_before_writer_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "labels.xml")
            with open(path, "w", encoding="utf8") as output:
                output.write("external")
            request = AnnotationSaveRequest(
                image_key="image-a",
                revision_id=7,
                target=path,
                resources=(
                    AnnotationResource(path, fingerprint_path(path)),
                ),
            )
            with open(path, "w", encoding="utf8") as output:
                output.write("changed outside")
            calls = []

            with self.assertRaises(AnnotationStorageConflict):
                AnnotationStorageCoordinator().save(
                    request,
                    lambda _request: calls.append(True),
                )

        self.assertEqual(calls, [])

    def test_same_resource_writers_are_serialized(self):
        coordinator = AnnotationStorageCoordinator()
        active = 0
        maximum = 0
        gate = threading.Lock()

        def writer(_request):
            nonlocal active, maximum
            with gate:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with gate:
                active -= 1

        request = AnnotationSaveRequest(
            image_key="image-a",
            revision_id=1,
            target="shared.json",
            resources=(AnnotationResource("shared.json"),),
        )
        threads = [
            threading.Thread(
                target=coordinator.save,
                args=(request, writer),
            )
            for _index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(maximum, 1)

    def test_precommit_detects_change_during_writer_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "labels.xml")
            with open(path, "wb") as output:
                output.write(b"expected")
            request = AnnotationSaveRequest(
                image_key="image-a",
                revision_id=1,
                target=path,
                resources=(
                    AnnotationResource(path, fingerprint_path(path)),
                ),
            )

            def writer(guarded):
                with open(path, "wb") as output:
                    output.write(b"external")
                guarded.precommit()

            with self.assertRaises(AnnotationStorageConflict):
                AnnotationStorageCoordinator().save(request, writer)

            with open(path, "rb") as source:
                self.assertEqual(source.read(), b"external")

    def test_committed_save_survives_backup_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "labels.xml")
            staged = os.path.join(directory, "staged.xml")
            with open(target, "wb") as output:
                output.write(b"old")
            with open(staged, "wb") as output:
                output.write(b"new")

            with mock.patch(
                "labelimg.annotation_storage.os.remove",
                side_effect=PermissionError("locked backup"),
            ):
                _atomic_commit_staged(((staged, target),))

            with open(target, "rb") as source:
                self.assertEqual(source.read(), b"new")


if __name__ == "__main__":
    unittest.main()
