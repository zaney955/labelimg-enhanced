import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication

from labelimg.canvas.widget import Canvas
from labelimg.canvas.shape import Shape


class CanvasReadoutsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = Canvas()
        self.canvas.load_pixmap(QPixmap(100, 100))
        self.canvas.resize(260, 260)
        self.coordinates = []
        self.canvas.coordinatesChanged.connect(self.coordinates.append)

    def tearDown(self):
        self.canvas.restore_cursor()
        self.canvas.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def move(self, point, buttons=Qt.NoButton):
        self.send(QEvent.MouseMove, point, buttons=buttons)

    def send(self, kind, point, button=Qt.NoButton, buttons=Qt.NoButton):
        position = self.canvas.image_to_widget(QPointF(*point))
        QApplication.sendEvent(self.canvas, QMouseEvent(
            kind, position, button, buttons, Qt.NoModifier,
        ))

    def begin_box(self):
        self.canvas.set_editing(False)
        self.send(QEvent.MouseButtonPress, (10, 10),
                  Qt.LeftButton, Qt.LeftButton)

    def test_no_annotation_has_no_size_text(self):
        sizes = []
        self.canvas.annotationSizeChanged.connect(sizes.append)
        self.move((20, 30))
        self.assertEqual(sizes[-1], "")
        self.canvas.set_editing(False)
        self.move((20, 30))
        self.assertEqual(sizes[-1], "")

    def test_outside_image_never_publishes_pixel_indices(self):
        for point in ((-1, 20), (20, -1), (100, 20), (20, 100), (150, 150)):
            with self.subTest(point=point):
                self.move(point)
                self.assertEqual(self.coordinates[-1], "X: —  Y: —")
        self.move((99, 99))
        self.assertEqual(self.coordinates[-1], "X: 99  Y: 99")
        self.move((0, 0))
        self.assertEqual(self.coordinates[-1], "X: 0  Y: 0")

    def test_leave_and_image_reset_clear_stale_coordinates(self):
        self.move((20, 30))
        QApplication.sendEvent(self.canvas, QEvent(QEvent.Leave))
        self.assertEqual(self.coordinates[-1], "X: —  Y: —")
        self.move((20, 30))
        self.canvas.reset_state()
        self.assertEqual(self.coordinates[-1], "X: —  Y: —")

    def test_view_refresh_uses_original_pixels_and_checks_fractional_bounds(self):
        self.canvas.scale = 2.0
        for point, expected in (
            ((12.75, 23.9), "X: 12  Y: 23"),
            ((-0.01, 20), "X: —  Y: —"),
            ((99.99, 99.99), "X: 99  Y: 99"),
            ((100, 50), "X: —  Y: —"),
        ):
            self.canvas.refresh_pointer_coordinates(
                self.canvas.image_to_widget(QPointF(*point)),
            )
            self.assertEqual(self.coordinates[-1], expected)

    def test_drawing_size_comes_from_the_bounded_preview(self):
        sizes = []
        self.canvas.annotationSizeChanged.connect(sizes.append)
        self.begin_box()
        for point in ((110, 110), (150, 150)):
            self.move(point, Qt.LeftButton)
            self.assertEqual(self.canvas.line[1], QPointF(100, 100))
            self.assertEqual(sizes[-1], "W: 90  H: 90")
            self.assertEqual(self.coordinates[-1], "X: —  Y: —")
        # Moving along the outside can still change the constrained rectangle.
        self.move((150, 60), Qt.LeftButton)
        self.assertEqual(sizes[-1], "W: 90  H: 50")
        self.move((50, 40), Qt.LeftButton)
        self.assertEqual(sizes[-1], "W: 40  H: 30")
        self.assertEqual(self.coordinates[-1], "X: 50  Y: 40")

    def test_square_preview_and_leave_keep_actual_size(self):
        sizes = []
        self.canvas.annotationSizeChanged.connect(sizes.append)
        self.canvas.set_drawing_shape_to_square(True)
        self.begin_box()
        self.move((150, 60), Qt.LeftButton)
        self.assertEqual(sizes[-1], "W: 50  H: 50")
        QApplication.sendEvent(self.canvas, QEvent(QEvent.Leave))
        self.assertEqual(sizes[-1], "W: 50  H: 50")
        self.assertEqual(self.coordinates[-1], "X: —  Y: —")
        self.canvas.cancel_current_drawing()
        self.assertEqual(sizes[-1], "")

    def test_vertex_drag_size_matches_actual_geometry_outside_image(self):
        sizes = []
        self.canvas.annotationSizeChanged.connect(sizes.append)
        shape = Shape(label="box")
        for point in ((10, 10), (70, 10), (70, 70), (10, 70)):
            shape.add_point(QPointF(*point))
        shape.close()
        self.canvas.load_shapes([shape])
        self.move((70, 70))
        self.send(QEvent.MouseButtonPress, (70, 70), Qt.LeftButton, Qt.LeftButton)
        for point in ((110, 110), (150, 150)):
            self.move(point, Qt.LeftButton)
            self.assertEqual(self.coordinates[-1], "X: —  Y: —")
            bounds = shape.bounding_rect()
            self.assertEqual(sizes[-1], "W: %d  H: %d" % (
                bounds.width(), bounds.height(),
            ))

    def test_edge_drag_and_whole_box_move_report_geometry_not_pointer(self):
        sizes = []
        self.canvas.annotationSizeChanged.connect(sizes.append)
        for start, target in (((40, 10), (40, -50)), ((40, 40), (150, 150))):
            with self.subTest(start=start):
                shape = Shape(label="box")
                for point in ((10, 10), (70, 10), (70, 70), (10, 70)):
                    shape.add_point(QPointF(*point))
                shape.close()
                self.canvas.load_shapes([shape])
                self.move(start)
                self.send(QEvent.MouseButtonPress, start,
                          Qt.LeftButton, Qt.LeftButton)
                self.move(target, Qt.LeftButton)
                bounds = shape.bounding_rect()
                self.assertEqual(sizes[-1], "W: %d  H: %d" % (
                    bounds.width(), bounds.height(),
                ))
                self.assertEqual(self.coordinates[-1], "X: —  Y: —")
                self.send(QEvent.MouseButtonRelease, target, Qt.LeftButton)

    def test_image_replacement_clears_both_readouts(self):
        sizes = []
        self.canvas.annotationSizeChanged.connect(sizes.append)
        self.begin_box()
        self.move((50, 50), Qt.LeftButton)
        self.canvas.load_pixmap(QPixmap(30, 30))
        self.assertEqual(self.coordinates[-1], "X: —  Y: —")
        self.assertEqual(sizes[-1], "")


if __name__ == "__main__":
    unittest.main()
