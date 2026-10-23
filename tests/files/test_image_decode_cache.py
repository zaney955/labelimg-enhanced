import os
import tempfile
import time
import unittest
import threading
from concurrent.futures import Future
from unittest.mock import patch

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

    def test_default_budget_supports_large_neighbors_and_respects_available_memory(self):
        for available, expected in ((16 * 1024**3, 1024 * 1024**2),
                                    (1024**3, 128 * 1024**2),
                                    (None, 256 * 1024**2)):
            with patch('labelimg.files.ui.image_decode_cache._available_memory_bytes',
                       return_value=available):
                cache = DecodedImageCache()
                try:
                    self.assertEqual(cache._max_bytes, expected)
                finally:
                    cache.shutdown()

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

    def test_oversized_image_does_not_evict_usable_cached_neighbors(self):
        path, image = self._image('small.png', 'red')
        self.cache.put(path, image)
        large_path = os.path.join(self.temporary.name, 'large.png')
        large = QImage(200, 200, QImage.Format_RGB32)
        large.fill(QColor('blue'))
        large.save(large_path)
        self.cache.put(large_path, large)
        self.assertIsNotNone(self.cache.get(path))
        self.assertIsNone(self.cache.get(large_path))
        with patch('labelimg.files.ui.image_decode_cache._decode_image') as decode:
            self.cache.prefetch((large_path,))
            decode.assert_not_called()

    def test_demand_load_reuses_running_prefetch(self):
        path, image = self._image('shared.png', 'green')
        started, release = threading.Event(), threading.Event()
        from labelimg.files.ui.image_decode_cache import _decode_image

        def decode(*args):
            started.set()
            release.wait(1)
            return _decode_image(*args)

        with patch('labelimg.files.ui.image_decode_cache._decode_image', side_effect=decode) as calls:
            try:
                self.cache.prefetch((path,))
                self.assertTrue(started.wait(1))
            finally:
                release.set()
            loaded = self.cache.load(path)
            self.assertEqual(loaded.size(), image.size())
            self.assertEqual(loaded.pixelColor(0, 0), image.pixelColor(0, 0))
            self.assertEqual(calls.call_count, 1)

    def test_prefetch_cancelled_during_demand_handoff_retries_decode(self):
        class CancelOnResult(Future):
            def result(self, timeout=None):
                self.cancel()
                return super().result(timeout)
        path, image = self._image('cancel-handoff.png', 'green')
        from labelimg.files.ui.image_decode_cache import _path_key
        self.cache._jobs[_path_key(path)] = CancelOnResult()
        loaded = self.cache.load(path)
        self.assertEqual(loaded.pixelColor(0, 0), image.pixelColor(0, 0))

    def test_obsolete_prefetch_does_not_displace_current_neighbors(self):
        path, _image = self._image('obsolete.png', 'blue')
        started, release = threading.Event(), threading.Event()
        from labelimg.files.ui.image_decode_cache import _decode_image
        def decode(*args):
            started.set()
            release.wait(1)
            return _decode_image(*args)
        with patch('labelimg.files.ui.image_decode_cache._decode_image', side_effect=decode):
            try:
                self.cache.prefetch((path,))
                self.assertTrue(started.wait(1))
                self.cache.prefetch(())
            finally:
                release.set()
            self.cache._executor.shutdown(wait=True)
        self.assertIsNone(self.cache.get(path))


if __name__ == "__main__":
    unittest.main()
