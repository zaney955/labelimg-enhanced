import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF, QSize
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication

from labelimg.canvas.widget import Canvas


class CanvasLogicalPixmapSizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_pixels_keep_full_image_geometry(self):
        canvas = Canvas()
        canvas.load_pixmap(QPixmap(20, 10), logical_size=QSize(200, 100))

        self.assertEqual(canvas.pixmap.size(), QSize(20, 10))
        self.assertEqual(canvas.pixmap_size, QSize(200, 100))
        self.assertEqual(canvas.minimumSizeHint(), QSize(200, 100))
        self.assertFalse(canvas.out_of_pixmap(QPointF(150, 75)))
        self.assertTrue(canvas.out_of_pixmap(QPointF(201, 75)))
        self.assertEqual(canvas.snap_point_to_canvas(240, 130), (200, 100, True))

    def test_replacing_preview_can_refine_pixels_without_changing_geometry(self):
        canvas = Canvas()
        canvas.load_pixmap(QPixmap(20, 10), logical_size=(200, 100))
        canvas.replace_pixmap(QPixmap(80, 40), logical_size=canvas.pixmap_size)

        self.assertEqual(canvas.pixmap.size(), QSize(80, 40))
        self.assertEqual(canvas.pixmap_size, QSize(200, 100))

    def test_default_interface_preserves_existing_pixmap_sized_behavior(self):
        canvas = Canvas()
        canvas.load_pixmap(QPixmap(120, 90))

        self.assertEqual(canvas.pixmap_size, QSize(120, 90))
        self.assertEqual(canvas.minimumSizeHint(), QSize(120, 90))


if __name__ == "__main__":
    unittest.main()
