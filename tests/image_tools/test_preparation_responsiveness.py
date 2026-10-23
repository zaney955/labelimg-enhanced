import os
from pathlib import Path
import tempfile
import threading
from concurrent.futures import CancelledError
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import QEvent, QTimer, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QProgressDialog
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench
from labelimg.image_tools.application.geometry_transform import ImageGeometryProcessor


class PreparationResponsivenessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'LABELIMG_CONFIG_DIR': self.temp.name})
        self.environment.start()
        classes = Path(self.temp.name, 'classes.txt')
        classes.write_text('', encoding='utf-8')
        self.window = create_workbench(WorkbenchLaunchOptions(class_file=str(classes)))
        self.path = str(Path(self.temp.name, 'image.png'))
        image = QImage(80, 60, QImage.Format_RGB32)
        image.fill(0)
        image.save(self.path)
        self.window.load_file(self.path)

    def tearDown(self):
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def test_image_menu_geometry_prepares_away_from_ui_and_keeps_event_loop_alive(self):
        ui_thread = threading.get_ident()
        heartbeat = threading.Event()
        observed = []
        original = ImageGeometryProcessor.prepare

        def prepare(processor, *args, **kwargs):
            observed.append(threading.get_ident())
            self.assertTrue(heartbeat.wait(.5), 'GUI heartbeat blocked by pixel preparation')
            return original(processor, *args, **kwargs)

        QTimer.singleShot(30, heartbeat.set)
        with patch.object(ImageGeometryProcessor, 'prepare', prepare), \
             patch.object(self.window.image_processing, 'commit') as commit, \
             patch('labelimg.image_tools.ui.controller.localized_warning') as warning:
            self.assertTrue(self.window.quick_transform_current_image('rotate-clockwise'))
            warning.assert_not_called()
            commit.assert_called_once()
        self.assertTrue(observed)
        self.assertTrue(all(thread != ui_thread for thread in observed))

    def test_committed_pixel_refresh_decodes_away_from_gui_without_cancel(self):
        ui_thread = threading.get_ident()
        heartbeat = threading.Event()
        from labelimg.image_tools.ui import controller
        original = controller.read
        def decode(*args):
            self.assertNotEqual(threading.get_ident(), ui_thread)
            self.assertTrue(heartbeat.wait(.5))
            return original(*args)
        QTimer.singleShot(20, heartbeat.set)
        with patch.object(controller, 'read', side_effect=decode):
            self.assertTrue(self.window._refresh_current_image_pixels((self.path,)))

    def test_committed_projection_ignores_escape_until_worker_finishes(self):
        from labelimg.image_tools.ui.preparation import run_preparation
        completed = threading.Event()
        def reject_progress():
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QProgressDialog):
                    QTest.keyClick(widget, Qt.Key_Escape)
                    widget.close()
            completed.set()
        QTimer.singleShot(20, reject_progress)
        result = run_preparation(lambda cancelled: (completed.wait(.5), 42)[1],
                                 self.window, cancellable=False)
        self.assertEqual(result, 42)

    def test_cancel_does_not_commit_or_change_source(self):
        release = threading.Event()
        original = ImageGeometryProcessor.prepare
        before = Path(self.path).read_bytes()

        def prepare(processor, *args, **kwargs):
            release.wait(.5)
            return original(processor, *args, **kwargs)

        def cancel():
            for dialog in self.window.findChildren(QProgressDialog):
                dialog.cancel()
            release.set()

        QTimer.singleShot(30, cancel)
        with patch.object(ImageGeometryProcessor, 'prepare', prepare), \
             patch.object(self.window.image_processing, 'commit') as commit:
            self.assertFalse(self.window.quick_transform_current_image('rotate-clockwise'))
            commit.assert_not_called()
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_cancelled_codec_finishes_before_another_preparation_allocates_pixels(self):
        release = threading.Event()
        first_started, second_started = threading.Event(), threading.Event()
        observed = []

        def first(cancelled):
            first_started.set()
            release.wait(2)

        def cancel():
            for dialog in self.window.findChildren(QProgressDialog):
                dialog.cancel()

        QTimer.singleShot(30, cancel)
        with self.assertRaises(CancelledError):
            self.window._run_image_preparation(first)
        self.assertTrue(first_started.is_set())

        def release_first():
            observed.append(not second_started.is_set())
            release.set()

        def second(cancelled):
            second_started.set()
            return True

        QTimer.singleShot(50, release_first)
        try:
            self.assertTrue(self.window._run_image_preparation(second))
        finally:
            release.set()
        self.assertEqual(observed, [True])
