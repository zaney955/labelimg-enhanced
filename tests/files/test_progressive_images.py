import os
import tempfile
import unittest
import time
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtGui import QColor, QImage
from labelimg.annotations import fingerprint_image
from labelimg.files.ui.progressive_images import NavigationImageCache
from labelimg.annotations.infrastructure.document import AnnotationDocument
from labelimg.annotations import AnnotationFormat


class ProgressiveImagesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name, 'large.jpg'))
        image = QImage(6000, 4000, QImage.Format_RGB32)
        image.fill(QColor('red'))
        self.assertTrue(image.save(self.path, 'JPEG'))
        self.cache = NavigationImageCache(fingerprint_for=fingerprint_image,
                                          preview_size=(800, 600))

    def tearDown(self):
        self.cache.shutdown()
        self.temp.cleanup()

    def test_preview_keeps_original_dimensions_for_voc_and_yolo(self):
        preview = self.cache.load(self.path)
        self.assertLess(preview.width(), 6000)
        info = self.cache.image_metadata(self.path, preview)
        self.assertEqual((info.width(), info.height()), (6000, 4000))
        document = AnnotationDocument(self.path, info)
        target = str(Path(self.temp.name, 'large.xml'))
        document.save(target, AnnotationFormat.PASCAL_VOC)
        from xml.etree import ElementTree
        root = ElementTree.parse(target).getroot()
        self.assertEqual(root.findtext('size/width'), '6000')
        self.assertEqual(root.findtext('size/height'), '4000')
        Path(self.temp.name, 'classes.txt').write_text('object\n')
        target = Path(self.temp.name, 'large.txt')
        target.write_text('0 0.5 0.5 0.5 0.5\n')
        loaded = AnnotationDocument.load(str(target), self.path, info)
        self.assertEqual(loaded.boxes[0].points, ((1500, 1000), (4500, 1000),
                                                (4500, 3000), (1500, 3000)))

    def test_refinement_is_bound_to_the_preview_source(self):
        preview = self.cache.load(self.path)
        expected = self.cache.cached_fingerprint(self.path, preview)
        full = self.cache.load_full(self.path, expected)
        self.assertEqual((full.width(), full.height()), (6000, 4000))
        self.assertEqual(self.cache.cached_fingerprint(self.path, full), expected)
        self.assertEqual(self.cache.get(self.path).size(), full.size())
        replacement = QImage(6000, 4000, QImage.Format_RGB32)
        replacement.fill(QColor('blue'))
        replacement.save(self.path, 'JPEG')
        with self.assertRaises(OSError):
            self.cache.load_full(self.path, expected)

    def test_invalidated_pixels_cannot_be_rebound_after_replacement(self):
        preview = self.cache.load(self.path)
        expected = self.cache.cached_fingerprint(self.path, preview)
        full = self.cache.load_full(self.path, expected)
        self.cache.invalidate((self.path,))
        self.assertFalse(self.cache.put(self.path, preview))
        self.assertFalse(self.cache.put(self.path, full))

    def test_full_pixels_from_changed_source_are_rejected_even_before_invalidation(self):
        preview = self.cache.load(self.path)
        full = self.cache.load_full(self.path, self.cache.cached_fingerprint(self.path, preview))
        replacement = QImage(6000, 4000, QImage.Format_RGB32)
        replacement.fill(QColor('blue')); replacement.save(self.path, 'JPEG')
        self.assertFalse(self.cache.put(self.path, full))

    def test_exif_rotated_preview_preserves_display_oriented_source_size(self):
        from PIL import Image
        path = str(Path(self.temp.name, 'rotated.jpg'))
        image = Image.new('RGB', (6000, 4000), 'blue')
        exif = Image.Exif(); exif[274] = 6
        image.save(path, exif=exif)
        preview = self.cache.load(path)
        info = self.cache.image_metadata(path, preview)
        self.assertEqual((info.width(), info.height()), (4000, 6000))
        self.assertLess(preview.width(), preview.height())
        full = self.cache.load_full(path, self.cache.cached_fingerprint(path, preview))
        self.assertEqual((full.width(), full.height()), (4000, 6000))

    def test_background_verification_of_preview_uses_original_dimensions(self):
        self.cache._verification_interval = 0
        with patch('labelimg.files.ui.image_decode_cache._source_token', return_value=('same',)):
            preview = self.cache.load(self.path)
            self.cache.get(self.path)
            deadline = time.monotonic() + 2
            while self.cache._verification_jobs and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertIsNotNone(self.cache.get(self.path))
            replacement = QImage(6000, 4000, QImage.Format_RGB32)
            replacement.fill(QColor('blue')); replacement.save(self.path, 'JPEG')
            deadline = time.monotonic() + 2
            while self.cache.get(self.path) is not None and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertIsNone(self.cache.get(self.path))
            self.assertFalse(self.cache.put(self.path, preview))
            latest = self.cache.load(self.path)
            self.assertGreater(latest.pixelColor(0, 0).blue(), 240)
            self.assertEqual(self.cache.image_metadata(self.path, latest).width(), 6000)

    def test_snapshot_pixels_cannot_be_paired_with_a_later_file_fingerprint(self):
        original = self.cache._fingerprint_for
        def replaced(path, dimensions):
            replacement = QImage(6000, 4000, QImage.Format_RGB32)
            replacement.fill(QColor('blue')); replacement.save(path, 'JPEG')
            return original(path, dimensions)
        with patch('labelimg.files.ui.image_decode_cache._source_token', return_value=('same',)), \
             patch.object(self.cache, '_fingerprint_for', side_effect=replaced):
            with self.assertRaises(OSError):
                self.cache.load(self.path)

    def test_bounded_grayscale_scan_checks_the_last_row(self):
        from labelimg.files.ui.image_decode_cache import _image_is_grayscale
        image = QImage(5000, 1000, QImage.Format_RGB32)
        image.fill(QColor('gray'))
        self.assertTrue(_image_is_grayscale(image))
        image.setPixelColor(4999, 999, QColor('blue'))
        self.assertFalse(_image_is_grayscale(image))

    def test_two_preview_sizes_retain_their_own_original_geometry(self):
        self.cache._max_bytes = 1  # Force re-decode while an earlier result is held.
        first = self.cache.load(self.path)
        self.cache.preview_size = (2200, 1600)
        second = self.cache.load(self.path)
        self.assertNotEqual(first.size(), second.size())
        self.assertTrue(self.cache.put(self.path, first))
        self.assertEqual(self.cache.image_metadata(self.path, first).width(), 6000)
        self.assertEqual(self.cache.cached_fingerprint(self.path, first).dimensions, (6000, 4000))


if __name__ == '__main__':
    unittest.main()
