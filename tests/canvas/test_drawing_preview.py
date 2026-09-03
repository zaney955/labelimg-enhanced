"""Pixel-level contracts for the uncommitted box and its alignment guides."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap, qRgb
from PyQt5.QtWidgets import QApplication

from labelimg.canvas.drawing_preview import paint_pending_box
from labelimg.canvas.widget import Canvas


class DrawingPreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def source(self, color=Qt.white):
        image = QImage(200, 160, QImage.Format_RGB32)
        image.fill(color)
        return image

    def render_preview(self, source, *, start=(20, 30), end=(180, 130),
                       scale=1.0, density=1.0, logical_size=None, clip=None,
                       drawing=True):
        size = logical_size or source.size()
        output = QImage(round(size.width() * scale * density),
                        round(size.height() * scale * density), QImage.Format_RGB32)
        output.setDevicePixelRatio(density)
        output.fill(Qt.white)
        painter = QPainter(output)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(scale, scale)
        bounds = QRectF(0, 0, size.width(), size.height())
        painter.drawImage(bounds, source)
        if clip is not None:
            painter.setClipRect(clip)
        paint_pending_box(
            painter, size, QPointF(*start), QPointF(*end), drawing=drawing,
        )
        painter.end()
        return output

    def test_outline_adapts_locally_across_one_light_and_dark_edge(self):
        source = self.source()
        painter = QPainter(source)
        painter.fillRect(100, 0, 100, 160, Qt.black)
        painter.end()
        output = self.render_preview(source)
        self.assertLess(output.pixelColor(60, 30).red(), 90)
        self.assertGreater(output.pixelColor(140, 30).red(), 165)
        for x in (60, 140):
            color = output.pixelColor(x, 30)
            self.assertEqual(color.red(), color.green())
            self.assertEqual(color.green(), color.blue())

    def test_interior_has_no_fill_or_diagonal(self):
        source = self.source(QColor(70, 110, 150))
        output = self.render_preview(source)
        for y in range(35, 125):
            for x in range(25, 175):
                self.assertEqual(output.pixel(x, y), source.pixel(x, y))

    def test_preview_inverts_gray_pixels_like_a_reverse_screen_cursor(self):
        for value in (0, 30, 90, 127, 128, 160, 220, 255):
            output = self.render_preview(self.source(QColor(value, value, value)))
            color = output.pixelColor(20, 30)
            self.assertEqual(color, QColor(255 - value, 255 - value, 255 - value))

    def test_color_pixels_are_inverted_in_each_rgb_channel(self):
        output = self.render_preview(
            self.source(QColor(24, 100, 170)), start=(20.5, 30.5), end=(180.5, 130.5),
        )
        expected = QColor(231, 155, 85)
        # Marker, outline, guide and their shared corner all invert exactly once.
        for point in ((20, 30), (60, 30), (190, 130), (180, 130)):
            self.assertEqual(output.pixelColor(*point), expected)

    def test_outline_inverts_individual_pixels_without_averaging_texture(self):
        source = self.source()
        for x in range(30, 100):
            source.setPixelColor(x, 30, QColor(40 if x % 2 else 180, 90, 130))
        output = self.render_preview(source, start=(20.5, 30.5), end=(180.5, 130.5))
        for x in range(30, 100):
            color = source.pixelColor(x, 30)
            self.assertEqual(output.pixelColor(x, 30), QColor(
                255 - color.red(), 255 - color.green(), 255 - color.blue(),
            ))

    def test_waiting_for_label_keeps_only_the_inverted_outline(self):
        output = self.render_preview(self.source(), drawing=False)
        self.assertLess(output.pixelColor(60, 30).red(), 90)
        self.assertEqual(output.pixelColor(180, 10), QColor(Qt.white))
        self.assertEqual(output.pixelColor(190, 130), QColor(Qt.white))
        self.assertEqual(output.pixelColor(18, 30), QColor(Qt.white))

    def test_fixed_edge_does_not_flicker_when_endpoint_nears_image_boundary(self):
        source = QImage(203, 80, QImage.Format_RGB32)
        for y in range(80):
            for x in range(203):
                value = 80 if x % 2 else 176
                source.setPixel(x, y, qRgb(value, value, value))
        before = self.render_preview(source, start=(20, 20), end=(200, 60))
        after = self.render_preview(source, start=(20, 20), end=(201, 60))
        self.assertEqual(
            [before.pixel(x, 20) for x in range(30, 170)],
            [after.pixel(x, 20) for x in range(30, 170)],
            "Moving the endpoint must not change the stationary top edge",
        )

    def test_start_is_solid_and_guides_continue_beyond_moving_corner(self):
        output = self.render_preview(self.source())
        self.assertEqual(output.pixelColor(20, 30), QColor(Qt.black))
        self.assertLess(output.pixelColor(180, 10).red(), 200)
        self.assertLess(output.pixelColor(190, 130).red(), 200)
        # Other corners do not gain the start marker's four-pixel footprint.
        self.assertEqual(output.pixelColor(181, 31), QColor(Qt.white))

    def test_middle_gray_retains_native_inversion_instead_of_contrast_boost(self):
        source = self.source(QColor(128, 128, 128))
        output = self.render_preview(source)
        self.assertEqual(output.pixelColor(20, 30), QColor(127, 127, 127))

    def test_stroke_and_marker_keep_screen_size_across_zoom_and_density(self):
        for scale in (0.5, 1.0, 3.0, 6.0):
            for density in (1.0, 2.0):
                with self.subTest(scale=scale, density=density):
                    output = self.render_preview(self.source(), scale=scale, density=density)
                    factor = scale * density
                    x, y = round(60 * factor), round(30 * factor)
                    coverage = sum(
                        (255 - output.pixelColor(x, row).red()) / 255
                        for row in range(y - 5, y + 6)
                    ) / density
                    self.assertAlmostEqual(coverage, 1.5, delta=0.08)
                    marker_x = round(20 * factor)
                    marker_coverage = sum(
                        (255 - output.pixelColor(col, y).red()) / 255
                        for col in range(marker_x - round(4 * density), marker_x)
                    ) / density
                    self.assertGreater(marker_coverage, 1.5)
                    self.assertLess(marker_coverage, 2.1)

    def test_reduced_display_image_uses_annotation_coordinate_space(self):
        source = self.source()
        painter = QPainter(source)
        painter.fillRect(100, 0, 100, 160, Qt.black)
        painter.end()
        output = self.render_preview(
            source, logical_size=QSize(400, 320), start=(40, 60), end=(360, 260),
        )
        self.assertLess(output.pixelColor(120, 60).red(), 90)
        self.assertGreater(output.pixelColor(280, 60).red(), 165)

    def test_reverse_drawing_preserves_all_edges(self):
        output = self.render_preview(self.source(), start=(180, 130), end=(20, 30))
        for point in ((60, 30), (60, 130), (20, 80), (180, 80)):
            self.assertLess(output.pixelColor(*point).red(), 90)
        self.assertEqual(output.pixelColor(180, 130), QColor(Qt.black))

    def test_stationary_edge_keeps_contrast_when_repaint_or_endpoint_changes(self):
        source = self.source()
        painter = QPainter(source)
        for x, value in ((55, 30), (77, 230), (113, 50), (139, 220)):
            painter.fillRect(x, 0, 200 - x, 160, QColor(value, value, value))
        painter.end()
        complete = self.render_preview(source)
        clipped = self.render_preview(source, clip=QRectF(51, 20, 106, 30))
        moved = self.render_preview(source, end=(177, 130))
        for x in range(56, 152):
            self.assertEqual(complete.pixel(x, 30), clipped.pixel(x, 30))
            self.assertEqual(complete.pixel(x, 30), moved.pixel(x, 30))

    def test_edge_touching_image_bounds_remains_visible(self):
        output = self.render_preview(self.source(Qt.black), start=(0, 0), end=(200, 160))
        for point in ((0, 80), (199, 80), (100, 0), (100, 159)):
            self.assertGreater(output.pixelColor(*point).red(), 100)

    def test_canvas_guides_follow_constrained_corner_and_cancel_clears_preview(self):
        canvas = Canvas()
        canvas.load_pixmap(QPixmap.fromImage(self.source()))
        canvas.resize(200, 160)
        canvas.set_editing(False)
        canvas.set_drawing_shape_to_square(True)
        try:
            for kind, point, button in (
                (QEvent.MouseButtonPress, (20, 30), Qt.LeftButton),
                (QEvent.MouseMove, (250, 90), Qt.NoButton),
            ):
                QApplication.sendEvent(canvas, QMouseEvent(
                    kind, canvas.image_to_widget(QPointF(*point)),
                    button, Qt.LeftButton, Qt.NoModifier,
                ))
            self.assertEqual(canvas.line[1], QPointF(80, 90))
            output = canvas.grab().toImage()
            self.assertLess(output.pixelColor(80, 10).red(), 200)
            self.assertLess(output.pixelColor(190, 90).red(), 200)
            self.assertEqual(output.pixelColor(100, 60), QColor(Qt.white))

            # Display adjustment/replacement must immediately change contrast.
            canvas.replace_pixmap(QPixmap.fromImage(self.source(Qt.black)))
            output = canvas.grab().toImage()
            self.assertGreater(output.pixelColor(80, 10).red(), 80)
            canvas.cancel_current_drawing()
            output = canvas.grab().toImage()
            self.assertEqual(output.pixelColor(80, 10), QColor(Qt.black))
        finally:
            canvas.restore_cursor()
            canvas.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
