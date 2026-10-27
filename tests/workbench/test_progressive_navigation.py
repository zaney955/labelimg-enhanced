"""Original-coordinate editing while navigation displays reduced pixels."""
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import QEvent, QPointF, QSize, Qt
from PyQt5.QtGui import QColor, QImage, QKeyEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from labelimg.canvas.shape import Shape
from labelimg.workbench.bootstrap import WorkbenchLaunchOptions, create_workbench


class ProgressiveNavigationTest(unittest.TestCase):
    image_format = 'JPEG'
    image_extension = '.jpg'
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, LABELIMG_CONFIG_DIR=self.temp.name)
        self.env.start()
        directory = Path(self.temp.name, 'images'); directory.mkdir()
        labels = Path(self.temp.name, 'labels'); labels.mkdir()
        classes = Path(self.temp.name, 'classes.txt'); classes.write_text('object\n')
        self.paths = [str(directory / f'{index}{self.image_extension}') for index in range(4)]
        image = QImage(6000, 4000, QImage.Format_RGB32); image.fill(QColor('red'))
        self.assertTrue(image.save(self.paths[0], self.image_format))
        for path in self.paths[1:]:
            shutil.copyfile(self.paths[0], path)
        self.window = create_workbench(WorkbenchLaunchOptions(
            class_file=str(classes), save_dir=str(labels)))
        self.window.resize(1000, 750)
        self.window.show()
        self.window.import_dir_images(str(directory))
        self.window.stop_directory_load()
        self.window._cancel_image_refinement()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.window.activateWindow(); self.window.canvas.setFocus()
        self.app.processEvents()
        self.assertTrue(self.window._has_image_preview())

    def tearDown(self):
        self.window.shutdown_image_decode_cache()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.env.stop()
        self.temp.cleanup()

    def wait_until(self, condition):
        deadline = time.monotonic() + 4
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(.005)
        self.assertTrue(condition())

    def add_box(self):
        shape = Shape(label='object')
        for point in ((3000, 2000), (5000, 2000), (5000, 3500), (3000, 3500)):
            shape.add_point(QPointF(*point))
        shape.close()
        self.window.canvas.load_shapes([shape]); self.window.add_label(shape)
        self.window.set_dirty()
        return shape

    def test_immediate_autosave_from_preview_uses_source_geometry(self):
        self.add_box()
        with patch.object(self.window, '_ensure_full_image', side_effect=AssertionError('save decoded full image')):
            self.window.open_next_image()
            self.wait_until(lambda: self.window.file_path == self.paths[1])
        root = ElementTree.parse(Path(self.temp.name, 'labels', '0.xml')).getroot()
        self.assertEqual(root.findtext('size/width'), '6000')
        self.assertEqual(root.findtext('size/height'), '4000')
        self.assertEqual(root.findtext('object/bndbox/xmax'), '5000')
        self.assertEqual(root.findtext('object/bndbox/ymax'), '3500')
        self.assertFalse(self.window.annotation_persistence.conflicts)

    def test_refinement_preserves_dirty_boxes_zoom_selection_and_revision(self):
        self.window.auto_saving.setChecked(False)
        shape = self.add_box()
        self.window.canvas.select_shape(shape)
        with patch.object(self.window, '_start_image_refinement'):
            self.window.set_zoom(30)
            self.app.processEvents()
        from labelimg.image_tools.application.display_adjustment import DisplayAdjustmentValues
        adjustment = DisplayAdjustmentValues(15, 20)
        completed_adjustments = []
        self.window.display_adjustment_controller._bridge.completed.connect(
            lambda request, _image: completed_adjustments.append(request.kind))
        self.window.display_adjustment_controller.set_current(adjustment)
        self.wait_until(lambda: 'full' in completed_adjustments)
        self.window.scroll_bars[Qt.Horizontal].setValue(120)
        self.window.scroll_bars[Qt.Vertical].setValue(80)
        scroll = {key: bar.value() for key, bar in self.window.scroll_bars.items()}
        revision = self.window.annotation_editing.view.revision_id
        zoom = self.window.zoom_widget.value()
        self.window._start_image_refinement()
        self.wait_until(lambda: not self.window._has_image_preview())
        self.assertEqual(self.window.image.size(), QSize(6000, 4000))
        self.assertEqual(self.window.canvas.pixmap_size, QSize(6000, 4000))
        self.assertEqual(self.window.canvas.shapes, [shape])
        self.assertEqual(self.window.canvas.selection_snapshot.active, shape)
        self.assertEqual(self.window.annotation_editing.view.revision_id, revision)
        self.assertEqual(self.window.zoom_widget.value(), zoom)
        self.assertEqual({key: bar.value() for key, bar in self.window.scroll_bars.items()}, scroll)
        self.assertEqual(self.window.display_adjustment_controller.session.effective(self.window.file_path), adjustment)
        self.assertTrue(self.window.dirty)

    def test_taps_do_not_start_full_decodes_until_navigation_stops(self):
        cache = self.window._ensure_image_decode_cache()
        with patch.object(cache, 'load_full', wraps=cache.load_full) as full:
            for index in range(10):
                key, text = (Qt.Key_D, 'd') if index % 2 == 0 else (Qt.Key_A, 'a')
                QApplication.sendEvent(self.window.canvas, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text))
                QApplication.sendEvent(self.window.canvas, QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier, text))
                QTest.qWait(60)
            self.assertEqual(full.call_count, 0)
            self.wait_until(lambda: not self.window._has_image_preview())
            self.assertEqual(full.call_count, 1)

    def test_late_refinement_cannot_replace_new_image(self):
        cache = self.window._ensure_image_decode_cache()
        started, release = threading.Event(), threading.Event()
        original = cache.load_full
        def blocked(path, expected):
            started.set(); release.wait(3)
            return original(path, expected)
        with patch.object(cache, 'load_full', side_effect=blocked):
            try:
                self.window._start_image_refinement()
                self.assertTrue(started.wait(1))
                self.window.open_next_image()
                self.wait_until(lambda: self.window.file_path == self.paths[1])
                self.window._cancel_image_refinement()
            finally:
                release.set()
            self.wait_until(lambda: not self.window._refinement_loader.busy)
            self.app.processEvents()
        self.assertEqual(self.window.file_path, self.paths[1])
        self.assertTrue(self.window._has_image_preview())

    def test_crop_preview_uses_original_coordinate_space(self):
        self.assertTrue(self.window.enter_crop_mode())
        self.assertEqual(self.window.canvas.pixmap_size, QSize(6000, 4000))
        self.assertTrue(self.window._has_image_preview())
        self.window.cancel_crop()


class PngProgressiveNavigationTest(ProgressiveNavigationTest):
    image_format = 'PNG'
    image_extension = '.png'


if __name__ == '__main__':
    unittest.main()
