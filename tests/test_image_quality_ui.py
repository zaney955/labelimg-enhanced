import os
import tempfile
import unittest

from PIL import Image
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication

from labelimg.image_tools.quality import (
    ImageQualityPolicy,
    ImageQualityScanner,
)
from labelimg.image_tools.quality_ui import (
    ImageQualityDialog,
    ImageQualityPanel,
)


class ImageQualityUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.first = os.path.join(self.temporary.name, "first.png")
        self.second = os.path.join(self.temporary.name, "second.png")
        Image.new("RGB", (20, 20), (10, 10, 10)).save(self.first)
        Image.new("RGB", (20, 20), (120, 120, 120)).save(self.second)

    def tearDown(self):
        for widget in getattr(self, "widgets", ()):
            widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temporary.cleanup()

    def test_dialog_defaults_to_workspace_and_exposes_per_run_overrides(self):
        dialog = ImageQualityDialog(
            self.first,
            (self.first,),
            (self.first, self.second),
        )
        self.widgets = (dialog,)

        self.assertEqual(dialog.scope_combo.currentData(), "workspace")
        dialog.min_width.setValue(10)
        dialog.min_height.setValue(10)
        dialog.accept()

        self.assertEqual(dialog.request.paths, (self.first, self.second))
        self.assertEqual(dialog.request.policy.min_width, 10)
        self.assertEqual(dialog.request.policy.min_height, 10)

    def test_panel_lists_findings_and_retains_paths_for_refresh(self):
        result = ImageQualityScanner().scan(
            self.first, ImageQualityPolicy.standard()
        )
        panel = ImageQualityPanel()
        self.widgets = (panel,)

        panel.set_results((result,))

        self.assertEqual(panel.table.rowCount(), 1)
        self.assertEqual(panel.result_paths, (self.first,))
        self.assertIn("dark", panel.table.item(0, 1).data(0x0100))


if __name__ == "__main__":
    unittest.main()
