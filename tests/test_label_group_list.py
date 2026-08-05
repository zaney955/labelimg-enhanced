import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import (
    QColor,
    QContextMenuEvent,
    QImage,
    QKeyEvent,
    QPainter,
)
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton

from labelimg.label_group_list import LabelGroupListWidget
from labelimg.shape import Shape


def rectangle(label, x, color=None):
    shape = Shape(label=label)
    for point in (
        QPointF(x, 10),
        QPointF(x + 10, 10),
        QPointF(x + 10, 20),
        QPointF(x, 20),
    ):
        shape.add_point(point)
    shape.close()
    if color is not None:
        shape.line_color = QColor(color)
    return shape


class LabelGroupListWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = LabelGroupListWidget()
        self.widget.resize(360, 180)
        self.widget.show()
        self.selection_requests = []
        self.visibility_requests = []
        self.hover_requests = []
        self.context_requests = []
        self.widget.selectionRequested.connect(
            lambda shapes, active: self.selection_requests.append(
                (tuple(shapes), active)
            )
        )
        self.widget.visibilityRequested.connect(
            lambda shapes, visible: self.visibility_requests.append(
                (tuple(shapes), visible)
            )
        )
        self.widget.hoverRequested.connect(
            lambda shapes: self.hover_requests.append(tuple(shapes))
        )
        self.widget.contextMenuRequested.connect(
            lambda target, pos: self.context_requests.append(target)
        )

    def tearDown(self):
        self.widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def set_scene(self, shapes, visible=None):
        self.widget.set_scene(
            shapes,
            visible_shapes=shapes if visible is None else visible,
        )
        self.app.processEvents()

    def test_groups_exact_labels_and_keeps_document_order(self):
        car_first = rectangle("car", 10)
        person = rectangle("person", 30)
        car_second = rectangle("car", 50)
        upper_car = rectangle("Car", 70)

        self.set_scene([car_first, person, car_second, upper_car])

        self.assertEqual(self.widget.group_labels(), ["Car", "car", "person"])
        self.assertEqual(
            self.widget.group_shapes("car"),
            (car_first, car_second),
        )
        self.assertEqual(self.widget.group_count(), 3)
        self.assertEqual(self.widget.annotation_count(), 4)

    def test_instance_click_selects_one_and_group_body_selects_group(self):
        first = rectangle("car", 10)
        second = rectangle("car", 30)
        self.set_scene([first, second])

        QTest.mouseClick(
            self.widget.viewport(),
            Qt.LeftButton,
            pos=self.widget.instance_rect(second).center(),
        )
        self.assertEqual(self.selection_requests[-1], ((second,), second))

        QTest.mouseClick(
            self.widget.viewport(),
            Qt.LeftButton,
            pos=self.widget.group_body_rect("car").center(),
        )
        self.assertEqual(
            self.selection_requests[-1],
            ((first, second), None),
        )

    def test_shift_range_crosses_group_rows_in_visual_order(self):
        alpha_first = rectangle("alpha", 10)
        alpha_second = rectangle("alpha", 30)
        bravo = rectangle("bravo", 50)
        charlie = rectangle("charlie", 70)
        self.set_scene([alpha_first, bravo, alpha_second, charlie])

        QTest.mouseClick(
            self.widget.viewport(),
            Qt.LeftButton,
            pos=self.widget.instance_rect(alpha_second).center(),
        )
        self.widget.project_selection((alpha_second,), alpha_second)
        QTest.mouseClick(
            self.widget.viewport(),
            Qt.LeftButton,
            Qt.ShiftModifier,
            pos=self.widget.instance_rect(charlie).center(),
        )

        self.assertEqual(
            self.selection_requests[-1],
            ((alpha_second, bravo, charlie), charlie),
        )

    def test_group_anchor_stays_complete_when_shift_extends(self):
        alpha = [rectangle("alpha", 10), rectangle("alpha", 30)]
        bravo = rectangle("bravo", 50)
        self.set_scene(alpha + [bravo])

        QTest.mouseClick(
            self.widget.viewport(),
            Qt.LeftButton,
            pos=self.widget.group_body_rect("alpha").center(),
        )
        self.widget.project_selection(tuple(alpha), None)
        QTest.mouseClick(
            self.widget.viewport(),
            Qt.LeftButton,
            Qt.ShiftModifier,
            pos=self.widget.instance_rect(bravo).center(),
        )

        self.assertEqual(
            self.selection_requests[-1],
            ((alpha[0], alpha[1], bravo), bravo),
        )

    def test_visibility_eye_reports_group_wide_three_state_action(self):
        visible = rectangle("car", 10)
        hidden = rectangle("car", 30)
        self.set_scene([visible, hidden], visible=[visible])

        self.assertEqual(self.widget.group_visibility("car"), Qt.PartiallyChecked)
        QTest.mouseClick(
            self.widget.viewport(),
            Qt.LeftButton,
            pos=self.widget.visibility_rect_for_label("car").center(),
        )

        self.assertEqual(
            self.visibility_requests[-1],
            ((visible, hidden), True),
        )

        self.widget.set_scene([visible, hidden], visible_shapes=[visible, hidden])
        QTest.mouseClick(
            self.widget.viewport(),
            Qt.LeftButton,
            pos=self.widget.visibility_rect_for_label("car").center(),
        )
        self.assertEqual(
            self.visibility_requests[-1],
            ((visible, hidden), False),
        )

    def test_button_uses_the_shape_opaque_outline_color(self):
        shape = rectangle("car", 10, QColor(12, 34, 56, 80))
        self.set_scene([shape])
        image = QImage(self.widget.viewport().size(), QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        self.widget.render(painter)
        painter.end()

        center = self.widget.instance_rect(shape).center()
        actual = image.pixelColor(center)
        self.assertEqual(actual, QColor(12, 34, 56, 255))

    def test_overflow_keeps_all_instances_and_scrolls_only_the_strip(self):
        shapes = [rectangle("car", index * 20) for index in range(20)]
        self.set_scene(shapes)

        self.assertEqual(self.widget.group_shapes("car"), tuple(shapes))
        self.assertGreater(self.widget.maximum_group_scroll("car"), 0)
        self.assertEqual(self.widget.group_scroll("car"), 0)

        self.widget.ensure_shape_visible(shapes[-1])

        self.assertGreater(self.widget.group_scroll("car"), 0)
        self.assertTrue(self.widget.instance_rect(shapes[-1]).isValid())

    def test_filter_reports_visible_totals_and_preserves_selection(self):
        car = rectangle("car", 10)
        person = rectangle("person", 30)
        self.set_scene([car, person])
        self.widget.project_selection((person,), person)

        self.widget.set_filter_text("car")

        self.assertEqual(self.widget.group_labels(), ["car"])
        self.assertEqual(
            self.widget.summary_text(),
            "显示 1/2 个标签组 · 1/2 个标注 · 另有 1 个已选标注未显示",
        )
        self.assertEqual(self.widget.selected_shapes(), (person,))

    def test_filtered_ctrl_a_selects_only_visible_results(self):
        car = rectangle("car", 10)
        person = rectangle("person", 30)
        self.set_scene([car, person])
        self.widget.set_filter_text("car")

        self.widget.keyPressEvent(QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_A,
            Qt.ControlModifier,
        ))

        self.assertEqual(self.selection_requests[-1], ((car,), car))

    def test_filtered_ctrl_click_preserves_selected_hidden_results(self):
        car = rectangle("car", 10)
        person = rectangle("person", 30)
        self.set_scene([car, person])
        self.widget.project_selection((person,), person)
        self.widget.set_filter_text("car")

        QTest.mouseClick(
            self.widget.viewport(),
            Qt.LeftButton,
            Qt.ControlModifier,
            self.widget.instance_rect(car).center(),
        )

        self.assertEqual(self.selection_requests[-1], ((car, person), car))

    def test_scroll_survives_same_scene_and_filter_but_resets_explicitly(self):
        shapes = [rectangle("car", index * 20) for index in range(20)]
        self.set_scene(shapes)
        self.widget.ensure_shape_visible(shapes[-1])
        offset = self.widget.group_scroll("car")

        self.widget.set_filter_text("car")
        self.widget.set_filter_text("")
        self.widget.set_scene(shapes, visible_shapes=shapes)
        self.assertEqual(self.widget.group_scroll("car"), offset)

        self.widget.set_scene(
            shapes,
            visible_shapes=shapes,
            reset_scroll=True,
        )
        self.assertEqual(self.widget.group_scroll("car"), 0)

    def test_large_group_is_virtualized_without_child_buttons(self):
        shapes = [rectangle("car", index * 20) for index in range(1000)]
        self.set_scene(shapes)

        self.assertEqual(len(self.widget.group_shapes("car")), 1000)
        self.assertEqual(self.widget.findChildren(QPushButton), [])

    def test_instance_hover_previews_one_and_group_hover_previews_visible_group(self):
        first = rectangle("car", 10)
        second = rectangle("car", 30)
        self.set_scene([first, second])

        QTest.mouseMove(
            self.widget.viewport(),
            pos=self.widget.instance_rect(second).center(),
        )
        self.assertEqual(self.hover_requests[-1], (second,))

        QTest.mouseMove(
            self.widget.viewport(),
            pos=self.widget.group_body_rect("car").center(),
        )
        self.assertEqual(self.hover_requests[-1], (first, second))

    def test_instance_tooltip_identifies_ordinal_and_geometry(self):
        first = rectangle("car", 10)
        second = rectangle("car", 30)
        self.set_scene([first, second])

        self.assertEqual(
            self.widget.tooltip_at(
                self.widget.instance_rect(second).center()
            ),
            "car #2｜x:30 y:10 w:10 h:10",
        )

    def test_instance_context_menu_selects_unselected_target_once(self):
        first = rectangle("car", 10)
        second = rectangle("car", 30)
        self.set_scene([first, second])
        self.widget.project_selection((first,), first)
        pos = self.widget.instance_rect(second).center()

        event = QContextMenuEvent(
            QContextMenuEvent.Mouse,
            pos,
            self.widget.viewport().mapToGlobal(pos),
        )
        QApplication.sendEvent(self.widget.viewport(), event)

        self.assertEqual(self.selection_requests, [((second,), second)])
        self.assertEqual(self.context_requests, [("instance", second)])


if __name__ == "__main__":
    unittest.main()
