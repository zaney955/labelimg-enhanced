import unittest
from unittest.mock import Mock

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt5.QtWidgets import QApplication

from labelimg.shape import Shape


class ShapeRenderingStyleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        Shape.scale = 1.0
        Shape.label_font_size = 8

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
        self.assertEqual(fill_color.alpha(), 30)
        for actual, expected in zip(
            fill_color.getRgb()[:3],
            (12, 34, 56),
        ):
            self.assertLessEqual(abs(actual - expected), 1)

    def test_hover_outline_is_same_width_dashed_color_without_underlay(self):
        image = QImage(80, 80, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        shape = self.make_rectangle()
        shape.line_color = QColor(12, 34, 56, 80)

        painter = QPainter(image)
        shape.paint(
            painter,
            outline_style=Qt.CustomDashLine,
            outline_dash_pattern=(4.0, 4.0),
        )
        painter.end()

        border_pixels = [
            image.pixelColor(x, 20)
            for x in range(25, 56)
        ]
        self.assertTrue(any(color.alpha() == 0 for color in border_pixels))
        self.assertTrue(any(color.alpha() > 0 for color in border_pixels))
        self.assertTrue(all(
            color.alpha() == 0
            or color.getRgb()[:3] == (12, 34, 56)
            for color in border_pixels
        ))
        self.assertTrue(all(
            image.pixelColor(x, 18).alpha() == 0
            for x in range(25, 56)
        ))
        self.assertEqual(
            image.pixelColor(40, 40),
            QColor(Qt.transparent),
        )

        recording_painter = Mock()
        shape.paint(
            recording_painter,
            outline_style=Qt.CustomDashLine,
            outline_dash_pattern=(4.0, 4.0),
        )
        outline_pen = recording_painter.setPen.call_args_list[0].args[0]
        self.assertEqual(outline_pen.style(), Qt.CustomDashLine)
        self.assertEqual(outline_pen.dashPattern(), [4.0, 4.0])
        self.assertEqual(outline_pen.widthF(), 1.5)
        self.assertEqual(outline_pen.color(), QColor(12, 34, 56, 255))

    def test_selected_label_uses_translucent_black_background_and_white_text(self):
        shape = self.make_rectangle()
        shape.paint_label = True
        shape.selected = True
        shape.fill = True
        painter = Mock()

        shape.paint(painter)

        painter.drawRoundedRect.assert_called_once()
        painter.setBrush.assert_called_once_with(
            Shape.selected_label_background_color
        )
        self.assertEqual(
            Shape.selected_label_background_color,
            QColor(0, 0, 0, 153),
        )
        self.assertIn(
            Shape.selected_label_text_color,
            [call.args[0] for call in painter.setPen.call_args_list],
        )
        painter.drawText.assert_called_once()
        text_x, text_y, label = painter.drawText.call_args.args
        self.assertEqual(text_x, 20)
        self.assertEqual(label, "car")

        font = QFont()
        font.setPointSize(Shape.label_font_size)
        font.setBold(True)
        expected_rect = QRectF(QFontMetrics(font).tightBoundingRect("car"))
        expected_rect.translate(text_x, text_y)
        self.assertLessEqual(
            expected_rect.bottom(),
            20 - Shape.label_outline_gap / Shape.scale,
        )
        expected_rect.adjust(
            -Shape.selected_label_padding,
            -Shape.selected_label_padding,
            Shape.selected_label_padding,
            Shape.selected_label_padding,
        )
        actual_rect, horizontal_radius, vertical_radius = (
            painter.drawRoundedRect.call_args.args
        )
        self.assertEqual(actual_rect, expected_rect)
        self.assertEqual(horizontal_radius, Shape.selected_label_radius)
        self.assertEqual(vertical_radius, Shape.selected_label_radius)

        method_names = [
            call[0] for call in painter.method_calls
        ]
        self.assertLess(
            max(
                index
                for index, name in enumerate(method_names)
                if name == "fillPath"
            ),
            method_names.index("drawRoundedRect"),
        )
        self.assertLess(
            method_names.index("drawRoundedRect"),
            method_names.index("drawText"),
        )

    def test_unselected_label_keeps_original_text_without_highlight(self):
        shape = self.make_rectangle()
        shape.paint_label = True
        painter = Mock()

        shape.paint(painter)

        painter.drawRoundedRect.assert_not_called()
        painter.setBrush.assert_not_called()
        painter.drawText.assert_called_once()
        self.assertEqual(
            painter.drawText.call_args.args[2],
            "car",
        )
        self.assertNotIn(
            Shape.selected_label_text_color,
            [call.args[0] for call in painter.setPen.call_args_list],
        )

    def test_label_descenders_are_separated_from_top_outline(self):
        shape = self.make_rectangle()
        shape.label = "C_PWBDZ"
        shape.paint_label = True
        painter = Mock()

        shape.paint(painter)

        text_x, text_y, label = painter.drawText.call_args.args
        font = QFont()
        font.setPointSize(Shape.label_font_size)
        font.setBold(True)
        glyph_rect = QRectF(QFontMetrics(font).tightBoundingRect(label))
        glyph_rect.translate(text_x, text_y)
        self.assertLessEqual(
            glyph_rect.bottom(),
            20 - Shape.label_outline_gap / Shape.scale,
        )

    def test_label_moves_inside_when_there_is_no_space_above(self):
        shape = Shape(label="C_PWBDZ", paint_label=True)
        for point in (
            QPointF(20, 2),
            QPointF(60, 2),
            QPointF(60, 42),
            QPointF(20, 42),
        ):
            shape.add_point(point)
        shape.close()
        painter = Mock()

        shape.paint(painter)

        text_x, text_y, label = painter.drawText.call_args.args
        font = QFont()
        font.setPointSize(Shape.label_font_size)
        font.setBold(True)
        glyph_rect = QRectF(QFontMetrics(font).tightBoundingRect(label))
        glyph_rect.translate(text_x, text_y)
        self.assertGreaterEqual(
            glyph_rect.top(),
            2 + Shape.label_outline_gap / Shape.scale,
        )

    def test_hidden_label_does_not_paint_highlight_when_selected(self):
        shape = self.make_rectangle()
        shape.selected = True
        painter = Mock()

        shape.paint(painter)

        painter.drawRoundedRect.assert_not_called()
        painter.drawText.assert_not_called()

    def test_selected_label_background_is_visible_in_rendered_pixels(self):
        image = QImage(100, 80, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        shape = self.make_rectangle()
        shape.paint_label = True
        shape.selected = True
        shape.fill = True

        painter = QPainter(image)
        shape.paint(painter)
        painter.end()

        label_pixels = [
            image.pixelColor(x, y)
            for y in range(5, 28)
            for x in range(15, 50)
        ]
        self.assertTrue(any(
            color.red() <= 5
            and color.green() <= 5
            and color.blue() <= 5
            and 140 <= color.alpha() <= 170
            for color in label_pixels
        ))


if __name__ == "__main__":
    unittest.main()
