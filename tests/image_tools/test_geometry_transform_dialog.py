import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog

from labelimg.image_tools.ui.geometry_dialog import GeometryTransformDialog
from labelimg.image_tools.application.geometry_transform import GeometryOperation


class GeometryTransformDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.first = self._image("first.png", 80, 40)
        self.second = self._image("second.png", 60, 30)

    def tearDown(self):
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temporary.cleanup()

    def _image(self, name, width, height):
        path = os.path.join(self.temporary.name, name)
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(path))
        return path

    def test_dialog_defaults_to_current_scope_and_shows_preview(self):
        dialog = GeometryTransformDialog(
            self.first,
            (self.first, self.second),
            preselected=GeometryOperation.ROTATE_CLOCKWISE,
        )
        dialog.show()
        self.app.processEvents()

        self.assertEqual(dialog.scope_combo.currentData(), "current")
        self.assertEqual(
            dialog.operation_combo.currentData(),
            GeometryOperation.ROTATE_CLOCKWISE,
        )
        self.assertFalse(dialog.preview_label.pixmap().isNull())
        self.assertEqual(dialog.preview_size_label.text(), "40 × 80")
        dialog.reject()

    def test_selected_resize_request_uses_one_proportional_percentage(self):
        dialog = GeometryTransformDialog(
            self.first,
            (self.first, self.second),
            preselected=GeometryOperation.RESIZE,
        )
        dialog.scope_combo.setCurrentIndex(1)
        dialog.percent_spin.setValue(50)

        QTest.mouseClick(dialog.apply_button, Qt.LeftButton)

        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.request.paths, (self.first, self.second))
        self.assertEqual(dialog.request.operation, GeometryOperation.RESIZE)
        self.assertEqual(dialog.request.resize_percent, 50)


if __name__ == "__main__":
    unittest.main()
