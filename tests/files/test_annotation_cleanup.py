"""Cleanup exercises directory pairing, reviewed deletion and recovery."""

import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from labelimg.annotations import AnnotationWorkspace
from labelimg.files.application.cleanup import (
    CleanupCanceled, CleanupError, scan_cleanup, verify_cleanup_selection,
)
from labelimg.files.application.transaction import FileOperationTransaction
from labelimg.platform.recovery import RecoveryStatus, TrashIdentity


BOX = '<annotation><object><name>cat</name><bndbox><xmin>1</xmin><ymin>1</ymin><xmax>9</xmax><ymax>9</ymax></bndbox></object></annotation>'


class FakeTrash:
    def __init__(self, directory):
        self.directory = directory
        self.preflight_paths = ()
        self.moves = []
        self.fail_name = None

    def preflight(self, paths):
        self.preflight_paths = tuple(paths)

    def move(self, path):
        if os.path.basename(path) == self.fail_name:
            raise RuntimeError("trash unavailable")
        destination = str(self.directory / str(len(self.moves)))
        shutil.move(path, destination)
        self.moves.append(path)
        return TrashIdentity("path", destination, path)

    def exists(self, identity):
        return os.path.exists(identity.token)

    def restore(self, identity, destination):
        shutil.move(identity.token, destination)


class AnnotationCleanupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.images = self.root / "images"
        self.labels = self.root / "labels"
        self.trash_dir = self.root / "trash"
        for directory in (self.images, self.labels, self.trash_dir):
            directory.mkdir()
        self.trash = FakeTrash(self.trash_dir)
        self.workspace = AnnotationWorkspace(image_dir=self.images, save_dir=self.labels)
        self.dirty = []
        self.resource_keys = ()
        self.transaction = FileOperationTransaction(
            self.workspace,
            SimpleNamespace(has_image=lambda _image: False, dirty_views=lambda: tuple(self.dirty)),
            SimpleNamespace(),
            SimpleNamespace(resource_keys_for=lambda _view: self.resource_keys),
            None, self.trash,
        )

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, text=""):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def scan(self, images=None, labels=None, report=None):
        return scan_cleanup(str(images or self.images), str(labels or self.labels), (".png", ".jpg"), report)

    def test_scan_differentiates_orphans_empty_variants_and_valid_annotations(self):
        for name in ("zero", "spaces", "objects", "valid", "review"):
            self.write("images/" + name + ".png")
        orphan = self.write("labels/absent.xml", BOX)
        zero = self.write("labels/zero.txt")
        spaces = self.write("labels/spaces.xml", " \n\t")
        objects = self.write("labels/objects.xml", "<annotation/>")
        review = self.write("labels/review.txt", "# labelimg-review: verified\n")
        valid = self.write("labels/valid.txt", "0 0.5 0.5 0.2 0.2\n")
        plan = self.scan()
        self.assertEqual({item.path: item.reason for item in plan.items}, {
            orphan: "orphan", zero: "zeroBytes", spaces: "whitespace", objects: "noObjects", review: "noObjects",
        })
        self.assertTrue(os.path.exists(valid))
        self.assertTrue(all(os.path.exists(item.path) for item in plan.items))

    def test_invalid_data_and_class_configurations_are_preserved(self):
        self.write("labels/classes.txt")
        self.write("labels/predefined_classes.txt")
        self.write("labels/data.yaml", "names: []")
        invalid = {self.write("labels/broken.xml", "<annotation>"), self.write("labels/config.json", "{}"), self.write("labels/readme.txt", "cat\ndog"), self.write("labels/not-voc.xml", "<config/>")}
        plan = self.scan()
        self.assertEqual(plan.items, ())
        self.assertEqual({path for path, _error in plan.skipped}, invalid)

    def test_relative_subdirectories_and_legacy_flat_annotations_match(self):
        self.write("images/category/a.png")
        mapped = self.write("labels/category/a.xml", "<annotation/>")
        flat = self.write("labels/a.txt")
        orphan = self.write("labels/other/a.xml", BOX)
        items = {item.path: item for item in self.scan().items}
        self.assertEqual(items[mapped].reason, "noObjects")
        self.assertEqual(items[flat].reason, "zeroBytes")
        self.assertEqual(items[orphan].reason, "orphan")

    def test_open_split_does_not_scan_other_label_splits(self):
        self.write("images/train/a.png")
        self.write("images/val/b.png")
        train = self.write("labels/train/a.txt")
        self.write("labels/val/b.txt")
        flat = self.write("labels/legacy.txt")
        plan = self.scan(self.images / "train")
        self.assertEqual({item.path for item in plan.items}, {train, flat})

    def test_same_directory_and_mixed_image_extensions_are_supported(self):
        self.write("images/a.jpg")
        label = self.write("images/a.XML", "<annotation/>")
        item, = self.scan(labels=self.images).items
        self.assertEqual(item.path, label)
        self.assertEqual(item.reason, "noObjects")

    def test_createml_collection_is_not_removed_when_any_record_is_nonempty(self):
        self.write("images/a.png")
        self.write("images/b.png")
        data = [
            {"image": "a.png", "annotations": []},
            {"image": "b.png", "annotations": [{"label": "cat", "coordinates": {"x": 5, "y": 5, "width": 2, "height": 2}}]},
        ]
        self.write("labels/shared.json", json.dumps(data))
        self.assertEqual(self.scan().items, ())

    def test_empty_shared_createml_and_unmatched_collection_are_classified(self):
        image = self.write("images/a.png")
        empty = self.write("labels/shared.json", json.dumps([{"image": "a.png", "annotations": []}, {"image": "missing.png", "annotations": []}]))
        orphan = self.write("labels/unmatched.json", json.dumps([{"image": "absent.png", "annotations": []}]))
        items = {item.path: item for item in self.scan().items}
        self.assertEqual(items[empty].reason, "noObjects")
        self.assertEqual(items[empty].image_paths, (image,))
        self.assertEqual(items[orphan].reason, "orphan")

    def test_single_createml_same_stem_obeys_directory_mapping(self):
        self.write("images/first/a.png")
        path = self.write("labels/second/a.json", json.dumps([{"image": "a.png", "annotations": []}]))
        self.assertEqual(self.scan().items[0].path, path)
        self.assertEqual(self.scan().items[0].reason, "orphan")

    def test_changed_annotation_or_added_image_invalidates_preview(self):
        path = self.write("labels/a.txt", "0 0.5 0.5 0.2 0.2")
        plan = self.scan()
        self.write("images/a.png")
        with self.assertRaises(CleanupError):
            verify_cleanup_selection(plan, plan.items)
        os.remove(self.images / "a.png")
        self.write("labels/a.txt", "0 0.3 0.3 0.1 0.1")
        with self.assertRaises(CleanupError):
            verify_cleanup_selection(plan, plan.items)
        self.assertTrue(os.path.isfile(path))

    def test_directory_read_error_aborts_the_scan(self):
        from unittest.mock import patch
        with patch("labelimg.files.application.cleanup.os.walk", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.scan()

    def test_cancel_scan_never_returns_an_actionable_partial_plan(self):
        path = self.write("labels/a.txt")
        def cancel(_path):
            raise CleanupCanceled()
        with self.assertRaises(CleanupCanceled):
            self.scan(report=cancel)
        self.assertTrue(os.path.isfile(path))

    def test_cleanup_moves_only_selected_annotations_and_recovers_the_batch(self):
        image = self.write("images/a.png")
        empty = self.write("labels/a.txt")
        orphan = self.write("labels/absent.xml", BOX)
        plan = self.scan()
        selected = tuple(item for item in plan.items if item.path == orphan)
        outcome = self.transaction.cleanup_annotations(plan, selected)
        self.assertEqual(outcome.file_result.removed_paths, [orphan])
        self.assertTrue(os.path.isfile(image))
        self.assertTrue(os.path.isfile(empty))
        self.assertFalse(os.path.exists(orphan))
        self.assertEqual(outcome.recovery_entry.operation, "cleanup")
        self.transaction.recover(outcome.recovery_entry.entry_id)
        self.assertEqual(Path(orphan).read_text(), BOX)
        self.assertEqual(outcome.recovery_entry.status, RecoveryStatus.RESTORED)

    def test_dirty_associated_image_blocks_deletion(self):
        image = self.write("images/a.png")
        path = self.write("labels/a.txt")
        self.dirty.append(SimpleNamespace(image_key=image))
        plan = self.scan()
        with self.assertRaisesRegex(CleanupError, "dirty"):
            self.transaction.cleanup_annotations(plan, plan.items)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.trash.moves, [])

    def test_dirty_shared_resource_blocks_even_an_orphan(self):
        path = self.write("labels/a.txt")
        self.dirty.append(SimpleNamespace(image_key="another.png"))
        self.resource_keys = (os.path.normcase(path),)
        plan = self.scan()
        with self.assertRaisesRegex(CleanupError, "dirty"):
            self.transaction.cleanup_annotations(plan, plan.items)

    def test_trash_preflight_changes_are_rechecked(self):
        path = self.write("labels/a.txt", "0 0.5 0.5 0.2 0.2")
        plan = self.scan()
        self.trash.preflight = lambda _paths: self.write("images/a.png")
        with self.assertRaisesRegex(CleanupError, "changed"):
            self.transaction.cleanup_annotations(plan, plan.items)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(self.trash.moves, [])

    def test_partial_failure_retains_recovery_for_successful_moves(self):
        first = self.write("labels/a.txt")
        second = self.write("labels/b.txt")
        self.trash.fail_name = "b.txt"
        plan = self.scan()
        outcome = self.transaction.cleanup_annotations(plan, plan.items)
        self.assertEqual(outcome.file_result.removed_paths, [first])
        self.assertEqual(len(outcome.file_result.failures), 1)
        self.assertTrue(os.path.isfile(second))
        self.transaction.recover(outcome.recovery_entry.entry_id)
        self.assertTrue(os.path.isfile(first))

    def test_cancel_cleanup_preserves_remaining_files_and_records_recovery(self):
        self.write("labels/a.txt")
        second = self.write("labels/b.txt")
        plan = self.scan()
        calls = iter((True, False))
        outcome = self.transaction.cleanup_annotations(plan, plan.items, lambda: next(calls))
        self.assertTrue(outcome.file_result.canceled)
        self.assertEqual(len(outcome.file_result.removed_paths), 1)
        self.assertTrue(os.path.isfile(second))
        self.assertIsNotNone(outcome.recovery_entry)

    def test_recovery_never_overwrites_recreated_file(self):
        path = self.write("labels/a.txt")
        plan = self.scan()
        outcome = self.transaction.cleanup_annotations(plan, plan.items)
        self.write("labels/a.txt", "new contents")
        with self.assertRaises(Exception):
            self.transaction.recover(outcome.recovery_entry.entry_id)
        self.assertEqual(Path(path).read_text(), "new contents")

    def test_symlink_files_and_directories_are_not_candidates(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "a.txt").write_text("")
        try:
            (self.labels / "link.txt").symlink_to(outside / "a.txt")
            (self.labels / "linked").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symbolic links unavailable")
        self.assertEqual(self.scan().items, ())


if __name__ == "__main__":
    unittest.main()
