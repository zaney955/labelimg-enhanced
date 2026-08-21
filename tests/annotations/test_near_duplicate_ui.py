import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPixmap
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication

from labelimg.canvas import (
    CATEGORY_CONFLICT,
    detect_near_duplicate_clusters,
)
from labelimg.annotations.ui.label_group_list import LabelGroupListWidget
from labelimg.annotations.ui.near_duplicate_chooser import NearDuplicateChooser
from labelimg.canvas.shape import Shape
from labelimg.canvas.widget import Canvas
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


def rectangle(label, left=20, top=20, right=80, bottom=80):
    shape = Shape(label)
    for point in (
        QPointF(left, top),
        QPointF(right, top),
        QPointF(right, bottom),
        QPointF(left, bottom),
    ):
        shape.add_point(point)
    shape.close()
    shape.line_color = QColor("#2673D9")
    return shape


class RecordingPainter(object):
    def __init__(self):
        self.texts = []
        self.lines = []

    def save(self):
        pass

    def restore(self):
        pass

    def setRenderHint(self, *_args):
        pass

    def setPen(self, *_args):
        pass

    def setBrush(self, *_args):
        pass

    def setFont(self, *_args):
        pass

    def font(self):
        return QFont()

    def drawRoundedRect(self, *_args):
        pass

    def drawEllipse(self, *_args):
        pass

    def drawRect(self, *_args):
        pass

    def drawText(self, *args):
        self.texts.append(args)

    def drawLine(self, *args):
        self.lines.append(args)


class NearDuplicateCanvasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = Canvas()
        self.canvas.resize(180, 140)
        pixmap = QPixmap(180, 140)
        pixmap.fill(QColor("white"))
        self.canvas.load_pixmap(pixmap)
        self.first = rectangle("cat")
        self.second = rectangle("cat")
        self.canvas.load_shapes((self.first, self.second))
        self.cluster = detect_near_duplicate_clusters(
            self.canvas.shapes
        )[0]
        self.canvas.set_near_duplicate_clusters((self.cluster,))
        self.canvas.show()
        self.app.processEvents()

    def tearDown(self):
        self.canvas.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_marker_is_screen_space_hit_target_only_in_edit_mode(self):
        image = QImage(180, 140, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        self.canvas.render(image)
        marker_rect = self.canvas._near_duplicate_marker_hits[0][0]
        requested = QSignalSpy(self.canvas.nearDuplicateRequested)

        QTest.mouseClick(
            self.canvas,
            Qt.LeftButton,
            pos=marker_rect.center().toPoint(),
        )
        self.assertEqual(len(requested), 1)
        self.assertIs(requested[0][0], self.cluster)

        self.canvas.set_mode(Canvas.PAN)
        QTest.mouseClick(
            self.canvas,
            Qt.LeftButton,
            pos=marker_rect.center().toPoint(),
        )
        self.assertEqual(len(requested), 1)

    def test_cluster_focus_collapses_selection_and_keeps_total_count(self):
        third = rectangle("other", 110, 20, 160, 70)
        self.canvas.shapes.append(third)
        self.canvas.set_selected_shapes((self.first, third))

        self.canvas.set_near_duplicate_focus(self.cluster, self.first)

        self.assertEqual(self.canvas.selected_shapes, [self.first])
        self.assertEqual(
            self.canvas._near_duplicate_marker_text(self.cluster),
            "2",
        )
        self.assertTrue(self.canvas.clear_near_duplicate_focus())
        self.assertEqual(self.canvas.selected_shapes, [self.first])

    def test_marker_reports_hidden_count_and_disappears_when_all_hidden(self):
        self.canvas.set_shape_visible(self.second, False)
        self.assertEqual(
            self.canvas._near_duplicate_marker_text(self.cluster),
            "2",
        )
        self.assertEqual(len(self.canvas._near_duplicate_marker_layout()), 1)

        self.canvas.set_shape_visible(self.first, False)
        self.assertEqual(self.canvas._near_duplicate_marker_layout(), ())

    def test_conflict_marker_text_does_not_repeat_conflict_glyph(self):
        different_label = rectangle("dog")
        self.canvas.shapes.append(different_label)
        cluster = detect_near_duplicate_clusters(self.canvas.shapes)[0]

        self.assertEqual(cluster.risk, CATEGORY_CONFLICT)
        # The painter already renders a dedicated mismatch glyph.
        self.assertEqual(self.canvas._near_duplicate_marker_text(cluster), "3")

    def test_canvas_conflict_icon_uses_not_equal_strokes(self):
        different_label = rectangle("dog")
        self.canvas.shapes.append(different_label)
        cluster = detect_near_duplicate_clusters(self.canvas.shapes)[0]
        self.canvas.set_near_duplicate_clusters((cluster,))
        painter = RecordingPainter()

        self.canvas._paint_near_duplicate_markers(painter)

        painted_text = [args[-1] for args in painter.texts]
        self.assertNotIn("!", painted_text)
        self.assertIn("3", painted_text)
        self.assertGreaterEqual(len(painter.lines), 3)

    def test_marker_tooltip_summarizes_labels_and_visibility(self):
        different_label = rectangle("dog")
        self.canvas.shapes.append(different_label)
        self.canvas.set_shape_visible(different_label, False)
        cluster = detect_near_duplicate_clusters(self.canvas.shapes)[0]

        tooltip = self.canvas._near_duplicate_tooltip(cluster)

        self.assertIn("cat ×2", tooltip)
        self.assertIn("dog ×1", tooltip)
        self.assertIn("2/3", tooltip)

    def test_default_marker_has_no_leader_and_displaced_marker_does(self):
        first = rectangle("cat", 20, 60, 80, 120)
        second = rectangle("cat", 20, 60, 80, 120)
        self.canvas.shapes = [first, second]
        cluster = detect_near_duplicate_clusters(self.canvas.shapes)[0]
        self.canvas.set_near_duplicate_clusters((cluster,))

        rect, _cluster, anchor = self.canvas._near_duplicate_marker_layout()[0]
        self.assertFalse(
            self.canvas._near_duplicate_marker_needs_leader(rect, anchor)
        )

        rect.translate(0, rect.height() + 4)
        self.assertTrue(
            self.canvas._near_duplicate_marker_needs_leader(rect, anchor)
        )

    def test_marker_hover_color_is_slightly_brighter(self):
        regular = self.canvas._near_duplicate_marker_color(self.cluster)
        hovered = self.canvas._near_duplicate_marker_color(
            self.cluster,
            hovered=True,
        )

        self.assertNotEqual(regular.name(), hovered.name())

    def test_marker_hover_state_clears_after_pointer_leaves_badge(self):
        image = QImage(180, 140, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        self.canvas.render(image)
        marker_rect = self.canvas._near_duplicate_marker_hits[0][0]

        QTest.mouseMove(self.canvas, marker_rect.center().toPoint())
        self.assertIs(
            self.canvas._near_duplicate_hover_cluster,
            self.cluster,
        )

        QTest.mouseMove(self.canvas, self.canvas.rect().bottomLeft())
        self.assertIsNone(self.canvas._near_duplicate_hover_cluster)

    def test_nearby_markers_shift_without_moving_their_anchors(self):
        third = rectangle("cat", 85, 20, 95, 30)
        fourth = rectangle("cat", 85, 20, 95, 30)
        self.canvas.shapes.extend((third, fourth))
        clusters = detect_near_duplicate_clusters(self.canvas.shapes)
        self.canvas.set_near_duplicate_clusters(clusters)

        layout = self.canvas._near_duplicate_marker_layout()

        self.assertEqual(len(layout), 2)
        first_rect, _first_cluster, first_anchor = layout[0]
        second_rect, _second_cluster, second_anchor = layout[1]
        self.assertFalse(first_rect.intersects(second_rect))
        self.assertNotEqual(first_anchor, second_anchor)


class NearDuplicateListAndChooserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.first = rectangle("cat")
        self.second = rectangle("cat")
        self.cluster = detect_near_duplicate_clusters(
            (self.first, self.second)
        )[0]

    def test_instance_risk_corner_opens_exact_cluster_without_selecting(self):
        widget = LabelGroupListWidget()
        widget.resize(360, 100)
        widget.set_scene((self.first, self.second))
        widget.set_near_duplicate_clusters((self.cluster,))
        widget.show()
        requested = QSignalSpy(widget.nearDuplicateRequested)
        selection = QSignalSpy(widget.selectionRequested)

        corner = widget._near_duplicate_corner_rect(self.first)
        QTest.mouseClick(
            widget.viewport(),
            Qt.LeftButton,
            pos=corner.center(),
        )

        self.assertEqual(len(requested), 1)
        self.assertIs(requested[0][0], self.cluster)
        self.assertIs(requested[0][2], self.first)
        self.assertEqual(len(selection), 0)
        widget.deleteLater()

    def test_group_risk_icon_uses_conflict_priority_without_a_count(self):
        dog = rectangle("dog")
        other_cat = rectangle("cat", 120, 20, 180, 80)
        other_cat_copy = rectangle("cat", 120, 20, 180, 80)
        clusters = detect_near_duplicate_clusters(
            (self.first, dog, other_cat, other_cat_copy)
        )
        widget = LabelGroupListWidget()
        widget.resize(360, 100)
        widget.set_scene((self.first, dog, other_cat, other_cat_copy))
        widget.set_near_duplicate_clusters(clusters)

        risk, involved = widget._group_near_duplicate_status(
            widget._groups_by_label["cat"]
        )

        self.assertEqual(risk, CATEGORY_CONFLICT)
        self.assertEqual(len(involved), 2)
        widget.deleteLater()

    def test_list_conflict_icons_use_not_equal_strokes(self):
        painter = RecordingPainter()
        LabelGroupListWidget._paint_group_risk_icon(
            painter,
            self._icon_rect(),
            CATEGORY_CONFLICT,
        )
        LabelGroupListWidget._paint_near_duplicate_corner(
            painter,
            self._icon_rect(),
            detect_near_duplicate_clusters(
                (self.first, rectangle("dog"))
            )[0],
        )

        self.assertNotIn("!", [args[-1] for args in painter.texts])
        self.assertEqual(len(painter.lines), 6)

    def test_group_risk_and_total_use_centered_fixed_slots(self):
        dog = rectangle("dog")
        cluster = detect_near_duplicate_clusters((self.first, dog))[0]
        widget = LabelGroupListWidget()
        widget.set_scene((self.first, dog))
        widget.set_near_duplicate_clusters((cluster,))
        status_rect = widget.count_rect_for_label("cat")
        risk_rect = widget._group_risk_rect(status_rect)
        count_rect = widget._group_count_value_rect(status_rect)
        painter = RecordingPainter()

        widget._paint_count(
            painter,
            widget._groups_by_label["cat"],
            status_rect,
            QColor("black"),
        )

        self.assertEqual(widget.count_area_width, 50)
        self.assertEqual(risk_rect.center().y(), status_rect.center().y())
        self.assertEqual(count_rect.center().y(), status_rect.center().y())
        self.assertLess(risk_rect.right(), count_rect.left())
        count_call = next(
            args for args in painter.texts if args[-1] == "×1"
        )
        self.assertTrue(count_call[1] & Qt.AlignVCenter)
        self.assertFalse(count_call[1] & Qt.AlignBottom)

        widget.resize(360, 100)
        widget.show()
        self.app.processEvents()
        status_rect = widget.count_rect_for_label("cat")
        risk_hit = widget._hit_test(
            widget._group_risk_rect(status_rect).center()
        )
        count_hit = widget._hit_test(
            widget._group_count_value_rect(status_rect).center()
        )
        self.assertEqual(risk_hit[0], "near_duplicate_group")
        self.assertEqual(count_hit[0], "count")
        widget.deleteLater()

    @staticmethod
    def _icon_rect():
        return QRectF(0, 0, 14, 14)

    def test_fully_hidden_instance_keeps_its_list_risk_target(self):
        widget = LabelGroupListWidget()
        widget.resize(360, 100)
        widget.set_scene(
            (self.first, self.second),
            visible_shapes=(),
        )
        widget.set_near_duplicate_clusters((self.cluster,))
        requested = QSignalSpy(widget.nearDuplicateRequested)

        QTest.mouseClick(
            widget.viewport(),
            Qt.LeftButton,
            pos=widget._near_duplicate_corner_rect(self.first).center(),
        )

        self.assertEqual(len(requested), 1)
        self.assertIs(requested[0][2], self.first)
        widget.deleteLater()

    def test_chooser_click_and_arrow_immediately_focus_current_member(self):
        chooser = NearDuplicateChooser()
        chooser.show_cluster(
            self.cluster,
            (self.first, self.second),
            preferred_shape=self.first,
        )
        selected = QSignalSpy(chooser.selectionRequested)
        visibility = QSignalSpy(chooser.visibilityRequested)
        edited = QSignalSpy(chooser.editRequested)
        deleted = QSignalSpy(chooser.deleteRequested)
        dismissed = QSignalSpy(chooser.dismissRequested)

        self.assertIs(chooser.current_shape, self.first)
        self.assertEqual(len(selected), 0)
        first_item = chooser.member_list.item(0)
        QTest.mouseClick(
            chooser.member_list.viewport(),
            Qt.LeftButton,
            pos=chooser.member_list.visualItemRect(first_item).center(),
        )
        self.assertEqual(len(selected), 1)
        self.assertIs(selected[0][1], self.first)

        QTest.keyClick(chooser.member_list, Qt.Key_Down)
        self.assertIs(chooser.current_shape, self.second)
        self.assertEqual(len(selected), 2)
        self.assertIs(selected[1][1], self.second)
        QTest.keyClick(chooser.member_list, Qt.Key_Space)
        QTest.keyClick(chooser, Qt.Key_F2)
        QTest.keyClick(chooser, Qt.Key_Delete)
        chooser.dismiss_cluster()

        self.assertEqual(len(visibility), 1)
        self.assertEqual(visibility[0], [self.second, False])
        self.assertEqual(len(edited), 1)
        self.assertIs(edited[0][0], self.second)
        self.assertEqual(len(deleted), 1)
        self.assertIs(deleted[0][0], self.second)
        self.assertEqual(len(dismissed), 1)
        self.assertIs(dismissed[0][0], self.cluster)
        chooser.close()
        chooser.deleteLater()

    def test_chooser_rows_keep_geometry_in_tooltip_only(self):
        chooser = NearDuplicateChooser()
        chooser.show_cluster(self.cluster, (self.first, self.second))
        item = chooser.member_list.item(0)
        row = chooser.member_list.itemWidget(item)

        self.assertFalse(hasattr(row, "geometry_label"))
        self.assertIn("x:20", item.toolTip())
        self.assertIn("w:60", item.toolTip())
        self.assertEqual(row.toolTip(), item.toolTip())

        chooser.close()
        chooser.deleteLater()

    def test_large_chooser_scrolls_and_canvas_count_is_compact(self):
        shapes = tuple(rectangle("cat") for _index in range(120))
        cluster = detect_near_duplicate_clusters(shapes)[0]
        chooser = NearDuplicateChooser()
        chooser.show_cluster(cluster, shapes)
        self.app.processEvents()

        self.assertEqual(chooser.member_list.count(), 120)
        self.assertGreater(
            chooser.member_list.verticalScrollBar().maximum(),
            0,
        )
        canvas = Canvas()
        canvas.shapes = list(shapes)
        canvas.set_near_duplicate_clusters((cluster,))
        self.assertEqual(canvas._near_duplicate_marker_text(cluster), "99+")
        chooser.close()
        chooser.deleteLater()
        canvas.deleteLater()


class NearDuplicateWorkbenchIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        classes_path = os.path.join(self.temporary.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=classes_path,
            save_dir=self.temporary.name,
        ))
        self.assertTrue(self.window.load_file(
            os.path.abspath("tests/test.512.512.bmp")
        ))
        self.window.annotation_clipboard = [
            (
                "cat",
                ((20, 20), (80, 20), (80, 80), (20, 80)),
                None,
                None,
                False,
            ),
            (
                "cat",
                ((20, 20), (80, 20), (80, 80), (20, 80)),
                None,
                None,
                False,
            ),
        ]
        self.window.paste_copied_bounding_boxes()

    def tearDown(self):
        self.window.near_duplicate_chooser.close()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temporary.cleanup()

    def test_dismiss_restore_and_relevant_edit_invalidation(self):
        cluster = self.window._near_duplicate_clusters[0]
        self.window.dismiss_near_duplicate_cluster(cluster)
        self.assertEqual(self.window._near_duplicate_clusters, ())
        self.assertTrue(self.window.restore_near_duplicate_action.isEnabled())
        first = self.window.canvas.shapes[0]
        with mock.patch.object(
            self.window.candidate_label_dialog,
            "choose",
            return_value="dog",
        ):
            self.window.edit_shape_label(first)

        self.assertEqual(
            self.window._near_duplicate_clusters[0].risk,
            CATEGORY_CONFLICT,
        )
        self.assertFalse(self.window.restore_near_duplicate_action.isEnabled())
        self.window.undo_annotation()
        self.assertEqual(
            self.window._near_duplicate_clusters[0].risk,
            "duplicate-label",
        )

    def test_delete_member_is_one_undoable_edit_and_dissolves_cluster(self):
        cluster = self.window._near_duplicate_clusters[0]
        shape = cluster.members[0]

        self.window.delete_near_duplicate_member(shape)

        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertEqual(self.window._near_duplicate_clusters, ())
        self.window.undo_annotation()
        self.assertEqual(len(self.window.canvas.shapes), 2)
        self.assertEqual(len(self.window._near_duplicate_clusters), 1)

    def test_open_chooser_is_non_modal_view_state(self):
        cluster = self.window._near_duplicate_clusters[0]

        self.window.open_near_duplicate_chooser(
            cluster,
            self.window.mapToGlobal(self.window.rect().center()),
        )

        self.assertTrue(self.window.near_duplicate_chooser.isVisible())
        self.assertFalse(self.window.near_duplicate_chooser.isModal())
        self.assertFalse(self.window.annotation_editing.pending)


if __name__ == "__main__":
    unittest.main()
