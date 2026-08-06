import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PIL import Image
from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog

from labelimg.image_tools.dialog import (
    ImageToolsDialog,
    _PreviewBadgeSpec,
    _array_pixmap,
    _layout_preview_badges,
)


class ImageToolsDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.commits = []
        self.current = self.save("current.png", red=True, yellow=True)
        self.second = self.save("second.png", red=True)

    def tearDown(self):
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, ImageToolsDialog):
                widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temporary.cleanup()

    def save(self, name, *, red=False, yellow=False):
        image = np.full((180, 240, 3), 120, dtype=np.uint8)
        if red:
            cv2.rectangle(image, (20, 25), (95, 145), (0, 0, 255), 7)
        if yellow:
            cv2.rectangle(image, (140, 30), (220, 150), (0, 255, 255), 7)
        path = os.path.join(self.temporary.name, name)
        Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)).save(path)
        return path

    def dialog(self, selected_paths=()):
        def commit(replacements):
            self.commits.append(replacements)
            return "committed"

        return ImageToolsDialog(
            self.current,
            selected_paths,
            commit=commit,
            asynchronous=False,
        )

    def show_dialog(self, dialog):
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_defaults_to_current_image_and_requires_explicit_batch_scope(self):
        dialog = self.dialog((self.current, self.second))

        self.assertEqual(dialog.scope_combo.currentData(), "current")
        self.assertEqual(dialog.target_paths, (self.current,))

        selected_index = dialog.scope_combo.findData("selected")
        dialog.scope_combo.setCurrentIndex(selected_index)

        self.assertEqual(dialog.target_paths, (self.current, self.second))
        self.assertEqual(dialog.target_list.topLevelItemCount(), 2)

    def test_candidate_exclusion_is_undoable_and_redoable(self):
        dialog = self.dialog()
        self.assertEqual(dialog.candidate_list.topLevelItemCount(), 2)
        first = dialog.candidate_list.topLevelItem(0)

        first.setCheckState(0, Qt.Unchecked)
        selected_after_exclusion = set(
            dialog._states[self.current].result.selected_candidate_ids
        )
        self.assertEqual(len(selected_after_exclusion), 1)
        self.assertTrue(dialog.undo_action.isEnabled())

        dialog.undo()
        self.assertEqual(
            len(dialog._states[self.current].result.selected_candidate_ids),
            2,
        )
        dialog.redo()
        self.assertEqual(
            set(dialog._states[self.current].result.selected_candidate_ids),
            selected_after_exclusion,
        )

    def test_apply_passes_only_ready_included_replacements_and_accepts(self):
        dialog = self.dialog((self.current, self.second))
        dialog.scope_combo.setCurrentIndex(
            dialog.scope_combo.findData("selected")
        )
        second_item = dialog.target_list.topLevelItem(1)
        second_item.setCheckState(0, Qt.Unchecked)

        self.assertTrue(
            dialog.apply_button.isEnabled(),
            repr({
                path: (state.status, state.included, state.result is not None)
                for path, state in dialog._states.items()
            }),
        )
        dialog.apply_button.click()

        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.outcome, "committed")
        self.assertEqual(len(self.commits), 1)
        self.assertEqual(len(self.commits[0]), 1)
        self.assertEqual(self.commits[0][0].path, self.current)

    def test_no_frame_image_is_excluded_and_never_committed(self):
        plain = self.save("plain.jpg")
        dialog = ImageToolsDialog(
            plain,
            commit=lambda replacements: self.commits.append(replacements),
            asynchronous=False,
        )

        state = dialog._states[plain]
        self.assertFalse(state.included)
        self.assertIsNone(state.result.replacement)
        self.assertFalse(dialog.apply_button.isEnabled())

    def test_preview_base_pixels_never_contain_candidate_ui(self):
        dialog = self.dialog()
        state = dialog._states[self.current]
        for mode, pixels in (
            ("original", state.result.original_pixels),
            ("result", state.result.result_pixels),
        ):
            with self.subTest(mode=mode):
                dialog.preview_mode.setCurrentIndex(
                    dialog.preview_mode.findData(mode)
                )
                preview = dialog._preview_source[0].toImage().convertToFormat(
                    QImage.Format_RGBA8888
                )
                expected = _array_pixmap(
                    pixels
                ).toImage().convertToFormat(QImage.Format_RGBA8888)
                self.assertEqual(preview, expected)

    def test_badges_appear_only_on_original_and_result_at_fixed_size(self):
        dialog = self.show_dialog(self.dialog())
        for mode in ("original", "result"):
            with self.subTest(mode=mode):
                dialog.preview_mode.setCurrentIndex(
                    dialog.preview_mode.findData(mode)
                )
                self.app.processEvents()
                rects = dialog.preview_label.badge_rects
                self.assertEqual(len(rects), 2)
                self.assertTrue(all(
                    rect.width() == 22 and rect.height() == 22
                    for rect in rects.values()
                ))

        dialog.preview_mode.setCurrentIndex(
            dialog.preview_mode.findData("mask")
        )
        self.app.processEvents()
        self.assertEqual(dialog.preview_label.badge_rects, {})

        dialog.preview_mode.setCurrentIndex(
            dialog.preview_mode.findData("result")
        )
        dialog.resize(920, 620)
        self.app.processEvents()
        self.assertTrue(all(
            rect.width() == 22 and rect.height() == 22
            for rect in dialog.preview_label.badge_rects.values()
        ))

    def test_included_badge_is_a_ring_not_a_solid_circle(self):
        dialog = self.show_dialog(self.dialog())
        badge = next(iter(dialog.preview_label.badge_rects.values()))
        preview = dialog.preview_label.grab().toImage()
        ring_pixel = preview.pixelColor(badge.center().x(), badge.top() + 1)
        interior_pixel = preview.pixelColor(
            badge.left() + 5,
            badge.center().y(),
        )

        self.assertNotEqual(ring_pixel, interior_pixel)

    def test_only_badge_click_toggles_candidate_and_updates_tooltip(self):
        dialog = self.show_dialog(self.dialog())
        state = dialog._states[self.current]
        candidate = state.result.candidates[0]
        selected_before = tuple(state.result.selected_candidate_ids)
        display = dialog.preview_label.display_rect
        image_height, image_width = state.result.original_pixels.shape[:2]
        rectangle_center = QPoint(
            round(
                display.left()
                + (candidate.x + candidate.width / 2)
                * display.width()
                / image_width
            ),
            round(
                display.top()
                + (candidate.y + candidate.height / 2)
                * display.height()
                / image_height
            ),
        )
        badge = dialog.preview_label.badge_rects[candidate.candidate_id]
        self.assertFalse(badge.contains(rectangle_center))

        QTest.mouseClick(
            dialog.preview_label,
            Qt.LeftButton,
            pos=rectangle_center,
        )
        self.app.processEvents()
        self.assertEqual(
            tuple(state.result.selected_candidate_ids),
            selected_before,
        )

        QTest.mouseMove(dialog.preview_label, badge.center())
        self.app.processEvents()
        self.assertEqual(
            dialog.preview_label.cursor().shape(),
            Qt.PointingHandCursor,
        )
        self.assertIn("Candidate 1", dialog.preview_label.toolTip())
        self.assertIn("click to exclude", dialog.preview_label.toolTip())
        self.assertEqual(
            tuple(state.result.selected_candidate_ids),
            selected_before,
        )

        QTest.mouseClick(
            dialog.preview_label,
            Qt.LeftButton,
            pos=badge.center(),
        )
        self.app.processEvents()
        self.assertNotIn(
            candidate.candidate_id,
            state.result.selected_candidate_ids,
        )
        specs = dialog.preview_label._badge_specs
        self.assertEqual(specs[0].number, 1)
        self.assertFalse(specs[0].included)

    def test_badge_layout_clamps_edges_and_avoids_collisions(self):
        specs = tuple(
            _PreviewBadgeSpec(
                candidate_id="candidate-%d" % number,
                number=number,
                x=239,
                y=179,
                included=True,
                tooltip="",
            )
            for number in range(1, 5)
        )
        display = QRect(10, 20, 300, 225)

        first = _layout_preview_badges(specs, (240, 180), display)
        second = _layout_preview_badges(specs, (240, 180), display)

        self.assertEqual(first, second)
        self.assertEqual(len(first), len(specs))
        for rect in first.values():
            self.assertEqual(rect.size().width(), 22)
            self.assertEqual(rect.size().height(), 22)
            self.assertTrue(display.contains(rect))
        rects = list(first.values())
        self.assertTrue(all(
            not rects[left].intersects(rects[right])
            for left in range(len(rects))
            for right in range(left + 1, len(rects))
        ))


if __name__ == "__main__":
    unittest.main()
