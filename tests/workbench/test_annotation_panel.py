import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication

from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class AnnotationPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(ENGLISH)
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": self.temporary.name})
        self.environment.start()
        classes = os.path.join(self.temporary.name, "classes.txt")
        with open(classes, "w", encoding="utf-8"):
            pass
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=classes, save_dir=self.temporary.name,
        ))
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(QColor("gray"))
        image_path = os.path.join(self.temporary.name, "sample.png")
        self.assertTrue(image.save(image_path))
        self.assertTrue(self.window.load_file(image_path))
        self.window.auto_saving.setChecked(False)
        self.window.annotation_clipboard = [
            ("P_LSBM", ((x, 10), (x + 10, 10), (x + 10, 20), (x, 20)), False)
            for x in (10, 40)
        ]
        self.window.paste_copied_bounding_boxes()
        self.window.canvas.clear_selection()
        self.window.resize(1180, 760)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()
        set_language(ENGLISH)

    def select(self, count):
        shapes = self.window.canvas.shapes[:count]
        self.window.canvas.set_selected_shapes(shapes, active_shape=shapes[0] if count == 1 else None)
        self.app.processEvents()

    def test_header_contains_global_controls_and_summary(self):
        w = self.window
        self.assertIs(w.dock.titleBarWidget(), w.annotation_header)
        for control in (w.visibility_button, w.label_color_button, w.near_duplicate_more_button):
            self.assertIs(control.parentWidget(), w.annotation_header)
        self.assertEqual(w.label_summary_label.text(), "Classes 1 · Boxes 2")
        self.assertEqual(w.label_summary_label.toolTip(), w.label_list.summary_text())
        self.assertFalse(w.annotation_selection_bar.isVisible())

    def test_dock_content_and_custom_count_receive_the_designed_surface(self):
        w = self.window
        self.assertEqual(w.default_category_caption.font().pixelSize(), 11)
        self.assertEqual(w.default_category_caption.palette().windowText().color(), QColor("#68758A"))
        badge = w.label_summary_label
        rendered = badge.grab().toImage()
        self.assertEqual(rendered.pixelColor(2, badge.height() // 2), QColor("#F1F3F8"))

    def test_context_bar_tracks_selection_without_moving_list_entry(self):
        w = self.window
        list_origin = w.label_list.mapTo(w.dock, QPoint(0, 0))
        self.select(1)
        self.assertTrue(w.annotation_selection_bar.isVisible())
        self.assertTrue(w.edit_button.isVisible())
        self.assertTrue(w.diffc_button.isVisible())
        self.assertEqual(w.annotation_selection_label.text(), "1 selected")
        self.select(2)
        self.assertTrue(w.annotation_selection_bar.isVisible())
        self.assertFalse(w.edit_button.isVisible())
        self.assertFalse(w.diffc_button.isVisible())
        self.assertTrue(w.copy_button.isEnabled())
        self.assertTrue(w.delete_button.isEnabled())
        self.assertEqual(w.annotation_selection_label.text(), "2 selected")
        self.assertEqual(w.label_list.mapTo(w.dock, QPoint(0, 0)), list_origin)
        w.canvas.clear_selection()
        self.assertFalse(w.annotation_selection_bar.isVisible())

    def test_hidden_selected_boxes_remain_counted_and_actionable(self):
        self.select(2)
        self.window.label_filter.setText("no-match")
        self.assertEqual(len(self.window.canvas.selected_shapes), 2)
        self.assertEqual(self.window.annotation_selection_label.text(), "2 selected")
        self.assertIn("2 selected outside filter", self.window.label_summary_label.text())
        self.assertIn("hidden", self.window.label_summary_label.toolTip())
        self.assertTrue(self.window.delete_button.isEnabled())

    def test_difficult_is_single_box_and_undoable(self):
        self.select(1)
        self.window.diffc_button.setChecked(True)
        self.assertTrue(self.window.canvas.shapes[0].difficult)
        self.assertFalse(self.window.canvas.shapes[1].difficult)
        self.window.undo_annotation()
        self.assertFalse(self.window.canvas.shapes[0].difficult)
        self.assertFalse(self.window.diffc_button.isChecked())
        self.select(2)
        self.assertFalse(self.window.diffc_button.isEnabled())

    def test_footer_reuses_existing_edit_duplicate_delete_actions(self):
        self.select(1)
        with patch.object(self.window.candidate_label_dialog, "choose", return_value="new-label"):
            self.window.edit_button.click()
        self.assertEqual(self.window.canvas.shapes[0].label, "new-label")
        self.window.copy_button.click()
        self.assertEqual(len(self.window.canvas.shapes), 3)
        self.window.delete_button.click()
        self.assertEqual(len(self.window.canvas.shapes), 2)
        self.window.undo_annotation()
        self.assertEqual(len(self.window.canvas.shapes), 3)

    def test_header_visibility_applies_to_all_boxes_without_changing_selection(self):
        self.select(1)
        selected = tuple(self.window.canvas.selected_shapes)
        self.window.visibility_button.click()
        self.assertFalse(any(self.window.canvas.isVisible(shape) for shape in self.window.canvas.shapes))
        self.assertEqual(tuple(self.window.canvas.selected_shapes), selected)
        self.window.visibility_button.click()
        self.assertTrue(all(self.window.canvas.isVisible(shape) for shape in self.window.canvas.shapes))

    def test_default_category_is_window_local_and_does_not_register_unused_labels(self):
        selector = self.window.default_category_selector
        before = self.window.annotation_editing.view.snapshot
        selector.set_fixed_label("unused-class")
        self.window.refresh_candidate_labels()
        self.assertEqual(selector.fixed_label, "unused-class")
        self.assertNotIn("unused-class", self.window.candidate_labels)
        self.assertEqual(self.window.annotation_editing.view.snapshot, before)
        selector.activated[int].emit(0)
        self.assertIsNone(selector.fixed_label)

    def test_custom_default_uses_name_chooser_and_cancel_preserves_previous_choice(self):
        selector = self.window.default_category_selector
        with patch.object(self.window.candidate_label_dialog, "choose", return_value="Custom_2") as choose:
            selector.activated[int].emit(selector.count() - 1)
        choose.assert_called_once_with("")
        self.assertEqual(selector.fixed_label, "Custom_2")
        with patch.object(self.window.candidate_label_dialog, "choose", return_value=None):
            selector.activated[int].emit(selector.count() - 1)
        self.assertEqual(selector.fixed_label, "Custom_2")
        self.assertEqual(selector.currentData(), ("fixed", "Custom_2"))

    def test_default_dropdown_drives_new_boxes_and_keeps_single_class_precedence(self):
        selector = self.window.default_category_selector
        self.window.single_class_mode.setChecked(True)
        self.window.lastLabel = "single-class-last"

        def draw(x):
            self.window.create_shape()
            self.window.canvas.handle_drawing(QPointF(x, 60))
            self.window.canvas.line[1] = QPointF(x + 10, 70)
            self.window.canvas.handle_drawing(QPointF(x + 10, 70))

        with patch.object(self.window.candidate_label_dialog, "choose") as choose:
            selector.activated[int].emit(1)
            draw(10)
            self.assertEqual(self.window.canvas.shapes[-1].label, "P_LSBM")
            selector.activated[int].emit(0)
            draw(30)
            self.assertEqual(self.window.canvas.shapes[-1].label, "single-class-last")
            choose.assert_not_called()
        self.window.single_class_mode.setChecked(False)
        with patch.object(self.window.candidate_label_dialog, "choose", return_value="chosen") as choose:
            draw(50)
            choose.assert_called_once()
            self.assertEqual(self.window.canvas.shapes[-1].label, "chosen")

    def test_default_and_context_retranslate_without_changing_user_label(self):
        self.window.default_category_selector.set_fixed_label("Custom_2")
        self.select(1)
        self.window.change_language(SIMPLIFIED_CHINESE)
        self.assertEqual(self.window.default_category_caption.text(), "默认类别")
        self.assertEqual(self.window.default_category_selector.currentText(), "固定：Custom_2")
        self.assertEqual(self.window.edit_button.text(), "改类别")
        self.assertEqual(self.window.annotation_selection_label.text(), "已选 1 个")
        self.assertEqual(self.window.label_summary_label.text(), "1 类 · 2 个")
        self.window.change_language(ENGLISH)
        self.assertEqual(self.window.default_category_selector.fixed_label, "Custom_2")

    def test_reset_clears_selection_bar_but_retains_default_category(self):
        self.window.default_category_selector.set_fixed_label("P_LSBM")
        self.select(1)
        self.window.reset_state()
        self.assertFalse(self.window.annotation_selection_bar.isVisible())
        self.assertEqual(self.window.default_category_selector.fixed_label, "P_LSBM")


if __name__ == "__main__":
    unittest.main()
