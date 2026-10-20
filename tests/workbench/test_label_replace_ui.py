import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QEvent
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from labelimg.annotations import AnnotationBox, AnnotationDocument, AnnotationFormat, AnnotationWorkspace
from labelimg.annotations.ui.label_replace_dialog import LabelReplaceDialog
from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class LabelReplaceUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language(ENGLISH)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'LABELIMG_CONFIG_DIR': str(self.root / 'config')})
        self.environment.start()
        self.images = self.root / 'images'
        self.images.mkdir()
        self.paths = tuple(str(self.images / name) for name in ('first.png', 'second.png'))
        workspace = AnnotationWorkspace(image_dir=self.images)
        for path in self.paths:
            image = QImage(40, 30, QImage.Format_RGB32)
            image.fill(0xFFFFFF)
            self.assertTrue(image.save(path))
            workspace.save(AnnotationDocument(
                image_path=path, image_data=Path(path).read_bytes(),
                boxes=(AnnotationBox('apple', ((2, 3), (12, 3), (12, 15), (2, 15))),),
            ), AnnotationFormat.PASCAL_VOC)
        classes = self.root / 'classes.txt'
        classes.write_text('')
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes), save_dir=''))
        self.window.import_dir_images(str(self.images))
        self.window.auto_saving.setChecked(False)

    def tearDown(self):
        self.window.stop_directory_load()
        self.window.finish_deferred_image_loads()
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()
        set_language(ENGLISH)

    def test_menu_action_replaces_hidden_images_and_recovers_canvas_and_candidates(self):
        self.assertTrue(self.window.actions.replaceLabels.isEnabled())
        self.assertIn(self.window.actions.replaceLabels, self.window.menus.edit.actions())
        self.window.file_list_controls.search_edit.setText('first')

        def choose(dialog):
            dialog.old_label.setEditText('apple')
            dialog.new_label.setText('apple_s')
            dialog.preview()
            self.assertIsNotNone(dialog.plan, dialog.summary.text())
            self.assertEqual(len(dialog.plan.items), 2)
            self.assertTrue(dialog.apply_button.isEnabled())
            return QDialog.Accepted

        with patch.object(LabelReplaceDialog, 'exec_', choose), patch.object(self.window, 'error_message') as error:
            self.window.actions.replaceLabels.trigger()
            error.assert_not_called()
        self.assertEqual([shape.label for shape in self.window.canvas.shapes], ['apple_s'])
        self.assertEqual(self.window.candidate_labels, ['apple_s'])
        entries = self.window.file_operations.recovery_entries
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].operation, 'label-replace')
        with patch('labelimg.workbench.recovery_ui.localized_question', return_value=QMessageBox.Yes):
            self.window._confirm_file_recovery(entries[0].entry_id)
        self.assertEqual([shape.label for shape in self.window.canvas.shapes], ['apple'])
        self.assertEqual(self.window.candidate_labels, ['apple'])
        self.assertFalse(self.window.dirty)

    def test_cancel_keeps_files_and_history_and_clears_pending(self):
        originals = tuple(Path(path).with_suffix('.xml').read_bytes() for path in self.paths)
        before = self.window.annotation_editing.view
        with patch.object(LabelReplaceDialog, 'exec_', return_value=QDialog.Rejected):
            self.window.replace_label_names()
        self.assertEqual(tuple(Path(path).with_suffix('.xml').read_bytes() for path in self.paths), originals)
        self.assertEqual(self.window.annotation_editing.view, before)
        self.assertFalse(self.window.annotation_editing.pending)
        self.assertFalse(self.window.file_operations.recovery_entries)

    def test_dialog_preview_invalidation_no_match_and_localization(self):
        set_language(SIMPLIFIED_CHINESE)
        dialog = LabelReplaceDialog(
            ['apple'], selected_count=1,
            preview=lambda scope, old, new, progress: self.window.label_replacement.preview(
                self.paths[:1] if scope == 'selected' else self.paths, old, new, AnnotationFormat.PASCAL_VOC,
            ),
        )
        self.assertEqual(dialog.windowTitle(), '替换标签名…')
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.old_label.setEditText('apple')
        dialog.new_label.setText('apple_s')
        dialog.preview()
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.table.rowCount(), 2)
        dialog.scope.setCurrentIndex(1)
        self.assertIsNone(dialog.plan)
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.preview()
        self.assertEqual(dialog.table.rowCount(), 1)
        dialog.new_label.setText('pear')
        self.assertIsNone(dialog.plan)
        dialog.old_label.setEditText('no_match')
        dialog.preview()
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.table.rowCount(), 0)
        dialog.old_label.setEditText('pear')
        self.assertFalse(dialog.preview_button.isEnabled())
        dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
