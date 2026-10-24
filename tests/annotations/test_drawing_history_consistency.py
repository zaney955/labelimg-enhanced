"""Drawing must start from the same complete state retained by history."""

import os
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QImage, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class DrawingHistoryConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.images = self.root / "images"
        self.labels = self.root / "labels"
        self.images.mkdir()
        self.labels.mkdir()
        (self.root / "config").mkdir()
        self.environment = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": str(self.root / "config")})
        self.environment.start()
        (self.labels / "classes.txt").write_text("cat\ndog\n", encoding="utf-8")
        image = QImage(100, 80, QImage.Format_RGB32)
        image.fill(Qt.white)
        for name in ("a.png", "b.png"):
            self.assertTrue(image.save(str(self.images / name)))
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=str(self.labels / "classes.txt"), save_dir=str(self.labels)))
        self.window.auto_saving.setChecked(False)
        self.window.import_dir_images(str(self.images))
        self.errors = []
        self.exception_hook = patch.object(sys, "excepthook", lambda kind, value, traceback: self.errors.append(value))
        self.exception_hook.start()

    def tearDown(self):
        self.window.auto_save_timer.stop()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.exception_hook.stop()
        self.environment.stop()
        self.temp.cleanup()

    def start_box(self):
        self.window.create_shape()
        self.window.canvas.handle_drawing(QPointF(10, 10))
        self.assertEqual(self.errors, [], repr(self.errors))
        self.assertTrue(self.window.annotation_editing.edit_open)

    def draw_box(self, label="cat"):
        self.start_box()
        self.window.canvas.line.points[1] = QPointF(35, 40)
        with patch.object(self.window.candidate_label_dialog, "choose", return_value=label):
            self.window.canvas.handle_drawing(QPointF(35, 40))
        self.assertEqual(self.errors, [], repr(self.errors))
        self.assertEqual(self.window.annotation_scene.capture(self.window.file_path), self.window.annotation_editing.view.snapshot)

    def test_first_and_repeated_drawings_start_with_consistent_history(self):
        self.draw_box()
        self.draw_box("dog")
        self.draw_box()

    def test_canceled_label_then_new_drawing_preserves_existing_history(self):
        self.draw_box()
        self.draw_box(None)
        self.draw_box("dog")

    def test_cancel_pending_drawing_then_start_another_box(self):
        self.draw_box()
        self.start_box()
        self.window.undo_annotation()
        self.draw_box("dog")

    def test_saved_and_reviewed_annotation_then_new_drawing(self):
        self.draw_box()
        self.window.save_file()
        self.window.verify_image()
        self.draw_box("dog")

    def test_undo_and_redo_then_start_drawing(self):
        self.draw_box()
        self.window.undo_annotation()
        self.window.redo_annotation()
        self.draw_box("dog")

    def test_navigation_back_to_saved_image_then_start_drawing(self):
        self.draw_box()
        self.window.save_file()
        original = self.window.file_path
        self.window.load_file(str(self.images / "b.png"))
        self.window.load_file(original)
        self.draw_box("dog")

    def test_manual_save_in_each_format_then_start_drawing(self):
        from labelimg.annotations import AnnotationFormat
        self.draw_box()
        for annotation_format in AnnotationFormat:
            self.window.set_annotation_format(annotation_format)
            self.window.save_file()
            self.draw_box("dog")

    def test_autosave_then_start_drawing(self):
        self.window.auto_saving.setChecked(True)
        self.draw_box()
        self.window.save_dirty_annotations()
        self.draw_box("dog")

    def test_current_review_controls_then_start_drawing(self):
        self.draw_box()
        for callback in (self.window.question_image, self.window.verify_image, self.window.verify_image):
            callback()
            self.draw_box()

    def test_segmented_review_control_then_start_drawing(self):
        self.draw_box()
        for state in ("verified", "questioned", "unreviewed"):
            self.window.set_current_review_state(state)
            self.draw_box()

    def test_selection_difficulty_and_duplicate_then_start_drawing(self):
        self.draw_box()
        self.window.canvas.select_shape(self.window.canvas.shapes[0])
        self.window.diffc_button.setChecked(True)
        self.draw_box("dog")
        self.window.canvas.select_shape(self.window.canvas.shapes[0])
        self.window.copy_selected_shape()
        self.draw_box()

    def mouse_draw(self):
        self.window.show()
        self.app.processEvents()
        self.window.create_shape()
        canvas = self.window.canvas
        count = len(canvas.shapes)
        size = canvas.pixmap_size
        first = ((QPointF(size.width() * .1, size.height() * .1) + canvas.offset_to_center()) * canvas.scale).toPoint()
        last = ((QPointF(size.width() * .5, size.height() * .5) + canvas.offset_to_center()) * canvas.scale).toPoint()
        with patch.object(self.window.candidate_label_dialog, "choose", return_value="cat"):
            QTest.mousePress(canvas, Qt.LeftButton, pos=first)
            self.assertEqual(self.errors, [], repr(self.errors))
            self.assertTrue(self.window.annotation_editing.edit_open, repr((canvas.isEnabled(), canvas.mode, canvas.scale, first, canvas.transform_pos(first), canvas.current, self.window.file_path)))
            QApplication.sendEvent(canvas, QMouseEvent(QEvent.MouseMove, QPointF(last), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
            QTest.mouseRelease(canvas, Qt.LeftButton, pos=last)
            self.app.processEvents()
        self.assertEqual(self.errors, [], repr(self.errors))
        self.assertFalse(self.window.annotation_editing.edit_open)
        self.assertEqual(len(canvas.shapes), count + 1)

    def test_real_mouse_drawings_with_repaint_and_hover(self):
        for _index in range(8):
            self.mouse_draw()

    def test_real_mouse_drawing_after_large_image_preview(self):
        image = QImage(5000, 3000, QImage.Format_RGB32)
        image.fill(Qt.white)
        large = str(self.images / "large.png")
        self.assertTrue(image.save(large))
        self.assertTrue(self.window.load_file(large))
        QTest.qWait(100)
        self.mouse_draw()

    def test_cleanup_and_recovery_then_start_drawing(self):
        from labelimg.files.ui.cleanup_dialog import AnnotationCleanupDialog
        (self.labels / "a.txt").write_text("")
        self.window.load_file(str(self.images / "a.png"))
        self.install_trash()
        def choose(dialog):
            dialog.scan()
            dialog.empty.setChecked(True)
            return QDialog.Accepted
        with patch.object(AnnotationCleanupDialog, "exec_", choose):
            self.window.cleanup_annotation_files()
        self.start_box()
        self.window.undo_annotation()
        entry = self.window.file_operations.recovery_entries[0]
        with patch("labelimg.workbench.recovery_ui.localized_question", return_value=QMessageBox.Yes):
            self.window._confirm_file_recovery(entry.entry_id)
        self.draw_box()

    def install_trash(self):
        from labelimg.platform.recovery import TrashIdentity
        moves = []
        def move(path):
            destination = str(self.root / ("trash-%d" % len(moves)))
            shutil.move(path, destination)
            moves.append(path)
            return TrashIdentity("path", destination, path)
        self.window.system_trash = type("Trash", (), {
            "move": staticmethod(move), "preflight": staticmethod(lambda _paths: None),
            "exists": staticmethod(lambda identity: Path(identity.token).exists()),
            "restore": staticmethod(lambda identity, destination: shutil.move(identity.token, destination)),
        })()

    def test_start_drawing_after_large_image_rotation(self):
        image = QImage(5000, 3000, QImage.Format_RGB32)
        image.fill(Qt.white)
        large = str(self.images / "large-rotate.png")
        self.assertTrue(image.save(large))
        self.assertTrue(self.window.load_file(large))
        self.install_trash()
        self.window.display_adjustment_panel.master_brightness.slider.setValue(20)
        self.window.display_adjustment_controller.finish_master_gesture()
        with patch("labelimg.image_tools.ui.controller.localized_warning") as warnings:
            self.window.actions.rotateClockwise.trigger()
        self.assertFalse(warnings.called, repr(warnings.call_args))
        self.start_box()

    def assert_preview_geometry_and_draw(self):
        canvas = self.window.canvas
        self.assertLess(canvas.pixmap.width() * canvas.pixmap.height(), self.window.image.width() * self.window.image.height())
        self.assertEqual(canvas.pixmap_size, self.window.image.size())
        self.draw_box()

    def test_adjusted_quick_transforms_preserve_original_geometry(self):
        self.install_trash()
        with patch("labelimg.image_tools.ui.display_adjustment.PREVIEW_MAX_PIXELS", 100), patch.object(self.window.display_adjustment_controller, "_submit_full"):
            self.window.display_adjustment_panel.master_brightness.slider.setValue(20)
            for name in ("rotateClockwise", "rotateCounterclockwise", "rotate180", "flipHorizontal", "flipVertical"):
                with self.subTest(action=name):
                    getattr(self.window.actions, name).trigger()
                    self.assert_preview_geometry_and_draw()
                    self.window.save_file()

    def test_adjusted_crop_preserves_original_geometry(self):
        from labelimg.image_tools.domain.crop_geometry import CropRegion
        self.install_trash()
        with patch("labelimg.image_tools.ui.display_adjustment.PREVIEW_MAX_PIXELS", 100), patch.object(self.window.display_adjustment_controller, "_submit_full"):
            self.window.display_adjustment_panel.master_brightness.slider.setValue(20)
            self.window.enter_crop_mode()
            self.window.crop_overlay.set_region(CropRegion(5, 5, 80, 60))
            self.assertTrue(self.window.apply_crop())
            self.assert_preview_geometry_and_draw()

    def test_adjusted_pixel_refresh_keeps_history_drawable(self):
        self.draw_box()
        with patch("labelimg.image_tools.ui.display_adjustment.PREVIEW_MAX_PIXELS", 100), patch.object(self.window.display_adjustment_controller, "_submit_full"):
            self.window.display_adjustment_panel.master_brightness.slider.setValue(20)
            self.assertTrue(self.window._refresh_current_image_pixels((self.window.file_path,)))
            self.assert_preview_geometry_and_draw()
            self.window.undo_annotation()
            self.assertEqual(len(self.window.canvas.shapes), 1)


if __name__ == "__main__":
    unittest.main()
