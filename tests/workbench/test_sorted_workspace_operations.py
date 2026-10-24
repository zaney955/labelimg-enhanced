import os
import shutil
import tempfile
import time
import unittest
from types import SimpleNamespace
from threading import Event
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QThread, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from labelimg.annotations import AnnotationWorkspace
from labelimg.platform.recovery import TrashIdentity
from labelimg.files.ui.list_widget import FILE_ANNOTATION_STATE_ROLE, FILE_REVIEW_STATE_ROLE, CURRENT_IMAGE_ROLE
from labelimg.image_tools.domain.quality import ImageQualityPolicy
from labelimg.image_tools.ui.quality_panel import ImageQualityRequest
from labelimg.image_tools.application.display_adjustment import DisplayAdjustmentValues
from labelimg.image_tools.application.colored_frame_processor import ImageToolProcessor
from labelimg.image_tools.application.adjustment import ImageAdjustmentOptions
from labelimg.image_tools.domain.crop_geometry import CropRegion
from labelimg.image_tools.application.geometry_transform import GeometryOperation
from labelimg.image_tools.ui.adjustment_dialog import ImageAdjustmentRequest
from labelimg.image_tools.ui.geometry_dialog import GeometryTransformRequest
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


SORTS = [(key, descending) for key in ("name", "modified", "annotation", "review")
         for descending in (False, True)]


class FakeTrash:
    def __init__(self, directory):
        self.directory = directory
        self.count = 0

    def preflight(self, paths):
        for path in paths:
            if not Path(path).exists():
                raise FileNotFoundError(path)

    def move(self, path):
        target = self.directory / str(self.count)
        self.count += 1
        shutil.move(path, target)
        return TrashIdentity("path", str(target), path)

    def exists(self, identity):
        return Path(identity.token).exists()

    def restore(self, identity, destination):
        shutil.move(identity.token, destination)


class SortedWorkspaceOperationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertTrue(predicate())

    @contextmanager
    def workspace(self, sort, descending, asynchronous=False, marked=False):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"LABELIMG_CONFIG_DIR": temporary}
        ):
            root = Path(temporary)
            self.images = root / "images"
            self.xml = root / "xml"
            self.images.mkdir()
            self.xml.mkdir()
            classes = root / "classes.txt"
            classes.write_text("", encoding="utf-8")
            for index in range(8):
                path = self.images / ("image%d.png" % index)
                image = QImage(24, 16, QImage.Format_RGB32)
                image.fill(QColor(20 + index * 20, 40, 60))
                image.setPixelColor(0, 0, QColor("red"))
                image.setPixelColor(23, 0, QColor("green"))
                if marked and index == 1:
                    image = QImage(240, 180, QImage.Format_RGB32)
                    image.fill(QColor(120, 120, 120))
                    painter = QPainter(image)
                    painter.setPen(QPen(QColor("red"), 7))
                    painter.drawRect(20, 25, 75, 120)
                    painter.end()
                self.assertTrue(image.save(str(path)))
                # Distinct image mtimes whose order differs from file names.
                timestamp = 1700000000 + ((index * 3) % 8)
                os.utime(path, (timestamp, timestamp))
                if index % 3 != 0:
                    annotation = ElementTree.Element("annotation")
                    ElementTree.SubElement(annotation, "filename").text = path.name
                    if index % 3 == 1:
                        annotation.set("verified", "yes")
                    elif index % 4 == 2:
                        annotation.set("verified", "no")
                    obj = ElementTree.SubElement(annotation, "object")
                    ElementTree.SubElement(obj, "name").text = "part"
                    box = ElementTree.SubElement(obj, "bndbox")
                    for key, value in (("xmin", "1"), ("ymin", "1"), ("xmax", "8"), ("ymax", "8")):
                        ElementTree.SubElement(box, key).text = value
                    ElementTree.ElementTree(annotation).write(self.xml / (path.stem + ".xml"))
            self.window = create_workbench(WorkbenchLaunchOptions(
                class_file=str(classes), save_dir=str(self.xml)
            ))
            trash = root / "trash"
            trash.mkdir()
            self.window.system_trash = FakeTrash(trash)
            self.window.file_list_controls.state.sort_key = sort
            self.window.file_list_controls.state.descending = descending
            self.sort = sort
            self.descending = descending
            try:
                if asynchronous:
                    self.window.start_directory_load(str(self.images))
                    self.wait_until(lambda: self.window.dir_name == str(self.images)
                                    and not self.window._directory_load_jobs
                                    and not self.window._directory_projection_pending)
                else:
                    self.window.import_dir_images(str(self.images))
                yield self.window
            finally:
                self.window.stop_directory_load()
                self.wait_until(lambda: not self.window._directory_load_jobs)
                self.window.finish_deferred_image_loads()
                self.window.shutdown_image_decode_cache()
                self.window.deleteLater()
                QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()

    def disk_state(self, path):
        annotation = self.xml / (Path(path).stem + ".xml")
        if not annotation.exists():
            return "unannotated", "unreviewed"
        root = ElementTree.parse(annotation).getroot()
        return (
            "annotated" if root.findall("object") else "unannotated",
            {"yes": "verified", "no": "questioned"}.get(root.get("verified"), "unreviewed"),
        )

    def expected_order(self, live_states=None):
        paths = sorted(str(path) for path in self.images.glob("*.png"))
        if self.sort == "name":
            return list(reversed(paths)) if self.descending else paths
        def primary(path):
            annotation, review = (live_states or {}).get(path, self.disk_state(path))
            if self.sort == "modified":
                return os.path.getmtime(path)
            if self.sort == "annotation":
                return {"unannotated": 0, "annotated": 1}[annotation]
            return {"unreviewed": 0, "questioned": 1, "verified": 2}[review]
        # Python's stable sort keeps filename order inside equal-state groups.
        return sorted(paths, key=primary, reverse=self.descending)

    def assert_consistent(self, live_states=None):
        window = self.window
        expected = self.expected_order(live_states)
        self.assertEqual(window.m_img_list, expected)
        self.assertEqual(window.img_count, len(expected))
        self.assertEqual(window.file_list_widget.count(), len(expected))
        for row, path in enumerate(expected):
            item = window.file_list_widget.item(row)
            self.assertEqual(item.data(Qt.UserRole), path)
            self.assertEqual(window._file_row_by_path[path], row)
            self.assertEqual((item.data(FILE_ANNOTATION_STATE_ROLE),
                              item.data(FILE_REVIEW_STATE_ROLE)),
                             (live_states or {}).get(path, self.disk_state(path)))
            self.assertEqual(bool(item.data(CURRENT_IMAGE_ROLE)), path == window.file_path)
        self.assertEqual(tuple(expected), window._file_list_projection.ordered_paths)
        if window.file_path:
            row = expected.index(window.file_path)
            self.assertEqual(window.cur_img_idx, row)
            self.assertEqual(window.counter_str(), "[%d / %d]" % (row + 1, len(expected)))
            self.assertEqual(window.top_commands.counter_label.text(), "%d / %d" % (row + 1, len(expected)))
            self.assertTrue(window.windowTitle().endswith(window.counter_str()), window.windowTitle())
            self.assertEqual(window.annotation_editing.view.image_key, window.file_path)
            current_state = (live_states or {}).get(window.file_path, self.disk_state(window.file_path))
            self.assertEqual(bool(window.canvas.shapes), current_state[0] == "annotated")
            self.assertEqual(window.canvas.verified, current_state[1] == "verified")
            self.assertEqual(window.canvas.questioned, current_state[1] == "questioned")
            self.assertEqual(len(window.annotation_editing.view.snapshot.boxes), len(window.canvas.shapes))
            disk_image = QImage(window.file_path)
            self.assertEqual(window.image.convertToFormat(QImage.Format_RGBA8888),
                             disk_image.convertToFormat(QImage.Format_RGBA8888),
                             "Canvas source must match the current image on disk")

    def test_open_and_navigation_in_every_sort_direction(self):
        for asynchronous in (False, True):
            for sort, descending in SORTS:
                with self.subTest(sort=sort, descending=descending, asynchronous=asynchronous):
                    with self.workspace(sort, descending, asynchronous) as window:
                        order = self.expected_order()
                        self.assertEqual(window.file_path, order[0])
                        self.assert_consistent()
                        window.open_next_image()
                        self.assertEqual(window.file_path, order[1])
                        self.assert_consistent()
                        window.open_prev_image()
                        self.assertEqual(window.file_path, order[0])
                        self.assert_consistent()

    def test_delete_current_preserves_next_image_identity_in_every_sort_direction(self):
        for sort, descending in SORTS:
            for position in (0, 2, 7):
                with self.subTest(sort=sort, descending=descending, position=position):
                    with self.workspace(sort, descending) as window:
                        before = list(window.m_img_list)
                        expected = before[position + 1] if position < 7 else before[6]
                        window.open_file_list_path(before[position])
                        window.delete_image()
                        self.wait_until(lambda: window.file_path == expected)
                        self.assert_consistent()

    def test_delete_other_image_keeps_current_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    before = list(window.m_img_list)
                    window.open_file_list_path(before[2])
                    window.delete_file_paths([before[0]])
                    self.assertEqual(window.file_path, before[2])
                    self.assert_consistent()

    def test_rename_current_preserves_image_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    source = window.file_path
                    target = str(self.images / "renamed.png")
                    window.execute_file_rename({source: target})
                    self.assertEqual(window.file_path, target)
                    self.assert_consistent()


    def test_filtered_deletion_uses_visible_order_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    window.file_list_controls._set_filter("all", "verified", "all")
                    before = window.visible_file_paths()
                    self.assertGreaterEqual(len(before), 2)
                    window.open_file_list_path(before[0])
                    window.delete_image()
                    self.wait_until(lambda: window.file_path == before[1])
                    self.assert_consistent()

    def test_clear_annotations_preserves_current_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    path = next(path for path in window.m_img_list
                                if self.disk_state(path)[0] == "annotated")
                    window.open_file_list_path(path)
                    window.file_list_widget.item(window._file_row_by_path[path]).setSelected(True)
                    with patch("labelimg.files.ui.controller.localized_question", return_value=QMessageBox.Yes):
                        window.clear_selected_file_annotations()
                    self.assertEqual(window.file_path, path)
                    self.assertEqual(self.disk_state(path), ("unannotated", "unreviewed"))
                    self.assert_consistent()


    def test_batch_delete_skips_removed_neighbors_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    before = list(window.m_img_list)
                    window.open_file_list_path(before[2])
                    window.delete_file_paths(before[2:5])
                    self.wait_until(lambda: window.file_path == before[5])
                    self.assert_consistent()

    def test_delete_all_clears_image_and_counter_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    window.delete_file_paths(list(window.m_img_list))
                    self.assertIsNone(window.file_path)
                    self.assertFalse(window.actions.openNext.isEnabled())
                    self.assertFalse(window.actions.openPrev.isEnabled())
                    self.assertEqual(window.top_commands.counter_label.text(), "0 / 0")
                    self.assertEqual(window.windowTitle(), "labelImg")
                    self.assert_consistent()


    def select_paths(self, paths):
        view = self.window.file_list_widget
        view.clearSelection()
        for path in paths:
            view.item(self.window._file_row_by_path[path]).setSelected(True)

    def recover(self, entry):
        with patch("labelimg.workbench.recovery_ui.localized_question", return_value=QMessageBox.Yes), patch.object(
            self.window, "_choose_image_recovery_paths", return_value=None
        ):
            self.window._confirm_file_recovery(entry.entry_id)

    def assert_next_previous_keep_identity(self):
        current = self.window.file_path
        visible = self.window.visible_file_paths()
        if current in visible and visible.index(current) + 1 < len(visible):
            target = visible[visible.index(current) + 1]
            self.window.open_next_image()
            self.assertEqual(self.window.file_path, target)
            self.assert_consistent()
            self.window.open_prev_image()
            self.assertEqual(self.window.file_path, current)
            self.assert_consistent()

    def test_annotation_undo_redo_and_save_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    path = str(self.images / "image0.png")
                    window.open_file_list_path(path)
                    window.auto_saving.setChecked(False)
                    window.annotation_clipboard = [("added", ((2, 2), (12, 2), (12, 10), (2, 10)), False)]
                    window.paste_copied_bounding_boxes()
                    self.assertEqual(len(window.canvas.shapes), 1)
                    self.assert_consistent({path: ("annotated", "unreviewed")})
                    window.undo_annotation()
                    self.assertEqual(len(window.canvas.shapes), 0)
                    self.assert_consistent()
                    window.redo_annotation()
                    self.assertEqual(len(window.canvas.shapes), 1)
                    self.assert_consistent({path: ("annotated", "unreviewed")})
                    self.assertTrue(window.save_current_annotations_directly())
                    self.assert_consistent()
                    self.assert_next_previous_keep_identity()
                    window.undo_annotation()
                    self.assert_consistent({path: ("unannotated", "unreviewed")})
                    self.assertTrue(window.save_current_annotations_directly())
                    self.assert_consistent()

    def test_file_delete_clear_and_rename_recovery_in_every_sort_direction(self):
        for sort, descending in SORTS:
            for operation in ("delete", "clear", "rename"):
                with self.subTest(sort=sort, descending=descending, operation=operation):
                    with self.workspace(sort, descending) as window:
                        path = str(self.images / "image1.png")
                        window.open_file_list_path(path)
                        if operation == "delete":
                            window.delete_image()
                            self.wait_until(lambda: window.file_path is not None)
                            current = window.file_path
                        elif operation == "clear":
                            self.select_paths([path])
                            with patch("labelimg.files.ui.controller.localized_question", return_value=QMessageBox.Yes):
                                window.clear_selected_file_annotations()
                            current = path
                        else:
                            current = str(self.images / "renamed.png")
                            window.execute_file_rename({path: current})
                        self.assert_consistent()
                        self.recover(window.file_operations.recovery_entries[-1])
                        self.assertEqual(window.file_path, path if operation == "rename" else current)
                        self.assertTrue(Path(path).exists())
                        self.assertEqual(self.disk_state(path), ("annotated", "verified"))
                        self.assert_consistent()
                        self.assert_next_previous_keep_identity()

    def test_batch_review_and_recovery_in_every_sort_direction(self):
        for sort, descending in SORTS:
            for state in ("verified", "questioned", "unreviewed"):
                with self.subTest(sort=sort, descending=descending, state=state):
                    with self.workspace(sort, descending) as window:
                        current = str(self.images / "image0.png")
                        window.open_file_list_path(current)
                        targets = [str(self.images / ("image%d.png" % index)) for index in (0, 1, 2)]
                        original = {path: self.disk_state(path) for path in targets}
                        self.select_paths(targets)
                        with patch("labelimg.annotations.ui.workbench_controller.localized_question", return_value=QMessageBox.Yes):
                            window.set_selected_review_state(state)
                        self.assertEqual(window.file_path, current)
                        self.assertEqual(set(window.selected_file_paths()), set(targets))
                        for path in targets:
                            self.assertEqual(self.disk_state(path)[1], state)
                        self.assert_consistent()
                        self.recover(window.file_operations.recovery_entries[-1])
                        self.assertEqual(window.file_path, current)
                        for path in targets:
                            self.assertEqual(self.disk_state(path), original[path])
                        self.assert_consistent()

    def test_quick_geometry_and_image_recovery_in_every_sort_direction(self):
        for sort, descending in SORTS:
            for action in ("rotateClockwise", "rotateCounterclockwise", "rotate180", "flipHorizontal", "flipVertical"):
                with self.subTest(sort=sort, descending=descending, action=action):
                    with self.workspace(sort, descending) as window:
                        path = str(self.images / "image1.png")
                        window.open_file_list_path(path)
                        before = Path(path).read_bytes()
                        annotation = self.xml / "image1.xml"
                        annotation_before = annotation.read_bytes()
                        with patch("labelimg.image_tools.ui.controller.localized_warning") as warning:
                            getattr(window.actions, action).trigger()
                        self.assertFalse(warning.called, warning.call_args)
                        self.assertEqual(window.file_path, path)
                        self.assertNotEqual(Path(path).read_bytes(), before)
                        self.assert_consistent()
                        self.assert_next_previous_keep_identity()
                        with patch.object(window, "_choose_image_recovery_paths", return_value=(path,)):
                            window.undo_last_image_processing()
                        self.assertEqual(Path(path).read_bytes(), before)
                        self.assertEqual(annotation.read_bytes(), annotation_before)
                        self.assertEqual(window.file_path, path)
                        self.assert_consistent()

    def test_batch_resize_adjustment_and_recovery_in_every_sort_direction(self):
        for sort, descending in SORTS:
            for operation in ("resize", "adjust"):
                with self.subTest(sort=sort, descending=descending, operation=operation):
                    with self.workspace(sort, descending) as window:
                        targets = (str(self.images / "image1.png"), str(self.images / "image2.png"))
                        window.open_file_list_path(targets[0])
                        self.select_paths(targets)
                        before = {path: Path(path).read_bytes() for path in targets}
                        if operation == "resize":
                            request = GeometryTransformRequest(paths=targets, operation=GeometryOperation.RESIZE, resize_percent=50)
                            dialog_class = "labelimg.image_tools.ui.geometry_dialog.GeometryTransformDialog"
                            action = window.actions.transformImage
                        else:
                            request = ImageAdjustmentRequest(paths=targets, options=ImageAdjustmentOptions(brightness=20))
                            dialog_class = "labelimg.image_tools.ui.adjustment_dialog.ImageAdjustmentDialog"
                            action = window.actions.adjustImage
                        dialog = SimpleNamespace(exec_=lambda: QDialog.Accepted, request=request)
                        with patch(dialog_class, return_value=dialog), patch("labelimg.image_tools.ui.controller.localized_warning") as warning:
                            action.trigger()
                        self.assertFalse(warning.called, warning.call_args)
                        self.assertEqual(window.file_path, targets[0])
                        for path in targets:
                            self.assertNotEqual(Path(path).read_bytes(), before[path])
                        self.assert_consistent()
                        self.assert_next_previous_keep_identity()
                        with patch.object(window, "_choose_image_recovery_paths", return_value=targets):
                            window.undo_last_image_processing()
                        for path in targets:
                            self.assertEqual(Path(path).read_bytes(), before[path])
                        self.assertEqual(window.file_path, targets[0])
                        self.assert_consistent()

    def test_crop_removing_annotations_and_recovery_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    path = str(self.images / "image1.png")
                    window.open_file_list_path(path)
                    before = Path(path).read_bytes()
                    self.assertTrue(window.enter_crop_mode())
                    window.crop_overlay.set_region(CropRegion(12, 0, 12, 16))
                    with patch("labelimg.image_tools.ui.controller.localized_question", return_value=QMessageBox.Yes), patch(
                        "labelimg.image_tools.ui.controller.localized_warning"
                    ) as warning:
                        window.apply_crop()
                    self.assertFalse(warning.called, warning.call_args)
                    self.assertEqual(window.file_path, path)
                    self.assertEqual(len(window.canvas.shapes), 0)
                    self.assert_consistent()
                    with patch.object(window, "_choose_image_recovery_paths", return_value=(path,)):
                        window.undo_last_image_processing()
                    self.assertEqual(Path(path).read_bytes(), before)
                    self.assertEqual(window.file_path, path)
                    self.assertEqual(len(window.canvas.shapes), 1)
                    self.assert_consistent()


    @contextmanager
    def paused_directory_index(self):
        captured, released = Event(), Event()
        scan = AnnotationWorkspace.scan
        def pause_after_scan(workspace, *args, **kwargs):
            result = scan(workspace, *args, **kwargs)
            if QThread.currentThread() != self.app.thread():
                captured.set()
                if not released.wait(10):
                    raise RuntimeError("test did not release background index")
            return result
        with patch.object(AnnotationWorkspace, "scan", pause_after_scan):
            try:
                self.window.start_directory_load(str(self.images))
                self.wait_until(lambda: captured.is_set() and not self.window.file_list_controls.index_complete)
                yield
            finally:
                released.set()
                self.wait_until(lambda: not self.window._directory_load_jobs
                                and not self.window._directory_projection_pending)

    def test_review_during_background_index_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    current = str(self.images / "image0.png")
                    with self.paused_directory_index():
                        window.open_file_list_path(current)
                        targets = [str(self.images / ("image%d.png" % index)) for index in (0, 1, 2)]
                        self.select_paths(targets)
                        with patch("labelimg.annotations.ui.workbench_controller.localized_question", return_value=QMessageBox.Yes):
                            window.set_selected_review_state("questioned")
                    self.assertEqual(window.file_path, current)
                    self.assert_consistent()

    def test_crop_during_background_index_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    current = str(self.images / "image1.png")
                    with self.paused_directory_index():
                        window.open_file_list_path(current)
                        self.assertTrue(window.enter_crop_mode())
                        window.crop_overlay.set_region(CropRegion(12, 0, 12, 16))
                        with patch("labelimg.image_tools.ui.controller.localized_question", return_value=QMessageBox.Yes):
                            self.assertTrue(window.apply_crop())
                    self.assertEqual(window.file_path, current)
                    self.assertEqual(len(window.canvas.shapes), 0)
                    self.assert_consistent()


    def test_unsaved_annotation_edit_during_background_index_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    current = str(self.images / "image0.png")
                    with self.paused_directory_index():
                        window.open_file_list_path(current)
                        window.auto_saving.setChecked(False)
                        window.annotation_clipboard = [("added", ((2, 2), (12, 2), (12, 10), (2, 10)), False)]
                        window.paste_copied_bounding_boxes()
                    self.assertEqual(window.file_path, current)
                    self.assert_consistent({current: ("annotated", "unreviewed")})


    def test_hidden_batch_review_preserves_selection_current_and_filter(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    current = str(self.images / "image3.png")
                    targets = [str(self.images / ("image%d.png" % index)) for index in (1, 2)]
                    window.open_file_list_path(current)
                    self.select_paths(targets)
                    window.file_list_controls._set_filter("all", "verified", "all")
                    before_query = window.file_list_controls.state.query
                    self.assertNotIn(targets[1], window.visible_file_paths())
                    with patch("labelimg.annotations.ui.workbench_controller.localized_question", return_value=QMessageBox.Yes):
                        window.set_selected_review_state("questioned")
                    self.assertEqual(set(window.selected_file_paths()), set(targets))
                    self.assertEqual(window.file_path, current)
                    self.assertEqual(window.file_list_controls.state.query, before_query)
                    self.assertTrue(all(path not in window.visible_file_paths() for path in targets))
                    self.assert_consistent()
                    self.recover(window.file_operations.recovery_entries[-1])
                    self.assertEqual(window.file_path, current)
                    self.assertEqual(set(window.selected_file_paths()), set(targets))
                    self.assertEqual(window.file_list_controls.state.query, before_query)
                    self.assert_consistent()

    def test_partial_batch_image_recovery_preserves_noncurrent_target_and_remaining_result(self):
        for sort, descending in SORTS:
            for operation in ("resize", "adjust"):
                with self.subTest(sort=sort, descending=descending, operation=operation):
                    with self.workspace(sort, descending) as window:
                        current = str(self.images / "image3.png")
                        targets = (str(self.images / "image1.png"), str(self.images / "image2.png"))
                        window.open_file_list_path(current)
                        self.select_paths(targets)
                        window.file_list_controls.search_edit.setText("image3")
                        before = {path: Path(path).read_bytes() for path in targets}
                        if operation == "resize":
                            request = GeometryTransformRequest(paths=targets, operation=GeometryOperation.RESIZE, resize_percent=50)
                            dialog_class = "labelimg.image_tools.ui.geometry_dialog.GeometryTransformDialog"
                            action = window.actions.transformImage
                        else:
                            request = ImageAdjustmentRequest(paths=targets, options=ImageAdjustmentOptions(brightness=20, contrast=1.2, gamma=0.8))
                            dialog_class = "labelimg.image_tools.ui.adjustment_dialog.ImageAdjustmentDialog"
                            action = window.actions.adjustImage
                        dialog = SimpleNamespace(exec_=lambda: QDialog.Accepted, request=request)
                        with patch(dialog_class, return_value=dialog), patch("labelimg.image_tools.ui.controller.localized_warning") as warning:
                            action.trigger()
                        self.assertFalse(warning.called, warning.call_args)
                        self.assertEqual(window.file_path, current)
                        self.assert_consistent()
                        remaining_bytes = Path(targets[1]).read_bytes()
                        self.assertNotEqual(remaining_bytes, before[targets[1]])
                        with patch.object(window, "_choose_image_recovery_paths", return_value=(targets[0],)):
                            window.undo_last_image_processing()
                        self.assertEqual(Path(targets[0]).read_bytes(), before[targets[0]])
                        self.assertEqual(Path(targets[1]).read_bytes(), remaining_bytes)
                        self.assertEqual(window.file_path, current)
                        self.assert_consistent()
                        with patch.object(window, "_choose_image_recovery_paths", return_value=(targets[1],)):
                            window.undo_last_image_processing()
                        self.assertEqual(Path(targets[1]).read_bytes(), before[targets[1]])
                        self.assert_consistent()

    def test_colored_frame_removal_and_recovery_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending, marked=True) as window:
                    path = str(self.images / "image1.png")
                    window.open_file_list_path(path)
                    original = Path(path).read_bytes()
                    prepared = ImageToolProcessor().prepare(path)
                    self.assertTrue(prepared.changed)
                    self.assertGreaterEqual(len(prepared.candidates), 1)
                    def dialog_factory(*args, commit, **kwargs):
                        outcome = commit((prepared.replacement,))
                        return SimpleNamespace(exec_=lambda: QDialog.Accepted, outcome=outcome)
                    with patch("labelimg.image_tools.ui.colored_frame_dialog.ImageToolsDialog", side_effect=dialog_factory), patch(
                        "labelimg.image_tools.ui.controller.localized_warning"
                    ) as warning:
                        window.actions.removeColoredFrames.trigger()
                    self.assertFalse(warning.called, warning.call_args)
                    self.assertNotEqual(Path(path).read_bytes(), original)
                    self.assertEqual(window.file_path, path)
                    self.assert_consistent()
                    self.assert_next_previous_keep_identity()
                    with patch.object(window, "_choose_image_recovery_paths", return_value=(path,)):
                        window.undo_last_image_processing()
                    self.assertEqual(Path(path).read_bytes(), original)
                    self.assert_consistent()

    def test_display_adjustment_and_reset_leave_workspace_files_unchanged(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    current = window.file_path
                    original = {path: (Path(path).read_bytes(), Path(path).stat().st_mtime_ns) for path in window.m_img_list}
                    controller = window.display_adjustment_controller
                    controller.set_master(DisplayAdjustmentValues(20, 10))
                    controller.set_current(DisplayAdjustmentValues(-10, 25))
                    self.assertEqual(window.file_path, current)
                    self.assert_consistent()
                    self.assert_next_previous_keep_identity()
                    controller.reset_current()
                    controller.reset_all()
                    for path, (content, modified) in original.items():
                        self.assertEqual(Path(path).read_bytes(), content)
                        self.assertEqual(Path(path).stat().st_mtime_ns, modified)
                    self.assert_consistent()

    def test_recovery_during_background_index_in_every_sort_direction(self):
        for sort, descending in SORTS:
            for operation in ("review", "clear", "crop"):
                with self.subTest(sort=sort, descending=descending, operation=operation):
                    with self.workspace(sort, descending) as window:
                        current = str(self.images / "image1.png")
                        window.open_file_list_path(current)
                        original = Path(current).read_bytes()
                        if operation == "review":
                            window.set_current_review_state("questioned")
                            entry = window.file_operations.recovery_entries[-1]
                        elif operation == "clear":
                            self.select_paths([current])
                            with patch("labelimg.files.ui.controller.localized_question", return_value=QMessageBox.Yes):
                                window.clear_selected_file_annotations()
                            entry = window.file_operations.recovery_entries[-1]
                        else:
                            self.assertTrue(window.enter_crop_mode())
                            window.crop_overlay.set_region(CropRegion(12, 0, 12, 16))
                            with patch("labelimg.image_tools.ui.controller.localized_question", return_value=QMessageBox.Yes):
                                self.assertTrue(window.apply_crop())
                        with self.paused_directory_index():
                            window.open_file_list_path(current)
                            if operation == "crop":
                                with patch.object(window, "_choose_image_recovery_paths", return_value=(current,)):
                                    window.undo_last_image_processing()
                            else:
                                self.recover(entry)
                        self.assertEqual(window.file_path, current)
                        self.assertEqual(Path(current).read_bytes(), original)
                        self.assertEqual(self.disk_state(current), ("annotated", "verified"))
                        self.assert_consistent()

    def test_canceled_commands_and_crop_undo_redo_do_not_mutate_workspace(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    current = window.file_path
                    order = list(window.m_img_list)
                    before = {path: Path(path).read_bytes() for path in order}
                    xml_before = {path: path.read_bytes() for path in self.xml.glob("*.xml")}
                    self.select_paths(order[:3])
                    with patch("labelimg.annotations.ui.workbench_controller.localized_question", return_value=QMessageBox.No):
                        window.set_selected_review_state("questioned")
                    dialog = SimpleNamespace(exec_=lambda: QDialog.Rejected, request=None)
                    with patch("labelimg.image_tools.ui.geometry_dialog.GeometryTransformDialog", return_value=dialog):
                        window.actions.transformImage.trigger()
                    with patch("labelimg.image_tools.ui.adjustment_dialog.ImageAdjustmentDialog", return_value=dialog):
                        window.actions.adjustImage.trigger()
                    self.assertTrue(window.enter_crop_mode())
                    full = window.crop_overlay.region
                    window.crop_overlay.set_region(CropRegion(2, 2, 12, 10))
                    window.undo_annotation()
                    self.assertEqual(window.crop_overlay.region, full)
                    window.redo_annotation()
                    self.assertEqual(window.crop_overlay.region, CropRegion(2, 2, 12, 10))
                    window.cancel_crop()
                    self.assertEqual(window.file_path, current)
                    self.assertEqual(window.m_img_list, order)
                    for path, content in before.items():
                        self.assertEqual(Path(path).read_bytes(), content)
                    self.assertEqual({path: path.read_bytes() for path in self.xml.glob("*.xml")}, xml_before)
                    self.assert_consistent()


    def test_annotation_save_during_background_index_in_every_sort_direction(self):
        for sort, descending in SORTS:
            for mode in ("manual", "autosave", "save-many"):
                with self.subTest(sort=sort, descending=descending, mode=mode):
                    with self.workspace(sort, descending) as window:
                        current = str(self.images / "image0.png")
                        with self.paused_directory_index():
                            window.open_file_list_path(current)
                            window.auto_saving.setChecked(False)
                            window.annotation_clipboard = [("added", ((2, 2), (12, 2), (12, 10), (2, 10)), False)]
                            window.paste_copied_bounding_boxes()
                            if mode == "manual":
                                self.assertTrue(window.save_current_annotations_directly())
                            elif mode == "autosave":
                                window.auto_saving.setChecked(True)
                                window.save_dirty_annotations()
                            else:
                                self.assertIsNotNone(window._save_history_views((window.annotation_editing.view,)))
                            self.assertFalse(window.annotation_editing.view.dirty)
                        self.assertEqual(window.file_path, current)
                        self.assert_consistent()

    def test_duplicate_delete_last_box_undo_redo_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    current = str(self.images / "image1.png")
                    window.open_file_list_path(current)
                    window.auto_saving.setChecked(False)
                    window.label_selection_requested((window.canvas.shapes[0],), window.canvas.shapes[0])
                    window.copy_selected_shape()
                    self.assertEqual(len(window.canvas.shapes), 2)
                    self.assert_consistent()
                    window.undo_annotation()
                    self.assertEqual(len(window.canvas.shapes), 1)
                    window.redo_annotation()
                    self.assertEqual(len(window.canvas.shapes), 2)
                    window.delete_annotation_shapes(tuple(window.canvas.shapes))
                    self.assertEqual(len(window.canvas.shapes), 0)
                    self.assert_consistent({current: ("unannotated", "verified")})
                    window.undo_annotation()
                    self.assertEqual(len(window.canvas.shapes), 2)
                    self.assert_consistent()
                    window.redo_annotation()
                    self.assertEqual(len(window.canvas.shapes), 0)
                    self.assert_consistent({current: ("unannotated", "verified")})
                    self.assertTrue(window.save_current_annotations_directly())
                    self.assert_consistent()

    def test_quality_check_and_clear_preserve_identity_and_files_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    current = window.file_path
                    paths = tuple(window.m_img_list)
                    before = {path: Path(path).read_bytes() for path in paths}
                    request = ImageQualityRequest(paths, ImageQualityPolicy.standard())
                    dialog = SimpleNamespace(exec_=lambda: QDialog.Accepted, request=request)
                    with patch("labelimg.image_tools.ui.quality_panel.ImageQualityDialog", return_value=dialog):
                        self.assertTrue(window.open_image_quality_check())
                        self.wait_until(lambda: window._image_quality_thread is None)
                    self.assertEqual(window.file_path, current)
                    self.assertEqual(set(window.image_quality_results), set(paths))
                    self.assert_consistent()
                    self.assertTrue(window.clear_image_quality_results())
                    self.assertEqual(window.image_quality_results, {})
                    for path in paths:
                        self.assertEqual(Path(path).read_bytes(), before[path])
                    self.assert_consistent()

    def test_failed_image_batch_rolls_back_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    current = str(self.images / "image1.png")
                    window.open_file_list_path(current)
                    targets = (current, str(self.images / "image2.png"))
                    before = {path: Path(path).read_bytes() for path in targets}
                    annotations = {path: path.read_bytes() for path in self.xml.glob("*.xml")}
                    request = GeometryTransformRequest(paths=targets, operation=GeometryOperation.RESIZE, resize_percent=50)
                    dialog = SimpleNamespace(exec_=lambda: QDialog.Accepted, request=request)
                    move = window.system_trash.move
                    calls = []
                    def fail_second_resource(path):
                        calls.append(path)
                        if len(calls) == 2:
                            raise OSError("simulated second-resource trash failure")
                        return move(path)
                    with patch("labelimg.image_tools.ui.geometry_dialog.GeometryTransformDialog", return_value=dialog), patch.object(
                        window.system_trash, "move", side_effect=fail_second_resource
                    ), patch("labelimg.image_tools.ui.controller.localized_warning") as warning:
                        window.actions.transformImage.trigger()
                    self.assertTrue(warning.called)
                    self.assertEqual(window.file_path, current)
                    for path in targets:
                        self.assertEqual(Path(path).read_bytes(), before[path])
                    self.assertEqual({path: path.read_bytes() for path in self.xml.glob("*.xml")}, annotations)
                    self.assert_consistent()


    def test_single_review_during_background_index_in_every_sort_direction(self):
        for sort, descending in SORTS:
            with self.subTest(sort=sort, descending=descending):
                with self.workspace(sort, descending) as window:
                    current = str(self.images / "image0.png")
                    with self.paused_directory_index():
                        window.open_file_list_path(current)
                        window.set_current_review_state("verified")
                    self.assertEqual(window.file_path, current)
                    self.assertEqual(self.disk_state(current), ("unannotated", "verified"))
                    self.assert_consistent()


if __name__ == "__main__":
    unittest.main()
