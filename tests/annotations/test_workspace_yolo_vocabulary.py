"""Dataset-wide class IDs and atomic publication of their mapping."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PyQt5.QtGui import QImage

from labelimg.annotations.application.workspace import AnnotationWorkspace
from labelimg.annotations.domain.model import AnnotationBox, AnnotationDocumentError, AnnotationFormat
from labelimg.annotations.infrastructure.document import AnnotationDocument
from labelimg.annotations.infrastructure import storage


class WorkspaceYoloVocabularyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.images = self.root / "photos"
        self.labels = self.root / "annotations"
        self.labels.mkdir()
        self.image = QImage(100, 100, QImage.Format_RGB32)
        self.image.fill(0)
        for category in ("left", "right"):
            directory = self.images / category
            directory.mkdir(parents=True)
            self.assertTrue(self.image.save(str(directory / "a.png")))
        self.workspace = AnnotationWorkspace(save_dir=self.labels, image_dir=self.images)

    def tearDown(self):
        self.temporary.cleanup()

    def document(self, category, label):
        return AnnotationDocument(
            image_path=str(self.images / category / "a.png"),
            image_data=self.image,
            boxes=(AnnotationBox(label, ((10, 10), (40, 10), (40, 40), (10, 40))),),
        )

    def save(self, category, label):
        return self.workspace.save(self.document(category, label), AnnotationFormat.YOLO)

    def files(self):
        return {path: path.read_bytes() for path in self.labels.rglob("*") if path.is_file()}

    def test_new_categories_share_class_ids_across_subdirectories_and_reopen(self):
        self.save("left", "cat")
        self.save("right", "dog")
        self.assertEqual((self.labels / "classes.txt").read_text(encoding="utf8").splitlines(), ["cat", "dog"])
        second = AnnotationDocument.load(
            str(self.labels / "right/a.txt"), str(self.images / "right/a.png"), self.image
        )
        self.assertEqual(second.class_names, ("cat", "dog"))
        self.assertEqual(second.boxes[0].label, "dog")
        self.assertTrue((self.labels / "right/a.txt").read_text(encoding="utf8").splitlines()[-1].startswith("1 "))

        self.workspace = AnnotationWorkspace(save_dir=self.labels, image_dir=self.images)
        self.workspace.scan(self.labels)
        self.save("left", "fox")
        self.assertEqual((self.labels / "classes.txt").read_text(encoding="utf8").splitlines(), ["cat", "dog", "fox"])
        self.assertTrue((self.labels / "left/a.txt").read_text(encoding="utf8").splitlines()[-1].startswith("2 "))

    def test_inconsistent_existing_class_ids_block_writes(self):
        for category, names in (("left", "cat\ndog\n"), ("right", "dog\ncat\n")):
            directory = self.labels / category
            directory.mkdir()
            (directory / "classes.txt").write_text(names, encoding="utf8")
            (directory / "a.txt").write_text("0 0.25 0.25 0.3 0.3\n", encoding="utf8")
        self.workspace.scan(self.labels)
        before = self.files()
        with self.assertRaises(AnnotationDocumentError) as error:
            self.save("left", "fox")
        self.assertIn("classes.txt", str(error.exception))
        self.assertEqual(self.files(), before)

    def test_mapping_commit_failure_rolls_back_annotation_and_local_classes(self):
        self.save("left", "cat")
        before = self.files()
        shared = str(self.labels / "classes.txt")
        commit = storage._atomic_commit_staged
        replace = os.replace
        failed = False

        def fail_once(source, destination):
            nonlocal failed
            if destination == shared and not failed:
                failed = True
                raise OSError("injected shared-mapping failure")
            replace(source, destination)

        with patch.object(storage, "_atomic_commit_staged", side_effect=lambda pairs: commit(pairs, replace=fail_once)):
            with self.assertRaises(OSError):
                self.save("right", "dog")
        self.assertTrue(failed)
        self.assertEqual(self.files(), before)

    def test_external_shared_mapping_change_is_not_overwritten(self):
        self.save("left", "cat")
        (self.labels / "classes.txt").write_text("cat\ndog\n", encoding="utf8")
        before = self.files()
        with self.assertRaises(storage.AnnotationStorageConflict):
            self.save("right", "fox")
        self.assertEqual(self.files(), before)

    def test_external_mapping_change_during_staging_blocks_commit(self):
        self.save("left", "cat")
        original = (self.labels / "left/a.txt").read_bytes()
        write_document = storage.save_document

        def external_write(*args, **kwargs):
            result = write_document(*args, **kwargs)
            (self.labels / "classes.txt").write_text("cat\nexternal\n", encoding="utf8")
            return result

        with patch.object(storage, "save_document", side_effect=external_write):
            with self.assertRaises(storage.AnnotationStorageConflict):
                self.save("left", "dog")
        self.assertEqual((self.labels / "left/a.txt").read_bytes(), original)
        self.assertEqual((self.labels / "classes.txt").read_text(encoding="utf8"), "cat\nexternal\n")

    def test_external_mapping_change_during_shared_copy_blocks_commit(self):
        self.save("left", "cat")
        copy = storage.shutil.copyfile

        def external_write(source, destination, *args, **kwargs):
            result = copy(source, destination, *args, **kwargs)
            if os.path.basename(destination) == "shared-classes.txt":
                (self.labels / "classes.txt").write_text("cat\nexternal\n", encoding="utf8")
            return result

        with patch.object(storage.shutil, "copyfile", side_effect=external_write):
            with self.assertRaises(storage.AnnotationStorageConflict):
                self.save("right", "dog")
        self.assertFalse((self.labels / "right/a.txt").exists())
        self.assertEqual((self.labels / "classes.txt").read_text(encoding="utf8"), "cat\nexternal\n")

    def test_first_annotation_creation_does_not_overwrite_a_racing_external_file(self):
        for annotation_format in (AnnotationFormat.PASCAL_VOC, AnnotationFormat.CREATE_ML):
            with self.subTest(annotation_format=annotation_format):
                target = self.labels / "left" / ("a" + annotation_format.extension)
                write_document = storage.save_document

                def external_write(*args, **kwargs):
                    result = write_document(*args, **kwargs)
                    target.write_bytes(b"external content")
                    return result

                with patch.object(storage, "save_document", side_effect=external_write):
                    with self.assertRaises(storage.AnnotationStorageConflict):
                        self.workspace.save(self.document("left", "cat"), annotation_format)
                self.assertEqual(target.read_bytes(), b"external content")


if __name__ == "__main__":
    unittest.main()
