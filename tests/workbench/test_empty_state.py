"""The finished empty surface projects existing commands and Canvas state."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

from labelimg.localization.runtime import ENGLISH, SIMPLIFIED_CHINESE, set_language
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class EmptyWorkbenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ, {"LABELIMG_CONFIG_DIR": self.temp.name}
        )
        self.environment.start()
        classes = Path(self.temp.name) / "classes.txt"
        classes.write_text("", encoding="utf-8")
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes)))
        self.window.change_language(ENGLISH)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.stop_directory_load()
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()
        set_language(ENGLISH)

    def test_start_action_and_canvas_projection(self):
        state = self.window.empty_state
        self.assertTrue(state.isVisible())
        with patch(
            "labelimg.workbench.main_window.QFileDialog.getExistingDirectory",
            return_value="",
        ) as choose:
            state.open_button.click()
        choose.assert_called_once()
        path = str(Path(self.temp.name) / "image.png")
        image = QImage(60, 40, QImage.Format_RGB32)
        image.fill(0)
        self.assertTrue(image.save(path))
        self.assertTrue(self.window.load_file(path))
        self.app.processEvents()
        self.assertTrue(state.isHidden())
        self.window.reset_state()
        self.app.processEvents()
        self.assertTrue(state.isVisible())

    def test_language_switch_keeps_the_existing_action_binding(self):
        self.window.change_language(SIMPLIFIED_CHINESE)
        self.assertEqual(self.window.empty_state.title.text(), "开始图像标注")
        self.assertEqual(
            self.window.empty_state.open_button.text(),
            self.window.actions.openDir.text().replace("&", ""),
        )
        self.assertEqual(
            self.window.actions.openDir.shortcut().toString(), "Ctrl+Shift+O"
        )


if __name__ == "__main__":
    unittest.main()
