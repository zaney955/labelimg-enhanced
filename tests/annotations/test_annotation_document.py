import os
import json
import shutil
import tempfile
import unittest

from PyQt5.QtGui import QImage

from labelimg.annotations.domain.model import (
    AnnotationBox,
    AnnotationFormat,
)
from labelimg.annotations.infrastructure.document import AnnotationDocument


class AnnotationDocumentTest(unittest.TestCase):
    def setUp(self):
        self.image_path = os.path.abspath("tests/test.512.512.bmp")
        self.image = QImage(self.image_path)
        self.boxes = (
            AnnotationBox(
                label="cat",
                points=((10, 20), (110, 20), (110, 120), (10, 120)),
                difficult=True,
            ),
        )

    def document(self):
        return AnnotationDocument(
            image_path=self.image_path,
            image_data=self.image,
            boxes=self.boxes,
            class_names=("cat",),
            verified=True,
        )

    def test_format_owns_display_name_and_extension(self):
        self.assertEqual(
            AnnotationFormat.PASCAL_VOC.extension,
            ".xml",
        )
        self.assertEqual(
            AnnotationFormat.from_path("sample.txt"),
            AnnotationFormat.YOLO,
        )

    def test_pascal_voc_round_trip_uses_one_document_interface(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.document().save(
                os.path.join(directory, "sample"),
                AnnotationFormat.PASCAL_VOC,
            )
            loaded = AnnotationDocument.load(
                target,
                self.image_path,
                self.image,
            )

        self.assertEqual(target[-4:], ".xml")
        self.assertEqual(loaded.boxes[0].label, "cat")
        self.assertTrue(loaded.boxes[0].difficult)
        self.assertTrue(loaded.verified)

    def test_yolo_round_trip_uses_same_document_interface(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.document().save(
                os.path.join(directory, "sample"),
                AnnotationFormat.YOLO,
            )
            loaded = AnnotationDocument.load(
                target,
                self.image_path,
                self.image,
            )

        self.assertEqual(loaded.boxes[0].label, "cat")
        self.assertEqual(loaded.boxes[0].points[0], (10, 20))
        self.assertTrue(loaded.verified)

    def test_yolo_inspect_ignores_compact_comment_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "sample.txt")
            with open(
                os.path.join(directory, "classes.txt"),
                "w",
                encoding="utf8",
            ) as output:
                output.write("cat\n")
            with open(target, "w", encoding="utf8") as output:
                output.write("#dataset note\n0 0.5 0.5 0.2 0.2\n")

            status = AnnotationDocument.inspect(target)

        self.assertTrue(status.has_annotations)
        self.assertEqual(status.labels, frozenset({"cat"}))

    def test_create_ml_round_trip_uses_same_document_interface(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.document().save(
                os.path.join(directory, "annotations"),
                AnnotationFormat.CREATE_ML,
            )
            loaded = AnnotationDocument.load(
                target,
                self.image_path,
                self.image,
            )

        self.assertEqual(loaded.boxes[0].label, "cat")
        self.assertTrue(loaded.verified)

    def test_legacy_create_ml_annotations_keep_verified_default(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "annotations.json")
            with open(target, "w", encoding="utf8") as output:
                json.dump(
                    [
                        {
                            "image": os.path.basename(self.image_path),
                            "annotations": [
                                {
                                    "label": "cat",
                                    "coordinates": {
                                        "x": 60,
                                        "y": 70,
                                        "width": 100,
                                        "height": 100,
                                    },
                                }
                            ],
                        }
                    ],
                    output,
                )

            loaded = AnnotationDocument.load(
                target,
                self.image_path,
                self.image,
            )
            status = AnnotationDocument.inspect(target)

        self.assertTrue(loaded.verified)
        self.assertTrue(status.verified)

    def test_questioned_review_state_round_trips_in_yolo_and_createml(self):
        with tempfile.TemporaryDirectory() as directory:
            document = self.document()
            document.verified = False
            document.questioned = True
            for annotation_format in (
                AnnotationFormat.YOLO,
                AnnotationFormat.CREATE_ML,
            ):
                target = document.save(
                    os.path.join(directory, annotation_format.name),
                    annotation_format,
                )
                loaded = AnnotationDocument.load(
                    target,
                    self.image_path,
                    self.image,
                )
                self.assertFalse(loaded.verified)
                self.assertTrue(loaded.questioned)

    def test_inspect_returns_status_without_exposing_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.document().save(
                os.path.join(directory, "sample"),
                AnnotationFormat.PASCAL_VOC,
            )
            status = AnnotationDocument.inspect(target)

        self.assertTrue(status.has_annotations)
        self.assertTrue(status.verified)
        self.assertEqual(status.labels, frozenset({"cat"}))

    def test_format_adapters_keep_image_path_hint_behind_document_seam(self):
        with tempfile.TemporaryDirectory() as directory:
            hinted_image_path = os.path.join(
                directory,
                os.path.basename(self.image_path),
            )
            shutil.copyfile(self.image_path, hinted_image_path)
            voc_path = self.document().save(
                os.path.join(directory, "sample"),
                AnnotationFormat.PASCAL_VOC,
            )
            create_ml_path = self.document().save(
                os.path.join(directory, "annotations"),
                AnnotationFormat.CREATE_ML,
            )

            self.assertEqual(
                AnnotationDocument.image_path_hint(voc_path),
                self.image_path,
            )
            self.assertEqual(
                AnnotationDocument.image_path_hint(create_ml_path),
                hinted_image_path,
            )


if __name__ == "__main__":
    unittest.main()
