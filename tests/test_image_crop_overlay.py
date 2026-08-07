import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QPixmap
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication, QWidget

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
        self.viewport = QWidget()
        self.viewport.resize(1100, 300)
        self.controls = CropControlBar(self.overlay, self.viewport)
        self.canvas.show()
        self.viewport.show()
        self.overlay.begin((240, 180))
        self.controls.begin((240, 180))
        self.app.processEvents()

    def tearDown(self):
        self.overlay.finish()
        self.controls.finish()
        self.canvas.close()
        self.viewport.close()
        self.canvas.deleteLater()
        self.viewport.deleteLater()
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

    def test_full_edge_hit_band_resizes_away_from_midpoint_handles(self):
        self.overlay.set_region(CropRegion(50, 40, 100, 80))

        QTest.mousePress(
            self.overlay,
            Qt.LeftButton,
            pos=QPoint(75, 40),
        )
        self.drag_move(QPoint(75, 25))
        QTest.mouseRelease(
            self.overlay,
            Qt.LeftButton,
            pos=QPoint(75, 25),
        )

        self.assertEqual(
            self.overlay.region,
            CropRegion(50, 25, 100, 95),
        )

    def test_pointer_coordinates_are_live_before_a_region_exists(self):
        self.assertIsNone(self.overlay.region)
        self.assertTrue(self.controls.spins["x"].isEnabled())
        self.assertTrue(self.controls.spins["y"].isEnabled())
        self.assertTrue(self.controls.spins["x"].isReadOnly())
        self.assertTrue(self.controls.spins["y"].isReadOnly())
        self.assertFalse(self.controls.spins["width"].isEnabled())
        self.assertFalse(self.controls.spins["height"].isEnabled())
        self.assertEqual(self.controls.spins["width"].value(), 0)
        self.assertEqual(self.controls.spins["height"].value(), 0)

        self.hover_move(QPoint(37, 29))

        self.assertEqual(self.controls.spins["x"].value(), 37)
        self.assertEqual(self.controls.spins["y"].value(), 29)
        self.assertIsNone(self.overlay.region)

    def test_pointer_coordinates_keep_last_valid_value_outside_image(self):
        self.hover_move(QPoint(37, 29))
        self.hover_move(QPoint(-5, -5))

        self.assertEqual(self.controls.spins["x"].value(), 37)
        self.assertEqual(self.controls.spins["y"].value(), 29)

    def test_edge_hit_tolerance_is_fixed_in_screen_pixels(self):
        self.overlay.set_region(CropRegion(50, 40, 100, 80))
        for scale in (1.0, 2.0):
            self.canvas.scale = scale
            self.canvas.resize(round(240 * scale), round(180 * scale))
            self.overlay._sync_geometry()
            rect = self.overlay._widget_region(self.overlay.region)
            edge_x = round(rect.left() + rect.width() / 3)

            self.assertEqual(
                self.overlay._hit_target(
                    QPoint(edge_x, round(rect.top()) + 5)
                ),
                "n",
            )
            self.assertIsNone(self.overlay._hit_target(
                QPoint(edge_x, round(rect.top()) + 7)
            ))
            self.assertEqual(
                self.overlay._hit_target(QPoint(
                    round(rect.left()) + 4,
                    round(rect.top()) + 4,
                )),
                "nw",
            )

    def test_floating_controls_drag_within_viewport_and_reset_next_session(self):
        expected_x = (self.viewport.width() - self.controls.width()) // 2
        self.assertEqual(self.controls.pos(), QPoint(expected_x, 8))

        start = self.controls.pos()
        self.controls._begin_drag(
            self.controls.mapToGlobal(QPoint(5, 5))
        )
        self.controls._continue_drag(
            self.viewport.mapToGlobal(QPoint(1000, 250))
        )
        self.controls._drag_offset = None

        self.assertNotEqual(self.controls.pos(), start)
        self.assertGreaterEqual(self.controls.x(), 0)
        self.assertGreaterEqual(self.controls.y(), 0)
        self.assertLessEqual(
            self.controls.x() + self.controls.width(),
            self.viewport.width(),
        )
        self.assertLessEqual(
            self.controls.y() + self.controls.height(),
            self.viewport.height(),
        )

        self.controls.finish()
        self.controls.begin((240, 180))

        self.assertEqual(self.controls.pos(), QPoint(expected_x, 8))

    def drag_move(self, point):
        event = QMouseEvent(
            QEvent.MouseMove,
            QPointF(point),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        QApplication.sendEvent(self.overlay, event)

    def hover_move(self, point):
        event = QMouseEvent(
            QEvent.MouseMove,
            QPointF(point),
            Qt.NoButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
        QApplication.sendEvent(self.overlay, event)


if __name__ == "__main__":
    unittest.main()
