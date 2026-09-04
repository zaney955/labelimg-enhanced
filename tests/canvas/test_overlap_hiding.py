"""Temporary overlap suppression must never replace explicit box visibility."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QColor, QKeyEvent, QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication

from labelimg.canvas.shape import Shape
from labelimg.canvas.widget import Canvas


class OverlapHidingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = Canvas()
        self.canvas.resize(200, 160)
        pixmap = QPixmap(200, 160)
        pixmap.fill(QColor("#505050"))
        self.canvas.load_pixmap(pixmap)
        self.shape = Shape(label="existing")
        for x, y in ((40, 40), (100, 40), (100, 100), (40, 100)):
            self.shape.add_point(QPointF(x, y))
        self.shape.close()
        self.canvas.load_shapes([self.shape])
        self.canvas.set_mode(Canvas.CREATE)

    def tearDown(self):
        self.canvas.restore_cursor()
        self.canvas.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def start_box(self, start=(20, 20), end=(80, 80)):
        self.canvas.cancel_current_drawing()
        self.canvas.handle_drawing(QPointF(*start))
        self.canvas.line[1] = QPointF(*end)

    def assert_box_painted(self, expected, shape=None):
        shape = shape or self.shape
        # This helper observes visibility during a complete layer rebuild.
        # Incremental rendering is checked separately against reference pixels.
        self.canvas._drawing_scene_cache.clear()
        with patch.object(shape, "paint", wraps=shape.paint) as paint:
            self.canvas.grab()
        self.assertEqual(bool(paint.call_count), expected)

    def move_pointer(self, point):
        QApplication.sendEvent(self.canvas, QMouseEvent(
            QEvent.MouseMove, self.canvas.image_to_widget(QPointF(*point)),
            Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        ))

    def set_control(self, pressed):
        QApplication.sendEvent(self.canvas, QKeyEvent(
            QEvent.KeyPress if pressed else QEvent.KeyRelease,
            Qt.Key_Control, Qt.ControlModifier if pressed else Qt.NoModifier,
        ))

    def test_predraw_pointer_hiding_is_opt_in_and_stable_across_repaints(self):
        self.move_pointer((60, 60))
        self.assert_box_painted(True)
        self.canvas.set_auto_hide_overlapping(True)
        for _ in range(4):
            self.assert_box_painted(False)
        # Neither label text above the box nor the extended guides count.
        for point in ((60, 30), (150, 60), (39, 60)):
            self.move_pointer(point)
            self.assert_box_painted(True)
        self.move_pointer((60, 60))
        self.assert_box_painted(False)
        self.canvas.set_auto_hide_overlapping(False)
        self.assert_box_painted(True)

    def test_pointer_crossing_does_not_repaint_unaffected_boxes(self):
        other = self.shape.copy()
        other.move_by(QPointF(100, 0))
        self.canvas.load_shapes([self.shape, other])
        self.canvas.set_auto_hide_overlapping(True)
        self.canvas.show()
        self.app.processEvents()
        self.move_pointer((20, 60))
        with patch.object(other, "paint", wraps=other.paint) as paint:
            self.move_pointer((60, 60))
            self.move_pointer((20, 60))
        self.assertEqual(paint.call_count, 0)

    def test_predraw_hides_all_containing_boxes_and_preserves_explicit_visibility(self):
        inner = self.shape.copy()
        inner.points = [QPointF(x, y) for x, y in (
            (50, 50), (70, 50), (70, 70), (50, 70),
        )]
        other = self.shape.copy()
        other.move_by(QPointF(100, 0))
        hidden = self.shape.copy()
        self.canvas.load_shapes([self.shape, inner, other, hidden])
        self.canvas.set_shape_visible(hidden, False)
        self.canvas.set_auto_hide_overlapping(True)
        self.move_pointer((60, 60))
        for shape in (self.shape, inner, hidden):
            self.assert_box_painted(False, shape)
        self.assert_box_painted(True, other)
        self.assertEqual(self.canvas.visible, {hidden: False})
        self.move_pointer((90, 90))
        self.assert_box_painted(True, inner)
        self.assert_box_painted(False)
        self.move_pointer((120, 120))
        self.assert_box_painted(True)
        self.assert_box_painted(False, hidden)

    def test_predraw_bounds_include_edges_and_image_origin_at_different_zooms(self):
        self.shape.move_by(QPointF(-40, -40))
        self.canvas.set_auto_hide_overlapping(True)
        for scale in (0.5, 1.0, 3.0):
            self.canvas.scale = scale
            for point, hidden in (
                ((0, 0), True), ((60, 60), True), ((60, 20), True),
                ((-2, 20), False), ((20, -2), False), ((62, 20), False),
            ):
                with self.subTest(scale=scale, point=point):
                    self.move_pointer(point)
                    self.assert_box_painted(not hidden)

    def test_first_click_and_zero_area_continue_pointer_hiding(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.move_pointer((50, 50))
        self.assert_box_painted(False)
        QApplication.sendEvent(self.canvas, QMouseEvent(
            QEvent.MouseButtonPress, self.canvas.image_to_widget(QPointF(50, 50)),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        ))
        self.assertEqual(self.canvas.line[0], self.canvas.line[1])
        self.assert_box_painted(False)
        self.move_pointer((70, 50))
        self.assert_box_painted(False)
        self.set_control(True)
        self.assert_box_painted(True)
        self.set_control(False)
        self.assert_box_painted(False)
        self.move_pointer((130, 50))
        self.assert_box_painted(True)
        self.move_pointer((130, 80))
        # Positive-area overlap hides the box even with the pointer outside it.
        self.assert_box_painted(False)
        self.set_control(True)
        self.assert_box_painted(False)
        self.set_control(False)

    def test_control_temporarily_restores_boxes_without_pointer_movement(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.move_pointer((60, 60))
        self.assert_box_painted(False)
        self.set_control(True)
        self.assert_box_painted(True)
        self.set_control(False)
        self.assert_box_painted(False)

    def test_leave_reenter_mode_and_scene_changes_restore_predraw_boxes(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.move_pointer((60, 60))
        self.assert_box_painted(False)
        QApplication.sendEvent(self.canvas, QEvent(QEvent.Leave))
        self.assert_box_painted(True)
        position = self.canvas.mapToGlobal(
            self.canvas.image_to_widget(QPointF(60, 60)).toPoint(),
        )
        with patch("labelimg.canvas.widget.QCursor.pos", return_value=position):
            QApplication.sendEvent(self.canvas, QEvent(QEvent.Enter))
        self.assert_box_painted(False)
        for mode, painted in ((Canvas.EDIT, True), (Canvas.CREATE, False), (Canvas.PAN, True)):
            self.canvas.set_mode(mode)
            self.assert_box_painted(painted)
        self.canvas.set_mode(Canvas.CREATE)
        self.canvas.load_shapes([self.shape])
        self.assert_box_painted(True)
        self.assertTrue(self.canvas.auto_hide_overlapping)

    def test_view_changes_reproject_stationary_pointer(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.move_pointer((60, 60))
        self.assert_box_painted(False)
        self.canvas.scale = 2.0
        self.canvas.refresh_tracked_pointer_coordinates()
        self.assertEqual(self.canvas._last_pointer_pos, QPointF(30, 30))
        self.assert_box_painted(True)
        self.canvas.scale = 1.0
        self.canvas.refresh_tracked_pointer_coordinates()
        self.assert_box_painted(False)

    def test_default_off_and_toggling_during_drawing(self):
        self.start_box()
        self.assert_box_painted(True)
        self.canvas.set_auto_hide_overlapping(True)
        self.assert_box_painted(False)
        self.canvas.set_auto_hide_overlapping(False)
        self.assert_box_painted(True)

    def test_positive_area_intersection_including_containment_and_reverse_drawing(self):
        self.canvas.set_auto_hide_overlapping(True)
        for start, end, hidden in (
            ((20, 20), (80, 80), True),     # Partial overlap.
            ((50, 50), (60, 60), True),     # Pending box inside existing box.
            ((10, 10), (130, 130), True),   # Existing box inside pending box.
            ((40, 40), (100, 100), True),   # Identical bounds.
            ((80, 80), (20, 20), True),     # Reverse drawing.
            ((20, 20), (40.1, 40.1), True), # Fractional image coordinates.
            ((20, 20), (40, 40), False),    # Corner contact.
            ((10, 50), (40, 80), False),    # Edge contact.
            ((20, 20), (30, 30), False),    # Disjoint.
        ):
            with self.subTest(start=start, end=end):
                self.start_box(start, end)
                self.assert_box_painted(not hidden)

    def test_endpoint_movement_restores_boxes_without_changing_manual_visibility(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.start_box()
        original_points = list(self.shape.points)
        self.assert_box_painted(False)
        self.assertTrue(self.canvas.isVisible(self.shape))
        self.assertEqual(self.canvas.visible, {})
        self.canvas.line[1] = QPointF(30, 30)
        self.assert_box_painted(True)
        self.canvas.set_shape_visible(self.shape, False)
        self.canvas.line[1] = QPointF(80, 80)
        self.assert_box_painted(False)
        self.canvas.cancel_current_drawing()
        self.assert_box_painted(False)
        self.assertFalse(self.canvas.isVisible(self.shape))
        self.assertEqual(self.shape.points, original_points)

    def test_cancellation_mode_changes_and_scene_replacement_clear_suppression(self):
        self.canvas.set_auto_hide_overlapping(True)
        for cleanup in (
            self.canvas.cancel_current_drawing,
            lambda: self.canvas.set_mode(Canvas.EDIT),
            lambda: self.canvas.set_mode(Canvas.PAN),
            lambda: self.canvas.load_shapes([self.shape]),
        ):
            self.canvas.set_mode(Canvas.CREATE)
            self.start_box()
            self.assert_box_painted(False)
            cleanup()
            self.assert_box_painted(True)
            self.assertTrue(self.canvas.auto_hide_overlapping)

    def test_geometry_confirmation_keeps_suppression_until_creation_ends(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.start_box()
        observed = []

        def choose_label():
            self.assertIsNone(self.canvas.current)
            self.assert_box_painted(False)
            observed.append(True)
            self.canvas.set_last_label("new")

        self.canvas.newShape.connect(choose_label)
        self.canvas.handle_drawing(QPointF(80, 80))
        self.assertEqual(observed, [True])
        self.assert_box_painted(True)

    def test_square_constraint_uses_drawn_corner_not_raw_pointer(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.canvas.set_drawing_shape_to_square(True)
        self.canvas.handle_drawing(QPointF(20, 20))
        QApplication.sendEvent(self.canvas, QMouseEvent(
            QEvent.MouseMove, self.canvas.image_to_widget(QPointF(180, 30)),
            Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        ))
        self.assertEqual(self.canvas.line[1], QPointF(30, 30))
        self.assert_box_painted(True)


if __name__ == "__main__":
    unittest.main()
