"""Category counts must reflect actual boxes, documents and image scope."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from labelimg.annotations import AnnotationWorkspace
from labelimg.annotations.application.statistics import AnnotationStatisticsCollector, StatisticsCanceled, StatisticsError
from labelimg.annotations.domain.history import AnnotationBoxState, AnnotationSnapshot


def voc(*labels):
    objects = ''.join('<object><name>%s</name><bndbox><xmin>1</xmin><ymin>1</ymin><xmax>8</xmax><ymax>8</ymax></bndbox></object>' % label for label in labels)
    return '<annotation><filename>a.png</filename>%s</annotation>' % objects


def record(image, *labels):
    return {"image": image, "annotations": [{"label": label, "coordinates": {"x": 5, "y": 5, "width": 2, "height": 2}} for label in labels]}


class AnnotationStatisticsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.images = self.root / "images"
        self.labels = self.root / "labels"
        self.images.mkdir()
        self.labels.mkdir()
        self.workspace = AnnotationWorkspace(image_dir=self.images, save_dir=self.labels)
        self.views = {}
        self.editing = SimpleNamespace(has_image=lambda path: path in self.views, view_image=lambda path, touch=False: self.views[path])
        self.collector = AnnotationStatisticsCollector(self.workspace, self.editing)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, text=""):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def collect(self, *names, progress=None):
        return self.collector.collect([str(self.images / name) for name in names], progress)

    def rows(self, result):
        return {row.label: (row.boxes, row.images) for row in result.categories}

    def test_voc_counts_instances_and_distinct_images_separately(self):
        self.write("labels/a.xml", voc("裂纹", "裂纹", "缺损"))
        self.write("labels/b.xml", voc("裂纹"))
        result = self.collect("a.png", "b.png")
        self.assertEqual(self.rows(result), {"裂纹": (3, 2), "缺损": (1, 1)})
        self.assertEqual(result.total_boxes, 4)
        self.assertEqual(result.annotated_images, 2)

    def test_yolo_class_ids_come_from_mapping_and_unused_names_are_excluded(self):
        self.write("labels/classes.txt", "cat\ndog\nunused\n")
        self.write("labels/a.txt", "# labelimg-review: verified\n1 .5 .5 .2 .2\n1 .5 .5 .1 .1\n0 .2 .2 .1 .1\n")
        result = self.collect("a.jpg")
        self.assertEqual(self.rows(result), {"dog": (2, 1), "cat": (1, 1)})
        self.assertEqual(result.issues, ())

    def test_yolo_yaml_mapping_and_split_subdirectories(self):
        self.write("data.yaml", "names: [cat, dog, unused]\n")
        self.write("images/train/a.png")
        self.write("labels/train/a.txt", "1 .5 .5 .2 .2\n")
        self.workspace.set_image_dir(self.images / "train")
        result = self.collector.collect([str(self.images / "train/a.png")])
        self.assertEqual(self.rows(result), {"dog": (1, 1)})

    def test_shared_createml_counts_only_records_of_workspace_images(self):
        self.write("labels/shared.json", json.dumps([record("a.png", "cat", "cat"), record("b.png", "dog"), record("outside.png", "ignored")]))
        result = self.collect("a.png", "b.png")
        self.assertEqual(self.rows(result), {"cat": (2, 1), "dog": (1, 1)})
        self.assertEqual(result.total_images, 2)

    def test_qualified_createml_references_distinguish_equal_basenames(self):
        self.write("labels/shared.json", json.dumps([record("one/a.png", "cat"), record("two/a.png", "dog", "dog")]))
        result = self.collect("one/a.png", "two/a.png")
        self.assertEqual(self.rows(result), {"cat": (1, 1), "dog": (2, 1)})

    def test_empty_missing_and_invalid_annotations_are_separate(self):
        self.write("labels/empty.xml", voc())
        self.write("labels/blank.txt")
        self.write("labels/broken.xml", "<annotation>")
        result = self.collect("empty.png", "blank.png", "missing.png", "broken.png")
        self.assertEqual((result.empty_images, result.missing_images, len(result.issues)), (2, 1, 1))
        self.assertEqual(result.total_boxes, 0)

    def test_multiformat_without_active_choice_is_skipped(self):
        self.write("labels/a.xml", voc("cat"))
        self.write("labels/a.txt", "0 .5 .5 .2 .2\n")
        result = self.collect("a.png")
        self.assertEqual(result.total_boxes, 0)
        self.assertEqual(result.issues[0].error.reason, "ambiguous")
        self.assertIn("a.xml", result.issues[0].annotation_path)

    def test_active_document_is_not_double_counted_or_blocked_by_invalid_inactive_format(self):
        active = self.write("labels/a.xml", voc("cat", "cat"))
        self.write("labels/a.txt", "malformed")
        self.workspace.scan(self.labels)
        self.workspace.select_active_document(str(self.images / "a.png"), active)
        result = self.collect("a.png")
        self.assertEqual(self.rows(result), {"cat": (2, 1)})
        self.assertEqual(result.issues, ())

    def dirty_view(self, image, *labels):
        self.views[str(self.images / image)] = SimpleNamespace(
            dirty=True, current_target=None,
            snapshot=AnnotationSnapshot(str(self.images / image), (100, 80), tuple(AnnotationBoxState(index + 1, label, ((1, 1), (8, 1), (8, 8), (1, 8))) for index, label in enumerate(labels))),
        )

    def test_unsaved_edits_replace_disk_counts_without_saving_or_losing_history(self):
        path = self.write("labels/a.xml", voc("old"))
        before = Path(path).read_bytes()
        self.dirty_view("a.png", "new", "new")
        view = self.views[str(self.images / "a.png")]
        result = self.collect("a.png")
        self.assertEqual(self.rows(result), {"new": (2, 1)})
        self.assertEqual(result.unsaved_images, 1)
        self.assertIs(self.views[str(self.images / "a.png")], view)
        self.assertEqual(Path(path).read_bytes(), before)

    def test_unsaved_deletion_is_empty_and_not_missing(self):
        self.write("labels/a.xml", voc("cat"))
        self.dirty_view("a.png")
        result = self.collect("a.png")
        self.assertEqual((result.empty_images, result.missing_images, result.unsaved_images), (1, 0, 1))

    def test_new_unsaved_document_contributes_boxes(self):
        self.dirty_view("new.png", "cat")
        result = self.collect("new.png")
        self.assertEqual(result.total_boxes, 1)
        self.assertFalse((self.labels / "new.xml").exists())

    def test_clean_retained_document_reads_current_disk(self):
        path = self.write("labels/a.xml", voc("current"))
        self.views[str(self.images / "a.png")] = SimpleNamespace(dirty=False, current_target=path)
        self.assertEqual(self.rows(self.collect("a.png")), {"current": (1, 1)})

    def test_only_images_in_scope_count_and_duplicate_paths_are_deduplicated(self):
        self.write("labels/a.xml", voc("cat"))
        self.write("labels/outside.xml", voc("ignored"))
        result = self.collect("a.png", "a.png")
        self.assertEqual(self.rows(result), {"cat": (1, 1)})
        self.assertEqual(result.total_images, 1)

    def test_refresh_discovers_new_shared_collection(self):
        self.assertEqual(self.collect("a.png").missing_images, 1)
        self.write("labels/new.json", json.dumps([record("a.png", "new")]))
        self.assertEqual(self.rows(self.collect("a.png")), {"new": (1, 1)})

    def test_bad_yolo_mapping_is_not_reported_as_empty(self):
        self.write("labels/a.txt", "8 .5 .5 .2 .2")
        result = self.collect("a.png")
        self.assertEqual(len(result.issues), 1)
        self.assertEqual(result.empty_images, 0)
        self.write("labels/classes.txt", "cat\n")
        self.assertEqual(len(self.collect("a.png").issues), 1)

    def test_cancel_during_indexing_does_not_return_partial_statistics(self):
        self.write("labels/a.xml", voc("cat"))
        def cancel(_value, _total):
            raise StatisticsCanceled()
        with self.assertRaises(StatisticsCanceled):
            self.collect("a.png", progress=cancel)

    def test_external_change_during_counting_requires_refresh(self):
        self.write("labels/a.xml", voc("cat"))
        def progress(value, total):
            if total and value == total:
                self.write("labels/a.xml", voc("dog"))
        with self.assertRaisesRegex(StatisticsError, "changed"):
            self.collect("a.png", progress=progress)

    def test_unavailable_root_is_not_reported_as_zero_annotations(self):
        self.workspace.set_save_dir(self.root / "missing")
        with self.assertRaisesRegex(StatisticsError, "directory"):
            self.collect("a.png")


if __name__ == "__main__":
    unittest.main()
