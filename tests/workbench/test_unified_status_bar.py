"""Visible footer contracts: one row, priority, full messages, stable controls."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QImage, QMouseEvent, QStatusTipEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QStatusBar

from labelimg.localization.runtime import current_language, set_language, tr
from labelimg.annotations.domain.model import AnnotationFormat
from labelimg.annotations.infrastructure.document import AnnotationBox, AnnotationDocument
from labelimg.image_tools.domain.crop_geometry import CropRegion
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.workbench.canvas_status import WorkbenchStatusBar
from labelimg.workbench.commands import ZoomControl
from labelimg.ui.metrics import dp
from labelimg.ui.theme import COLORS


class UnifiedStatusBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
        if font.is_file():
            font_id = QFontDatabase.addApplicationFont(str(font))
            cls.app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 9))

    def setUp(self):
        self.language = current_language()
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": self.temporary.name})
        self.environment.start()
        classes = Path(self.temporary.name) / "classes.txt"
        classes.write_text("", encoding="utf-8")
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes), save_dir=""))
        self.window.resize(1024, 720)
        self.window.show()
        self.bar = self.window.statusBar()
        self.pump()
        self.bar.clearMessage()

    def pump(self):
        for _ in range(4):
            self.app.processEvents()

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()
        set_language(self.language)

    def assert_readable(self):
        for label in (self.bar.coordinates, self.bar.dimensions):
            self.assertGreaterEqual(label.width(), label.fontMetrics().horizontalAdvance(label.text()))
            self.assertGreaterEqual(label.height(), label.fontMetrics().height())
        for widget in (self.bar.readouts, self.bar.feedback, self.bar.view_controls):
            self.assertTrue(self.bar.surface.rect().contains(widget.geometry()))
        self.assertLess(self.bar.readouts.geometry().right(), self.bar.feedback.geometry().left())
        self.assertLess(self.bar.feedback.geometry().right(), self.bar.view_controls.geometry().left())

    def load_hint_fixture(self):
        path = Path(self.temporary.name) / "hints.png"
        image = QImage(240, 180, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(str(path)))
        AnnotationDocument(str(path), image, boxes=(
            AnnotationBox("C_TGSE", ((20, 20), (100, 20), (100, 100), (20, 100))),
            AnnotationBox("OTHER", ((140, 20), (220, 20), (220, 100), (140, 100))),
        )).save(str(path.with_suffix("")), AnnotationFormat.PASCAL_VOC)
        self.assertTrue(self.window.load_file(str(path)))
        self.bar.clearMessage()
        self.pump()

    def move_over_image(self, x, y):
        position = self.window.canvas.image_to_widget(QPointF(x, y))
        QApplication.sendEvent(self.window.canvas, QMouseEvent(
            QEvent.MouseMove, position, Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        ))

    def test_canvas_hover_updates_immediately_when_target_changes(self):
        self.load_hint_fixture()
        self.move_over_image(60, 60)
        self.assertEqual(self.bar.currentMessage(), tr("canvas.moveShape", label="C_TGSE"))
        self.move_over_image(180, 60)
        self.assertEqual(self.bar.currentMessage(), tr("canvas.moveShape", label="OTHER"))

    def test_entering_draw_mode_invalidates_previous_shape_status_tip(self):
        self.load_hint_fixture()
        self.move_over_image(60, 60)
        # Reproduce the native StatusTip delivered after the earlier hover.
        QApplication.sendEvent(self.window, QStatusTipEvent(self.window.canvas.statusTip()))
        self.assertIn("C_TGSE", self.bar.currentMessage())
        self.window.create_shape()
        self.assertNotIn("C_TGSE", self.bar.currentMessage())
        self.move_over_image(60, 60)
        self.assertNotIn("C_TGSE", self.bar.currentMessage())

    def test_tool_changes_and_hidden_targets_clear_previous_annotation_dimensions_immediately(self):
        self.load_hint_fixture()
        self.move_over_image(60, 60)
        self.assertEqual(self.bar.dimensions.text(), "W: 80  H: 80")
        self.window.create_shape()
        self.assertEqual(self.bar.dimensions.text(), "")
        self.window.set_edit_mode()
        self.move_over_image(60, 60)
        self.window.canvas.set_shape_visible(self.window.canvas.shapes[0], False)
        self.assertEqual(self.bar.dimensions.text(), "")

    def test_blank_canvas_and_leave_invalidate_previous_shape_hint(self):
        self.load_hint_fixture()
        self.move_over_image(60, 60)
        QApplication.sendEvent(self.window, QStatusTipEvent(self.window.canvas.statusTip()))
        self.move_over_image(120, 140)
        self.assertNotIn("C_TGSE", self.bar.currentMessage())
        self.move_over_image(60, 60)
        QApplication.sendEvent(self.window, QStatusTipEvent(self.window.canvas.statusTip()))
        QApplication.sendEvent(self.window.canvas, QEvent(QEvent.Leave))
        self.assertNotIn("C_TGSE", self.bar.currentMessage())

    def test_single_footer_at_supported_width_and_both_languages(self):
        for language in ("en", "zh_CN"):
            set_language(language)
            self.window.retranslate_ui()
            self.bar.set_image_size(QSize(200000, 100000))
            self.bar.coordinates.setText("X: 199999  Y: 99999")
            self.bar.dimensions.setText("W: 200000  H: 100000")
            self.pump()
            self.assertEqual(self.window.width(), 1024)
            self.assertEqual(self.window.findChildren(QStatusBar), [self.bar])
            self.assertEqual(self.bar.width(), self.window.width())
            self.assertLessEqual(self.bar.height(), 40)
            self.assert_readable()

    def test_theme_changed_before_first_show_keeps_footer_copy_readable(self):
        self.window.appearance.apply_preferences("light", "plum")
        other = create_workbench(WorkbenchLaunchOptions(
            class_file=str(Path(self.temporary.name) / "classes.txt"), save_dir="",
        ))
        try:
            other.auto_saving.setChecked(False)
            other.appearance.apply_preferences("dark", "plum")
            other.show()
            self.pump()
            pixels = other.statusBar().grab().toImage()
            self.assertEqual(pixels.pixelColor(2, pixels.height() // 2), QColor(COLORS["panel_header"]))
        finally:
            other.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_fresh_qt_hover_replaces_results_but_not_loading_feedback(self):
        self.window.status("Saved", 0)
        QApplication.sendEvent(self.window, QStatusTipEvent("Move box"))
        self.assertEqual(self.bar.currentMessage(), "Move box")
        self.bar.set_task_message("directoryLoading.indexing", count=123)
        self.window.status("Other result", 0)
        QApplication.sendEvent(self.window, QStatusTipEvent("Resize box"))
        self.assertEqual(self.bar.currentMessage(), tr("directoryLoading.indexing", count=123))
        self.bar.clear_task_message()
        self.assertEqual(self.bar.currentMessage(), "Resize box")
        self.bar.clearMessage()
        self.assertEqual(self.bar.currentMessage(), "Resize box")
        QApplication.sendEvent(self.window, QStatusTipEvent(""))
        self.assertEqual(self.bar.currentMessage(), "")

    def test_important_feedback_and_details_survive_lower_priority_messages(self):
        detail = "Unable to read annotation: " + "long/path/" * 100
        self.window.status(detail, 0, important=True)
        self.bar.set_task_message("directoryLoading.discovering")
        self.window.status("Saved", 0)
        QApplication.sendEvent(self.window, QStatusTipEvent("Move box"))
        self.pump()
        self.assertEqual(self.bar.currentMessage(), detail)
        self.assertEqual(self.bar.message_label.toolTip(), detail)
        self.assertEqual(self.bar.message_label.accessibleDescription(), detail)
        self.assertTrue(self.bar.details_button.isVisible())
        with patch("labelimg.workbench.canvas_status.information") as dialog:
            QTest.mouseClick(self.bar.details_button, Qt.LeftButton)
            self.assertEqual(dialog.call_args.args[2], detail)
        self.bar.clear_important_message()
        self.assertEqual(self.bar.currentMessage(), tr("directoryLoading.discovering"))

    def test_expiring_results_never_restore_an_old_native_hover(self):
        changes = []
        self.bar.messageChanged.connect(changes.append)
        QApplication.sendEvent(self.window, QStatusTipEvent("Move box"))
        self.bar.showMessage("Saved", 30)
        QTest.qWait(70)
        self.assertEqual(self.bar.currentMessage(), "")
        self.assertEqual(changes, ["Move box", "Saved", ""])

    def test_real_save_result_yields_immediately_to_fresh_canvas_interaction(self):
        path = Path(self.temporary.name) / "save.png"
        image = QImage(100, 80, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(str(path)))
        AnnotationDocument(str(path), image, boxes=(
            AnnotationBox("box", ((10, 10), (40, 10), (40, 30), (10, 30))),
        )).save(str(path.with_suffix("")), AnnotationFormat.PASCAL_VOC)
        self.assertTrue(self.window.load_file(str(path)))
        self.window.save_file()
        self.assertIn(str(path.with_suffix(".xml")), self.bar.currentMessage())
        self.move_over_image(25, 20)
        self.assertEqual(self.bar.currentMessage(), tr("canvas.moveShape", label="box"))

    def test_results_do_not_delay_mode_or_pointer_changes_or_reappear_after_timeout(self):
        self.load_hint_fixture()
        self.bar.showMessage("Saved", 30)
        self.move_over_image(60, 60)
        expected = tr("canvas.moveShape", label="C_TGSE")
        self.assertEqual(self.bar.currentMessage(), expected)
        QTest.qWait(70)
        self.assertEqual(self.bar.currentMessage(), expected)
        self.bar.showMessage("Saved", 5000)
        self.window.set_pan_mode()
        self.assertEqual(self.bar.currentMessage(), tr("canvas.hintPan"))
        self.window.create_shape()
        self.assertEqual(self.bar.currentMessage(), tr("canvas.hintDrawStart"))

    def test_draw_stage_and_cancel_have_current_guidance(self):
        self.load_hint_fixture()
        self.window.create_shape()
        position = self.window.canvas.image_to_widget(QPointF(120, 120)).toPoint()
        QTest.mousePress(self.window.canvas, Qt.LeftButton, pos=position)
        self.assertEqual(self.bar.currentMessage(), tr("canvas.hintDrawFinish"))
        QTest.mouseMove(self.window.canvas, position + QPoint(20, 20))
        QTest.keyClick(self.window.canvas, Qt.Key_Escape)
        self.assertNotEqual(self.bar.currentMessage(), tr("canvas.hintDrawFinish"))
        self.assertNotIn("C_TGSE", self.bar.currentMessage())
        QTest.mouseRelease(self.window.canvas, Qt.LeftButton, pos=position)

    def test_control_multi_selection_and_middle_pan_replace_shape_hint(self):
        self.load_hint_fixture()
        self.move_over_image(60, 60)
        self.window.canvas.set_multi_selection_mode(True)
        self.assertEqual(self.bar.currentMessage(), tr("canvas.ctrlToggle", label="C_TGSE"))
        self.window.canvas.set_multi_selection_mode(False)
        point = self.window.canvas.image_to_widget(QPointF(60, 60)).toPoint()
        QTest.mousePress(self.window.canvas, Qt.MiddleButton, pos=point)
        self.assertEqual(self.bar.currentMessage(), tr("canvas.hintPan"))
        QTest.mouseRelease(self.window.canvas, Qt.MiddleButton, pos=point)
        self.assertNotEqual(self.bar.currentMessage(), tr("canvas.hintPan"))

    def test_mouse_release_keeps_a_new_commit_result_until_the_next_interaction(self):
        self.load_hint_fixture()
        self.window.auto_saving.setChecked(False)
        canvas = self.window.canvas
        canvas.annotationGestureFinished.connect(lambda _description: self.window.status("Commit complete"))
        point = canvas.image_to_widget(QPointF(60, 60)).toPoint()
        destination = point + QPoint(10, 0)
        QTest.mousePress(canvas, Qt.LeftButton, pos=point)
        QApplication.sendEvent(canvas, QMouseEvent(
            QEvent.MouseMove, QPointF(destination), Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        ))
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=destination)
        self.assertEqual(self.bar.currentMessage(), "Commit complete")
        self.move_over_image(180, 60)
        self.assertEqual(self.bar.currentMessage(), tr("canvas.moveShape", label="OTHER"))

    def test_keyboard_move_and_multi_selection_warning_have_localized_current_copy(self):
        self.load_hint_fixture()
        for language in ("en", "zh_CN"):
            set_language(language)
            canvas = self.window.canvas
            canvas.set_selected_shapes((canvas.shapes[0],), active_shape=canvas.shapes[0])
            QTest.keyPress(canvas, Qt.Key_Right)
            self.assertEqual(self.bar.currentMessage(), tr("canvas.hintKeyboardMove", label="C_TGSE"))
            QTest.keyRelease(canvas, Qt.Key_Right)
            self.assertNotEqual(self.bar.currentMessage(), tr("canvas.hintKeyboardMove", label="C_TGSE"))
            canvas.set_selected_shapes(tuple(canvas.shapes), active_shape=canvas.shapes[0])
            QTest.keyClick(canvas, Qt.Key_Right)
            self.assertEqual(self.bar.currentMessage(), tr("canvas.singleSelectionForArrows"))

    def test_crop_context_persists_without_timer_and_clears_on_cancel(self):
        self.load_hint_fixture()
        self.move_over_image(60, 60)
        self.assertTrue(self.window.enter_crop_mode())
        self.assertEqual(self.bar.currentMessage(), tr("canvas.hintCrop"))
        self.assertEqual(self.bar.dimensions.text(), "")
        self.bar.clearMessage()
        self.assertEqual(self.bar.currentMessage(), tr("canvas.hintCrop"))
        overlay = self.window.crop_overlay
        position = self.window.canvas.image_to_widget(QPointF(130, 120))
        QApplication.sendEvent(overlay, QMouseEvent(
            QEvent.MouseMove, position, Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        ))
        self.assertEqual(self.bar.coordinates.text(), "X: 130  Y: 120")
        overlay.set_region(CropRegion(10, 10, 100, 100))
        position = self.window.canvas.image_to_widget(QPointF(170, 140))
        QApplication.sendEvent(overlay, QMouseEvent(
            QEvent.MouseMove, position, Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        ))
        self.assertEqual(self.bar.coordinates.text(), "X: 170  Y: 140")
        self.window.canvas.refresh_pointer_coordinates(self.window.canvas.image_to_widget(QPointF(60, 60)))
        self.assertEqual(self.bar.coordinates.text(), "X: 170  Y: 140")
        self.assertEqual(self.bar.dimensions.text(), "")
        self.bar.show_important_message("repair needed", source="test")
        QApplication.sendEvent(overlay, QEvent(QEvent.Leave))
        self.assertEqual(self.bar.coordinates.text(), "X: —  Y: —")
        self.assertEqual(self.bar.currentMessage(), "repair needed")
        self.bar.clear_important_message(source="test")
        self.window.cancel_crop()
        self.assertNotEqual(self.bar.currentMessage(), tr("canvas.hintCrop"))
        self.assertTrue(self.window.canvas.editing())
        self.move_over_image(180, 60)
        self.assertEqual(self.bar.coordinates.text(), "X: 180  Y: 60")
        self.assertEqual(self.bar.dimensions.text(), "W: 80  H: 80")
        self.assertEqual(self.bar.currentMessage(), tr("canvas.moveShape", label="OTHER"))

    def test_language_change_reprojects_shape_and_tool_hints_without_old_timer_text(self):
        self.load_hint_fixture()
        for language in ("en", "zh_CN"):
            self.move_over_image(60, 60)
            self.bar.showMessage("old-language result", 30)
            set_language(language)
            self.window.retranslate_ui()
            self.assertEqual(self.bar.currentMessage(), tr("canvas.moveShape", label="C_TGSE"))
            QTest.qWait(70)
            self.assertEqual(self.bar.currentMessage(), tr("canvas.moveShape", label="C_TGSE"))
        self.window.create_shape()
        set_language("en")
        self.assertEqual(self.bar.currentMessage(), tr("canvas.hintDrawStart"))

    def test_switch_image_and_close_drop_old_hints_results_and_failure_timers(self):
        self.load_hint_fixture()
        self.move_over_image(60, 60)
        self.bar.show_important_message("old image failure", 30)
        self.bar.showMessage("old image result", 40)
        path = Path(self.temporary.name) / "new.png"
        image = QImage(100, 80, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(str(path)))
        self.assertTrue(self.window.load_file(str(path)))
        self.bar.clearMessage()
        QTest.qWait(80)
        self.assertNotIn("C_TGSE", self.bar.currentMessage())
        self.assertNotIn("old image", self.bar.currentMessage())
        self.window.close_file()
        self.bar.clearMessage()
        self.assertEqual(self.bar.currentMessage(), "")

    def test_annotation_directory_resume_restarts_the_annotation_request(self):
        self.window._ensure_directory_loading()
        self.window._directory_load_kind = "annotations"
        self.window._directory_load_request = ("annotation-directory",)
        self.window.directory_load_button.show()
        self.window._directory_feedback("directoryLoading.failed", error="unavailable")
        self.pump()
        with patch.object(self.window, "start_annotation_directory_load") as resume, \
                patch.object(self.window, "start_directory_load") as images:
            QTest.mouseClick(self.window.directory_load_button, Qt.LeftButton)
            resume.assert_called_once_with("annotation-directory")
            images.assert_not_called()

    def test_hidden_or_deleted_annotation_cannot_remain_in_canvas_hint(self):
        self.load_hint_fixture()
        self.move_over_image(60, 60)
        shape = self.window.canvas.shapes[0]
        self.window.canvas.set_shape_visible(shape, False)
        self.assertNotIn("C_TGSE", self.bar.currentMessage())
        self.window.canvas.set_shape_visible(shape, True)
        self.move_over_image(60, 60)
        self.window.canvas.set_selected_shapes((shape,), active_shape=shape)
        self.window.canvas.delete_selected()
        self.assertNotIn("C_TGSE", self.bar.currentMessage())

    def test_external_annotation_failure_remains_visible_until_repair(self):
        self.load_hint_fixture()
        path = Path(self.temporary.name) / "hints.xml"
        valid = path.read_bytes()
        path.write_text("<annotation>", encoding="utf-8")
        self.window._process_external_annotation_change()
        failure = self.bar.currentMessage()
        self.assertTrue(self.bar.details_button.isVisible())
        self.move_over_image(60, 60)
        self.assertEqual(self.bar.currentMessage(), failure)
        for language in ("en", "zh_CN"):
            set_language(language)
            self.window.retranslate_ui()
            prefix = tr("external.invalid", path=str(path), error="").split(str(path))[0]
            self.assertTrue(self.bar.currentMessage().startswith(prefix))
            self.assertIn(str(path), self.bar.currentMessage())
            self.assertTrue(self.bar.details_button.isVisible())
        path.write_bytes(valid)
        self.window._process_external_annotation_change()
        self.assertFalse(self.bar.details_button.isVisible())
        self.move_over_image(180, 60)
        self.assertEqual(self.bar.currentMessage(), tr("canvas.moveShape", label="OTHER"))

    def test_feedback_and_directory_controls_never_move_zoom_or_change_height(self):
        self.window._ensure_directory_loading()
        self.pump()
        origin = self.bar.zoom.slider.mapToGlobal(QPoint())
        height = self.bar.height()
        for key in ("directoryLoading.discovering", "directoryLoading.stopped", "directoryLoading.failed"):
            self.window.directory_load_button.show()
            self.window._directory_feedback(key, **({"error": "long path " * 100} if key.endswith("failed") else {}))
            self.bar.showMessage("result " * 100)
            self.pump()
            self.assertEqual(self.bar.zoom.slider.mapToGlobal(QPoint()), origin)
            self.assertEqual(self.bar.height(), height)
            self.assert_readable()
        self.window._complete_directory_feedback()
        self.pump()
        self.assertEqual(self.bar.zoom.slider.mapToGlobal(QPoint()), origin)
        self.assertEqual(self.bar.height(), height)

    def test_directory_action_remains_operable_after_live_language_switch(self):
        self.window._ensure_directory_loading()
        self.window.directory_load_button.show()
        self.window._directory_feedback("directoryLoading.indexing", count=400)
        set_language("en")
        self.pump()
        self.assertEqual(self.window.directory_load_button.text(), tr("directoryLoading.stop"))
        QTest.mouseClick(self.window.directory_load_button, Qt.LeftButton)
        self.assertEqual(self.bar.currentMessage(), tr("directoryLoading.stopped"))
        set_language("zh_CN")
        self.pump()
        self.assertEqual(self.bar.currentMessage(), tr("directoryLoading.stopped"))
        self.assertEqual(self.window.directory_load_button.text(), tr("directoryLoading.resume"))
        self.window._directory_load_request = ("fixture-directory", 0)
        with patch.object(self.window, "start_directory_load") as restart:
            QTest.mouseClick(self.window.directory_load_button, Qt.LeftButton)
            restart.assert_called_once_with("fixture-directory", 0)

    def test_dock_relayout_and_restore_do_not_create_another_footer(self):
        state = self.window.saveState()
        for dock_area in (Qt.LeftDockWidgetArea, Qt.BottomDockWidgetArea, Qt.RightDockWidgetArea):
            self.window.addDockWidget(dock_area, self.window.file_dock)
            self.pump()
            self.assertEqual(self.bar.width(), self.window.width())
            self.assert_readable()
        self.window.tabifyDockWidget(self.window.dock, self.window.file_dock)
        self.window.file_dock.setFloating(True)
        self.pump()
        self.window.file_dock.setFloating(False)
        self.assertTrue(self.window.restoreState(state))
        self.pump()
        self.assertEqual(self.window.findChildren(QStatusBar), [self.bar])
        self.assert_readable()

    def test_extra_narrow_footer_stacks_only_readouts_without_clipping(self):
        footer = WorkbenchStatusBar(ZoomControl())
        footer.set_image_size(QSize(200000, 100000))
        footer.coordinates.setText("X: 199999  Y: 99999")
        footer.dimensions.setText("W: 200000  H: 100000")
        footer.resize(700, 40)
        footer.show()
        try:
            self.pump()
            self.assertTrue(footer.stacked)
            self.assertEqual(footer.zoom.slider.width(), dp(64))
            self.assertTrue(footer.surface.rect().contains(footer.view_controls.geometry()))
            for label in (footer.coordinates, footer.dimensions):
                self.assertGreaterEqual(label.width(), label.fontMetrics().horizontalAdvance(label.text()))
            self.assertLessEqual(footer.height(), footer.coordinates.height() * 2 + dp(10))
        finally:
            footer.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_live_application_scale_recomputes_content_and_restores_baseline(self):
        self.window._ensure_directory_loading()
        self.window.directory_load_button.show()
        self.window._directory_feedback("directoryLoading.failed", error="long path " * 80)
        self.pump()
        baseline = (self.bar.height(), self.bar.coordinates.width(), self.bar.zoom.slider.width())
        try:
            for percent in (125, 150, 200, 75, 100):
                self.window.ui_scale.set_percent(percent, persist=False)
                self.pump()
                self.assert_readable()
                self.assertEqual(self.bar.width(), self.window.width())
                self.assertLessEqual(self.bar.minimumSizeHint().width(), dp(1024) if percent < 100 else 1024)
                self.assertIn(self.bar.zoom.slider.width(), (dp(64), dp(80), dp(112)))
                self.assertTrue(self.bar.details_button.isVisible())
            self.assertEqual((self.bar.height(), self.bar.coordinates.width(),
                              self.bar.zoom.slider.width()), baseline)
        finally:
            self.window.ui_scale.set_percent(100, persist=False)
            self.pump()


if __name__ == "__main__":
    unittest.main()
