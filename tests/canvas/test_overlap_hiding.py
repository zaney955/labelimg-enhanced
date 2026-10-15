"""Partial annotation clipping must preserve outside pixels and explicit visibility."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QImage, QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication

from labelimg.canvas.shape import Shape
from labelimg.canvas.widget import Canvas


class OverlapHidingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # Windows offscreen Qt may discover no system fonts in a restricted host.
        # Load a real font so glyph clipping assertions exercise painted text.
        if not QFontDatabase().families() and os.name == "nt":
            fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            QFontDatabase.addApplicationFont(str(fonts / "arial.ttf"))
            QFontDatabase.addApplicationFont(str(fonts / "arialbd.ttf"))
            cls.app.setFont(QFont("Arial"))

    def setUp(self):
        self.canvas = Canvas()
        self.canvas.resize(200, 160)
        self.background = QColor("#505050")
        pixmap = QPixmap(200, 160)
        pixmap.fill(self.background)
        self.canvas.load_pixmap(pixmap)
        self.shape = self.box("existing annotation", (40, 40, 100, 100))
        self.canvas.load_shapes([self.shape])
        self.canvas.set_mode(Canvas.CREATE)
        self.canvas.grab()

    def tearDown(self):
        self.canvas.restore_cursor()
        self.canvas.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    @staticmethod
    def box(label, rect):
        shape = Shape(label=label, paint_label=True)
        left, top, right, bottom = rect
        for x, y in ((left, top), (right, top), (right, bottom), (left, bottom)):
            shape.add_point(QPointF(x, y))
        shape.close()
        return shape

    def start_box(self, start=(20, 20), end=(80, 80)):
        self.canvas.cancel_current_drawing()
        self.canvas.handle_drawing(QPointF(*start))
        self.canvas.line[1] = QPointF(*end)

    def capture(self):
        # Observe the annotation layer separately from the reverse-screen preview.
        self.canvas.prev_point = QPointF()
        with patch("labelimg.canvas.widget.paint_pending_box"):
            return self.canvas.grab().toImage().convertToFormat(QImage.Format_RGB32)

    def color(self, image, x, y):
        point = self.canvas.image_to_widget(QPointF(x, y)).toPoint()
        return image.pixelColor(point)

    def assert_frame_clipped(self):
        image = self.capture()
        self.assertEqual(self.color(image, 60, 40), self.background)
        self.assertNotEqual(self.color(image, 90, 40), self.background)
        self.assertNotEqual(self.color(image, 40, 90), self.background)

    def mouse(self, event, point, button=Qt.NoButton, buttons=Qt.NoButton,
              modifiers=Qt.NoModifier):
        QApplication.sendEvent(self.canvas, QMouseEvent(
            event, self.canvas.image_to_widget(QPointF(*point)),
            button, buttons, modifiers,
        ))

    def begin_drag(self, start=(135, 85), end=(85, 85)):
        active = self.box("active", (115, 60, 155, 115))
        active.line_color = QColor("#ff8000")
        self.canvas.load_shapes([self.shape, active])
        self.canvas.set_mode(Canvas.EDIT)
        self.mouse(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        self.mouse(QEvent.MouseMove, end, buttons=Qt.LeftButton)
        return active

    def test_partial_intersection_keeps_uncovered_frame_and_label_pixels(self):
        self.start_box()
        baseline = self.capture()
        self.canvas.set_auto_hide_overlapping(True)
        self.assert_frame_clipped()
        image = self.capture()
        # The right half of the label also survives this partial cutout.
        label = self.shape.label_text_rect()
        remaining_ink = 0
        for x in range(82, int(label.right())):
            for y in range(int(label.top()), int(label.bottom()) + 1):
                self.assertEqual(image.pixelColor(x, y), baseline.pixelColor(x, y))
                remaining_ink += baseline.pixelColor(x, y) != self.background
        self.assertGreater(remaining_ink, 0)

    def test_label_only_intersection_clips_only_covered_glyph_pixels(self):
        label = self.shape.label_text_rect()
        split = int(label.center().x())
        self.start_box((label.left() - 2, label.top() - 2),
                       (split, label.bottom() + 2))
        self.assertLess(self.canvas.line[1].y(), self.shape.bounding_rect().top())
        baseline = self.capture()
        self.canvas.set_auto_hide_overlapping(True)
        clipped = self.capture()
        counts = [0, 0]
        for x in range(int(label.left()), int(label.right()) + 1):
            for y in range(int(label.top()), int(label.bottom()) + 1):
                if baseline.pixelColor(x, y) != self.background:
                    side = int(x >= split)
                    counts[side] += 1
                    expected = baseline.pixelColor(x, y) if side else self.background
                    self.assertEqual(clipped.pixelColor(x, y), expected)
        self.assertTrue(all(counts))
        self.assertNotEqual(self.color(clipped, 60, 40), self.background)

    def test_contained_pending_box_does_not_hide_an_enclosing_outline(self):
        self.start_box((50, 50), (60, 60))
        baseline = self.capture()
        self.canvas.set_auto_hide_overlapping(True)
        self.assertEqual(self.capture(), baseline)

    def test_complete_coverage_hides_outline_and_label(self):
        self.start_box((10, 10), (190, 130))
        self.canvas.set_auto_hide_overlapping(True)
        image = self.capture()
        for x, y in ((40, 40), (100, 100), (60, 40)):
            self.assertEqual(self.color(image, x, y), self.background)
        self.assertTrue(self.canvas._is_overlap_hidden(self.shape))

    def test_reverse_and_fractional_boxes_use_normalized_clip_geometry(self):
        self.canvas.set_auto_hide_overlapping(True)
        for start, end in (((80, 80), (20, 20)), ((20.25, 20.5), (80.25, 80.5))):
            with self.subTest(start=start):
                self.start_box(start, end)
                self.assert_frame_clipped()

    def test_pointer_first_corner_and_zero_area_do_not_hide_boxes(self):
        self.canvas.set_auto_hide_overlapping(True)
        baseline = self.capture()
        for point in ((60, 60), (40, 40), (60, 30)):
            self.mouse(QEvent.MouseMove, point)
            self.assertEqual(self.capture(), baseline)
        self.canvas.handle_drawing(QPointF(50, 50))
        self.assertEqual(self.capture(), baseline)
        self.canvas.line[1] = QPointF(80, 50)
        self.assertEqual(self.capture(), baseline)

    def test_cache_and_fallback_match_with_labels_zoom_and_fractional_bounds(self):
        self.canvas.set_auto_hide_overlapping(True)
        for scale in (0.5, 1.0, 2.0):
            self.canvas.scale = scale
            self.canvas.set_view_offset(QPointF(3.25, 5.5))
            for start, end in (((20.25, 20.5), (80.5, 80.25)),
                               ((100, 20), (30, 35)), ((10, 5), (20, 10))):
                with self.subTest(scale=scale, start=start, end=end):
                    self.start_box(start, end)
                    cached = self.capture()
                    with patch.object(self.canvas._drawing_scene_cache, "paint",
                                      return_value=False):
                        direct = self.capture()
                    a = cached.bits().asstring(cached.byteCount())
                    b = direct.bits().asstring(direct.byteCount())
                    self.assertLessEqual(max(abs(x - y) for x, y in zip(a, b)), 1)

    def test_moving_cutout_does_not_rerasterize_static_annotations(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.start_box()
        self.capture()
        with patch.object(self.shape, "paint", wraps=self.shape.paint) as paint:
            for point in ((90, 80), (130, 130), (30, 30), (80, 80)):
                self.canvas.line[1] = QPointF(*point)
                self.capture()
        self.assertEqual(paint.call_count, 0)
        self.assert_frame_clipped()

    def test_option_off_and_endpoint_movement_restore_pixels(self):
        self.start_box()
        baseline = self.capture()
        self.canvas.set_auto_hide_overlapping(True)
        self.assert_frame_clipped()
        # Avoid covering label pixels for the disjoint endpoint.
        self.canvas.line[0] = QPointF(10, 5)
        self.canvas.line[1] = QPointF(20, 10)
        self.assertEqual(self.capture(), baseline)
        self.canvas.set_auto_hide_overlapping(False)
        self.assertEqual(self.capture(), baseline)

    def test_explicit_visibility_and_geometry_are_unchanged(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.start_box()
        points = list(self.shape.points)
        self.assert_frame_clipped()
        self.assertEqual(self.canvas.visible, {})
        self.assertTrue(self.canvas.isVisible(self.shape))
        self.canvas.set_shape_visible(self.shape, False)
        self.canvas.cancel_current_drawing()
        self.assertEqual(self.color(self.capture(), 60, 40), self.background)
        self.assertFalse(self.canvas.isVisible(self.shape))
        self.assertEqual(self.shape.points, points)

    def test_cancellation_modes_and_scene_replacement_restore_pixels(self):
        baseline = self.capture()
        self.canvas.set_auto_hide_overlapping(True)
        for cleanup in (self.canvas.cancel_current_drawing,
                        lambda: self.canvas.set_mode(Canvas.EDIT),
                        lambda: self.canvas.set_mode(Canvas.PAN),
                        lambda: self.canvas.load_shapes([self.shape])):
            self.canvas.set_mode(Canvas.CREATE)
            self.start_box()
            self.assert_frame_clipped()
            cleanup()
            self.assertEqual(self.capture(), baseline)
            self.assertTrue(self.canvas.auto_hide_overlapping)

    def test_label_confirmation_keeps_partial_clip_until_creation_ends(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.start_box()
        observed = []

        def choose_label():
            self.assertIsNone(self.canvas.current)
            self.assert_frame_clipped()
            observed.append(True)
            self.canvas.set_last_label("new")

        self.canvas.newShape.connect(choose_label)
        self.canvas.handle_drawing(QPointF(80, 80))
        self.assertEqual(observed, [True])
        self.assertIsNone(self.canvas._pending_overlap_rectangle())
        self.assertNotEqual(self.color(self.capture(), 60, 40), self.background)

    def test_square_constraint_uses_actual_preview(self):
        self.canvas.set_auto_hide_overlapping(True)
        self.canvas.set_drawing_shape_to_square(True)
        self.canvas.handle_drawing(QPointF(20, 20))
        self.mouse(QEvent.MouseMove, (180, 30))
        self.assertEqual(self.canvas.line[1], QPointF(30, 30))
        self.assertEqual(self.canvas._pending_overlap_rectangle(), QRectF(20, 20, 10, 10))
        self.assertNotEqual(self.color(self.capture(), 60, 40), self.background)

    def test_drag_clips_other_frame_and_restores_it_on_release(self):
        self.canvas.set_auto_hide_overlapping(True)
        active = self.begin_drag()
        self.assertEqual(active.bounding_rect(), QRectF(65, 60, 40, 55))
        with patch.object(active, "paint"):
            image = self.capture()
            self.assertEqual(self.color(image, 100, 80), self.background)
            self.assertNotEqual(self.color(image, 40, 80), self.background)
            self.canvas.set_auto_hide_overlapping(False)
            self.assertNotEqual(self.color(self.capture(), 100, 80), self.background)
            self.canvas.set_auto_hide_overlapping(True)
            self.mouse(QEvent.MouseButtonRelease, (85, 85), Qt.LeftButton)
            self.assertIsNone(self.canvas._pending_overlap_rectangle())
            self.assertNotEqual(self.color(self.capture(), 100, 80), self.background)

    def test_dragged_box_and_its_label_remain_visible(self):
        self.canvas.set_auto_hide_overlapping(True)
        active = self.begin_drag()
        image = self.capture()
        self.assertNotEqual(self.color(image, 65, 90), self.background)
        label = active.label_text_rect().toAlignedRect()
        self.assertTrue(any(image.pixelColor(x, y) != self.background
                            for x in range(label.left(), label.right())
                            for y in range(label.top(), label.bottom())))

    def test_drag_hides_other_outline_over_active_label_outside_active_box(self):
        active = self.begin_drag()
        label = active.label_hit_rect()
        line_y = int(label.center().y())
        self.assertLess(line_y, active.bounding_rect().top())
        self.shape.points = [QPointF(x, y) for x, y in (
            (20, line_y), (180, line_y), (180, 140), (20, 140),
        )]
        self.shape.paint_label = False
        with patch.object(active, "paint"):
            baseline = self.capture()
            sample_x = int(label.center().x())
            self.assertNotEqual(self.color(baseline, sample_x, line_y), self.background)
            self.canvas.set_auto_hide_overlapping(True)
            clipped = self.capture()
            self.assertEqual(self.color(clipped, sample_x, line_y), self.background)
            self.assertNotEqual(self.color(clipped, 40, line_y), self.background)

    def test_drag_hides_other_text_over_active_label_until_selection_and_hover_end(self):
        active = self.begin_drag()
        self.shape.points = [QPointF(x, y) for x, y in (
            (40, 60), (180, 60), (180, 140), (40, 140),
        )]
        label = active.label_hit_rect().toAlignedRect()
        with patch.object(active, "paint"):
            baseline = self.capture()
            ink = [(x, y) for x in range(label.left() + 1, label.right())
                   for y in range(label.top() + 1, label.bottom())
                   if baseline.pixelColor(x, y) != self.background]
            self.assertTrue(ink)
            self.canvas.set_auto_hide_overlapping(True)
            clipped = self.capture()
            self.assertTrue(all(clipped.pixelColor(x, y) == self.background
                                for x, y in ink))
            self.mouse(QEvent.MouseButtonRelease, (85, 85), Qt.LeftButton)
            self.assertEqual(self.capture(), clipped)
            self.canvas.clear_selection()
            self.canvas.set_hover_target(None)
            restored = self.capture()
            self.assertTrue(all(restored.pixelColor(x, y) == baseline.pixelColor(x, y)
                                for x, y in ink))

    def test_active_label_mask_tracks_zoom_font_and_corner_resize(self):
        self.canvas.set_auto_hide_overlapping(True)
        for scale, font_size, start, end in (
            (0.5, 8, (135, 85), (85, 85)),
            (1.0, 12, (115, 85), (80, 85)),
            (2.0, 12, (115, 60), (80, 50)),
        ):
            with self.subTest(scale=scale, font_size=font_size, start=start):
                self.canvas.scale = 1.0
                active = self.begin_drag(start, end)
                active.label = "active annotation with a long label"
                self.canvas.scale = scale
                self.canvas.label_font_size = font_size
                label = active.label_hit_rect(scale=scale, font_size=font_size)
                line_y = int(label.center().y())
                self.shape.paint_label = False
                self.shape.points = [QPointF(x, y) for x, y in (
                    (20, line_y), (180, line_y), (180, 140), (20, 140),
                )]
                with patch.object(active, "paint"):
                    clipped = self.capture()
                    self.assertEqual(self.color(clipped, label.left() + 4, line_y),
                                     self.background)
                    self.assertNotEqual(self.color(clipped, 40, line_y), self.background)
                self.mouse(QEvent.MouseButtonRelease, end, Qt.LeftButton)

    def test_undisplayed_active_label_does_not_mask_other_annotations(self):
        active = self.begin_drag()
        line_y = int(active.label_hit_rect().center().y())
        self.shape.points = [QPointF(x, y) for x, y in (
            (20, line_y), (180, line_y), (180, 140), (20, 140),
        )]
        active.paint_label = False
        self.shape.paint_label = False
        self.canvas.set_auto_hide_overlapping(True)
        with patch.object(active, "paint"):
            self.assertNotEqual(self.color(self.capture(), 80, line_y), self.background)

    def test_other_selected_boxes_remain_protected_including_fill(self):
        self.canvas.set_auto_hide_overlapping(True)
        active = self.begin_drag()
        self.canvas.set_selected_shapes([self.shape, active], active_shape=active)
        with patch.object(active, "paint"):
            image = self.capture()
            self.assertNotEqual(self.color(image, 80, 80), self.background)
            self.assertNotEqual(self.color(image, 50, 80), self.background)
            self.assertNotEqual(self.color(image, 100, 80), self.background)

    def test_resize_edges_and_corners_also_clip_other_annotations(self):
        self.canvas.set_auto_hide_overlapping(True)
        for start, end in (((115, 85), (80, 85)), ((115, 60), (80, 50))):
            with self.subTest(start=start):
                active = self.begin_drag(start, end)
                with patch.object(active, "paint"):
                    image = self.capture()
                    self.assertEqual(self.color(image, 100, 80), self.background)
                    self.assertNotEqual(self.color(image, 40, 80), self.background)
                self.mouse(QEvent.MouseButtonRelease, end, Qt.LeftButton)
                self.assertIsNone(self.canvas._pending_overlap_rectangle())

    def test_drag_can_clip_only_label_text_outside_its_box(self):
        self.canvas.set_auto_hide_overlapping(True)
        active = self.box("active", (115, 3, 155, 35))
        self.canvas.load_shapes([self.shape, active])
        self.canvas.set_mode(Canvas.EDIT)
        self.mouse(QEvent.MouseButtonPress, (135, 19), Qt.LeftButton, Qt.LeftButton)
        self.mouse(QEvent.MouseMove, (65, 19), buttons=Qt.LeftButton)
        with patch.object(active, "paint"):
            clipped = self.capture()
            self.assertNotEqual(self.color(clipped, 60, 40), self.background)
            self.canvas.set_auto_hide_overlapping(False)
            baseline = self.capture()
            label = self.shape.label_text_rect().toAlignedRect()
            covered_ink = [(x, y) for x in range(46, 84)
                           for y in range(label.top(), label.bottom())
                           if baseline.pixelColor(x, y) != self.background]
            self.assertTrue(covered_ink)
            self.assertTrue(all(clipped.pixelColor(x, y) == self.background
                                for x, y in covered_ink))

    def prepare_protection_target(self):
        target = self.box("target", (65, 60, 105, 115))
        target.line_color = QColor("#ff8000")
        # Put the target below its peer to also exercise rendering order.
        self.canvas.load_shapes([target, self.shape])
        self.canvas.set_mode(Canvas.EDIT)
        return target

    def test_canvas_hover_protects_box_and_releases_on_pointer_leave(self):
        target = self.prepare_protection_target()
        self.canvas.set_auto_hide_overlapping(True)
        self.mouse(QEvent.MouseMove, (85, 110))
        self.assertIs(self.canvas.hover_shape_for_paint, target)
        with patch.object(target, "paint"):
            image = self.capture()
            self.assertEqual(self.color(image, 100, 80), self.background)
            self.assertNotEqual(self.color(image, 40, 80), self.background)
            QApplication.sendEvent(self.canvas, QEvent(QEvent.Leave))
            self.assertNotEqual(self.color(self.capture(), 100, 80), self.background)
        self.assertEqual(self.canvas.selected_shapes, [])
        self.assertEqual(self.canvas.visible, {})

    def test_hover_and_selection_protect_own_label_from_other_outlines_and_text(self):
        for state in ("hover", "selected"):
            for peer_part in ("outline", "text"):
                with self.subTest(state=state, peer_part=peer_part):
                    target = self.prepare_protection_target()
                    if state == "hover":
                        self.canvas.set_hover_target(target)
                    else:
                        self.canvas.set_selected_shapes([target])
                    label = target.label_text_rect()
                    line_y = int(label.center().y())
                    top = line_y if peer_part == "outline" else 60
                    self.shape.points = [QPointF(x, y) for x, y in (
                        (20, top), (180, top), (180, 140), (20, 140),
                    )]
                    self.shape.paint_label = peer_part == "text"
                    self.canvas.set_auto_hide_overlapping(False)
                    with patch.object(target, "paint"):
                        baseline = self.capture()
                        inside = [(x, y) for x in range(int(label.left()) + 1, int(label.right()))
                                  for y in range(int(label.top()) + 1, int(label.bottom()))
                                  if baseline.pixelColor(x, y) != self.background]
                        self.assertTrue(inside)
                        self.canvas.set_auto_hide_overlapping(True)
                        clipped = self.capture()
                        self.assertTrue(all(clipped.pixelColor(x, y) == self.background
                                            for x, y in inside))
                    self.canvas.clear_selection()
                    self.canvas.set_hover_target(None)

    def test_selection_protection_persists_off_pointer_and_ends_on_deselect(self):
        target = self.prepare_protection_target()
        self.canvas.set_selected_shapes([target])
        self.mouse(QEvent.MouseMove, (190, 150))
        self.canvas.set_auto_hide_overlapping(True)
        with patch.object(target, "paint"):
            self.assertEqual(self.color(self.capture(), 100, 80), self.background)
            self.canvas.clear_selection()
            self.assertNotEqual(self.color(self.capture(), 100, 80), self.background)

    def test_group_list_hover_protects_all_visible_members(self):
        target = self.prepare_protection_target()
        second = self.box("target", (10, 80, 50, 130))
        self.canvas.load_shapes([target, second, self.shape])
        self.canvas.set_external_hover_shapes([target, second])
        self.canvas.set_auto_hide_overlapping(True)
        with patch.object(target, "paint"), patch.object(second, "paint"):
            image = self.capture()
            self.assertEqual(self.color(image, 100, 80), self.background)
            self.assertEqual(self.color(image, 40, 90), self.background)
            self.assertNotEqual(self.color(image, 60, 40), self.background)
            self.canvas.set_shape_visible(second, False)
            self.assertNotEqual(self.color(self.capture(), 40, 90), self.background)
            self.canvas.set_external_hover_shapes([])
            self.assertNotEqual(self.color(self.capture(), 100, 80), self.background)

    def test_hover_and_selection_are_protected_together_and_remain_unclipped(self):
        target = self.prepare_protection_target()
        self.canvas.set_selected_shapes([self.shape])
        self.canvas.set_hover_target(target)
        self.canvas.set_auto_hide_overlapping(True)
        with patch.object(target, "paint"):
            image = self.capture()
            self.assertNotEqual(self.color(image, 100, 80), self.background)
            self.assertFalse(self.canvas._is_overlap_hidden(target))
            self.assertFalse(self.canvas._is_overlap_hidden(self.shape))
        self.canvas.set_shape_visible(self.shape, False)
        self.assertEqual(self.canvas._overlap_protected_shapes(), (target,))

    def test_protected_hover_is_complete_and_above_clipped_background(self):
        target = self.prepare_protection_target()
        self.canvas.set_hover_target(target)
        self.canvas.set_auto_hide_overlapping(True)
        image = self.capture()
        self.canvas.set_shape_visible(self.shape, False)
        reference = self.capture()
        label = target.label_text_rect().toAlignedRect()
        self.assertTrue(any(reference.pixelColor(x, y) != self.background
                            for x in range(label.left(), label.right())
                            for y in range(label.top(), label.bottom())))
        for x in range(label.left(), label.right()):
            for y in range(label.top(), label.bottom()):
                self.assertEqual(image.pixelColor(x, y), reference.pixelColor(x, y))
        for x in range(67, 103):
            for y in range(62, 113):
                self.assertEqual(image.pixelColor(x, y), reference.pixelColor(x, y))

    def test_selected_targets_in_draw_mode_are_kept_outside_the_clipped_cache(self):
        target = self.prepare_protection_target()
        self.canvas.set_mode(Canvas.CREATE)
        self.canvas.set_selected_shapes([target])
        self.canvas.set_auto_hide_overlapping(True)
        with patch.object(target, "paint"):
            image = self.capture()
            self.assertEqual(self.color(image, 100, 80), self.background)
            self.canvas.clear_selection()
            self.assertNotEqual(self.color(self.capture(), 100, 80), self.background)

    def test_hover_target_stays_reachable_after_temporary_clipping(self):
        target = self.box("inner", (60, 60, 90, 90))
        self.canvas.load_shapes([target, self.shape])
        self.canvas.set_mode(Canvas.EDIT)
        self.canvas.set_auto_hide_overlapping(True)
        for _ in range(3):
            self.mouse(QEvent.MouseMove, (75, 75))
            self.assertIs(self.canvas.hover_shape_for_paint, target)
            self.capture()
        self.mouse(QEvent.MouseMove, (95, 95))
        self.assertIs(self.canvas.hover_shape_for_paint, self.shape)
        self.capture()
        self.mouse(QEvent.MouseMove, (75, 75))
        self.assertIs(self.canvas.hover_shape_for_paint, target)

    def test_hover_protection_follows_actual_label_visibility(self):
        target = self.prepare_protection_target()
        label = target.label_text_rect()
        line_y = int(label.center().y())
        self.shape.paint_label = False
        self.shape.points = [QPointF(x, y) for x, y in (
            (20, line_y), (180, line_y), (180, 140), (20, 140),
        )]
        self.canvas.set_hover_target(target)
        self.canvas.set_auto_hide_overlapping(True)
        with patch.object(target, "paint"):
            target.paint_label = False
            self.assertNotEqual(self.color(self.capture(), label.center().x(), line_y),
                                self.background)
            target.paint_label = True
            self.assertEqual(self.color(self.capture(), label.center().x(), line_y),
                             self.background)

    def test_cancel_mode_and_scene_changes_clear_drag_tracking(self):
        self.canvas.set_auto_hide_overlapping(True)
        for cleanup in (self.canvas.cancel_annotation_gesture,
                        lambda: self.canvas.set_mode(Canvas.PAN),
                        lambda: self.canvas.load_shapes([self.shape])):
            self.begin_drag()
            self.assertIsNotNone(self.canvas._overlap_drag_shape)
            cleanup()
            self.assertIsNone(self.canvas._overlap_drag_shape)


if __name__ == "__main__":
    unittest.main()
