import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QKeySequence
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

from labelimg.app import MainWindow
from labelimg.i18n import SIMPLIFIED_CHINESE, set_language
from labelimg.annotation_document import AnnotationDocument, AnnotationFormat
from labelimg.constants import FORMAT_YOLO
from labelimg.shape import Shape
from labelimg.file_recovery import (
    FileRecoveryError,
    ReviewRecoveryRecord,
    TrashIdentity,
)
from labelimg.file_list import (
    FILE_ANNOTATION_STATE_ROLE,
    FILE_REVIEW_STATE_ROLE,
)


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
        set_language(SIMPLIFIED_CHINESE)
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
        set_language(SIMPLIFIED_CHINESE)
        trash_dir = os.path.join(self.temp_dir.name, "trash")
        os.makedirs(trash_dir)
        self.window.system_trash = FakeTrashAdapter(trash_dir)
        self.window.auto_saving.setChecked(False)
        self.window.import_dir_images(self.image_dir)

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
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
        self.window.set_dirty()
        return shape

    def test_list_separates_annotation_and_review_states_from_filename(self):
        expected_annotation = (
            "unannotated",
            "annotated",
            "annotated",
            "annotated",
        )
        expected_review = (
            "unreviewed",
            "unreviewed",
            "verified",
            "questioned",
        )
        for index, image_path in enumerate(self.image_paths):
            self.assertEqual(self.item(index).text(), self.display_paths[index])
            self.assertEqual(
                self.item(index).data(Qt.UserRole),
                image_path,
            )
            self.assertEqual(
                self.item(index).data(FILE_ANNOTATION_STATE_ROLE),
                expected_annotation[index],
            )
            self.assertEqual(
                self.item(index).data(FILE_REVIEW_STATE_ROLE),
                expected_review[index],
            )
            self.assertEqual(self.item(index).toolTip(), image_path)

    def test_state_selection_uses_independent_dimensions(self):
        self.window.select_files_by_annotation_state("annotated")
        self.assertEqual(
            self.window.selected_file_paths(),
            self.image_paths[1:],
        )

        self.window.select_files_by_review_state("unreviewed")
        self.assertEqual(
            self.window.selected_file_paths(),
            self.image_paths[:2],
        )

        self.window.select_files_by_review_state("verified")
        self.assertEqual(
            self.window.selected_file_paths(),
            [self.image_paths[2]],
        )

    def test_persistence_filter_updates_live_with_dirty_and_saved_state(self):
        controls = self.window.file_list_controls
        controls.filter_panel.alert_combo.setCurrentIndex(1)
        self.assertEqual(
            self.window.visible_file_paths(),
            self.image_paths,
        )

        self.add_rectangle()
        self.assertNotIn(
            self.window.file_path,
            self.window.visible_file_paths(),
        )
        self.assertIn(
            "当前图像已被筛选隐藏",
            self.window.file_selection_count_label.text(),
        )

        controls.filter_panel.alert_combo.setCurrentIndex(2)
        self.assertEqual(
            self.window.visible_file_paths(),
            [self.window.file_path],
        )

        self.window.save_file()
        self.assertEqual(self.window.visible_file_paths(), [])
        self.assertIs(
            self.window.file_list_stack.currentWidget(),
            self.window.file_list_empty_state,
        )

    def test_annotation_filter_reapplies_after_saving_first_box(self):
        controls = self.window.file_list_controls
        controls.filter_panel.annotation_combo.setCurrentIndex(1)
        self.assertEqual(
            self.window.visible_file_paths(),
            [self.image_paths[0]],
        )

        self.add_rectangle()
        self.window.save_file()

        self.assertEqual(self.window.visible_file_paths(), [])
        self.assertEqual(
            self.window.file_list_controls.state.annotation_filter,
            "unannotated",
        )

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
        self.assertEqual(
            set(self.window.review_control.actions),
            {'unreviewed', 'questioned', 'verified'},
        )
        self.assertIs(
            self.window.top_commands.review_control,
            self.window.review_control,
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
            self.display_paths[1],
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
            self.display_paths[0],
        )

        self.window.question_image()

        self.assertFalse(os.path.exists(annotation_path))
        self.assertEqual(self.item(0).text(), self.display_paths[0])

    def test_batch_review_state_sets_explicit_state_for_selection(self):
        self.item(0).setSelected(True)
        self.item(1).setSelected(True)

        with patch(
            "labelimg.app.localized_question",
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
            self.display_paths[0],
        )
        self.assertEqual(
            self.item(1).text(),
            self.display_paths[1],
        )

    def test_batch_review_cancels_pending_edit_before_saving(self):
        self.item(0).setSelected(True)
        self.window.annotation_editing.begin_edit("Move box")
        self.window.annotation_editing.set_pending(
            "Move box",
            lambda: self.window.annotation_editing.cancel_edit(
                restore=True
            ),
        )

        self.window.set_selected_review_state("verified")

        self.assertFalse(self.window.annotation_editing.pending)
        self.assertFalse(self.window.annotation_editing.edit_open)
        root = ElementTree.parse(
            os.path.join(self.annotation_dir, "01_blank.xml")
        ).getroot()
        self.assertEqual(root.attrib.get("verified"), "yes")

    def test_canceling_batch_review_confirmation_preserves_pending_edit(self):
        self.item(0).setSelected(True)
        self.item(1).setSelected(True)
        self.window.annotation_editing.begin_edit("Move box")
        self.window.annotation_editing.set_pending(
            "Move box",
            lambda: self.window.annotation_editing.cancel_edit(
                restore=True
            ),
        )

        with patch(
            "labelimg.app.localized_question",
            return_value=QMessageBox.No,
        ):
            self.window.set_selected_review_state("verified")

        self.assertTrue(self.window.annotation_editing.pending)
        self.assertTrue(self.window.annotation_editing.edit_open)
        self.window.annotation_editing.cancel_pending_operation()

    def test_batch_review_preserves_the_active_yolo_format(self):
        self.window.set_annotation_format(AnnotationFormat.YOLO)
        self.assertEqual(self.window.actions.save_format.text(), FORMAT_YOLO)
        self.item(0).setSelected(True)

        self.window.set_selected_review_state("questioned")

        yolo_path = os.path.join(self.annotation_dir, "01_blank.txt")
        self.assertTrue(os.path.isfile(yolo_path))
        self.assertFalse(
            os.path.exists(os.path.join(self.annotation_dir, "01_blank.xml"))
        )
        loaded = AnnotationDocument.load(
            yolo_path,
            self.image_paths[0],
            QImage(self.image_paths[0]),
        )
        self.assertTrue(loaded.questioned)

    def test_batch_review_rebases_an_inactive_dirty_history(self):
        self.assertTrue(self.window.load_file(self.image_paths[1]))
        self.add_rectangle()
        self.assertTrue(
            self.window.annotation_editing.view_image(
                self.image_paths[1], touch=False
            ).dirty
        )
        self.assertTrue(self.window.load_file(self.image_paths[0]))
        self.item(1).setSelected(True)

        self.window.set_selected_review_state("verified")

        view = self.window.annotation_editing.view_image(
            self.image_paths[1], touch=False
        )
        self.assertTrue(view.snapshot.verified)
        self.assertFalse(view.dirty)
        self.assertFalse(view.can_undo)

    def test_review_recovery_captures_rollback_bytes_under_resource_lease(self):
        annotation_path = os.path.join(
            self.annotation_dir, "02_annotated.xml"
        )
        coordinator = self.window.annotation_workspace.storage_coordinator
        real_lease = coordinator.lease
        leased_bytes = []

        @contextmanager
        def tracked_lease(resources):
            with real_lease(resources):
                root = ElementTree.parse(annotation_path).getroot()
                root.set("leased-version", "preserve")
                ElementTree.ElementTree(root).write(
                    annotation_path,
                    encoding="utf-8",
                    xml_declaration=True,
                )
                with open(annotation_path, "rb") as source:
                    leased_bytes.append(source.read())
                yield

        change = ReviewRecoveryRecord(
            image_path=self.image_paths[1],
            prior_verified=True,
            prior_questioned=False,
            result_verified=False,
            result_questioned=False,
            annotation_path=annotation_path,
        )
        with patch.object(coordinator, "lease", tracked_lease):
            with self.assertRaises(FileRecoveryError):
                self.window.review_state_transaction.recover((change,))

        with open(annotation_path, "rb") as source:
            self.assertEqual(source.read(), leased_bytes[0])

    def test_review_recovery_rechecks_review_fields_inside_resource_lease(self):
        annotation_path = os.path.join(
            self.annotation_dir, "02_annotated.xml"
        )
        coordinator = self.window.annotation_workspace.storage_coordinator
        real_lease = coordinator.lease

        @contextmanager
        def change_after_lock(resources):
            with real_lease(resources):
                root = ElementTree.parse(annotation_path).getroot()
                root.set("verified", "no")
                root.set("questioned", "yes")
                ElementTree.ElementTree(root).write(
                    annotation_path,
                    encoding="utf-8",
                    xml_declaration=True,
                )
                yield

        change = ReviewRecoveryRecord(
            image_path=self.image_paths[1],
            prior_verified=True,
            prior_questioned=False,
            result_verified=False,
            result_questioned=False,
            annotation_path=annotation_path,
        )
        with patch.object(coordinator, "lease", change_after_lock):
            with self.assertRaises(FileRecoveryError):
                self.window.review_state_transaction.recover((change,))

        loaded = AnnotationDocument.load(
            annotation_path,
            self.image_paths[1],
            QImage(self.image_paths[1]),
        )
        self.assertTrue(loaded.questioned)

    def test_review_recovery_rolls_back_earlier_ordinary_write(self):
        first_path = os.path.join(
            self.annotation_dir, "02_annotated.xml"
        )
        second_path = os.path.join(
            self.annotation_dir, "04_questioned.xml"
        )
        with open(first_path, "rb") as source:
            first_before = source.read()
        with open(second_path, "rb") as source:
            second_before = source.read()
        real_save = self.window.annotation_workspace.save
        calls = [0]

        def fail_second_save(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError("second review save failed")
            return real_save(*args, **kwargs)

        changes = (
            ReviewRecoveryRecord(
                image_path=self.image_paths[1],
                prior_verified=True,
                prior_questioned=False,
                result_verified=False,
                result_questioned=False,
                annotation_path=first_path,
            ),
            ReviewRecoveryRecord(
                image_path=self.image_paths[3],
                prior_verified=False,
                prior_questioned=False,
                result_verified=False,
                result_questioned=True,
                annotation_path=second_path,
            ),
        )
        with patch.object(
            self.window.annotation_workspace,
            "save",
            side_effect=fail_second_save,
        ):
            with self.assertRaises(FileRecoveryError):
                self.window.review_state_transaction.recover(changes)

        with open(first_path, "rb") as source:
            self.assertEqual(source.read(), first_before)
        with open(second_path, "rb") as source:
            self.assertEqual(source.read(), second_before)

    def test_review_recovery_rolls_back_a_save_that_raises_after_commit(self):
        annotation_path = os.path.join(
            self.annotation_dir, "02_annotated.xml"
        )
        with open(annotation_path, "rb") as source:
            before = source.read()
        real_save = self.window.annotation_workspace.save

        def save_then_raise(*args, **kwargs):
            real_save(*args, **kwargs)
            raise RuntimeError("post-commit bookkeeping failed")

        change = ReviewRecoveryRecord(
            image_path=self.image_paths[1],
            prior_verified=True,
            prior_questioned=False,
            result_verified=False,
            result_questioned=False,
            annotation_path=annotation_path,
        )
        with patch.object(
            self.window.annotation_workspace,
            "save",
            side_effect=save_then_raise,
        ):
            with self.assertRaises(FileRecoveryError):
                self.window.review_state_transaction.recover((change,))

        with open(annotation_path, "rb") as source:
            self.assertEqual(source.read(), before)

    def test_review_recovery_restores_missing_empty_pascal_document(self):
        self.item(0).setSelected(True)
        self.window.set_selected_review_state("verified")
        self.window.set_selected_review_state("unreviewed")
        annotation_path = os.path.join(
            self.annotation_dir, "01_blank.xml"
        )
        self.assertFalse(os.path.exists(annotation_path))

        self.window.review_state_transaction.recover(
            (
                ReviewRecoveryRecord(
                    image_path=self.image_paths[0],
                    prior_verified=True,
                    prior_questioned=False,
                    result_verified=False,
                    result_questioned=False,
                    annotation_path=annotation_path,
                ),
            )
        )

        loaded = AnnotationDocument.load(
            annotation_path,
            self.image_paths[0],
            QImage(self.image_paths[0]),
        )
        self.assertTrue(loaded.verified)

    def test_review_recovery_retains_later_dirty_candidate_override(self):
        self.item(1).setSelected(True)
        self.window.set_selected_review_state("verified")
        self.assertTrue(self.window.load_file(self.image_paths[1]))
        shape = Shape(label="later-unsaved")
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
        annotation_path = os.path.join(
            self.annotation_dir, "02_annotated.xml"
        )

        self.window.review_state_transaction.recover(
            (
                ReviewRecoveryRecord(
                    image_path=self.image_paths[1],
                    prior_verified=False,
                    prior_questioned=False,
                    result_verified=True,
                    result_questioned=False,
                    annotation_path=annotation_path,
                ),
            )
        )

        view = self.window.annotation_editing.view_image(
            self.image_paths[1], touch=False
        )
        self.assertTrue(view.dirty)
        self.assertIn(
            "later-unsaved",
            self.window.annotation_workspace.candidate_labels,
        )

    def test_opening_next_annotated_image_starts_without_selection(self):
        self.window.open_next_image()
        self.app.processEvents()

        self.assertEqual(self.window.file_path, self.image_paths[1])
        self.assertEqual(self.window.label_list.selected_shapes(), ())
        self.assertIsNone(self.window.label_list.active_shape())
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
            self.display_paths[0],
        )
        self.assertEqual(self.item(1).text(), self.display_paths[1])
        self.assertEqual(self.item(2).text(), self.display_paths[2])
        self.assertEqual(self.item(3).text(), self.display_paths[3])

    def test_status_updates_after_save_verify_and_delete(self):
        shape = self.add_rectangle()
        self.window.save_file()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0],
        )

        self.window.question_image()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0],
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
            self.display_paths[0],
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
            self.display_paths[0],
        )
        self.assertTrue(self.window.canvas.questioned)
        self.assertFalse(self.window.canvas.verified)

        self.window.question_image()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0],
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
            self.display_paths[0],
        )
        self.window.verify_image()
        self.assertEqual(
            self.item(0).text(),
            self.display_paths[0],
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
