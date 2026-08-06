import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, PropertyMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent
from PyQt5.QtGui import QColor, QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QDialog

from labelimg.app import MainWindow
from labelimg.file_recovery import RecoveryOperation
from labelimg.i18n import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.shape import Shape


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
        self.window = MainWindow(
            default_prefdef_class_file=classes_path,
            default_save_dir="",
        )
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
                self.window.actions.removeColoredFrames,
                actions[1],
                self.window.actions.undoImageProcessing,
            ],
        )
        self.assertTrue(actions[1].isSeparator())
        self.assertEqual(
            self.window.actions.removeColoredFrames.text(),
            "Remove Red/Yellow Frames…",
        )
        self.assertEqual(
            self.window.actions.undoImageProcessing.text(),
            "Undo Last Image Processing…",
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
            "去除红框/黄框…",
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
            "labelimg.image_tools.dialog.ImageToolsDialog",
            return_value=fake_dialog,
        ) as dialog_type:
            self.window.open_remove_colored_frames()

        args, kwargs = dialog_type.call_args
        self.assertEqual(args[0], self.image_path)
        self.assertEqual(args[1], selected)
        self.assertIs(kwargs["commit"].__self__, self.window.file_operations)
        self.assertIs(kwargs["parent"], self.window)

    def test_pending_annotation_gesture_blocks_workspace_entry(self):
        self.window.annotation_editing.set_pending("drag", lambda: None)
        with patch(
            "labelimg.image_tools.dialog.ImageToolsDialog",
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
            operation=RecoveryOperation.IMAGE_PROCESSING,
            recoverable=True,
            entry_id="image",
        )
        with patch.object(
            type(self.window.file_operations),
            "recovery_entries",
            new_callable=PropertyMock,
            return_value=(ordinary, image_entry),
        ):
            self.window.update_image_menu()
            latest = self.window._latest_image_processing_recovery()

        self.assertIs(latest, image_entry)
        self.assertTrue(self.window.actions.undoImageProcessing.isEnabled())

    def test_image_recovery_uses_explicit_subset_without_rescanning_annotations(self):
        entry = SimpleNamespace(
            operation=RecoveryOperation.IMAGE_PROCESSING,
            recoverable=True,
            entry_id="image",
            payload=(SimpleNamespace(original_path=self.image_path),),
            target_count=1,
        )
        outcome = SimpleNamespace(
            restored_paths=(self.image_path,),
            renamed=(),
            review_result=None,
        )
        with patch.object(
            type(self.window.file_operations),
            "recovery_entries",
            new_callable=PropertyMock,
            return_value=(entry,),
        ), patch.object(
            self.window,
            "_choose_image_recovery_paths",
            return_value=(self.image_path,),
        ), patch.object(
            self.window.file_operations,
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


if __name__ == "__main__":
    unittest.main()
