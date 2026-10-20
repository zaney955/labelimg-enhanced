"""Cross-format replacement, rollback, retained edits, and recovery conflicts."""

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PyQt5.QtGui import QImage

from labelimg.annotations.application.editing import AnnotationEditingController
from labelimg.annotations.application.label_replace import LabelReplacementTransaction
from labelimg.annotations.application.persistence import AnnotationSaveCoordinator
from labelimg.annotations.application.workspace import AnnotationWorkspace
from labelimg.annotations.domain.history import AnnotationBoxState, AnnotationSnapshot
from labelimg.annotations.domain.model import AnnotationBox, AnnotationFormat
from labelimg.annotations.infrastructure.document import AnnotationDocument
from labelimg.annotations.infrastructure.storage import AnnotationStorageConflict, fingerprint_image, fingerprint_path
from labelimg.platform.recovery import RecoveryConflict


class LabelReplacementTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = AnnotationWorkspace(image_dir=self.root)
        self.editing = AnnotationEditingController(
            lambda key: self.editing.view_image(key, touch=False).snapshot,
            lambda request: None,
        )
        self.persistence = AnnotationSaveCoordinator(self.workspace, self.editing)
        self.transaction = LabelReplacementTransaction(
            self.workspace, self.editing, self.persistence, image_data_for=lambda path: Path(path).read_bytes(),
        )

    def tearDown(self):
        self.temp.cleanup()

    def image(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(40, 30, QImage.Format_RGB32)
        image.fill(0xFFFFFF)
        self.assertTrue(image.save(str(path)))
        return str(path)

    def document(self, path, labels=('apple',), annotation_format=AnnotationFormat.PASCAL_VOC, target=None):
        document = AnnotationDocument(
            image_path=path, image_data=Path(path).read_bytes(),
            boxes=tuple(AnnotationBox(label, ((2, 3), (12, 3), (12, 15), (2, 15)), True) for label in labels),
            class_names=tuple(dict.fromkeys(labels)), verified=False, questioned=True,
        )
        return self.workspace.save(document, annotation_format, annotation_path=target)

    def retain(self, path, saved, dirty_label=None):
        document = saved.document
        snapshot = AnnotationSnapshot(
            image_key=path, image_size=(40, 30),
            boxes=tuple(AnnotationBoxState(index + 1, box.label, box.points, box.difficult)
                        for index, box in enumerate(document.boxes)),
            verified=document.verified, questioned=document.questioned,
            image_fingerprint=fingerprint_image(path, (40, 30)),
        )
        self.editing.open_image(path, snapshot, (saved.annotation_path, saved.fingerprints))
        if dirty_label:
            token = self.editing.history.begin_edit(path, snapshot, 'Change label')
            snapshot = replace(snapshot, boxes=(replace(snapshot.boxes[0], label=dirty_label), *snapshot.boxes[1:]))
            self.editing.history.commit_edit(token, snapshot, (1,))
            self.persistence.track(self.editing.view_image(path, touch=False))
        return snapshot

    def preview(self, paths, old='apple', new='apple_s'):
        return self.transaction.preview(paths, old, new, AnnotationFormat.PASCAL_VOC)

    def labels(self, path):
        return tuple(box.label for box in self.workspace.load_for_image(path, Path(path).read_bytes()).document.boxes)

    def test_exact_match_merge_and_byte_exact_recovery(self):
        first, second = self.image('first.png'), self.image('second.png')
        saved = self.document(first, ('apple', 'apple_big', 'Apple', 'apple_s', 'apple'))
        other = self.document(second, ('pear',))
        original = Path(saved.annotation_path).read_bytes()
        untouched = fingerprint_path(other.annotation_path)
        plan = self.preview((first, second))
        self.assertEqual(len(plan.items), 1)
        self.assertEqual(plan.box_count, 2)
        self.assertIsNone(plan.items[0].before.image_data)
        self.assertTrue(plan.merges)
        result = self.transaction.apply(plan)
        self.assertEqual(self.labels(first), ('apple_s', 'apple_big', 'Apple', 'apple_s', 'apple_s'))
        document = self.workspace.load_for_image(first, Path(first).read_bytes()).document
        self.assertTrue(document.questioned)
        self.assertEqual(document.boxes[0].points, saved.document.boxes[0].points)
        self.assertEqual(fingerprint_path(other.annotation_path), untouched)
        self.transaction.recover(result.recovery)
        self.assertEqual(Path(saved.annotation_path).read_bytes(), original)

    def test_retained_dirty_document_is_authoritative_and_recovery_preserves_unsaved_content(self):
        path = self.image('dirty.png')
        saved = self.document(path, ('pear',))
        prior = self.retain(path, saved, dirty_label='apple')
        original = Path(saved.annotation_path).read_bytes()
        result = self.transaction.apply(self.preview((path,)))
        self.assertEqual(self.labels(path), ('apple_s',))
        self.assertFalse(self.editing.view_image(path).dirty)
        self.assertFalse(self.editing.view_image(path).can_undo)
        self.transaction.recover(result.recovery)
        self.assertEqual(Path(saved.annotation_path).read_bytes(), original)
        self.assertEqual(self.editing.view_image(path).snapshot, prior)
        self.assertTrue(self.editing.view_image(path).dirty)
        self.persistence.verify_baseline(self.editing.view_image(path))

    def test_new_unsaved_document_recovers_absent_file_and_dirty_snapshot(self):
        path = self.image('new.png')
        snapshot = AnnotationSnapshot(path, (40, 30), (
            AnnotationBoxState(1, 'apple', ((2, 3), (12, 3), (12, 15), (2, 15))),
        ), image_fingerprint=fingerprint_image(path, (40, 30)))
        self.editing.open_image(path, snapshot)
        result = self.transaction.apply(self.preview((path,)))
        target = Path(path).with_suffix('.xml')
        self.assertTrue(target.exists())
        self.transaction.recover(result.recovery)
        self.assertFalse(target.exists())
        self.assertEqual(self.editing.view_image(path).snapshot, snapshot)
        self.assertTrue(self.editing.view_image(path).dirty)

    def test_later_file_change_invalidates_preview_before_any_write(self):
        paths = (self.image('first.png'), self.image('second.png'))
        saved = tuple(self.document(path) for path in paths)
        plan = self.preview(paths)
        first_bytes = Path(saved[0].annotation_path).read_bytes()
        with open(saved[1].annotation_path, 'ab') as stream:
            stream.write(b'\n')
        with self.assertRaises(AnnotationStorageConflict):
            self.transaction.apply(plan)
        self.assertEqual(Path(saved[0].annotation_path).read_bytes(), first_bytes)

    def test_later_memory_edit_invalidates_preview(self):
        path = self.image('retained.png')
        saved = self.document(path)
        snapshot = self.retain(path, saved)
        plan = self.preview((path,))
        token = self.editing.history.begin_edit(path, snapshot, 'Change label')
        self.editing.history.commit_edit(token, replace(snapshot, boxes=(replace(snapshot.boxes[0], label='pear'),)), (1,))
        with self.assertRaises(RecoveryConflict):
            self.transaction.apply(plan)
        self.assertEqual(self.labels(path), ('apple',))

    def test_second_write_failure_rolls_back_disk_and_keeps_dirty_history(self):
        paths = (self.image('first.png'), self.image('second.png'))
        saved = tuple(self.document(path) for path in paths)
        prior = self.retain(paths[0], saved[0], dirty_label='apple')
        original = tuple(Path(item.annotation_path).read_bytes() for item in saved)
        plan = self.preview(paths)
        save = self.workspace.save
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise OSError('injected write failure')
            return save(*args, **kwargs)

        with patch.object(self.workspace, 'save', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'injected'):
                self.transaction.apply(plan)
        self.assertEqual(tuple(Path(item.annotation_path).read_bytes() for item in saved), original)
        self.assertEqual(self.editing.view_image(paths[0]).snapshot, prior)
        self.persistence.verify_baseline(self.editing.view_image(paths[0]))

    def test_yolo_new_label_preserves_other_ids_and_subset_annotations(self):
        first, second = self.image('first.png'), self.image('second.png')
        saved = self.document(first, ('apple', 'pear'), AnnotationFormat.YOLO)
        untouched = self.document(second, ('apple',), AnnotationFormat.YOLO)
        other_bytes = Path(untouched.annotation_path).read_bytes()
        classes = self.root / 'classes.txt'
        before_classes = classes.read_bytes()
        result = self.transaction.apply(self.preview((first,)))
        self.assertEqual(classes.read_text().splitlines(), ['apple', 'pear', 'apple_s'])
        data_lines = [line for line in Path(saved.annotation_path).read_text().splitlines() if not line.startswith('#')]
        self.assertEqual(data_lines[0].split()[0], '2')
        self.assertEqual(self.labels(first), ('apple_s', 'pear'))
        self.assertEqual(self.labels(second), ('apple',))
        self.assertEqual(Path(untouched.annotation_path).read_bytes(), other_bytes)
        self.transaction.recover(result.recovery)
        self.assertEqual(classes.read_bytes(), before_classes)
        self.assertEqual(self.labels(first), ('apple', 'pear'))

    def test_yolo_existing_destination_reuses_id_without_duplicate_names(self):
        path = self.image('image.png')
        saved = self.document(path, ('apple', 'apple_s', 'pear'), AnnotationFormat.YOLO)
        classes = self.root / 'classes.txt'
        original = classes.read_bytes()
        result = self.transaction.apply(self.preview((path,)))
        self.assertEqual(self.labels(path), ('apple_s', 'apple_s', 'pear'))
        self.assertEqual(classes.read_bytes(), original)
        self.assertNotIn(str(classes), dict(result.recovery.original_contents))
        self.transaction.recover(result.recovery)
        self.assertEqual(self.labels(path), ('apple', 'apple_s', 'pear'))

    def test_shared_createml_collection_updates_only_target_records(self):
        first, second = self.image('train/same.png'), self.image('val/same.png')
        outside = self.image('outside.png')
        target = str(self.root / 'collection.json')
        first_saved = self.document(first, target=target, annotation_format=AnnotationFormat.CREATE_ML)
        # Give records their complete references to distinguish equal names.
        payload = json.loads(Path(target).read_text())
        payload[0]['image'] = 'train/same.png'
        payload.append({**payload[0], 'image': 'val/same.png', 'custom': 'preserve'})
        payload.append({**payload[0], 'image': 'outside.png'})
        Path(target).write_text(json.dumps(payload), encoding='utf8')
        self.workspace.scan(self.root)
        self.workspace.select_active_document(first, target)
        self.workspace.select_active_document(second, target)
        original = Path(target).read_bytes()
        plan = self.preview((first, second))
        self.assertEqual(plan.box_count, 2)
        result = self.transaction.apply(plan)
        rows = json.loads(Path(target).read_text())
        self.assertEqual([row['annotations'][0]['label'] for row in rows], ['apple_s', 'apple_s', 'apple'])
        self.assertEqual(rows[1]['custom'], 'preserve')
        self.transaction.recover(result.recovery)
        self.assertEqual(Path(target).read_bytes(), original)

    def test_recovery_refuses_later_disk_or_unsaved_edits(self):
        path = self.image('image.png')
        saved = self.document(path)
        self.retain(path, saved)
        result = self.transaction.apply(self.preview((path,)))
        snapshot = self.editing.view_image(path).snapshot
        token = self.editing.history.begin_edit(path, snapshot, 'Change label')
        self.editing.history.commit_edit(token, replace(snapshot, boxes=(replace(snapshot.boxes[0], label='pear'),)), (1,))
        with self.assertRaises(RecoveryConflict):
            self.transaction.recover(result.recovery)
        self.assertEqual(self.labels(path), ('apple_s',))
        with open(saved.annotation_path, 'ab') as stream:
            stream.write(b'\n')
        with self.assertRaises(AnnotationStorageConflict):
            self.transaction.recover(result.recovery)

    def test_no_match_does_not_create_files_or_recovery(self):
        path = self.image('empty.png')
        plan = self.preview((path,))
        result = self.transaction.apply(plan)
        self.assertFalse(result.updates)
        self.assertIsNone(result.recovery)
        self.assertFalse(Path(path).with_suffix('.xml').exists())

    def test_image_change_after_preview_blocks_stale_geometry_save(self):
        path = self.image('image.png')
        saved = self.document(path)
        plan = self.preview((path,))
        original = Path(saved.annotation_path).read_bytes()
        image = QImage(60, 50, QImage.Format_RGB32)
        image.fill(0)
        self.assertTrue(image.save(path))
        with self.assertRaises(AnnotationStorageConflict):
            self.transaction.apply(plan)
        self.assertEqual(Path(saved.annotation_path).read_bytes(), original)

    def test_yolo_failure_restores_class_mapping_as_well_as_annotation_files(self):
        paths = (self.image('first.png'), self.image('second.png'))
        saved = tuple(self.document(path, annotation_format=AnnotationFormat.YOLO) for path in paths)
        resources = [*(Path(item.annotation_path) for item in saved), self.root / 'classes.txt']
        before = [path.read_bytes() for path in resources]
        save = self.workspace.save

        def fail_second(document, *args, **kwargs):
            if document.image_path == paths[1]:
                raise OSError('injected failure')
            return save(document, *args, **kwargs)

        plan = self.preview(paths)
        with patch.object(self.workspace, 'save', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.transaction.apply(plan)
        self.assertEqual([path.read_bytes() for path in resources], before)
        self.assertEqual(self.labels(paths[0]), ('apple',))

    def test_split_yolo_files_update_local_and_shared_classes_consistently(self):
        images = self.root / 'images'
        labels = self.root / 'labels'
        labels.mkdir()
        self.workspace.set_image_dir(images)
        self.workspace.set_save_dir(labels)
        first, second = self.image('images/train/first.png'), self.image('images/val/second.png')
        self.document(first, ('apple', 'pear'), AnnotationFormat.YOLO)
        self.document(second, ('apple',), AnnotationFormat.YOLO)
        mappings = (labels / 'classes.txt', labels / 'train/classes.txt', labels / 'val/classes.txt')
        before = tuple(path.read_bytes() for path in mappings)
        result = self.transaction.apply(self.preview((first, second)))
        self.assertEqual(self.labels(first), ('apple_s', 'pear'))
        self.assertEqual(self.labels(second), ('apple_s',))
        for path in mappings:
            self.assertEqual(path.read_text().splitlines(), ['apple', 'pear', 'apple_s'])
        self.transaction.recover(result.recovery)
        self.assertEqual(tuple(path.read_bytes() for path in mappings), before)

    def test_recovery_blocks_unsaved_sibling_sharing_an_appended_class_mapping(self):
        first, second = self.image('first.png'), self.image('second.png')
        self.document(first, annotation_format=AnnotationFormat.YOLO)
        sibling = self.document(second, ('pear',), AnnotationFormat.YOLO)
        self.retain(second, sibling)
        result = self.transaction.apply(self.preview((first,)))
        snapshot = self.editing.view_image(second).snapshot
        token = self.editing.history.begin_edit(second, snapshot, 'Change label')
        self.editing.history.commit_edit(token, replace(snapshot, boxes=(replace(snapshot.boxes[0], label='apple_s'),)), (1,))
        with self.assertRaises(RecoveryConflict):
            self.transaction.recover(result.recovery)
        self.assertEqual(self.labels(first), ('apple_s',))

    def test_recovery_updates_history_opened_after_the_batch(self):
        path = self.image('image.png')
        self.document(path)
        result = self.transaction.apply(self.preview((path,)))
        loaded = self.workspace.load_for_image(path, Path(path).read_bytes())
        from labelimg.annotations.application.workspace import WorkspaceSave
        saved = WorkspaceSave(loaded.annotation_path, loaded.document, fingerprints=((loaded.annotation_path, fingerprint_path(loaded.annotation_path)),))
        self.retain(path, saved)
        self.transaction.recover(result.recovery)
        self.assertEqual(self.editing.view_image(path).snapshot.boxes[0].label, 'apple')
        self.assertFalse(self.editing.view_image(path).dirty)

    def test_recovery_write_failure_restores_complete_post_operation_state(self):
        paths = (self.image('first.png'), self.image('second.png'))
        saved = tuple(self.document(path) for path in paths)
        result = self.transaction.apply(self.preview(paths))
        after = tuple(Path(item.annotation_path).read_bytes() for item in saved)
        replace_file = os.replace
        calls = []

        def fail_second(source, target):
            calls.append(target)
            if len(calls) == 2:
                raise OSError('injected recovery failure')
            return replace_file(source, target)

        from labelimg.platform.recovery import RecoveryError
        with patch('labelimg.annotations.application.label_replace.os.replace', side_effect=fail_second):
            with self.assertRaises(RecoveryError):
                self.transaction.recover(result.recovery)
        self.assertEqual(tuple(Path(item.annotation_path).read_bytes() for item in saved), after)
        # A successful rollback must leave the recovery entry retryable.
        self.transaction.recover(result.recovery)
        self.assertEqual(tuple(self.labels(path) for path in paths), (('apple',), ('apple',)))

    def test_label_validation_rejects_noop_empty_and_multiline_names(self):
        for old, new in (('apple', 'apple'), ('', 'pear'), ('apple', ''), ('apple', 'a\nb')):
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                self.preview((), old, new)

    def test_recovery_refuses_a_new_save_target_even_if_its_history_is_clean(self):
        path = self.image('image.png')
        saved = self.document(path)
        self.retain(path, saved)
        result = self.transaction.apply(self.preview((path,)))
        view = self.editing.view_image(path)
        self.editing.rebase_image(path, view.snapshot, (str(self.root / 'elsewhere.xml'), ()))
        with self.assertRaises(RecoveryConflict):
            self.transaction.recover(result.recovery)
        self.assertEqual(self.labels(path), ('apple_s',))


if __name__ == '__main__':
    unittest.main()
