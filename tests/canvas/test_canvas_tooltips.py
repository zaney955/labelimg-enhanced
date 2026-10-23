"""Canvas hover guidance belongs in the status bar, without floating popups."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QHelpEvent, QMouseEvent, QPixmap
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QToolTip, QWidget

from labelimg.canvas.shape import Shape
from labelimg.canvas.widget import Canvas


class CanvasTooltipsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = Canvas()
        self.canvas.resize(260, 260)
        pixmap = QPixmap(200, 200)
        pixmap.fill(Qt.white)
        self.canvas.load_pixmap(pixmap)
        shape = Shape(label="box")
        for point in ((40, 40), (160, 40), (160, 160), (40, 160)):
            shape.add_point(QPointF(*point))
        shape.close()
        self.canvas.load_shapes([shape])
        self.canvas.show()
        self.app.processEvents()

    def tearDown(self):
        QToolTip.hideText()
        QTest.qWait(350)
        self.canvas.restore_cursor()
        self.canvas.close()
        self.canvas.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def request_tooltip(self, widget, position):
        self.app.processEvents()
        event = QHelpEvent(QEvent.ToolTip, position, widget.mapToGlobal(position))
        QApplication.sendEvent(widget, event)
        self.app.processEvents()

    def test_stationary_pointer_does_not_show_popup_in_any_canvas_mode(self):
        hints = []
        self.canvas.interactionHintChanged.connect(lambda text, _: hints.append(text))
        for mode in (Canvas.EDIT, Canvas.CREATE, Canvas.PAN):
            self.canvas.set_mode(mode)
            for point in ((20, 20), (40, 40), (100, 40), (100, 100)):
                with self.subTest(mode=mode, point=point):
                    position = self.canvas.image_to_widget(QPointF(*point))
                    QApplication.sendEvent(self.canvas, QMouseEvent(
                        QEvent.MouseMove, position, Qt.NoButton,
                        Qt.NoButton, Qt.NoModifier,
                    ))
                    self.assertTrue(hints[-1], "Status-bar guidance must remain available")
                    # Send Qt's delayed hover event at the same pointer position.
                    self.request_tooltip(self.canvas, position.toPoint())
                    self.assertFalse(QToolTip.isVisible())

    def test_other_controls_keep_native_tooltips(self):
        control = QWidget()
        try:
            control.setToolTip("Control help")
            control.show()
            self.request_tooltip(control, QPoint(10, 10))
            self.assertTrue(QToolTip.isVisible())
            self.assertEqual(QToolTip.text(), "Control help")
        finally:
            control.close()
            control.deleteLater()


if __name__ == "__main__":
    unittest.main()
