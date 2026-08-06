import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PIL import Image
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QApplication, QDialog

from labelimg.image_tools.dialog import ImageToolsDialog


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


if __name__ == "__main__":
    unittest.main()
