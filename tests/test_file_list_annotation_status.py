import os
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QKeySequence
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

from labelimg.app import MainWindow
from labelimg.shape import Shape


def write_pascal_voc(
        path, image_name, verified=False, questioned=False):
    annotation = ElementTree.Element("annotation")
    if verified:
        annotation.set("verified", "yes")
    elif questioned:
        annotation.set("verified", "no")
    ElementTree.SubElement(annotation, "filename").text = image_name
    object_element = ElementTree.SubElement(annotation, "object")
    ElementTree.SubElement(object_element, "name").text = "car"
    ElementTree.SubElement(object_element, "difficult").text = "0"
    bounding_box = ElementTree.SubElement(object_element, "bndbox")
    for name, value in (
        ("xmin", "10"),
        ("ymin", "10"),
        ("xmax", "40"),
        ("ymax", "40"),
    ):
        ElementTree.SubElement(bounding_box, name).text = value
    ElementTree.ElementTree(annotation).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )


class FileListAnnotationStatusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.image_dir = os.path.join(self.temp_dir.name, "images")
        self.annotation_dir = os.path.join(
            self.temp_dir.name,
            "annotations",
        )
        os.makedirs(self.image_dir)
        os.makedirs(self.annotation_dir)

        self.image_paths = []
        for name in (
            "01_blank.png",
            "02_annotated.png",
            "03_verified.png",
            "04_questioned.png",
        ):
            path = os.path.join(self.image_dir, name)
            image = QImage(100, 100, QImage.Format_RGB32)
            image.fill(QColor("white"))
            self.assertTrue(image.save(path))
            self.image_paths.append(os.path.abspath(path))
        self.display_paths = [
            os.path.relpath(path, self.image_dir)
            for path in self.image_paths
        ]

        write_pascal_voc(
            os.path.join(self.annotation_dir, "02_annotated.xml"),
            "02_annotated.png",
        )
        write_pascal_voc(
            os.path.join(self.annotation_dir, "03_verified.xml"),
            "03_verified.png",
            verified=True,
        )
        write_pascal_voc(
            os.path.join(self.annotation_dir, "04_questioned.xml"),
            "04_questioned.png",
            questioned=True,
        )

        classes_path = os.path.join(self.temp_dir.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass

        self.window = MainWindow(
            default_prefdef_class_file=classes_path,
            default_save_dir=self.annotation_dir,
        )
        self.window.auto_saving.setChecked(False)
        self.window.import_dir_images(self.image_dir)

    def tearDown(self):
        self.window.deleteLater()
        self.app.processEvents()
        self.temp_dir.cleanup()

    def item(self, index):
        return self.window.file_list_widget.item(index)

    def add_rectangle(self):
        shape = Shape(label="car")
        for point in (
            QPointF(10, 10),
            QPointF(40, 10),
            QPointF(40, 40),
            QPointF(10, 40),
        ):
            shape.add_point(point)
        shape.close()
        self.window.canvas.load_shapes([shape])
        self.window.add_label(shape)
        return shape

    def test_list_marks_annotated_verified_and_questioned_images(self):
        self.assertEqual(self.item(0).text(), self.display_paths[0])
        self.assertEqual(
            self.item(1).text(),
            self.display_paths[1] + "  ○",
        )
        self.assertEqual(
            self.item(2).text(),
            self.display_paths[2] + "  ✓",
        )
        self.assertEqual(
            self.item(3).text(),
            self.display_paths[3] + "  ?",
        )
        for index, image_path in enumerate(self.image_paths):
            self.assertEqual(
                self.item(index).data(Qt.UserRole),
                image_path,
            )
            self.assertEqual(self.item(index).toolTip(), image_path)

    def test_nested_file_shows_relative_path_and_opens_absolute_path(self):
        nested_dir = os.path.join(self.image_dir, "nested")
        os.makedirs(nested_dir)
        nested_path = os.path.abspath(
            os.path.join(nested_dir, "child.png")
        )
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(nested_path))

        self.window.import_dir_images(self.image_dir)
        nested_item = next(
            self.item(index)
            for index in range(self.window.file_list_widget.count())
            if self.item(index).data(Qt.UserRole) == nested_path
        )

        self.assertEqual(
            nested_item.text(),
            os.path.join("nested", "child.png"),
        )
        self.assertEqual(nested_item.toolTip(), nested_path)

        self.window.file_item_double_clicked(nested_item)
        self.assertEqual(self.window.file_path, nested_path)

    def test_double_click_uses_stored_path_instead_of_display_text(self):
        self.window.file_item_double_clicked(self.item(1))

        self.assertEqual(self.window.file_path, self.image_paths[1])
        self.assertEqual(self.window.cur_img_idx, 1)

    def test_question_shortcut_is_ctrl_space(self):
        shortcut = self.window.actions.question.shortcut()

        self.assertEqual(shortcut, QKeySequence("Ctrl+Space"))
        self.assertFalse(self.window.actions.question.icon().isNull())
        self.assertNotEqual(
            self.window.actions.question.icon().cacheKey(),
            self.window.actions.verify.icon().cacheKey(),
        )
        self.assertIn(
            self.window.actions.question,
            self.window.actions.beginner,
        )
        verify_index = self.window.actions.beginner.index(
            self.window.actions.verify
        )
        self.assertIs(
            self.window.actions.beginner[verify_index + 1],
            self.window.actions.question,
        )

    def test_ctrl_space_triggers_question_status(self):
        self.window.file_item_double_clicked(self.item(1))
        self.window.show()
        self.window.activateWindow()
        self.window.canvas.setFocus()
        self.app.processEvents()

        QTest.keyClick(
            self.window.canvas,
            Qt.Key_Space,
            Qt.ControlModifier,
        )
        self.app.processEvents()

        self.assertTrue(self.window.canvas.questioned)
        self.assertFalse(self.window.canvas.verified)
        self.assertEqual(
            self.item(1).text(),
            self.display_paths[1] + "  ?",
        )

    def test_loading_questioned_xml_restores_canvas_status(self):
        self.window.file_item_double_clicked(self.item(3))

        self.assertTrue(self.window.canvas.questioned)
        self.assertFalse(self.window.canvas.verified)

    def test_unannotated_image_can_persist_review_only_pascal_document(self):
        self.window.question_image()

        annotation_path = os.path.join(
            self.annotation_dir,
            "01_blank.xml",
        )
        root = ElementTree.parse(annotation_path).getroot()
        self.assertEqual(root.attrib.get("verified"), "no")
        self.assertEqual(root.findall("object"), [])
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0] + "  ?",
        )

        self.window.question_image()

        self.assertFalse(os.path.exists(annotation_path))
        self.assertEqual(self.item(0).text(), self.display_paths[0])

    def test_batch_review_state_sets_explicit_state_for_selection(self):
        self.item(0).setSelected(True)
        self.item(1).setSelected(True)

        with patch(
            "labelimg.app.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ):
            self.window.set_selected_review_state("verified")

        for stem in ("01_blank", "02_annotated"):
            root = ElementTree.parse(
                os.path.join(self.annotation_dir, stem + ".xml")
            ).getroot()
            self.assertEqual(root.attrib.get("verified"), "yes")
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0] + "  ✓",
        )
        self.assertEqual(
            self.item(1).text(),
            self.display_paths[1] + "  ✓",
        )

    def test_opening_next_annotated_image_starts_without_selection(self):
        self.window.open_next_image()
        self.app.processEvents()

        self.assertEqual(self.window.file_path, self.image_paths[1])
        self.assertEqual(self.window.label_list.selectedItems(), [])
        self.assertIsNone(self.window.label_list.currentItem())
        self.assertEqual(self.window.canvas.selected_shapes, [])
        self.assertFalse(self.window.actions.delete.isEnabled())
        self.assertFalse(self.window.actions.copy.isEnabled())
        self.assertFalse(self.window.actions.edit.isEnabled())

    def test_changing_save_dir_refreshes_all_status_marks(self):
        other_annotation_dir = os.path.join(
            self.temp_dir.name,
            "other_annotations",
        )
        os.makedirs(other_annotation_dir)
        write_pascal_voc(
            os.path.join(other_annotation_dir, "01_blank.xml"),
            "01_blank.png",
            verified=True,
        )

        with patch(
            "labelimg.app.QFileDialog.getExistingDirectory",
            return_value=other_annotation_dir,
        ):
            self.window.change_save_dir_dialog()

        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0] + "  ✓",
        )
        self.assertEqual(self.item(1).text(), self.display_paths[1])
        self.assertEqual(self.item(2).text(), self.display_paths[2])
        self.assertEqual(self.item(3).text(), self.display_paths[3])

    def test_status_updates_after_save_verify_and_delete(self):
        shape = self.add_rectangle()
        self.window.save_file()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0] + "  ○",
        )

        self.window.question_image()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0] + "  ?",
        )
        root = ElementTree.parse(
            os.path.join(self.annotation_dir, "01_blank.xml")
        ).getroot()
        self.assertEqual(root.attrib.get("verified"), "no")
        self.assertTrue(self.window.canvas.questioned)
        self.assertFalse(self.window.canvas.verified)
        self.assertEqual(
            self.window.canvas.status_background_color(),
            QColor(255, 193, 7, 128),
        )

        self.window.verify_image()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0] + "  ✓",
        )
        self.assertFalse(self.window.canvas.questioned)
        self.assertTrue(self.window.canvas.verified)
        self.assertEqual(
            self.window.canvas.status_background_color(),
            QColor(184, 239, 38, 128),
        )

        self.window.question_image()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0] + "  ?",
        )
        self.assertTrue(self.window.canvas.questioned)
        self.assertFalse(self.window.canvas.verified)

        self.window.question_image()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0] + "  ○",
        )
        root = ElementTree.parse(
            os.path.join(self.annotation_dir, "01_blank.xml")
        ).getroot()
        self.assertNotIn("verified", root.attrib)
        self.assertFalse(self.window.canvas.questioned)
        self.assertFalse(self.window.canvas.verified)
        self.assertEqual(
            self.window.canvas.status_background_color(),
            QColor(232, 232, 232, 255),
        )

        self.window.verify_image()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0] + "  ✓",
        )
        self.window.verify_image()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0] + "  ○",
        )

        self.window.canvas.select_shape(shape)
        self.window.delete_selected_shape()
        self.window.save_file()
        self.assertEqual(self.item(0).text(), self.display_paths[0])
        self.assertFalse(os.path.exists(
            os.path.join(self.annotation_dir, "01_blank.xml")
        ))


if __name__ == "__main__":
    unittest.main()
