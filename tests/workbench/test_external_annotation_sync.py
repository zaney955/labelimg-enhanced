import os
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

from labelimg.canvas.shape import Shape
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


def write_pascal_voc(path, image_name, label):
    annotation = ElementTree.Element("annotation")
    ElementTree.SubElement(annotation, "filename").text = image_name
    object_element = ElementTree.SubElement(annotation, "object")
    ElementTree.SubElement(object_element, "name").text = label
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
        path, encoding="utf-8", xml_declaration=True
    )


class ExternalAnnotationSyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings_environment = patch.dict(
            os.environ,
            {"LABELIMG_CONFIG_DIR": self.temporary.name},
        )
        self.settings_environment.start()
        self.image_dir = os.path.join(self.temporary.name, "images")
        self.annotation_dir = os.path.join(self.temporary.name, "annotations")
        os.makedirs(self.image_dir)
        os.makedirs(self.annotation_dir)
        self.images = []
        for name in ("first.png", "second.png"):
            path = os.path.abspath(os.path.join(self.image_dir, name))
            image = QImage(100, 100, QImage.Format_RGB32)
            image.fill(QColor("white"))
            self.assertTrue(image.save(path))
            self.images.append(path)
        self.first_annotation = os.path.join(
            self.annotation_dir, "first.xml"
        )
        write_pascal_voc(self.first_annotation, "first.png", "old")
        classes = os.path.join(self.temporary.name, "classes.txt")
        with open(classes, "w", encoding="utf-8"):
            pass
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=classes,
            save_dir=self.annotation_dir,
        ))
        self.assertTrue(self.window.load_file(self.images[0]))
        self.window.m_img_list = list(self.images)
        self.window.img_count = len(self.images)

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.settings_environment.stop()
        self.temporary.cleanup()

    def test_external_change_reloads_current_canvas_and_candidates(self):
        self.assertEqual(self.window.canvas.shapes[0].label, "old")
        write_pascal_voc(self.first_annotation, "first.png", "external")

        self.window._process_external_annotation_change()

        self.assertEqual(self.window.canvas.shapes[0].label, "external")
        self.assertIn("external", self.window.candidate_labels)
        self.assertNotIn("old", self.window.candidate_labels)
        self.assertFalse(self.window.annotation_editing.view.dirty)
        self.assertFalse(self.window.annotation_editing.view.can_undo)

    def test_filesystem_watcher_delivers_external_change_while_idle(self):
        write_pascal_voc(self.first_annotation, "first.png", "watched")

        QTest.qWait(900)

        self.assertEqual(self.window.canvas.shapes[0].label, "watched")
        self.assertIn("watched", self.window.candidate_labels)

    def test_load_external_conflict_rebases_and_allows_subsequent_autosave(self):
        self.window.auto_saving.setChecked(False)
        self.window.canvas.shapes[0].label = "local"
        self.window.set_dirty()
        write_pascal_voc(self.first_annotation, "first.png", "external")
        outcome = self.window.annotation_persistence.save(
            self.images[0], self.window.annotation_format,
        )
        self.assertFalse(outcome.ok)
        conflict = next(iter(self.window.annotation_persistence.conflicts.values()))

        with patch.object(self.window, "error_message") as error:
            resolved = self.window._load_external_resource_conflict(conflict)

        self.assertTrue(resolved, error.call_args)
        error.assert_not_called()
        self.assertEqual(self.window.canvas.shapes[0].label, "external")
        self.assertFalse(self.window.dirty)
        self.assertFalse(self.window.annotation_persistence.has_conflict(self.images[0]))
        self.window.auto_saving.setChecked(True)
        self.window.canvas.shapes[0].label = "after-resolution"
        self.window.set_dirty()
        self.window.save_dirty_annotations()
        self.assertFalse(self.window.dirty)
        self.assertEqual(
            ElementTree.parse(self.first_annotation).findtext("object/name"),
            "after-resolution",
        )

    def replace_first_image(self):
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(QColor("red"))
        self.assertTrue(image.save(self.images[0]))

    def test_reopening_replaced_clean_image_autosaves_without_conflict(self):
        self.assertTrue(self.window.load_file(self.images[1]))
        self.replace_first_image()
        self.assertTrue(self.window.load_file(self.images[0]))
        self.assertEqual(self.window.image.pixelColor(0, 0), QColor("red"))
        self.window.auto_saving.setChecked(True)
        self.window.canvas.shapes[0].label = "replacement"
        self.window.set_dirty()

        with patch(
            "labelimg.workbench.main_window.localized_warning",
            return_value=QMessageBox.Cancel,
        ) as warning:
            self.window.open_file_list_path(self.images[1])

        warning.assert_not_called()
        self.assertEqual(self.window.file_path, self.images[1])
        self.assertFalse(self.window.annotation_persistence.conflicts)
        self.assertEqual(
            ElementTree.parse(self.first_annotation).findtext("object/name"),
            "replacement",
        )

    def test_background_check_refreshes_same_metadata_replacement_before_editing(self):
        cache = self.window._ensure_image_decode_cache()
        cache._verification_interval = 0
        with patch('labelimg.files.ui.image_decode_cache._source_token', return_value=('unchanged',)):
            self.assertTrue(self.window.load_file(self.images[0]))
            self.assertTrue(self.window.load_file(self.images[1]))
            self.replace_first_image()
            cache.get(self.images[0])
            for _ in range(100):
                if cache.get(self.images[0]) is None:
                    break
                QTest.qWait(10)
            self.assertIsNone(cache.get(self.images[0]))
            self.assertTrue(self.window.load_file(self.images[0]))
            self.assertEqual(self.window.image.pixelColor(0, 0), QColor('red'))
            self.window.auto_saving.setChecked(True)
            self.window.canvas.shapes[0].label = 'new-image'
            self.window.set_dirty()
            self.window.save_dirty_annotations()
            self.assertFalse(self.window.dirty)
            self.assertFalse(self.window.annotation_persistence.conflicts)

    def test_load_replaced_image_conflict_refreshes_pixels_and_autosave(self):
        self.window.auto_saving.setChecked(True)
        self.window.canvas.shapes[0].label = "local"
        self.window.set_dirty()
        self.replace_first_image()
        self.window.save_dirty_annotations()
        conflict = next(iter(self.window.annotation_persistence.conflicts.values()))
        self.assertEqual(conflict.resource, os.path.normcase(self.images[0]))

        with patch.object(self.window, "error_message") as error:
            resolved = self.window._load_external_resource_conflict(conflict)

        self.assertTrue(resolved, error.call_args)
        self.assertEqual(self.window.image.pixelColor(0, 0), QColor("red"))
        self.assertEqual(self.window.canvas.shapes[0].label, "old")
        self.assertFalse(self.window.dirty)
        self.assertFalse(self.window.annotation_persistence.conflicts)
        self.window.canvas.shapes[0].label = "replacement"
        self.window.set_dirty()
        self.window.save_dirty_annotations()
        self.assertFalse(self.window.dirty)

    def test_unreadable_replacement_does_not_discard_local_edits_or_conflict(self):
        self.window.auto_saving.setChecked(True)
        self.window.canvas.shapes[0].label = "local"
        self.window.set_dirty()
        with open(self.images[0], "wb") as target:
            target.write(b"not an image")
        self.window.save_dirty_annotations()
        conflict = next(iter(self.window.annotation_persistence.conflicts.values()))

        with patch.object(self.window, "error_message") as error:
            resolved = self.window._load_external_resource_conflict(conflict)

        self.assertFalse(resolved)
        error.assert_called_once()
        self.assertEqual(self.window.canvas.shapes[0].label, "local")
        self.assertTrue(self.window.dirty)
        self.assertTrue(self.window.annotation_persistence.has_conflict(self.images[0]))

    def test_content_identical_rewrite_does_not_rebuild_canvas(self):
        original_shape = self.window.canvas.shapes[0]
        original_message = self.window.statusBar().currentMessage()
        with open(self.first_annotation, "rb") as source:
            content = source.read()
        with open(self.first_annotation, "wb") as target:
            target.write(content)

        self.window._process_external_annotation_change()

        self.assertIs(self.window.canvas.shapes[0], original_shape)
        self.assertEqual(
            self.window.statusBar().currentMessage(), original_message
        )

    def test_external_deletion_clears_clean_current_document(self):
        os.remove(self.first_annotation)

        self.window._process_external_annotation_change()

        self.assertEqual(self.window.canvas.shapes, [])
        self.assertNotIn("old", self.window.candidate_labels)
        self.assertFalse(self.window.annotation_editing.view.dirty)

    def test_inactive_image_uses_latest_disk_document_when_reopened(self):
        self.assertTrue(self.window.load_file(self.images[1]))
        write_pascal_voc(self.first_annotation, "first.png", "latest")

        self.assertTrue(self.window.load_file(self.images[0]))

        self.assertEqual(self.window.canvas.shapes[0].label, "latest")
        self.assertIn("latest", self.window.candidate_labels)
        self.assertNotIn("old", self.window.candidate_labels)

    def test_invalid_target_annotation_cancels_navigation(self):
        second_annotation = os.path.join(
            self.annotation_dir, "second.xml"
        )
        with open(second_annotation, "w", encoding="utf-8") as target:
            target.write("<annotation>")

        with patch.object(self.window, "error_message"):
            self.window.open_file_list_path(self.images[1])

        self.assertEqual(self.window.file_path, self.images[0])
        self.assertEqual(self.window.cur_img_idx, 0)
        self.assertEqual(self.window.canvas.shapes[0].label, "old")

    def test_new_workspace_enables_autosave_but_same_workspace_does_not(self):
        self.window.auto_saving.setChecked(False)

        self.window.import_dir_images(self.image_dir)
        self.assertTrue(self.window.auto_saving.isChecked())

        self.window.auto_saving.setChecked(False)
        self.window.import_dir_images(self.image_dir)
        self.assertFalse(self.window.auto_saving.isChecked())

    def test_navigation_cancel_keeps_dirty_current_image_open(self):
        self.window.auto_saving.setChecked(False)
        shape = Shape(label="local")
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
        self.window.set_dirty()

        with patch(
            "labelimg.workbench.main_window.localized_warning",
            return_value=QMessageBox.Cancel,
        ):
            self.window.open_file_list_path(self.images[1])

        self.assertEqual(self.window.file_path, self.images[0])
        self.assertTrue(self.window.annotation_editing.view.dirty)

    def test_navigation_save_waits_for_success_before_switching(self):
        self.window.auto_saving.setChecked(False)
        self.window.canvas.shapes[0].label = "local"
        self.window.set_dirty()

        with patch(
            "labelimg.workbench.main_window.localized_warning",
            return_value=QMessageBox.Save,
        ), patch.object(
            self.window,
            "save_file",
            wraps=self.window.save_file,
        ) as save_file:
            self.window.open_file_list_path(self.images[1])

        save_file.assert_called_once_with()
        self.assertFalse(
            self.window.annotation_editing.view.dirty,
            dict(self.window.annotation_persistence.conflicts),
        )
        self.assertEqual(self.window.file_path, self.images[1])
        self.assertFalse(
            self.window.annotation_editing.view_image(
                self.images[0], touch=False
            ).dirty
        )

    def test_navigation_save_failure_keeps_current_image_open(self):
        self.window.auto_saving.setChecked(False)
        self.window.canvas.shapes[0].label = "local"
        self.window.set_dirty()

        with patch(
            "labelimg.workbench.main_window.localized_warning",
            return_value=QMessageBox.Save,
        ), patch.object(self.window, "save_file"):
            self.window.open_file_list_path(self.images[1])

        self.assertEqual(self.window.file_path, self.images[0])
        self.assertTrue(self.window.annotation_editing.view.dirty)


class ImageDirectoryAutosaveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_autosave_uses_image_directory_without_custom_save_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = os.path.join(directory, "sample.png")
            image = QImage(50, 50, QImage.Format_RGB32)
            image.fill(QColor("white"))
            self.assertTrue(image.save(image_path))
            classes = os.path.join(directory, "classes.txt")
            with open(classes, "w", encoding="utf-8"):
                pass
            with patch.dict(
                os.environ,
                {"LABELIMG_CONFIG_DIR": directory},
            ):
                window = create_workbench(WorkbenchLaunchOptions(
                    class_file=classes,
                ))
            window.auto_saving.setChecked(True)
            self.assertTrue(window.load_file(image_path))
            shape = Shape(label="saved")
            for point in (
                QPointF(5, 5),
                QPointF(20, 5),
                QPointF(20, 20),
                QPointF(5, 20),
            ):
                shape.add_point(point)
            shape.close()
            window.canvas.load_shapes([shape])
            window.add_label(shape)
            window.set_dirty()

            window.save_dirty_annotations()

            self.assertTrue(os.path.isfile(os.path.join(directory, "sample.xml")))
            self.assertFalse(window.annotation_editing.view.dirty)
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
