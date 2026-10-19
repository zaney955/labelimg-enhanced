"""YOLO split directories and stable dataset class IDs."""

from pathlib import Path
import tempfile
import unittest

from PyQt5.QtGui import QImage
from labelimg.annotations.application.workspace import (
    AnnotationWorkspace,
    AmbiguousAnnotationDocuments,
)
from labelimg.annotations.domain.model import (
    AnnotationBox,
    AnnotationDocumentError,
    AnnotationFormat,
)
from labelimg.annotations.infrastructure.document import AnnotationDocument


class YoloDatasetTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.images = self.root / "images"
        self.labels = self.root / "labels"
        self.image_path = self.images / "train/sample.png"
        self.annotation = self.labels / "train/sample.txt"
        self.image_path.parent.mkdir(parents=True)
        self.annotation.parent.mkdir(parents=True)
        self.image = QImage(100, 100, QImage.Format_RGB32)
        self.image.fill(0)
        self.assertTrue(self.image.save(str(self.image_path)))
        self.annotation.write_text("2 0.5 0.5 0.2 0.2\n", encoding="utf8")
        self.names = ("unused-zero", "unused-one", "used", "unused-three")
        (self.root / "data.yaml").write_text(
            "path: /old/linux/dataset\nnames:\n"
            "  2: used\n  0: unused-zero\n  3: unused-three\n  1: unused-one\n",
            encoding="utf8",
        )

    def workspace(self):
        return AnnotationWorkspace(save_dir=self.labels, image_dir=self.images)

    def load(self):
        return AnnotationDocument.load(self.annotation, self.image_path, self.image)

    def test_relative_paths_load_and_index_split_annotations(self):
        workspace = self.workspace()
        workspace.scan(self.labels)
        loaded = workspace.load_for_image(self.image_path, self.image)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.annotation_path, str(self.annotation))
        self.assertEqual(loaded.document.boxes[0].label, "used")
        self.assertTrue(workspace.entry(self.image_path).status.has_annotations)
        self.assertEqual(workspace.candidate_labels, ("used",))

    def test_mapping_search_does_not_escape_dataset_root(self):
        from labelimg.annotations.infrastructure.formats.yolo_classes import (
            resolve_yolo_classes,
        )

        child = self.root / "isolated/labels/train/sample.txt"
        child.parent.mkdir(parents=True)
        child.write_text("2 0.5 0.5 0.2 0.2\n", encoding="utf8")
        mapping = resolve_yolo_classes(child, allow_missing=True)
        self.assertIsNone(mapping.source)
        self.assertEqual(mapping.names, ())
        self.assertNotIn(str(self.root / "data.yaml"), mapping.resources)

    def test_nonstandard_mapping_is_marked_for_confirmation(self):
        from labelimg.annotations.infrastructure.formats.yolo_classes import (
            resolve_yolo_classes,
        )

        (self.root / "data.yaml").unlink()
        unusual = self.root / "classes.txt"
        unusual.write_text("zero\none\ntwo\n", encoding="utf8")
        mapping = resolve_yolo_classes(self.annotation)
        self.assertEqual(mapping.source, str(unusual))
        self.assertTrue(mapping.requires_confirmation)
        self.assertEqual(mapping.dataset_root, str(self.root))

    def test_unusual_mapping_approval_is_required_before_loading(self):
        from labelimg.annotations.domain.model import YoloClassMappingDeclined
        from unittest.mock import Mock

        (self.root / "data.yaml").unlink()
        unusual = self.root / "classes.txt"
        unusual.write_text("zero\none\ntwo\n", encoding="utf8")
        callback = Mock(return_value=False)
        workspace = AnnotationWorkspace(
            save_dir=self.labels, image_dir=self.images, confirm_yolo_mapping=callback
        )
        with self.assertRaises(YoloClassMappingDeclined):
            workspace.load_for_image(self.image_path, self.image)
        self.assertEqual(workspace.candidate_labels, ())
        callback.return_value = True
        self.assertEqual(
            workspace.load_for_image(self.image_path, self.image)
            .document.boxes[0]
            .label,
            "two",
        )
        self.assertEqual(callback.call_count, 2)
        workspace.load_for_image(self.image_path, self.image)
        self.assertEqual(callback.call_count, 2)

    def test_standard_yaml_wins_over_nonstandard_nested_yaml(self):
        from labelimg.annotations.infrastructure.formats.yolo_classes import (
            resolve_yolo_classes,
        )

        (self.labels / "data.yaml").write_text("names: [wrong]", encoding="utf8")
        mapping = resolve_yolo_classes(self.annotation)
        self.assertEqual(mapping.names, self.names)
        self.assertFalse(mapping.requires_confirmation)

    def test_new_target_keeps_relative_subdirectory(self):
        entry = self.workspace().entry(self.images / "val/new.png")
        self.assertEqual(
            entry.path_for(AnnotationFormat.YOLO), str(self.labels / "val/new.txt")
        )

    def test_flat_layout_is_still_readable(self):
        flat = self.labels / "sample.txt"
        self.annotation.rename(flat)
        self.assertEqual(
            self.workspace()
            .load_for_image(self.image_path, self.image)
            .annotation_path,
            str(flat),
        )

    def test_relative_and_flat_candidates_require_explicit_choice(self):
        flat = self.labels / "sample.txt"
        flat.write_text("# labelimg-review: unreviewed\n", encoding="utf8")
        workspace = self.workspace()
        with self.assertRaises(AmbiguousAnnotationDocuments) as caught:
            workspace.load_for_image(self.image_path, self.image)
        self.assertEqual(
            {c.annotation_path for c in caught.exception.choices},
            {str(flat), str(self.annotation)},
        )
        workspace.select_active_document(self.image_path, self.annotation)
        self.assertEqual(
            workspace.load_for_image(self.image_path, self.image)
            .document.boxes[0]
            .label,
            "used",
        )

    def test_yaml_fallback_keeps_unused_class_ids_when_saved(self):
        (self.labels / "classes.txt").write_text("", encoding="utf8")
        self.assertEqual(self.load().class_names, self.names)
        workspace = self.workspace()
        loaded = workspace.load_for_image(self.image_path, self.image)
        workspace.save(loaded.document, AnnotationFormat.YOLO)
        self.assertEqual(
            (self.annotation.parent / "classes.txt")
            .read_text(encoding="utf8")
            .splitlines(),
            list(self.names),
        )
        self.assertTrue(self.annotation.read_text().splitlines()[1].startswith("2 "))

    def test_class_file_precedence(self):
        (self.labels / "classes.txt").write_text(
            "p0\np1\nparent\np3\n", encoding="utf8"
        )
        self.assertEqual(self.load().boxes[0].label, "parent")
        (self.annotation.parent / "classes.txt").write_text(
            "l0\nl1\nlocal\nl3\n", encoding="utf8"
        )
        self.assertEqual(self.load().boxes[0].label, "local")

    def test_yaml_list_and_empty_local_classes(self):
        (self.annotation.parent / "classes.txt").write_text("\n", encoding="utf8")
        (self.root / "data.yaml").write_text(
            "names: [zero, one, two, three]\n", encoding="utf8"
        )
        self.assertEqual(self.load().class_names, ("zero", "one", "two", "three"))

    def test_sparse_and_duplicate_yaml_names_rejected(self):
        for content in (
            "names: {0: zero, 2: two}",
            "names: [same, same, two]",
            "names: {0: old, 0: new, 1: one, 2: two}",
        ):
            with self.subTest(content=content):
                (self.root / "data.yaml").write_text(content, encoding="utf8")
                with self.assertRaises(AnnotationDocumentError):
                    self.load()

    def test_save_without_loading_keeps_dataset_class_ids(self):
        document = AnnotationDocument(
            image_path=str(self.image_path),
            image_data=self.image,
            class_names=("used",),
            boxes=(AnnotationBox("used", ((40, 40), (60, 40), (60, 60), (40, 60))),),
        )
        self.workspace().save(document, AnnotationFormat.YOLO)
        self.assertTrue(self.annotation.read_text().splitlines()[1].startswith("2 "))

    def test_split_image_root_can_be_paired_with_labels_root(self):
        workspace = AnnotationWorkspace(
            save_dir=self.labels, image_dir=self.images / "train"
        )
        self.assertEqual(
            workspace.load_for_image(self.image_path, self.image).annotation_path,
            str(self.annotation),
        )

    def test_arbitrary_image_root_preserves_relative_paths(self):
        moved = self.root / "photos"
        self.images.rename(moved)
        image_path = moved / "train/sample.png"
        workspace = AnnotationWorkspace(save_dir=self.labels, image_dir=moved)
        self.assertEqual(
            workspace.load_for_image(image_path, self.image).annotation_path,
            str(self.annotation),
        )
        outside = self.root / "outside.png"
        self.assertEqual(
            workspace.entry(outside).path_for(AnnotationFormat.YOLO),
            str(self.labels / "outside.txt"),
        )

    def test_direct_document_save_and_new_labels_keep_class_ids(self):
        document = self.load()
        document.boxes += (
            AnnotationBox("new", ((10, 10), (20, 10), (20, 20), (10, 20))),
        )
        document.save(str(self.annotation), AnnotationFormat.YOLO)
        lines = self.annotation.read_text().splitlines()
        self.assertTrue(lines[1].startswith("2 "))
        self.assertTrue(lines[2].startswith("4 "))
        self.assertEqual(
            (self.annotation.parent / "classes.txt").read_text().splitlines(),
            list(self.names) + ["new"],
        )

    def test_external_yaml_change_blocks_save(self):
        from labelimg.annotations.infrastructure.storage import (
            AnnotationStorageConflict,
        )

        workspace = self.workspace()
        loaded = workspace.load_for_image(self.image_path, self.image)
        (self.root / "data.yaml").write_text(
            "names: [other, one, two, three]\n", encoding="utf8"
        )
        with self.assertRaises(AnnotationStorageConflict):
            workspace.save(loaded.document, AnnotationFormat.YOLO)
        self.assertFalse((self.annotation.parent / "classes.txt").exists())

    def test_file_operations_find_nested_labels_and_shared_mapping(self):
        from labelimg.files.application.operations import (
            AnnotationFileService,
            SynchronizedRenamer,
        )

        service = AnnotationFileService(save_dir=self.labels, image_dir=self.images)
        self.assertEqual(service.annotation_count([self.image_path]), 1)
        resources = service.associated_annotation_resources([self.image_path]).resources
        self.assertIn(str(self.annotation), resources)
        self.assertIn(str(self.root / "data.yaml"), resources)
        target = self.image_path.with_name("renamed.png")
        SynchronizedRenamer(save_dir=self.labels, image_dir=self.images).rename(
            {str(self.image_path): str(target)}
        )
        self.assertFalse(self.annotation.exists())
        self.assertTrue(self.annotation.with_name("renamed.txt").is_file())

    def test_workspace_save_rejects_local_mapping_when_parent_differs(self):
        parent = ("parent-zero", "parent-one", "parent-two", "parent-three")
        local = ("local-zero", "local-one", "local-two", "local-three")
        (self.labels / "classes.txt").write_text("\n".join(parent), encoding="utf8")
        local_path = self.annotation.parent / "classes.txt"
        local_path.write_text("\n".join(local), encoding="utf8")
        workspace = self.workspace()
        loaded = workspace.load_for_image(self.image_path, self.image)
        original = self.annotation.read_bytes()
        with self.assertRaises(AnnotationDocumentError):
            workspace.save(loaded.document, AnnotationFormat.YOLO)
        self.assertEqual(local_path.read_text().splitlines(), list(local))
        self.assertEqual((self.labels / "classes.txt").read_text().splitlines(), list(parent))
        self.assertEqual(self.annotation.read_bytes(), original)

    def test_missing_mapping_error_lists_configuration_paths(self):
        (self.root / "data.yaml").unlink()
        (self.labels / "classes.txt").write_text("", encoding="utf8")
        with self.assertRaises(AnnotationDocumentError) as caught:
            self.load()
        message = str(caught.exception)
        self.assertIn("Missing YOLO class mapping", message)
        self.assertIn(str(self.annotation.parent / "classes.txt"), message)
        self.assertIn(str(self.labels / "classes.txt"), message)
        self.assertIn(str(self.root / "data.yaml"), message)

    def test_out_of_range_error_names_mapping_and_record_line(self):
        mapping = self.annotation.parent / "classes.txt"
        mapping.write_text("zero\none\n", encoding="utf8")
        self.annotation.write_text(
            "# review comment\n\n3 0.5 0.5 0.2 0.2\n", encoding="utf8"
        )
        with self.assertRaises(AnnotationDocumentError) as caught:
            self.load()
        message = str(caught.exception)
        self.assertIn("class ID 3", message)
        self.assertIn("line 3", message)
        self.assertIn("0-1", message)
        self.assertIn(str(mapping), message)
        self.assertIn("2 classes", message)

    def test_empty_annotation_without_mapping_still_loads(self):
        (self.root / "data.yaml").unlink()
        self.annotation.write_text("# labelimg-review: unreviewed\n", encoding="utf8")
        self.assertEqual(self.load().boxes, ())

    def test_explicit_missing_class_file_uses_missing_mapping_error(self):
        from labelimg.annotations.domain.model import YoloClassMappingError
        from labelimg.annotations.infrastructure.formats.yolo import YoloReader

        mapping = self.root / "missing-classes.txt"
        with self.assertRaises(YoloClassMappingError) as caught:
            YoloReader(str(self.annotation), self.image, str(mapping))
        self.assertEqual(caught.exception.reason, "missing")
        self.assertIn(str(mapping), caught.exception.checked_paths)


if __name__ == "__main__":
    unittest.main()
