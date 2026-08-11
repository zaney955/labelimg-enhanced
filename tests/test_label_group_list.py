import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QPalette,
    QPainter,
)
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton

from labelimg.label_group_list import LabelGroupListWidget
from labelimg.i18n import SIMPLIFIED_CHINESE, set_language
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
        set_language(SIMPLIFIED_CHINESE)
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

    def render_view(self):
        image = QImage(
            self.widget.viewport().size(),
            QImage.Format_ARGB32,
        )
        image.fill(QColor("transparent"))
        painter = QPainter(image)
        self.widget.viewport().render(painter)
        painter.end()
        return image

    @staticmethod
    def blended(foreground, background, alpha):
        ratio = alpha / 255.0
        return QColor(
            round(foreground.red() * ratio + background.red() * (1 - ratio)),
            round(foreground.green() * ratio + background.green() * (1 - ratio)),
            round(foreground.blue() * ratio + background.blue() * (1 - ratio)),
        )

    def assert_color_close(self, actual, expected, tolerance=2):
        for actual_channel, expected_channel in zip(
            actual.getRgb()[:3],
            expected.getRgb()[:3],
        ):
            self.assertLessEqual(
                abs(actual_channel - expected_channel),
                tolerance,
            )

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

    def test_button_uses_transparent_fill_and_shape_outline_color(self):
        shape = rectangle("car", 10, QColor(12, 34, 56, 80))
        self.set_scene([shape])
        image = self.render_view()
        rect = self.widget.instance_rect(shape)
        base = self.widget.palette().color(QPalette.Base)

        self.assert_color_close(
            image.pixelColor(rect.left() + 5, rect.top() + 17),
            base,
        )
        self.assert_color_close(
            image.pixelColor(rect.left() + 1, rect.center().y()),
            QColor(12, 34, 56),
        )

    def test_selected_button_uses_32_alpha_shape_fill(self):
        shape = rectangle("car", 10, QColor(40, 120, 200))
        self.set_scene([shape])
        self.widget.project_selection((shape,), shape)

        image = self.render_view()
        rect = self.widget.instance_rect(shape)
        expected = self.blended(
            QColor(40, 120, 200),
            self.widget.palette().color(QPalette.Base),
            32,
        )
        self.assert_color_close(
            image.pixelColor(rect.left() + 5, rect.top() + 5),
            expected,
        )

    def test_hidden_button_stays_transparent_and_dims_its_outline(self):
        shape = rectangle("car", 10, QColor(20, 80, 160))
        self.set_scene([shape], visible=[])
        image = self.render_view()
        rect = self.widget.instance_rect(shape)
        base = self.widget.palette().color(QPalette.Base)

        self.assert_color_close(
            image.pixelColor(rect.left() + 5, rect.top() + 17),
            base,
        )
        self.assert_color_close(
            image.pixelColor(rect.left() + 1, rect.center().y()),
            self.blended(QColor(20, 80, 160), base, 115),
        )

    def test_hover_replaces_shape_outline_with_dashes(self):
        shape = rectangle("car", 10, QColor(20, 80, 160))
        self.set_scene([shape])
        rect = self.widget.instance_rect(shape)

        solid = self.render_view()
        QTest.mouseMove(self.widget.viewport(), pos=rect.center())
        dashed = self.render_view()

        def colored_pixels(image):
            return sum(
                1
                for x in range(rect.left() + 4, rect.right() - 3)
                if max(
                    abs(a - b)
                    for a, b in zip(
                        image.pixelColor(x, rect.top() + 1).getRgb()[:3],
                        (20, 80, 160),
                    )
                ) < 35
            )

        self.assertGreater(colored_pixels(solid), colored_pixels(dashed))
        self.assertGreater(colored_pixels(dashed), 0)

    def test_selected_hover_keeps_fill_while_outline_becomes_dashed(self):
        shape = rectangle("car", 10, QColor(40, 120, 200))
        self.set_scene([shape])
        self.widget.project_selection((shape,), shape)
        rect = self.widget.instance_rect(shape)

        QTest.mouseMove(self.widget.viewport(), pos=rect.center())
        image = self.render_view()
        hover_background = self.blended(
            self.widget.palette().color(QPalette.Mid),
            self.widget.palette().color(QPalette.Base),
            45,
        )
        expected_fill = self.blended(
            QColor(40, 120, 200),
            hover_background,
            32,
        )

        self.assert_color_close(
            image.pixelColor(rect.left() + 5, rect.top() + 5),
            expected_fill,
        )
        top_colors = [
            image.pixelColor(x, rect.top() + 1)
            for x in range(rect.left() + 4, rect.right() - 3)
        ]
        self.assertTrue(any(
            max(
                abs(a - b)
                for a, b in zip(color.getRgb()[:3], (40, 120, 200))
            ) < 35
            for color in top_colors
        ))
        self.assertTrue(any(
            max(
                abs(a - b)
                for a, b in zip(
                    color.getRgb()[:3],
                    expected_fill.getRgb()[:3],
                )
            ) < 5
            for color in top_colors
        ))

    def test_group_hover_uses_file_list_gray_background(self):
        shape = rectangle("car", 10)
        self.set_scene([shape])
        sample = QPointF(
            self.widget.group_body_rect("car").right() - 3,
            self.widget.group_body_rect("car").center().y(),
        ).toPoint()
        base = self.widget.palette().color(QPalette.Base)

        QTest.mouseMove(self.widget.viewport(), pos=sample)
        image = self.render_view()
        expected = self.blended(
            self.widget.palette().color(QPalette.Mid),
            base,
            45,
        )

        self.assert_color_close(image.pixelColor(sample), expected)

    def test_count_and_visibility_columns_use_faint_dividers(self):
        shape = rectangle("car", 10)
        self.set_scene([shape])
        image = self.render_view()
        count = self.widget.count_rect_for_label("car")
        visibility = self.widget.visibility_rect_for_label("car")
        expected = self.blended(
            self.widget.palette().color(QPalette.Mid),
            self.widget.palette().color(QPalette.Base),
            45,
        )

        self.assert_color_close(
            image.pixelColor(count.left(), count.center().y()),
            expected,
        )
        self.assert_color_close(
            image.pixelColor(visibility.left(), visibility.center().y()),
            expected,
        )

    def test_overflow_keeps_all_instances_and_scrolls_only_the_strip(self):
        shapes = [rectangle("car", index * 20) for index in range(20)]
        self.set_scene(shapes)

        self.assertEqual(self.widget.group_shapes("car"), tuple(shapes))
        self.assertGreater(self.widget.maximum_group_scroll("car"), 0)
        self.assertEqual(self.widget.group_scroll("car"), 0)

        self.widget.ensure_shape_visible(shapes[-1])

        self.assertGreater(self.widget.group_scroll("car"), 0)
        self.assertTrue(self.widget.instance_rect(shapes[-1]).isValid())

    def test_visible_groups_share_a_content_fitted_label_column(self):
        first = rectangle("P_LS_JM", 10)
        second = rectangle("PD_LSQS", 30)
        self.set_scene([first, second])

        first_label = self.widget.group_body_rect("P_LS_JM")
        second_label = self.widget.group_body_rect("PD_LSQS")
        first_button = self.widget.instance_rect(first)
        second_button = self.widget.instance_rect(second)
        measurement_font = QFont(self.widget.font())
        measurement_font.setBold(True)
        measurement_metrics = QFontMetrics(measurement_font)
        measure = getattr(
            measurement_metrics,
            "horizontalAdvance",
            measurement_metrics.width,
        )
        desired = max(
            self.widget.label_min_width,
            max(measure("P_LS_JM"), measure("PD_LSQS"))
            + self.widget.label_button_gap,
        )
        available = self.widget.viewport().width() - 1
        maximum = min(
            self.widget.label_max_width,
            int(available * self.widget.label_width_ratio),
            available
            - self.widget.count_area_width
            - self.widget.visibility_area_width
            - self.widget.label_left_margin
            - self.widget.chip_size,
        )
        expected = min(desired, maximum)

        self.assertEqual(first_label.width(), expected)
        self.assertEqual(second_label.width(), expected)
        self.assertEqual(first_button.left(), second_button.left())

    def test_label_column_reserves_bold_selected_text_without_relayout(self):
        shape = rectangle("P_LS_JM", 10)
        self.widget.resize(700, 180)
        self.set_scene([shape])
        self.widget._invalidate_label_width()
        with patch(
            "labelimg.label_group_list.QFontMetrics",
            wraps=QFontMetrics,
        ) as metrics_factory:
            before_label = self.widget.group_body_rect(shape.label)
        self.assertTrue(metrics_factory.called)
        measurement_font = metrics_factory.call_args.args[0]
        self.assertTrue(measurement_font.bold())
        before_button = self.widget.instance_rect(shape)

        selected_font = QFont(self.widget.font())
        selected_font.setBold(True)
        selected_metrics = QFontMetrics(selected_font)
        measure = getattr(
            selected_metrics,
            "horizontalAdvance",
            selected_metrics.width,
        )
        text_capacity = (
            before_label.width() - self.widget.label_button_gap
        )

        self.assertLessEqual(measure(shape.label), text_capacity)

        self.widget.project_selection((shape,), shape)
        self.app.processEvents()

        self.assertEqual(
            self.widget.group_body_rect(shape.label),
            before_label,
        )
        self.assertEqual(self.widget.instance_rect(shape), before_button)

    def test_capped_label_uses_one_bold_elision_in_every_selection_state(self):
        shape = rectangle("extraordinarily_long_class_name", 10)
        self.widget.resize(360, 180)
        self.set_scene([shape])
        capacity = (
            self.widget.group_body_rect(shape.label).width()
            - self.widget.label_button_gap
        )

        unselected_text = self.widget._elided_label_text(
            shape.label,
            capacity,
        )
        self.widget.project_selection((shape,), shape)
        selected_text = self.widget._elided_label_text(
            shape.label,
            capacity,
        )

        selected_font = QFont(self.widget.font())
        selected_font.setBold(True)
        selected_metrics = QFontMetrics(selected_font)
        self.assertEqual(
            unselected_text,
            selected_metrics.elidedText(
                shape.label,
                Qt.ElideRight,
                capacity,
            ),
        )
        self.assertEqual(selected_text, unselected_text)

    def test_long_label_can_use_45_percent_up_to_240_pixels(self):
        shape = rectangle("x" * 200, 10)
        self.widget.resize(360, 180)
        self.set_scene([shape])
        available = self.widget.viewport().width() - 1

        self.assertEqual(
            self.widget.group_body_rect(shape.label).width(),
            int(available * 0.45),
        )

        self.widget.resize(700, 180)
        self.app.processEvents()

        self.assertEqual(
            self.widget.group_body_rect(shape.label).width(),
            240,
        )
        self.assertLess(
            self.widget.instance_rect(shape).right(),
            self.widget.count_rect_for_label(shape.label).left(),
        )

    def test_filter_recomputes_label_column_from_visible_groups(self):
        short = rectangle("car", 10)
        long = rectangle("extraordinarily_long_class_name", 30)
        self.set_scene([short, long])
        before = self.widget.group_body_rect("car").width()
        before_button = self.widget.instance_rect(short).left()

        self.widget.set_filter_text("car")

        after = self.widget.group_body_rect("car").width()
        after_button = self.widget.instance_rect(short).left()
        self.assertLess(after, before)
        self.assertLess(after_button, before_button)

    def test_filter_keeps_hidden_group_horizontal_position(self):
        car = rectangle("car", 10)
        long_group = [
            rectangle("extraordinarily_long_class_name", 30 + index * 20)
            for index in range(20)
        ]
        self.set_scene([car] + long_group)
        self.widget.ensure_shape_visible(long_group[-1])
        before = self.widget.group_scroll("extraordinarily_long_class_name")

        self.widget.set_filter_text("car")

        self.assertEqual(
            self.widget.group_scroll("extraordinarily_long_class_name"),
            before,
        )

    def test_narrow_layout_keeps_one_complete_button_before_fixed_columns(self):
        self.widget.resize(130, 180)
        shapes = [rectangle("long_class_name", index * 20) for index in range(8)]
        self.set_scene(shapes)

        first_button = self.widget.instance_rect(shapes[0])
        count = self.widget.count_rect_for_label("long_class_name")

        self.assertEqual(first_button.width(), self.widget.chip_size)
        self.assertGreaterEqual(first_button.left(), 0)
        self.assertLess(first_button.right(), count.left())

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
