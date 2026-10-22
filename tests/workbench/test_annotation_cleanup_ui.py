"""Tools entry, safe defaults, localization and real workbench projection."""

import os
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from labelimg.files.ui.cleanup_dialog import AnnotationCleanupDialog
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.platform.recovery import TrashIdentity
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class AnnotationCleanupUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(ENGLISH)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.images = self.root / "images"
        self.labels = self.root / "labels"
        self.images.mkdir()
        self.labels.mkdir()
        (self.labels / "classes.txt").write_text("cat\n")
        image = QImage(20, 20, QImage.Format_RGB32)
        image.fill(Qt.white)
        image.save(str(self.images / "a.png"))
        (self.labels / "a.txt").write_text("")
        (self.labels / "absent.txt").write_text("")
        (self.labels / "invalid.json").write_text("{}")
        (self.root / "config").mkdir()
        self.environment = patch.dict(os.environ, {"LABELIMG_CONFIG_DIR": str(self.root / "config")})
        self.environment.start()
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=str(self.labels / "classes.txt"), save_dir=""))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.deleteLater()
        self.window.auto_save_timer.stop()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()
        set_language(ENGLISH)

    def dialog(self):
        dialog = AnnotationCleanupDialog(str(self.images), str(self.labels), (".png",), self.window)
        self.dialogs.append(dialog)
        return dialog

    def open_workspace(self):
        self.window._switch_annotation_directory(str(self.labels))
        self.window.import_dir_images(str(self.images))

    def test_tools_is_in_the_approved_menu_position_and_has_one_entry(self):
        self.assertEqual(self.window.menuBar().actions(), [
            getattr(self.window.menus, name).menuAction()
            for name in ("file", "edit", "image", "view", "tools", "settings", "help")
        ])
        action = self.window.actions.cleanupAnnotations
        self.assertEqual(self.window.menus.tools.actions(), [action, self.window.actions.annotationStatistics])
        self.assertFalse(action.isEnabled())
        self.assertTrue(action.shortcut().isEmpty())
        self.assertFalse(action.icon().isNull())
        self.assertNotIn(action, self.window.menus.annotationDirectory.actions())
        self.open_workspace()
        self.assertTrue(action.isEnabled())

    def test_preview_has_orphans_checked_and_empty_annotations_unchecked(self):
        dialog = self.dialog()
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.scan()
        self.assertEqual([Path(item.path).name for item in dialog.selected_items], ["absent.txt"])
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertEqual(dialog.skipped.rowCount(), 1)
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertTrue((self.labels / "absent.txt").exists())
        dialog.empty.setChecked(True)
        self.assertEqual(len(dialog.selected_items), 2)
        dialog.orphans.setChecked(False)
        self.assertEqual([Path(item.path).name for item in dialog.selected_items], ["a.txt"])

    def test_per_file_checkbox_can_exclude_an_individual_candidate(self):
        dialog = self.dialog()
        dialog.scan()
        row = next(row for row, item in enumerate(dialog.plan.items) if item.reason == "orphan")
        dialog.table.item(row, 0).setCheckState(Qt.Unchecked)
        self.assertEqual(dialog.selected_items, ())
        self.assertFalse(dialog.apply_button.isEnabled())

    def test_rescanning_discards_stale_selection_and_reclassifies_added_images(self):
        dialog = self.dialog()
        dialog.scan()
        shutil.copyfile(self.images / "a.png", self.images / "absent.png")
        dialog.scan()
        self.assertEqual(dialog.selected_items, ())
        self.assertTrue(all(item.reason == "zeroBytes" for item in dialog.plan.items))

    def test_confirmation_defaults_to_no_and_preserves_dialog_on_rejection(self):
        dialog = self.dialog()
        dialog.scan()
        with patch("labelimg.files.ui.cleanup_dialog.question", return_value=QMessageBox.No) as question:
            dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertEqual(question.call_args.args[-1], QMessageBox.No)
        self.assertTrue((self.labels / "absent.txt").exists())

    def test_menu_and_dialog_switch_languages_live_without_changing_selection(self):
        dialog = self.dialog()
        dialog.scan()
        selected = dialog.selected_items
        self.window.change_language(SIMPLIFIED_CHINESE)
        self.assertEqual(self.window.menus.tools.title(), "工具(&T)")
        self.assertEqual(self.window.actions.cleanupAnnotations.text(), "清理标注文件…")
        self.assertEqual(dialog.windowTitle(), "清理标注文件…")
        self.assertEqual(dialog.scan_button.text(), "扫描文件")
        self.assertEqual(dialog.selected_items, selected)
        self.assertEqual(dialog.skipped.item(0, 1).text(), "无法将此文件识别为有效标注，已保留。")
        self.window.change_language(ENGLISH)
        self.assertEqual(self.window.menus.tools.title(), "&Tools")

    def test_cancel_scan_leaves_no_actionable_partial_plan(self):
        dialog = self.dialog()
        with patch("labelimg.files.ui.cleanup_dialog.QProgressDialog.wasCanceled", return_value=True):
            dialog.scan()
        self.assertIsNone(dialog.plan)
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn("canceled", dialog.summary.text())

    def test_tools_command_cleans_and_recovers_in_the_real_workbench(self):
        self._exercise_cleanup_and_recovery()

    def test_shared_createml_review_state_is_projected_after_recovery(self):
        (self.labels / "a.txt").unlink()
        (self.labels / "absent.txt").unlink()
        (self.labels / "shared.json").write_text(json.dumps([
            {"image": "a.png", "annotations": [], "verified": True},
            {"image": "absent.png", "annotations": []},
        ]))
        self._exercise_cleanup_and_recovery(shared=True)

    def _exercise_cleanup_and_recovery(self, shared=False):
        self.open_workspace()
        if shared:
            self.assertTrue(self.window.annotation_document.verified)
        trashed = {}
        def move(path):
            destination = str(self.root / ("trash-" + str(len(trashed))))
            shutil.move(path, destination)
            trashed[path] = destination
            return TrashIdentity("path", destination, path)
        self.window.system_trash = type("Trash", (), {
            "move": staticmethod(move),
            "preflight": staticmethod(lambda _paths: None),
            "exists": staticmethod(lambda identity: os.path.exists(identity.token)),
            "restore": staticmethod(lambda identity, destination: shutil.move(identity.token, destination)),
        })()
        # Exercise the public command; automate only the modal review decision.
        def review(dialog):
            dialog.scan()
            dialog.empty.setChecked(True)
            return QDialog.Accepted
        with patch.object(AnnotationCleanupDialog, "exec_", review), patch("labelimg.files.ui.cleanup_dialog.warning") as warnings:
            self.window.cleanup_annotation_files()
        self.assertFalse(warnings.called, repr(warnings.call_args))
        if shared:
            self.assertFalse((self.labels / "shared.json").exists())
            self.assertIsNone(self.window.annotation_document)
        else:
            self.assertFalse((self.labels / "a.txt").exists())
            self.assertFalse((self.labels / "absent.txt").exists())
        self.assertTrue((self.images / "a.png").exists())
        self.assertTrue((self.labels / "classes.txt").exists())
        self.assertFalse(self.window.annotation_editing.pending)
        self.assertEqual(len(self.window.file_operations.recovery_entries), 1)
        entry = self.window.file_operations.recovery_entries[0]
        with patch("labelimg.workbench.recovery_ui.localized_question", return_value=QMessageBox.Yes):
            self.window._confirm_file_recovery(entry.entry_id)
        if shared:
            self.assertTrue((self.labels / "shared.json").exists())
            self.assertTrue(self.window.annotation_document.verified)
        else:
            self.assertTrue((self.labels / "a.txt").exists())
            self.assertTrue((self.labels / "absent.txt").exists())
        self.assertEqual(self.window.file_path, str(self.images / "a.png"))


if __name__ == "__main__":
    unittest.main()
