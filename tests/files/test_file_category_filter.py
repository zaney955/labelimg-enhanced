"""Category filtering through projections, real controls and the workbench."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QElapsedTimer, QEvent, QPoint, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from labelimg.annotations.domain.model import AnnotationFormat
from labelimg.annotations.infrastructure.document import AnnotationBox, AnnotationDocument
from labelimg.files.model import FileListItemState, FileListProjection, FileListQuery
from labelimg.files.ui.list_widget import FileListControlBar
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class CategoryProjectionTest(unittest.TestCase):
    def test_all_any_exact_labels_and_conjunction_share_navigation(self):
        root = os.path.abspath("workspace")
        paths = [os.path.join(root, str(index) + ".png") for index in range(5)]
        items = tuple(FileListItemState(path, labels=labels, review_state=review)
                      for path, labels, review in zip(paths, (
                          {"Crack"}, {"Crack", "缺损", "extra"}, {"缺损"}, set(), {"crack"},
                      ), ("verified", "verified", "unreviewed", "unreviewed", "verified")))
        all_of = FileListProjection.create(root, items, FileListQuery(categories={"Crack", "缺损"}))
        self.assertEqual(all_of.visible_paths, (paths[1],))
        any_of = FileListProjection.create(root, items, FileListQuery(
            categories={"Crack", "缺损"}, category_match="any"))
        self.assertEqual(any_of.visible_paths, tuple(paths[:3]))
        self.assertEqual(any_of.adjacent_visible(paths[1], 1), paths[2])
        self.assertIsNone(any_of.adjacent_visible(paths[2], 1))
        self.assertEqual(any_of.adjacent_visible(paths[4], -1), paths[2])
        combined = FileListProjection.create(root, items, FileListQuery(
            categories={"Crack", "缺损"}, category_match="any", review="verified", text="1.png"))
        self.assertEqual(combined.visible_paths, (paths[1],))
        unrestricted = FileListProjection.create(root, items, FileListQuery(category_match="any"))
        self.assertEqual(unrestricted.visible_paths, tuple(paths))
        self.assertFalse(unrestricted.filter_active)


class CategoryControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(SIMPLIFIED_CHINESE)
        self.controls = FileListControlBar()
        self.controls.set_workspace_available(True)
        self.controls.set_available_categories(("裂纹", "缺损", "Crack"))
        self.controls.show()

    def tearDown(self):
        self.controls.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        set_language(ENGLISH)

    def test_checkboxes_search_modes_summary_and_live_language_switch(self):
        panel = self.controls.filter_panel
        self.controls.show_filter_panel()
        self.app.processEvents()
        panel.category_search.setText("裂")
        item = next(panel.category_list.item(row) for row in range(panel.category_list.count())
                    if panel.category_list.item(row).text() == "裂纹")
        QTest.mouseClick(panel.category_list.viewport(), Qt.LeftButton,
                         pos=panel.category_list.visualItemRect(item).topLeft() + QPoint(9, 9))
        self.assertEqual(self.controls.state.category_filter, frozenset({"裂纹"}))
        self.controls.set_category_filter({"裂纹", "缺损"})
        panel.category_any.click()
        self.assertEqual(self.controls.state.category_match, "any")
        self.assertIn("任一包含", self.controls.category_chip_button.text())
        self.assertTrue(self.controls.filter_button.active)
        panel.category_search.setText("CRACK")
        self.assertEqual([panel.category_list.item(row).text() for row in range(panel.category_list.count())
                          if not panel.category_list.item(row).isHidden()], ["Crack"])
        self.assertEqual(self.controls.state.category_filter, frozenset({"裂纹", "缺损"}))
        set_language(ENGLISH)
        self.assertEqual(panel.category_title.text(), "Annotation categories")
        self.assertEqual(panel.category_any.text(), "Any selected")
        self.assertEqual(panel.category_any.accessibleName(), "Include any selected category")
        self.assertIn("Categories: any of", self.controls.category_chip_button.text())
        self.assertIn("裂纹", self.controls.category_chip_button.text())
        panel.hide()
        self.controls.category_chip_button.click()
        self.assertTrue(panel.isVisible())
        self.controls.search_edit.setText("image")
        panel.review_combo.setCurrentIndex(3)
        self.controls.category_clear_button.click()
        self.assertFalse(self.controls.state.category_filter)
        self.assertEqual(self.controls.state.text_filter, "image")
        self.assertEqual(self.controls.state.review_filter, "verified")
        self.controls.clear_all_conditions()
        self.assertFalse(self.controls.state.filter_active)
        self.assertEqual(panel.category_search.text(), "")

    def test_index_gating_and_disappearing_categories_preserve_query(self):
        self.controls.set_category_filter({"裂纹"})
        self.controls.set_available_categories(("缺损",))
        self.assertEqual(self.controls.state.category_filter, frozenset({"裂纹"}))
        self.assertIn("裂纹", [self.controls.filter_panel.category_list.item(row).text()
                              for row in range(self.controls.filter_panel.category_list.count())])
        self.controls.set_index_complete(False)
        self.assertFalse(self.controls.filter_button.isEnabled())
        self.assertFalse(self.controls.state.projection_query(False).categories)
        self.controls.set_index_complete(True)
        self.assertEqual(self.controls.state.projection_query().categories, frozenset({"裂纹"}))

    def test_category_section_is_independent_and_its_clear_keeps_other_conditions(self):
        panel = self.controls.filter_panel
        self.controls.search_edit.setText("01")
        panel.review_combo.setCurrentIndex(3)
        self.controls.set_category_filter({"裂纹", "缺损"}, "any")
        self.controls.show_filter_panel()
        self.app.processEvents()
        self.assertTrue(panel.category_section.isAncestorOf(panel.category_search))
        self.assertTrue(panel.state_section.isAncestorOf(panel.review_combo))
        self.assertFalse(panel.category_section.isAncestorOf(panel.review_combo))
        self.assertLess(panel.category_section.geometry().bottom(), panel.state_section.geometry().top())
        self.assertIn("2", panel.category_count.text())
        panel.category_reset_button.click()
        self.assertFalse(self.controls.state.category_filter)
        self.assertEqual(self.controls.state.text_filter, "01")
        self.assertEqual(self.controls.state.review_filter, "verified")
        self.assertFalse(panel.category_reset_button.isEnabled())
        panel.close_button.click()
        self.assertFalse(panel.isVisible())
        self.assertEqual(self.controls.state.review_filter, "verified")

    def test_category_list_uses_content_height_and_local_search_does_not_change_selection(self):
        panel = self.controls.filter_panel
        self.controls.set_available_categories(["category%d" % index for index in range(40)])
        self.controls.set_category_filter({"category30"})
        self.controls.show_filter_panel()
        self.app.processEvents()
        many_height = panel.category_list.height()
        panel.category_search.setText("category30")
        self.app.processEvents()
        self.assertLess(panel.category_list.height(), many_height)
        self.assertEqual(self.controls.state.category_filter, frozenset({"category30"}))
        panel.category_search.setText("no such category")
        self.assertTrue(panel.category_list.isHidden())
        self.assertFalse(panel.category_empty.isHidden())
        self.assertEqual(self.controls.state.category_filter, frozenset({"category30"}))
        panel.category_any.click()
        self.assertIn("至少一个", panel.category_match_help.text())
        set_language(ENGLISH)
        self.assertEqual(panel.state_title.text(), "State conditions")
        self.assertEqual(panel.category_count.text(), "1 selected")
        self.assertIn("at least one", panel.category_match_help.text())

    def test_popup_keeps_footer_on_screen_with_a_long_category_list(self):
        panel = self.controls.filter_panel
        font_id = -1
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
        if font_path.is_file():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            family = QFontDatabase.applicationFontFamilies(font_id)[0]
        elif QFontDatabase().families():
            family = QFontDatabase().families()[0]
        else:
            self.skipTest("A real UI font is required for layout verification")
        try:
            panel.setFont(QFont(family, 9))
            self.controls.set_available_categories(["category%d" % index for index in range(100)])
            set_language(ENGLISH)
            self.controls.show_filter_panel()
            self.app.processEvents()
            available = panel.screen().availableGeometry()
            self.assertLessEqual(panel.geometry().bottom(), available.bottom())
            self.assertGreaterEqual(panel.geometry().top(), available.top())
            self.assertTrue(panel.clear_button.isVisible())
            self.assertLess(panel.clear_button.mapTo(panel, QPoint()).y() + panel.clear_button.height(), panel.height())
            panel.category_search.setText("category30")
            self.app.processEvents()
            panel.move(panel.x(), available.bottom() - panel.height() + 1)
            panel.category_search.clear()
            self.app.processEvents()
            self.assertLessEqual(panel.geometry().bottom(), available.bottom())
        finally:
            panel.hide()
            if font_id != -1:
                QFontDatabase.removeApplicationFont(font_id)


class CategoryWorkbenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.env = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": str(self.root / "config")})
        self.env.start()
        self.images = self.root / "images"
        self.annotations = self.root / "annotations"
        self.images.mkdir()
        self.annotations.mkdir()
        self.paths = [str(self.images / ("0%d.png" % index)) for index in range(5)]
        image = QImage(100, 80, QImage.Format_RGB32)
        image.fill(QColor("white"))
        for path in self.paths:
            self.assertTrue(image.save(path))
        document = AnnotationDocument(self.paths[0], image, boxes=(
            AnnotationBox("裂纹", ((10, 10), (30, 10), (30, 30), (10, 30))),))
        document.save(str(self.annotations / "00"), AnnotationFormat.PASCAL_VOC)
        (self.annotations / "classes.txt").write_text("裂纹\n缺损\n其它\nunused\n", encoding="utf-8")
        (self.annotations / "01.txt").write_text(
            "0 0.2 0.2 0.1 0.1\n1 0.4 0.4 0.1 0.1\n2 0.6 0.6 0.1 0.1\n", encoding="utf-8")
        (self.annotations / "collection.json").write_text(json.dumps([
            {"image": "02.png", "annotations": [{"label": "缺损", "coordinates": {
                "x": 20, "y": 20, "width": 10, "height": 10}}]},
            {"image": "04.png", "annotations": [{"label": "异物", "coordinates": {
                "x": 20, "y": 20, "width": 10, "height": 10}}]},
        ]), encoding="utf-8")
        classes = self.root / "defaults.txt"
        classes.write_text("", encoding="utf-8")
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=str(classes), save_dir=str(self.annotations)))
        self.window.auto_saving.setChecked(False)
        self.window.import_dir_images(str(self.images))

    def tearDown(self):
        self.window.stop_directory_load()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.env.stop()
        self.temporary.cleanup()

    def test_three_formats_navigation_hidden_selection_and_refresh(self):
        controls = self.window.file_list_controls
        self.assertNotIn("unused", controls.filter_panel._available_categories)
        self.window.file_list_widget.item(3).setSelected(True)
        controls.set_category_filter({"裂纹", "缺损"})
        self.assertEqual(self.window.visible_file_paths(), [self.paths[1]])
        self.assertEqual(self.window.file_path, self.paths[0])
        self.assertEqual(self.window.selected_file_paths(), [self.paths[3]])
        controls.set_category_filter({"裂纹", "缺损"}, "any")
        self.assertEqual(self.window.visible_file_paths(), self.paths[:3])
        self.window.open_next_image()
        self.assertEqual(self.window.file_path, self.paths[1])
        self.window.open_next_image()
        self.assertEqual(self.window.file_path, self.paths[2])
        self.assertFalse(self.window.actions.openNext.isEnabled())
        self.window.refresh_file_list_statuses()
        self.assertEqual(self.window.visible_file_paths(), self.paths[:3])
        self.assertEqual(controls.state.category_match, "any")
        controls.set_category_filter({"异物"})
        self.assertEqual(self.window.visible_file_paths(), [self.paths[4]])
        controls.clear_all_conditions()
        self.assertEqual(self.window.visible_file_paths(), self.paths)

    def test_committed_edit_undo_redo_and_save_update_results(self):
        controls = self.window.file_list_controls
        controls.set_category_filter({"裂纹"})
        self.window.label_selection_requested(self.window.canvas.shapes, self.window.canvas.shapes[0])
        self.window.delete_selected_shape()
        self.assertEqual(self.window.visible_file_paths(), [self.paths[1]])
        self.assertEqual(self.window.file_path, self.paths[0])
        self.window.undo_annotation()
        self.assertEqual(self.window.visible_file_paths(), self.paths[:2])
        self.window.redo_annotation()
        self.assertEqual(self.window.visible_file_paths(), [self.paths[1]])
        self.window.save_file()
        self.assertEqual(self.window.visible_file_paths(), [self.paths[1]])

    def test_label_edit_and_last_occurrence_removal_keep_selected_condition(self):
        controls = self.window.file_list_controls
        shape = self.window.canvas.shapes[0]
        with patch.object(self.window.candidate_label_dialog, "choose", return_value="唯一类别"):
            self.window.edit_shape_label(shape)
        controls.set_category_filter({"唯一类别"})
        self.assertEqual(self.window.visible_file_paths(), [self.paths[0]])
        self.window.undo_annotation()
        self.assertEqual(self.window.visible_file_paths(), [])
        self.assertEqual(controls.state.category_filter, frozenset({"唯一类别"}))
        self.assertTrue(controls.category_chip.isVisibleTo(controls))
        self.assertIs(self.window.file_list_stack.currentWidget(), self.window.file_list_empty_state)
        self.window.redo_annotation()
        self.assertEqual(self.window.visible_file_paths(), [self.paths[0]])

    def test_background_refresh_preserves_filter_and_workspace_switch_resets_it(self):
        controls = self.window.file_list_controls
        controls.set_category_filter({"裂纹", "缺损"}, "any")
        self.window.start_directory_load(str(self.images))
        timer = QElapsedTimer()
        timer.start()
        while (self.window._directory_load_jobs or not controls.index_complete) and timer.elapsed() < 5000:
            QTest.qWait(10)
        self.assertFalse(self.window._directory_load_jobs)
        self.assertTrue(controls.index_complete)
        self.assertEqual(self.window.visible_file_paths(), self.paths[:3])
        self.assertEqual(controls.state.category_filter, frozenset({"裂纹", "缺损"}))
        other = self.root / "other"
        other.mkdir()
        image = QImage(10, 10, QImage.Format_RGB32)
        image.fill(Qt.white)
        image.save(str(other / "another.png"))
        self.window.import_dir_images(str(other))
        self.assertFalse(controls.state.category_filter)
        self.assertFalse(controls.category_chip.isVisibleTo(controls))

    def test_inactive_formats_are_not_combined(self):
        image = QImage(self.paths[1])
        document = AnnotationDocument(self.paths[1], image, boxes=(
            AnnotationBox("XML only", ((10, 10), (30, 10), (30, 30), (10, 30))),))
        document.save(str(self.annotations / "01"), AnnotationFormat.PASCAL_VOC)
        xml = str(self.annotations / "01.xml")
        workspace = self.window.annotation_workspace
        workspace.refresh_document_choices(self.paths[1])
        self.assertEqual(workspace.labels_for_image(self.paths[1]), frozenset())
        workspace.select_active_document(self.paths[1], xml)
        self.window.update_file_list_item_status(self.paths[1])
        self.window.file_list_controls.set_category_filter({"XML only", "裂纹"})
        self.assertEqual(self.window.visible_file_paths(), [])
        self.window.file_list_controls.set_category_filter({"XML only"})
        self.assertEqual(self.window.visible_file_paths(), [self.paths[1]])


if __name__ == "__main__":
    unittest.main()
