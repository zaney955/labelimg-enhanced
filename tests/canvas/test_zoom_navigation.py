import math
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PyQt5.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QStyle, QStyleOptionSlider

from labelimg.canvas.widget import Canvas
from labelimg.workbench.bootstrap import (
    WorkbenchLaunchOptions,
    create_workbench,
)
from labelimg.workbench.commands import ZoomControl
from labelimg.localization.runtime import current_language, set_language


def wheel_event(
    *,
    pixel=0,
    angle=120,
    modifiers=Qt.NoModifier,
    buttons=Qt.NoButton,
    position=QPointF(20, 30),
):
    return QWheelEvent(
        QPointF(position),
        QPointF(position),
        QPoint(0, pixel),
        QPoint(0, angle),
        buttons,
        modifiers,
        Qt.NoScrollPhase,
        False,
    )


class CanvasWheelRoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = Canvas()
        self.scrolls = []
        self.zooms = []
        self.canvas.scrollRequest.connect(
            lambda delta, orientation, pixels: self.scrolls.append(
                (delta, orientation, pixels)
            )
        )
        self.canvas.zoomRequest.connect(
            lambda units, position: self.zooms.append((units, position))
        )

    def test_plain_shift_and_control_wheels_have_distinct_routes(self):
        self.canvas.wheelEvent(wheel_event())
        self.canvas.wheelEvent(wheel_event(modifiers=Qt.ShiftModifier))
        self.canvas.wheelEvent(wheel_event(
            modifiers=Qt.ControlModifier | Qt.ShiftModifier,
        ))

        self.assertEqual(self.scrolls[0], (120.0, Qt.Vertical, False))
        self.assertEqual(self.scrolls[1], (120.0, Qt.Horizontal, False))
        self.assertEqual(len(self.zooms), 1)
        self.assertAlmostEqual(self.zooms[0][0], 1.0)
        self.assertEqual(self.zooms[0][1], QPointF(20, 30))

    def test_pixel_delta_is_continuous_and_dragging_blocks_zoom(self):
        self.canvas.wheelEvent(wheel_event(pixel=24, angle=0))
        self.canvas.wheelEvent(wheel_event(
            pixel=24,
            angle=0,
            modifiers=Qt.ControlModifier,
        ))
        self.canvas.wheelEvent(wheel_event(
            modifiers=Qt.ControlModifier,
            buttons=Qt.LeftButton,
        ))

        self.assertEqual(self.scrolls, [(24.0, Qt.Vertical, True)])
        self.assertEqual(len(self.zooms), 1)
        self.assertAlmostEqual(self.zooms[0][0], 0.2)


class ZoomControlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_logarithmic_value_and_adaptive_percentage_copy(self):
        control = ZoomControl()

        self.assertTrue(control.setValue(1.05))
        self.assertEqual(control.value_button.text(), "1.05%")
        self.assertTrue(control.setValue(0.5))
        self.assertEqual(control.value(), 1.0)
        control.setMinimumValue(0.5)
        self.assertTrue(control.setValue(0.5))
        self.assertEqual(control.value_button.text(), "0.5%")
        self.assertTrue(control.setValue(700))
        self.assertEqual(control.value(), 600.0)
        self.assertEqual(control.value_button.text(), "600%")
        control.setMaximumValue(2400)
        self.assertTrue(control.setValue(2400))
        self.assertEqual(control.maximumValue(), 2400.0)
        self.assertEqual(control.value_button.text(), "2400%")

    def test_slider_keyboard_step_uses_the_shared_increment_factor(self):
        control = ZoomControl()
        control.setValue(100)

        control.slider.setValue(
            control.slider.value() + control.slider.singleStep()
        )

        self.assertAlmostEqual(control.value(), 110.0, delta=0.1)

    def test_wheel_over_child_uses_shared_zoom_step_signal(self):
        control = ZoomControl()
        steps = []
        control.zoomStepRequested.connect(steps.append)

        event = wheel_event(pixel=30, angle=0)
        QApplication.sendEvent(control.slider, event)

        self.assertEqual(steps, [0.25])
        self.assertTrue(event.isAccepted())


class WorkbenchZoomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.previous_language = current_language()
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {"LABELIMG_CONFIG_DIR": self.temporary.name},
        )
        self.environment.start()
        classes_path = os.path.join(self.temporary.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=classes_path,
            save_dir="",
        ))
        self.window.resize(1180, 760)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()
        set_language(self.previous_language)

    def load_image(self, width, height, name="zoom.png"):
        path = os.path.join(self.temporary.name, name)
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(path))
        self.assertTrue(self.window.load_file(path))
        self.app.processEvents()
        return path

    def test_zoom_control_stays_visible_and_compacts_in_a_narrow_window(self):
        self.window.resize(1600, 760)
        self.app.processEvents()
        self.assertTrue(self.window.zoom_widget.isVisible())
        self.assertTrue(self.window.zoom_widget.slider.isVisible())
        self.assertFalse(self.window.zoom_widget.isEnabled())
        self.assertEqual(self.window.zoom_widget.slider.width(), 112)

        self.window.resize(self.window.minimumWidth(), 760)
        self.app.processEvents()

        self.assertTrue(self.window.zoom_widget.isVisible())
        self.assertTrue(self.window.zoom_widget.slider.isVisible())
        self.assertIn(self.window.zoom_widget.slider.width(), (64, 80))

    def test_canvas_status_is_local_and_reflows_when_sidebar_expands(self):
        self.window.resize(1800, 760)
        self.app.processEvents()
        strip = self.window.canvas_status
        self.assertFalse(strip.stacked)
        self.assertEqual(strip.width(), self.window.scroll_area.width())
        self.assertEqual(strip.mapToGlobal(QPoint()).x(),
                         self.window.scroll_area.mapToGlobal(QPoint()).x())
        self.assertNotIn(self.window.zoom_widget,
                         self.window.statusBar().findChildren(ZoomControl))
        self.assertGreaterEqual(strip.mapToGlobal(QPoint()).y(),
                                self.window.scroll_area.mapToGlobal(QPoint(
                                    0, self.window.scroll_area.height(),
                                )).y())

        window_width = self.window.width()
        self.window.resizeDocks([self.window.file_dock], [1200], Qt.Horizontal)
        for _ in range(3):
            self.app.processEvents()
        self.assertEqual(self.window.width(), window_width)
        self.assertTrue(strip.stacked)
        self.assertTrue(strip.rect().contains(
            self.window.zoom_widget.geometry()))
        for label in (strip.coordinates, strip.dimensions):
            self.assertGreaterEqual(label.width(), label.sizeHint().width())

    def test_readout_digits_and_placeholders_do_not_move_slider(self):
        self.assertEqual(self.window.label_dimensions.text(), "")
        self.load_image(10000, 10)
        slider = self.window.zoom_widget.slider
        origin = slider.mapToGlobal(QPoint())
        for coordinates, dimensions in (
            ("X: —  Y: —", ""),
            ("X: 0  Y: 0", "W: 1  H: 1"),
            ("X: 9999  Y: 9", "W: 10000  H: 10"),
            ("X: —  Y: —", ""),
        ):
            self.window.canvas.coordinatesChanged.emit(coordinates)
            self.window.canvas.annotationSizeChanged.emit(dimensions)
            self.app.processEvents()
            self.assertEqual(slider.mapToGlobal(QPoint()), origin)
            for label in (self.window.label_coordinates, self.window.label_dimensions):
                self.assertGreaterEqual(label.width(),
                                        label.fontMetrics().horizontalAdvance(label.text()))

    def test_scroll_and_pan_refresh_stationary_pointer(self):
        self.load_image(1200, 900)
        self.window.set_zoom(100)
        self.app.processEvents()
        viewport_point = QPoint(150, 100)
        local = self.window.canvas.mapFrom(self.window.scroll_area.viewport(),
                                          viewport_point)
        QApplication.sendEvent(self.window.canvas, QMouseEvent(
            QEvent.MouseMove, QPointF(local), Qt.NoButton, Qt.NoButton,
            Qt.NoModifier,
        ))
        before = self.window.label_coordinates.text()
        self.window.scroll_bars[Qt.Horizontal].setValue(100)
        self.app.processEvents()
        point = self.image_point_at_viewport(viewport_point)
        self.assertEqual(self.window.label_coordinates.text(),
                         "X: %d  Y: %d" % (math.floor(point.x()), math.floor(point.y())))
        self.assertNotEqual(before, self.window.label_coordinates.text())

        self.load_image(30, 30)
        local = self.window.canvas.image_to_widget(QPointF(15, 15))
        QApplication.sendEvent(self.window.canvas, QMouseEvent(
            QEvent.MouseMove, local, Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        ))
        self.window.pan_request(500, 500)
        self.app.processEvents()
        self.assertEqual(self.window.label_coordinates.text(), "X: —  Y: —")

    def test_pending_fit_reflow_is_canceled_when_window_is_destroyed(self):
        path = self.load_image(30, 30)
        doomed = create_workbench(WorkbenchLaunchOptions(
            class_file=os.path.join(self.temporary.name, "classes.txt"),
            save_dir="",
        ))
        doomed.load_file(path)
        self.app.processEvents()
        self.assertFalse(doomed._ignore_zoom_viewport_resize)
        errors = []
        with patch("sys.excepthook", side_effect=lambda *args: errors.append(args)):
            doomed.canvas_viewport_resize_event(QResizeEvent(
                self.window.scroll_area.viewport().size(), QSize(400, 400),
            ))
            doomed.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
        self.assertEqual(errors, [])

    def test_zoom_shortcuts_use_equal_minus_and_actual_size(self):
        self.load_image(100, 100)
        self.window.set_zoom(100)

        self.assertEqual(
            [shortcut.toString()
             for shortcut in self.window.actions.zoomIn.shortcuts()],
            ["Ctrl+="],
        )
        self.assertEqual(
            self.window.actions.zoomInAlias.key().toString(),
            "Ctrl++",
        )
        self.assertEqual(
            [shortcut.toString()
             for shortcut in self.window.actions.zoomOut.shortcuts()],
            ["Ctrl+-"],
        )
        self.assertEqual(
            [shortcut.toString()
             for shortcut in self.window.actions.zoomOrg.shortcuts()],
            ["Ctrl+1"],
        )

        self.window.actions.zoomIn.trigger()
        self.assertAlmostEqual(self.window.zoom_widget.value(), 110.0)
        self.window.actions.zoomOut.trigger()
        self.assertAlmostEqual(self.window.zoom_widget.value(), 100.0)
        self.window.actions.zoomInAlias.activated.emit()
        self.assertAlmostEqual(self.window.zoom_widget.value(), 110.0)
        self.window.actions.zoomOrg.trigger()
        self.assertAlmostEqual(self.window.zoom_widget.value(), 100.0)

        QTest.keyClick(self.window, Qt.Key_Equal, Qt.ControlModifier)
        self.assertAlmostEqual(self.window.zoom_widget.value(), 110.0)
        QTest.keyClick(self.window, Qt.Key_Minus, Qt.ControlModifier)
        self.assertAlmostEqual(self.window.zoom_widget.value(), 100.0)
        QTest.keyClick(self.window, Qt.Key_Plus, Qt.ControlModifier)
        self.assertAlmostEqual(self.window.zoom_widget.value(), 110.0)
        QTest.keyClick(self.window, Qt.Key_1, Qt.ControlModifier)
        self.assertAlmostEqual(self.window.zoom_widget.value(), 100.0)

    def test_canvas_and_control_wheels_share_ten_percent_curve(self):
        self.load_image(100, 100)
        self.window.set_zoom(100)
        canvas_point = self.window.canvas.image_to_widget(QPointF(50, 50))

        QApplication.sendEvent(
            self.window.canvas,
            wheel_event(
                angle=120,
                modifiers=Qt.ControlModifier,
                position=canvas_point,
            ),
        )
        self.assertAlmostEqual(self.window.zoom_widget.value(), 110.0)

        self.window.set_zoom(100)
        QApplication.sendEvent(
            self.window.zoom_widget.slider,
            wheel_event(angle=120),
        )
        self.assertAlmostEqual(self.window.zoom_widget.value(), 110.0)

        self.window.set_zoom(100)
        QApplication.sendEvent(
            self.window.canvas,
            wheel_event(
                pixel=24,
                angle=0,
                modifiers=Qt.ControlModifier,
                position=canvas_point,
            ),
        )
        self.assertAlmostEqual(
            self.window.zoom_widget.value(),
            100.0 * math.pow(1.10, 0.2),
        )

    def image_point_at_viewport(self, viewport_point):
        canvas_point = self.window.canvas.mapFrom(
            self.window.scroll_area.viewport(),
            viewport_point,
        )
        return self.window.canvas.transform_pos(QPointF(canvas_point))

    def viewport_point_for_image(self, image_point):
        origin = self.window.canvas.mapTo(
            self.window.scroll_area.viewport(),
            QPoint(0, 0),
        )
        return QPointF(origin) + self.window.canvas.image_to_widget(image_point)

    def drag_zoom_slider_right(self, distance=8):
        slider = self.window.zoom_widget.slider
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        handle = slider.style().subControlRect(
            QStyle.CC_Slider,
            option,
            QStyle.SC_SliderHandle,
            slider,
        )
        start_global = slider.mapToGlobal(handle.center())
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(handle.center()),
            QPointF(start_global),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        QApplication.sendEvent(slider, press)
        samples = []
        for offset in range(1, distance + 1):
            global_point = QPoint(start_global.x() + offset, start_global.y())
            local_point = slider.mapFromGlobal(global_point)
            move = QMouseEvent(
                QEvent.MouseMove,
                QPointF(local_point),
                QPointF(global_point),
                Qt.NoButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            QApplication.sendEvent(slider, move)
            self.app.processEvents()
            samples.append((
                offset,
                slider.value(),
                self.window.zoom_widget.value(),
                slider.mapToGlobal(QPoint()).x(),
                self.window.zoom_widget.value_button.width(),
            ))
        release_global = QPoint(
            start_global.x() + distance,
            start_global.y(),
        )
        release = QMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(slider.mapFromGlobal(release_global)),
            QPointF(release_global),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
        QApplication.sendEvent(slider, release)
        return samples

    def test_dragging_zoom_slider_right_never_reduces_zoom(self):
        self.load_image(1, 100)
        self.window.set_zoom(20)
        self.app.processEvents()

        samples = self.drag_zoom_slider_right()
        values = [sample[2] for sample in samples]

        self.assertTrue(all(
            later >= earlier
            for earlier, later in zip(values, values[1:])
        ), samples)
        self.assertEqual(len({sample[3] for sample in samples}), 1, samples)
        self.assertEqual(len({sample[4] for sample in samples}), 1, samples)

    def test_ctrl_wheel_refreshes_coordinates_at_the_pointer(self):
        self.load_image(30, 30)
        viewport_point = QPoint(10, 10)
        canvas_point = QPointF(self.window.canvas.mapFrom(
            self.window.scroll_area.viewport(),
            viewport_point,
        ))
        global_point = self.window.canvas.mapToGlobal(canvas_point.toPoint())
        move = QMouseEvent(
            QEvent.MouseMove,
            canvas_point,
            QPointF(global_point),
            Qt.NoButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
        QApplication.sendEvent(self.window.canvas, move)
        QApplication.sendEvent(
            self.window.canvas,
            wheel_event(
                angle=120,
                modifiers=Qt.ControlModifier,
                position=canvas_point,
            ),
        )
        self.app.processEvents()

        canvas_point = QPointF(self.window.canvas.mapFrom(
            self.window.scroll_area.viewport(),
            viewport_point,
        ))
        image_point = self.window.canvas.transform_pos(canvas_point)
        inside = 0 <= image_point.x() < 30 and 0 <= image_point.y() < 30
        expected = ("X: %d  Y: %d" % (math.floor(image_point.x()),
                                     math.floor(image_point.y()))
                    if inside else "X: —  Y: —")
        self.assertEqual(self.window.label_coordinates.text(), expected)

    def test_repeated_ctrl_wheel_round_trip_does_not_drift(self):
        self.load_image(1600, 1200)
        self.window.set_zoom(100)
        self.app.processEvents()
        self.window.scroll_bars[Qt.Horizontal].setValue(350)
        self.window.scroll_bars[Qt.Vertical].setValue(240)
        viewport_point = QPoint(220, 170)
        before = self.image_point_at_viewport(viewport_point)

        errors = []
        for angle in (120, -120) * 40:
            canvas_point = QPointF(self.window.canvas.mapFrom(
                self.window.scroll_area.viewport(),
                viewport_point,
            ))
            QApplication.sendEvent(
                self.window.canvas,
                wheel_event(
                    angle=angle,
                    modifiers=Qt.ControlModifier,
                    position=canvas_point,
                ),
            )
            self.app.processEvents()
            current = self.image_point_at_viewport(viewport_point)
            errors.append(
                math.hypot(
                    current.x() - before.x(),
                    current.y() - before.y(),
                ) * self.window.canvas.scale
            )

        self.assertLessEqual(max(errors), 0.5, errors)

    def test_repeated_ctrl_wheel_round_trip_on_fitted_image_does_not_drift(self):
        self.load_image(400, 350)
        self.window.set_zoom(100)
        self.app.processEvents()
        image_point = QPointF(150, 120)
        viewport_location = self.viewport_point_for_image(image_point)
        viewport_point = QPoint(
            round(viewport_location.x()),
            round(viewport_location.y()),
        )
        before = self.image_point_at_viewport(viewport_point)

        errors = []
        for angle in (120, -120) * 40:
            canvas_point = QPointF(self.window.canvas.mapFrom(
                self.window.scroll_area.viewport(),
                viewport_point,
            ))
            QApplication.sendEvent(
                self.window.canvas,
                wheel_event(
                    angle=angle,
                    modifiers=Qt.ControlModifier,
                    position=canvas_point,
                ),
            )
            self.app.processEvents()
            current = self.image_point_at_viewport(viewport_point)
            errors.append(
                math.hypot(
                    current.x() - before.x(),
                    current.y() - before.y(),
                ) * self.window.canvas.scale
            )

        self.assertLessEqual(max(errors), 0.5, errors)

    def test_cursor_anchor_is_stable_and_zoom_round_trip_has_no_drift(self):
        self.load_image(1600, 1200)
        self.window.set_zoom(100)
        self.app.processEvents()
        self.window.scroll_bars[Qt.Horizontal].setValue(350)
        self.window.scroll_bars[Qt.Vertical].setValue(240)
        viewport_point = QPoint(220, 170)
        before = self.image_point_at_viewport(viewport_point)

        canvas_point = self.window.canvas.mapFrom(
            self.window.scroll_area.viewport(),
            viewport_point,
        )
        self.window.zoom_request(1.0, QPointF(canvas_point))
        self.app.processEvents()
        after_in = self.image_point_at_viewport(viewport_point)
        self.assertLessEqual(
            math.hypot(after_in.x() - before.x(), after_in.y() - before.y())
            * self.window.canvas.scale,
            0.5,
        )

        canvas_point = self.window.canvas.mapFrom(
            self.window.scroll_area.viewport(),
            viewport_point,
        )
        self.window.zoom_request(-1.0, QPointF(canvas_point))
        self.app.processEvents()
        after_out = self.image_point_at_viewport(viewport_point)
        self.assertAlmostEqual(self.window.zoom_widget.value(), 100.0)
        self.assertLessEqual(
            math.hypot(after_out.x() - before.x(), after_out.y() - before.y())
            * self.window.canvas.scale,
            0.5,
        )

    def test_small_image_stays_at_actual_size_for_fit_window(self):
        self.load_image(30, 30)

        self.assertEqual(self.window.zoom_widget.value(), 100.0)
        self.window.set_fit_window(True)
        self.assertEqual(self.window.zoom_widget.value(), 100.0)

    def test_small_image_cursor_anchor_overrides_automatic_centering(self):
        self.load_image(30, 30)
        image_point = QPointF(5, 7)
        before = self.viewport_point_for_image(image_point)
        canvas_point = self.window.canvas.image_to_widget(image_point)

        self.window.zoom_request(1.0, canvas_point)
        self.app.processEvents()

        after = self.viewport_point_for_image(image_point)
        self.assertLessEqual(
            math.hypot(after.x() - before.x(), after.y() - before.y()),
            0.5,
        )
        self.assertFalse(self.window.canvas.view_offset.isNull())

    def test_cursor_anchor_survives_scrollbar_appearance(self):
        self.load_image(300, 300)
        image_point = QPointF(60, 80)
        before = self.viewport_point_for_image(image_point)
        canvas_point = self.window.canvas.image_to_widget(image_point)

        self.window.zoom_request(20.0, canvas_point)
        self.app.processEvents()
        self.app.processEvents()

        after = self.viewport_point_for_image(image_point)
        self.assertLessEqual(
            math.hypot(after.x() - before.x(), after.y() - before.y()),
            0.5,
        )
        self.assertGreater(
            self.window.scroll_bars[Qt.Vertical].maximum(),
            0,
        )
        self.assertLessEqual(
            math.hypot(
                self.window.canvas.view_offset.x(),
                self.window.canvas.view_offset.y(),
            ),
            0.75,
        )

    def test_blank_area_zoom_anchors_the_nearest_image_boundary(self):
        self.load_image(30, 30)
        blank_canvas_point = QPointF(0, 0)
        image_point, before = self.window._capture_zoom_anchor(
            blank_canvas_point
        )
        self.assertEqual(image_point, QPointF(0, 0))

        self.window.zoom_request(1.0, blank_canvas_point)
        self.app.processEvents()

        after = self.viewport_point_for_image(image_point)
        self.assertLessEqual(
            math.hypot(after.x() - before.x(), after.y() - before.y()),
            0.5,
        )

    def test_extreme_fit_can_use_sub_one_percent_as_dynamic_minimum(self):
        self.load_image(20, 10)
        self.window.canvas.load_pixmap(
            QPixmap(20, 10),
            logical_size=(200000, 100000),
        )
        self.window.set_fit_window(True)
        self.app.processEvents()

        value = self.window.zoom_widget.value()
        self.assertLess(value, 1.0)
        self.assertAlmostEqual(self.window.zoom_widget.minimumValue(), value)
        self.window.add_zoom(1.0)
        self.assertAlmostEqual(
            self.window.zoom_widget.value(),
            value * self.window.ZOOM_FACTOR,
        )

    def test_fit_width_extends_the_dynamic_maximum(self):
        self.load_image(1, 100)
        expected = 100.0 * self.window.scale_fit_width()

        self.assertGreater(expected, 600.0)
        self.assertTrue(self.window.actions.fitWidth.isEnabled())
        self.assertAlmostEqual(
            self.window.zoom_widget.maximumValue(),
            expected,
        )
        self.window.set_fit_width(True)
        self.assertAlmostEqual(self.window.zoom_widget.value(), expected)

    def test_switching_images_recomputes_the_dynamic_range(self):
        self.load_image(1, 100, "narrow.png")
        self.assertGreater(self.window.zoom_widget.maximumValue(), 600.0)

        self.load_image(1600, 1200, "large.png")

        self.assertEqual(self.window.zoom_widget.maximumValue(), 600.0)

    def test_fit_width_is_disabled_only_beyond_the_safe_canvas_size(self):
        self.load_image(20, 10)
        self.window.canvas.load_pixmap(
            QPixmap(1, 1000),
            logical_size=(1, 100000),
        )
        self.window.set_fit_window(True)

        self.assertFalse(self.window.actions.fitWidth.isEnabled())
        self.assertEqual(self.window.zoom_widget.maximumValue(), 600.0)

    def test_one_image_can_extend_both_dynamic_bounds(self):
        self.load_image(20, 10)
        self.window.canvas.load_pixmap(
            QPixmap(50, 1000),
            logical_size=(50, 200000),
        )
        self.window.set_fit_window(True)
        expected_minimum = 100.0 * self.window.scale_fit_window()
        expected_maximum = 100.0 * self.window.scale_fit_width()

        self.assertLess(expected_minimum, 1.0)
        self.assertGreater(expected_maximum, 600.0)
        self.assertAlmostEqual(
            self.window.zoom_widget.minimumValue(),
            expected_minimum,
        )
        self.assertAlmostEqual(
            self.window.zoom_widget.maximumValue(),
            expected_maximum,
        )

    def test_incremental_zoom_snaps_once_to_actual_size(self):
        self.load_image(100, 100)
        self.window.set_zoom(98)

        self.window.add_zoom(1.0)
        self.assertEqual(self.window.zoom_widget.value(), 100.0)
        self.window.add_zoom(1.0)
        self.assertAlmostEqual(self.window.zoom_widget.value(), 110.0)

    def test_manual_zoom_is_retained_when_dynamic_range_contracts(self):
        self.load_image(50, 100)
        self.assertGreater(self.window.zoom_widget.maximumValue(), 600.0)
        self.window.set_zoom(800)
        self.app.processEvents()

        self.window.resize(self.window.minimumWidth(), 760)
        self.app.processEvents()
        self.app.processEvents()

        self.assertAlmostEqual(self.window.zoom_widget.value(), 800.0)
        self.assertGreaterEqual(
            self.window.zoom_widget.maximumValue(),
            800.0,
        )

    def test_manual_zoom_keeps_percentage_and_center_point_on_resize(self):
        self.load_image(1600, 1200)
        self.window.set_zoom(125)
        self.app.processEvents()
        self.window.scroll_bars[Qt.Horizontal].setValue(420)
        self.window.scroll_bars[Qt.Vertical].setValue(310)
        old_center = self.window.scroll_area.viewport().rect().center()
        before = self.image_point_at_viewport(old_center)

        self.window.resize(1320, 820)
        self.app.processEvents()
        self.app.processEvents()

        new_center = self.window.scroll_area.viewport().rect().center()
        after = self.image_point_at_viewport(new_center)
        self.assertEqual(self.window.zoom_widget.value(), 125.0)
        self.assertLessEqual(
            math.hypot(after.x() - before.x(), after.y() - before.y())
            * self.window.canvas.scale,
            0.5,
            (
                before,
                after,
                self.window.scroll_area.viewport().size(),
                self.window.canvas.view_offset,
                self.window.scroll_bars[Qt.Horizontal].value(),
                self.window.scroll_bars[Qt.Vertical].value(),
            ),
        )

    def test_direct_slider_change_leaves_fit_mode(self):
        self.load_image(1600, 1200)
        self.assertEqual(self.window.zoom_mode, self.window.FIT_WINDOW)

        self.window.zoom_widget.slider.setValue(
            self.window.zoom_widget.slider.value() + 10
        )

        self.assertEqual(self.window.zoom_mode, self.window.MANUAL_ZOOM)
        self.assertFalse(self.window.actions.fitWindow.isChecked())


if __name__ == "__main__":
    unittest.main()
