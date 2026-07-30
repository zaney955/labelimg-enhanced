import unittest

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from labelimg.shape import Shape


class ShapeRenderingStyleTest(unittest.TestCase):
    def make_rectangle(self):
        shape = Shape(label="car")
        for point in (
            QPointF(20, 20),
            QPointF(60, 20),
            QPointF(60, 60),
            QPointF(20, 60),
        ):
            shape.add_point(point)
        shape.close()
        return shape

    def test_corner_points_have_four_pixel_diameter(self):
        shape = self.make_rectangle()
        vertex_path = QPainterPath()

        shape.draw_vertex(vertex_path, 0)

        bounds = vertex_path.boundingRect()
        self.assertEqual(bounds.width(), 4)
        self.assertEqual(bounds.height(), 4)

    def test_outline_is_one_and_half_pixels_wide(self):
        class RecordingPainter:
            def setPen(self, pen):
                self.pen = QPen(pen)

            def drawPath(self, _path):
                pass

            def fillPath(self, _path, _color):
                pass

        shape = self.make_rectangle()
        painter = RecordingPainter()

        shape.paint(painter)

        self.assertEqual(painter.pen.widthF(), 1.5)

    def test_outline_and_corner_points_use_same_opaque_color(self):
        image = QImage(80, 80, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        shape = self.make_rectangle()
        expected_color = QColor(12, 34, 56, 255)
        shape.line_color = QColor(12, 34, 56, 80)

        painter = QPainter(image)
        shape.paint(painter)
        painter.end()

        self.assertEqual(image.pixelColor(40, 20), expected_color)
        self.assertEqual(image.pixelColor(20, 20), expected_color)
        self.assertEqual(image.pixelColor(40, 40), QColor(Qt.transparent))

    def test_selected_shape_uses_its_own_color_for_outline_and_fill(self):
        image = QImage(80, 80, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        shape = self.make_rectangle()
        shape.line_color = QColor(12, 34, 56, 80)
        shape.selected = True
        shape.fill = True

        painter = QPainter(image)
        shape.paint(painter)
        painter.end()

        self.assertEqual(
            image.pixelColor(40, 20),
            QColor(12, 34, 56, 255),
        )
        fill_color = image.pixelColor(40, 40)
        self.assertEqual(fill_color.alpha(), 100)
        for actual, expected in zip(
            fill_color.getRgb()[:3],
            (12, 34, 56),
        ):
            self.assertLessEqual(abs(actual - expected), 1)


if __name__ == "__main__":
    unittest.main()
