import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor, QImage

from labelimg.files.ui.image_decode_cache import DecodedImageCache


class DecodedImageCacheTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.cache = DecodedImageCache(max_bytes=64 * 1024, workers=1)

    def tearDown(self):
        self.cache.shutdown()
        self.temporary.cleanup()

    def _image(self, name, color):
        path = os.path.join(self.temporary.name, name)
        image = QImage(40, 30, QImage.Format_RGBA8888)
        image.fill(QColor(color))
        self.assertTrue(image.save(path))
        return path, image

    def test_put_get_and_source_change_invalidation(self):
        path, image = self._image("cached.png", "red")
        self.assertTrue(self.cache.put(path, image))
        self.assertEqual(self.cache.get(path).pixelColor(0, 0), QColor("red"))

        replacement = QImage(40, 30, QImage.Format_RGBA8888)
        replacement.fill(QColor("blue"))
        time.sleep(0.002)
        self.assertTrue(replacement.save(path))

        self.assertIsNone(self.cache.get(path))

    def test_prefetch_decodes_without_ui_thread_projection(self):
        path, _image = self._image("prefetched.png", "green")
        self.cache.prefetch((path,))

        deadline = time.monotonic() + 2.0
        cached = None
        while cached is None and time.monotonic() < deadline:
            cached = self.cache.get(path)
            time.sleep(0.005)

        self.assertIsNotNone(cached)
        self.assertEqual(cached.pixelColor(0, 0), QColor("green"))


if __name__ == "__main__":
    unittest.main()
