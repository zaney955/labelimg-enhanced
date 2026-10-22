"""Navigation must remain responsive while a large destination is decoding."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QMouseEvent
from PyQt5.QtWidgets import QApplication
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class NavigationLatencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'LABELIMG_CONFIG_DIR': self.temporary.name})
        self.environment.start()
        classes = Path(self.temporary.name, 'classes.txt')
        classes.write_text('', encoding='utf-8')
        self.paths = []
        for index in range(5):
            path = str(Path(self.temporary.name, f'{index}.png'))
            image = QImage(40, 30, QImage.Format_RGB32)
            image.fill(QColor(20 * index, 0, 0))
            image.save(path)
            self.paths.append(path)
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes)))
        self.window.import_dir_images(self.temporary.name)
        self.window.stop_directory_load()

    def tearDown(self):
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(condition())

    def test_uncached_large_navigation_returns_before_decode_and_latest_target_wins(self):
        started, release = threading.Event(), threading.Event()
        cache = self.window._ensure_image_decode_cache()
        calls = []

        def decode(path):
            calls.append(path)
            started.set()
            release.wait(2)
            return QImage(path)

        with patch.object(self.window, '_requires_async_image_load', return_value=True), \
             patch.object(cache, 'get', return_value=None), \
             patch.object(cache, 'load', side_effect=decode):
            try:
                self.window.open_next_image()
                self.assertTrue(started.wait(.5))
                self.assertFalse(release.is_set())
                self.assertEqual(self.window.file_path, self.paths[0])
                self.window.open_next_image()
                self.window.open_next_image()
                self.window.open_prev_image()
                self.assertEqual(self.window._navigation_load_path, self.paths[2])
            finally:
                release.set()
            self.wait_until(lambda: self.window.file_path == self.paths[2])
        self.assertEqual(calls, [self.paths[1], self.paths[2]])
        self.assertEqual(self.window.cur_img_idx, 2)

    def test_direct_load_cancels_pending_destination(self):
        release = threading.Event()
        cache = self.window._ensure_image_decode_cache()
        with patch.object(self.window, '_requires_async_image_load', return_value=True), \
             patch.object(cache, 'get', return_value=None), \
             patch.object(cache, 'load', side_effect=lambda path: (release.wait(2), QImage(path))[1]):
            try:
                self.window.open_next_image()
                self.assertTrue(self.window.load_file(self.paths[4]))
            finally:
                release.set()
            self.wait_until(lambda: not self.window._navigation_loader.busy)
            self.app.processEvents()
        self.assertEqual(self.window.file_path, self.paths[4])

    def test_failed_decode_keeps_current_image_and_counter(self):
        with patch.object(self.window, '_requires_async_image_load', return_value=True), \
             patch.object(self.window._ensure_image_decode_cache(), 'get', return_value=None), \
             patch.object(self.window._ensure_image_decode_cache(), 'load', return_value=QImage()), \
             patch.object(self.window, 'error_message') as error:
            self.window.open_next_image()
            self.wait_until(lambda: self.window._navigation_load_path is None)
            error.assert_called_once()
        self.assertEqual(self.window.file_path, self.paths[0])
        self.assertEqual(self.window.cur_img_idx, 0)

    def test_pending_decode_cannot_overwrite_new_annotation_edits(self):
        with patch.object(self.window, '_requires_async_image_load', return_value=True), \
             patch.object(self.window._ensure_image_decode_cache(), 'get', return_value=None), \
             patch.object(self.window, '_guard_image_navigation', side_effect=(True, False)) as guard:
            self.window.open_next_image()
            self.wait_until(lambda: self.window._navigation_load_path is None)
        self.assertEqual(guard.call_count, 2)
        self.assertEqual(self.window.file_path, self.paths[0])

    def test_removed_pending_target_does_not_raise_or_replace_current(self):
        release = threading.Event()
        cache = self.window._ensure_image_decode_cache()
        with patch.object(self.window, '_requires_async_image_load', return_value=True), \
             patch.object(cache, 'get', return_value=None), \
             patch.object(cache, 'load', side_effect=lambda path: (release.wait(1), QImage(path))[1]):
            self.window.open_next_image()
            self.window.m_img_list.remove(self.paths[1])
            release.set()
            self.wait_until(lambda: self.window._navigation_load_path is None)
        self.assertEqual(self.window.file_path, self.paths[0])

    def test_starting_a_new_box_cancels_pending_navigation(self):
        release = threading.Event()
        cache = self.window._ensure_image_decode_cache()
        with patch.object(self.window, '_requires_async_image_load', return_value=True), \
             patch.object(cache, 'get', return_value=None), \
             patch.object(cache, 'load', side_effect=lambda path: (release.wait(1), QImage(path))[1]):
            try:
                self.window.open_next_image()
                canvas = self.window.canvas
                canvas.set_editing(False)
                QApplication.sendEvent(canvas, QMouseEvent(
                    QEvent.MouseButtonPress, canvas.image_to_widget(QPointF(5, 5)),
                    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
                self.assertIsNone(self.window._navigation_load_path)
            finally:
                release.set()
            self.wait_until(lambda: not self.window._navigation_loader.busy)
            self.app.processEvents()
        self.assertEqual(self.window.file_path, self.paths[0])
        self.assertIsNotNone(self.window.canvas.current)
