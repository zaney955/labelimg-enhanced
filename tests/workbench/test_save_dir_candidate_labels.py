import os
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.annotations.infrastructure.formats.pascal_voc import PascalVocReader


def write_pascal_voc(path, labels):
    annotation = ElementTree.Element("annotation")
    ElementTree.SubElement(annotation, "filename").text = "sample.png"
    for label in labels:
        object_element = ElementTree.SubElement(annotation, "object")
        ElementTree.SubElement(object_element, "name").text = label
        ElementTree.SubElement(object_element, "difficult").text = "0"
        bounding_box = ElementTree.SubElement(object_element, "bndbox")
        for name, value in (
            ("xmin", "1"),
            ("ymin", "1"),
            ("xmax", "20"),
            ("ymax", "20"),
        ):
            ElementTree.SubElement(bounding_box, name).text = value
    ElementTree.ElementTree(annotation).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )


class SaveDirCandidateLabelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.annotation_dir = os.path.join(
            self.temp_dir.name, "annotations"
        )
        os.makedirs(self.annotation_dir)

        self.image_path = os.path.join(self.temp_dir.name, "first.png")
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(self.image_path))

        classes_path = os.path.join(self.temp_dir.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8") as classes_file:
            classes_file.write("predefined\n")

        write_pascal_voc(
            os.path.join(self.annotation_dir, "first.xml"),
            ["zebra", "apple"],
        )
        write_pascal_voc(
            os.path.join(self.annotation_dir, "second.xml"),
            ["apple", "middle"],
        )
        with open(
            os.path.join(self.annotation_dir, "broken.xml"),
            "w",
            encoding="utf-8",
        ) as broken_file:
            broken_file.write("not xml")

        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=classes_path,
            save_dir="",
        ))

    def tearDown(self):
        self.window.deleteLater()
        self.app.processEvents()
        self.temp_dir.cleanup()

    def candidate_names(self):
        return [
            self.window.candidate_label_dialog.list_widget.item(index).text()
            for index in range(
                self.window.candidate_label_dialog.list_widget.count()
            )
        ]

    def change_to_annotation_dir(self):
        with patch(
            "labelimg.workbench.main_window.QFileDialog.getExistingDirectory",
            return_value=self.annotation_dir,
        ):
            self.window.change_save_dir_dialog()

    def test_predefined_classes_are_not_candidate_labels(self):
        self.assertEqual(self.window.label_hist, ["predefined"])
        self.assertEqual(self.candidate_names(), [])

    def test_changing_save_dir_loads_existing_xml_labels(self):
        self.change_to_annotation_dir()

        self.assertEqual(
            self.window.label_hist,
            ["predefined", "apple", "middle", "zebra"],
        )
        self.assertEqual(
            self.candidate_names(),
            ["apple", "middle", "zebra"],
        )

    def test_startup_save_dir_preloads_existing_xml_labels(self):
        startup_window = create_workbench(WorkbenchLaunchOptions(
            class_file=os.path.join(
                self.temp_dir.name,
                "classes.txt",
            ),
            save_dir=self.annotation_dir,
        ))
        try:
            candidate_names = [
                startup_window.candidate_label_dialog.list_widget.item(
                    index
                ).text()
                for index in range(
                    startup_window.candidate_label_dialog.list_widget.count()
                )
            ]

            self.assertEqual(
                candidate_names,
                ["apple", "middle", "zebra"],
            )
        finally:
            startup_window.deleteLater()
            self.app.processEvents()

    def test_reloading_the_same_dir_does_not_duplicate_labels(self):
        self.change_to_annotation_dir()
        self.change_to_annotation_dir()

        self.assertEqual(
            self.window.label_hist,
            ["predefined", "apple", "middle", "zebra"],
        )

    def test_removing_a_labels_last_occurrence_removes_its_candidate(self):
        self.change_to_annotation_dir()
        self.window.auto_saving.setChecked(True)
        self.assertTrue(self.window.load_file(self.image_path))
        zebra_shape = next(
            shape
            for shape in self.window.canvas.shapes
            if shape.label == "zebra"
        )

        self.window.canvas.select_shape(zebra_shape)
        self.window.delete_selected_shape()
        QTest.qWait(300)

        reader = PascalVocReader(
            os.path.join(self.annotation_dir, "first.xml")
        )
        self.assertEqual(
            [shape[0] for shape in reader.get_shapes()],
            ["apple"],
        )
        self.assertNotIn("zebra", self.candidate_names())
        self.assertEqual(
            self.candidate_names(),
            ["apple", "middle"],
        )

    def test_label_used_by_another_xml_remains_a_candidate(self):
        self.change_to_annotation_dir()
        self.window.auto_saving.setChecked(True)
        self.assertTrue(self.window.load_file(self.image_path))
        apple_shape = next(
            shape
            for shape in self.window.canvas.shapes
            if shape.label == "apple"
        )

        self.window.canvas.select_shape(apple_shape)
        self.window.delete_selected_shape()
        QTest.qWait(300)

        self.assertIn("apple", self.window.label_hist)
        self.assertIn("apple", self.candidate_names())


if __name__ == "__main__":
    unittest.main()
