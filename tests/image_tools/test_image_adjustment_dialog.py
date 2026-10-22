import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QSlider

from labelimg.image_tools.infrastructure.image_codec import ImageFileCodec
from labelimg.image_tools.ui.adjustment_dialog import ImageAdjustmentDialog


class ImageAdjustmentDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.first = self._image("first.png", QColor(30, 60, 120))
        self.second = self._image("second.png", QColor(180, 90, 20))

    def tearDown(self):
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temporary.cleanup()

    def _image(self, name, color):
        path = os.path.join(self.temporary.name, name)
        image = QImage(32, 24, QImage.Format_RGB32)
        image.fill(color)
        self.assertTrue(image.save(path))
        return path

    def test_preview_expands_beside_settings_without_changing_adjustments(self):
        dialog = ImageAdjustmentDialog(self.first, (self.first, self.second))
        dialog.brightness_slider.setValue(25)
        dialog.show()
        self.app.processEvents()
        QTest.qWait(80)
        dialog.resize(1180, 760)
        self.app.processEvents()
        QTest.qWait(80)
        preview = dialog.preview_label
        pixmap = preview.pixmap()
        self.assertTrue(abs(pixmap.width() - preview.width()) <= 2 or
                        abs(pixmap.height() - preview.height()) <= 2)
        self.assertLess(preview.mapTo(dialog, QPoint(preview.width(), 0)).x(),
                        dialog.scope_combo.mapTo(dialog, QPoint()).x())
        self.assertEqual(dialog.brightness_slider.value(), 25)
        self.assertIsNone(dialog.request)
        dialog.deleteLater()

    def test_auto_adjust_updates_three_sliders_and_preserves_grayscale(self):
        dialog = ImageAdjustmentDialog(self.first, (self.first, self.second))
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn(dialog.auto_adjust_button.text(), {"Auto Adjust", "自动调整"})
        dialog.grayscale_checkbox.setChecked(True)

        suggestion = SimpleNamespace(brightness=18, contrast=1.4, gamma=0.8)
        with patch(
            "labelimg.image_tools.ui.adjustment_dialog."
            "suggest_auto_adjustment",
            return_value=suggestion,
        ) as suggest:
            QTest.mouseClick(dialog.auto_adjust_button, Qt.LeftButton)

        suggest.assert_called_once()
        self.assertIs(suggest.call_args.args[0], dialog._preview.pixels)
        self.assertEqual(dialog.brightness_slider.value(), 18)
        self.assertEqual(dialog.contrast_slider.value(), 14)
        self.assertEqual(dialog.gamma_slider.value(), 8)
        self.assertTrue(dialog.grayscale_checkbox.isChecked())
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertFalse(hasattr(dialog, "undo_button"))
        self.assertFalse(hasattr(dialog, "redo_button"))

    def test_selected_scope_returns_composed_adjustment_request(self):
        dialog = ImageAdjustmentDialog(self.first, (self.first, self.second))
        dialog.scope_combo.setCurrentIndex(1)
        dialog.contrast_slider.setValue(14)
        dialog.gamma_slider.setValue(8)
        dialog.grayscale_checkbox.setChecked(True)

        QTest.mouseClick(dialog.apply_button, Qt.LeftButton)

        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.request.paths, (self.first, self.second))
        self.assertEqual(dialog.request.options.contrast, 1.4)
        self.assertEqual(dialog.request.options.gamma, 0.8)
        self.assertTrue(dialog.request.options.grayscale)

    def test_reset_restores_all_adjustment_controls_to_safe_defaults(self):
        dialog = ImageAdjustmentDialog(self.first)
        self.assertIn(dialog.reset_button.text(), {"Reset", "重置"})
        self.assertFalse(dialog.reset_button.isEnabled())

        dialog.brightness_slider.setValue(25)
        dialog.contrast_slider.setValue(14)
        dialog.gamma_slider.setValue(8)
        dialog.grayscale_checkbox.setChecked(True)
        self.assertTrue(dialog.reset_button.isEnabled())

        QTest.mouseClick(dialog.reset_button, Qt.LeftButton)

        self.assertEqual(dialog.brightness_slider.value(), 0)
        self.assertEqual(dialog.contrast_slider.value(), 10)
        self.assertEqual(dialog.gamma_slider.value(), 10)
        self.assertFalse(dialog.grayscale_checkbox.isChecked())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertFalse(dialog.reset_button.isEnabled())

    def test_all_images_scope_returns_every_workspace_path(self):
        dialog = ImageAdjustmentDialog(
            self.first,
            (self.first,),
            workspace_paths=(self.first, self.second),
        )
        workspace_index = dialog.scope_combo.findData("workspace")

        self.assertGreaterEqual(workspace_index, 0)
        self.assertIn(
            dialog.scope_combo.itemText(workspace_index),
            {"All images (2)", "全部图像（2 张）"},
        )
        dialog.scope_combo.setCurrentIndex(workspace_index)
        dialog.brightness_slider.setValue(10)
        self.assertEqual(dialog.target_list.item(1).toolTip(), self.second)
        QTest.mouseClick(dialog.apply_button, Qt.LeftButton)

        self.assertEqual(dialog.request.paths, (self.first, self.second))

    def test_repeated_brightness_steps_do_not_repeat_full_image_prepare(self):
        prepared = SimpleNamespace(
            result_pixels=np.zeros((24, 32, 3), dtype=np.uint8),
            changed=False,
        )
        with patch(
            "labelimg.image_tools.application.adjustment."
            "ImageAdjustmentProcessor.prepare",
            return_value=prepared,
        ) as prepare:
            dialog = ImageAdjustmentDialog(self.first)
            initial_calls = prepare.call_count

            for value in range(1, 6):
                dialog.brightness_slider.setValue(value)

        self.assertEqual(prepare.call_count, initial_calls)

    def test_current_qimage_reuses_decoded_pixels_for_adaptive_preview(self):
        current = QImage(self.first)
        with patch.object(ImageFileCodec, "load_preview") as load_preview:
            dialog = ImageAdjustmentDialog(
                self.first,
                preview_image=current,
            )

        load_preview.assert_not_called()
        preview = dialog._preview.pixels
        self.assertLessEqual(
            preview.shape[0] * preview.shape[1],
            dialog.PREVIEW_MAX_PIXELS,
        )
        self.assertEqual(dialog._preview.source_size, (32, 24))

    def test_preview_allocation_failure_is_contained_in_the_dialog(self):
        dialog = ImageAdjustmentDialog(self.first)
        dialog.brightness_slider.setValue(10)

        with patch.object(
            dialog.preview_label,
            "setPixmap",
            side_effect=MemoryError("large-image preview allocation failed"),
        ):
            dialog._refresh_preview()

        self.assertIn(
            "large-image preview allocation failed",
            dialog.preview_label.text(),
        )
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertFalse(dialog.auto_adjust_button.isEnabled())

    def test_three_adjustments_are_sliders_with_compact_value_badges(self):
        dialog = ImageAdjustmentDialog(self.first)

        self.assertIsInstance(dialog.brightness_slider, QSlider)
        self.assertIsInstance(dialog.contrast_slider, QSlider)
        self.assertIsInstance(dialog.gamma_slider, QSlider)
        self.assertEqual(
            (dialog.brightness_slider.minimum(), dialog.brightness_slider.maximum()),
            (-100, 100),
        )
        self.assertEqual(dialog.brightness_value_label.text(), "0%")
        self.assertEqual(dialog.contrast_value_label.text(), "1.0×")
        self.assertEqual(dialog.gamma_value_label.text(), "1.0")

        dialog.brightness_slider.setValue(25)
        dialog.contrast_slider.setValue(14)
        dialog.gamma_slider.setValue(8)

        self.assertEqual(dialog.brightness_value_label.text(), "+25%")
        self.assertEqual(dialog.contrast_value_label.text(), "1.4×")
        self.assertEqual(dialog.gamma_value_label.text(), "0.8")

if __name__ == "__main__":
    unittest.main()
