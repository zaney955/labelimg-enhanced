import os
import tempfile
import time
import unittest
from threading import Event
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEventLoop, QTimer, Qt
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication

from labelimg.annotations import AnnotationWorkspace
from labelimg.files.application.operations import FileOperationError
from labelimg.files.ui.list_widget import (
    FILE_ANNOTATION_STATE_ROLE,
    FILE_REVIEW_STATE_ROLE,
)
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class DirectoryLoadingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": self.temporary.name})
        self.environment.start()
        classes = os.path.join(self.temporary.name, "classes.txt")
        with open(classes, "w", encoding="utf-8"):
            pass
        self.window = create_workbench(
            WorkbenchLaunchOptions(class_file=classes, save_dir="")
        )

    def tearDown(self):
        self.window.stop_directory_load()
        deadline = time.monotonic() + 5
        while self.window._directory_load_jobs and time.monotonic() < deadline:
            self.app.processEvents()
        self.window.deleteLater()
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()

    def directory(self, name, image_name):
        directory = os.path.join(self.temporary.name, name)
        os.makedirs(directory)
        path = os.path.join(directory, image_name)
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(path))
        return directory, os.path.abspath(path)

    def wait_until(self, predicate, timeout_ms=5000):
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        timer.start()
        deadline.start(timeout_ms)
        loop.exec_()
        timer.stop()
        self.assertTrue(predicate())

    def test_superseded_generation_cannot_replace_newer_directory(self):
        first, _first_path = self.directory("first", "first.png")
        second, second_path = self.directory("second", "second.png")

        self.window.start_directory_load(first)
        self.window.start_directory_load(second)
        self.wait_until(
            lambda: not self.window._directory_load_jobs
            and self.window.file_path == second_path
        )

        self.assertEqual(self.window.dir_name, second)
        self.assertEqual(self.window.m_img_list, [second_path])

    def image_batch(self, count=117):
        directory, _ = self.directory("batch", "image000.png")
        paths = [
            os.path.abspath(os.path.join(directory, "image%03d.png" % index))
            for index in range(count)
        ]
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(QColor("white"))
        for path in paths[1:]:
            self.assertTrue(image.save(path))

        return directory, paths

    def test_ready_directory_keeps_full_count_and_navigation_order(self):
        directory, paths = self.image_batch(65)
        self.window._ensure_directory_loading()
        self.window._directory_paths_discovered(
            self.window._directory_load_generation, directory, 0, paths
        )

        self.assertEqual(self.window.img_count, 65)
        self.assertEqual(self.window.m_img_list, paths)
        self.assertEqual(self.window.counter_str(), "[1 / 65]")
        self.window.open_next_image()
        self.assertEqual(self.window.file_path, paths[1])
        self.assertEqual(self.window.counter_str(), "[2 / 65]")
        self.wait_until(lambda: not self.window._directory_pending_paths)
        self.assertEqual(self.window.m_img_list, paths)

    def test_completed_index_updates_every_row_after_early_navigation(self):
        directory, paths = self.image_batch()
        annotation_directory = os.path.join(self.temporary.name, "xml")
        os.makedirs(annotation_directory)
        annotated = set(paths[82:])
        for path in annotated:
            annotation_path = os.path.join(
                annotation_directory, os.path.splitext(os.path.basename(path))[0] + ".xml"
            )
            with open(annotation_path, "w", encoding="utf-8") as stream:
                stream.write(
                    "<annotation verified='yes'><filename>%s</filename>"
                    "<object><name>part</name><bndbox><xmin>1</xmin>"
                    "<ymin>1</ymin><xmax>4</xmax><ymax>4</ymax>"
                    "</bndbox></object></annotation>" % os.path.basename(path)
                )
        self.assertTrue(self.window._switch_annotation_directory(annotation_directory))
        workspace = AnnotationWorkspace(
            image_dir=directory, save_dir=annotation_directory
        )
        workspace.scan(annotation_directory)
        self.window._ensure_directory_loading()
        generation = self.window._directory_load_generation
        self.window._directory_paths_discovered(generation, directory, 0, paths)
        self.window.open_next_image()
        self.window._directory_index_completed(generation, workspace)
        self.wait_until(lambda: self.window.file_list_controls.index_complete)

        self.assertEqual(self.window.img_count, 117)
        self.assertEqual(self.window.file_path, paths[1])
        self.assertEqual(self.window.cur_img_idx, 1)
        for row, path in enumerate(paths):
            item = self.window.file_list_widget.item(row)
            self.assertEqual(item.data(Qt.UserRole), path)
            self.assertEqual(self.window._file_row_by_path[path], row)
            self.assertEqual(
                item.data(FILE_ANNOTATION_STATE_ROLE),
                "annotated" if path in annotated else "unannotated",
            )
            self.assertEqual(
                item.data(FILE_REVIEW_STATE_ROLE),
                "verified" if path in annotated else "unreviewed",
            )

    def test_double_click_late_row_keeps_image_selection_and_scroll(self):
        directory, paths = self.image_batch()
        self.window.start_directory_load(directory)
        self.wait_until(
            lambda: self.window.dir_name == directory
            and not self.window._directory_load_jobs
            and not self.window._directory_projection_pending
        )
        self.assert_late_row_double_click(paths)

    def test_double_click_late_row_before_index_completion(self):
        directory, paths = self.image_batch()
        self.window._ensure_directory_loading()
        self.window._directory_paths_discovered(
            self.window._directory_load_generation, directory, 0, paths
        )
        self.wait_until(lambda: not self.window._directory_pending_paths)
        self.assertFalse(self.window.file_list_controls.index_complete)
        self.assert_late_row_double_click(paths)

    def assert_late_row_double_click(self, paths):
        self.window.show()
        self.app.processEvents()
        view = self.window.file_list_widget
        target = view.item(105)
        view.scrollToItem(target)
        self.app.processEvents()
        point = view.visualItemRect(target).center()
        self.assertIs(view.itemAt(point), target)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self.wait_until(lambda: not view._preserved_selection_timer.isActive())
        self.assertEqual(
            [item.data(Qt.UserRole) for item in view.selectedItems()],
            [paths[105]],
        )
        resets = QSignalSpy(view.model().modelReset)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self.app.processEvents()

        self.assertEqual(self.window.file_path, paths[105])
        self.assertEqual(len(resets), 0, "opening an image must not rebuild unchanged rows")
        self.assertEqual(self.window.cur_img_idx, 105)
        self.assertEqual(self.window.selected_file_paths(), [paths[105]])
        self.assertTrue(view.viewport().rect().intersects(view.visualItemRect(target)))
        self.assertEqual(self.window.counter_str(), "[106 / 117]")
        self.assertEqual(self.window.top_commands.counter_label.text(), "106 / 117")

    def test_navigation_can_cross_unpublished_rows(self):
        directory, paths = self.image_batch()
        self.window._ensure_directory_loading()
        self.window._directory_paths_discovered(
            self.window._directory_load_generation, directory, 63, paths
        )
        self.assertEqual(self.window.file_list_widget.count(), 64)
        self.window.open_next_image()
        self.assertEqual(self.window.file_path, paths[64])
        self.assertEqual(self.window.counter_str(), "[65 / 117]")
        self.assertEqual(self.window.top_commands.counter_label.text(), "65 / 117")
        self.wait_until(lambda: not self.window._directory_pending_paths)
        self.assertEqual(self.window.m_img_list, paths)

    def test_search_for_unpublished_image_preserves_complete_workspace(self):
        directory, paths = self.image_batch()
        self.window._ensure_directory_loading()
        self.window._directory_paths_discovered(
            self.window._directory_load_generation, directory, 0, paths
        )
        self.window.file_list_controls.search_edit.setText("image105")
        self.assertEqual(self.window.m_img_list, paths)
        self.assertEqual(self.window.img_count, 117)
        self.wait_until(lambda: not self.window._directory_pending_paths)
        self.assertEqual(self.window.visible_file_paths(), [paths[105]])
        self.window.open_first_image_search_result()
        self.assertEqual(self.window.file_path, paths[105])
        self.assertEqual(self.window.counter_str(), "[106 / 117]")

    def test_sort_during_publication_preserves_row_path_mapping(self):
        directory, paths = self.image_batch()
        self.window._ensure_directory_loading()
        self.window._directory_paths_discovered(
            self.window._directory_load_generation, directory, 0, paths
        )
        self.window.file_list_controls.state.descending = True
        self.window.apply_file_list_view()
        self.wait_until(lambda: not self.window._directory_pending_paths)
        ordered = list(reversed(paths))
        self.assertEqual(self.window.m_img_list, ordered)
        self.assertEqual(self.window.img_count, 117)
        for row, path in enumerate(ordered):
            self.assertEqual(
                self.window.file_list_widget.item(row).data(Qt.UserRole), path
            )
            self.assertEqual(self.window._file_row_by_path[path], row)
        self.window.open_file_list_path(paths[106])
        self.window.open_next_image()
        self.assertEqual(self.window.file_path, paths[105])


    def annotation_sorted_directory(self):
        directory, paths = self.image_batch()
        for path in paths[81:]:
            with open(os.path.splitext(path)[0] + ".xml", "w", encoding="utf-8") as stream:
                stream.write(
                    "<annotation><filename>%s</filename><object><name>part</name><bndbox>"
                    "<xmin>1</xmin><ymin>1</ymin><xmax>4</xmax><ymax>4</ymax>"
                    "</bndbox></object></annotation>" % os.path.basename(path)
                )
        self.window.file_list_controls.state.sort_key = "annotation"
        self.window.file_list_controls.state.descending = True
        return directory, paths

    def wait_for_directory_index(self, directory):
        self.wait_until(
            lambda: self.window.dir_name == directory
            and not self.window._directory_load_jobs
            and not self.window._directory_projection_pending
        )

    def test_initial_counter_matches_image_after_status_sort(self):
        directory, _ = self.annotation_sorted_directory()
        self.window.start_directory_load(directory)
        self.wait_for_directory_index(directory)
        row = self.window.m_img_list.index(self.window.file_path)
        expected = "[%d / 117]" % (row + 1)
        self.assertEqual(self.window.counter_str(), expected)
        self.assertEqual(self.window.top_commands.counter_label.text(), "%d / 117" % (row + 1))
        self.assertTrue(self.window.windowTitle().endswith(expected), self.window.windowTitle())

    def test_default_open_uses_first_image_in_selected_sort_order(self):
        directory, paths = self.annotation_sorted_directory()
        self.window.start_directory_load(directory)
        self.wait_for_directory_index(directory)
        self.assertEqual(self.window.m_img_list[0], paths[81])
        self.assertEqual(self.window.file_path, self.window.m_img_list[0])
        self.assertEqual(self.window.cur_img_idx, 0)
        self.assertEqual(self.window.counter_str(), "[1 / 117]")


    def test_index_completion_preserves_manual_navigation_and_updates_title(self):
        directory, paths = self.annotation_sorted_directory()
        workspace = AnnotationWorkspace(image_dir=directory)
        workspace.scan(directory)
        self.window._ensure_directory_loading()
        generation = self.window._directory_load_generation
        self.window._directory_paths_discovered(generation, directory, 0, paths)
        self.window.open_next_image()
        self.assertEqual(self.window.file_path, paths[1])
        self.window._directory_index_completed(generation, workspace)
        self.wait_until(lambda: self.window.file_list_controls.index_complete)
        self.assertEqual(self.window.file_path, paths[1])
        self.assertEqual(self.window.counter_str(), "[38 / 117]")
        self.assertTrue(self.window.windowTitle().endswith("[38 / 117]"))

    def test_superseded_publication_callbacks_cannot_complete_new_index(self):
        directory, paths = self.image_batch()
        self.window._ensure_directory_loading()
        generation = self.window._directory_load_generation
        self.window._directory_paths_discovered(generation, directory, 0, paths)
        workspace = AnnotationWorkspace(image_dir=directory)
        workspace.scan(directory)
        self.window._directory_index_completed(generation, workspace)
        self.window.stop_directory_load()
        second, second_path = self.directory("second", "only.png")
        generation = self.window._directory_load_generation
        self.window._directory_paths_discovered(generation, second, 0, [second_path])
        self.app.processEvents()
        self.assertEqual(self.window.m_img_list, [second_path])
        self.assertEqual(self.window.file_path, second_path)
        self.assertFalse(self.window.file_list_controls.index_complete)


    def test_failed_rename_does_not_cancel_an_unfinished_directory(self):
        directory, paths = self.image_batch()
        self.window._ensure_directory_loading()
        generation = self.window._directory_load_generation
        self.window._directory_paths_discovered(generation, directory, 0, paths)
        with patch.object(self.window.file_operations, "execute", side_effect=FileOperationError("blocked")), patch(
            "labelimg.files.ui.controller.localized_warning"
        ):
            self.window.execute_file_rename({paths[0]: os.path.join(directory, "renamed.png")})
        self.assertEqual(self.window._directory_load_generation, generation)
        self.wait_until(lambda: self.window.file_list_widget.count() == len(paths))
        self.assertEqual(self.window.m_img_list, paths)


    def test_directory_job_remains_owned_until_its_thread_has_finished(self):
        directory, _ = self.directory("thread-lifetime", "image.png")
        emitted, released = Event(), Event()
        self.window.start_directory_load(directory)
        generation = self.window._directory_load_generation
        thread, worker = self.window._directory_load_jobs[generation]
        def hold_worker_after_completion(_generation):
            emitted.set()
            released.wait(5)
        worker.finished.connect(hold_worker_after_completion, Qt.DirectConnection)
        try:
            self.wait_until(emitted.is_set)
            self.assertTrue(thread.isRunning())
            self.assertIn(generation, self.window._directory_load_jobs)
        finally:
            released.set()
            thread.quit()
            thread.wait(5000)
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
