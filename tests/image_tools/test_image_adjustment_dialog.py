import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog

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

    def test_controls_preview_and_transient_undo_restore_safe_defaults(self):
        dialog = ImageAdjustmentDialog(self.first, (self.first, self.second))
        self.assertFalse(dialog.apply_button.isEnabled())

        dialog.brightness_spin.setValue(25)

        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertTrue(dialog.undo_button.isEnabled())
        QTest.mouseClick(dialog.undo_button, Qt.LeftButton)
        self.assertEqual(dialog.brightness_spin.value(), 0)
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertTrue(dialog.redo_button.isEnabled())

    def test_selected_scope_returns_composed_adjustment_request(self):
        dialog = ImageAdjustmentDialog(self.first, (self.first, self.second))
        dialog.scope_combo.setCurrentIndex(1)
        dialog.contrast_spin.setValue(1.4)
        dialog.gamma_spin.setValue(0.8)
        dialog.grayscale_checkbox.setChecked(True)

        QTest.mouseClick(dialog.apply_button, Qt.LeftButton)

        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.request.paths, (self.first, self.second))
        self.assertEqual(dialog.request.options.contrast, 1.4)
        self.assertEqual(dialog.request.options.gamma, 0.8)
        self.assertTrue(dialog.request.options.grayscale)

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
                dialog.brightness_spin.setValue(value)

        self.assertEqual(prepare.call_count, initial_calls)


if __name__ == "__main__":
    unittest.main()
