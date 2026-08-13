import os
import shutil
import tempfile
import unittest
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor, QImage, QKeySequence
from PyQt5.QtWidgets import QApplication

from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.files.application.recovery import TrashIdentity


class FakeTrashAdapter:
    def __init__(self, directory):
        self.directory = directory
        self.paths = {}

    def move(self, path):
        token = str(len(self.paths) + 1)
        destination = os.path.join(self.directory, token)
        shutil.move(path, destination)
        self.paths[token] = destination
        return TrashIdentity("path", destination, path)

    def exists(self, identity):
        return os.path.exists(identity.token)

    def restore(self, identity, destination):
        shutil.move(identity.token, destination)


def write_pascal_voc(path, label):
    annotation = ElementTree.Element("annotation")
    ElementTree.SubElement(annotation, "filename").text = "01.png"
    object_element = ElementTree.SubElement(annotation, "object")
    ElementTree.SubElement(object_element, "name").text = label
    ElementTree.SubElement(object_element, "difficult").text = "0"
    bounding_box = ElementTree.SubElement(object_element, "bndbox")
    for name, value in (
        ("xmin", "1"),
        ("ymin", "1"),
        ("xmax", "7"),
        ("ymax", "7"),
    ):
        ElementTree.SubElement(bounding_box, name).text = value
    ElementTree.ElementTree(annotation).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )


class DeleteImageNavigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.annotation_dir = os.path.join(
            self.temp_dir.name,
            "annotations",
        )
        os.makedirs(self.annotation_dir)
        self.image_paths = []
        for name in ("01.png", "02.png", "03.png"):
            path = os.path.join(self.temp_dir.name, name)
            image = QImage(8, 8, QImage.Format_RGB32)
            image.fill(QColor("white"))
            self.assertTrue(image.save(path))
            self.image_paths.append(os.path.abspath(path))

        classes_path = os.path.join(self.temp_dir.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass

        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=classes_path,
            save_dir=self.annotation_dir,
        ))
        trash_dir = os.path.join(self.temp_dir.name, "trash")
        os.makedirs(trash_dir)
        self.window.system_trash = FakeTrashAdapter(trash_dir)
        self.window.import_dir_images(self.temp_dir.name)

    def tearDown(self):
        self.window.deleteLater()
        self.app.processEvents()
        self.temp_dir.cleanup()

    def test_delete_image_shortcut_is_ctrl_delete(self):
        shortcut = self.window.actions.deleteImg.shortcut()

        self.assertEqual(shortcut, QKeySequence("Ctrl+Delete"))
        self.assertEqual(shortcut.toString(), "Ctrl+Del")

    def test_deleting_first_image_keeps_the_next_image_open(self):
        self.assertEqual(self.window.file_path, self.image_paths[0])

        self.window.delete_image()

        self.assertEqual(self.window.file_path, self.image_paths[1])
        self.assertEqual(self.window.cur_img_idx, 0)
        self.assertEqual(self.window.img_count, 2)

    def test_deleting_middle_image_keeps_the_next_image_open(self):
        self.window.cur_img_idx = 1
        self.assertTrue(self.window.load_file(self.image_paths[1]))

        self.window.delete_image()

        self.assertEqual(self.window.file_path, self.image_paths[2])
        self.assertEqual(self.window.cur_img_idx, 1)
        self.assertEqual(self.window.img_count, 2)

    def test_deleting_last_image_opens_the_previous_image(self):
        self.window.cur_img_idx = 2
        self.assertTrue(self.window.load_file(self.image_paths[2]))

        self.window.delete_image()

        self.assertEqual(self.window.file_path, self.image_paths[1])
        self.assertEqual(self.window.cur_img_idx, 1)
        self.assertEqual(self.window.img_count, 2)

    def test_deleting_the_only_remaining_image_clears_the_view(self):
        self.window.delete_image()
        self.window.delete_image()
        self.window.delete_image()

        self.assertIsNone(self.window.file_path)
        self.assertEqual(self.window.cur_img_idx, 0)
        self.assertEqual(self.window.img_count, 0)
        self.assertFalse(self.window.canvas.isEnabled())

    def test_deleting_image_removes_all_saved_annotation_formats(self):
        deleted_paths = []
        for extension in (".xml", ".txt", ".json"):
            annotation_path = os.path.join(
                self.annotation_dir,
                "01" + extension,
            )
            with open(annotation_path, "w", encoding="utf-8"):
                pass
            deleted_paths.append(annotation_path)

        neighbour_annotation = os.path.join(
            self.annotation_dir,
            "02.xml",
        )
        write_pascal_voc(neighbour_annotation, "neighbour")

        self.window.delete_image()

        for annotation_path in deleted_paths:
            self.assertFalse(os.path.exists(annotation_path))
        self.assertTrue(os.path.exists(neighbour_annotation))

    def test_deleting_image_removes_annotations_beside_image(self):
        self.window.default_save_dir = None
        self.window.auto_saving.setChecked(False)
        deleted_paths = []
        for extension in (".xml", ".txt", ".json"):
            annotation_path = os.path.splitext(
                self.image_paths[0]
            )[0] + extension
            with open(annotation_path, "w", encoding="utf-8"):
                pass
            deleted_paths.append(annotation_path)

        self.window.delete_image()

        for annotation_path in deleted_paths:
            self.assertFalse(os.path.exists(annotation_path))

    def test_deleting_annotation_updates_candidate_labels(self):
        deleted_label = "only_on_deleted_image"
        annotation_path = os.path.join(
            self.annotation_dir,
            "01.xml",
        )
        write_pascal_voc(annotation_path, deleted_label)
        self.window.load_candidate_labels_from_dir(
            self.annotation_dir
        )
        self.assertIn(deleted_label, self.window.candidate_labels)

        self.window.delete_image()

        self.assertFalse(os.path.exists(annotation_path))
        self.assertNotIn(
            deleted_label,
            self.window.candidate_labels,
        )


if __name__ == "__main__":
    unittest.main()
