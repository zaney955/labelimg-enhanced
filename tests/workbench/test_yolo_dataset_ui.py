"""Workbench entry points for nested YOLO datasets."""

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent
from PyQt5.QtGui import QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language


class YoloDatasetUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.images = self.root / "photos"
        self.labels = self.root / "labels"
        for split, class_id in [("train", 2), ("val", 1)]:
            directory = self.images / split
            directory.mkdir(parents=True)
            image = QImage(100, 100, QImage.Format_RGB32)
            image.fill(0)
            image.save(str(directory / "sample.png"))
            directory = self.labels / split
            directory.mkdir(parents=True)
            (directory / "sample.txt").write_text(
                f"{class_id} 0.5 0.5 0.2 0.2\n", encoding="utf8"
            )
        (self.root / "data.yaml").write_text(
            "names: [zero, one, two, three]\n", encoding="utf8"
        )
        (self.labels / "classes.txt").write_text("", encoding="utf8")
        self.environment = patch.dict(
            os.environ, {"LABELIMG_CONFIG_DIR": str(self.root / "settings")}
        )
        self.environment.start()
        self.window = create_workbench(
            WorkbenchLaunchOptions(
                class_file=str(self.labels / "classes.txt"), save_dir=str(self.labels)
            )
        )

    def tearDown(self):
        set_language(ENGLISH)
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()

    def unusual_mapping(self, filename="classes.txt"):
        (self.root / "data.yaml").unlink()
        path = (
            self.root / filename
            if filename == "classes.txt"
            else self.labels / filename
        )
        content = (
            "zero\none\ntwo\nthree\n"
            if filename == "classes.txt"
            else "names: [zero, one, two, three]\n"
        )
        path.write_text(content, encoding="utf8")
        return path

    def test_nonstandard_class_mapping_confirmation_is_shared_across_navigation(self):
        mapping = self.unusual_mapping()
        set_language(SIMPLIFIED_CHINESE)
        with patch(
            "labelimg.workbench.main_window.localized_question",
            return_value=QMessageBox.Yes,
        ) as prompt:
            self.window.import_dir_images(str(self.images))
            self.assertEqual([s.label for s in self.window.canvas.shapes], ["two"])
            self.assertTrue(self.window.load_file(str(self.images / "val/sample.png")))
        self.assertEqual(prompt.call_count, 1)
        self.assertIn(str(mapping), prompt.call_args.args[2])
        self.assertIn("0: zero", prompt.call_args.args[2])
        self.assertIn("确认类别映射", prompt.call_args.args[1])

    def test_cancel_nonstandard_mapping_keeps_previous_workspace_and_canvas(self):
        self.window.default_save_dir = None
        self.window.import_dir_images(str(self.images))
        mapping = self.unusual_mapping("data.yaml")
        previous = self.window.annotation_workspace
        with patch(
            "labelimg.workbench.main_window.localized_question",
            return_value=QMessageBox.Cancel,
        ) as prompt:
            with patch.object(self.window, "error_message") as error:
                self.assertFalse(
                    self.window._switch_annotation_directory(str(self.labels))
                )
        self.assertIs(self.window.annotation_workspace, previous)
        self.assertIsNone(self.window.default_save_dir)
        self.assertEqual(self.window.canvas.shapes, [])
        error.assert_not_called()
        self.assertIn(str(mapping), prompt.call_args.args[2])

    def test_cancel_opening_another_dataset_preserves_current_image(self):
        self.window.import_dir_images(str(self.images))
        self.window.default_save_dir = None
        old_workspace = self.window.annotation_workspace
        old_path = self.window.file_path
        other = self.root / "other"
        images = other / "images/train"
        labels = other / "labels/train"
        images.mkdir(parents=True)
        labels.mkdir(parents=True)
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(0)
        image.save(str(images / "another.png"))
        (images / "another.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf8")
        (other / "classes.txt").write_text("other\n", encoding="utf8")
        for background in (False, True):
            with self.subTest(background=background):
                with patch(
                    "labelimg.workbench.main_window.localized_question",
                    return_value=QMessageBox.Cancel,
                ) as prompt:
                    result = (
                        self.window.commit_discovered_directory(
                            str(other / "images"), [str(images / "another.png")]
                        )
                        if background
                        else self.window.import_dir_images(str(other / "images"))
                    )
                self.assertFalse(result)
                self.assertEqual(prompt.call_count, 1)
                self.assertIs(self.window.annotation_workspace, old_workspace)
                self.assertEqual(self.window.file_path, old_path)
                self.assertEqual([s.label for s in self.window.canvas.shapes], ["two"])

    def test_background_nonstandard_mapping_prompts_once_on_ui_thread(self):
        from PyQt5.QtCore import QThread

        self.unusual_mapping()
        threads = []

        def approve(*_args):
            threads.append(QThread.currentThread())
            return QMessageBox.Yes

        with patch(
            "labelimg.workbench.main_window.localized_question", side_effect=approve
        ) as prompt:
            self.assertTrue(self.window.start_directory_load(str(self.images)))
            deadline = time.monotonic() + 10
            while (
                not self.window.file_path
                or self.window._directory_load_jobs
                or self.window._directory_projection_pending
            ) and time.monotonic() < deadline:
                QTest.qWait(10)
        self.assertEqual(prompt.call_count, 1)
        self.assertEqual(threads, [self.app.thread()])
        self.assertEqual([s.label for s in self.window.canvas.shapes], ["two"])

    def test_changed_nonstandard_mapping_requires_confirmation_again(self):
        mapping = self.unusual_mapping()
        with patch(
            "labelimg.workbench.main_window.localized_question",
            return_value=QMessageBox.Yes,
        ):
            self.window.import_dir_images(str(self.images))
        previous_labels = self.window.annotation_workspace.candidate_labels
        mapping.write_text("zero\nchanged-one\nchanged-two\nthree\n", encoding="utf8")
        with patch(
            "labelimg.workbench.main_window.localized_question",
            return_value=QMessageBox.Cancel,
        ) as prompt:
            self.window._process_external_annotation_change()
        self.assertEqual(prompt.call_count, 1)
        self.assertEqual([s.label for s in self.window.canvas.shapes], ["two"])

        self.assertEqual(
            self.window.annotation_workspace.candidate_labels, previous_labels
        )

    def test_synchronous_open_and_navigation_keep_split_identity(self):
        self.window.import_dir_images(str(self.images))
        self.assertEqual([s.label for s in self.window.canvas.shapes], ["two"])
        self.assertTrue(self.window.load_file(str(self.images / "val/sample.png")))
        self.assertEqual([s.label for s in self.window.canvas.shapes], ["one"])
        watched = self.window._annotation_file_watcher.files()
        self.assertIn(str(self.root / "data.yaml"), watched)

    def test_background_open_uses_same_relative_mapping(self):
        self.assertTrue(self.window.start_directory_load(str(self.images)))
        deadline = time.monotonic() + 10
        while (
            not self.window.file_path
            or self.window._directory_load_jobs
            or self.window._directory_projection_pending
        ) and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(self.window._directory_load_jobs)
        self.assertEqual([s.label for s in self.window.canvas.shapes], ["two"])
        self.assertEqual(
            self.window.annotation_workspace.candidate_labels, ("one", "two")
        )

    def test_switch_directory_prompts_for_competing_flat_annotation(self):
        self.window.default_save_dir = None
        self.window.import_dir_images(str(self.images))
        (self.labels / "sample.txt").write_text(
            "# labelimg-review: unreviewed\n", encoding="utf8"
        )

        def choose(_parent, _title, _prompt, items, *_args):
            return items[0], True

        with patch(
            "labelimg.workbench.main_window.QInputDialog.getItem", side_effect=choose
        ) as prompt:
            self.assertTrue(self.window._switch_annotation_directory(str(self.labels)))
        self.assertEqual(prompt.call_count, 1)
        self.assertEqual([s.label for s in self.window.canvas.shapes], ["two"])

    def test_shared_yaml_change_refreshes_current_and_inactive_labels(self):
        self.window.import_dir_images(str(self.images))
        self.assertEqual(
            self.window.annotation_workspace.candidate_labels, ("one", "two")
        )
        (self.root / "data.yaml").write_text(
            "names: [zero, changed-one, changed-two, three]\n", encoding="utf8"
        )
        self.window._process_external_annotation_change()
        self.assertEqual([s.label for s in self.window.canvas.shapes], ["changed-two"])
        self.assertEqual(
            self.window.annotation_workspace.candidate_labels,
            ("changed-one", "changed-two"),
        )

    def annotation_icons(self):
        from labelimg.files.ui.list_widget import FILE_ANNOTATION_STATE_ROLE

        return [
            self.window.file_list_widget.item(index).data(FILE_ANNOTATION_STATE_ROLE)
            for index in range(self.window.file_list_widget.count())
        ]

    def test_restoring_mapping_and_reopening_same_annotation_directory_refreshes_all_icons(
        self,
    ):
        mapping = self.root / "data.yaml"
        original = mapping.read_bytes()
        mapping.unlink()
        with patch.object(self.window, "error_message") as error:
            self.window.import_dir_images(str(self.images))
        self.assertTrue(error.called)
        self.assertEqual(self.annotation_icons(), ["unannotated", "unannotated"])
        mapping.write_bytes(original)
        with patch(
            "labelimg.workbench.main_window.QFileDialog.getExistingDirectory",
            return_value=str(self.labels),
        ):
            self.window.change_save_dir_dialog()
        self.assertEqual(self.annotation_icons(), ["annotated", "annotated"])

    def test_background_reopening_same_directory_after_mapping_recovery_refreshes_all_icons(
        self,
    ):
        mapping = self.root / "data.yaml"
        original = mapping.read_bytes()
        mapping.unlink()
        with patch.object(self.window, "error_message") as error:
            self.window.import_dir_images(str(self.images))
        self.assertTrue(error.called)
        self.assertEqual(self.annotation_icons(), ["unannotated", "unannotated"])
        mapping.write_bytes(original)
        with patch(
            "labelimg.workbench.main_window.QFileDialog.getExistingDirectory",
            return_value=str(self.labels),
        ):
            with patch.object(self.window, "isVisible", return_value=True):
                self.window.change_save_dir_dialog()
        deadline = time.monotonic() + 10
        while self.window._directory_load_jobs and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(self.window._directory_load_jobs)
        self.assertEqual(self.annotation_icons(), ["annotated", "annotated"])
        self.assertEqual([shape.label for shape in self.window.canvas.shapes], ["two"])

    def test_same_directory_refresh_preserves_dirty_annotations_and_history(self):
        self.window.import_dir_images(str(self.images))
        self.window.auto_saving.setChecked(False)
        with patch.object(
            self.window, "_choose_annotation_label", return_value=("local-edit", False)
        ):
            self.window.edit_shape_label(self.window.canvas.shapes[0])
        view = self.window.annotation_editing.view
        self.assertTrue(view.dirty)
        self.assertTrue(view.can_undo)
        workspace = self.window.annotation_workspace
        shape = self.window.canvas.shapes[0]
        with patch(
            "labelimg.workbench.main_window.QFileDialog.getExistingDirectory",
            return_value=str(self.labels),
        ):
            with patch.object(self.window, "may_continue") as guard:
                self.window.change_save_dir_dialog()
        guard.assert_not_called()
        self.assertIs(self.window.annotation_workspace, workspace)
        self.assertEqual(self.window.annotation_editing.view, view)
        self.assertIs(self.window.canvas.shapes[0], shape)
        self.assertFalse(self.window.auto_saving.isChecked())
        self.assertEqual(self.annotation_icons(), ["annotated", "annotated"])

    def test_restoring_classes_file_refreshes_all_icons(self):
        (self.root / "data.yaml").unlink()
        mapping = self.labels / "classes.txt"
        content = "zero\none\ntwo\nthree\n"
        mapping.unlink()
        with patch.object(self.window, "error_message") as error:
            self.window.import_dir_images(str(self.images))
        self.assertTrue(error.called)
        self.assertEqual(self.annotation_icons(), ["unannotated", "unannotated"])
        mapping.write_text(content, encoding="utf8")
        with patch(
            "labelimg.workbench.main_window.QFileDialog.getExistingDirectory",
            return_value=str(self.labels),
        ):
            self.window.change_save_dir_dialog()
        self.assertEqual(self.annotation_icons(), ["annotated", "annotated"])
        self.assertEqual([shape.label for shape in self.window.canvas.shapes], ["two"])

    def test_background_same_directory_refresh_preserves_dirty_history(self):
        self.window.import_dir_images(str(self.images))
        self.window.auto_saving.setChecked(False)
        with patch.object(
            self.window, "_choose_annotation_label", return_value=("local-edit", False)
        ):
            self.window.edit_shape_label(self.window.canvas.shapes[0])
        view = self.window.annotation_editing.view
        self.assertTrue(view.dirty)
        workspace = self.window.annotation_workspace
        with patch.object(self.window, "may_continue") as guard:
            self.assertTrue(
                self.window.start_annotation_directory_load(str(self.labels))
            )
            deadline = time.monotonic() + 10
            while self.window._directory_load_jobs and time.monotonic() < deadline:
                QTest.qWait(10)
        self.assertFalse(self.window._directory_load_jobs)
        guard.assert_not_called()
        self.assertIs(self.window.annotation_workspace, workspace)
        self.assertEqual(self.window.annotation_editing.view, view)
        self.assertFalse(self.window.auto_saving.isChecked())
        self.assertEqual(
            [shape.label for shape in self.window.canvas.shapes], ["local-edit"]
        )

    def test_restoring_mapping_and_switching_annotation_directory_refreshes_all_icons(
        self,
    ):
        self.window.default_save_dir = None
        self.window.import_dir_images(str(self.images))
        mapping = self.root / "data.yaml"
        original = mapping.read_bytes()
        mapping.unlink()
        with patch.object(self.window, "error_message") as error:
            self.assertFalse(self.window._switch_annotation_directory(str(self.labels)))
        self.assertTrue(error.called)
        mapping.write_bytes(original)
        self.assertTrue(self.window._switch_annotation_directory(str(self.labels)))
        self.assertEqual(self.annotation_icons(), ["annotated", "annotated"])

    def test_missing_mapping_dialog_lists_paths_in_both_languages(self):
        from html import escape

        self.window.default_save_dir = None
        self.window.import_dir_images(str(self.images))
        (self.root / "data.yaml").unlink()
        for language, heading in [
            (SIMPLIFIED_CHINESE, "缺少 YOLO 类别映射"),
            (ENGLISH, "Missing YOLO class mapping"),
        ]:
            with self.subTest(language=language):
                set_language(language)
                with patch.object(self.window, "error_message") as dialog:
                    self.assertFalse(
                        self.window._switch_annotation_directory(str(self.labels))
                    )
                message = dialog.call_args.args[1]
                self.assertIn(heading, message)
                self.assertIn(escape(str(self.labels / "train/classes.txt")), message)
                self.assertIn(escape(str(self.labels / "classes.txt")), message)
                self.assertIn(escape(str(self.root / "data.yaml")), message)
                self.assertIn("<br>", message)
                self.assertIsNone(self.window.default_save_dir)

    def test_out_of_range_dialog_reports_line_source_and_valid_ids(self):
        self.window.default_save_dir = None
        self.window.import_dir_images(str(self.images))
        mapping = self.labels / "train/classes.txt"
        mapping.write_text("zero\none\n", encoding="utf8")
        (self.labels / "train/sample.txt").write_text(
            "# comment\n\n3 0.5 0.5 0.2 0.2\n", encoding="utf8"
        )
        set_language(SIMPLIFIED_CHINESE)
        with patch.object(self.window, "error_message") as dialog:
            self.assertFalse(self.window._switch_annotation_directory(str(self.labels)))
        message = dialog.call_args.args[1]
        self.assertIn("YOLO 类别编号超出范围", message)
        self.assertIn("第 3 行的类别编号为 3", message)
        self.assertIn("2 个类别", message)
        self.assertIn("0-1", message)
        self.assertIn(str(mapping), message)


if __name__ == "__main__":
    unittest.main()
