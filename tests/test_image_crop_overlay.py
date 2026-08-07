import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QPixmap
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication

from labelimg.canvas import Canvas
from labelimg.image_tools.crop import CropRegion
from labelimg.image_tools.crop_ui import CropControlBar, CropOverlay


class ImageCropOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = Canvas()
        self.canvas.resize(240, 180)
        self.canvas.load_pixmap(QPixmap(240, 180))
        self.overlay = CropOverlay(self.canvas)
        self.controls = CropControlBar(self.overlay)
        self.canvas.show()
        self.overlay.begin((240, 180))
        self.controls.begin((240, 180))
        self.app.processEvents()

    def tearDown(self):
        self.canvas.close()
        self.controls.close()
        self.canvas.deleteLater()
        self.app.processEvents()

    def test_drag_creates_region_with_eight_fixed_screen_handles(self):
        QTest.mousePress(
            self.overlay,
            Qt.LeftButton,
            pos=QPoint(20, 25),
        )
        self.drag_move(QPoint(120, 85))
        QTest.mouseRelease(
            self.overlay,
            Qt.LeftButton,
            pos=QPoint(120, 85),
        )

        self.assertEqual(self.overlay.region, CropRegion(20, 25, 100, 60))
        self.assertEqual(len(self.overlay.handle_rects), 8)
        self.assertTrue(all(
            rect.width() == 9 and rect.height() == 9
            for rect in self.overlay.handle_rects.values()
        ))

    def test_ratio_keyboard_movement_and_transient_undo_redo(self):
        self.overlay.set_ratio((1, 1))
        QTest.mousePress(
            self.overlay,
            Qt.LeftButton,
            pos=QPoint(10, 10),
        )
        self.drag_move(QPoint(80, 50))
        QTest.mouseRelease(
            self.overlay,
            Qt.LeftButton,
            pos=QPoint(80, 50),
        )
        created = self.overlay.region
        self.assertEqual(created.width, created.height)

        QTest.keyClick(self.overlay, Qt.Key_Right, Qt.ShiftModifier)
        moved = self.overlay.region
        self.assertEqual(moved.x, created.x + 10)

        QTest.keyClick(self.overlay, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(self.overlay.region, created)
        QTest.keyClick(self.overlay, Qt.Key_Y, Qt.ControlModifier)
        self.assertEqual(self.overlay.region, moved)

    def test_enter_and_escape_request_apply_and_cancel(self):
        apply_spy = QSignalSpy(self.overlay.applyRequested)
        cancel_spy = QSignalSpy(self.overlay.cancelRequested)
        self.overlay.set_region(CropRegion(1, 1, 100, 100))

        QTest.keyClick(self.overlay, Qt.Key_Return)
        QTest.keyClick(self.overlay, Qt.Key_Escape)

        self.assertEqual(len(apply_spy), 1)
        self.assertEqual(len(cancel_spy), 1)

    def test_numeric_size_fields_remain_linked_under_fixed_ratio(self):
        self.overlay.set_region(CropRegion(10, 10, 40, 30))
        self.controls.ratio_combo.setCurrentIndex(2)
        self.assertEqual(
            self.overlay.region.width,
            self.overlay.region.height,
        )

        self.controls.spins["width"].setValue(50)

        self.assertEqual(self.overlay.region, CropRegion(10, 5, 50, 50))
        self.assertEqual(self.controls.spins["height"].value(), 50)

    def drag_move(self, point):
        event = QMouseEvent(
            QEvent.MouseMove,
            QPointF(point),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        QApplication.sendEvent(self.overlay, event)


if __name__ == "__main__":
    unittest.main()
