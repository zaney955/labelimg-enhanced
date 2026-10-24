import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QImage
from PyQt5.QtCore import QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from labelimg.annotations.domain.model import AnnotationBox, AnnotationFormat
from labelimg.annotations.infrastructure.document import AnnotationDocument
from labelimg.annotations.infrastructure.formats.pascal_voc import PascalVocReader
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class NestedAnnotationSaveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ, {"LABELIMG_CONFIG_DIR": str(self.root / "config")}
        )
        self.environment.start()
        self.dataset = self.root / "分类数据"
        self.category = self.dataset / "类别一"
        self.category.mkdir(parents=True)
        self.image_path = self.category / "sample.png"
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(0)
        self.assertTrue(image.save(str(self.image_path)))
        self.annotation_path = self.category / "sample.xml"
        AnnotationDocument(
            image_path=str(self.image_path),
            image_data=image,
            boxes=(AnnotationBox(
                "old", ((10, 10), (40, 10), (40, 40), (10, 40))
            ),),
        ).save(str(self.annotation_path.with_suffix("")), AnnotationFormat.PASCAL_VOC)
        classes = self.root / "classes.txt"
        classes.write_text("", encoding="utf-8")
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=str(classes), save_dir=str(self.dataset),
        ))
        self.window.import_dir_images(str(self.dataset))
        self.window.auto_saving.setChecked(False)

    def tearDown(self):
        self.window.auto_save_timer.stop()
        self.window.stop_directory_load()
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()

    def change_label(self, label="new"):
        shape = self.window.canvas.shapes[0]
        with patch.object(
            self.window.candidate_label_dialog, "choose", return_value=label
        ):
            self.window.edit_shape_label(shape)

    def assert_saved_in_category(self):
        self.assertFalse((self.dataset / "sample.xml").exists())
        self.assertEqual(
            PascalVocReader(str(self.annotation_path)).get_shapes()[0][0], "new"
        )
        self.assertFalse(self.window.dirty)

    def test_explicit_save_updates_original_xml_in_shared_nested_directory(self):
        self.assertEqual(self.window.file_path, str(self.image_path))
        self.change_label()
        self.window.save_file()
        self.assert_saved_in_category()

    def test_autosave_updates_original_xml_in_shared_nested_directory(self):
        self.window.auto_saving.setChecked(True)
        self.change_label()
        QTest.qWait(300)
        self.assert_saved_in_category()

    def test_first_save_preserves_category_for_new_annotation(self):
        self.annotation_path.unlink()
        self.window.import_dir_images(str(self.dataset))
        self.window.auto_saving.setChecked(False)
        self.assertFalse(self.window.canvas.shapes)
        self.window.annotation_clipboard = [
            ("new", ((10, 10), (40, 10), (40, 40), (10, 40)), False)
        ]
        self.window.paste_copied_bounding_boxes()
        self.window.save_file()
        self.assert_saved_in_category()

    def test_save_after_save_as_keeps_the_chosen_target(self):
        chosen = self.category / "chosen.xml"
        with patch.object(self.window, "save_file_dialog", return_value=str(chosen)):
            self.window.save_file_as()
        self.change_label()
        self.window.save_file()

        self.assertFalse((self.dataset / "sample.xml").exists())
        self.assertEqual(
            PascalVocReader(str(self.annotation_path)).get_shapes()[0][0], "old"
        )
        self.assertEqual(
            PascalVocReader(str(chosen)).get_shapes()[0][0], "new"
        )
        self.assertFalse(self.window.dirty)

    def test_same_image_name_in_other_category_keeps_its_own_annotation(self):
        other_category = self.dataset / "类别二"
        other_category.mkdir()
        other_image = other_category / "sample.png"
        other_annotation = other_category / "sample.xml"
        other_image.write_bytes(self.image_path.read_bytes())
        other_annotation.write_bytes(self.annotation_path.read_bytes())
        original = other_annotation.read_bytes()
        self.window.import_dir_images(str(self.dataset))
        self.window.auto_saving.setChecked(False)

        self.change_label()
        self.window.save_file()

        self.assert_saved_in_category()
        self.assertEqual(other_annotation.read_bytes(), original)

    def test_separate_annotation_root_preserves_relative_category(self):
        annotations = self.root / "annotations"
        target = annotations / "类别一" / "sample.xml"
        target.parent.mkdir(parents=True)
        target.write_bytes(self.annotation_path.read_bytes())
        with patch(
            "PyQt5.QtWidgets.QFileDialog.getExistingDirectory",
            return_value=str(annotations),
        ):
            self.window.change_save_dir_dialog()
        self.window.auto_saving.setChecked(False)
        self.change_label()
        self.window.save_file()

        self.assertFalse((annotations / "sample.xml").exists())
        self.assertEqual(PascalVocReader(str(target)).get_shapes()[0][0], "new")
        self.assertEqual(
            PascalVocReader(str(self.annotation_path)).get_shapes()[0][0], "old"
        )
        self.assertFalse(self.window.dirty)


if __name__ == "__main__":
    unittest.main()
