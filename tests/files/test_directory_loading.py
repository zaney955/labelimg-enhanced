import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication

from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class DirectoryLoadingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        classes = os.path.join(self.temporary.name, "classes.txt")
        with open(classes, "w", encoding="utf-8"):
            pass
        self.window = create_workbench(
            WorkbenchLaunchOptions(class_file=classes, save_dir="")
        )

    def tearDown(self):
        self.window.stop_directory_load()
        deadline = time.monotonic() + 5
        while self.window._directory_load_jobs and time.monotonic() < deadline:
            self.app.processEvents()
        self.window.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def directory(self, name, image_name):
        directory = os.path.join(self.temporary.name, name)
        os.makedirs(directory)
        path = os.path.join(directory, image_name)
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(path))
        return directory, os.path.abspath(path)

    def wait_until(self, predicate, timeout_ms=5000):
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        timer.start()
        deadline.start(timeout_ms)
        loop.exec_()
        timer.stop()
        self.assertTrue(predicate())

    def test_superseded_generation_cannot_replace_newer_directory(self):
        first, _first_path = self.directory("first", "first.png")
        second, second_path = self.directory("second", "second.png")

        self.window.start_directory_load(first)
        self.window.start_directory_load(second)
        self.wait_until(
            lambda: not self.window._directory_load_jobs
            and self.window.file_path == second_path
        )

        self.assertEqual(self.window.dir_name, second)
        self.assertEqual(self.window.m_img_list, [second_path])


if __name__ == "__main__":
    unittest.main()
