import os
import tempfile
import unittest

from PyQt5.QtGui import QImage

from labelimg.annotation_document import (
    AnnotationBox,
    AnnotationDocument,
    AnnotationFormat,
)


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


if __name__ == "__main__":
    unittest.main()
