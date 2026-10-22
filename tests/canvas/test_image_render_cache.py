"""Work and pixel regressions for moving over a large displayed image."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent, QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication
from labelimg.canvas.widget import Canvas
from labelimg.canvas.shape import Shape


class ImageRenderPerformanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mouse_burst_queues_paint_instead_of_blocking_each_event(self):
        canvas = Canvas()
        canvas.load_pixmap(QPixmap(1000, 700))
        canvas.resize(500, 350)
        canvas.scale = .5
        canvas.set_editing(False)
        canvas.show()
        self.app.processEvents()
        with patch.object(canvas, 'repaint') as repaint:
            for index in range(20):
                QApplication.sendEvent(canvas, QMouseEvent(
                    QEvent.MouseMove, QPointF(100 + index, 100),
                    Qt.NoButton, Qt.NoButton, Qt.NoModifier))
            repaint.assert_not_called()
        canvas.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_cached_background_matches_direct_render_across_transforms_and_dpr(self):
        from labelimg.canvas.image_layer import ImageLayerCache
        source = QImage(320, 180, QImage.Format_ARGB32_Premultiplied)
        source.fill(QColor(100, 150, 210, 180))
        painter = QPainter(source)
        painter.fillRect(20, 10, 100, 60, QColor('red'))
        painter.end()
        pixmap = QPixmap.fromImage(source)
        cache = ImageLayerCache()
        for density in (1., 1.25, 1.5):
            for scale in (.25, 1., 4.):
                outputs = []
                for cached in (False, True):
                    target = QImage(round(210 * density), round(160 * density),
                                    QImage.Format_ARGB32_Premultiplied)
                    target.setDevicePixelRatio(density)
                    target.fill(QColor('white'))
                    painter = QPainter(target)
                    painter.setRenderHint(QPainter.SmoothPixmapTransform)
                    painter.scale(scale, scale)
                    painter.translate(-3.5, 2.25)
                    if cached:
                        cache.paint(painter, pixmap, source.size(), QRect(0, 0, 210, 160))
                    else:
                        painter.drawPixmap(QRectF(source.rect()), pixmap, QRectF(pixmap.rect()))
                    painter.end()
                    outputs.append(target)
                self.assertEqual(outputs[0], outputs[1], (density, scale))

    def test_repeated_keyboard_nudges_keep_geometry_without_synchronous_paints(self):
        canvas = Canvas()
        canvas.load_pixmap(QPixmap(1000, 700))
        shape = Shape(label='box')
        for point in ((10, 10), (100, 10), (100, 80), (10, 80)):
            shape.add_point(QPointF(*point))
        shape.close()
        canvas.load_shapes([shape])
        canvas.select_shape(shape)
        with patch.object(canvas, 'repaint') as repaint:
            for _ in range(20):
                canvas.move_one_pixel('Right')
            repaint.assert_not_called()
        self.assertEqual(shape.points[0], QPointF(30, 10))
        canvas.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_reuses_raster_until_source_or_view_changes_and_bounds_memory(self):
        from labelimg.canvas.image_layer import ImageLayerCache
        cache = ImageLayerCache()
        source = QPixmap(1000, 700)
        source.fill(Qt.white)
        target = QImage(300, 200, QImage.Format_RGB32)
        painter = QPainter(target)
        painter.scale(.25, .25)
        with patch.object(cache, '_rasterize', wraps=cache._rasterize) as rasterize:
            for _ in range(10):
                cache.paint(painter, source, source.size(), QRect(0, 0, 300, 200))
            self.assertEqual(rasterize.call_count, 1)
            painter.translate(10, 0)
            cache.paint(painter, source, source.size(), QRect(0, 0, 300, 200))
            source.fill(Qt.red)
            cache.paint(painter, source, source.size(), QRect(0, 0, 300, 200))
            self.assertEqual(rasterize.call_count, 3)
        self.assertLessEqual(cache._layer.width() * cache._layer.height(), cache.MAX_PIXELS)
        painter.end()
