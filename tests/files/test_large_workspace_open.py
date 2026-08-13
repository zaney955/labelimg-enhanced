import os
import json
import tempfile
import unittest
from unittest.mock import patch

from labelimg.annotations import AnnotationWorkspace
from labelimg.annotations import CreateMLRecordIdentity
from labelimg.files import discover_images


class LargeWorkspaceOpenTest(unittest.TestCase):
    def test_discovery_returns_one_stable_natural_order(self):
        with tempfile.TemporaryDirectory() as directory:
            nested = os.path.join(directory, "nested")
            os.makedirs(nested)
            for relative in (
                "image10.png",
                "image2.png",
                "image01.png",
                os.path.join("nested", "image3.png"),
                "ignore.xml",
            ):
                path = os.path.join(directory, relative)
                with open(path, "wb"):
                    pass

            result = discover_images(directory, (".png",))

        self.assertEqual(
            [os.path.relpath(path, directory) for path in result],
            [
                "image01.png",
                "image2.png",
                "image10.png",
                os.path.join("nested", "image3.png"),
            ],
        )

    def test_scan_reuses_status_and_reads_shared_yolo_vocabulary_once(self):
        with tempfile.TemporaryDirectory() as directory:
            classes = os.path.join(directory, "classes.txt")
            with open(classes, "w", encoding="utf-8") as stream:
                stream.write("cat\ndog\n")
            images = []
            for index in range(20):
                image = os.path.join(directory, "image%02d.png" % index)
                annotation = os.path.join(directory, "image%02d.txt" % index)
                with open(image, "wb"):
                    pass
                with open(annotation, "w", encoding="utf-8") as stream:
                    stream.write("1 0.5 0.5 0.25 0.25\n")
                images.append(image)

            real_open = open
            reads = {}

            def counting_open(path, mode="r", *args, **kwargs):
                if "r" in mode:
                    key = os.path.normcase(os.path.abspath(os.fspath(path)))
                    reads[key] = reads.get(key, 0) + 1
                return real_open(path, mode, *args, **kwargs)

            workspace = AnnotationWorkspace(save_dir=directory)
            with patch("builtins.open", side_effect=counting_open):
                workspace.scan(directory)
                first = tuple(workspace.entry(path).status for path in images)
                second = tuple(workspace.entry(path).status for path in images)

        self.assertEqual(first, second)
        self.assertTrue(all(status.has_annotations for status in first))
        self.assertEqual(workspace.candidate_labels, ("dog",))
        self.assertLessEqual(reads[os.path.normcase(classes)], 1)
        for index in range(20):
            annotation = os.path.normcase(
                os.path.join(directory, "image%02d.txt" % index)
            )
            self.assertLessEqual(reads[annotation], 1)

    def test_adopting_completed_index_preserves_live_active_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            image = os.path.join(directory, "image.png")
            annotation = os.path.join(directory, "image.xml")
            with open(image, "wb"):
                pass
            with open(annotation, "w", encoding="utf-8") as stream:
                stream.write(
                    "<annotation verified='yes'><filename>image.png</filename>"
                    "<object><name>cat</name><bndbox><xmin>1</xmin>"
                    "<ymin>1</ymin><xmax>2</xmax><ymax>2</ymax>"
                    "</bndbox></object></annotation>"
                )
            active = AnnotationWorkspace(save_dir=directory)
            indexed = AnnotationWorkspace(save_dir=directory)
            indexed.scan(directory)
            active.select_active_document(image, annotation)

            active.adopt_index(indexed)

        self.assertEqual(active.active_document_path(image), annotation)
        self.assertTrue(active.entry(image).status.verified)
        self.assertEqual(active.candidate_labels, ("cat",))

    def test_createml_row_lookup_does_not_rescan_collection_records(self):
        with tempfile.TemporaryDirectory() as directory:
            records = []
            images = []
            for index in range(2_000):
                name = "image%05d.png" % index
                path = os.path.join(directory, name)
                with open(path, "wb"):
                    pass
                images.append(path)
                records.append({
                    "image": name,
                    "annotations": [{"label": "cat", "coordinates": {}}],
                })
            collection = os.path.join(directory, "annotations.json")
            with open(collection, "w", encoding="utf-8") as stream:
                json.dump(records, stream)
            workspace = AnnotationWorkspace(save_dir=directory)
            workspace.scan(directory)

            original_matches = CreateMLRecordIdentity.matches
            with patch.object(
                CreateMLRecordIdentity,
                "matches",
                autospec=True,
                side_effect=original_matches,
            ) as matches:
                statuses = tuple(workspace.entry(path).status for path in images)

        self.assertTrue(all(status.has_annotations for status in statuses))
        self.assertEqual(matches.call_count, 0)


if __name__ == "__main__":
    unittest.main()
