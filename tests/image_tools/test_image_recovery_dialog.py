import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QApplication

from labelimg.image_tools.ui.recovery_dialog import (
    ImageRecoverySelectionDialog,
)


class ImageRecoverySelectionDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_defaults_to_all_and_returns_an_explicit_subset(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = tuple(
                os.path.join(directory, name)
                for name in ("one.png", "two.png", "three.png")
            )
            dialog = ImageRecoverySelectionDialog(tuple(
                SimpleNamespace(original_path=path)
                for path in paths
            ))

            self.assertEqual(dialog.selected_paths, paths)
            dialog.list_widget.item(1).setCheckState(Qt.Unchecked)

            self.assertEqual(
                dialog.selected_paths,
                (paths[0], paths[2]),
            )
            self.assertTrue(dialog.restore_button.isEnabled())
            dialog.deleteLater()

    def test_requires_at_least_one_selected_image(self):
        resource = SimpleNamespace(original_path=os.path.abspath("one.png"))
        dialog = ImageRecoverySelectionDialog((resource,))

        dialog.list_widget.item(0).setCheckState(Qt.Unchecked)

        self.assertFalse(dialog.restore_button.isEnabled())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
