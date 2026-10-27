"""Navigation must remain responsive while a large destination is decoding."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import QEvent, QPointF, Qt, QTimer
from PyQt5.QtGui import QColor, QImage, QMouseEvent, QKeyEvent
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

    def test_held_d_displays_consecutive_images_before_release_without_backlog(self):
        # Decode is slower than OS auto-repeat: this must throttle navigation,
        # not continually invalidate the result that is about to be displayed.
        self.window.show()
        self.window.activateWindow()
        self.window.canvas.setFocus()
        self.app.processEvents()
        cache = self.window._ensure_image_decode_cache()
        displayed = []
        original = self.window._load_indexed_image

        def display(path, **kwargs):
            result = original(path, **kwargs)
            displayed.append(path)
            return result

        def decode(path):
            time.sleep(.08)
            return QImage(path)

        repeat = QTimer()
        repeat.setInterval(15)
        repeat.timeout.connect(lambda: QApplication.sendEvent(
            self.window.canvas, QKeyEvent(
                QEvent.KeyPress, Qt.Key_D, Qt.NoModifier, 'd', True)))
        with patch.object(self.window, '_requires_async_image_load', return_value=True), \
             patch.object(cache, 'get', return_value=None), \
             patch.object(cache, 'load', side_effect=decode), \
             patch.object(self.window, '_load_indexed_image', side_effect=display):
            QApplication.sendEvent(self.window.canvas, QKeyEvent(
                QEvent.KeyPress, Qt.Key_D, Qt.NoModifier, 'd'))
            repeat.start()
            deadline = time.monotonic() + 2
            while len(displayed) < 3 and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.002)
            repeat.stop()
            before_release = list(displayed)
            QApplication.sendEvent(self.window.canvas, QKeyEvent(
                QEvent.KeyRelease, Qt.Key_D, Qt.NoModifier, 'd'))
            self.wait_until(lambda: not self.window._navigation_load_path)
        self.assertGreaterEqual(len(before_release), 3,
                                'held D starves completed image decodes')
        self.assertEqual(displayed, self.paths[1:1 + len(displayed)],
                         'key repeats skipped images that were never displayed')
        self.assertLessEqual(len(displayed) - len(before_release), 1)

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
                self.window._request_indexed_image(self.paths[3])
                self.window._request_indexed_image(self.paths[4])
                self.window._request_indexed_image(self.paths[2])
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

    def test_direct_open_of_uncached_large_image_decodes_outside_gui(self):
        ui_thread = threading.get_ident()
        cache = self.window._ensure_image_decode_cache()
        heartbeat = threading.Event()
        def decode(path):
            self.assertNotEqual(threading.get_ident(), ui_thread)
            self.assertTrue(heartbeat.wait(.5))
            return QImage(path)
        QTimer.singleShot(20, heartbeat.set)
        with patch.object(self.window, '_requires_async_image_load', return_value=True), \
             patch.object(cache, 'get', return_value=None), \
             patch.object(cache, 'load', side_effect=decode) as load:
            self.assertTrue(self.window.load_file(self.paths[3]))
            load.assert_called_once_with(self.paths[3])
        self.assertEqual(self.window.file_path, self.paths[3])

    def test_warm_previous_and_next_do_not_hash_image_on_gui_thread(self):
        from labelimg.annotations.infrastructure import storage
        original = storage.fingerprint_path
        for path in self.paths[:2]:
            self.assertTrue(self.window.load_file(path))
        gui_thread = threading.get_ident()

        def fingerprint(path):
            if str(path) in self.paths:
                self.assertNotEqual(
                    threading.get_ident(), gui_thread,
                    'warm navigation reads the complete image on the GUI thread',
                )
            return original(path)

        with patch.object(storage, 'fingerprint_path', side_effect=fingerprint):
            for _ in range(3):
                self.window.open_prev_image()
                self.assertEqual(self.window.file_path, self.paths[0])
                self.window.open_next_image()
                self.assertEqual(self.window.file_path, self.paths[1])

    def test_cold_large_image_fingerprint_is_prepared_off_gui_thread(self):
        from labelimg.annotations.infrastructure import storage
        path = str(Path(self.temporary.name, 'large.png'))
        image = QImage(3000, 2000, QImage.Format_RGB32)
        image.fill(QColor('red'))
        self.assertTrue(image.save(path))
        original = storage.fingerprint_path
        gui_thread = threading.get_ident()
        observed = []

        def fingerprint(resource):
            if str(resource) == path:
                observed.append(threading.get_ident())
                self.assertNotEqual(threading.get_ident(), gui_thread)
            return original(resource)

        with patch.object(storage, 'fingerprint_path', side_effect=fingerprint):
            self.assertTrue(self.window.load_file(path))
        self.assertTrue(observed)
        self.assertIsNotNone(self.window.annotation_editing.view.snapshot.image_fingerprint)

    def test_reversing_pending_step_at_boundary_cancels_it(self):
        release = threading.Event()
        cache = self.window._ensure_image_decode_cache()
        with patch.object(self.window, '_requires_async_image_load', return_value=True), \
             patch.object(cache, 'get', return_value=None), \
             patch.object(cache, 'load', side_effect=lambda path: (release.wait(1), QImage(path))[1]):
            try:
                self.window.open_next_image()
                for _ in range(20):
                    self.window.open_next_image()
                self.assertEqual(self.window._navigation_load_path, self.paths[1])
                self.assertTrue(self.window.actions.openPrev.isEnabled())
                self.window.open_prev_image()
                self.assertIsNone(self.window._navigation_load_path)
            finally:
                release.set()
            self.wait_until(lambda: not self.window._navigation_loader.busy)
            self.app.processEvents()
        self.assertEqual(self.window.file_path, self.paths[0])

    def test_direct_large_decode_error_preserves_the_visible_image(self):
        cache = self.window._ensure_image_decode_cache()
        with patch.object(self.window, '_requires_async_image_load', return_value=True), \
             patch.object(cache, 'get', return_value=None), \
             patch.object(cache, 'load', side_effect=OSError('source changed')), \
             patch.object(self.window, 'error_message') as error:
            self.assertFalse(self.window.load_file(self.paths[3]))
            error.assert_called_once()
        self.assertEqual(self.window.file_path, self.paths[0])

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
