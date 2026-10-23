"""Cached Draw-mode pixels must match ordinary painting after view/state changes."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QImage, QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget

from labelimg.canvas.shape import Shape
from labelimg.canvas.widget import Canvas


class DrawingSceneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font_path = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', 'msyh.ttc')
        if os.path.isfile(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                cls.app.setFont(QFont(families[0], 9))

    def setUp(self):
        self.canvas = Canvas()
        self.canvas.resize(280, 220)
        source = QPixmap(260, 200)
        source.fill(QColor('#606060'))
        self.canvas.load_pixmap(source)
        self.first = self.box('long label', (30, 50, 115, 135), '#f29637')
        self.peer = self.box('peer', (65, 75, 170, 155), '#3aa4ed')
        self.other = self.box('other', (185, 40, 245, 110), '#c873da')
        self.canvas.load_shapes([self.first, self.peer, self.other])
        self.canvas.set_mode(Canvas.CREATE)
        self.canvas.set_auto_hide_overlapping(True)
        self.canvas.grab()  # Initialize the Canvas status-background palette.

    def tearDown(self):
        self.canvas.restore_cursor()
        self.canvas.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    @staticmethod
    def box(label, rect, color):
        shape = Shape(label=label, paint_label=True)
        left, top, right, bottom = rect
        for point in ((left, top), (right, top), (right, bottom), (left, bottom)):
            shape.add_point(QPointF(*point))
        shape.close()
        shape.line_color = QColor(color)
        return shape

    def move(self, point):
        QApplication.sendEvent(self.canvas, QMouseEvent(
            QEvent.MouseMove, self.canvas.image_to_widget(QPointF(*point)),
            Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        ))

    def assert_matches_reference(self, rect=None):
        def capture():
            pixmap = self.canvas.grab() if rect is None else self.canvas.grab(rect)
            return pixmap.toImage().convertToFormat(QImage.Format_RGB32)

        cached = capture()
        # Bypass only the cache; the same Canvas paints the full reference scene.
        with patch.object(self.canvas._drawing_scene_cache, 'paint', return_value=False):
            reference = capture()
        self.assertEqual(cached.size(), reference.size())
        a = cached.bits().asstring(cached.byteCount())
        b = reference.bits().asstring(reference.byteCount())
        # Compositing overlapping antialiased edges onto one retained layer
        # adds up to two 8-bit rounding levels at fractional screen densities.
        self.assertLessEqual(max(abs(x-y) for x, y in zip(a, b)), 2)

    def test_crossing_overlapping_boxes_and_restoring_leaves_no_old_pixels(self):
        for point in ((10, 20), (40, 60), (80, 90), (140, 145), (205, 65), (10, 20)):
            with self.subTest(point=point):
                self.move(point)
                self.assert_matches_reference()

    def test_edit_hover_selection_and_drag_reuse_unchanged_shapes(self):
        self.canvas.resize(640, 220)
        self.other.move_by(QPointF(300, 0))
        self.canvas.set_mode(Canvas.EDIT)
        self.move((10, 20))
        self.assert_matches_reference()
        with patch.object(self.other, 'paint', wraps=self.other.paint) as paint:
            for point in ((35, 55), (80, 90), (140, 145), (10, 20)):
                self.move(point)
                self.canvas.grab()
            self.assertEqual(paint.call_count, 0,
                             'hovering unrelated boxes repaints the whole scene')
        for point in ((35, 55), (80, 90), (140, 145), (10, 20)):
            self.move(point)
            self.assert_matches_reference()
        self.canvas.set_selected_shapes([self.first])
        self.assert_matches_reference()
        self.first.move_by(QPointF(16, 10))
        self.assert_matches_reference()

    def test_mutations_refresh_geometry_text_color_selection_and_visibility(self):
        self.move((10, 20))
        self.assert_matches_reference()
        for change in (
            lambda: self.first.move_by(QPointF(15, 20)),
            lambda: setattr(self.first, 'label', 'renamed with much longer text'),
            lambda: setattr(self.first, 'line_color', QColor('#36cb87')),
            lambda: self.canvas.set_selected_shapes([self.first]),
            lambda: setattr(self.first, 'paint_label', False),
            lambda: self.canvas.set_shape_visible(self.peer, False),
            lambda: self.canvas.set_shape_visible(self.peer, True),
            lambda: self.canvas.set_selected_shapes([]),
            lambda: setattr(self.canvas, 'label_font_size', 14),
        ):
            change()
            self.assert_matches_reference()

    def test_order_zoom_offset_and_source_replacement_preserve_rendering(self):
        self.move((10, 20))
        self.assert_matches_reference()
        self.canvas.shapes.reverse()
        self.assert_matches_reference()
        for scale in (0.5, 1.0, 2.0, 3.0):
            self.canvas.scale = scale
            self.canvas.set_view_offset(QPointF(7.25, 11.5))
            self.assert_matches_reference()
        source = QPixmap(130, 100)
        source.fill(QColor('#abcade'))
        self.canvas.replace_pixmap(source, logical_size=(260, 200))
        self.assert_matches_reference()

    def test_pending_preview_and_ctrl_selection_keep_same_composition(self):
        self.move((45, 60))
        self.assert_matches_reference()
        self.canvas.handle_drawing(QPointF(45, 60))
        for point in ((90, 60), (90, 125), (200, 180)):
            self.move(point)
            self.assert_matches_reference()
        self.canvas.cancel_current_drawing()
        self.canvas.set_multi_selection_mode(True)
        self.assert_matches_reference()
        self.canvas.set_multi_selection_mode(False)
        self.assert_matches_reference()

    def test_small_budget_falls_back_and_mode_exit_releases_layer(self):
        self.canvas.handle_drawing(QPointF(45, 60))
        self.move((90, 125))
        self.assert_matches_reference()
        self.assertFalse(self.canvas._drawing_scene_cache._layer.isNull())
        with patch.object(self.canvas._drawing_scene_cache, 'MAX_PIXELS', 1):
            self.assert_matches_reference()
            self.assertTrue(self.canvas._drawing_scene_cache._layer.isNull())
        self.assert_matches_reference()
        self.canvas.set_mode(Canvas.EDIT)
        self.assertTrue(self.canvas._drawing_scene_cache._layer.isNull())

    def test_scrolled_viewport_with_nonzero_origin_matches_reference(self):
        parent = QWidget()
        parent.resize(180, 140)
        self.canvas.setParent(parent)
        self.canvas.move(-40, -25)
        parent.show()
        self.canvas.show()
        self.app.processEvents()
        try:
            rect = self.canvas.visibleRegion().boundingRect()
            self.assertGreater(rect.x(), 0)
            self.assertGreater(rect.y(), 0)
            self.canvas.handle_drawing(QPointF(15, 25))
            for point in ((100, 110), (150, 175), (45, 60), (15, 25)):
                self.move(point)
                self.assert_matches_reference(rect)
        finally:
            self.canvas.setParent(None)
            parent.deleteLater()


if __name__ == '__main__':
    unittest.main()
