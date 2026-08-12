import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch, PropertyMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QColor, QCursor, QImage, QKeySequence, QPixmap
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox, QToolButton

from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.annotations.domain.model import (
    AnnotationBox,
    AnnotationFormat,
)
from labelimg.annotations.infrastructure.document import AnnotationDocument
from labelimg.files.application.recovery import (
    RecoveryOperation,
    TrashIdentity,
)
from labelimg.image_tools.application.recovery import ImageProcessingOperation
from labelimg.image_tools.application.transaction import ImageRecoveryBlocked
from labelimg.files.ui.list_widget import FILE_QUALITY_FINDINGS_ROLE
from labelimg.image_tools.application.crop import CropRegion
from labelimg.image_tools.application.adjustment import ImageAdjustmentOptions
from labelimg.image_tools.ui.adjustment_dialog import ImageAdjustmentRequest
from labelimg.image_tools.ui.geometry_dialog import GeometryTransformRequest
from labelimg.image_tools.application.geometry_transform import GeometryOperation
from labelimg.image_tools.domain.quality import ImageQualityPolicy
from labelimg.image_tools.ui.quality_panel import ImageQualityRequest
from labelimg.image_tools.application.session import (
    ImageProcessingProjectionKind,
    PreparedPixelChange,
)
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.canvas.shape import Shape


class ImageToolsAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(ENGLISH)
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {"LABELIMG_CONFIG_DIR": self.temporary.name},
        )
        self.environment.start()
        classes_path = os.path.join(self.temporary.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=classes_path,
            save_dir="",
        ))
        self.image_path = os.path.join(self.temporary.name, "sample.png")
        image = QImage(40, 40, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(self.image_path))
        self.assertTrue(self.window.load_file(self.image_path))

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()
        set_language(ENGLISH)

    def test_image_menu_separates_processing_from_annotation_undo(self):
        self.assertEqual(self.window.menus.image.title(), "&Image")
        actions = self.window.menus.image.actions()
        self.assertEqual(
            actions,
            [
                self.window.actions.cropImage,
                self.window.menus.geometry.menuAction(),
                self.window.actions.transformImage,
                actions[3],
                self.window.actions.adjustImage,
                actions[5],
                self.window.actions.checkImageQuality,
                actions[7],
                self.window.menus.specializedRepair.menuAction(),
                actions[9],
                self.window.actions.undoImageProcessing,
            ],
        )
        for index in (3, 5, 7, 9):
            self.assertTrue(actions[index].isSeparator())
        self.assertEqual(
            self.window.menus.specializedRepair.actions(),
            [self.window.actions.removeColoredFrames],
        )
        self.assertEqual(
            self.window.menus.geometry.actions(),
            [
                self.window.actions.rotateClockwise,
                self.window.actions.rotateCounterclockwise,
                self.window.actions.rotate180,
                self.window.menus.geometry.actions()[3],
                self.window.actions.flipHorizontal,
                self.window.actions.flipVertical,
            ],
        )
        self.assertTrue(self.window.menus.geometry.actions()[3].isSeparator())
        self.assertEqual(
            self.window.actions.cropImage.text(),
            "Crop…",
        )
        self.assertEqual(
            self.window.actions.removeColoredFrames.text(),
            "Remove Red/Yellow Borders…",
        )
        self.assertEqual(
            self.window.actions.undoImageProcessing.text(),
            "Undo Last Image Processing…",
        )
        self.assertEqual(
            self.window.actions.transformImage.text(),
            "Batch Geometry Transform…",
        )
        self.assertIsNot(
            self.window.actions.undoImageProcessing,
            self.window.actions.undoAnnotation,
        )

    def test_image_menu_retranslates_to_simplified_chinese(self):
        set_language(SIMPLIFIED_CHINESE)
        self.window.retranslate_ui()

        self.assertEqual(self.window.menus.image.title(), "图像(&I)")
        self.assertEqual(
            self.window.actions.removeColoredFrames.text(),
            "去除红色/黄色边框…",
        )
        self.assertEqual(self.window.actions.cropImage.text(), "裁剪…")
        self.assertEqual(
            self.window.actions.transformImage.text(),
            "批量几何变换…",
        )
        self.assertEqual(
            self.window.actions.undoImageProcessing.text(),
            "撤销上次图像处理…",
        )

    def test_workspace_receives_current_image_and_explicit_file_selection(self):
        selected = (self.image_path, os.path.join(self.temporary.name, "two.png"))
        fake_dialog = SimpleNamespace(
            exec_=lambda: QDialog.Rejected,
            outcome=None,
        )
        with patch.object(
            self.window,
            "selected_file_paths",
            return_value=list(selected),
        ), patch(
            "labelimg.image_tools.ui.colored_frame_dialog.ImageToolsDialog",
            return_value=fake_dialog,
        ) as dialog_type:
            self.window.open_remove_colored_frames()

        args, kwargs = dialog_type.call_args
        self.assertEqual(args[0], self.image_path)
        self.assertEqual(args[1], selected)
        plan = object()
        outcome = object()
        replacement = object()
        with patch.object(
            self.window.image_processing,
            "prepare",
            return_value=plan,
        ) as prepare, patch.object(
            self.window.image_processing,
            "commit",
            return_value=outcome,
        ) as commit:
            self.assertIs(
                kwargs["commit"]((replacement,), target_count=1),
                outcome,
            )
        change = prepare.call_args.args[0]
        self.assertIsInstance(change, PreparedPixelChange)
        self.assertEqual(change.replacements, (replacement,))
        self.assertEqual(change.target_count, 1)
        commit.assert_called_once_with(plan)
        self.assertIs(kwargs["parent"], self.window)

    def test_pending_annotation_gesture_blocks_workspace_entry(self):
        self.window.annotation_editing.set_pending("drag", lambda: None)
        with patch(
            "labelimg.image_tools.ui.colored_frame_dialog.ImageToolsDialog",
        ) as dialog_type:
            self.window.open_remove_colored_frames()

        dialog_type.assert_not_called()
        self.assertEqual(
            self.window.statusBar().currentMessage(),
            "Finish or cancel the current drawing or drag operation first.",
        )
        self.window.annotation_editing.clear_pending()

    def test_pixel_refresh_preserves_canvas_shapes_and_view_values(self):
        sentinel_shape = Shape("box")
        self.window.canvas.shapes = [sentinel_shape]
        self.window.zoom_widget.setValue(175)
        self.window.scroll_bars[next(iter(self.window.scroll_bars))].setValue(4)

        replacement = QImage(40, 40, QImage.Format_RGB32)
        replacement.fill(QColor("black"))
        self.assertTrue(replacement.save(self.image_path))
        zoom_before = self.window.zoom_widget.value()
        scroll_before = {
            orientation: bar.value()
            for orientation, bar in self.window.scroll_bars.items()
        }

        self.assertTrue(
            self.window._refresh_current_image_pixels((self.image_path,))
        )

        self.assertEqual(self.window.canvas.shapes, [sentinel_shape])
        self.assertEqual(self.window.zoom_widget.value(), zoom_before)
        self.assertEqual(
            {
                orientation: bar.value()
                for orientation, bar in self.window.scroll_bars.items()
            },
            scroll_before,
        )
        self.assertFalse(self.window.canvas.pixmap.isNull())

    def test_latest_recovery_action_targets_only_image_processing(self):
        ordinary = SimpleNamespace(
            operation=RecoveryOperation.DELETE,
            recoverable=True,
            entry_id="delete",
        )
        image_entry = SimpleNamespace(
            operation=ImageProcessingOperation.PROCESS,
            recoverable=True,
            entry_id="image",
        )
        with patch.object(
            type(self.window.image_processing),
            "recovery_entries",
            new_callable=PropertyMock,
            return_value=(ordinary, image_entry),
        ):
            self.window.update_image_menu()
            latest = self.window._latest_image_processing_recovery()

        self.assertIs(latest, image_entry)
        self.assertTrue(self.window.actions.undoImageProcessing.isEnabled())

    def test_crop_action_uses_canvas_scoped_c_and_transient_controls(self):
        self.assertEqual(
            self.window.actions.cropImage.shortcut(),
            QKeySequence("C"),
        )
        self.window.show()
        self.window.canvas.setFocus()
        QTest.keyClick(self.window.canvas, Qt.Key_C)
        self.app.processEvents()

        self.assertTrue(self.window._crop_active)
        self.assertTrue(self.window.actions.cropImage.isChecked())
        self.assertTrue(self.window.crop_controls.isVisible())
        self.assertIsNone(self.window.crop_overlay.region)

        # The second C is deliberately idempotent.
        QTest.keyClick(self.window.crop_overlay, Qt.Key_C)
        self.assertTrue(self.window._crop_active)
        self.window.cancel_crop()

        self.window.file_list_widget.setFocus()
        QTest.keyClick(self.window.file_list_widget, Qt.Key_C)
        self.assertFalse(self.window._crop_active)

    def test_quick_rotation_commits_current_image_without_a_shortcut(self):
        rectangular_path = os.path.join(self.temporary.name, "rectangular.png")
        image = QImage(60, 40, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(rectangular_path))
        self.assertTrue(self.window.load_file(rectangular_path))
        trash_dir = os.path.join(self.temporary.name, "trash-quick-rotate")
        os.makedirs(trash_dir)
        self.window.system_trash = _FakeTrash(trash_dir)

        self.assertTrue(self.window.actions.rotateClockwise.shortcut().isEmpty())
        with patch("labelimg.image_tools.ui.controller.localized_warning") as warning:
            self.window.actions.rotateClockwise.trigger()
        self.assertFalse(warning.called, warning.call_args)

        transformed = QImage(rectangular_path)
        self.assertEqual(
            (transformed.width(), transformed.height()),
            (40, 60),
        )
        self.assertEqual(
            (self.window.image.width(), self.window.image.height()),
            (40, 60),
        )
        entry = self.window._latest_image_processing_recovery()
        self.assertEqual(entry.target_count, 1)
        self.assertEqual(entry.payload[0].image_path, rectangular_path)

    def test_top_bar_exposes_rotate_and_flip_split_buttons(self):
        buttons = self.window.top_commands.findChildren(QToolButton)
        rotate = next(
            button for button in buttons
            if button.defaultAction() is self.window.actions.rotateClockwise
        )
        flip = next(
            button for button in buttons
            if button.defaultAction() is self.window.actions.flipHorizontal
        )

        self.assertEqual(rotate.popupMode(), QToolButton.MenuButtonPopup)
        self.assertEqual(
            rotate.menu().actions(),
            [
                self.window.actions.rotateCounterclockwise,
                self.window.actions.rotate180,
            ],
        )
        self.assertEqual(flip.popupMode(), QToolButton.MenuButtonPopup)
        self.assertEqual(
            flip.menu().actions(),
            [self.window.actions.flipVertical],
        )

    def test_transform_workspace_command_applies_accepted_current_request(self):
        rectangular_path = os.path.join(self.temporary.name, "workspace-rect.png")
        image = QImage(80, 40, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(rectangular_path))
        self.assertTrue(self.window.load_file(rectangular_path))
        trash_dir = os.path.join(self.temporary.name, "trash-transform-workspace")
        os.makedirs(trash_dir)
        self.window.system_trash = _FakeTrash(trash_dir)
        fake_dialog = SimpleNamespace(
            exec_=lambda: QDialog.Accepted,
            request=GeometryTransformRequest(
                paths=(rectangular_path,),
                operation=GeometryOperation.ROTATE_COUNTERCLOCKWISE,
            ),
        )

        with patch(
            "labelimg.image_tools.ui.geometry_dialog.GeometryTransformDialog",
            return_value=fake_dialog,
        ), patch("labelimg.image_tools.ui.controller.localized_warning") as warning:
            self.window.actions.transformImage.trigger()

        self.assertFalse(warning.called, warning.call_args)
        transformed = QImage(rectangular_path)
        self.assertEqual(
            (transformed.width(), transformed.height()),
            (40, 80),
        )

    def test_transform_workspace_atomically_applies_selected_resize_batch(self):
        first = os.path.join(self.temporary.name, "batch-first.png")
        second = os.path.join(self.temporary.name, "batch-second.png")
        for path, size in ((first, (80, 40)), (second, (60, 30))):
            image = QImage(size[0], size[1], QImage.Format_RGB32)
            image.fill(QColor("white"))
            self.assertTrue(image.save(path))
        self.assertTrue(self.window.load_file(first))
        trash_dir = os.path.join(self.temporary.name, "trash-transform-batch")
        os.makedirs(trash_dir)
        self.window.system_trash = _FakeTrash(trash_dir)
        fake_dialog = SimpleNamespace(
            exec_=lambda: QDialog.Accepted,
            request=GeometryTransformRequest(
                paths=(first, second),
                operation=GeometryOperation.RESIZE,
                resize_percent=50,
            ),
        )

        with patch.object(
            self.window,
            "selected_file_paths",
            return_value=[first, second],
        ), patch(
            "labelimg.image_tools.ui.geometry_dialog.GeometryTransformDialog",
            return_value=fake_dialog,
        ), patch("labelimg.image_tools.ui.controller.localized_warning") as warning:
            self.window.actions.transformImage.trigger()

        self.assertFalse(warning.called, warning.call_args)
        first_result = QImage(first)
        second_result = QImage(second)
        self.assertEqual((first_result.width(), first_result.height()), (40, 20))
        self.assertEqual((second_result.width(), second_result.height()), (30, 15))
        entry = self.window._latest_image_processing_recovery()
        self.assertEqual(entry.target_count, 2)
        self.assertEqual(
            tuple(group.image_path for group in entry.payload),
            (first, second),
        )

    def test_adjust_image_command_commits_selected_pixel_batch(self):
        second = os.path.join(self.temporary.name, "adjust-second.png")
        image = QImage(40, 40, QImage.Format_RGB32)
        image.fill(QColor(20, 40, 60))
        self.assertTrue(image.save(second))
        trash_dir = os.path.join(self.temporary.name, "trash-adjust-batch")
        os.makedirs(trash_dir)
        self.window.system_trash = _FakeTrash(trash_dir)
        request = ImageAdjustmentRequest(
            paths=(self.image_path, second),
            options=ImageAdjustmentOptions(brightness=-20),
        )
        fake_dialog = SimpleNamespace(
            exec_=lambda: QDialog.Accepted,
            request=request,
        )

        with patch.object(
            self.window,
            "selected_file_paths",
            return_value=[self.image_path, second],
        ), patch(
            "labelimg.image_tools.ui.adjustment_dialog.ImageAdjustmentDialog",
            return_value=fake_dialog,
        ), patch("labelimg.image_tools.ui.controller.localized_warning") as warning:
            self.window.actions.adjustImage.trigger()

        self.assertFalse(warning.called, warning.call_args)
        entry = self.window._latest_image_processing_recovery()
        self.assertEqual(entry.target_count, 2)
        self.assertEqual(
            {resource.original_path for resource in entry.payload},
            {self.image_path, second},
        )

    def test_quality_command_populates_badge_cache_and_nonmodal_panel(self):
        self.window.populate_file_list((self.image_path,))
        request = ImageQualityRequest(
            (self.image_path,),
            ImageQualityPolicy.standard(),
        )
        fake_dialog = SimpleNamespace(
            exec_=lambda: QDialog.Accepted,
            request=request,
        )

        with patch(
            "labelimg.image_tools.ui.quality_panel.ImageQualityDialog",
            return_value=fake_dialog,
        ):
            self.window.actions.checkImageQuality.trigger()

        for _ in range(200):
            if self.window.image_quality_panel.result_paths:
                break
            QTest.qWait(10)

        item = self.window.file_list_widget.item(0)
        self.assertTrue(item.data(FILE_QUALITY_FINDINGS_ROLE))
        self.assertEqual(
            self.window.image_quality_panel.result_paths,
            (self.image_path,),
        )
        self.assertFalse(self.window.image_quality_dock.isHidden())
        self.assertIsNotNone(
            self.window.image_quality_cache.get(
                self.image_path,
                request.policy,
            )
        )

    def test_crop_action_immediately_owns_and_restores_cursor(self):
        self.window.show()
        self.app.processEvents()
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        QApplication.setOverrideCursor(QCursor(Qt.OpenHandCursor))
        try:
            self.window.actions.cropImage.trigger()
            self.app.processEvents()

            self.assertEqual(
                QApplication.overrideCursor().shape(),
                Qt.CrossCursor,
            )
            self.window.cancel_crop()
            self.assertEqual(
                QApplication.overrideCursor().shape(),
                Qt.OpenHandCursor,
            )
        finally:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

    def test_crop_controls_do_not_relayout_the_canvas(self):
        self.window.resize(900, 640)
        self.window.show()
        self.app.processEvents()
        before = (
            self.window.canvas.mapToGlobal(QPoint(0, 0)),
            self.window.scroll_area.viewport().geometry(),
            self.window.scroll_area.viewport().size(),
        )

        self.window.actions.cropImage.trigger()
        self.app.processEvents()
        active = (
            self.window.canvas.mapToGlobal(QPoint(0, 0)),
            self.window.scroll_area.viewport().geometry(),
            self.window.scroll_area.viewport().size(),
        )
        self.window.cancel_crop()
        self.app.processEvents()
        finished = (
            self.window.canvas.mapToGlobal(QPoint(0, 0)),
            self.window.scroll_area.viewport().geometry(),
            self.window.scroll_area.viewport().size(),
        )

        self.assertEqual(active, before)
        self.assertEqual(finished, before)

    def test_enter_in_numeric_crop_field_does_not_apply(self):
        self.window.enter_crop_mode()
        self.window.crop_overlay.set_region(CropRegion(1, 1, 20, 20))
        apply_spy = QSignalSpy(self.window.crop_overlay.applyRequested)
        width = self.window.crop_controls.spins["width"]
        width.setFocus()

        QTest.keyClick(width, Qt.Key_1)
        QTest.keyClick(width, Qt.Key_0)
        QTest.keyClick(width, Qt.Key_Return)

        self.assertEqual(len(apply_spy), 0)
        self.assertTrue(self.window._crop_active)
        self.window.cancel_crop()

    def test_crop_history_shortcuts_do_not_enter_annotation_history(self):
        self.window.show()
        self.window.enter_crop_mode()
        first = CropRegion(1, 1, 20, 20)
        second = CropRegion(2, 3, 18, 17)
        self.window.crop_overlay.set_region(first)
        self.window.crop_overlay.set_region(second)
        width = self.window.crop_controls.spins["width"]
        width.setFocus()
        annotation_view = self.window.annotation_editing.view

        QTest.keyClick(width, Qt.Key_Z, Qt.ControlModifier)

        self.assertEqual(self.window.crop_overlay.region, first)
        self.assertEqual(
            self.window.annotation_editing.view.revision_id,
            annotation_view.revision_id,
        )
        self.window.cancel_crop()

    def test_crop_commit_records_one_recoverable_image_group(self):
        trash_dir = os.path.join(self.temporary.name, "trash")
        os.makedirs(trash_dir)
        self.window.system_trash = _FakeTrash(trash_dir)
        self.window.enter_crop_mode()
        self.window.crop_overlay.set_region(CropRegion(5, 6, 20, 18))

        self.assertTrue(self.window.apply_crop())

        result = QImage(self.image_path)
        self.assertEqual((result.width(), result.height()), (20, 18))
        entry = self.window._latest_image_processing_recovery()
        self.assertEqual(entry.target_count, 1)
        self.assertEqual(entry.payload[0].image_path, self.image_path)
        self.assertFalse(self.window._crop_active)
        self.assertFalse(self.window.annotation_editing.view.can_undo)

    def test_crop_commits_and_recovers_image_with_pascal_annotations(self):
        annotation_path = os.path.splitext(self.image_path)[0] + ".xml"
        AnnotationDocument(
            image_path=self.image_path,
            image_data=self.window.image_data,
            boxes=(
                AnnotationBox(
                    "clipped",
                    ((5, 5), (20, 5), (20, 20), (5, 20)),
                ),
                AnnotationBox(
                    "removed",
                    ((30, 30), (38, 30), (38, 38), (30, 38)),
                ),
            ),
        ).save(annotation_path, AnnotationFormat.PASCAL_VOC)
        self.window.annotation_workspace.scan(self.temporary.name)
        view = self.window.annotation_editing.view
        self.window.annotation_persistence.release(view)
        self.window.annotation_editing.remove_images((self.image_path,))
        self.window.annotation_scene.forget_image(self.image_path)
        self.assertTrue(self.window.load_file(annotation_path))
        self.assertEqual(len(self.window.canvas.shapes), 2)
        trash_dir = os.path.join(self.temporary.name, "trash-joint")
        os.makedirs(trash_dir)
        self.window.system_trash = _FakeTrash(trash_dir)
        self.window.enter_crop_mode()
        self.window.crop_overlay.set_region(CropRegion(10, 10, 20, 20))

        with patch(
            "labelimg.image_tools.ui.controller.localized_question",
            return_value=QMessageBox.Yes,
        ):
            self.assertTrue(self.window.apply_crop())

        cropped = AnnotationDocument.load(
            annotation_path,
            self.image_path,
            self.window.image_data,
        )
        self.assertEqual((self.window.image.width(), self.window.image.height()), (20, 20))
        self.assertEqual(len(cropped.boxes), 1)
        self.assertEqual(
            cropped.boxes[0].points,
            ((1, 1), (10, 1), (10, 10), (1, 10)),
        )
        entry = self.window._latest_image_processing_recovery()
        self.assertEqual(len(entry.payload[0].resources), 2)

        recovery = self.window.image_processing.recover(
            entry.entry_id,
            selected_paths=(self.image_path,),
        )
        self.assertEqual(recovery.reload_images, (self.image_path,))
        restored_image = QImage(self.image_path)
        restored = AnnotationDocument.load(
            annotation_path,
            self.image_path,
            restored_image,
        )
        self.assertEqual((restored_image.width(), restored_image.height()), (40, 40))
        self.assertEqual(len(restored.boxes), 2)

    def test_drawing_after_crop_recovery_uses_the_restored_geometry_baseline(self):
        trash_dir = os.path.join(self.temporary.name, "trash-draw-after-recovery")
        os.makedirs(trash_dir)
        self.window.system_trash = _FakeTrash(trash_dir)
        self.window.enter_crop_mode()
        self.window.crop_overlay.set_region(CropRegion(5, 6, 20, 18))
        self.assertTrue(self.window.apply_crop())
        entry = self.window._latest_image_processing_recovery()
        with patch.object(
            self.window,
            "_choose_image_recovery_paths",
            return_value=(self.image_path,),
        ):
            self.window._confirm_file_recovery(entry.entry_id)

        restored = self.window.annotation_scene.capture(self.image_path)
        self.assertEqual(restored.image_size, (40, 40))
        self.assertEqual(
            restored,
            self.window.annotation_editing.view.snapshot,
        )

        self.window.create_shape()
        self.window.canvas.current = Shape()
        self.window._annotation_drawing_state_changed(True)
        self.assertTrue(self.window.annotation_editing.pending)

    def test_crop_recovery_blocks_unsaved_annotation_changes(self):
        trash_dir = os.path.join(self.temporary.name, "trash-dirty-recovery")
        os.makedirs(trash_dir)
        self.window.system_trash = _FakeTrash(trash_dir)
        self.window.enter_crop_mode()
        self.window.crop_overlay.set_region(CropRegion(5, 6, 20, 18))
        self.assertTrue(self.window.apply_crop())
        entry = self.window._latest_image_processing_recovery()
        self.window.annotation_clipboard = [(
            "cat",
            ((1, 1), (5, 1), (5, 5), (1, 5)),
            None,
            None,
            False,
        )]
        self.window.paste_copied_bounding_boxes()

        with self.assertRaises(ImageRecoveryBlocked):
            self.window.image_processing.recover(
                entry.entry_id,
                selected_paths=(self.image_path,),
            )

        self.assertEqual(
            (self.window.image.width(), self.window.image.height()),
            (20, 18),
        )
        self.assertTrue(self.window.annotation_editing.view.dirty)

    def test_image_recovery_uses_explicit_subset_without_rescanning_annotations(self):
        entry = SimpleNamespace(
            operation=ImageProcessingOperation.PROCESS,
            recoverable=True,
            entry_id="image",
            created_at=datetime.now(timezone.utc),
            payload=(SimpleNamespace(original_path=self.image_path),),
            target_count=1,
        )
        outcome = SimpleNamespace(
            restored_paths=(self.image_path,),
            renamed=(),
            review_result=None,
            reload_images=(),
        )
        with patch.object(
            type(self.window.image_processing),
            "recovery_entries",
            new_callable=PropertyMock,
            return_value=(entry,),
        ), patch.object(
            self.window,
            "_choose_image_recovery_paths",
            return_value=(self.image_path,),
        ), patch.object(
            self.window.image_processing,
            "recover",
            return_value=outcome,
        ) as recover, patch.object(
            self.window,
            "rescan_annotation_workspace",
        ) as rescan, patch.object(
            self.window,
            "_refresh_current_image_pixels",
        ):
            self.window._confirm_file_recovery(entry.entry_id)

        recover.assert_called_once_with(
            entry.entry_id,
            selected_paths=(self.image_path,),
        )
        rescan.assert_not_called()

    def test_failed_image_projection_blocks_editing_but_keeps_recovery(self):
        recovery_entry = SimpleNamespace(
            operation=ImageProcessingOperation.PROCESS,
            recoverable=True,
        )
        self.window.actions.undoImageProcessing.setEnabled(False)

        with patch.object(
            type(self.window.image_processing),
            "recovery_entries",
            new_callable=PropertyMock,
            return_value=(recovery_entry,),
        ):
            self.window._project_image_processing(SimpleNamespace(
                kind=ImageProcessingProjectionKind.PROJECTION_FAILED,
            ))

            self.assertFalse(self.window.canvas.isEnabled())
            for action in (
                self.window.actions.create,
                self.window.actions.save,
                self.window.actions.openNext,
                self.window.actions.cropImage,
                self.window.actions.transformImage,
            ):
                self.assertFalse(action.isEnabled())
            self.assertTrue(
                self.window.actions.undoImageProcessing.isEnabled()
            )

            self.window._project_image_processing(SimpleNamespace(
                kind=ImageProcessingProjectionKind.RECOVERY,
                outcome=SimpleNamespace(
                    restored_paths=(),
                    reload_images=(),
                ),
                paths=(),
            ))

            self.assertTrue(self.window.canvas.isEnabled())
            self.assertTrue(self.window.actions.create.isEnabled())


class _FakeTrash:
    def __init__(self, directory):
        self.directory = directory
        self.counter = 0

    def preflight(self, _paths):
        return None

    def move(self, path):
        self.counter += 1
        destination = os.path.join(
            self.directory, "%d-%s" % (self.counter, os.path.basename(path))
        )
        shutil.move(path, destination)
        return TrashIdentity("path", destination, path)

    @staticmethod
    def exists(identity):
        return os.path.exists(identity.token)

    @staticmethod
    def restore(identity, destination):
        shutil.move(identity.token, destination)


if __name__ == "__main__":
    unittest.main()
